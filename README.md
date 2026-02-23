from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

# MCP
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client


# =============================================================================
# CONFIG
# =============================================================================

# Jira MCP (unchanged)
JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")
TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-2140")

# Appium MCP (SSE endpoint shown by your container logs)
APPIUM_MCP_SSE_URL = os.getenv("APPIUM_MCP_SSE_URL", "http://localhost:3000/sse")

# Remote Appium Server (running on host)
# In your offline machine, Appium is running on 4723
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")

# LLM
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Proxy (optional)
PROXY_URL = os.getenv("PROXY_URL", "")

# Devices (YOU fill these)
DEVICE_1_ID = os.getenv("DEVICE_1_ID", "").strip()
DEVICE_2_ID = os.getenv("DEVICE_2_ID", "").strip()

# App under test (Android package)
GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", GLOBAL_PACKAGE).strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", GLOBAL_PACKAGE).strip()

# Limits
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# ReAct loop limits
MAX_TURNS_PER_DRIVER = int(os.getenv("MAX_TURNS_PER_DRIVER", "30"))
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "60"))
TOOL_ATTEMPTS = int(os.getenv("TOOL_ATTEMPTS", "3"))
TOOL_BACKOFF_BASE_S = float(os.getenv("TOOL_BACKOFF_BASE_S", "0.6"))


# =============================================================================
# TEXT / TRUNCATION
# =============================================================================

def _strip_control_chars(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)

def truncate_text(text: str) -> str:
    text = _strip_control_chars(text)
    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED_LINES]..."
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "\n...[TRUNCATED_CHARS]..."
    return text

def mcp_result_to_text(result: Any) -> str:
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                t = getattr(item, "text", None)
                parts.append(t if t is not None else str(item))
        text = "\n".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, ensure_ascii=False)
        except Exception:
            text = str(content)
    return truncate_text(text)

async def safe_chat(async_client: AsyncOpenAI, **kwargs):
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            return await async_client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# =============================================================================
# MCP REMOTE: SSE (Appium MCP) + Streamable HTTP (Jira MCP)
# =============================================================================

class MCPRemoteSSE:
    def __init__(self, sse_url: str):
        self.sse_url = sse_url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteSSE":
        read_stream, write_stream = await self._stack.enter_async_context(sse_client(self.sse_url))
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session
        return (await self.session.list_tools()).tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session
        return await self.session.call_tool(name, args)

class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        read_stream, write_stream = await self._stack.enter_async_context(streamable_http_client(self.url))
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session
        return (await self.session.list_tools()).tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session
        return await self.session.call_tool(name, args)


# =============================================================================
# SAFE TOOL CALLS (retry)
# =============================================================================

def is_transient_error(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in [
        "timeout", "timed out", "temporar", "connection", "reset",
        "unavailable", "try again", "internal", "server error", "mcp error",
        "disconnected without sending a response",
    ])

async def mcp_call_raw(mcp: MCPRemoteSSE, tool: str, args: Dict[str, Any]) -> str:
    result = await mcp.call_tool(tool, args)
    return mcp_result_to_text(result)

async def mcp_call_safe(
    mcp: MCPRemoteSSE,
    tool: str,
    args: Optional[Dict[str, Any]],
    timeout_s: float = TOOL_TIMEOUT_S,
    attempts: int = TOOL_ATTEMPTS,
    backoff_base_s: float = TOOL_BACKOFF_BASE_S,
) -> Tuple[bool, str, Dict[str, Any]]:
    if args is None or not isinstance(args, dict):
        args = {}
    call_args = dict(args)

    last_text = ""
    for attempt in range(1, attempts + 1):
        try:
            text = await asyncio.wait_for(mcp_call_raw(mcp, tool, call_args), timeout=timeout_s)
            last_text = text
            if "invalid arguments" in text.lower() or "invalid_type" in text.lower():
                return False, text, call_args
            return True, text, call_args
        except Exception as e:
            last_text = f"[TOOL_ERROR] {tool}: {repr(e)}"
            if attempt >= attempts:
                break
            await asyncio.sleep(backoff_base_s * attempt)
            if not is_transient_error(last_text):
                break
    return False, last_text, call_args


# =============================================================================
# APPium-MCP: session + element helpers
# =============================================================================

def build_android_caps(udid: str, app_package: str = "") -> Dict[str, Any]:
    caps: Dict[str, Any] = {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": udid,
        # optional but often helps stability
        "appium:newCommandTimeout": 300,
    }
    # If you want to start a specific app:
    if app_package:
        # depending on your app you might also need appActivity
        caps["appium:appPackage"] = app_package
    return caps

async def appium_setup_and_create_session(mcp: MCPRemoteSSE, udid: str, app_package: str) -> None:
    # 1) REQUIRED: select_platform
    await mcp_call_safe(mcp, "select_platform", {"platform": "Android"})

    # 2) create_session (forward to remote Appium server)
    # We try a couple of likely argument shapes because schema is not shown.
    caps = build_android_caps(udid, app_package)
    candidates = [
        {"mode": "android", "serverUrl": APPIUM_SERVER_URL, "capabilities": caps},
        {"platform": "Android", "serverUrl": APPIUM_SERVER_URL, "capabilities": caps},
        {"serverUrl": APPIUM_SERVER_URL, "capabilities": caps},
        {"remoteServerUrl": APPIUM_SERVER_URL, "capabilities": caps},
    ]

    last = None
    for c in candidates:
        ok, out, used = await mcp_call_safe(mcp, "create_session", c, timeout_s=90, attempts=2)
        last = (ok, out, used)
        if ok:
            return

    raise RuntimeError(f"create_session failed. Last response={last}")

async def appium_delete_session(mcp: MCPRemoteSSE) -> None:
    await mcp_call_safe(mcp, "delete_session", {}, timeout_s=60, attempts=2)

async def appium_find_element(mcp: MCPRemoteSSE, strategy: str, selector: str) -> Tuple[bool, str]:
    """
    Returns (ok, element_id_or_payload).
    We try different likely arg schemas.
    """
    candidates = [
        {"using": strategy, "value": selector},
        {"strategy": strategy, "selector": selector},
        {"locatorStrategy": strategy, "locator": selector},
        {"by": strategy, "locator": selector},
    ]
    last_text = ""
    for c in candidates:
        ok, out, _ = await mcp_call_safe(mcp, "appium_find_element", c, timeout_s=45, attempts=2)
        last_text = out
        if ok:
            return True, out
    return False, last_text

def extract_element_id(find_element_output: str) -> Optional[str]:
    """
    appium-mcp might return JSON containing an element UUID.
    We try to parse common fields.
    """
    try:
        data = json.loads(find_element_output)
        if isinstance(data, dict):
            for k in ["elementId", "element_id", "id", "uuid", "ELEMENT"]:
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # nested
            if "value" in data and isinstance(data["value"], dict):
                for k in ["elementId", "element_id", "id", "uuid", "ELEMENT"]:
                    v = data["value"].get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    except Exception:
        pass

    # fallback regex for uuid-ish
    m = re.search(r"\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b", find_element_output, re.I)
    if m:
        return m.group(1)
    return None

async def appium_click(mcp: MCPRemoteSSE, element_id: str) -> Tuple[bool, str]:
    candidates = [
        {"elementId": element_id},
        {"element_id": element_id},
        {"id": element_id},
        {"uuid": element_id},
    ]
    last_text = ""
    for c in candidates:
        ok, out, _ = await mcp_call_safe(mcp, "appium_click", c, timeout_s=45, attempts=2)
        last_text = out
        if ok:
            return True, out
    return False, last_text

async def appium_set_value(mcp: MCPRemoteSSE, element_id: str, text: str) -> Tuple[bool, str]:
    candidates = [
        {"elementId": element_id, "text": text},
        {"element_id": element_id, "text": text},
        {"id": element_id, "value": text},
        {"uuid": element_id, "text": text},
    ]
    last_text = ""
    for c in candidates:
        ok, out, _ = await mcp_call_safe(mcp, "appium_set_value", c, timeout_s=45, attempts=2)
        last_text = out
        if ok:
            return True, out
    return False, last_text


# =============================================================================
# WRAPPERS exposed to the MODEL
# =============================================================================

@dataclass
class DriverContext:
    name: str
    driver_index: int
    device_id: str
    package_name: str
    mcp: MCPRemoteSSE
    lock: asyncio.Lock

class Barrier:
    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._count = 0
        self._generation = 0

    async def wait(self, who: str) -> str:
        async with self._cond:
            gen = self._generation
            self._count += 1
            if self._count >= 2:
                self._count = 0
                self._generation += 1
                self._cond.notify_all()
                return f"[BARRIER] released generation={self._generation} (last={who})"
            while gen == self._generation:
                await self._cond.wait()
            return f"[BARRIER] released generation={self._generation} (waiter={who})"

async def tool_observe(ctx: DriverContext) -> str:
    async with ctx.lock:
        ok_src, src, _ = await mcp_call_safe(ctx.mcp, "appium_get_page_source", {}, timeout_s=60, attempts=2)
        ok_ss, ss, _ = await mcp_call_safe(ctx.mcp, "appium_screenshot", {}, timeout_s=60, attempts=2)

        return json.dumps({
            "driver": ctx.name,
            "device": ctx.device_id,
            "page_source_ok": ok_src,
            "screenshot_ok": ok_ss,
            "page_source": src[:6000],
            "screenshot": ss[:800],
        }, ensure_ascii=False)

async def tool_launch_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (DRIVERx_PACKAGE or packageName)"}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, used = await mcp_call_safe(ctx.mcp, "appium_activate_app", {"bundleId": pkg}, timeout_s=60, attempts=2)
        # some servers use packageName instead of bundleId for Android
        if not ok:
            ok, out, used = await mcp_call_safe(ctx.mcp, "appium_activate_app", {"packageName": pkg}, timeout_s=60, attempts=2)
        post = await tool_observe(ctx)

        return json.dumps({"ok": ok, "tool": "appium_activate_app", "args": used, "output": out, "pre": json.loads(pre), "post": json.loads(post)}, ensure_ascii=False)

async def tool_terminate_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (DRIVERx_PACKAGE or packageName)"}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, used = await mcp_call_safe(ctx.mcp, "appium_terminateApp", {"bundleId": pkg}, timeout_s=60, attempts=2)
        if not ok:
            ok, out, used = await mcp_call_safe(ctx.mcp, "appium_terminateApp", {"packageName": pkg}, timeout_s=60, attempts=2)
        post = await tool_observe(ctx)

        return json.dumps({"ok": ok, "tool": "appium_terminateApp", "args": used, "output": out, "pre": json.loads(pre), "post": json.loads(post)}, ensure_ascii=False)

async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    Find element by common heuristics:
    - accessibility id = target_text
    - id = target_text
    - xpath by @text or @content-desc
    then click.
    """
    if not target_text:
        return json.dumps({"ok": False, "error": "target_text is required"}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)

        locators = [
            ("accessibility id", target_text),
            ("id", target_text),
            ("xpath", f"//*[@text={json.dumps(target_text)}]"),
            ("xpath", f"//*[@content-desc={json.dumps(target_text)}]"),
            ("xpath", f"//*[contains(@text, {json.dumps(target_text)})]"),
            ("xpath", f"//*[contains(@content-desc, {json.dumps(target_text)})]"),
        ]

        last_find = ""
        for strat, sel in locators:
            ok_find, out = await appium_find_element(ctx.mcp, strat, sel)
            last_find = out
            if not ok_find:
                continue
            el_id = extract_element_id(out)
            if not el_id:
                continue
            ok_click, out_click = await appium_click(ctx.mcp, el_id)
            post = await tool_observe(ctx)
            return json.dumps({
                "ok": ok_click,
                "tool": "ui_click",
                "target_text": target_text,
                "strategy": strat,
                "selector": sel,
                "element_id": el_id,
                "find_output": out[:1200],
                "click_output": out_click[:1200],
                "pre": json.loads(pre),
                "post": json.loads(post),
            }, ensure_ascii=False)

        post = await tool_observe(ctx)
        return json.dumps({
            "ok": False,
            "tool": "ui_click",
            "target_text": target_text,
            "error": "Element not found with common locator heuristics",
            "last_find_output": last_find[:1500],
            "pre": json.loads(pre),
            "post": json.loads(post),
        }, ensure_ascii=False)

async def tool_ui_type(ctx: DriverContext, text: str, submit: bool = False) -> str:
    """
    Types into a focused field if possible.
    If not, you should click a field first, then ui_type.
    """
    async with ctx.lock:
        pre = await tool_observe(ctx)

        # simplest: set value on currently focused element is not always possible,
        # so we provide a basic approach: try a generic "focused" xpath.
        locators = [
            ("xpath", "//*[@focused='true']"),
            ("xpath", "//*[@focusable='true' and (@focused='true')]"),
        ]

        chosen_el = None
        last_find = ""
        for strat, sel in locators:
            ok_find, out = await appium_find_element(ctx.mcp, strat, sel)
            last_find = out
            if not ok_find:
                continue
            el_id = extract_element_id(out)
            if not el_id:
                continue
            chosen_el = el_id
            break

        if not chosen_el:
            post = await tool_observe(ctx)
            return json.dumps({
                "ok": False,
                "tool": "ui_type",
                "error": "No focused input found. Click an input first then ui_type.",
                "last_find_output": last_find[:1500],
                "pre": json.loads(pre),
                "post": json.loads(post),
            }, ensure_ascii=False)

        ok_set, out_set = await appium_set_value(ctx.mcp, chosen_el, text)
        post = await tool_observe(ctx)
        return json.dumps({
            "ok": ok_set,
            "tool": "ui_type",
            "text": text,
            "element_id": chosen_el,
            "set_value_output": out_set[:1200],
            "pre": json.loads(pre),
            "post": json.loads(post),
        }, ensure_ascii=False)

async def tool_ui_swipe(ctx: DriverContext, direction: str = "down", distance: Optional[float] = None) -> str:
    d = (direction or "down").strip().lower()
    args: Dict[str, Any] = {"direction": d}
    if isinstance(distance, (int, float)):
        args["distance"] = float(distance)

    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, used = await mcp_call_safe(ctx.mcp, "appium_scroll", args, timeout_s=60, attempts=2)
        if not ok:
            # fallback to swipe if scroll schema differs
            ok, out, used = await mcp_call_safe(ctx.mcp, "appium_swipe", args, timeout_s=60, attempts=2)
        post = await tool_observe(ctx)

        return json.dumps({
            "ok": ok,
            "tool": "ui_swipe",
            "args": used,
            "output": out[:1200],
            "pre": json.loads(pre),
            "post": json.loads(post),
        }, ensure_ascii=False)


# =============================================================================
# OPENAI TOOL DEFINITIONS for wrappers
# =============================================================================

def openai_tool(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}

def build_react_tools() -> List[Dict[str, Any]]:
    return [
        openai_tool("observe", "Observe current UI: page source + screenshot.", {"type": "object", "properties": {}, "required": []}),
        openai_tool("launch_app", "Activate/launch the app (uses package config if omitted).", {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []}),
        openai_tool("terminate_app", "Terminate the app (uses package config if omitted).", {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []}),
        openai_tool("ui_click", "Click UI element by text (heuristic locators).", {"type": "object", "properties": {"target_text": {"type": "string"}}, "required": ["target_text"]}),
        openai_tool("ui_type", "Type text into focused field (click field first if needed).", {"type": "object", "properties": {"text": {"type": "string"}, "submit": {"type": "boolean"}}, "required": ["text"]}),
        openai_tool("ui_swipe", "Scroll/swipe screen.", {"type": "object", "properties": {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "distance": {"type": "number"}}, "required": []}),
        openai_tool("sync_barrier", "Synchronize with the other driver.", {"type": "object", "properties": {}, "required": []}),
        openai_tool("finish", "Finish the test for this driver.", {"type": "object", "properties": {"status": {"type": "string", "enum": ["success", "failure", "blocked"]}, "notes": {"type": "string"}}, "required": ["status"]}),
    ]


# =============================================================================
# REACT LOOP
# =============================================================================

SYSTEM_REACT = """Tu es un agent QA mobile autonome en mode ReAct (observe → decide → act → observe).
Tu pilotes l'application Android en appelant UNIQUEMENT les tools fournis.

Règles:
- Pour cliquer un élément UI: utilise toujours ui_click.
- Pour taper: ui_type. Pour scroller: ui_swipe.
- Pour observer l'état: observe.
- Utilise sync_barrier quand une étape doit être synchronisée avec l'autre driver.
- Sois robuste: observe souvent, et si un élément n'est pas visible, fais ui_swipe puis observe et réessaie.
- Termine en appelant finish avec un status (success/failure/blocked).
"""

async def run_react_driver(async_client: AsyncOpenAI, ctx: DriverContext, barrier: Barrier, jira_summary: str) -> Dict[str, Any]:
    tools = build_react_tools()

    async def _dispatch(tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "observe":
            return await tool_observe(ctx)
        if tool_name == "launch_app":
            return await tool_launch_app(ctx, packageName=args.get("packageName"))
        if tool_name == "terminate_app":
            return await tool_terminate_app(ctx, packageName=args.get("packageName"))
        if tool_name == "ui_click":
            return await tool_ui_click(ctx, target_text=args.get("target_text", ""))
        if tool_name == "ui_type":
            return await tool_ui_type(ctx, text=args.get("text", ""), submit=bool(args.get("submit", False)))
        if tool_name == "ui_swipe":
            return await tool_ui_swipe(ctx, direction=args.get("direction", "down"), distance=args.get("distance"))
        if tool_name == "sync_barrier":
            return await barrier.wait(ctx.name)
        if tool_name == "finish":
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": f"Unknown tool {tool_name}"})

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_REACT},
        {
            "role": "user",
            "content": (
                f"Résumé Jira:\n{jira_summary}\n\n"
                f"Contexte:\n"
                f"- driver: {ctx.name}\n"
                f"- device: {ctx.device_id}\n"
                f"- package: {ctx.package_name or '[EMPTY]'}\n\n"
                f"Commence par observer, puis exécute le test."
            ),
        },
    ]

    messages.append({"role": "assistant", "content": "Je commence par observer l'UI."})
    obs0 = await tool_observe(ctx)
    messages.append({"role": "tool", "tool_call_id": "init_observe", "content": obs0})

    final: Dict[str, Any] = {"status": "blocked", "notes": "No finish called"}

    for turn in range(1, MAX_TURNS_PER_DRIVER + 1):
        resp = await safe_chat(
            async_client,
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
            temperature=0.2,
            max_tokens=1200,
        )
        msg = resp.choices[0].message
        messages.append({"role": "assistant", "content": msg.content or ""})

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            messages.append({"role": "user", "content": "Tu dois appeler un tool (observe/ui_click/ui_type/ui_swipe/...) ou finish."})
            continue

        for tc in tool_calls:
            tool_name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if tool_name == "finish":
                final = {
                    "status": args.get("status", "blocked"),
                    "notes": args.get("notes", ""),
                    "turn": turn,
                    "driver": ctx.name,
                    "device": ctx.device_id,
                }
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": True, "final": final})})
                return final

            out = await _dispatch(tool_name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    return {
        "status": "blocked",
        "notes": f"Max turns reached ({MAX_TURNS_PER_DRIVER}) without finish",
        "driver": ctx.name,
        "device": ctx.device_id,
    }


# =============================================================================
# JIRA SUMMARY (tool-driven)
# =============================================================================

SYSTEM_JIRA = f"""Tu es un assistant Jira. Ticket cible: {TICKET_KEY}
Tu es QA Automation. Résume un ticket Jira de façon actionnable.
Concentre-toi sur les critères d'acceptation / "Test Details" (souvent customfield_11504),
et tout ce qui ressemble à : plateforme, données d'entrée, étapes, résultats attendus.
Retourne STRICTEMENT ce format :
- Titre:
- Test Details(customfield_11504):
- Objectif:
- Plateforme:
- Données (inputs/valeurs):
- Résultats attendus:
"""

async def jira_fetch_and_summarize(async_client: AsyncOpenAI) -> str:
    async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
        tools = await jira_mcp.list_tools()
        openai_tools = []
        for t in tools:
            schema = getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}
            openai_tools.append({
                "type": "function",
                "function": {"name": t.name, "description": getattr(t, "description", "") or "", "parameters": schema},
            })

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_JIRA},
            {"role": "user", "content": f"Récupère le ticket {TICKET_KEY} via les tools Jira puis résume-le."},
        ]

        for _ in range(12):
            resp = await safe_chat(
                async_client,
                model=MODEL,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                stream=False,
                temperature=0.2,
                max_tokens=4000,
            )
            msg = resp.choices[0].message
            messages.append({"role": "assistant", "content": msg.content or ""})
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                break

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except Exception:
                    args = {}
                if not isinstance(args, dict):
                    args = {}

                result = await jira_mcp.call_tool(tool_name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": mcp_result_to_text(result)})

        messages.append({"role": "user", "content": "Donne maintenant le résumé final STRICTEMENT au format demandé."})
        final = await safe_chat(async_client, model=MODEL, messages=messages, stream=False, temperature=0.2, max_tokens=1800)
        return final.choices[0].message.content or ""


# =============================================================================
# HTTPX
# =============================================================================

def _make_httpx_async_client() -> httpx.AsyncClient:
    kwargs: Dict[str, Any] = dict(verify=False, follow_redirects=False, timeout=120.0)
    if PROXY_URL:
        try:
            return httpx.AsyncClient(proxy=PROXY_URL, **kwargs)  # type: ignore[arg-type]
        except TypeError:
            return httpx.AsyncClient(proxies=PROXY_URL, **kwargs)  # type: ignore[arg-type]
    return httpx.AsyncClient(**kwargs)


# =============================================================================
# MAIN
# =============================================================================

async def main():
    if not DEVICE_1_ID or not DEVICE_2_ID:
        raise RuntimeError("Set DEVICE_1_ID and DEVICE_2_ID env vars with your phone ids.")

    async with _make_httpx_async_client() as http_client:
        async_client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, http_client=http_client)

        # 1) Jira summary
        print("\n===== (1) JIRA: Fetch + Summary =====\n")
        jira_summary = await jira_fetch_and_summarize(async_client)
        print(jira_summary)

        # 2) Appium MCP sessions
        print("\n===== (2) APPIUM MCP: Create sessions =====\n")
        barrier = Barrier()

        async with MCPRemoteSSE(APPIUM_MCP_SSE_URL) as mcp1, MCPRemoteSSE(APPIUM_MCP_SSE_URL) as mcp2:
            # create session per driver
            await appium_setup_and_create_session(mcp1, DEVICE_1_ID, DRIVER1_PACKAGE)
            await appium_setup_and_create_session(mcp2, DEVICE_2_ID, DRIVER2_PACKAGE)

            ctx1 = DriverContext("driver1", 1, DEVICE_1_ID, DRIVER1_PACKAGE, mcp1, asyncio.Lock())
            ctx2 = DriverContext("driver2", 2, DEVICE_2_ID, DRIVER2_PACKAGE, mcp2, asyncio.Lock())

            try:
                print("\n===== (3) REACT LIVE (parallel drivers) =====\n")
                r1, r2 = await asyncio.gather(
                    run_react_driver(async_client, ctx1, barrier, jira_summary),
                    run_react_driver(async_client, ctx2, barrier, jira_summary),
                )

                print("\n===== (4) DRIVER RESULTS =====\n")
                print(json.dumps({"driver1": r1, "driver2": r2}, ensure_ascii=False, indent=2))

                statuses = [r1.get("status"), r2.get("status")]
                if "failure" in statuses:
                    overall = "failure"
                elif "blocked" in statuses:
                    overall = "blocked"
                else:
                    overall = "success"

                print("\n===== OVERALL =====\n")
                print(json.dumps({"result": overall, "details": {"driver1": r1, "driver2": r2}}, ensure_ascii=False, indent=2))
            finally:
                # always cleanup sessions
                await appium_delete_session(mcp1)
                await appium_delete_session(mcp2)


if __name__ == "__main__":
    asyncio.run(main())