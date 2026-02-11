# test_gitlab_ai_get_project_proxy.py
# Test minimal AI → MCP GitLab → (get_project -> get_repository_tree -> get_file_contents) + proxy httpx
#
# Objectif:
# - Vérifier que le modèle arrive à appeler des tools MCP GitLab
# - Enchaîner plusieurs appels tools (tool loop)
# - Gérer proxy (comme ton exemple Jira)
#
# Prérequis:
#   pip install openai httpx
#
# ENV:
#   OPENAI_API_KEY
#   OPENAI_BASE_URL        (optionnel)
#   OPENAI_MODEL           (ex: magistral-2509)
#   PROXY_URL              (optionnel, ex: http://user:pass@proxy:8080)
#
#   GITLAB_MCP_URL         (ex: http://localhost:9001/mcp)
#   GITLAB_PROJECT_ID      (ex: 10)
#   GITLAB_REF             (optionnel, ex: main)
#
# Notes importantes (vu sur tes erreurs):
# - Ton MCP GitLab attend souvent `file_path` (pas `path`) pour get_file_contents
# - get_repository_tree: `path` = chemin DANS le repo (ex: "docs"), pas un path local PC.

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional, List, Tuple

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
PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "10").strip()
GITLAB_REF = os.environ.get("GITLAB_REF", "").strip() or ""  # optionnel

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


async def open_mcp(url: str) -> Tuple[Any, ClientSession]:
    """
    Ouvre MCP streamable-http proprement et retourne:
    - transport_cm (pour __aexit__)
    - session (ClientSession)
    """
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


def build_tool_param_index(openai_tools: List[Dict[str, Any]]) -> Dict[str, set]:
    """
    Indexe les paramètres attendus par tool pour injecter project_id/ref si nécessaire.
    """
    idx: Dict[str, set] = {}
    for t in openai_tools:
        fn = t.get("function", {})
        name = fn.get("name")
        params = fn.get("parameters", {}) or {}
        props = (params.get("properties", {}) or {})
        idx[name] = set(props.keys())
    return idx


def inject_common_args(tool_params: set, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Injecte project_id et ref si le tool les attend.
    """
    out = dict(args or {})

    # project_id
    if "project_id" in tool_params and "project_id" not in out:
        out["project_id"] = PROJECT_ID

    # ref
    if GITLAB_REF and "ref" in tool_params and "ref" not in out:
        out["ref"] = GITLAB_REF

    return out


def fix_args_for_known_tools(tool_name: str, tool_params: set, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fixe les divergences fréquentes (vu sur tes logs):
    - get_file_contents attend souvent file_path (pas path)
    - certains outils attendent project_id (toujours injecté si présent)
    """
    out = dict(args or {})

    if tool_name == "get_file_contents":
        # Si le modèle envoie "path", convertir vers "file_path" si requis
        if "file_path" in tool_params and "file_path" not in out:
            if "path" in out:
                out["file_path"] = out.pop("path")

        # Si aucun des deux n'est présent, on met un défaut si le modèle oublie
        # (tu peux commenter si tu veux forcer le modèle)
        if "file_path" in tool_params and "file_path" not in out:
            out["file_path"] = "docs/conventions.md"

    return out


async def run_tool_loop(
    async_client: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    max_steps: int = 8,
) -> List[Dict[str, Any]]:
    """
    Exécute un loop tool-calling (non-streaming) :
    - Le modèle demande un tool
    - On l'exécute via MCP
    - On renvoie le résultat au modèle
    - Jusqu'à réponse finale
    """
    tool_params_index = build_tool_param_index(openai_tools)

    for step in range(1, max_steps + 1):
        print(f"\n--- TOOL LOOP step {step}/{max_steps} ---")

        resp = await async_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            temperature=0.0,
        )

        msg = resp.choices[0].message

        # Pas de tool calls => fin
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            print("\n=== FINAL ANSWER ===\n")
            print(msg.content or "")
            return messages

        # Ajouter le message assistant qui contient les tool_calls
        messages.append(msg)

        # Exécuter chaque tool call
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            raw_args = tc.function.arguments or "{}"

            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception:
                args = {"_raw": raw_args}

            params = tool_params_index.get(tool_name, set())

            # Inject project_id/ref si attendus
            args = inject_common_args(params, args)
            # Fix spécifiques
            args = fix_args_for_known_tools(tool_name, params, args)

            print(f"[TOOL_CALL] {tool_name} args={args}")

            try:
                result = await mcp.call_tool(tool_name, args)
                norm = normalize(getattr(result, "content", result))
            except Exception as e:
                norm = {"error": str(e), "tool": tool_name, "args": args}

            # Affiche un preview
            preview = json.dumps(norm, ensure_ascii=False, indent=2)
            print("[TOOL_RESULT preview]")
            print(preview[:2000] + ("\n...[TRUNCATED]..." if len(preview) > 2000 else ""))

            # Renvoie résultat au modèle
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tool_name,
                    "content": json.dumps(norm, ensure_ascii=False),
                }
            )

    # Si max_steps atteint
    print("\n[WARN] max_steps atteint, arrêt du loop.")
    return messages


# -----------------------------------------------------------------------------
async def main():
    if not LLM_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    print("=== TEST AI → MCP GitLab (proxy) : get_project -> tree -> file -> synthèse ===")
    print(f"- GITLAB_MCP_URL: {GITLAB_MCP_URL}")
    print(f"- PROJECT_ID   : {PROJECT_ID}")
    print(f"- GITLAB_REF   : {GITLAB_REF or '(default)'}")
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
            print(" - " + "\n - ".join(tool_names[:35]) + ("...\n" if len(tool_names) > 35 else "\n"))

            # Check minimal
            if "get_project" not in tool_names:
                raise RuntimeError("Tool get_project introuvable côté MCP GitLab.")
            if "get_file_contents" not in tool_names:
                print("[WARN] Tool get_file_contents absent -> on ne pourra pas lire un fichier.")
            if "get_repository_tree" not in tool_names:
                print("[WARN] Tool get_repository_tree absent -> on ne pourra pas explorer l'arbo.")

            # Messages : on demande l’enchaînement (le loop gérera les tools)
            messages: List[Dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "Tu es un agent GitLab MCP.\n"
                        "Tu dois utiliser les tools MCP pour obtenir les infos.\n"
                        "Fais dans l'ordre:\n"
                        "1) get_project(project_id)\n"
                        "2) get_repository_tree(project_id, path='docs', ref si possible)\n"
                        "3) get_file_contents(project_id, file_path='docs/conventions.md', ref si possible)\n"
                        "Ensuite: fais une synthèse courte (5-10 lignes) sur le framework.\n"
                        "IMPORTANT: pour get_file_contents, l'argument attendu est file_path (pas path).\n"
                        "Le 'path' dans get_repository_tree est un chemin DANS le repo (ex: 'docs'), pas un chemin local."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Project id = {PROJECT_ID}. "
                        "Exécute la séquence et termine par une synthèse."
                    ),
                },
            ]

            await run_tool_loop(
                async_client=async_client,
                mcp=mcp,
                openai_tools=openai_tools,
                messages=messages,
                max_steps=8,
            )

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
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())