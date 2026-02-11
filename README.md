from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

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
MAX_ROBOT_SAMPLES = int(os.environ.get("MAX_ROBOT_SAMPLES", "2"))

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
    """
    gitlab-mcp peut renvoyer list[TextContent] ou dict etc.
    """
    r = normalize(result)
    if r is None:
        return ""
    if isinstance(r, str):
        return r
    if isinstance(r, list):
        parts = []
        for item in r:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(r, dict):
        # selon impl
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

async def llm_force_one_tool_call(
    llm: AsyncOpenAI,
    model: str,
    tools: List[Dict[str, Any]],
    tool_name: str,
    user_instruction: str,
) -> Dict[str, Any]:
    """
    Demande au modèle de générer UN tool_call (et seulement celui-là).
    Retourne args dict.
    """
    messages = [
        {
            "role": "system",
            "content": (
                f"Tu dois appeler EXACTEMENT le tool {tool_name}. "
                "Ne réponds pas en texte normal. "
                "Ne fais qu'un seul tool_call."
            ),
        },
        {"role": "user", "content": user_instruction},
    ]

    resp = await llm.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.0,
    )

    msg = resp.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError(f"Aucun tool_call généré pour {tool_name}")

    tc = msg.tool_calls[0]
    if tc.function.name != tool_name:
        raise RuntimeError(f"Le modèle a appelé {tc.function.name} au lieu de {tool_name}")

    args = json.loads(tc.function.arguments or "{}")
    return args

def collect_paths_from_tree(tree_res: Any) -> List[str]:
    t = normalize(tree_res)
    paths: List[str] = []

    # souvent: list[{"path": "...", "type": "blob/tree"}]
    if isinstance(t, list):
        for it in t:
            if isinstance(it, dict):
                p = it.get("path") or it.get("name")
                if isinstance(p, str):
                    paths.append(p)
        return paths

    # parfois: dict avec "items"/"data"
    if isinstance(t, dict):
        for key in ("items", "tree", "data", "result"):
            v = t.get(key)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        p = it.get("path") or it.get("name")
                        if isinstance(p, str):
                            paths.append(p)
    return paths

# -----------------------------------------------------------------------------
# Synthesis (no tools)
# -----------------------------------------------------------------------------
async def synthesize(llm: AsyncOpenAI, payload: Dict[str, Any]) -> str:
    system = (
        "Tu es un expert QA Automation (Robot Framework). "
        "On te donne des extraits d'un repo GitLab (conventions + structure + exemples). "
        "Produis une synthèse actionnable pour générer de nouveaux tests.\n\n"
        "Format attendu:\n"
        "1) Accès repo (OK/KO) + infos projet\n"
        "2) Architecture repo (dossiers clés)\n"
        "3) Conventions Robot Framework (naming, tags, setup/teardown, resources)\n"
        "4) Patterns repérés dans les suites (structure, variables, imports)\n"
        "5) Liste des keywords/ressources importants (si visibles)\n"
        "6) Checklist pour générer une nouvelle suite .robot conforme\n"
        "Cite les fichiers utilisés."
    )

    user = "PAYLOAD:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=1400,
    )

    return (resp.choices[0].message.content or "").strip()

# -----------------------------------------------------------------------------
async def main():
    if not LLM_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    print("=== GitLab MCP → collecte → synthèse ===")
    print(f"- MCP URL   : {GITLAB_MCP_URL}")
    print(f"- Project   : {PROJECT_ID}")
    print(f"- Ref       : {GITLAB_REF}")
    print(f"- Model     : {LLM_MODEL}")
    print(f"- Proxy     : {PROXY_URL or '(none)'}")
    print("--------------------------------------------------")

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

            for needed in ("get_project", "get_repository_tree", "get_file_contents"):
                if needed not in tool_names:
                    print(f"[WARN] Tool manquant: {needed}")

            payload: Dict[str, Any] = {
                "project_id": PROJECT_ID,
                "ref": GITLAB_REF,
                "files_used": [],
                "project": None,
                "tree_root_preview": [],
                "tree_docs_preview": [],
                "tree_tests_preview": [],
                "convention": None,
                "readme": None,
                "robot_samples": [],
            }

            # 1) get_project
            if "get_project" in tool_names:
                args = await llm_force_one_tool_call(
                    llm,
                    LLM_MODEL,
                    openai_tools,
                    "get_project",
                    f"Appelle get_project avec project_id='{PROJECT_ID}'.",
                )
                project_res = await mcp.call_tool("get_project", args)
                payload["project"] = normalize(project_res)

            # 2) repository tree (root + doc + tests) => ça aide à trouver les bons chemins
            def tree_call(path: str) -> Any:
                return mcp.call_tool(
                    "get_repository_tree",
                    {"project_id": PROJECT_ID, "path": path, "ref": GITLAB_REF, "recursive": True},
                )

            if "get_repository_tree" in tool_names:
                root_tree = await tree_call("")
                root_paths = collect_paths_from_tree(root_tree)
                payload["tree_root_preview"] = root_paths[:120]

                docs_tree = await tree_call("doc")
                docs_paths = collect_paths_from_tree(docs_tree)
                payload["tree_docs_preview"] = docs_paths[:120]

                tests_tree = await tree_call("tests")
                tests_paths = collect_paths_from_tree(tests_tree)
                payload["tree_tests_preview"] = tests_paths[:120]

                # 3) lire convention.md (trouver le bon chemin via previews)
                convention_candidates = [
                    "doc/convention.md",
                    "docs/convention.md",
                    "doc/conventions.md",
                    "convention.md",
                ]
                # si le tree doc montre quelque chose proche, on pousse en tête
                for p in docs_paths:
                    if isinstance(p, str) and p.lower().endswith("convention.md"):
                        convention_candidates.insert(0, p)

                conv_text = None
                conv_path = None
                for p in convention_candidates:
                    try:
                        res = await mcp.call_tool(
                            "get_file_contents",
                            {"project_id": PROJECT_ID, "file_path": p, "ref": GITLAB_REF},
                        )
                        txt = extract_text(res).strip()
                        if txt:
                            conv_text = truncate(txt)
                            conv_path = p
                            break
                    except Exception:
                        continue

                if conv_path:
                    payload["files_used"].append(conv_path)
                    payload["convention"] = {"path": conv_path, "content": conv_text}

                # 4) README
                for rp in ("README.md", "readme.md"):
                    try:
                        res = await mcp.call_tool(
                            "get_file_contents",
                            {"project_id": PROJECT_ID, "file_path": rp, "ref": GITLAB_REF},
                        )
                        txt = extract_text(res).strip()
                        if txt:
                            payload["files_used"].append(rp)
                            payload["readme"] = {"path": rp, "content": truncate(txt, 8000)}
                            break
                    except Exception:
                        pass

                # 5) 1-2 exemples .robot
                all_candidates = []
                for p in tests_paths + root_paths:
                    if isinstance(p, str) and p.lower().endswith(".robot"):
                        all_candidates.append(p)
                all_candidates = all_candidates[: max(20, MAX_ROBOT_SAMPLES * 10)]

                picked: List[str] = []
                for p in all_candidates:
                    if len(picked) >= MAX_ROBOT_SAMPLES:
                        break
                    # préfère ceux dans tests/
                    if p.startswith("tests/"):
                        picked.append(p)
                # fallback si pas assez
                for p in all_candidates:
                    if len(picked) >= MAX_ROBOT_SAMPLES:
                        break
                    if p not in picked:
                        picked.append(p)

                for p in picked:
                    try:
                        res = await mcp.call_tool(
                            "get_file_contents",
                            {"project_id": PROJECT_ID, "file_path": p, "ref": GITLAB_REF},
                        )
                        txt = extract_text(res).strip()
                        if txt:
                            payload["files_used"].append(p)
                            payload["robot_samples"].append({"path": p, "content": truncate(txt, 9000)})
                    except Exception:
                        pass

            # 6) Synthèse (sans tools)
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