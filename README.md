from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

# MCP python client
from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client

# =============================================================================
# CONFIG
# =============================================================================

# --- Jira MCP (streamable-http)
JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")

# --- Mobile MCP (stdio node) : mobile-next/mobile-mcp
MOBILE_MCP_COMMAND = os.getenv("MOBILE_MCP_COMMAND", "node")
MOBILE_MCP_ARGS = json.loads(
    os.getenv("MOBILE_MCP_ARGS_JSON", r'["C:/ads_mcp/mobile-mcp-main/lib/index.js"]')
)

# (Optionnel) Forcer un device précis. Sinon auto-pick.
MOBILE_DEVICE_ID = os.getenv("MOBILE_DEVICE_ID")  # ex: "R5CX72Q8CBR"

# --- LLM OpenAI-compatible
LLM_API_KEY = os.getenv("LLM_API_KEY", "xxxx")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")  # IMPORTANT: URL complète
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # adapte

# --- Proxy (optionnel)
PROXY_URL = os.getenv("PROXY_URL", "")  # ex: http://user:pass@host:port

# --- Ticket Jira
TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-2140")  # clé exacte

# =============================================================================
# SAFETY / TOOL OUTPUT TRUNCATION
# =============================================================================

MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "8000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "200"))
STRIP_CONTROL_CHARS = True


def _strip_control_chars(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


def mcp_result_to_text(result: Any) -> str:
    """
    Convertit un résultat MCP (souvent list[TextContent]) en string,
    puis clean + truncate.
    """
    content = getattr(result, "content", result)

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                t = getattr(item, "text", None)
                if t is not None:
                    parts.append(t)
                else:
                    parts.append(str(item))
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
    """
    Retry léger si ton backend OpenAI-compatible renvoie parfois 500.
    """
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            return await async_client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


# =============================================================================
# MCP WRAPPERS
# =============================================================================

class MCPRemoteHTTP:
    """
    Jira MCP streamable-http wrapper.
    Compatible anciennes versions:
      - streamable_http_client(url) -> tuple(read_stream, write_stream)
      - ou objet read_stream/write_stream
      - ou objet streams[]
    """

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
            raise TypeError(f"Transport streamable_http_client inconnu: {type(transport)}")

        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session
        return await self.session.call_tool(name, args)


class MCPMobileStdio:
    """
    Mobile MCP (Android) via stdio (node index.js).
    """

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
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session
        return await self.session.call_tool(name, args)


# =============================================================================
# OPENAI TOOLS CONVERSION + DEVICE AUTO-INJECTION
# =============================================================================

DEVICE_KEYS = ["device_id", "deviceId", "udid", "serial", "device", "android_device_id"]


def mcp_tools_to_openai_tools_and_schema(mcp_tools) -> Tuple[List[dict], Dict[str, dict]]:
    """
    Convertit MCP tools -> OpenAI tools, et retourne aussi un dict tool_name -> schema(parameters).
    """
    tools_openai: List[dict] = []
    schema_by_name: Dict[str, dict] = {}

    for t in mcp_tools:
        schema = (
            getattr(t, "inputSchema", None)
            or getattr(t, "input_schema", None)
            or {"type": "object", "properties": {}}
        )

        if not isinstance(schema, dict) or schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        schema.setdefault("properties", {})

        schema_by_name[t.name] = schema

        tools_openai.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": schema,
                },
            }
        )

    return tools_openai, schema_by_name


def maybe_inject_device_id(
    tool_name: str,
    args: Dict[str, Any],
    schema_by_name: Dict[str, dict],
    device_id: Optional[str],
) -> None:
    """
    Si un device_id est sélectionné, et si le schema du tool contient une propriété device,
    on l'injecte automatiquement si l'utilisateur/LLM ne l'a pas déjà mis.
    """
    if not device_id:
        return
    if any(k in args for k in DEVICE_KEYS):
        return

    schema = schema_by_name.get(tool_name) or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return

    for k in DEVICE_KEYS:
        if k in props:
            args[k] = device_id
            return


def extract_first_device_id(devices_payload: Any) -> Optional[str]:
    """
    Best-effort extraction d'un id/serial/udid depuis le résultat de mobile_list_available_devices.
    Le payload peut être dict, list, str(JSON), etc.
    """
    if devices_payload is None:
        return None

    if isinstance(devices_payload, str):
        try:
            devices_payload = json.loads(devices_payload)
        except Exception:
            return None

    if isinstance(devices_payload, dict):
        for key in ["devices", "result", "data", "items"]:
            if key in devices_payload and isinstance(devices_payload[key], list) and devices_payload[key]:
                devices_payload = devices_payload[key]
                break

    if isinstance(devices_payload, list) and devices_payload:
        first = devices_payload[0]
        if isinstance(first, str):
            return first.strip()
        if isinstance(first, dict):
            for k in DEVICE_KEYS + ["id", "name"]:
                v = first.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    return None


async def get_devices_payload_with_retries(
    mobile_mcp: MCPMobileStdio,
    attempts: int = 6,
    delay_s: float = 0.5,
) -> Any:
    """
    Appelle mobile_list_available_devices plusieurs fois.
    Retourne le payload (dict/list/str) du "meilleur" résultat obtenu.
    Stop dès qu'on peut extraire un device_id.
    """
    last_payload: Any = None

    for i in range(attempts):
        try:
            result = await mobile_mcp.call_tool("mobile_list_available_devices", {})
            devices_text = mcp_result_to_text(result)

            print(f"\n[MOBILE] devices attempt {i+1}/{attempts} preview:\n{devices_text[:800]}\n")

            try:
                payload = json.loads(devices_text)
            except Exception:
                payload = devices_text

            last_payload = payload

            picked = extract_first_device_id(payload)
            if picked:
                return payload

        except Exception as e:
            print(f"[MOBILE] WARNING devices attempt {i+1}/{attempts} failed: {repr(e)}")

        await asyncio.sleep(delay_s * (i + 1))

    return last_payload


# =============================================================================
# TOOL CALL LOOP
# =============================================================================

Message = Dict[str, Any]


async def run_tool_call_loop(
    async_client: AsyncOpenAI,
    mcp_session: Any,
    tools_openai: List[dict],
    schema_by_name: Dict[str, dict],
    messages: List[Message],
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
            max_tokens=9000,
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

            if not isinstance(args, dict):
                args = {}

            maybe_inject_device_id(tool_name, args, schema_by_name, selected_device_id)

            print(f"\n[{label}] CALL TOOL: {tool_name} ARGS: {args}\n")

            try:
                result = await mcp_session.call_tool(tool_name, args)
                tool_text = mcp_result_to_text(result)
                print(f"[{label}] [TOOL_RESULT] {tool_name} chars={len(tool_text)} lines={tool_text.count(chr(10))+1}")
            except Exception as e:
                tool_text = f"[TOOL_ERROR] {tool_name}: {repr(e)}"
                print(f"[{label}] {tool_text}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_text,
                }
            )

    return messages


async def stream_final_answer(async_client: AsyncOpenAI, messages: List[Message], title: str) -> None:
    print(f"\n--- {title} (streaming) ---\n", end="", flush=True)

    stream = await async_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
        temperature=0.2,
        max_tokens=9000,
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
# PROMPTS
# =============================================================================

SYSTEM_JIRA = f"""Tu es un assistant Jira.
Ticket cible: {TICKET_KEY}

Tu es QA Automation. Résume un ticket Jira de façon actionnable.
Concentre-toi en particulier sur les champs "Test Details" (souvent customfield_11504)
et tout ce qui ressemble à : plateforme, données d'entrée, étapes, résultats attendus.

Retourne STRICTEMENT ce format :

- Titre:
- Test Details(customfield_11504):
- Objectif:
- Plateforme:
- Données (inputs/valeurs):
- Résultats attendus:
"""

SYSTEM_MOBILE = """Tu es un agent d'automatisation Android via MCP mobile-next/mobile-mcp.

Règles:
- Utilise les tools MCP quand nécessaire (tool_choice auto).
- Si un device est imposé, utilise-le. Sinon, utilise le device par défaut.
- Réponds à la fin avec RESULT: success/failure + justification claire.
"""


# =============================================================================
# MAIN
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


async def main():
    async with _make_httpx_async_client() as http_client:
        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        # ---------------------------------------------------------------------
        # 1) JIRA - Résumé ticket
        # ---------------------------------------------------------------------
        jira_summary_text = ""

        async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
            jira_mcp_tools = await jira_mcp.list_tools()
            jira_tools_openai, jira_schema_by_name = mcp_tools_to_openai_tools_and_schema(jira_mcp_tools)

            jira_messages: List[Message] = [
                {"role": "system", "content": SYSTEM_JIRA},
                {"role": "user", "content": f"Récupère le ticket {TICKET_KEY} via Jira tools puis résume-le."},
            ]

            jira_messages = await run_tool_call_loop(
                async_client,
                jira_mcp,
                jira_tools_openai,
                jira_schema_by_name,
                jira_messages,
                max_steps=8,
                label="JIRA",
            )

            jira_messages.append({"role": "user", "content": "Donne maintenant le résumé final au format demandé."})
            await stream_final_answer(async_client, jira_messages, "RÉSUMÉ JIRA")

            for m in reversed(jira_messages):
                if m.get("role") == "assistant" and m.get("content"):
                    jira_summary_text = m["content"]
                    break

        # ---------------------------------------------------------------------
        # 2) MOBILE - Devices (retries) + exécution
        # ---------------------------------------------------------------------
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_mcp:
            mobile_mcp_tools = await mobile_mcp.list_tools()
            mobile_tools_openai, mobile_schema_by_name = mcp_tools_to_openai_tools_and_schema(mobile_mcp_tools)

            selected_device = MOBILE_DEVICE_ID

            try:
                devices_payload = await get_devices_payload_with_retries(
                    mobile_mcp,
                    attempts=6,
                    delay_s=0.5,
                )

                if not selected_device and devices_payload is not None:
                    selected_device = extract_first_device_id(devices_payload)

                if selected_device:
                    print(f"[MOBILE] Selected device id: {selected_device}")
                else:
                    print("[MOBILE] WARNING: impossible de détecter un device_id (même après retries).")

            except Exception as e:
                print("[MOBILE] WARNING: devices retrieval failed:", repr(e))

            mobile_messages: List[Message] = [
                {"role": "system", "content": SYSTEM_MOBILE},
                {
                    "role": "user",
                    "content": (
                        "Test mobile simple.\n"
                        "1) Réaliser les critères d'acceptation du ticket Jira.\n"
                        "Réponds avec RESULT: success/failure.\n\n"
                        f"(Contexte Jira - optionnel)\n{jira_summary_text[:1200]}"
                    ),
                },
            ]

            mobile_messages = await run_tool_call_loop(
                async_client,
                mobile_mcp,
                mobile_tools_openai,
                mobile_schema_by_name,
                mobile_messages,
                max_steps=50,
                selected_device_id=selected_device,
                label="MOBILE",
            )

            mobile_messages.append({"role": "user", "content": "Donne le résultat final (RESULT + justification)."})
            await stream_final_answer(async_client, mobile_messages, "RÉSULTAT MOBILE")


if __name__ == "__main__":
    asyncio.run(main())