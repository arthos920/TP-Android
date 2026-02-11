# test_gitlab_ai_get_project_proxy.py
# Test minimal AI → MCP GitLab → get_project (avec proxy httpx)

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional, List

import httpx
from openai import AsyncOpenAI

# -----------------------------------------------------------------------------
# MCP imports
# -----------------------------------------------------------------------------
try:
    from mcp.client.streamable_http import streamable_http_client  # type: ignore
    from mcp.client.session import ClientSession  # type: ignore
except Exception:
    from mcpclient.streamable_http import streamable_http_client  # type: ignore
    from mcpclient.session import ClientSession  # type: ignore

# -----------------------------------------------------------------------------
# ENV
# -----------------------------------------------------------------------------
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None
LLM_MODEL = os.environ.get("OPENAI_MODEL", "magistral-2509").strip()

# Proxy (comme ton exemple Jira)
PROXY_URL = os.environ.get("PROXY_URL", "").strip() or None

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "http://localhost:9001/mcp").strip()
PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "10").strip()  # ici ton test = 10

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def normalize(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, dict):
        return {k: normalize(v) for k, v in x.items()}
    if isinstance(x, list):
        return [normalize(v) for v in x]
    if hasattr(x, "type") and hasattr(x, "text"):
        return {"type": getattr(x, "type"), "text": getattr(x, "text")}
    if hasattr(x, "__dict__"):
        return normalize(x.__dict__)
    return str(x)

async def open_mcp(url: str):
    cm = streamable_http_client(url)
    entered = await cm.__aenter__()
    if not isinstance(entered, tuple) or len(entered) < 2:
        raise RuntimeError(f"streamable_http_client retour inattendu: {entered}")
    read_stream, write_stream = entered[0], entered[1]

    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    if hasattr(session, "initialize"):
        await session.initialize()
    return cm, session

def mcp_tools_to_openai(tools_resp: Any) -> List[Dict[str, Any]]:
    tools_list = getattr(tools_resp, "tools", tools_resp)
    out = []
    for t in tools_list:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema
                    or {"type": "object", "properties": {}, "additionalProperties": True},
                },
            }
        )
    return out

# -----------------------------------------------------------------------------
async def main():
    if not LLM_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    print("=== TEST AI → MCP GitLab → get_project (proxy) ===")
    print(f"- GITLAB_MCP_URL: {GITLAB_MCP_URL}")
    print(f"- PROJECT_ID   : {PROJECT_ID}")
    print(f"- MODEL        : {LLM_MODEL}")
    print(f"- PROXY_URL    : {PROXY_URL or '(none)'}")
    print("--------------------------------------------------")

    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(
        proxy=proxy,
        verify=False,          # comme ton exemple (si corporate MITM)
        follow_redirects=False,
        timeout=120.0,
    ) as http_client:

        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,   # ✅ IMPORTANT
        )

        transport_cm, mcp = await open_mcp(GITLAB_MCP_URL)

        try:
            tools_resp = await mcp.list_tools()
            openai_tools = mcp_tools_to_openai(tools_resp)

            tool_names = [t["function"]["name"] for t in openai_tools]
            print(f"[OK] Tools exposés: {len(tool_names)}")
            print(" - " + "\n - ".join(tool_names[:30]) + ("...\n" if len(tool_names) > 30 else "\n"))

            if "get_project" not in tool_names:
                raise RuntimeError("Tool get_project introuvable côté MCP GitLab.")

            # On force le modèle à appeler get_project
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Tu dois appeler EXACTEMENT le tool get_project avec l'argument project_id. "
                        "Ne réponds pas autrement."
                    ),
                },
                {"role": "user", "content": f"Appelle get_project pour project_id={PROJECT_ID}."},
            ]

            resp = await async_client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.0,
            )

            msg = resp.choices[0].message
            if not msg.tool_calls:
                print("❌ Aucun tool_call généré par le modèle.")
                print("Assistant message:", msg)
                return

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                print(f"\n[TOOL_CALL] {name} args={args}")

                result = await mcp.call_tool(name, args)

                print("\n=== RESULT (raw) ===")
                print(json.dumps(normalize(result), ensure_ascii=False, indent=2))

        finally:
            # fermeture MCP propre
            try:
                await mcp.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await transport_cm.__aexit__(None, None, None)
            except Exception:
                pass

    print("\n--- DONE ---")


if __name__ == "__main__":
    asyncio.run(main())