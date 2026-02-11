# test_gitlab_ai_toolloop_proxy.py
# Minimal AI -> MCP GitLab (streamable-http) with proxy + robust tool-loop
# Runs: get_project -> get_repository_tree -> get_file_contents (doc/convention.md)

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI
from openai import APIStatusError, APITimeoutError, APIConnectionError

# -----------------------------------------------------------------------------
# MCP imports (adapte à ton install)
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

# IMPORTANT: project_id numérique (string OK)
PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "10").strip()
GITLAB_REF = os.environ.get("GITLAB_REF", "main").strip()

# Troncature des retours tools (évite 400/413 côté LLM)
MAX_TOOL_CHARS = int(os.environ.get("MAX_TOOL_CHARS", "12000"))

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

def dumps_truncated(obj: Any, limit: int = MAX_TOOL_CHARS) -> str:
    s = json.dumps(normalize(obj), ensure_ascii=False)
    if len(s) <= limit:
        return s
    head = s[:limit]
    return head + f"\n...[TRUNCATED {len(s)-limit} chars]..."

async def open_mcp(url: str) -> Tuple[Any, ClientSession]:
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
    out: List[Dict[str, Any]] = []
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

def safe_json_loads(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s) if s else {}
    except Exception:
        # si le modèle renvoie un truc pas JSON
        return {"_raw": s}

def inject_defaults(args: Dict[str, Any]) -> Dict[str, Any]:
    # Ajoute project_id/ref si le modèle oublie
    a = dict(args or {})
    a.setdefault("project_id", PROJECT_ID)
    if "ref" not in a and GITLAB_REF:
        a["ref"] = GITLAB_REF
    return a

async def call_openai_with_retry(fn, *, retries: int = 4):
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            return await fn()
        except (APITimeoutError, APIConnectionError) as e:
            if attempt == retries:
                raise
            print(f"[WARN] OpenAI network/timeout ({type(e).__name__}), retry in {delay:.1f}s")
            await asyncio.sleep(delay)
            delay *= 2
        except APIStatusError as e:
            # retry sur erreurs transitoires
            if e.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                print(f"[WARN] OpenAI status={e.status_code}, retry in {delay:.1f}s")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise

async def run_tool_loop(
    async_client: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    max_steps: int = 8,
) -> List[Dict[str, Any]]:
    """
    Tool loop simple (non-streaming) :
    - appelle le LLM
    - exécute tool_calls
    - renvoie tool results
    - stop quand plus de tool_calls
    """
    for step in range(1, max_steps + 1):
        print(f"\n=== TOOL LOOP step {step}/{max_steps} ===")

        async def _do():
            return await async_client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.0,
            )

        try:
            resp = await call_openai_with_retry(_do, retries=4)
        except APIStatusError as e:
            print("\n[OPENAI APIStatusError]")
            print("status_code:", e.status_code)
            # e.response peut être None selon versions, mais souvent dispo:
            try:
                print("response_text:", e.response.text)  # type: ignore
            except Exception:
                print("error:", str(e))
            raise
        except Exception as e:
            print("\n[OPENAI ERROR]", repr(e))
            raise

        msg = resp.choices[0].message
        messages.append({"role": "assistant", "content": msg.content or ""})

        if not msg.tool_calls:
            print("[OK] No more tool calls. Stop.")
            return messages

        for tc in msg.tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            args = inject_defaults(safe_json_loads(raw_args))

            print(f"[TOOL_CALL] {name} args={args}")

            tool_res = await mcp.call_tool(name, args)
            tool_content = dumps_truncated(tool_res)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": tool_content,
                }
            )
            print(f"[TOOL_RESULT] {name} chars={len(tool_content)}")

    print("[WARN] max_steps reached.")
    return messages

# -----------------------------------------------------------------------------
async def main():
    if not LLM_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    print("=== TEST AI → MCP GitLab (proxy) tool-loop ===")
    print(f"- GITLAB_MCP_URL : {GITLAB_MCP_URL}")
    print(f"- PROJECT_ID     : {PROJECT_ID}")
    print(f"- REF            : {GITLAB_REF}")
    print(f"- MODEL          : {LLM_MODEL}")
    print(f"- PROXY_URL      : {PROXY_URL or '(none)'}")
    print("--------------------------------------------------")

    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(
        proxy=proxy,
        verify=False,          # corporate MITM / SSL inspect
        follow_redirects=False,
        timeout=180.0,
    ) as http_client:

        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,   # ✅ IMPORTANT (proxy)
        )

        transport_cm, mcp = await open_mcp(GITLAB_MCP_URL)

        try:
            tools_resp = await mcp.list_tools()
            openai_tools = mcp_tools_to_openai(tools_resp)
            tool_names = [t["function"]["name"] for t in openai_tools]

            print(f"[OK] Tools exposés: {len(tool_names)}")
            print(" - " + "\n - ".join(tool_names[:35]) + ("...\n" if len(tool_names) > 35 else "\n"))

            required = ["get_project", "get_repository_tree", "get_file_contents"]
            missing = [x for x in required if x not in tool_names]
            if missing:
                print("[WARN] Tools manquants:", missing)
                print("On peut quand même tester get_project si dispo.")

            system = (
                "Tu es un agent qui pilote GitLab via MCP.\n"
                "Objectif: vérifier l'accès au repo.\n"
                "Tu dois exécuter EXACTEMENT ces actions, dans cet ordre:\n"
                "1) get_project(project_id)\n"
                "2) get_repository_tree(project_id, path='doc', ref)\n"
                "   - si ça échoue ou vide: get_repository_tree(project_id, path='', ref)\n"
                "3) get_file_contents(project_id, file_path='doc/convention.md', ref)\n"
                "Puis tu termines par une réponse texte courte: "
                "résumé du projet + est-ce qu'on a trouvé doc/convention.md.\n"
                "Important:\n"
                "- 'path' = chemin DANS le repo GitLab (pas local).\n"
                "- Utilise project_id numérique.\n"
            )

            user = f"Fais le check d'accès pour project_id={PROJECT_ID} ref={GITLAB_REF}."

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            messages = await run_tool_loop(
                async_client=async_client,
                mcp=mcp,
                openai_tools=openai_tools,
                messages=messages,
                max_steps=8,
            )

            # Affiche la dernière réponse assistant (résumé)
            final_assistant = ""
            for m in reversed(messages):
                if m["role"] == "assistant" and (m.get("content") or "").strip():
                    final_assistant = m["content"].strip()
                    break

            print("\n=== FINAL ASSISTANT OUTPUT ===")
            print(final_assistant or "(no final text)")

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