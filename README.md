"""
ai_chat_mcp_jira_summary.py

Objectif:
- 1 seule IA (Planner) qui lit un ticket Jira via MCP (streamable-http)
- Boucle tool-calling en NON-STREAM (fiable pour récupérer tool_calls)
- Résumé final en STREAMING (affichage console)
- Fixes:
  - compat anciennes versions MCP streamable_http_client (transport tuple len>=2)
  - conversion robuste des résultats MCP (TextContent, etc.) -> texte
  - sanitation (control chars) + truncation (lignes + chars) pour éviter 500 backend
  - retry léger en cas de 500 transient côté backend LLM
  - logs utiles (taille tool result, tool appelé)

À adapter:
- JIRA_MCP_URL
- LLM_API_KEY / LLM_BASE_URL / PROXY_URL
- MODEL
- TICKET_KEY (clé exacte Jira)
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# =========================
# CONFIG
# =========================

JIRA_MCP_URL = "http://localhost:20000/mcp"

LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = "magistral-2509"

PROXY_URL = "xxxx"  # "" si pas de proxy

TICKET_KEY = ""  # <-- mets la clé EXACTE ici (attention I/l)


# =========================
# TOOL RESULT SAFETY (FIX 500)
# =========================

MAX_TOOL_CHARS = 8000          # baisse si ton backend est fragile
MAX_TOOL_LINES = 200           # limite le nombre de lignes
STRIP_CONTROL_CHARS = True

Message = Dict[str, Any]


def _strip_control_chars(s: str) -> str:
    # supprime les caractères de contrôle (souvent source de bugs)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


def mcp_result_to_text(result: Any) -> str:
    """
    Convertit proprement un résultat MCP (souvent list[TextContent]) en string,
    + sanitation + truncation.
    """
    content = getattr(result, "content", result)

    # 1) Extraction texte
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

    # 2) Clean
    if STRIP_CONTROL_CHARS:
        text = _strip_control_chars(text)

    # 3) Limit lines
    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED_LINES]..."

    # 4) Limit chars
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "\n...[TRUNCATED_CHARS]..."

    return text


async def safe_chat_completion(async_client: AsyncOpenAI, **kwargs):
    """
    Retry léger en cas d'erreur backend (500, etc.).
    """
    last_err = None
    for attempt in range(3):
        try:
            return await async_client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err


# =========================
# MCP HTTP wrapper (compat anciennes versions)
# =========================

class MCPRemoteHTTP:
    """
    Wrapper MCP streamable-http compatible anciennes versions:
    - streamable_http_client(url) renvoie parfois tuple len>=2, ou objet avec read_stream/write_stream.
    """

    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(streamable_http_client(self.url))

        # Compat multi versions
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


def mcp_tools_to_openai_tools(mcp_tools) -> List[dict]:
    """
    Convertit MCP tools en tools OpenAI-compatible.
    Compat anciennes versions: inputSchema ou input_schema.
    """
    tools: List[dict] = []
    for t in mcp_tools:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": getattr(t, "inputSchema", getattr(t, "input_schema", {"type": "object"})),
                },
            }
        )
    return tools


# =========================
# PROMPT (résumé Jira)
# =========================

SYSTEM_PROMPT = f"""Tu es un assistant expert Jira.

Ticket cible: {TICKET_KEY}

Règles:
- Tu DOIS utiliser les outils Jira pour récupérer les infos du ticket {TICKET_KEY}.
- Si un outil "get issue" échoue, utilise un outil de recherche (search) avec la clé.
- Évite de récupérer des données énormes (commentaires/changelog/attachments) si possible.
- Si tu n'as pas d'option de filtre, utilise les champs essentiels (summary, description, acceptance criteria).

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


# =========================
# 1) Tool calling loop (NON-STREAM, fiable)
# =========================

async def run_tool_call_loop(
    async_client: AsyncOpenAI,
    jira_mcp: MCPRemoteHTTP,
    tools_openai: List[dict],
    messages: List[Message],
    max_steps: int = 8,
) -> List[Message]:
    """
    Boucle:
    - appel LLM non-stream pour obtenir tool_calls de manière fiable
    - exécution des tools via MCP
    - ajout des résultats (sanitized + truncated)
    - stop quand plus de tool_calls
    """
    for step in range(max_steps):
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
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            print(f"\nCALL TOOL: {name} ARGS: {args}\n")

            result = await jira_mcp.call_tool(name, args)

            tool_text = mcp_result_to_text(result)
            print(f"[TOOL_RESULT] {name} chars={len(tool_text)} lines={tool_text.count(chr(10))+1}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_text,
                }
            )

    return messages


# =========================
# 2) Résumé final (STREAMING)
# =========================

async def stream_final_answer(async_client: AsyncOpenAI, messages: List[Message]) -> str:
    print("\n--- RÉSUMÉ (streaming) ---\n", end="", flush=True)

    stream = await async_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
        temperature=0.2,
        max_tokens=900,
    )

    out: List[str] = []
    async for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            print(piece, end="", flush=True)
            out.append(piece)

    print("\n")
    return "".join(out).strip()


# =========================
# MAIN
# =========================

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

        async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
            tools_openai = mcp_tools_to_openai_tools(await jira_mcp.list_tools())

            messages: List[Message] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Récupère le ticket {TICKET_KEY} via Jira tools puis résume-le."},
            ]

            # 1) le modèle appelle Jira tools (non-stream, fiable)
            messages = await run_tool_call_loop(async_client, jira_mcp, tools_openai, messages)

            # 2) on demande le résumé final (streaming)
            messages.append({"role": "user", "content": "Donne maintenant le résumé final au format demandé."})
            await stream_final_answer(async_client, messages)


if __name__ == "__main__":
    asyncio.run(main())