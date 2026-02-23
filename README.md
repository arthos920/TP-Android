"""
Jira -> LLM -> Appium MCP (HTTP Stream) -> Appium Server (host) -> Android devices

Changes vs your "mobile-mcp" version:
- Uses Appium MCP over HTTP Stream (no stdio client).
- Devices are provided via DEVICE_1 / DEVICE_2 variables (you fill them).
- Keeps your ReAct loop + Jira MCP flow.
- Adds a "tool mapping" layer because Appium MCP tool names differ from mobile-mcp.

IMPORTANT:
1) Appium MCP tool names are NOT guaranteed to match the placeholders below.
2) Run once with PRINT_APPIUM_TOOLS=1 to print all tools and adjust TOOLMAP accordingly.
3) Appium Server must be reachable from the MCP container:
   - If MCP runs in Docker on Windows host, Appium URL from container is:
     http://host.docker.internal:4723
"""

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
from mcp.client.streamable_http import streamable_http_client

# =============================================================================
# CONFIG
# =============================================================================

# Jira MCP
JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")
TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-2140")

# Appium MCP (HTTP Stream endpoint)
# Example (your Docker): http://localhost:3000/sse
APPIUM_MCP_URL = os.getenv("APPIUM_MCP_URL", "http://localhost:3000/sse")

# Appium Server URL (where Appium v3 is running)
# If MCP is in Docker and Appium is on Windows host, use:
# http://host.docker.internal:4723
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")

# Devices (YOU fill these)
DEVICE_1 = os.getenv("DEVICE_1", "").strip()
DEVICE_2 = os.getenv("DEVICE_2", "").strip()

# App packages (optional)
GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", GLOBAL_PACKAGE).strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", GLOBAL_PACKAGE).strip()

# LLM
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Proxy (optional)
PROXY_URL = os.getenv("PROXY_URL", "")

# Limits
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# ReAct loop limits
MAX_TURNS_PER_DRIVER = int(os.getenv("MAX_TURNS_PER_DRIVER", "30"))
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "90"))
TOOL_ATTEMPTS = int(os.getenv("TOOL_ATTEMPTS", "3"))
TOOL_BACKOFF_BASE_S = float(os.getenv("TOOL_BACKOFF_BASE_S", "0.6"))

# Debug: print tools and exit
PRINT_APPIUM_TOOLS = os.getenv("PRINT_APPIUM_TOOLS", "0").strip() == "1"

# =============================================================================
# TOOL MAPPING (EDIT THIS AFTER YOU PRINT TOOLS)
# =============================================================================
# Appium MCP tool names will differ from "mobile-mcp".
# Run with PRINT_APPIUM_TOOLS=1 to see names & schemas, then map them here.
TOOLMAP: Dict[str, str] = {
    # Sessions
    "create_session": "create_session",  # <-- likely exists
    "delete_session": "delete_session",  # <-- likely exists

    # App lifecycle
    "activate_app": "activate_app",      # sometimes "activate_app" or "activateApp"
    "terminate_app": "terminate_app",    # sometimes "terminate_app"

    # UI/Screenshot/Source
    "screenshot": "take_screenshot",     # sometimes "screenshot" or "get_screenshot"
    "page_source": "get_page_source",    # sometimes "get_page_source" or "source"

    # Input/actions
    "tap": "tap",                        # sometimes "tap" / "click" / "tap_coordinates"
    "type": "type_keys",                 # sometimes "type" / "send_keys"
    "press_key": "press_button",         # sometimes "press_button" / "press_keycode"
    "swipe": "swipe",                    # sometimes "swipe" / "perform_swipe"
}

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
# MCP WRAPPER (HTTP Stream)
# =============================================================================

class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(streamable_http_client(self.url))
        if isinstance(transport, tuple) and len(transport) >= 2:
            read_stream, write_stream = transport[0], transport[1]
        elif hasattr(transport, "read_stream") and hasattr(transport, "write_stream"):
            read_stream, write_stream = transport.read_stream, transport.write_stream
        elif hasattr(transport, "streams") and len(transport.streams) >= 2:
            read_stream, write_stream = transport.streams[0], transport.streams[1]
        else:
            raise TypeError(f"Unknown transport from streamable_http_client: {type(transport)}")
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
# SCHEMA HELPERS
# =============================================================================

def schema_from_mcp_tool(t: Any) -> Dict[str, Any]:
    schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {"type": "object"}
    if not isinstance(schema, dict):
        schema = {"type": "object"}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    return schema

def build_schema_by_name(mcp_tools: List[Any]) -> Dict[str, Dict[str, Any]]:
    return {t.name: schema_from_mcp_tool(t) for t in mcp_tools}

# =============================================================================
# SAFE CALLS (generic)
# =============================================================================

def is_transient_error(text: str) -> bool:
    t = text.lower()
    return any(
        s in t for s in [
            "timeout",
            "timed out",
            "temporar",
            "connection",
            "reset",
            "unavailable",
            "try again",
            "internal",
            "server error",
            "mcp error",
        ]
    )

async def mcp_call_raw(mcp: MCPRemoteHTTP, tool: str, args: Dict[str, Any]) -> str:
    result = await mcp.call_tool(tool, args)
    return mcp_result_to_text(result)

async def mcp_call_safe(
    mcp: MCPRemoteHTTP,
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
# APPium MCP helpers
# =============================================================================

def _tool(name: str) -> str:
    """Resolve logical tool name to actual MCP tool name (via TOOLMAP)."""
    return TOOLMAP.get(name, name)

async def appium_create_session(ctx: "DriverContext") -> Dict[str, Any]:
    """
    Create an Appium session through Appium MCP, targeting a remote Appium server.
    This assumes Appium MCP provides a tool named like TOOLMAP['create_session'].
    """
    # Minimal W3C caps for Android
    caps: Dict[str, Any] = {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": ctx.device_id,
        "appium:noReset": True,
    }

    # Some apps need this if you want to launch your app directly via caps.
    # If you want MCP to "activate_app" by package, keep caps minimal.
    # If you know appActivity, you can add appium:appPackage/appium:appActivity.

    payload = {
        # These field names may differ. Adjust after printing tool schema.
        "serverUrl": APPIUM_SERVER_URL,
        "capabilities": caps,
    }

    ok, text, used = await mcp_call_safe(ctx.mcp, _tool("create_session"), payload, timeout_s=120)
    if not ok:
        return {"ok": False, "error": text, "args": used}

    # Expect a JSON-ish response containing session id
    try:
        data = json.loads(text)
    except Exception:
        data = {"raw": text}

    return {"ok": True, "data": data, "args": used}

async def appium_delete_session(ctx: "DriverContext") -> None:
    if not ctx.session_id:
        return
    payload = {
        "sessionId": ctx.session_id,
        "serverUrl": APPIUM_SERVER_URL,
    }
    await mcp_call_safe(ctx.mcp, _tool("delete_session"), payload, timeout_s=60)

def _extract_session_id(obj: Any) -> Optional[str]:
    """Try several common shapes."""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj if len(obj) >= 8 else None
    if isinstance(obj, dict):
        for k in ["sessionId", "session_id", "id", "value"]:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # sometimes nested
        if isinstance(obj.get("data"), dict):
            return _extract_session_id(obj["data"])
        if isinstance(obj.get("result"), dict):
            return _extract_session_id(obj["result"])
        if isinstance(obj.get("value"), dict):
            return _extract_session_id(obj["value"])
    return None

# =============================================================================
# UI PARSING: elements -> coords (kept as-is)
# NOTE: With Appium MCP, you might not get "elements list with bounds".
# You may need page source parsing instead. This wrapper remains, but might need changes.
# =============================================================================

def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None

def _extract_xy_from_obj(o: Any) -> Optional[Tuple[int, int]]:
    if not isinstance(o, dict):
        return None
    if isinstance(o.get("x"), (int, float)) and isinstance(o.get("y"), (int, float)):
        return int(o["x"]), int(o["y"])
    for k in ("center", "point", "tapPoint"):
        v = o.get(k)
        if isinstance(v, dict) and isinstance(v.get("x"), (int, float)) and isinstance(v.get("y"), (int, float)):
            return int(v["x"]), int(v["y"])
    b = o.get("bounds") or o.get("rect")
    if isinstance(b, dict):
        left = b.get("left")
        top = b.get("top")
        right = b.get("right")
        bottom = b.get("bottom")
        if all(isinstance(v, (int, float)) for v in (left, top, right, bottom)):
            return int((left + right) / 2), int((top + bottom) / 2)
    return None

def _element_texts(o: Any) -> List[str]:
    if not isinstance(o, dict):
        return []
    keys = ["text", "label", "name", "contentDescription", "accessibilityLabel", "accessibility_label", "value"]
    out: List[str] = []
    for k in keys:
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out

def find_click_target(elements_payload: Any, target: str) -> Optional[Dict[str, Any]]:
    if not target:
        return None
    target_l = target.lower()

    candidates: List[Dict[str, Any]] = []
    if isinstance(elements_payload, dict):
        for k in ("elements", "items", "result", "data"):
            v = elements_payload.get(k)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        candidates.append(it)
        if not candidates:
            candidates = [elements_payload]
    elif isinstance(elements_payload, list):
        for it in elements_payload:
            if isinstance(it, dict):
                candidates.append(it)

    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for el in candidates:
        texts = _element_texts(el)
        joined = " | ".join(texts).lower()
        if not joined:
            continue
        score = 0
        if target_l in joined:
            score += 50
        for t in texts:
            if t.lower() == target_l:
                score += 80
        xy = _extract_xy_from_obj(el)
        if xy is None:
            continue
        if score > 0 and (best is None or score > best[0]):
            el2 = dict(el)
            el2["_click_x"] = xy[0]
            el2["_click_y"] = xy[1]
            el2["_matched_texts"] = texts
            best = (score, el2)
    return best[1] if best else None

# =============================================================================
# TOOL WRAPPERS exposed to the MODEL
# =============================================================================

@dataclass
class DriverContext:
    name: str
    driver_index: int
    device_id: str
    package_name: str
    mcp: MCPRemoteHTTP
    schema_by_name: Dict[str, Dict[str, Any]]
    lock: asyncio.Lock
    session_id: Optional[str] = None

class Barrier:
    """A 2-party barrier: both drivers call sync_barrier() to proceed."""
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
    """
    Observe = page source (or element list) + screenshot.
    This implementation tries:
      - page_source tool
      - screenshot tool
    """
    async with ctx.lock:
        # Page source
        ok1, src, _ = await mcp_call_safe(
            ctx.mcp,
            _tool("page_source"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id},
            timeout_s=60,
            attempts=2,
        )

        # Screenshot
        ok2, ss, _ = await mcp_call_safe(
            ctx.mcp,
            _tool("screenshot"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id},
            timeout_s=60,
            attempts=2,
        )

        payload = {
            "driver": ctx.name,
            "device": ctx.device_id,
            "sessionId": ctx.session_id,
            "source_ok": ok1,
            "page_source_preview": (src[:2500] if isinstance(src, str) else str(src)[:2500]),
            "screenshot_preview": (ss[:800] if isinstance(ss, str) else str(ss)[:800]),
        }
        return json.dumps(payload, ensure_ascii=False)

async def tool_launch_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (set DRIVERx_PACKAGE or pass packageName)."}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)

        # Try activate app by package
        ok, out, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("activate_app"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "appId": pkg},
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps(
            {"ok": ok, "tool": "activate_app", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
            ensure_ascii=False,
        )

async def tool_terminate_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (set DRIVERx_PACKAGE or pass packageName)."}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)

        ok, out, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("terminate_app"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "appId": pkg},
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps(
            {"ok": ok, "tool": "terminate_app", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
            ensure_ascii=False,
        )

async def tool_ui_click(ctx: DriverContext, x: int, y: int) -> str:
    """
    Click by coordinates (reliable for a first version).
    Your previous version clicked by "target_text"; with Appium MCP, the element listing differs.
    If you want "click by text", we can add XML parsing of page_source later.
    """
    async with ctx.lock:
        pre = await tool_observe(ctx)

        ok_click, out_click, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("tap"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "x": int(x), "y": int(y)},
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps(
            {
                "ok": ok_click,
                "tool": "tap",
                "chosen": {"x": int(x), "y": int(y)},
                "args": args_used,
                "output": out_click,
                "pre": json.loads(pre),
                "post": json.loads(post),
            },
            ensure_ascii=False,
        )

async def tool_ui_type(ctx: DriverContext, text: str, submit: bool = False) -> str:
    async with ctx.lock:
        pre = await tool_observe(ctx)

        ok, out, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("type"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "text": text, "submit": bool(submit)},
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps({"ok": ok, "tool": "type", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)}, ensure_ascii=False)

async def tool_ui_swipe(ctx: DriverContext, direction: str = "down", distance: Optional[float] = None) -> str:
    d = (direction or "down").strip().lower()
    args: Dict[str, Any] = {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "direction": d}
    if isinstance(distance, (int, float)):
        args["distance"] = float(distance)

    async with ctx.lock:
        pre = await tool_observe(ctx)

        ok, out, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("swipe"),
            args,
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps({"ok": ok, "tool": "swipe", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)}, ensure_ascii=False)

async def tool_press_button(ctx: DriverContext, button: str) -> str:
    async with ctx.lock:
        pre = await tool_observe(ctx)

        ok, out, args_used = await mcp_call_safe(
            ctx.mcp,
            _tool("press_key"),
            {"serverUrl": APPIUM_SERVER_URL, "sessionId": ctx.session_id, "button": button},
            timeout_s=60,
            attempts=2,
        )

        post = await tool_observe(ctx)
        return json.dumps({"ok": ok, "tool": "press_button", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)}, ensure_ascii=False)

# =============================================================================
# OPENAI TOOL DEFINITIONS
# =============================================================================

def openai_tool(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }

def build_react_tools() -> List[Dict[str, Any]]:
    return [
        openai_tool("observe", "Observe current UI: page source + screenshot.", {"type": "object", "properties": {}, "required": []}),
        openai_tool("launch_app", "Launch/activate the app by packageName.", {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []}),
        openai_tool("terminate_app", "Terminate the app by packageName.", {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []}),
        # For Appium MCP version 1, we use coordinates (reliable). You can evolve to click-by-text later.
        openai_tool(
            "ui_click",
            "Tap by screen coordinates.",
            {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
        ),
        openai_tool(
            "ui_type",
            "Type text (assumes focus is on a field). Auto observe before/after.",
            {"type": "object", "properties": {"text": {"type": "string"}, "submit": {"type": "boolean"}}, "required": ["text"]},
        ),
        openai_tool(
            "ui_swipe",
            "Swipe screen. Auto observe before/after.",
            {"type": "object", "properties": {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "distance": {"type": "number"}}, "required": []},
        ),
        openai_tool("press_button", "Press a device button (back/home/etc).", {"type": "object", "properties": {"button": {"type": "string"}}, "required": ["button"]}),
        openai_tool("sync_barrier", "Synchronize with the other driver.", {"type": "object", "properties": {}, "required": []}),
        openai_tool(
            "finish",
            "Finish the test for this driver. Provide status and notes.",
            {"type": "object", "properties": {"status": {"type": "string", "enum": ["success", "failure", "blocked"]}, "notes": {"type": "string"}}, "required": ["status"]},
        ),
    ]

# =============================================================================
# REACT AGENT LOOP
# =============================================================================

SYSTEM_REACT = """
Tu es un agent QA mobile autonome en mode ReAct (observe → decide → act → observe).

Tu pilotes l'application Android en appelant UNIQUEMENT les tools fournis.

Règles:
- Observe souvent (observe).
- Pour cliquer: ui_click (coordonnées).
- Pour taper: ui_type.
- Pour scroller: ui_swipe.
- Utilise sync_barrier quand une étape doit être synchronisée avec l'autre driver (ex: appel entrant/sortant, action simultanée).
- Termine en appelant finish avec un status (success/failure/blocked) et des notes utiles.

Tu reçois:
- Résumé Jira
- Contexte driver (driver1/driver2, device, package)
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
            return await tool_ui_click(ctx, x=int(args.get("x", 0)), y=int(args.get("y", 0)))
        if tool_name == "ui_type":
            return await tool_ui_type(ctx, text=str(args.get("text", "")), submit=bool(args.get("submit", False)))
        if tool_name == "ui_swipe":
            return await tool_ui_swipe(ctx, direction=str(args.get("direction", "down")), distance=args.get("distance"))
        if tool_name == "press_button":
            return await tool_press_button(ctx, button=str(args.get("button", "back")))
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
                f"- package: {ctx.package_name or '[EMPTY]'}\n"
                f"- sessionId: {ctx.session_id}\n\n"
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
                    "sessionId": ctx.session_id,
                }
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": True, "final": final})})
                return final

            out = await _dispatch(tool_name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    final = {
        "status": "blocked",
        "notes": f"Max turns reached ({MAX_TURNS_PER_DRIVER}) without finish",
        "driver": ctx.name,
        "device": ctx.device_id,
        "sessionId": ctx.session_id,
    }
    return final

# =============================================================================
# JIRA SUMMARY (tool-driven)
# =============================================================================

SYSTEM_JIRA = f"""
Tu es un assistant Jira. Ticket cible: {TICKET_KEY}

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
            schema = schema_from_mcp_tool(t)
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": getattr(t, "description", "") or "",
                        "parameters": schema,
                    },
                }
            )

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
                tool_text = mcp_result_to_text(result)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_text})

            messages.append({"role": "user", "content": "Donne maintenant le résumé final STRICTEMENT au format demandé."})

        final = await safe_chat(
            async_client,
            model=MODEL,
            messages=messages,
            stream=False,
            temperature=0.2,
            max_tokens=1800,
        )
        return final.choices[0].message.content or ""

# =============================================================================
# HTTPX
# =============================================================================

def _make_httpx_async_client() -> httpx.AsyncClient:
    kwargs: Dict[str, Any] = dict(
        verify=False,
        follow_redirects=False,
        timeout=120.0,
    )
    if PROXY_URL:
        try:
            return httpx.AsyncClient(proxy=PROXY_URL, **kwargs)  # type: ignore[arg-type]
        except TypeError:
            return httpx.AsyncClient(proxies=PROXY_URL, **kwargs)  # type: ignore[arg-type]
    return httpx.AsyncClient(**kwargs)

# =============================================================================
# MAIN
# =============================================================================

async def _print_appium_tools_and_exit():
    async with MCPRemoteHTTP(APPIUM_MCP_URL) as probe:
        tools = await probe.list_tools()
        print("\n===== APPIUM MCP TOOLS =====\n")
        for t in tools:
            schema = schema_from_mcp_tool(t)
            print(f"- {t.name}")
            print(json.dumps(schema, ensure_ascii=False, indent=2)[:2000])
            print()
    raise SystemExit(0)

async def main():
    if PRINT_APPIUM_TOOLS:
        await _print_appium_tools_and_exit()

    if not DEVICE_1:
        raise SystemExit("DEVICE_1 is required (set env var DEVICE_1). Example: set DEVICE_1=R3CN30...")

    # If no DEVICE_2 provided, reuse DEVICE_1 (single device run)
    device1 = DEVICE_1
    device2 = DEVICE_2 or DEVICE_1

    async with _make_httpx_async_client() as http_client:
        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        # 1) Jira summary
        print("\n===== (1) JIRA: Fetch + Summary =====\n")
        jira_summary = await jira_fetch_and_summarize(async_client)
        print(jira_summary)

        # 2) Run 2 drivers in parallel (live ReAct)
        print("\n===== (2) APPIUM MCP: Create sessions =====\n")

        barrier = Barrier()

        async with MCPRemoteHTTP(APPIUM_MCP_URL) as mcp1, MCPRemoteHTTP(APPIUM_MCP_URL) as mcp2:
            tools1 = await mcp1.list_tools()
            tools2 = await mcp2.list_tools()
            schema1 = build_schema_by_name(tools1)
            schema2 = build_schema_by_name(tools2)

            ctx1 = DriverContext(
                name="driver1",
                driver_index=1,
                device_id=device1,
                package_name=DRIVER1_PACKAGE,
                mcp=mcp1,
                schema_by_name=schema1,
                lock=asyncio.Lock(),
            )
            ctx2 = DriverContext(
                name="driver2",
                driver_index=2,
                device_id=device2,
                package_name=DRIVER2_PACKAGE,
                mcp=mcp2,
                schema_by_name=schema2,
                lock=asyncio.Lock(),
            )

            # Create sessions
            s1 = await appium_create_session(ctx1)
            s2 = await appium_create_session(ctx2)

            if not s1.get("ok") or not s2.get("ok"):
                print("\n[ERROR] Failed to create session(s)")
                print(json.dumps({"driver1": s1, "driver2": s2}, ensure_ascii=False, indent=2))
                raise SystemExit(2)

            # Extract session ids
            sid1 = _extract_session_id(s1.get("data"))
            sid2 = _extract_session_id(s2.get("data"))
            ctx1.session_id = sid1
            ctx2.session_id = sid2

            if not ctx1.session_id or not ctx2.session_id:
                print("\n[ERROR] Could not extract sessionId(s) from create_session output.")
                print(json.dumps({"driver1": s1, "driver2": s2}, ensure_ascii=False, indent=2))
                raise SystemExit(3)

            print(f"[CTX] driver1 device={ctx1.device_id} sessionId={ctx1.session_id} package={ctx1.package_name or '[EMPTY]'}")
            print(f"[CTX] driver2 device={ctx2.device_id} sessionId={ctx2.session_id} package={ctx2.package_name or '[EMPTY]'}")

            print("\n===== (3) REACT LIVE (parallel drivers) =====\n")
            try:
                r1, r2 = await asyncio.gather(
                    run_react_driver(async_client, ctx1, barrier, jira_summary),
                    run_react_driver(async_client, ctx2, barrier, jira_summary),
                )
            finally:
                # Cleanup sessions
                await appium_delete_session(ctx1)
                await appium_delete_session(ctx2)

        # 4) Aggregate result
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

if __name__ == "__main__":
    asyncio.run(main())
