# jira_gitlab_summary_keywords.py
# 1) Jira MCP: récupère ticket + résumé
# 2) GitLab MCP: get_project + tree(doc) + doc/convention.md
# 3) LLM: propose quelles fonctions/keywords du framework utiliser pour écrire la feuille Robot

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

JIRA_MCP_URL = os.environ.get("JIRA_MCP_URL", "").strip()
JIRA_KEY = os.environ.get("JIRA_KEY", "").strip()

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()
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
        for k in ("content", "text", "body", "description", "data", "result"):
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

def find_tool_name(tool_names: List[str], preferred: List[str]) -> Optional[str]:
    # match exact
    for p in preferred:
        if p in tool_names:
            return p
    # match fuzzy contains
    lowered = [t.lower() for t in tool_names]
    for p in preferred:
        pl = p.lower()
        for i, t in enumerate(lowered):
            if pl in t:
                return tool_names[i]
    return None

# -----------------------------------------------------------------------------
# Run one forced tool call (like your STEP)
# -----------------------------------------------------------------------------
async def run_forced_tool_call(
    llm: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: List[Dict[str, Any]],
    expected_tool: str,
    messages: List[Dict[str, str]],
) -> Any:
    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=openai_tools,
        tool_choice="auto",
        temperature=0.0,
    )

    msg = resp.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError(f"Aucun tool_call généré. Message: {msg.content}")

    tc = msg.tool_calls[0]
    tool_name = tc.function.name
    args = json.loads(tc.function.arguments or "{}")

    if tool_name != expected_tool:
        raise RuntimeError(f"Tool inattendu: {tool_name} (attendu: {expected_tool})")

    print(f"\n[TOOL_CALL] {tool_name} args={args}")
    return await mcp.call_tool(tool_name, args)

# -----------------------------------------------------------------------------
# JIRA: get issue (tool) then summarize (LLM)
# -----------------------------------------------------------------------------
async def jira_fetch_and_summarize(llm: AsyncOpenAI) -> Dict[str, Any]:
    if not JIRA_MCP_URL or not JIRA_KEY:
        raise RuntimeError("JIRA_MCP_URL et JIRA_KEY sont requis.")

    transport_cm, jira = await open_mcp(JIRA_MCP_URL)
    try:
        tools_resp = await jira.list_tools()
        openai_tools = mcp_tools_to_openai(tools_resp)
        tool_names = [t["function"]["name"] for t in openai_tools]

        # Tool Jira le plus probable pour lire un ticket
        issue_tool = find_tool_name(
            tool_names,
            preferred=[
                "get_issue",
                "jira_get_issue",
                "get_jira_issue",
                "get_issue_by_key",
                "issue_get",
            ],
        )
        if not issue_tool:
            raise RuntimeError(
                "Impossible de trouver un tool Jira pour récupérer un ticket. "
                f"Tools disponibles (extrait): {tool_names[:40]}"
            )

        # IMPORTANT: on met l'argument DANS le message pour que le modèle construise le bon JSON.
        # Ici, selon l'implémentation, l'arg peut s'appeler key / issue_key / jira_key / ticket_key.
        # Le modèle décidera en lisant le schema tool.
        messages = [
            {
                "role": "system",
                "content": (
                    f"Tu dois appeler EXACTEMENT le tool {issue_tool} pour récupérer un ticket Jira.\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Récupère le ticket Jira '{JIRA_KEY}'. "
                    "Utilise l'argument attendu par le tool (ex: key/issue_key/jira_key)."
                ),
            },
        ]

        issue_raw = await run_forced_tool_call(
            llm=llm,
            mcp=jira,
            openai_tools=openai_tools,
            expected_tool=issue_tool,
            messages=messages,
        )

        issue_text = truncate(extract_text(issue_raw), 14000)

        # Résumé LLM (sans tools)
        system = (
            "Tu es QA Automation. Résume un ticket Jira de façon actionnable pour écrire un test Robot Framework.\n"
            "Retourne STRICTEMENT ce format:\n"
            "- Titre:\n"
            "- Objectif:\n"
            "- Préconditions:\n"
            "- Étapes (Given/When/Then):\n"
            "- Données (inputs/valeurs):\n"
            "- Résultats attendus:\n"
            "- Points d'attention:\n"
        )
        user = f"TICKET_KEY: {JIRA_KEY}\n\nCONTENU:\n{issue_text}"

        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=900,
        )
        summary = (resp.choices[0].message.content or "").strip()

        return {
            "jira_key": JIRA_KEY,
            "issue_tool": issue_tool,
            "issue_raw": normalize(issue_raw),
            "issue_summary": summary,
        }

    finally:
        try:
            await jira.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await transport_cm.__aexit__(None, None, None)
        except Exception:
            pass

# -----------------------------------------------------------------------------
# GITLAB steps: get_project + get_repository_tree(doc) + get_file_contents(doc/convention.md)
# PATH/FILE_PATH uniquement dans messages (comme tu veux)
# -----------------------------------------------------------------------------
def build_gitlab_messages_for_step(step: int) -> Tuple[str, List[Dict[str, str]]]:
    if step == 1:
        tool = "get_project"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_project avec l'argument project_id (string). "
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
                    "Utilise project_id, ref, recursive, path.\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_repository_tree pour project_id='{PROJECT_ID}', ref='{GITLAB_REF}', "
                    "recursive=true, path='doc'."
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
                    "Utilise project_id, ref, file_path.\n"
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

    raise ValueError("step doit être 1,2,3")

async def gitlab_run_step(
    llm: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: List[Dict[str, Any]],
    step: int,
) -> Any:
    expected_tool, messages = build_gitlab_messages_for_step(step)
    return await run_forced_tool_call(llm, mcp, openai_tools, expected_tool, messages)

# -----------------------------------------------------------------------------
# Final: propose keywords/fonctions à utiliser (à partir Jira summary + convention + tree)
# -----------------------------------------------------------------------------
async def recommend_keywords_and_plan(llm: AsyncOpenAI, payload: Dict[str, Any]) -> str:
    system = (
        "Tu es un expert Robot Framework + framework existant.\n"
        "On te donne:\n"
        "- un résumé Jira (scénario attendu)\n"
        "- la convention du framework (doc/convention.md)\n"
        "- un tree du dossier doc (pour repérer ressources/structure)\n\n"
        "Ta mission:\n"
        "1) Déduire les imports/resources typiques à utiliser\n"
        "2) Décrire les keywords/fonctions à rechercher/réutiliser dans le repo\n"
        "3) Proposer un squelette de test Robot (Settings/Variables/Test Cases) basé sur le Jira\n\n"
        "IMPORTANT:\n"
        "- Si tu ne vois pas les keywords exacts, propose des 'keywords à rechercher' (patterns de noms)\n"
        "- Donne une liste concrète de fichiers à lire ensuite (ex: resources/*.robot, keywords/*.robot)\n"
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
    if not JIRA_MCP_URL or not JIRA_KEY:
        raise RuntimeError("JIRA_MCP_URL et JIRA_KEY manquants.")

    print("=== Jira + GitLab MCP + recommandations keywords ===")
    print(f"- JIRA_MCP_URL   : {JIRA_MCP_URL}")
    print(f"- JIRA_KEY       : {JIRA_KEY}")
    print(f"- GITLAB_MCP_URL : {GITLAB_MCP_URL}")
    print(f"- PROJECT_ID     : {PROJECT_ID}")
    print(f"- REF            : {GITLAB_REF}")
    print(f"- MODEL          : {LLM_MODEL}")
    print(f"- PROXY_URL      : {PROXY_URL or '(none)'}")
    print("---------------------------------------------------")

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

        # 1) Jira summary
        jira_part = await jira_fetch_and_summarize(llm)
        print("\n=== JIRA SUMMARY ===\n")
        print(jira_part["issue_summary"])

        # 2) GitLab
        transport_cm, gitlab = await open_mcp(GITLAB_MCP_URL)
        try:
            tools_resp = await gitlab.list_tools()
            openai_tools = mcp_tools_to_openai(tools_resp)
            tool_names = [t["function"]["name"] for t in openai_tools]

            for required in ("get_project", "get_repository_tree", "get_file_contents"):
                if required not in tool_names:
                    raise RuntimeError(f"Tool GitLab manquant: {required}")

            project_res = await gitlab_run_step(llm, gitlab, openai_tools, step=1)
            tree_res = await gitlab_run_step(llm, gitlab, openai_tools, step=2)
            conv_res = await gitlab_run_step(llm, gitlab, openai_tools, step=3)

            payload = {
                "jira": {
                    "key": jira_part["jira_key"],
                    "summary": jira_part["issue_summary"],
                },
                "gitlab": {
                    "project_id": PROJECT_ID,
                    "ref": GITLAB_REF,
                    "project": normalize(project_res),
                    "tree_doc": normalize(tree_res),
                    "convention_md": {
                        "path": "doc/convention.md",
                        "content": truncate(extract_text(conv_res), 12000),
                    },
                },
            }

            print("\n=== RECOMMANDATIONS (keywords + squelette) ===\n")
            reco = await recommend_keywords_and_plan(llm, payload)
            print(reco)

        finally:
            try:
                await gitlab.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await transport_cm.__aexit__(None, None, None)
            except Exception:
                pass

    print("\n--- DONE ---")

if __name__ == "__main__":
    asyncio.run(main())