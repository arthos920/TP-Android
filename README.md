from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable

import httpx
from openai import AsyncOpenAI

# MCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client


# =============================================================================
# CONFIG
# =============================================================================

# Jira MCP
JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")
TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-2140")

# Mobile MCP
MOBILE_MCP_COMMAND = os.getenv("MOBILE_MCP_COMMAND", "node")
MOBILE_MCP_ARGS = json.loads(
    os.getenv("MOBILE_MCP_ARGS_JSON", r'["C:/ads_mcp/mobile-mcp-main/lib/index.js"]')
)

# LLM
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Proxy (optional)
PROXY_URL = os.getenv("PROXY_URL", "")

# Packages per driver
GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", GLOBAL_PACKAGE).strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", GLOBAL_PACKAGE).strip()

# Optional device override
FORCE_DEVICE_DRIVER1 = os.getenv("FORCE_DEVICE_DRIVER1", "").strip()
FORCE_DEVICE_DRIVER2 = os.getenv("FORCE_DEVICE_DRIVER2", "").strip()

# Limits
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# ReAct loop limits
MAX_TURNS_PER_DRIVER = int(os.getenv("MAX_TURNS_PER_DRIVER", "30"))
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "60"))
TOOL_ATTEMPTS = int(os.getenv("TOOL_ATTEMPTS", "3"))
TOOL_BACKOFF_BASE_S = float(os.getenv("TOOL_BACKOFF_BASE_S", "0.6"))

DEVICE_KEYS = ["device", "device_id", "deviceId", "udid", "serial", "android_device_id"]


# =============================================================================
# TOOL WHITELIST (from your screenshots)
# =============================================================================

ALLOWED_MOBILE_TOOLS = [
    "mobile_list_available_devices",
    "mobile_list_apps",
    "mobile_launch_app",
    "mobile_terminate_app",
    "mobile_install_app",
    "mobile_uninstall_app",
    "mobile_get_screen_size",
    "mobile_click_on_screen_at_coordinates",
    "mobile_double_tap_on_screen",
    "mobile_long_press_on_screen_at_coordinates",
    "mobile_list_elements_on_screen",
    "mobile_press_button",
    "mobile_open_url",
    "mobile_swipe_on_screen",
    "mobile_type_keys",
    "mobile_save_screenshot",
    "mobile_take_screenshot",
    "mobile_set_orientation",
    "mobile_get_orientation",
]


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
# DEVICES PARSING
# =============================================================================

def extract_all_device_ids(devices_payload: Any) -> List[str]:
    if devices_payload is None:
        return []

    if isinstance(devices_payload, str):
        s = devices_payload.strip()
        try:
            parsed = json.loads(s)
            return extract_all_device_ids(parsed)
        except Exception:
            pass

        m = re.search(r"Android devices:\s*\[([^\]]+)\]", s, re.IGNORECASE)
        if m:
            inside = m.group(1)
            return [p.strip() for p in inside.split(",") if p.strip()]

        tokens = re.findall(r"\b([A-Za-z0-9_-]{6,})\b", s)
        out: List[str] = []
        for t in tokens:
            if t not in out:
                out.append(t)
        return out

    if isinstance(devices_payload, dict):
        for key in ["devices", "result", "data", "items"]:
            v = devices_payload.get(key)
            if isinstance(v, list):
                return extract_all_device_ids(v)

    if isinstance(devices_payload, list):
        out: List[str] = []
        for item in devices_payload:
            if isinstance(item, str) and item.strip():
                if item.strip() not in out:
                    out.append(item.strip())
            elif isinstance(item, dict):
                for k in DEVICE_KEYS + ["id", "name"]:
                    v = item.get(k)
                    if isinstance(v, str) and v.strip() and v.strip() not in out:
                        out.append(v.strip())
                        break
        return out

    return []


def pick_device_for_driver(devices: List[str], driver_index: int) -> Optional[str]:
    if not devices:
        return None
    if driver_index <= 1:
        return devices[0]
    if len(devices) >= 2:
        return devices[1]
    return devices[0]


# =============================================================================
# MCP WRAPPERS
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


class MCPMobileStdio:
    def __init__(self, command: str, args: List[str]):
        self.command = command
        self.args = args
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPMobileStdio":
        transport = await self._stack.enter_async_context(
            stdio_client(StdioServerParameters(command=self.command, args=self.args))
        )

        if isinstance(transport, tuple) and len(transport) >= 2:
            read_stream, write_stream = transport[0], transport[1]
        else:
            read_stream, write_stream = transport

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
# SCHEMA HELPERS (for "noParams" detection)
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


def schema_allows_key(schema: Dict[str, Any], key: str) -> bool:
    props = schema.get("properties")
    return isinstance(props, dict) and key in props


# =============================================================================
# MOBILE SAFE CALLS (retry + device + noParams)
# =============================================================================

def is_transient_error(text: str) -> bool:
    t = text.lower()
    return any(
        s in t
        for s in [
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


async def mobile_call_raw(mobile_mcp: MCPMobileStdio, tool: str, args: Dict[str, Any]) -> str:
    result = await mobile_mcp.call_tool(tool, args)
    return mcp_result_to_text(result)


async def mobile_call_safe(
    mobile_mcp: MCPMobileStdio,
    tool: str,
    args: Optional[Dict[str, Any]],
    device_id: Optional[str],
    schema_by_name: Dict[str, Dict[str, Any]],
    timeout_s: float = TOOL_TIMEOUT_S,
    attempts: int = TOOL_ATTEMPTS,
    backoff_base_s: float = TOOL_BACKOFF_BASE_S,
) -> Tuple[bool, str, Dict[str, Any]]:
    if args is None or not isinstance(args, dict):
        args = {}

    call_args = dict(args)
    schema = schema_by_name.get(tool, {"type": "object", "properties": {}})

    # Inject device
    if device_id and not any(k in call_args for k in DEVICE_KEYS):
        injected = False
        for k in DEVICE_KEYS:
            if schema_allows_key(schema, k):
                call_args[k] = device_id
                injected = True
                break
        if not injected and tool.startswith("mobile_") and tool != "mobile_list_available_devices":
            call_args["device"] = device_id

    # Inject noParams only if needed
    if tool == "mobile_list_available_devices" and "noParams" not in call_args:
        call_args["noParams"] = {}
    elif "noParams" not in call_args and schema_allows_key(schema, "noParams"):
        call_args["noParams"] = {}

    last_text = ""
    for attempt in range(1, attempts + 1):
        try:
            text = await asyncio.wait_for(mobile_call_raw(mobile_mcp, tool, call_args), timeout=timeout_s)
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


async def get_devices_payload_with_retries(
    mobile_mcp: MCPMobileStdio,
    schema_by_name: Dict[str, Dict[str, Any]],
    attempts: int = 6,
    delay_s: float = 0.5,
) -> Any:
    last_payload: Any = None
    for i in range(attempts):
        ok, text, _ = await mobile_call_safe(
            mobile_mcp=mobile_mcp,
            tool="mobile_list_available_devices",
            args={"noParams": {}},
            device_id=None,
            schema_by_name=schema_by_name,
            timeout_s=30,
            attempts=2,
            backoff_base_s=0.3,
        )
        print(f"\n[MOBILE] devices attempt {i+1}/{attempts} preview:\n{text[:800]}\n")
        try:
            payload = json.loads(text)
        except Exception:
            payload = text
        last_payload = payload
        ids = extract_all_device_ids(payload)
        if ok and ids:
            return payload
        await asyncio.sleep(delay_s * (i + 1))
    return last_payload


# =============================================================================
# UI PARSING: elements -> coords
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
#   These are the ONLY tools the model should call.
#   They enforce "list -> act -> list" for UI actions.
# =============================================================================

@dataclass
class DriverContext:
    name: str                  # "driver1" / "driver2"
    driver_index: int          # 1 / 2
    device_id: Optional[str]
    package_name: str
    mcp: MCPMobileStdio
    schema_by_name: Dict[str, Dict[str, Any]]
    lock: asyncio.Lock         # ensures sequential actions per driver


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
            # wait for release
            while gen == self._generation:
                await self._cond.wait()
            return f"[BARRIER] released generation={self._generation} (waiter={who})"


async def tool_observe(ctx: DriverContext) -> str:
    """Observe = list elements + screenshot (no click)."""
    async with ctx.lock:
        ok1, elems, _ = await mobile_call_safe(
            ctx.mcp, "mobile_list_elements_on_screen", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )
        ok2, ss, _ = await mobile_call_safe(
            ctx.mcp, "mobile_take_screenshot", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )
    payload = {
        "driver": ctx.name,
        "device": ctx.device_id,
        "list_ok": ok1,
        "elements": elems[:2500],
        "screenshot": ss[:800],
    }
    return json.dumps(payload, ensure_ascii=False)


async def tool_launch_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (set DRIVERx_PACKAGE or pass packageName)."})
    async with ctx.lock:
        # pre observe
        pre = await tool_observe(ctx)
        ok, out, args_used = await mobile_call_safe(
            ctx.mcp, "mobile_launch_app", {"packageName": pkg}, ctx.device_id, ctx.schema_by_name
        )
        post = await tool_observe(ctx)
    return json.dumps(
        {"ok": ok, "tool": "mobile_launch_app", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
        ensure_ascii=False,
    )


async def tool_terminate_app(ctx: DriverContext, packageName: Optional[str] = None) -> str:
    pkg = (packageName or "").strip() or ctx.package_name
    if not pkg:
        return json.dumps({"ok": False, "error": "Missing packageName (set DRIVERx_PACKAGE or pass packageName)."})
    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, args_used = await mobile_call_safe(
            ctx.mcp, "mobile_terminate_app", {"packageName": pkg}, ctx.device_id, ctx.schema_by_name
        )
        post = await tool_observe(ctx)
    return json.dumps(
        {"ok": ok, "tool": "mobile_terminate_app", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
        ensure_ascii=False,
    )


async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    Enforce: list -> find coords -> click coords -> list + screenshot.
    """
    if not target_text or not isinstance(target_text, str):
        return json.dumps({"ok": False, "error": "target_text is required"}, ensure_ascii=False)

    async with ctx.lock:
        # PRE
        ok_list, elems_text, _ = await mobile_call_safe(
            ctx.mcp, "mobile_list_elements_on_screen", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )
        ok_ss, ss_text, _ = await mobile_call_safe(
            ctx.mcp, "mobile_take_screenshot", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )
        payload = _maybe_json(elems_text)
        el = find_click_target(payload, target_text) if payload is not None else None

        if not el:
            # POST anyway for evidence
            ok_list2, elems2, _ = await mobile_call_safe(
                ctx.mcp, "mobile_list_elements_on_screen", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
            )
            ok_ss2, ss2, _ = await mobile_call_safe(
                ctx.mcp, "mobile_take_screenshot", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
            )
            return json.dumps(
                {
                    "ok": False,
                    "tool": "ui_click",
                    "target_text": target_text,
                    "error": "Target not found in elements list",
                    "pre": {"list_ok": ok_list, "elements": elems_text[:2500], "screenshot": ss_text[:800]},
                    "post": {"list_ok": ok_list2, "elements": elems2[:2500], "screenshot": ss2[:800]},
                },
                ensure_ascii=False,
            )

        x = int(el["_click_x"])
        y = int(el["_click_y"])

        ok_click, out_click, args_used = await mobile_call_safe(
            ctx.mcp,
            "mobile_click_on_screen_at_coordinates",
            {"x": x, "y": y},
            ctx.device_id,
            ctx.schema_by_name,
        )

        # POST
        ok_list2, elems2, _ = await mobile_call_safe(
            ctx.mcp, "mobile_list_elements_on_screen", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )
        ok_ss2, ss2, _ = await mobile_call_safe(
            ctx.mcp, "mobile_take_screenshot", {}, ctx.device_id, ctx.schema_by_name, timeout_s=45, attempts=2
        )

    return json.dumps(
        {
            "ok": ok_click,
            "tool": "ui_click",
            "target_text": target_text,
            "chosen": {"x": x, "y": y, "matched_texts": el.get("_matched_texts", [])},
            "args": args_used,
            "output": out_click,
            "pre": {"list_ok": ok_list, "elements": elems_text[:2500], "screenshot": ss_text[:800]},
            "post": {"list_ok": ok_list2, "elements": elems2[:2500], "screenshot": ss2[:800]},
        },
        ensure_ascii=False,
    )


async def tool_ui_type(ctx: DriverContext, text: str, submit: bool = False) -> str:
    if text is None or not isinstance(text, str):
        return json.dumps({"ok": False, "error": "text is required"}, ensure_ascii=False)

    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, args_used = await mobile_call_safe(
            ctx.mcp,
            "mobile_type_keys",
            {"text": text, "submit": bool(submit)},
            ctx.device_id,
            ctx.schema_by_name,
        )
        post = await tool_observe(ctx)

    return json.dumps(
        {"ok": ok, "tool": "ui_type", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
        ensure_ascii=False,
    )


async def tool_ui_swipe(ctx: DriverContext, direction: str = "down", distance: Optional[float] = None) -> str:
    d = (direction or "down").strip().lower()
    args: Dict[str, Any] = {"direction": d}
    if isinstance(distance, (int, float)):
        args["distance"] = distance

    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, args_used = await mobile_call_safe(
            ctx.mcp,
            "mobile_swipe_on_screen",
            args,
            ctx.device_id,
            ctx.schema_by_name,
        )
        post = await tool_observe(ctx)

    return json.dumps(
        {"ok": ok, "tool": "ui_swipe", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
        ensure_ascii=False,
    )


async def tool_press_button(ctx: DriverContext, button: str) -> str:
    # button: "home", "back", etc (depends on your MCP)
    async with ctx.lock:
        pre = await tool_observe(ctx)
        ok, out, args_used = await mobile_call_safe(
            ctx.mcp,
            "mobile_press_button",
            {"button": button},
            ctx.device_id,
            ctx.schema_by_name,
        )
        post = await tool_observe(ctx)

    return json.dumps(
        {"ok": ok, "tool": "mobile_press_button", "args": args_used, "output": out, "pre": json.loads(pre), "post": json.loads(post)},
        ensure_ascii=False,
    )


# =============================================================================
# OPENAI TOOL DEFINITIONS for our wrappers
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
        openai_tool(
            "observe",
            "Observe current UI: lists elements on screen + screenshot.",
            {"type": "object", "properties": {}, "required": []},
        ),
        openai_tool(
            "launch_app",
            "Launch the app. If packageName omitted, uses driver package config.",
            {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []},
        ),
        openai_tool(
            "terminate_app",
            "Terminate the app. If packageName omitted, uses driver package config.",
            {"type": "object", "properties": {"packageName": {"type": "string"}}, "required": []},
        ),
        openai_tool(
            "ui_click",
            "UI click by target text: automatically list elements, find coords, click, then list again + screenshot.",
            {"type": "object", "properties": {"target_text": {"type": "string"}}, "required": ["target_text"]},
        ),
        openai_tool(
            "ui_type",
            "Type text (assumes focus is on a field). Auto observe before/after.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "submit": {"type": "boolean"},
                },
                "required": ["text"],
            },
        ),
        openai_tool(
            "ui_swipe",
            "Swipe screen. Auto observe before/after.",
            {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "distance": {"type": "number"},
                },
                "required": [],
            },
        ),
        openai_tool(
            "press_button",
            "Press a device button (e.g., back, home). Auto observe before/after.",
            {"type": "object", "properties": {"button": {"type": "string"}}, "required": ["button"]},
        ),
        openai_tool(
            "sync_barrier",
            "Synchronize with the other driver. Call this when both drivers must align before continuing.",
            {"type": "object", "properties": {}, "required": []},
        ),
        openai_tool(
            "finish",
            "Finish the test for this driver. Provide status and notes.",
            {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["success", "failure", "blocked"]},
                    "notes": {"type": "string"},
                },
                "required": ["status"],
            },
        ),
    ]


# =============================================================================
# REACT AGENT LOOP (the model pilots live)
# =============================================================================

SYSTEM_REACT = """
Tu es un agent QA mobile autonome en mode ReAct (observe → decide → act → observe).
Tu pilotes l'application Android en appelant UNIQUEMENT les tools fournis.

Règles:
- Pour cliquer un élément UI: utilise toujours ui_click (NE PAS utiliser mobile_click_on_screen_at_coordinates).
- Pour taper: ui_type. Pour scroller: ui_swipe.
- Pour observer l'état: observe.
- Utilise sync_barrier quand une étape doit être synchronisée avec l'autre driver (ex: appel entrant/sortant, action simultanée).
- Sois robuste: observe souvent, et si un élément n'est pas visible, fais ui_swipe puis observe et réessaie.
- Termine en appelant finish avec un status (success/failure/blocked).

Tu reçois:
- Résumé Jira
- Contexte driver (driver1/driver2, device, package)
"""

async def run_react_driver(
    async_client: AsyncOpenAI,
    ctx: DriverContext,
    barrier: Barrier,
    jira_summary: str,
) -> Dict[str, Any]:
    tools = build_react_tools()

    # Map tool name -> callable for this driver
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
        if tool_name == "press_button":
            return await tool_press_button(ctx, button=args.get("button", "back"))
        if tool_name == "sync_barrier":
            return await barrier.wait(ctx.name)
        if tool_name == "finish":
            # finish handled by loop logic
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

    # Initial observe (gives model a starting state)
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
            # Model didn't call a tool; nudge it.
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
                # add tool message for trace
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": True, "final": final})})
                return final

            out = await _dispatch(tool_name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    # If max turns reached
    final = {
        "status": "blocked",
        "notes": f"Max turns reached ({MAX_TURNS_PER_DRIVER}) without finish",
        "driver": ctx.name,
        "device": ctx.device_id,
    }
    return final


# =============================================================================
# JIRA SUMMARY (tool-driven)
# =============================================================================

SYSTEM_JIRA = f"""Tu es un assistant Jira.
Ticket cible: {TICKET_KEY}

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

async def main():
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

        # 2) Probe devices
        print("\n===== (2) MOBILE: Probe devices =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as probe:
            tools = await probe.list_tools()
            schema_probe = build_schema_by_name(tools)
            devices_payload = await get_devices_payload_with_retries(probe, schema_probe, attempts=6, delay_s=0.5)
            devices_list = extract_all_device_ids(devices_payload)
            print("[MOBILE] devices_list =", devices_list)

        device1 = FORCE_DEVICE_DRIVER1 or pick_device_for_driver(devices_list, 1)
        device2 = FORCE_DEVICE_DRIVER2 or pick_device_for_driver(devices_list, 2)

        if not device1:
            print(json.dumps({"result": "blocked", "justification": "No Android device detected", "evidence": []}, indent=2))
            return

        # 3) Run 2 drivers in parallel (live ReAct)
        print("\n===== (3) REACT LIVE (parallel drivers) =====\n")

        barrier = Barrier()

        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mcp1, \
                   MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mcp2:

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

            print(f"[CTX] driver1 device={ctx1.device_id} package={ctx1.package_name or '[EMPTY]'}")
            print(f"[CTX] driver2 device={ctx2.device_id} package={ctx2.package_name or '[EMPTY]'}")

            r1, r2 = await asyncio.gather(
                run_react_driver(async_client, ctx1, barrier, jira_summary),
                run_react_driver(async_client, ctx2, barrier, jira_summary),
            )

        # 4) Aggregate result
        print("\n===== (4) DRIVER RESULTS =====\n")
        print(json.dumps({"driver1": r1, "driver2": r2}, ensure_ascii=False, indent=2))

        # Simple aggregation rule:
        # - if any failure => failure
        # - elif any blocked => blocked
        # - else success
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