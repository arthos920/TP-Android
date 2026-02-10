from __future__ import annotations

import asyncio, json
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


JIRA_MCP_URL = "http://localhost:20000/mcp"

LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = "magistral-2509"

PROXY_URL = "xxxx"  # "" si pas de proxy

TICKET_KEY = "AMCXSOl-1706"  # <-- mets la clé exacte ici


Message = Dict[str, Any]


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


def mcp_result_to_text(result) -> str:
    content = getattr(result, "content", result)

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                text = getattr(item, "text", None)
                if text is not None:
                    parts.append(text)
                else:
                    parts.append(str(item))
        return "\n".join(parts)

    if isinstance(content, str):
        return content

    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


SYSTEM_PROMPT = f"""Tu es un assistant Jira.

Ticket cible: {TICKET_KEY}

Règles:
- Tu DOIS utiliser les outils Jira pour récupérer les infos du ticket {TICKET_KEY}.
- Si un outil "get issue" échoue, utilise un outil de recherche (search) avec la clé.
- Ensuite, résume en FR au format:

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


async def run_tool_call_loop(async_client: AsyncOpenAI, jira_mcp: MCPRemoteHTTP, tools_openai: List[dict], messages: List[Message], max_steps: int = 8) -> List[Message]:
    for _ in range(max_steps):
        resp = await async_client.chat.completions.create(
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

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": mcp_result_to_text(result),
            })

    return messages


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
            tools_openai = mcp_tools_to_openai_tools(await jira_mcp.list_tools())

            messages: List[Message] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Récupère le ticket {TICKET_KEY} via Jira tools puis résume-le."},
            ]

            messages = await run_tool_call_loop(async_client, jira_mcp, tools_openai, messages)
            messages.append({"role": "user", "content": "Donne maintenant le résumé final au format demandé."})
            await stream_final_answer(async_client, messages)


if __name__ == "__main__":
    asyncio.run(main())