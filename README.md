# ai_get_project_test.py
# Test: OpenAI -> tool call -> GitLab MCP get_project(project_id="10")
#
# Env requis:
#   OPENAI_API_KEY
#   GITLAB_MCP_URL   ex: http://localhost:9001/mcp
# Optionnel:
#   OPENAI_BASE_URL
#   OPENAI_MODEL     ex: magistral-2509

from __future__ import annotations

import asyncio
import inspect
import json
import os
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

# -----------------------------------------------------------------------------
# MCP imports (adapte à ton install)
# -----------------------------------------------------------------------------
MCP_IMPORT_ERROR = None
try:
    from mcp.client.streamable_http import streamable_http_client  # type: ignore
    from mcp.client.session import ClientSession  # type: ignore
except Exception as e1:
    MCP_IMPORT_ERROR = e1
    try:
        from mcpclient.streamable_http import streamable_http_client  # type: ignore
        from mcpclient.session import ClientSession  # type: ignore
        MCP_IMPORT_ERROR = None
    except Exception as e2:
        MCP_IMPORT_ERROR = e2


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "magistral-2509").strip()

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()

PROJECT_ID = "10"  # demandé


def normalize_mcp_content(content: Any) -> Any:
    if content is None:
        return None
    if isinstance(content, (str, int, float, bool)):
        return content
    if isinstance(content, dict):
        return {k: normalize_mcp_content(v) for k, v in content.items()}
    if isinstance(content, list):
        return [normalize_mcp_content(x) for x in content]
    if hasattr(content, "type") and hasattr(content, "text"):
        return {"type": getattr(content, "type"), "text": getattr(content, "text")}
    if hasattr(content, "__dict__"):
        return {k: normalize_mcp_content(v) for k, v in content.__dict__.items()}
    return str(content)


async def open_streamable_http_cm(url: str):
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    cm = streamable_http_client(url)
    if not hasattr(cm, "__aenter__"):
        raise RuntimeError(f"streamable_http_client inattendu: {cm}")

    entered = await cm.__aenter__()
    if not isinstance(entered, tuple) or len(entered) < 2:
        raise RuntimeError(f"Format retour streamable_http_client inconnu: {entered}")

    return cm, entered[0], entered[1]


def mcp_tools_to_openai(tools: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        name = getattr(t, "name", None) or t.get("name")
        desc = getattr(t, "description", None) or t.get("description", "") or ""
        schema = getattr(t, "inputSchema", None) or t.get("inputSchema") or {}
        if not schema:
            schema = {"type": "object", "properties": {}, "additionalProperties": True}

        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": schema,
                },
            }
        )
    return out


async def main():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    print("== Test OpenAI -> GitLab MCP get_project ==")
    print(f"- MODEL: {OPENAI_MODEL}")
    print(f"- MCP  : {GITLAB_MCP_URL}")
    print(f"- project_id: {PROJECT_ID}")
    print("--------------------------------------------------")

    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    transport_cm, read_stream, write_stream = await open_streamable_http_cm(GITLAB_MCP_URL)

    try:
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        if hasattr(session, "initialize"):
            await session.initialize()

        # Liste tools -> conversion OpenAI
        tools_resp = await session.list_tools()
        tools_list = getattr(tools_resp, "tools", tools_resp)
        tool_names = [(getattr(t, "name", None) or t.get("name")) for t in tools_list]
        if "get_project" not in tool_names:
            raise RuntimeError("Tool 'get_project' introuvable sur ton MCP GitLab.")

        openai_tools = mcp_tools_to_openai(tools_list)

        async def exec_tool(name: str, args: Dict[str, Any]) -> Any:
            resp = await session.call_tool(name, args)
            return normalize_mcp_content(getattr(resp, "content", resp))

        # Prompt: on force l'appel
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu es un assistant technique. "
                    "Tu dois appeler l'outil get_project avec project_id='10' puis résumer le résultat."
                ),
            },
            {"role": "user", "content": "Appelle get_project avec project_id='10'."},
        ]

        stream = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            stream=True,
            temperature=0.0,
        )

        tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        assistant_text_parts: List[str] = []

        async for chunk in stream:
            delta = chunk.choices[0].delta

            if getattr(delta, "content", None):
                print(delta.content, end="", flush=True)
                assistant_text_parts.append(delta.content)

            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    tool_calls_acc.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                    if getattr(tc, "id", None):
                        tool_calls_acc[idx]["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            tool_calls_acc[idx]["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            tool_calls_acc[idx]["arguments"] += fn.arguments

        assistant_text = "".join(assistant_text_parts).strip()
        if assistant_text:
            print("\n\n--- Assistant said (pre-tool) ---")
            print(assistant_text)

        # Exécute les tool calls détectés
        if not tool_calls_acc:
            print("\n[WARN] Aucun tool call détecté. (Le modèle n'a pas appelé get_project.)")
            return

        for _, tc in sorted(tool_calls_acc.items(), key=lambda x: x[0]):
            name = tc["name"]
            args_str = tc["arguments"] or "{}"
            try:
                args = json.loads(args_str)
            except Exception:
                args = {"_raw": args_str}

            print(f"\n=== TOOL_CALL: {name} args={args} ===")
            result = await exec_tool(name, args)
            print("=== TOOL_RESULT (raw) ===")
            print(json.dumps(result, ensure_ascii=False, indent=2))

    finally:
        try:
            await session.__aexit__(None, None, None)  # type: ignore
        except Exception:
            pass
        try:
            await transport_cm.__aexit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())