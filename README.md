from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from contextlib import AsyncExitStack
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


Message = Dict[str, Any]


# =========================
# MCP HTTP wrapper (compatible anciennes versions)
# =========================
class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(
            streamable_http_client(self.url)
        )

        # Compat multi versions
        if isinstance(transport, tuple) and len(transport) >= 2:
            read_stream, write_stream = transport[0], transport[1]

        elif hasattr(transport, "read_stream"):
            read_stream = transport.read_stream
            write_stream = transport.write_stream

        elif hasattr(transport, "streams"):
            read_stream, write_stream = transport.streams[0], transport.streams[1]

        else:
            raise TypeError(f"Transport inconnu: {type(transport)}")

        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

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
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": getattr(
                        t,
                        "inputSchema",
                        getattr(t, "input_schema", {"type": "object"})
                    ),
                },
            }
        )

    return tools


# =========================
# Streaming completion + tool calling
# =========================
async def stream_and_call_tools(
    async_client: AsyncOpenAI,
    *,
    model: str,
    messages: List[Message],
    tools_openai: List[dict],
    jira_mcp: MCPRemoteHTTP,
) -> str:

    while True:

        print("\n--- PLANNER (streaming résumé ticket) ---\n", end="")

        stream = await async_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools_openai,
            tool_choice="auto",
            stream=True,
            temperature=0.2,
        )

        full_text = ""
        tool_calls = []

        async for chunk in stream:

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Texte
            if delta.content:
                print(delta.content, end="", flush=True)
                full_text += delta.content

            # Tool calls (si streamés)
            if getattr(delta, "tool_calls", None):
                tool_calls.extend(delta.tool_calls)

        print("\n")

        messages.append({"role": "assistant", "content": full_text})

        if not tool_calls:
            return full_text

        # Exécuter tools Jira
        for tc in tool_calls:

            name = tc.function.name
            args = tc.function.arguments or "{}"

            try:
                args = json.loads(args)
            except:
                args = {}

            result = await jira_mcp.call_tool(name, args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result.content, ensure_ascii=False),
                }
            )


# =========================
# SYSTEM PROMPT résumé Jira
# =========================
SYSTEM_PROMPT = """Tu es un assistant expert Jira.

Objectif:
Lire un ticket Jira via les outils disponibles et produire un résumé clair.

Instructions:
1. Récupère le ticket demandé (ou le plus récent si non précisé).
2. Lis description, critères d’acceptation, commentaires, statut.
3. Résume en français structuré:

FORMAT:

TICKET: <clé + titre>

CONTEXTE:
<résumé fonctionnel>

OBJECTIF:
<but du ticket>

CRITÈRES D’ACCEPTATION:
- ...

IMPACT MOBILE:
<si applicable>

RISQUES / POINTS D’ATTENTION:
- ...
"""


# =========================
# MAIN
# =========================
async def main():

    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(
        proxy=proxy,
        verify=False,
        follow_redirects=False,
    ) as http_client:

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
                {
                    "role": "user",
                    "content": "Peux-tu résumer le ticket Jira AMCXSOl-1706 ?",
                },
            ]

            await stream_and_call_tools(
                async_client,
                model=MODEL,
                messages=messages,
                tools_openai=tools_openai,
                jira_mcp=jira_mcp,
            )


if __name__ == "__main__":
    asyncio.run(main())