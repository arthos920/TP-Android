# gitlab_mcp_access_check.py
from __future__ import annotations

import asyncio
import inspect
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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
GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()          # ex: http://localhost:9001/mcp
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "").strip()    # ex: 284
GITLAB_REF = os.environ.get("GITLAB_REF", "main").strip()              # main/master/...
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "").strip()              # optionnel (remote auth)

# timeouts/pagination
PER_PAGE = int(os.environ.get("GITLAB_TREE_PER_PAGE", "100"))


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


async def open_streamable_http_cm(url: str, headers: Optional[Dict[str, str]] = None):
    """
    Ouvre le transport streamable-http et retourne (cm, read_stream, write_stream)
    en gérant les libs qui supportent ou non "headers".
    """
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
        # fallback tuple direct
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
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        if MCP_IMPORT_ERROR is not None:
            raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")
        if not url:
            raise ValueError("URL MCP vide.")
        self.url = url
        self.headers = headers
        self._session: Optional[ClientSession] = None
        self._transport_cm = None

    async def __aenter__(self) -> "MCPClient":
        self._transport_cm, read_stream, write_stream = await open_streamable_http_cm(
            self.url, headers=self.headers
        )
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


def short_tree_preview(items: Any, limit: int = 30) -> List[Dict[str, Any]]:
    items = normalize_mcp_content(items)
    if not isinstance(items, list):
        return [{"_raw": items}]
    out = []
    for it in items[:limit]:
        if isinstance(it, dict):
            out.append(
                {
                    "type": it.get("type"),
                    "path": it.get("path"),
                    "name": it.get("name"),
                }
            )
        else:
            out.append({"_raw": it})
    return out


async def main():
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")
    if not GITLAB_PROJECT_ID:
        raise RuntimeError("GITLAB_PROJECT_ID manquant (ex: 284).")

    headers = None
    if GITLAB_TOKEN:
        # Remote auth: le serveur attend un header Authorization ou Private-Token
        headers = {"Authorization": f"Bearer {GITLAB_TOKEN}"}

    print("== GitLab MCP Access Check ==")
    print(f"- MCP URL    : {GITLAB_MCP_URL}")
    print(f"- Project ID : {GITLAB_PROJECT_ID}")
    print(f"- Ref        : {GITLAB_REF}")
    print(f"- Auth hdr   : {'YES' if headers else 'NO'}")
    print("--------------------------------------------------")

    async with MCPClient(GITLAB_MCP_URL, headers=headers) as mcp:
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        print(f"[OK] Tools dispo: {len(tool_names)}")

        if "get_project" not in tool_names:
            raise RuntimeError("Tool get_project introuvable côté MCP GitLab.")
        if "get_repository_tree" not in tool_names:
            raise RuntimeError("Tool get_repository_tree introuvable côté MCP GitLab.")

        # 1) get_project
        project = await mcp.call_tool("get_project", {"project_id": GITLAB_PROJECT_ID})
        print("\n--- get_project OK ---")
        print(json.dumps(project, ensure_ascii=False, indent=2)[:2000])

        # 2) get_repository_tree root
        tree_root = await mcp.call_tool(
            "get_repository_tree",
            {
                "project_id": GITLAB_PROJECT_ID,
                "path": "",            # root du repo
                "ref": GITLAB_REF,
                "recursive": False,
                "per_page": PER_PAGE,
            },
        )
        print("\n--- get_repository_tree(root) OK ---")
        print(json.dumps(short_tree_preview(tree_root, 40), ensure_ascii=False, indent=2))

        # 3) si "tests" est présent, on liste tests/
        root_items = normalize_mcp_content(tree_root)
        has_tests = False
        if isinstance(root_items, list):
            for it in root_items:
                if isinstance(it, dict) and it.get("type") == "tree" and it.get("path") == "tests":
                    has_tests = True
                    break

        if has_tests:
            tree_tests = await mcp.call_tool(
                "get_repository_tree",
                {
                    "project_id": GITLAB_PROJECT_ID,
                    "path": "tests",
                    "ref": GITLAB_REF,
                    "recursive": True,
                    "per_page": PER_PAGE,
                },
            )
            print("\n--- get_repository_tree(tests, recursive) OK ---")
            print(json.dumps(short_tree_preview(tree_tests, 60), ensure_ascii=False, indent=2))

    print("\n--- DONE ---")


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())