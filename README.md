from __future__ import annotations

import asyncio, json
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

Message = Dict[str, Any]


# =========================
# CONFIG
# =========================
JIRA_MCP_URL = "http://localhost:20000/mcp"

LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = "magistral-2509"

PROXY_URL = "xxxx"  # "" si pas de proxy


# =========================
# MCP wrapper (compat ancienne version)
# =========================
class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(streamable_http_client(self.url))

        # transport est un tuple len>=2 chez toi
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
    tools = []
    for t in mcp_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": getattr(t, "inputSchema", getattr(t, "input_schema", {"type": "object"})),
            }
        })
    return tools


SYSTEM_PROMPT = """Tu es un assistant Jira.
Tu dois utiliser les outils Jira pour lire le ticket demandé et faire un résumé structuré en FR.

FORMAT:

TICKET: <clé + titre>

CONTEXTE:
...

OBJECTIF:
...

CRITÈRES D’ACCEPTATION:
- ...

ÉTAPES / RÈGLES MÉTIER:
- ...

POINTS D’ATTENTION:
- ...

Si tu n'arrives pas à récupérer le ticket, dis précisément quelle info manque (clé, projet, etc.).
"""


# =========================
# 1) Tool calling (non-stream) - fiable
# =========================
async def run_tool_call_loop(
    async_client: AsyncOpenAI,
    jira_mcp: MCPRemoteHTTP,
    tools_openai: List[dict],
    messages: List[Message],
    max_steps: int = 6,
) -> List[Message]:
    """
    Boucle: appel LLM non-stream -> execute tool calls -> ajoute tool results -> ...
    jusqu'à ce qu'il n'y ait plus de tool calls.
    """
    for _ in range(max_steps):
        resp = await async_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools_openai,
            tool_choice="auto",
            stream=False,
            temperature=0.2,
            max_tokens=800,
        )
        msg = resp.choices[0].message
        messages.append({"role": "assistant", "content": (msg.content or "")})

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return messages

        # execute tools
        for tc in tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            result = await jira_mcp.call_tool(name, args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result.content, ensure_ascii=False),
            })

    return messages


# =========================
# 2) Résumé final en streaming (affichage)
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

    out = []
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


async def main():
    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(proxy=proxy, verify=False, follow_redirects=False, timeout=120.0) as http_client:
        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        async with MCPRemoteHTTP(JIRA_MCP_URL) as jira_mcp:
            mcp_tools = await jira_mcp.list_tools()
            tools_openai = mcp_tools_to_openai_tools(mcp_tools)

            messages: List[Message] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Résume le ticket Jira ."},
            ]

            # 1) On laisse le modèle appeler Jira tools (non-stream, fiable)
            messages = await run_tool_call_loop(async_client, jira_mcp, tools_openai, messages)

            # 2) Puis on demande un résumé FINAL (streaming)
            messages.append({"role": "user", "content": "Maintenant, donne le résumé final au format demandé."})
            await stream_final_answer(async_client, messages)


if __name__ == "__main__":
    asyncio.run(main())