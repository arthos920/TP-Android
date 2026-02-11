from __future__ import annotations

import asyncio
import inspect
import json
import os
from dataclasses import dataclass
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

# -----------------------------------------------------------------------------
# ENV
# -----------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "magistral-2509").strip()

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "").strip()  # optionnel si on auto-discover
GITLAB_REF = os.environ.get("GITLAB_REF", "").strip() or "main"       # mets "master" si besoin
GITLAB_SEARCH = os.environ.get("GITLAB_SEARCH", "").strip()           # ex: "tr_pmr_agnet_test_automation"

MAX_FILE_CHARS = int(os.environ.get("MAX_FILE_CHARS", "14000"))

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
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

def extract_text(res: Any) -> str:
    res = normalize_mcp_content(res)
    if res is None:
        return ""
    if isinstance(res, str):
        return res
    if isinstance(res, list):
        # souvent [{"type":"text","text":"..."}]
        parts = []
        for x in res:
            if isinstance(x, dict) and "text" in x:
                parts.append(str(x["text"]))
            else:
                parts.append(str(x))
        return "\n".join(parts)
    if isinstance(res, dict):
        # parfois "content" / "text" / "data"
        for k in ("content", "text", "data", "body", "file_content"):
            v = res.get(k)
            if isinstance(v, str):
                return v
        return json.dumps(res, ensure_ascii=False, indent=2)
    return str(res)

def truncate(s: str, n: int = MAX_FILE_CHARS) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "\n...[TRUNCATED]..."

# -----------------------------------------------------------------------------
# MCP transport open/close (évite tes erreurs cancel-scope)
# -----------------------------------------------------------------------------
async def open_streamable_http_cm(url: str, headers: Optional[Dict[str, str]] = None):
    sig = None
    try:
        sig = inspect.signature(streamable_http_client)
    except Exception:
        sig = None

    kwargs = {}
    if headers and sig and "headers" in sig.parameters:
        kwargs["headers"] = headers

    cm = streamable_http_client(url, **kwargs) if kwargs else streamable_http_client(url)

    if not hasattr(cm, "__aenter__"):
        # fallback tuple
        if isinstance(cm, tuple) and len(cm) >= 2:
            return None, cm[0], cm[1]
        raise RuntimeError(f"streamable_http_client inattendu: {cm}")

    entered = await cm.__aenter__()
    if not isinstance(entered, tuple) or len(entered) < 2:
        raise RuntimeError(f"Format retour streamable_http_client inconnu: {entered}")

    return cm, entered[0], entered[1]

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]

class MCPClient:
    def __init__(self, url: str):
        if MCP_IMPORT_ERROR is not None:
            raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")
        if not url:
            raise ValueError("URL MCP vide.")
        self.url = url
        self._session: Optional[ClientSession] = None
        self._transport_cm = None

    async def __aenter__(self) -> "MCPClient":
        self._transport_cm, read_stream, write_stream = await open_streamable_http_cm(self.url)
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()
        if hasattr(self._session, "initialize"):
            await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session is not None:
            try:
                await self._session.__aexit__(exc_type, exc, tb)
            except Exception:
                pass
            self._session = None
        if self._transport_cm is not None:
            try:
                await self._transport_cm.__aexit__(exc_type, exc, tb)
            except Exception:
                pass
            self._transport_cm = None

    async def list_tools(self) -> List[MCPTool]:
        assert self._session is not None
        resp = await self._session.list_tools()
        tools: List[MCPTool] = []
        for t in getattr(resp, "tools", resp):
            name = getattr(t, "name", None) or t.get("name")
            desc = getattr(t, "description", None) or t.get("description", "") or ""
            schema = getattr(t, "inputSchema", None) or t.get("inputSchema") or {}
            tools.append(MCPTool(name=name, description=desc, input_schema=schema))
        return tools

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Any:
        assert self._session is not None
        resp = await self._session.call_tool(name, args)
        if hasattr(resp, "content"):
            return normalize_mcp_content(resp.content)
        return normalize_mcp_content(resp)

def tool_param_set(t: MCPTool) -> set:
    props = (t.input_schema or {}).get("properties", {}) or {}
    return set(props.keys())

# -----------------------------------------------------------------------------
# OpenAI synthèse
# -----------------------------------------------------------------------------
async def synthese(openai_client: AsyncOpenAI, content_by_file: Dict[str, str]) -> None:
    system = (
        "Tu es un assistant QA automation. Fais une synthèse du framework à partir des fichiers fournis.\n"
        "Donne: architecture, conventions, ressources/keywords repérés, recommandations pour écrire un nouveau test Robot.\n"
        "Cite les fichiers."
    )
    user = "Fichiers lus:\n" + json.dumps(content_by_file, ensure_ascii=False, indent=2)

    stream = await openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        stream=True,
        temperature=0.2,
        max_tokens=1200,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            print(delta.content, end="", flush=True)
    print()

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
async def main():
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    print("== GitLab MCP quick test (search_repositories + get_file_contents) ==")
    print(f"- GITLAB_MCP_URL    : {GITLAB_MCP_URL}")
    print(f"- GITLAB_PROJECT_ID : {GITLAB_PROJECT_ID or '(auto)'}")
    print(f"- GITLAB_REF        : {GITLAB_REF}")
    print(f"- GITLAB_SEARCH     : {GITLAB_SEARCH or '(non fourni)'}")
    print("--------------------------------------------------")

    async with MCPClient(GITLAB_MCP_URL) as mcp:
        tools = await mcp.list_tools()
        toolmap = {t.name: t for t in tools}
        print(f"[OK] Tools: {len(tools)}")

        # check tools
        if "search_repositories" not in toolmap:
            raise RuntimeError("Tool search_repositories introuvable sur ton MCP GitLab.")
        if "get_file_contents" not in toolmap:
            raise RuntimeError("Tool get_file_contents introuvable sur ton MCP GitLab.")

        # 1) Découvrir project_id si pas fourni
        project_id = GITLAB_PROJECT_ID
        if not project_id:
            if not GITLAB_SEARCH:
                raise RuntimeError(
                    "Tu n'as pas mis GITLAB_PROJECT_ID. Mets au moins GITLAB_SEARCH (nom du projet / mot clé) "
                    "pour qu'on trouve le repo via search_repositories."
                )
            print(f"\n[STEP] search_repositories(search='{GITLAB_SEARCH}')")
            res = await mcp.call_tool("search_repositories", {"search": GITLAB_SEARCH, "per_page": 20, "page": 1})
            data = normalize_mcp_content(res)

            # essaie d’extraire le 1er projet
            projects = []
            if isinstance(data, list):
                projects = data
            elif isinstance(data, dict):
                for k in ("projects", "items", "result", "data"):
                    v = data.get(k)
                    if isinstance(v, list):
                        projects = v
                        break

            if not projects:
                raise RuntimeError(f"Aucun projet retourné par search_repositories: {data}")

            # prend le premier match
            p0 = projects[0] if isinstance(projects[0], dict) else {}
            pid = p0.get("id") or p0.get("project_id") or p0.get("projectId")
            if not pid:
                raise RuntimeError(f"Impossible de récupérer un project_id depuis: {p0}")

            project_id = str(pid)
            print(f"[OK] project_id trouvé: {project_id}")
            name = p0.get("name") or p0.get("path") or p0.get("path_with_namespace")
            if name:
                print(f"[INFO] project: {name}")

        # 2) Lire des fichiers clés avec get_file_contents
        candidates = [
            "doc/convention.md",
            "docs/convention.md",
            "convention.md",
            "README.md",
            "readme.md",
        ]

        file_contents: Dict[str, str] = {}
        for path in candidates:
            args = {"project_id": project_id, "path": path, "ref": GITLAB_REF}
            try:
                print(f"\n[STEP] get_file_contents({args})")
                res = await mcp.call_tool("get_file_contents", args)
                txt = extract_text(res).strip()
                if txt:
                    file_contents[path] = truncate(txt, 12000)
                    print(f"[OK] lu: {path} ({len(txt)} chars)")
            except Exception as e:
                print(f"[SKIP] {path} -> {e}")

        if not file_contents:
            raise RuntimeError(
                "Aucun fichier n'a pu être lu. "
                "Vérifie: project_id, ref (main/master), et le path exact dans le repo."
            )

        # 3) Synthèse IA
        print("\n=== Synthèse IA (streaming) ===\n")
        await synthese(openai_client, file_contents)

    print("\n--- DONE ---")

if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())