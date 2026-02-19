from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

# LLM (OpenAI-compatible)
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Proxy (optional)
PROXY_URL = os.getenv("PROXY_URL", "")

# Truncation
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# Parallel / step retry/timeout
STEP_DEFAULT_TIMEOUT_S = float(os.getenv("STEP_DEFAULT_TIMEOUT_S", "60"))
STEP_DEFAULT_ATTEMPTS = int(os.getenv("STEP_DEFAULT_ATTEMPTS", "3"))
STEP_BACKOFF_BASE_S = float(os.getenv("STEP_BACKOFF_BASE_S", "0.6"))

# Device overrides (optional)
FORCE_DEVICE_DRIVER1 = os.getenv("FORCE_DEVICE_DRIVER1", "").strip()
FORCE_DEVICE_DRIVER2 = os.getenv("FORCE_DEVICE_DRIVER2", "").strip()

# ✅ Package override per driver (requested)
GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", GLOBAL_PACKAGE).strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", GLOBAL_PACKAGE).strip()

# =============================================================================
# TOOLS (whitelist from your screenshots)
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

# Pseudo-tools handled by our runner (not MCP):
PSEUDO_UI_TOOLS = ["ui_click", "ui_type", "ui_swipe"]

DEVICE_KEYS = ["device", "device_id", "deviceId", "udid", "serial", "android_device_id"]


# =============================================================================
# TEXT + MCP RESULT HELPERS
# =============================================================================

def _strip_control_chars(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


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

    text = _strip_control_chars(text)

    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED_LINES]..."

    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "\n...[TRUNCATED_CHARS]..."

    return text


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
    """
    Supporte:
    - JSON (dict/list)
    - string JSON
    - string texte: "Android devices: [ID1, ID2]"
    """
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
# MCP TOOL SCHEMAS (for safe injection)
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
# MOBILE SAFE CALLS + INTELLIGENT RETRY
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
    timeout_s: float,
    attempts: int,
    backoff_base_s: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    if args is None or not isinstance(args, dict):
        args = {}

    call_args = dict(args)
    schema = schema_by_name.get(tool, {"type": "object", "properties": {}})

    # Inject device if needed/possible
    if device_id and not any(k in call_args for k in DEVICE_KEYS):
        for k in DEVICE_KEYS:
            if schema_allows_key(schema, k):
                call_args[k] = device_id
                break
        else:
            if tool.startswith("mobile_") and tool != "mobile_list_available_devices":
                call_args["device"] = device_id

    # Inject noParams only if schema expects it OR for list_available_devices
    if tool == "mobile_list_available_devices" and "noParams" not in call_args:
        call_args["noParams"] = {}
    elif "noParams" not in call_args and schema_allows_key(schema, "noParams"):
        call_args["noParams"] = {}

    last_text = ""
    for attempt in range(1, attempts + 1):
        try:
            text = await asyncio.wait_for(mobile_call_raw(mobile_mcp, tool, call_args), timeout=timeout_s)
            last_text = text

            # If tool output shows argument error, fail fast (not transient)
            if "invalid arguments" in text.lower() or "invalid_type" in text.lower():
                return False, text, call_args

            return True, text, call_args

        except Exception as e:
            last_text = f"[TOOL_ERROR] {tool}: {repr(e)}"
            if attempt >= attempts:
                break
            # backoff
            await asyncio.sleep(backoff_base_s * attempt)

            # fail fast if not transient
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
# UI HELPER: list elements -> select -> click
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
# JIRA: tool-driven fetch + summary
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
# AUTONOMOUS QA AGENT (Planner -> Parallel Execute -> Verify)
# =============================================================================

SYSTEM_PLANNER = """
Tu es un agent QA mobile autonome expert Android.

Tu dois transformer un ticket Jira (résumé) en PLAN exécutable via MCP mobile tools.

Règles strictes:
- Tu ne dois PAS appeler de tools.
- Tu produis UNIQUEMENT du JSON valide.
- Tu n'utilises que les tools autorisés listés.
- Les actions UI doivent se faire via pseudo-tools:
  - ui_click: choisir un élément par texte/label, puis cliquer dessus (le runner liste les éléments avant d'agir)
  - ui_type: taper du texte (runner liste avant/après)
  - ui_swipe: swipe (runner liste avant/après)
- Pour lancer/fermer app, utilise les vrais tools:
  - mobile_launch_app, mobile_terminate_app
- Driver mapping:
  - driver1 -> device[0] (user1)
  - driver2 -> device[1] (user2)
- Synchronisation:
  - Si une étape doit attendre l'autre driver, mets "barrier": true sur cette étape (ou sur une étape dédiée).
- Robustesse:
  - Mets "attempts" (1-5) et "timeout_s" si nécessaire.
- IMPORTANT packages:
  - On te donne package driver1 et package driver2 (peuvent être vides).
  - Si tu connais le packageName, mets-le dans args.packageName.
  - Sinon laisse args.packageName absent, le runner injectera automatiquement si disponible.

FORMAT JSON STRICT:

{
  "steps": [
    {
      "id": "S1",
      "driver": 1,
      "tool": "mobile_launch_app",
      "args": { "packageName": "..." },
      "expect": "App opened",
      "attempts": 3,
      "timeout_s": 60,
      "barrier": false
    },
    {
      "id": "S2",
      "driver": 1,
      "tool": "ui_click",
      "ui_target": "Login",
      "expect": "Login screen shown"
    }
  ],
  "verifications": [
    {
      "id": "V1",
      "driver": 1,
      "tool": "mobile_list_elements_on_screen",
      "args": {},
      "rule": "Condition lisible (ex: bouton PTT visible)"
    }
  ],
  "final_rule": "success si toutes les verifications satisfaites"
}
"""

SYSTEM_VERIFIER = """
Tu es un vérificateur QA mobile strict.

On te donne:
- résumé Jira
- plan JSON
- logs d'exécution (tool outputs + éléments/screenshot)

Tu dois rendre UNIQUEMENT du JSON valide:
{
  "result": "success" | "failure" | "blocked",
  "justification": "courte et précise",
  "evidence": ["...","..."]
}

Règles:
- success seulement si les critères attendus sont vérifiés avec evidence.
- blocked si infos indispensables manquantes (package, credentials, contacts, etc.) ou impossibilité technique.
- failure si exécution échoue ou UI inattendue.
"""


def sanitize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        plan["steps"] = []
        return plan

    clean_steps = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        tool = s.get("tool")
        if isinstance(tool, str) and (tool in ALLOWED_MOBILE_TOOLS or tool in PSEUDO_UI_TOOLS):
            clean_steps.append(s)
        else:
            clean_steps.append(
                {
                    "id": s.get("id", "S?"),
                    "driver": s.get("driver", 1),
                    "tool": None,
                    "status": "blocked",
                    "reason": f"Tool not allowed/invalid: {tool}",
                }
            )

    plan["steps"] = clean_steps

    verifs = plan.get("verifications", [])
    if isinstance(verifs, list):
        clean_verifs = []
        for v in verifs:
            if not isinstance(v, dict):
                continue
            tool = v.get("tool")
            if isinstance(tool, str) and tool in ALLOWED_MOBILE_TOOLS:
                clean_verifs.append(v)
            else:
                clean_verifs.append(
                    {
                        "id": v.get("id", "V?"),
                        "driver": v.get("driver", 1),
                        "tool": None,
                        "status": "blocked",
                        "reason": f"Tool not allowed/invalid: {tool}",
                    }
                )
        plan["verifications"] = clean_verifs

    return plan


async def build_plan(
    async_client: AsyncOpenAI,
    jira_summary: str,
    allowed_tools_present: List[str],
    driver1_package: str,
    driver2_package: str,
) -> Dict[str, Any]:
    tool_list = "\n".join(f"- {n}" for n in allowed_tools_present)

    messages = [
        {"role": "system", "content": SYSTEM_PLANNER},
        {
            "role": "user",
            "content": (
                "Résumé Jira:\n"
                f"{jira_summary}\n\n"
                "Tools mobiles autorisés:\n"
                f"{tool_list}\n\n"
                f"Package driver1: {driver1_package or '[EMPTY]'}\n"
                f"Package driver2: {driver2_package or '[EMPTY]'}\n\n"
                "Génère le plan JSON."
            ),
        },
    ]

    resp = await safe_chat(
        async_client,
        model=MODEL,
        messages=messages,
        stream=False,
        temperature=0.1,
        max_tokens=2600,
    )
    content = resp.choices[0].message.content or "{}"

    try:
        plan = json.loads(content)
        if not isinstance(plan, dict):
            return {}
        return sanitize_plan(plan)
    except Exception:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return {}
        try:
            plan = json.loads(m.group(0))
            return sanitize_plan(plan if isinstance(plan, dict) else {})
        except Exception:
            return {}


@dataclass
class DriverContext:
    driver_index: int
    device_id: Optional[str]
    package_name: str
    mcp: MCPMobileStdio
    schema_by_name: Dict[str, Dict[str, Any]]
    lock: asyncio.Lock


def fill_package_if_missing(tool: str, args: Dict[str, Any], package_name: str) -> Dict[str, Any]:
    if tool in ("mobile_launch_app", "mobile_terminate_app") and "packageName" not in args:
        if package_name:
            new_args = dict(args)
            new_args["packageName"] = package_name
            return new_args
    return args


async def list_elements_and_screenshot(ctx: DriverContext, tag: str) -> Dict[str, Any]:
    """
    Always produce evidence. Best effort; never throws.
    """
    out: Dict[str, Any] = {}
    ok_list, text_list, _ = await mobile_call_safe(
        ctx.mcp,
        "mobile_list_elements_on_screen",
        {},
        ctx.device_id,
        ctx.schema_by_name,
        timeout_s=45,
        attempts=2,
        backoff_base_s=0.4,
    )
    ok_ss, text_ss, _ = await mobile_call_safe(
        ctx.mcp,
        "mobile_take_screenshot",
        {},
        ctx.device_id,
        ctx.schema_by_name,
        timeout_s=45,
        attempts=2,
        backoff_base_s=0.4,
    )

    out[f"{tag}_list_ok"] = ok_list
    out[f"{tag}_elements"] = text_list[:2500]
    out[f"{tag}_screenshot"] = text_ss[:600]
    out[f"{tag}_payload"] = _maybe_json(text_list)
    return out


async def execute_one_step(ctx: DriverContext, step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Implements:
    - For EVERY action: list elements first, then act, then list elements again.
    - UI actions use pseudo-tools: ui_click / ui_type / ui_swipe.
    - Native tools supported: mobile_launch_app, mobile_terminate_app, etc.
    """
    sid = step.get("id", "S?")
    drv = step.get("driver", ctx.driver_index)
    expect = step.get("expect", "")
    barrier = bool(step.get("barrier", False))

    tool = step.get("tool")
    if not isinstance(tool, str):
        return {"step": sid, "driver": drv, "status": "blocked", "reason": "missing tool", "barrier": barrier}

    timeout_s = float(step.get("timeout_s", STEP_DEFAULT_TIMEOUT_S))
    attempts = int(step.get("attempts", STEP_DEFAULT_ATTEMPTS))

    ui_target = step.get("ui_target", "")  # for ui_click
    text_to_type = step.get("text", "")    # for ui_type
    submit = bool(step.get("submit", False))

    direction = step.get("direction", "")  # for ui_swipe
    distance = step.get("distance", None)

    args = step.get("args", {})
    if not isinstance(args, dict):
        args = {}

    # Auto inject packageName on launch/terminate if missing
    args = fill_package_if_missing(tool, args, ctx.package_name)

    t0 = time.time()

    async with ctx.lock:
        # PRE evidence
        pre = await list_elements_and_screenshot(ctx, "pre")
        pre_payload = pre.get("pre_payload")

        action_ok = True
        action_out = ""
        action_args_used: Dict[str, Any] = args

        # ACTION
        if tool == "ui_click":
            if not ui_target:
                return {"step": sid, "driver": drv, "status": "blocked", "reason": "ui_click requires ui_target"}

            target_el = find_click_target(pre_payload, ui_target) if pre_payload is not None else None
            if not target_el:
                action_ok = False
                action_out = f"[UI_CLICK] target not found: {ui_target}"
            else:
                x = int(target_el["_click_x"])
                y = int(target_el["_click_y"])
                action_ok, action_out, action_args_used = await mobile_call_safe(
                    ctx.mcp,
                    "mobile_click_on_screen_at_coordinates",
                    {"x": x, "y": y},
                    ctx.device_id,
                    ctx.schema_by_name,
                    timeout_s=timeout_s,
                    attempts=attempts,
                    backoff_base_s=STEP_BACKOFF_BASE_S,
                )

        elif tool == "ui_type":
            if not text_to_type:
                return {"step": sid, "driver": drv, "status": "blocked", "reason": "ui_type requires text"}

            action_ok, action_out, action_args_used = await mobile_call_safe(
                ctx.mcp,
                "mobile_type_keys",
                {"text": text_to_type, "submit": submit},
                ctx.device_id,
                ctx.schema_by_name,
                timeout_s=timeout_s,
                attempts=attempts,
                backoff_base_s=STEP_BACKOFF_BASE_S,
            )

        elif tool == "ui_swipe":
            a: Dict[str, Any] = {"direction": direction or "down"}
            if isinstance(distance, (int, float)):
                a["distance"] = distance

            action_ok, action_out, action_args_used = await mobile_call_safe(
                ctx.mcp,
                "mobile_swipe_on_screen",
                a,
                ctx.device_id,
                ctx.schema_by_name,
                timeout_s=timeout_s,
                attempts=attempts,
                backoff_base_s=STEP_BACKOFF_BASE_S,
            )

        else:
            # Native MCP tool
            if tool not in ALLOWED_MOBILE_TOOLS:
                return {"step": sid, "driver": drv, "status": "blocked", "reason": f"tool not allowed: {tool}"}

            action_ok, action_out, action_args_used = await mobile_call_safe(
                ctx.mcp,
                tool,
                args,
                ctx.device_id,
                ctx.schema_by_name,
                timeout_s=timeout_s,
                attempts=attempts,
                backoff_base_s=STEP_BACKOFF_BASE_S,
            )

        # POST evidence
        post = await list_elements_and_screenshot(ctx, "post")
        post.pop("post_payload", None)  # keep logs smaller

    return {
        "step": sid,
        "driver": drv,
        "device": ctx.device_id,
        "tool": tool,
        "args": action_args_used,
        "ui_target": ui_target,
        "expect": expect,
        "ok": bool(action_ok),
        "output": action_out,
        "evidence": {
            **{k: v for k, v in pre.items() if k != "pre_payload"},
            **post,
        },
        "barrier": barrier,
        "duration_s": round(time.time() - t0, 3),
    }


async def execute_plan_parallel(plan: Dict[str, Any], driver1: DriverContext, driver2: DriverContext) -> List[Dict[str, Any]]:
    """
    Parallel execution:
    - tasks for steps
    - each driver protected by its lock => sequential per driver, parallel across drivers
    - barrier=true => wait all pending tasks (sync point)
    """
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        return []

    driver_map = {1: driver1, 2: driver2}

    pending: List[asyncio.Task] = []
    results: List[Dict[str, Any]] = []

    for step in steps:
        if not isinstance(step, dict):
            continue

        drv = step.get("driver", 1)
        ctx = driver_map.get(drv, driver1)

        pending.append(asyncio.create_task(execute_one_step(ctx, step)))

        if bool(step.get("barrier", False)):
            done = await asyncio.gather(*pending, return_exceptions=False)
            results.extend(done)
            pending = []

    if pending:
        done = await asyncio.gather(*pending, return_exceptions=False)
        results.extend(done)

    # Verifications (also parallel)
    verifs = plan.get("verifications", [])
    if isinstance(verifs, list) and verifs:
        v_pending: List[asyncio.Task] = []
        for v in verifs:
            if not isinstance(v, dict):
                continue
            drv = v.get("driver", 1)
            ctx = driver_map.get(drv, driver1)

            # treat verification like a native step
            v_step = {
                "id": v.get("id", "V?"),
                "driver": drv,
                "tool": v.get("tool"),
                "args": v.get("args", {}),
                "expect": v.get("rule", ""),
                "attempts": int(v.get("attempts", 2)),
                "timeout_s": float(v.get("timeout_s", 45)),
                "barrier": bool(v.get("barrier", False)),
            }
            v_pending.append(asyncio.create_task(execute_one_step(ctx, v_step)))

            if bool(v_step.get("barrier", False)):
                done_v = await asyncio.gather(*v_pending, return_exceptions=False)
                results.extend(done_v)
                v_pending = []

        if v_pending:
            done_v = await asyncio.gather(*v_pending, return_exceptions=False)
            results.extend(done_v)

    return results


async def verify_execution(
    async_client: AsyncOpenAI,
    jira_summary: str,
    plan: Dict[str, Any],
    exec_logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYSTEM_VERIFIER},
        {"role": "user", "content": "Résumé Jira:\n" + jira_summary},
        {"role": "user", "content": "Plan JSON:\n" + json.dumps(plan, ensure_ascii=False, indent=2)},
        {"role": "user", "content": "Logs exécution:\n" + json.dumps(exec_logs, ensure_ascii=False, indent=2)},
        {"role": "user", "content": "Rends le verdict JSON."},
    ]

    resp = await safe_chat(
        async_client,
        model=MODEL,
        messages=messages,
        stream=False,
        temperature=0.1,
        max_tokens=900,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        out = json.loads(content)
        if isinstance(out, dict):
            return out
        return {"result": "failure", "justification": "Verifier output not dict", "evidence": []}
    except Exception:
        return {"result": "failure", "justification": "Verifier output not valid JSON", "evidence": [content[:600]]}


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

        # 2) Probe mobile tools + devices once
        print("\n===== (2) MOBILE: Probe tools + devices =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_probe:
            mcp_tools = await mobile_probe.list_tools()
            schema_probe = build_schema_by_name(mcp_tools)
            tool_names = [t.name for t in mcp_tools]

            allowed_present = [t for t in tool_names if t in ALLOWED_MOBILE_TOOLS]
            print("[MOBILE] tools present:", allowed_present)

            devices_payload = await get_devices_payload_with_retries(
                mobile_probe,
                schema_by_name=schema_probe,
                attempts=6,
                delay_s=0.5,
            )
            devices_list = extract_all_device_ids(devices_payload)
            print("[MOBILE] devices_list =", devices_list)

        device1 = FORCE_DEVICE_DRIVER1 or pick_device_for_driver(devices_list, 1)
        device2 = FORCE_DEVICE_DRIVER2 or pick_device_for_driver(devices_list, 2)

        if not device1:
            verdict = {"result": "blocked", "justification": "No Android device detected", "evidence": []}
            print("\n===== VERDICT =====\n")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            return

        # 3) Plan
        print("\n===== (3) PLAN (autonomous) =====\n")
        plan = await build_plan(
            async_client=async_client,
            jira_summary=jira_summary,
            allowed_tools_present=allowed_present,
            driver1_package=DRIVER1_PACKAGE,
            driver2_package=DRIVER2_PACKAGE,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))

        if not plan:
            verdict = {"result": "blocked", "justification": "Planner failed to output a valid plan", "evidence": []}
            print("\n===== VERDICT =====\n")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            return

        # 4) Parallel execution with 2 independent MCP sessions
        print("\n===== (4) EXECUTE (parallel drivers, list->act->list each step) =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver1, \
                   MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver2:

            tools_d1 = await mobile_driver1.list_tools()
            tools_d2 = await mobile_driver2.list_tools()
            schema_d1 = build_schema_by_name(tools_d1)
            schema_d2 = build_schema_by_name(tools_d2)

            driver1 = DriverContext(
                driver_index=1,
                device_id=device1,
                package_name=DRIVER1_PACKAGE,
                mcp=mobile_driver1,
                schema_by_name=schema_d1,
                lock=asyncio.Lock(),
            )
            driver2 = DriverContext(
                driver_index=2,
                device_id=device2,
                package_name=DRIVER2_PACKAGE,
                mcp=mobile_driver2,
                schema_by_name=schema_d2,
                lock=asyncio.Lock(),
            )

            print(f"[MOBILE] driver1 device={driver1.device_id} package={driver1.package_name or '[EMPTY]'}")
            print(f"[MOBILE] driver2 device={driver2.device_id} package={driver2.device_id or '[EMPTY]'}")

            exec_logs = await execute_plan_parallel(plan, driver1, driver2)

        # 5) Print short summary
        for item in exec_logs:
            if isinstance(item, dict) and "tool" in item:
                print(
                    f"[LOG] {item.get('step')} drv={item.get('driver')} "
                    f"tool={item.get('tool')} ok={item.get('ok')} dur={item.get('duration_s')}s"
                )

        # 6) Verify
        print("\n===== (5) VERIFY =====\n")
        verdict = await verify_execution(async_client, jira_summary, plan, exec_logs)

        print("\n===== VERDICT =====\n")
        print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())




print(f"[MOBILE] driver2 device={driver2.device_id} package={driver2.package_name or '[EMPTY]'}")