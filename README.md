from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# >>> IMPORTANT: le tool get_repository_tree attend "project_id" (string) :
#                on part sur ID numérique => ex: "123456"
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "").strip()

# branche/tag (optionnel)
GITLAB_REF = os.environ.get("GITLAB_REF", "").strip() or ""  # ex: main/master

# limites lecture
MAX_FILE_CHARS = int(os.environ.get("MAX_FILE_CHARS", "14000"))
MAX_FILES = int(os.environ.get("MAX_FILES", "6"))

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

def extract_text_from_file_result(res: Any) -> str:
    """
    Supporte différents formats de retour:
    - dict {content: "..."} / {text:"..."}
    - list [{"type":"text","text":"..."}]
    - string
    """
    res = normalize_mcp_content(res)
    if res is None:
        return ""
    if isinstance(res, str):
        return res
    if isinstance(res, list):
        parts = []
        for x in res:
            if isinstance(x, dict) and "text" in x:
                parts.append(str(x["text"]))
            else:
                parts.append(str(x))
        return "\n".join(parts)
    if isinstance(res, dict):
        for k in ("content", "text", "file_content", "body", "data"):
            v = res.get(k)
            if isinstance(v, str):
                return v
        # parfois payload nested
        if "result" in res and isinstance(res["result"], str):
            return res["result"]
        return json.dumps(res, ensure_ascii=False, indent=2)
    return str(res)

def truncate(s: str, n: int = MAX_FILE_CHARS) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + "\n...[TRUNCATED]..."

# -----------------------------------------------------------------------------
# MCP transport open/close (fix cancel-scope)
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

# -----------------------------------------------------------------------------
# GitLab: appels robustes (project_id/ref auto si attendu)
# -----------------------------------------------------------------------------
def build_tool_param_index(tools: List[MCPTool]) -> Dict[str, set]:
    idx: Dict[str, set] = {}
    for t in tools:
        props = (t.input_schema or {}).get("properties", {}) or {}
        idx[t.name] = set(props.keys())
    return idx

def maybe_inject_common_args(tool_params: set, args: Dict[str, Any]) -> Dict[str, Any]:
    args = dict(args or {})

    # --- FIX: project_id numérique obligatoire quand le tool le supporte ---
    # get_repository_tree (zereight/gitlab-mcp) attend "project_id" (string).
    if "project_id" in tool_params and "project_id" not in args:
        if not GITLAB_PROJECT_ID:
            raise RuntimeError(
                "GITLAB_PROJECT_ID manquant. "
                "Le tool get_repository_tree attend project_id (ID numérique ou chemin encodé). "
                "➡️ Exporte: GITLAB_PROJECT_ID=123456"
            )
        # on force string (même si numeric)
        args["project_id"] = str(GITLAB_PROJECT_ID)

    # ref/branch (optionnel)
    if GITLAB_REF and "ref" in tool_params and "ref" not in args:
        args["ref"] = GITLAB_REF

    return args

async def call_gitlab(mcp: MCPClient, tool_params_index: Dict[str, set], name: str, args: Dict[str, Any]) -> Any:
    params = tool_params_index.get(name, set())
    fixed_args = maybe_inject_common_args(params, args)
    return await mcp.call_tool(name, fixed_args)

# -----------------------------------------------------------------------------
# Repo exploration (read-only)
# -----------------------------------------------------------------------------
async def try_read_file(mcp: MCPClient, idx: Dict[str, set], path: str) -> Optional[str]:
    """
    Essaie plusieurs schémas d'args fréquemment rencontrés.
    """
    variants = [
        {"path": path},
        {"file_path": path},
        {"filepath": path},
    ]
    for v in variants:
        try:
            res = await call_gitlab(mcp, idx, "get_file_contents", v)
            txt = extract_text_from_file_result(res)
            if txt:
                return txt
        except Exception:
            continue
    return None

def _extract_next_page_token(payload: Any) -> Optional[str]:
    payload = normalize_mcp_content(payload)
    if isinstance(payload, dict):
        for k in ("next_page_token", "nextPageToken", "page_token", "pageToken", "next", "next_page"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # parfois nested
        for k in ("pagination", "meta"):
            v = payload.get(k)
            if isinstance(v, dict):
                t = _extract_next_page_token(v)
                if t:
                    return t
    return None

def _extract_items_list(payload: Any) -> List[Dict[str, Any]]:
    payload = normalize_mcp_content(payload)
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("items", "tree", "result", "data", "nodes"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []

async def get_repo_tree(mcp: MCPClient, idx: Dict[str, set], path: str = "") -> Any:
    """
    FIX zereight/gitlab-mcp:
    - project_id requis
    - path racine doit être "" (pas ".")
    - pagination keyset possible via per_page/page_token/pagination
    """
    # IMPORTANT: path racine => ""
    path = path or ""

    # args "safe defaults" pour ce MCP
    base_args: Dict[str, Any] = {
        "path": path,
        "recursive": True,
        "per_page": 100,
        "pagination": "keyset",
    }
    # ref auto-injecté si supporté (via maybe_inject_common_args)

    all_items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    last_raw: Any = None

    for _ in range(1, 50):  # garde-fou
        args = dict(base_args)
        if page_token:
            args["page_token"] = page_token

        last_raw = await call_gitlab(mcp, idx, "get_repository_tree", args)

        items = _extract_items_list(last_raw)
        if items:
            all_items.extend(items)

        next_tok = _extract_next_page_token(last_raw)
        if not next_tok:
            break
        # évite boucle infinie si token identique
        if next_tok == page_token:
            break
        page_token = next_tok

    # si on a agrégé, on renvoie une structure simple
    if all_items:
        return {"items": all_items, "count": len(all_items)}
    return last_raw

def collect_paths_from_tree(tree: Any) -> List[str]:
    tree = normalize_mcp_content(tree)
    paths: List[str] = []

    items = _extract_items_list(tree)
    if items:
        for item in items:
            p = item.get("path") or item.get("name") or item.get("file_path")
            if isinstance(p, str):
                paths.append(p)
        return paths

    # fallback legacy
    if isinstance(tree, list):
        for item in tree:
            if isinstance(item, dict):
                p = item.get("path") or item.get("name") or item.get("file_path")
                if isinstance(p, str):
                    paths.append(p)
    elif isinstance(tree, dict):
        for key in ("items", "tree", "result", "data"):
            v = tree.get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        p = item.get("path") or item.get("name") or item.get("file_path")
                        if isinstance(p, str):
                            paths.append(p)
    return paths

# -----------------------------------------------------------------------------
# OpenAI synthesis (stream)
# -----------------------------------------------------------------------------
async def stream_synthesis(openai_client: AsyncOpenAI, payload: Dict[str, Any]) -> str:
    system = (
        "Tu es un assistant QA/Automation. "
        "Tu dois analyser des extraits d'un repo Robot Framework (et conventions) et produire une synthèse claire.\n"
        "Donne:\n"
        "1) Architecture (dossiers clés)\n"
        "2) Conventions (naming, tags, setup/teardown, resources)\n"
        "3) Patterns de tests (comment les suites sont structurées)\n"
        "4) Liste des keywords/ressources importants repérés (si visible)\n"
        "5) Recommandations pour générer une nouvelle suite .robot cohérente\n"
        "Reste concret, cite les fichiers sources utilisés."
    )

    user = "Extraits GitLab:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    stream = await openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        stream=True,
        temperature=0.2,
        max_tokens=1200,
    )

    out_parts: List[str] = []
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            print(delta.content, end="", flush=True)
            out_parts.append(delta.content)
    print()
    return "".join(out_parts)

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

    print("== GitLab MCP access test + synthèse ==")
    print(f"- GITLAB_MCP_URL    : {GITLAB_MCP_URL}")
    print(f"- GITLAB_PROJECT_ID : {GITLAB_PROJECT_ID or '(non fourni)'}")
    print(f"- GITLAB_REF        : {GITLAB_REF or '(non fourni)'}")
    print(f"- MODEL             : {OPENAI_MODEL}")
    print("--------------------------------------------------")

    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    async with MCPClient(GITLAB_MCP_URL) as mcp:
        tools = await mcp.list_tools()
        tool_index = build_tool_param_index(tools)

        tool_names = [t.name for t in tools]
        print(f"[OK] Tools dispo ({len(tool_names)}):")
        print(" - " + "\n - ".join(tool_names[:60]) + ("...\n" if len(tool_names) > 60 else "\n"))

        if "get_file_contents" not in tool_names:
            raise RuntimeError("Tool get_file_contents introuvable sur ton MCP GitLab.")
        if "get_repository_tree" not in tool_names:
            print("[WARN] Tool get_repository_tree introuvable -> on fera seulement lecture convention/README si possible.")

        # 1) Lire convention.md (priorité)
        candidates = ["doc/convention.md", "docs/convention.md", "convention.md", "doc/conventions.md"]
        convention_text = None
        convention_path = None
        for p in candidates:
            txt = await try_read_file(mcp, tool_index, p)
            if txt:
                convention_text = txt
                convention_path = p
                break

        # 2) Lire README (optionnel)
        readme_text = None
        for p in ["README.md", "readme.md", "Readme.md"]:
            txt = await try_read_file(mcp, tool_index, p)
            if txt:
                readme_text = txt
                break

        # 3) Explorer tree et sélectionner 1-2 .robot (si tool dispo)
        robot_samples: List[Dict[str, str]] = []
        tree_paths: List[str] = []
        if "get_repository_tree" in tool_names:
            # >>> FIX: nécessite GITLAB_PROJECT_ID, et path="" racine
            tree = await get_repo_tree(mcp, tool_index, path="")
            tree_paths = collect_paths_from_tree(tree)

            robots = [p for p in tree_paths if isinstance(p, str) and p.lower().endswith(".robot")]
            robots_tests = [p for p in robots if p.startswith("tests/") or p.startswith("test/")]
            pick = robots_tests[:2] if robots_tests else robots[:2]

            for rp in pick:
                txt = await try_read_file(mcp, tool_index, rp)
                if txt:
                    robot_samples.append({"path": rp, "content": truncate(txt, 9000)})

        # 4) Construire payload pour synthèse
        payload = {
            "access_ok": True,
            "project_id_used": GITLAB_PROJECT_ID or None,
            "ref_used": GITLAB_REF or None,
            "files_read": [],
            "convention_md": {"path": convention_path, "content": truncate(convention_text or "", 9000)},
            "readme": truncate(readme_text or "", 6000),
            "robot_samples": robot_samples,
            "tree_hint": {
                "tree_paths_count": len(tree_paths),
                "tree_paths_preview": tree_paths[:80],
            },
        }

        if convention_path:
            payload["files_read"].append(convention_path)
        if readme_text:
            payload["files_read"].append("README.md")
        for s in robot_samples:
            payload["files_read"].append(s["path"])

        print("\n=== Synthèse (streaming) ===\n")
        await stream_synthesis(openai_client, payload)

        if "get_repository_tree" in tool_names and not GITLAB_PROJECT_ID:
            print(
                "\n[WARN] Tu as get_repository_tree mais pas de GITLAB_PROJECT_ID.\n"
                "➡️ Exporte un ID numérique:  set GITLAB_PROJECT_ID=123456\n"
            )

    print("\n--- DONE ---")

if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())