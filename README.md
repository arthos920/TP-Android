from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

import httpx
from openai import AsyncOpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ================= CONFIG =================

JIRA_MCP_URL = "http://localhost:20000/mcp"

LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"
MODEL = "magistral-2509"

PROXY_URL = "xxxx"
TICKET_KEY = "


# ================= MCP WRAPPER =================

class MCPRemoteHTTP:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self):
        transport = await self._stack.enter_async_context(
            streamable_http_client(self.url)
        )

        if isinstance(transport, tuple) and len(transport) >= 2:
            read_stream, write_stream = transport[0], transport[1]
        else:
            read_stream = transport.read_stream
            write_stream = transport.write_stream

        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)


# ================= TOOL PARSER =================

def extract_text(result) -> str:
    content = getattr(result, "content", result)

    if isinstance(content, list):
        parts = []
        for c in content:
            parts.append(getattr(c, "text", str(c)))
        return "\n".join(parts)

    return str(content)


def extract_jira_fields(text: str) -> Dict[str, str]:
    """
    Extraction simple summary + description depuis JSON Jira brut.
    """
    try:
        data = json.loads(text)
    except Exception:
        return {"summary": "N/A", "description": text[:2000]}

    fields = data.get("fields", {})

    return {
        "summary": fields.get("summary", "N/A"),
        "description": fields.get("description", "N/A"),
        "status": fields.get("status", {}).get("name", "N/A"),
        "priority": fields.get("priority", {}).get("name", "N/A"),
    }


# ================= STREAMING =================

async def stream_summary(async_client, prompt):

    print("\n--- RÉSUMÉ TICKET ---\n", end="", flush=True)

    stream = await async_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        temperature=0.2,
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)

    print("\n")


# ================= MAIN =================

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

            print("\nCALL TOOL jira_get_issue...\n")

            result = await jira_mcp.call_tool(
                "jira_get_issue",
                {
                    "issue_key": TICKET_KEY,
                    "fields": "summary,description,status,priority",
                },
            )

            raw_text = extract_text(result)
            print(f"[TOOL_RESULT chars={len(raw_text)}]\n")

            fields = extract_jira_fields(raw_text)

            prompt = f"""
Résume ce ticket Jira :

Clé: {TICKET_KEY}
Titre: {fields['summary']}
Statut: {fields['status']}
Priorité: {fields['priority']}

Description:
{fields['description']}

Fais un résumé structuré en français :
- Contexte
- Objectif
- Critères d’acceptation
- Points d’attention
"""

            await stream_summary(async_client, prompt)


if __name__ == "__main__":
    asyncio.run(main())