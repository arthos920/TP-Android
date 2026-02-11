"""
planner_json_executor_android.py

Pipeline:
1) Jira Planner (MCP streamable-http) -> génère PLAN JSON strict (auto-exécutable)
2) Android Executor (mobile-next/mobile-mcp via stdio node) -> exécute le plan step-by-step

✅ Tool calling MCP en NON-STREAM (fiable)
✅ Résultats finaux en STREAMING (affichage)
✅ Fixes anti-500: sanitation + truncation tool results
✅ Compat anciennes versions MCP streamable_http_client (transport tuple len>=2)

A ADAPTER:
- JIRA_MCP_URL
- LLM_API_KEY / LLM_BASE_URL / PROXY_URL
- MODEL
- TICKET_KEY
- MOBILE_MCP_COMMAND + MOBILE_MCP_ARGS (chemin index.js)
- (Optionnel) MOBILE_DEVICE_ID
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client


# =============================================================================
# CONFIG
# =============================================================================

# Jira MCP (streamable-http)
JIRA_MCP_URL = "http://localhost:20000/mcp"

# Mobile MCP (stdio node) - mobile-next/mobile-mcp
MOBILE_MCP_COMMAND = "node"
MOBILE_MCP_ARGS = [
    r"C:/ads mcp/mobile-mcp-main/lib/index.js"  # <-- adapte
]

# Optionnel: forcer un device id/serial
MOBILE_DEVICE_ID: Optional[str] = None

# LLM endpoint
LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = "9"

PROXY_URL = "xxxx"  # "" si pas de proxy

# Ticket Jira
TICKET_KEY = ""  # ⚠️ clé exacte

Message = Dict[str, Any]


# =============================================================================
# FIX 500 (tool result sanitation + truncation)
# =============================================================================

MAX_TOOL_CHARS = 8000
MAX_TOOL_LINES = 200
STRIP_CONTROL_CHARS = True


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

    if STRIP_CONTROL_CHARS:
        text = _strip_control_chars(text)

    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED_LINES]..."

    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "\n...[TRUNCATED_CHARS]..."

    return text


async def safe_chat_completion(async_client: AsyncOpenAI, **kwargs):
    last_err = None
    for attempt in range(3):
        try:
            return await async_client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err


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
        elif hasattr(transport, "streams"):
            read_stream, write_stream = transport.streams[0], transport.streams[1]
        else:
            raise TypeError(f"Transport streamable_http_client inconnu: {type(transport)}")

        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
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
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)


def mcp_tools_to_openai_tools_and_schema(mcp_tools) -> Tuple[List[dict], Dict[str, dict]]:
    tools_openai: List[dict] = []
    schema_by_name: Dict[str, dict] = {}

    for t in mcp_tools:
        schema = getattr(t, "inputSchema", getattr(t, "input_schema", {"type": "object"})) or {"type": "object"}
        schema_by_name[t.name] = schema

        tools_openai.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            }
        )

    return tools_openai, schema_by_name


# =============================================================================
# MOBILE HELPERS (resolve coords / inject device)
# =============================================================================

DEVICE_KEYS = ["device_id", "deviceId", "udid", "serial", "device", "android_device_id"]


def _maybe_inject_device_id(tool_name: str, args: Dict[str, Any], schema_by_name: Dict[str, dict], device_id: Optional[str]):
    if not device_id:
        return
    if any(k in args for k in DEVICE_KEYS):
        return
    schema = schema_by_name.get(tool_name) or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    for k in DEVICE_KEYS:
        if k in props:
            args[k] = device_id
            return


def _extract_first_device_id_from_text(devices_text: str) -> Optional[str]:
    try:
        payload = json.loads(devices_text)
    except Exception:
        payload = devices_text

    if isinstance(payload, dict):
        for key in ["devices", "result", "data", "items"]:
            if key in payload and isinstance(payload[key], list) and payload[key]:
                payload = payload[key]
                break

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for k in DEVICE_KEYS + ["id", "name"]:
                v = first.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _pick_coords_from_elements(elements_payload: Any, target_text: str) -> Optional[Tuple[int, int]]:
    """
    Best-effort :
    - elements_payload attendu: list[dict] avec text/label + x/y ou bounds.
    - on match target_text (contains) sur text/label/description/accessibility.
    - on renvoie (x,y) si trouvé.
    """
    if not target_text or target_text.strip().lower() in ("n/a", "na", "none"):
        return None

    # elements_payload peut être string JSON
    if isinstance(elements_payload, str):
        try:
            elements_payload = json.loads(elements_payload)
        except Exception:
            return None

    if isinstance(elements_payload, dict):
        for key in ["elements", "result", "data", "items"]:
            if key in elements_payload:
                elements_payload = elements_payload[key]
                break

    if not isinstance(elements_payload, list):
        return None

    needle = _norm(target_text)

    def get_label(el: dict) -> str:
        for k in ["text", "label", "contentDescription", "content_description", "accessibilityLabel", "name", "value"]:
            v = el.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    def get_xy(el: dict) -> Optional[Tuple[int, int]]:
        # direct x/y
        x = el.get("x")
        y = el.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return int(x), int(y)

        # bounds: {left, top, right, bottom}
        b = el.get("bounds") or el.get("rect")
        if isinstance(b, dict):
            left = b.get("left")
            top = b.get("top")
            right = b.get("right")
            bottom = b.get("bottom")
            if all(isinstance(v, (int, float)) for v in [left, top, right, bottom]):
                return int((left + right) / 2), int((top + bottom) / 2)

        return None

    # 1) match contains
    for el in elements_payload:
        if not isinstance(el, dict):
            continue
        label = _norm(get_label(el))
        if needle and needle in label:
            xy = get_xy(el)
            if xy:
                return xy

    # 2) match reverse (label in needle)
    for el in elements_payload:
        if not isinstance(el, dict):
            continue
        label = _norm(get_label(el))
        if label and label in needle:
            xy = get_xy(el)
            if xy:
                return xy

    return None


# =============================================================================
# LLM TOOL CALL LOOP (generic)
# =============================================================================

async def run_tool_call_loop(
    async_client: AsyncOpenAI,
    mcp_session,
    tools_openai: List[dict],
    schema_by_name: Dict[str, dict],
    messages: List[Message],
    *,
    max_steps: int = 10,
    selected_device_id: Optional[str] = None,
    label: str = "AGENT",
) -> List[Message]:
    for _ in range(max_steps):
        resp = await safe_chat_completion(
            async_client,
            model=MODEL,
            messages=messages,
            tools=tools_openai,
            tool_choice="auto",
            stream=False,
            temperature=0.2,
            max_tokens=1200,
        )

        msg = resp.choices[0].message
        messages.append({"role": "assistant", "content": msg.content or ""})

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return messages

        for tc in tool_calls:
            tool_name = tc.function.name
            raw_args = tc.function.arguments or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            _maybe_inject_device_id(tool_name, args, schema_by_name, selected_device_id)

            print(f"\n[{label}] CALL TOOL: {tool_name} ARGS: {args}\n")
            result = await mcp_session.call_tool(tool_name, args)

            tool_text = mcp_result_to_text(result)
            print(f"[{label}] [TOOL_RESULT] {tool_name} chars={len(tool_text)} lines={tool_text.count(chr(10))+1}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_text,
                }
            )

    return messages


async def stream_final_answer(async_client: AsyncOpenAI, messages: List[Message], title: str):
    print(f"\n--- {title} (streaming) ---\n", end="", flush=True)

    stream = await async_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
        temperature=0.2,
        max_tokens=1200,
    )

    async for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            print(piece, end="", flush=True)

    print("\n")


# =============================================================================
# PLANNER -> PLAN JSON (strict)
# =============================================================================

PLANNER_SYSTEM = f"""Tu es IA-PLANNER (Jira).

Objectif: produire un PLAN JSON STRICT et auto-exécutable pour Android.

Tu as accès aux outils Jira uniquement.
Ticket cible: {TICKET_KEY}

Étapes:
1) Récupère le ticket via outils Jira (summary/description/acceptance criteria).
2) Génère un plan JSON STRICT selon le schéma ci-dessous.

SCHÉMA JSON (OBLIGATOIRE) :

{{
  "ticket": "{TICKET_KEY}",
  "app": {{
    "package": "<package android si connu sinon ''>",
    "name": "<nom app si connu sinon ''>"
  }},
  "preconditions": [
    "..."
  ],
  "steps": [
    {{
      "id": 1,
      "action": "launch_app|tap_text|type_text|swipe|press_button|open_url|wait_for_text|verify_text|screenshot",
      "target_text": "<texte à trouver à l'écran (pour tap/verify/wait) ou ''>",
      "text": "<texte à saisir (pour type_text) ou ''>",
      "url": "<url pour open_url sinon ''>",
      "button": "<HOME|BACK|ENTER etc si press_button sinon ''>",
      "swipe": {{ "direction": "up|down|left|right", "distance": "short|medium|long" }},
      "check": "<critère de réussite attendu>"
    }}
  ]
}}

Règles:
- Le JSON doit être PARSABLE (pas de commentaires, pas de markdown).
- Si tu ne connais pas le package, mets "" et l'Executor fera mobile_list_apps.
- Privilégie des actions atomiques et vérifiables.
- Ajoute des verify_text / wait_for_text quand nécessaire.
- Termine en output avec UNIQUEMENT le JSON, rien d'autre.
"""


# =============================================================================
# EXECUTOR - exécution déterministe du plan JSON
# =============================================================================

@dataclass
class ExecResult:
    result: str  # success/failed/blocked
    done_steps: List[int]
    failed_step: Optional[int]
    error: str
    evidence: List[str]


async def mobile_call(mobile_mcp: MCPMobileStdio, schema_by_name: Dict[str, dict], device_id: Optional[str],
                      tool_name: str, args: Dict[str, Any]) -> Any:
    _maybe_inject_device_id(tool_name, args, schema_by_name, device_id)
    print(f"\n[MOBILE] CALL TOOL: {tool_name} ARGS: {args}\n")
    return await mobile_mcp.call_tool(tool_name, args)


async def list_elements(mobile_mcp: MCPMobileStdio, schema_by_name: Dict[str, dict], device_id: Optional[str]) -> Any:
    res = await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_list_elements_on_screen", {})
    return mcp_result_to_text(res)


async def take_screenshot(mobile_mcp: MCPMobileStdio, schema_by_name: Dict[str, dict], device_id: Optional[str],
                          step_id: int, evidence: List[str]):
    # tools disponibles: mobile_take_screenshot, mobile_save_screenshot (selon ton serveur)
    try:
        res = await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_take_screenshot", {})
        txt = mcp_result_to_text(res)
        evidence.append(f"step_{step_id}_screenshot_taken:{txt[:200]}")
    except Exception:
        pass

    # Si ton MCP supporte save avec path, tu peux l’ajouter ici (optionnel)


async def execute_plan(
    mobile_mcp: MCPMobileStdio,
    schema_by_name: Dict[str, dict],
    plan: Dict[str, Any],
    device_id: Optional[str],
) -> ExecResult:
    done: List[int] = []
    evidence: List[str] = []

    # 0) device selection (best-effort)
    if not device_id:
        try:
            res = await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_list_available_devices", {})
            device_id = _extract_first_device_id_from_text(mcp_result_to_text(res))
            if device_id:
                print(f"[MOBILE] Selected device id: {device_id}")
        except Exception:
            pass

    # 1) launch app if needed
    app = plan.get("app", {}) if isinstance(plan.get("app"), dict) else {}
    pkg = (app.get("package") or "").strip()
    name = (app.get("name") or "").strip()

    # Some plans may not specify; we'll let steps handle launch_app.
    # But if plan includes package/name and first action isn't launch_app, we can still launch.
    # (On reste minimal: on suit le plan.)

    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        return ExecResult("failed", done, None, "Plan JSON: steps n'est pas une liste", evidence)

    for step in steps:
        sid = step.get("id")
        action = (step.get("action") or "").strip()
        target_text = (step.get("target_text") or "").strip()
        text = (step.get("text") or "").strip()
        url = (step.get("url") or "").strip()
        button = (step.get("button") or "").strip()
        swipe = step.get("swipe") if isinstance(step.get("swipe"), dict) else {}
        check = (step.get("check") or "").strip()

        if not isinstance(sid, int):
            # fallback: try int conversion
            try:
                sid = int(sid)
            except Exception:
                sid = 0

        try:
            # --- Action routing ---
            if action == "launch_app":
                # If package missing, use mobile_list_apps and try to find by name
                if not pkg and name:
                    res_apps = await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_list_apps", {})
                    apps_text = mcp_result_to_text(res_apps)
                    # best effort: find package string
                    # (simple heuristic: search for name, then look for "package" nearby)
                    # If your MCP returns structured JSON, you can improve this.
                    if _norm(name) in _norm(apps_text):
                        # If apps_text is JSON list of dicts, parse it
                        try:
                            apps_payload = json.loads(apps_text)
                            if isinstance(apps_payload, list):
                                for a in apps_payload:
                                    if isinstance(a, dict):
                                        aname = _norm(str(a.get("name", "")))
                                        apkg = str(a.get("package", "")).strip()
                                        if aname and _norm(name) in aname and apkg:
                                            pkg = apkg
                                            break
                        except Exception:
                            pass

                args = {}
                # mobile_launch_app: selon implémentation -> souvent {package_name: "..."} ou {package: "..."}
                # On fait best-effort multi keys
                if pkg:
                    args = {"package": pkg}
                elif name:
                    args = {"name": name}
                else:
                    raise RuntimeError("launch_app: ni package ni name fourni")

                await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_launch_app", args)

            elif action == "tap_text":
                # list elements + resolve coords
                elems_text = await list_elements(mobile_mcp, schema_by_name, device_id)
                coords = _pick_coords_from_elements(elems_text, target_text)

                if not coords:
                    # try a swipe then retry once
                    await mobile_call(
                        mobile_mcp, schema_by_name, device_id,
                        "mobile_swipe_on_screen",
                        {"direction": "up", "distance": "medium"},
                    )
                    elems_text = await list_elements(mobile_mcp, schema_by_name, device_id)
                    coords = _pick_coords_from_elements(elems_text, target_text)

                if not coords:
                    raise RuntimeError(f"tap_text: élément introuvable pour target_text='{target_text}'")

                x, y = coords
                await mobile_call(
                    mobile_mcp, schema_by_name, device_id,
                    "mobile_click_on_screen_at_coordinates",
                    {"x": x, "y": y},
                )

            elif action == "type_text":
                if text == "":
                    raise RuntimeError("type_text: champ 'text' vide")
                await mobile_call(mobile_mcp, schema_by_name, device_id, "mobile_type_keys", {"text": text})

            elif action == "swipe":
                direction = (swipe.get("direction") or "up").strip()
                distance = (swipe.get("distance") or "medium").strip()
                await mobile_call(
                    mobile_mcp, schema_by_name, device_id,
                    "mobile_swipe_on_screen",
                    {"direction": direction, "distance": distance},
                )

            elif action == "press_button":
                if not button:
                    raise RuntimeError("press_button: champ 'button' vide")
                await mobile_call(
                    mobile_mcp, schema_by_name, device_id,
                    "mobile_press_button",
                    {"button": button},
                )

            elif action == "open_url":
                if not url:
                    raise RuntimeError("open_url: champ 'url' vide")
                await mobile_call(
                    mobile_mcp, schema_by_name, device_id,
                    "mobile_open_url",
                    {"url": url},
                )

            elif action == "wait_for_text":
                # Simple polling (2 tries). Si tu as un tool wait, remplace.
                found = False
                for _ in range(2):
                    elems_text = await list_elements(mobile_mcp, schema_by_name, device_id)
                    if _norm(target_text) in _norm(elems_text):
                        found = True
                        break
                    await asyncio.sleep(1.0)
                if not found:
                    raise RuntimeError(f"wait_for_text: texte '{target_text}' non visible")

            elif action == "verify_text":
                elems_text = await list_elements(mobile_mcp, schema_by_name, device_id)
                if _norm(target_text) not in _norm(elems_text):
                    raise RuntimeError(f"verify_text: texte '{target_text}' non visible")

            elif action == "screenshot":
                await take_screenshot(mobile_mcp, schema_by_name, device_id, sid, evidence)

            else:
                raise RuntimeError(f"Action inconnue: {action}")

            # Après chaque step: screenshot + marquer done
            await take_screenshot(mobile_mcp, schema_by_name, device_id, sid, evidence)
            done.append(sid)

        except Exception as e:
            return ExecResult(
                result="failed",
                done_steps=done,
                failed_step=sid,
                error=f"{type(e).__name__}: {e}",
                evidence=evidence,
            )

    return ExecResult("success", done, None, "", evidence)


# =============================================================================
# MAIN
# =============================================================================

async def main():
    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(
        proxy=proxy,
        verify=False,
        follow_redirects=False,
        timeout=120.0,
    ) as http_client:
        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        # --- 1) Jira Planner -> Plan JSON
        async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
            jira_tools_openai, jira_schema_by_name = mcp_tools_to_openai_tools_and_schema(await jira_mcp.list_tools())

            planner_msgs: List[Message] = [
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": f"Produis le plan JSON strict pour le ticket {TICKET_KEY}."},
            ]

            planner_msgs = await run_tool_call_loop(
                async_client,
                jira_mcp,
                jira_tools_openai,
                jira_schema_by_name,
                planner_msgs,
                max_steps=10,
                label="PLANNER-JIRA",
            )

            # Demander output final JSON (non-stream pour fiabilité)
            planner_msgs.append({"role": "user", "content": "Output final: renvoie UNIQUEMENT le JSON du plan."})

            resp = await safe_chat_completion(
                async_client,
                model=MODEL,
                messages=planner_msgs,
                stream=False,
                temperature=0.2,
                max_tokens=1500,
            )

            plan_text = (resp.choices[0].message.content or "").strip()
            print("\n=== PLAN JSON (raw) ===\n", plan_text, "\n")

            # Parse JSON strict
            try:
                plan = json.loads(plan_text)
            except Exception as e:
                # Fallback: tenter extraction JSON si le modèle a ajouté du texte
                m = re.search(r"\{.*\}", plan_text, flags=re.S)
                if not m:
                    raise RuntimeError(f"Plan JSON non parsable: {e}\n{plan_text[:800]}")
                plan = json.loads(m.group(0))

        # --- 2) Executor Mobile -> exécuter le plan
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_mcp:
            mobile_tools_openai, mobile_schema_by_name = mcp_tools_to_openai_tools_and_schema(await mobile_mcp.list_tools())

            # détecter device
            device_id = MOBILE_DEVICE_ID
            if not device_id:
                try:
                    res = await mobile_mcp.call_tool("mobile_list_available_devices", {})
                    device_id = _extract_first_device_id_from_text(mcp_result_to_text(res))
                    if device_id:
                        print(f"[MOBILE] Selected device id: {device_id}")
                except Exception:
                    pass

            exec_result = await execute_plan(mobile_mcp, mobile_schema_by_name, plan, device_id)

            # --- 3) Rapport final (streaming)
            report_msgs: List[Message] = [
                {
                    "role": "system",
                    "content": "Tu es un assistant QA. Résume le résultat d'exécution d'un plan mobile de manière concise.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "ticket": plan.get("ticket"),
                            "result": exec_result.result,
                            "done_steps": exec_result.done_steps,
                            "failed_step": exec_result.failed_step,
                            "error": exec_result.error,
                            "evidence": exec_result.evidence,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
            ]

            await stream_final_answer(async_client, report_msgs, "RAPPORT EXECUTION MOBILE")


if __name__ == "__main__":
    asyncio.run(main())