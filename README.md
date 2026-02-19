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

# LLM OpenAI-compatible
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")  # URL complète
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Proxy (optionnel)
PROXY_URL = os.getenv("PROXY_URL", "")

# Safety / truncation
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# Parallel / timeouts / retries
STEP_DEFAULT_TIMEOUT_S = float(os.getenv("STEP_DEFAULT_TIMEOUT_S", "60"))
STEP_DEFAULT_ATTEMPTS = int(os.getenv("STEP_DEFAULT_ATTEMPTS", "3"))
STEP_BACKOFF_BASE_S = float(os.getenv("STEP_BACKOFF_BASE_S", "0.6"))

# Device picking
FORCE_DEVICE_DRIVER1 = os.getenv("FORCE_DEVICE_DRIVER1", "")  # optional override
FORCE_DEVICE_DRIVER2 = os.getenv("FORCE_DEVICE_DRIVER2", "")  # optional override

# ✅ Package override per driver (requested)
# If a step does not provide packageName, we'll fill it automatically using these.
GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "")  # optional fallback
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", GLOBAL_PACKAGE)
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", GLOBAL_PACKAGE)

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
# MCP TOOL SCHEMAS (for safe "noParams" injection)
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
    out: Dict[str, Dict[str, Any]] = {}
    for t in mcp_tools:
        out[t.name] = schema_from_mcp_tool(t)
    return out


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
            "mcp error",
            "internal",
        ]
    )


async def mobile_call_raw(
    mobile_mcp: MCPMobileStdio,
    tool: str,
    args: Dict[str, Any],
) -> str:
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
    """
    Intelligent retry:
    - Inject device if schema has it and args doesn't
    - Inject noParams only if schema expects it
    - Timeout per call
    - Retry transient failures with backoff
    Returns: (ok, output_text, final_args_used)
    """
    if args is None or not isinstance(args, dict):
        args = {}

    # make a copy (avoid mutating plan)
    call_args = dict(args)

    schema = schema_by_name.get(tool, {"type": "object", "properties": {}})

    # Inject device safely
    if device_id and not any(k in call_args for k in DEVICE_KEYS):
        for k in DEVICE_KEYS:
            if schema_allows_key(schema, k):
                call_args[k] = device_id
                break
        else:
            # Most of your mobile tools use "device"
            # If schema doesn't advertise, still try "device" only if tool is mobile_* and likely needs it.
            if tool.startswith("mobile_") and tool != "mobile_list_available_devices":
                call_args["device"] = device_id

    # Inject noParams safely (only if schema includes it OR tool is list_available_devices)
    if tool == "mobile_list_available_devices" and "noParams" not in call_args:
        call_args["noParams"] = {}
    elif "noParams" not in call_args and schema_allows_key(schema, "noParams"):
        call_args["noParams"] = {}

    last_text = ""
    for attempt in range(1, attempts + 1):
        try:
            text = await asyncio.wait_for(mobile_call_raw(mobile_mcp, tool, call_args), timeout=timeout_s)
            last_text = text

            # Heuristic: if tool output contains obvious error marker
            if text.startswith("[TOOL_ERROR]") or "invalid arguments" in text.lower():
                raise RuntimeError(text)

            return True, text, call_args

        except Exception as e:
            err_text = repr(e)
            last_text = f"[TOOL_ERROR] {tool}: {err_text}"

            # Recovery probes for UI-ish failures: grab screenshot + elements before retry
            # (best effort, ignore errors)
            if attempt < attempts:
                await asyncio.sleep(backoff_base_s * attempt)

            # If not transient, don't waste retries
            if attempt >= attempts or (not is_transient_error(err_text) and not is_transient_error(last_text)):
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
- Driver mapping:
  - driver1 -> device[0] (user1)
  - driver2 -> device[1] (user2)
- Synchronisation:
  - Si une étape doit attendre l'autre driver, mets "barrier": true sur cette étape (ou sur une étape dédiée).
- Robustesse:
  - Mets "attempts" (1-5) et "timeout_s" si nécessaire.
  - Préfère des vérifications UI via mobile_list_elements_on_screen et/ou mobile_take_screenshot.

IMPORTANT packages:
- On te donne package driver1 et package driver2 (peuvent être vides).
- Si tu connais le packageName, mets-le dans args.packageName.
- Si packageName manquant mais nécessaire, laisse args.packageName vide et indique dans "expect" ce qui manque,
  ou mets une étape BLOCKED.

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
        if isinstance(tool, str) and tool in ALLOWED_MOBILE_TOOLS:
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
    mobile_tool_names: List[str],
    driver1_package: str,
    driver2_package: str,
) -> Dict[str, Any]:
    tool_list = "\n".join(f"- {n}" for n in mobile_tool_names if n in ALLOWED_MOBILE_TOOLS)

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


def fill_package_if_missing(step_tool: str, args: Dict[str, Any], package_name: str) -> Dict[str, Any]:
    """
    If the step launches/terminates app and args lacks packageName, fill it.
    """
    if step_tool in ("mobile_launch_app", "mobile_terminate_app") and "packageName" not in args:
        if package_name:
            new_args = dict(args)
            new_args["packageName"] = package_name
            return new_args
    return args


async def post_action_evidence(ctx: DriverContext) -> Dict[str, str]:
    """
    Grab evidence without derailing if a tool fails.
    """
    evidence: Dict[str, str] = {}
    for tool in ("mobile_list_elements_on_screen", "mobile_take_screenshot"):
        if tool not in ALLOWED_MOBILE_TOOLS:
            continue
        ok, out, _ = await mobile_call_safe(
            mobile_mcp=ctx.mcp,
            tool=tool,
            args={},
            device_id=ctx.device_id,
            schema_by_name=ctx.schema_by_name,
            timeout_s=30,
            attempts=2,
            backoff_base_s=0.4,
        )
        evidence[tool] = out[:1200]
        # If first succeeds, keep going; both are useful
    return evidence


async def execute_one_step(ctx: DriverContext, step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes one step under a driver lock (prevents drift).
    Includes intelligent retry and evidence capture.
    """
    sid = step.get("id", "S?")
    tool = step.get("tool")
    drv = step.get("driver", ctx.driver_index)
    expect = step.get("expect", "")
    barrier = bool(step.get("barrier", False))

    if not isinstance(tool, str):
        return {
            "step": sid,
            "driver": drv,
            "status": "blocked",
            "reason": step.get("reason", "missing tool"),
            "barrier": barrier,
        }

    if tool not in ALLOWED_MOBILE_TOOLS:
        return {
            "step": sid,
            "driver": drv,
            "status": "blocked",
            "reason": f"tool not allowed: {tool}",
            "barrier": barrier,
        }

    args = step.get("args", {})
    if not isinstance(args, dict):
        args = {}

    # Fill package automatically if missing and we have one
    args = fill_package_if_missing(tool, args, ctx.package_name)

    # Step-level overrides
    timeout_s = float(step.get("timeout_s", STEP_DEFAULT_TIMEOUT_S))
    attempts = int(step.get("attempts", STEP_DEFAULT_ATTEMPTS))

    t0 = time.time()

    async with ctx.lock:
        ok, out, final_args = await mobile_call_safe(
            mobile_mcp=ctx.mcp,
            tool=tool,
            args=args,
            device_id=ctx.device_id,
            schema_by_name=ctx.schema_by_name,
            timeout_s=timeout_s,
            attempts=attempts,
            backoff_base_s=STEP_BACKOFF_BASE_S,
        )

        evidence = await post_action_evidence(ctx)

    return {
        "step": sid,
        "driver": drv,
        "device": ctx.device_id,
        "tool": tool,
        "args": final_args,
        "expect": expect,
        "ok": ok,
        "output": out,
        "evidence": evidence,
        "barrier": barrier,
        "duration_s": round(time.time() - t0, 3),
    }


async def execute_plan_parallel(
    plan: Dict[str, Any],
    driver1: DriverContext,
    driver2: DriverContext,
) -> List[Dict[str, Any]]:
    """
    ✅ Parallel execution driver1/driver2:
    - We create tasks for steps; per-driver locks keep each driver sequential.
    - "barrier": true forces synchronization (wait for all pending tasks).
    This prevents drift where one driver waits too long while the other is executing multiple actions.
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

        task = asyncio.create_task(execute_one_step(ctx, step))
        pending.append(task)

        # Barrier: wait everyone up to now
        if bool(step.get("barrier", False)):
            done = await asyncio.gather(*pending, return_exceptions=False)
            results.extend(done)
            pending = []

    # finish
    if pending:
        done = await asyncio.gather(*pending, return_exceptions=False)
        results.extend(done)

    # Now run verifications (also parallel)
    verifs = plan.get("verifications", [])
    if isinstance(verifs, list) and verifs:
        v_pending: List[asyncio.Task] = []
        for v in verifs:
            if not isinstance(v, dict):
                continue
            drv = v.get("driver", 1)
            ctx = driver_map.get(drv, driver1)
            # Treat verification as a step (tool + evidence)
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

        # 1) Jira summary (LLM + Jira tools)
        print("\n===== (1) JIRA: Fetch + Summary =====\n")
        jira_summary = await jira_fetch_and_summarize(async_client)
        print(jira_summary)

        # 2) Probe mobile tools + devices once
        print("\n===== (2) MOBILE: Probe tools + devices =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_probe:
            mobile_tools = await mobile_probe.list_tools()
            mobile_schema_by_name = build_schema_by_name(mobile_tools)
            tool_names = [t.name for t in mobile_tools]
            allowed_present = [t for t in tool_names if t in ALLOWED_MOBILE_TOOLS]
            print("[MOBILE] tools present:", allowed_present)

            devices_payload = await get_devices_payload_with_retries(
                mobile_probe,
                schema_by_name=mobile_schema_by_name,
                attempts=6,
                delay_s=0.5,
            )
            devices_list = extract_all_device_ids(devices_payload)
            print("[MOBILE] devices_list =", devices_list)

        # Driver device selection
        device1 = FORCE_DEVICE_DRIVER1.strip() or pick_device_for_driver(devices_list, 1)
        device2 = FORCE_DEVICE_DRIVER2.strip() or pick_device_for_driver(devices_list, 2)

        if not device1:
            verdict = {"result": "blocked", "justification": "No Android device detected", "evidence": []}
            print("\n===== VERDICT =====\n")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            return

        # 3) Build plan (LLM, no tools)
        print("\n===== (3) PLAN (autonomous) =====\n")
        plan = await build_plan(
            async_client=async_client,
            jira_summary=jira_summary,
            mobile_tool_names=allowed_present,
            driver1_package=DRIVER1_PACKAGE,
            driver2_package=DRIVER2_PACKAGE,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))

        if not plan:
            verdict = {"result": "blocked", "justification": "Planner failed to output a valid plan", "evidence": []}
            print("\n===== VERDICT =====\n")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            return

        # 4) Parallel execution with 2 independent MCP sessions (prevents drift)
        print("\n===== (4) EXECUTE (parallel drivers) =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver1, \
                   MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver2:

            # Build schemas per session (usually same, but safe)
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
            print(f"[MOBILE] driver2 device={driver2.device_id} package={driver2.package_name or '[EMPTY]'}")

            exec_logs = await execute_plan_parallel(plan, driver1, driver2)

        # Print short summary
        for item in exec_logs:
            if isinstance(item, dict) and "tool" in item:
                print(
                    f"[LOG] {item.get('step')} drv={item.get('driver')} "
                    f"tool={item.get('tool')} ok={item.get('ok')} dur={item.get('duration_s')}s"
                )

        # 5) Verify (LLM, no tools)
        print("\n===== (5) VERIFY =====\n")
        verdict = await verify_execution(async_client, jira_summary, plan, exec_logs)

        print("\n===== VERDICT =====\n")
        print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())