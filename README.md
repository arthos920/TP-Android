# gitlab_steps_then_synthesis.py
# Flow:
# 1) IA appelle get_project
# 2) IA appelle get_repository_tree (path demandé dans le message)
# 3) IA appelle get_file_contents (file_path demandé dans le message)
# 4) IA génère une synthèse (sans tools)

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Tuple, Optional

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

PROXY_URL = os.environ.get("PROXY_URL", "").strip() or None

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "http://localhost:9001/mcp").strip()
PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "10").strip()
GITLAB_REF = os.environ.get("GITLAB_REF", "main").strip()

MAX_CHARS = int(os.environ.get("MAX_CHARS", "12000"))

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

def truncate(s: str, n: int = MAX_CHARS) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + "\n...[TRUNCATED]..."

def extract_text(result: Any) -> str:
    r = normalize(result)
    if r is None:
        return ""
    if isinstance(r, str):
        return r
    if isinstance(r, list):
        parts = []
        for it in r:
            if isinstance(it, dict) and "text" in it:
                parts.append(str(it["text"]))
            else:
                parts.append(str(it))
        return "\n".join(parts)
    if isinstance(r, dict):
        for k in ("content", "text", "file_content", "body", "data", "result"):
            v = r.get(k)
            if isinstance(v, str):
                return v
        return json.dumps(r, ensure_ascii=False, indent=2)
    return str(r)

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
# STEP messages (PATH UNIQUEMENT ICI)
# -----------------------------------------------------------------------------
def build_messages_for_step(step: int) -> Tuple[str, List[Dict[str, str]]]:
    """
    Retourne (expected_tool_name, messages)
    IMPORTANT: on met path/ref/file_path DANS LES MESSAGES, pas dans le code.
    """
    if step == 1:
        tool = "get_project"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_project.\n"
                    "Arguments attendus:\n"
                    "- project_id (string)\n"
                    "Ne fais rien d'autre."
                ),
            },
            {"role": "user", "content": f"Appelle get_project avec project_id='{PROJECT_ID}'."},
        ]
        return tool, messages

    if step == 2:
        tool = "get_repository_tree"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_repository_tree.\n"
                    "Arguments attendus:\n"
                    "- project_id (string)\n"
                    "- path (string) : chemin DANS le repo (ex: '', 'doc', 'tests')\n"
                    "- ref (string) : branche/tag\n"
                    "- recursive (boolean)\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_repository_tree pour project_id='{PROJECT_ID}', "
                    f"ref='{GITLAB_REF}', recursive=true, et path='doc'."
                ),
            },
        ]
        return tool, messages

    if step == 3:
        tool = "get_file_contents"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_file_contents.\n"
                    "Arguments attendus:\n"
                    "- project_id (string)\n"
                    "- ref (string)\n"
                    "- file_path (string) : chemin DANS le repo (ex: 'doc/convention.md')\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents pour project_id='{PROJECT_ID}', ref='{GITLAB_REF}', "
                    "file_path='doc/convention.md'."
                ),
            },
        ]
        return tool, messages

    raise ValueError("step doit être 1, 2 ou 3")

# -----------------------------------------------------------------------------
# Run one step (1 tool_call)
# -----------------------------------------------------------------------------
async def run_one_step(
    llm: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: List[Dict[str, Any]],
    step: int,
) -> Any:
    expected_tool, messages = build_messages_for_step(step)

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=openai_tools,
        tool_choice="auto",
        temperature=0.0,
    )

    msg = resp.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError(f"[STEP {step}] Aucun tool_call généré. Message: {msg.content}")

    tc = msg.tool_calls[0]
    tool_name = tc.function.name
    args = json.loads(tc.function.arguments or "{}")

    if tool_name != expected_tool:
        raise RuntimeError(f"[STEP {step}] Tool inattendu: {tool_name} (attendu: {expected_tool})")

    print(f"\n[STEP {step}] TOOL_CALL => {tool_name} args={args}")
    result = await mcp.call_tool(tool_name, args)
    return result

# -----------------------------------------------------------------------------
# Synthesis (no tools)
# -----------------------------------------------------------------------------
async def synthesize(llm: AsyncOpenAI, payload: Dict[str, Any]) -> str:
    system = (
        "Tu es un expert QA Automation Robot Framework.\n"
        "Tu reçois des extraits GitLab (projet + tree + conventions).\n"
        "Fais une synthèse courte et actionnable:\n"
        "1) Structure repo\n"
        "2) Conventions importantes\n"
        "3) Ce qu'il faut respecter pour générer un nouveau .robot\n"
        "Cite les fichiers utilisés."
    )

    user = "PAYLOAD:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=1200,
    )
    return (resp.choices[0].message.content or "").strip()

# -----------------------------------------------------------------------------
async def main():
    if not LLM_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    print("=== GitLab MCP steps (path in messages) + synthèse ===")
    print(f"- MCP URL : {GITLAB_MCP_URL}")
    print(f"- Project : {PROJECT_ID}")
    print(f"- Ref     : {GITLAB_REF}")
    print(f"- Model   : {LLM_MODEL}")
    print(f"- Proxy   : {PROXY_URL or '(none)'}")
    print("-----------------------------------------------------")

    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(
        proxy=proxy,
        verify=False,
        follow_redirects=False,
        timeout=180.0,
    ) as http_client:

        llm = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        transport_cm, mcp = await open_mcp(GITLAB_MCP_URL)

        try:
            tools_resp = await mcp.list_tools()
            openai_tools = mcp_tools_to_openai(tools_resp)
            tool_names = [t["function"]["name"] for t in openai_tools]
            print(f"[OK] Tools exposés: {len(tool_names)}")

            # steps
            project_res = await run_one_step(llm, mcp, openai_tools, step=1)
            tree_res = await run_one_step(llm, mcp, openai_tools, step=2)
            conv_res = await run_one_step(llm, mcp, openai_tools, step=3)

            payload = {
                "project_id": PROJECT_ID,
                "ref": GITLAB_REF,
                "project": normalize(project_res),
                "tree_doc": normalize(tree_res),
                "convention_md": {
                    "path": "doc/convention.md",
                    "content": truncate(extract_text(conv_res), 12000),
                },
                "files_used": ["doc/convention.md"],
            }

            print("\n=== SYNTHÈSE ===\n")
            summary = await synthesize(llm, payload)
            print(summary)

        finally:
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