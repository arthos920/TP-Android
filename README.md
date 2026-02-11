"""
ai_chat_mcp_jira_plus_mobile_test.py

✅ Ce script fait 2 choses, dans cet ordre :

1) JIRA (MCP streamable-http) :
   - Le modèle récupère un ticket Jira via tools MCP
   - Résume le ticket (tool-calling en NON-STREAM + résumé final STREAMING)
   - Fixes anti-500 : sanitation + truncation des tool results

2) MOBILE (Android) (MCP stdio Node - mobile-next/mobile-mcp) :
   - Connexion au MCP mobile via stdio (node index.js)
   - Sélection automatique d’un device (premier de la liste) si plusieurs
   - Test simple : ouvrir l’app Settings / Paramètres
   - Tool-calling mobile en NON-STREAM (fiable)
   - (Optionnel) streaming pour afficher le texte final

⚙️ À ADAPTER :
- JIRA_MCP_URL
- LLM_API_KEY / LLM_BASE_URL / PROXY_URL
- MODEL
- TICKET_KEY
- MOBILE_MCP_COMMAND + MOBILE_MCP_ARGS (chemin vers index.js du serveur mobile-mcp)
- (Optionnel) MOBILE_DEVICE_ID si tu veux forcer un device précis

Dépendances:
pip install openai httpx mcp anyio
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from mcp import ClientSession, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client


# =============================================================================
# CONFIG
# =============================================================================

# --- Jira MCP (streamable-http)
JIRA_MCP_URL = "http://localhost:20000/mcp"

# --- Mobile MCP (stdio node) : mobile-next/mobile-mcp
# ⚠️ Mets ici le chemin exact vers le fichier index.js (build) de mobile-mcp.
# Exemple si tu as cloné le repo et build:
#   node <repo>/dist/index.js  (ou lib/index.js selon build)
MOBILE_MCP_COMMAND = "node"
MOBILE_MCP_ARGS = [
    r"C:/ads mcp/mobile-mcp-main/lib/index.js"  # <-- adapte
]

# Optionnel : si tu veux forcer un device précis.
# Sinon on prendra le premier device renvoyé par mobile_list_available_devices.
MOBILE_DEVICE_ID: Optional[str] = None


# --- LLM endpoint OpenAI-compatible
LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = ""

PROXY_URL = "xxxx"  # "" si pas de proxy

# --- Ticket Jira à résumer
TICKET_KEY = ""  # ⚠️ clé exacte (I majuscule vs l minuscule)

Message = Dict[str, Any]


# =============================================================================
# SAFETY / FIX 500 (tool result sanitation + truncation)
# =============================================================================

MAX_TOOL_CHARS = 8000
MAX_TOOL_LINES = 200
STRIP_CONTROL_CHARS = True


def _strip_control_chars(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


def mcp_result_to_text(result: Any) -> str:
    """
    Convertit un résultat MCP (souvent list[TextContent]) en string,
    puis clean + truncate (évite les 500 côté backend LLM).
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
    """
    Jira MCP streamable-http compatible anciennes versions:
    - streamable_http_client(url) -> tuple len>=2 ou objet read_stream/write_stream.
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
    """
    Mobile MCP (Android) via stdio (node index.js).
    Compatible mobile-next/mobile-mcp.
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

        # stdio_client renvoie normalement (read_stream, write_stream)
        if isinstance(transport, tuple) and len(transport) >= 2:
            read_stream, write_stream = transport[0], transport[1]
        else:
            # fallback
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
    """
    Convertit MCP tools -> OpenAI tools, et retourne aussi un dict tool_name -> schema (parameters).
    """
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
# DEVICE AUTO-INJECTION (mobile)
# =============================================================================

DEVICE_KEYS = ["device_id", "deviceId", "udid", "serial", "device", "android_device_id"]


def _maybe_inject_device_id(tool_name: str, args: Dict[str, Any], schema_by_name: Dict[str, dict], device_id: Optional[str]):
    """
    Si un device_id est sélectionné, et si le schema du tool contient un champ device,
    on l’injecte automatiquement si l’utilisateur/LLM ne l’a pas mis.
    """
    if not device_id:
        return

    schema = schema_by_name.get(tool_name) or {}
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}

    # si args contient déjà un device key, ne pas toucher
    if any(k in args for k in DEVICE_KEYS):
        return

    for k in DEVICE_KEYS:
        if k in props:
            args[k] = device_id
            return


def _extract_first_device_id(devices_payload: Any) -> Optional[str]:
    """
    Essaie d’extraire un id/serial/udid depuis le résultat de mobile_list_available_devices.
    Format dépendant de l’implémentation MCP, donc on fait du best-effort.
    """
    # payload peut être dict, list, str(JSON), etc.
    if devices_payload is None:
        return None

    # si c’est déjà une string JSON
    if isinstance(devices_payload, str):
        try:
            devices_payload = json.loads(devices_payload)
        except Exception:
            return None

    # si c’est dict avec une liste à l’intérieur
    if isinstance(devices_payload, dict):
        # ex: {"devices": [...]} ou {"result": [...]}
        for key in ["devices", "result", "data", "items"]:
            if key in devices_payload and isinstance(devices_payload[key], list) and devices_payload[key]:
                devices_payload = devices_payload[key]
                break

    # si c’est une list, on prend le premier item
    if isinstance(devices_payload, list) and devices_payload:
        first = devices_payload[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for k in DEVICE_KEYS + ["id", "name"]:
                if k in first and isinstance(first[k], str) and first[k].strip():
                    return first[k].strip()

    return None


# =============================================================================
# PROMPTS
# =============================================================================

SYSTEM_JIRA = f"""Tu es un assistant Jira.

Ticket cible: {TICKET_KEY}

Règles:
- Tu DOIS utiliser les outils Jira pour récupérer les infos du ticket {TICKET_KEY}.
- Si un outil "get issue" échoue, utilise un outil de recherche (search) avec la clé.
- Évite de récupérer des données énormes (commentaires/changelog/attachments) si possible.
- Si tu n'as pas d'option de filtre, utilise les champs essentiels.

FORMAT DE SORTIE (FR):

TICKET: <clé + titre>
STATUT / PRIORITÉ:
CONTEXTE:
OBJECTIF:
CRITÈRES D’ACCEPTATION:
- ...
DONNÉES / PRÉREQUIS:
- ...
POINTS D’ATTENTION:
- ...
"""

SYSTEM_MOBILE = """Tu es un agent d'automatisation Android via MCP mobile-next/mobile-mcp.

Règles d'exécution:
- Commence par lister les devices (mobile_list_available_devices).
- Si plusieurs devices, choisis le premier par défaut (sauf si on te donne un device_id).
- Pour ouvrir une app:
  1) mobile_list_apps (si tu as besoin de trouver le package)
  2) mobile_launch_app (avec package si nécessaire)
- Si un outil nécessite un device_id, ajoute-le.

Objectif immédiat:
- Faire un test simple: ouvrir l'app "Paramètres / Settings".
- Puis faire une capture d'écran (mobile_take_screenshot ou mobile_save_screenshot si dispo).
- Réponds ensuite: RESULT: success/failed + brève justification.
"""


# =============================================================================
# TOOL CALL LOOP (NON-STREAM) - générique Jira & Mobile
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
    """
    Boucle non-stream :
    - appeler LLM (tool_choice auto)
    - exécuter tool_calls via MCP
    - append tool results (sanitized+truncated)
    - stop si plus de tool_calls
    """

    for _ in range(max_steps):
        resp = await safe_chat_completion(
            async_client,
            model=MODEL,
            messages=messages,
            tools=tools_openai,
            tool_choice="auto",
            stream=False,
            temperature=0.2,
            max_tokens=900,
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

            # injection device_id si requis et disponible
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
        max_tokens=900,
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

        # ---------------------------------------------------------------------
        # 1) JIRA - Résumé ticket
        # ---------------------------------------------------------------------
        jira_summary_text = ""

        async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
            jira_tools_openai, jira_schema_by_name = mcp_tools_to_openai_tools_and_schema(
                await jira_mcp.list_tools()
            )

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

            # résumé final streaming
            jira_messages.append({"role": "user", "content": "Donne maintenant le résumé final au format demandé."})
            await stream_final_answer(async_client, jira_messages, "RÉSUMÉ JIRA")

            # (Optionnel) récupérer le dernier assistant content en texte
            for m in reversed(jira_messages):
                if m.get("role") == "assistant" and m.get("content"):
                    jira_summary_text = m["content"]
                    break

        # ---------------------------------------------------------------------
        # 2) MOBILE (Android) - Test simple (ouvrir Settings)
        # ---------------------------------------------------------------------
        async with MCPMobileStdio(MOBILE_MCP_COMMAND, MOBILE_MCP_ARGS) as mobile_mcp:
            mobile_tools_openai, mobile_schema_by_name = mcp_tools_to_openai_tools_and_schema(
                await mobile_mcp.list_tools()
            )

            # Sélection device (automatique)
            selected_device = MOBILE_DEVICE_ID

            # On appelle directement l’outil mobile_list_available_devices
            try:
                result = await mobile_mcp.call_tool("mobile_list_available_devices", {})
                devices_text = mcp_result_to_text(result)

                # best-effort extraction
                # certains serveurs renvoient du JSON string, d’autres du dict, etc.
                try:
                    devices_payload = json.loads(devices_text)
                except Exception:
                    devices_payload = devices_text

                if not selected_device:
                    selected_device = _extract_first_device_id(devices_payload)

                print("\n[MOBILE] Devices raw preview:\n", devices_text[:1200], "\n")

                if selected_device:
                    print(f"[MOBILE] Selected device id: {selected_device}")
                else:
                    print("[MOBILE] WARNING: impossible de détecter un device_id. "
                          "Le serveur peut utiliser un device par défaut.")

            except Exception as e:
                print("[MOBILE] WARNING: mobile_list_available_devices a échoué:", repr(e))

            # Messages mobile (on peut injecter le résumé Jira, utile plus tard)
            mobile_messages: List[Message] = [
                {"role": "system", "content": SYSTEM_MOBILE},
                {
                    "role": "user",
                    "content": (
                        "Test mobile simple.\n"
                        "1) Ouvre l'app Paramètres (Settings) sur Android.\n"
                        "2) Fais une capture d'écran.\n"
                        "Réponds avec RESULT: success/failed.\n\n"
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
                max_steps=10,
                selected_device_id=selected_device,
                label="MOBILE",
            )

            # (Optionnel) réponse finale en streaming
            mobile_messages.append({"role": "user", "content": "Donne le résultat final (RESULT + justification)."})
            await stream_final_answer(async_client, mobile_messages, "RÉSULTAT MOBILE")


if __name__ == "__main__":
    asyncio.run(main())