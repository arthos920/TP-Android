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
from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client


# =============================================================================
# CONFIG
# =============================================================================

JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")

MOBILE_MCP_COMMAND = os.getenv("MOBILE_MCP_COMMAND", "node")
MOBILE_MCP_ARGS = json.loads(
    os.getenv("MOBILE_MCP_ARGS_JSON", r'["C:/ads_mcp/mobile-mcp-main/lib/index.js"]')
)

LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")  # URL complète
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

PROXY_URL = os.getenv("PROXY_URL", "")

TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-2140")

# Safety truncation
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))

# Mobile schema keys
DEVICE_KEYS = ["device", "device_id", "deviceId", "udid", "serial", "android_device_id"]

# Some mobile tools in your MCP require noParams (as shown in your logs)
DEFAULT_NOPARAMS = {"noParams": {}}


# =============================================================================
# UTILS
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
            parts = [p.strip() for p in inside.split(",") if p.strip()]
            return parts

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
# MOBILE: robust calls (inject device + noParams + retries)
# =============================================================================

async def mobile_call_safe(
    mobile_mcp: MCPMobileStdio,
    tool_name: str,
    args: Optional[Dict[str, Any]],
    device_id: Optional[str],
    attempts: int = 3,
) -> str:
    """
    - Injecte device si absent
    - Injecte noParams si absent (car ton MCP le requiert souvent)
    - Retry léger
    - Retourne tool_text truncaté
    """
    if args is None:
        args = {}

    # Always ensure dict
    if not isinstance(args, dict):
        args = {}

    # Inject device
    if device_id and not any(k in args for k in DEVICE_KEYS):
        # ton MCP semble utiliser "device"
        args["device"] = device_id

    # Inject noParams if missing
    if "noParams" not in args:
        args.update(DEFAULT_NOPARAMS)

    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            result = await mobile_mcp.call_tool(tool_name, args)
            return mcp_result_to_text(result)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.4 * (i + 1))
    return f"[TOOL_ERROR] {tool_name}: {repr(last_err)}"


async def get_devices_payload_with_retries(
    mobile_mcp: MCPMobileStdio,
    attempts: int = 6,
    delay_s: float = 0.5,
) -> Any:
    """
    Appelle mobile_list_available_devices plusieurs fois.
    Le tool requiert {"noParams":{}} sur ton MCP.
    """
    last_payload: Any = None
    for i in range(attempts):
        try:
            result = await mobile_mcp.call_tool("mobile_list_available_devices", {"noParams": {}})
            devices_text = mcp_result_to_text(result)

            print(f"\n[MOBILE] devices attempt {i+1}/{attempts} preview:\n{devices_text[:800]}\n")

            # parse JSON best effort
            try:
                payload = json.loads(devices_text)
            except Exception:
                payload = devices_text

            last_payload = payload

            ids = extract_all_device_ids(payload)
            if ids:
                return payload

        except Exception as e:
            print(f"[MOBILE] WARNING devices attempt {i+1}/{attempts} failed: {repr(e)}")

        await asyncio.sleep(delay_s * (i + 1))

    return last_payload


# =============================================================================
# JIRA: tool-driven retrieval + summary (simple)
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
    """
    Le LLM pilote les tools Jira MCP pour récupérer le ticket puis produit un résumé.
    """
    async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
        tools = await jira_mcp.list_tools()
        # Convert MCP tools -> OpenAI tools (minimal)
        openai_tools = []
        for t in tools:
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {"type": "object"}
            if not isinstance(schema, dict):
                schema = {"type": "object"}
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})

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

        # tool loop (Jira uniquement)
        for _ in range(10):
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

                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": tool_text}
                )

        # force final summary format
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
# AUTONOMOUS QA AGENT: Plan -> Execute -> Verify -> Verdict
# =============================================================================

# We DO NOT let the model call tools in this stage.
# It outputs a deterministic JSON plan. We execute it.

SYSTEM_PLANNER = """Tu es un agent QA autonome sérieux.

Objectif:
- Lire un résumé Jira (acceptance criteria)
- Produire un PLAN JSON exécutable pour automatiser le test Android via MCP.

Contraintes:
- Tu ne dois PAS appeler de tools.
- Tu produis UNIQUEMENT du JSON valide.
- Le plan doit être actionnable: des étapes avec tool_name et args.
- Les tools disponibles sont donnés en liste.
- Driver mapping:
  - driver1 -> device[0]
  - driver2 -> device[1]
- Les outils MCP exigent souvent "noParams": {} même si vide.
- Ne PAS inventer des packages/credentials: si le ticket ne fournit pas, prévoir une étape "BLOCKED" avec raison.

Format JSON STRICT:
{
  "prechecks": [ { "check": "...", "required": true/false, "reason": "..." } ],
  "steps": [
    {
      "id": "S1",
      "driver": 1,
      "tool": "mobile_launch_app",
      "args": { "packageName": "..." },
      "expect": "texte court sur ce que tu attends"
    }
  ],
  "verifications": [
    { "id": "V1", "driver": 1, "rule": "comment décider success/failure", "evidence": "quelle info tool vérifier" }
  ],
  "final_rule": "comment conclure RESULT success/failure"
}
"""

SYSTEM_VERIFIER = """Tu es un vérificateur QA strict.
On te donne:
- le résumé Jira
- le plan JSON
- les logs d'exécution (tool outputs)
Tu dois rendre UNIQUEMENT du JSON:
{
  "result": "success" | "failure" | "blocked",
  "justification": "courte et précise",
  "evidence": [ "élément 1", "élément 2" ]
}
Règles:
- success seulement si les critères du ticket sont vérifiés avec evidence.
- blocked si manque d'infos (credentials, packageName, etc.) ou impossibilité technique.
- failure si des actions/attendus échouent.
"""

@dataclass
class DriverContext:
    driver_index: int
    device_id: Optional[str]
    mcp: MCPMobileStdio


async def build_plan(async_client: AsyncOpenAI, jira_summary: str, mobile_tool_names: List[str]) -> Dict[str, Any]:
    tool_list = "\n".join(f"- {n}" for n in mobile_tool_names)

    messages = [
        {"role": "system", "content": SYSTEM_PLANNER},
        {
            "role": "user",
            "content": (
                "Résumé Jira:\n"
                f"{jira_summary}\n\n"
                "Tools mobile disponibles:\n"
                f"{tool_list}\n\n"
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
        max_tokens=2500,
    )
    content = resp.choices[0].message.content or "{}"

    # Parse strict-ish
    try:
        plan = json.loads(content)
        if not isinstance(plan, dict):
            return {}
        return plan
    except Exception:
        # last resort: try to extract JSON block
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


async def execute_plan(
    jira_summary: str,
    plan: Dict[str, Any],
    driver1: DriverContext,
    driver2: DriverContext,
) -> List[Dict[str, Any]]:
    """
    Exécute le plan de manière déterministe:
    - step.driver == 1 -> driver1
    - step.driver == 2 -> driver2
    """
    logs: List[Dict[str, Any]] = []

    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        steps = []

    driver_map = {
        1: driver1,
        2: driver2,
    }

    for step in steps:
        if not isinstance(step, dict):
            continue

        sid = step.get("id", "S?")
        drv = step.get("driver", 1)
        tool = step.get("tool")
        args = step.get("args", {})
        expect = step.get("expect", "")

        ctx = driver_map.get(1 if drv not in (1, 2) else drv, driver1)

        if not tool or not isinstance(tool, str):
            logs.append(
                {
                    "step": sid,
                    "driver": ctx.driver_index,
                    "status": "skipped",
                    "reason": "missing tool",
                }
            )
            continue

        tool_text = await mobile_call_safe(
            ctx.mcp,
            tool_name=tool,
            args=args if isinstance(args, dict) else {},
            device_id=ctx.device_id,
            attempts=3,
        )

        logs.append(
            {
                "step": sid,
                "driver": ctx.driver_index,
                "device": ctx.device_id,
                "tool": tool,
                "args": args,
                "expect": expect,
                "output": tool_text,
            }
        )

    return logs


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
        return out if isinstance(out, dict) else {"result": "failure", "justification": "Verifier output not dict", "evidence": []}
    except Exception:
        return {"result": "failure", "justification": "Verifier output not valid JSON", "evidence": [content[:400]]}


# =============================================================================
# HTTPX client
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

        # 2) Mobile: open 2 sessions (driver1/driver2)
        print("\n===== (2) MOBILE: Init drivers + devices =====\n")
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_mcp_probe:
            # Probe devices once
            devices_payload = await get_devices_payload_with_retries(mobile_mcp_probe, attempts=6, delay_s=0.5)
            devices_list = extract_all_device_ids(devices_payload)
            print("[MOBILE] devices_list =", devices_list)

        device1 = pick_device_for_driver(devices_list, 1)
        device2 = pick_device_for_driver(devices_list, 2)

        if not device1:
            print("[MOBILE] No device detected -> BLOCKED")
            print(json.dumps({"result": "blocked", "justification": "No Android device detected", "evidence": []}, indent=2))
            return

        # Two independent MCP sessions for two drivers
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver1, \
                   MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_driver2:

            # Get tool list (from one session)
            tools = await mobile_driver1.list_tools()
            mobile_tool_names = [t.name for t in tools]

            driver1 = DriverContext(driver_index=1, device_id=device1, mcp=mobile_driver1)
            driver2 = DriverContext(driver_index=2, device_id=device2, mcp=mobile_driver2)

            print(f"[MOBILE] driver1 device = {driver1.device_id}")
            print(f"[MOBILE] driver2 device = {driver2.device_id}")

            # 3) PLAN (LLM, no tools)
            print("\n===== (3) PLAN (autonomous) =====\n")
            plan = await build_plan(async_client, jira_summary, mobile_tool_names)
            print(json.dumps(plan, ensure_ascii=False, indent=2))

            if not plan:
                verdict = {"result": "blocked", "justification": "Planner failed to output a valid plan", "evidence": []}
                print("\n===== VERDICT =====\n")
                print(json.dumps(verdict, ensure_ascii=False, indent=2))
                return

            # 4) EXECUTE deterministically (we call MCP tools; model does not)
            print("\n===== (4) EXECUTE =====\n")
            exec_logs = await execute_plan(jira_summary, plan, driver1, driver2)
            # Optional: print short log
            for item in exec_logs:
                print(f"[EXEC] {item.get('step')} drv={item.get('driver')} tool={item.get('tool')}")

            # 5) VERIFY (LLM, no tools)
            print("\n===== (5) VERIFY =====\n")
            verdict = await verify_execution(async_client, jira_summary, plan, exec_logs)

            print("\n===== VERDICT =====\n")
            print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())