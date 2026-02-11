# gitlab_mcp_access_check.py
# Test ultra simple: connexion MCP GitLab + lecture de fichiers
#
# Env requis:
#   GITLAB_MCP_URL      ex: http://localhost:9001/mcp
#   GITLAB_PROJECT_ID   ex:    (ID numérique)
#   GITLAB_REF          ex: main  (ou master)
#
# Run:
#   python gitlab_mcp_access_check.py

from __future__ import annotations

import asyncio
import os
import inspect
from typing import Any, Dict, Optional

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


GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "").strip()
GITLAB_REF = os.environ.get("GITLAB_REF", "main").strip()


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
    """
    Supporte retours courants MCP:
    - list [{"type":"text","text":"..."}]
    - dict {"content": "..."} etc.
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
        return str(res)
    return str(res)


async def open_streamable_http_cm(url: str):
    """
    Ouvre streamable_http_client en supportant les variations.
    Retourne: (cm, read_stream, write_stream)
    """
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    cm = streamable_http_client(url)

    # async context manager attendu
    if not hasattr(cm, "__aenter__"):
        raise RuntimeError(f"streamable_http_client inattendu: {cm}")

    entered = await cm.__aenter__()
    if not isinstance(entered, tuple) or len(entered) < 2:
        raise RuntimeError(f"Format retour streamable_http_client inconnu: {entered}")

    return cm, entered[0], entered[1]


async def get_file_contents(session: ClientSession, file_path: str) -> str:
    args: Dict[str, Any] = {
        "project_id": int(GITLAB_PROJECT_ID),
        "file_path": file_path,
        "ref": GITLAB_REF,
    }
    resp = await session.call_tool("get_file_contents", args)
    content = getattr(resp, "content", resp)
    return extract_text(content)


async def main():
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")
    if not GITLAB_PROJECT_ID:
        raise RuntimeError("GITLAB_PROJECT_ID manquant (ID numérique).")
    if not GITLAB_REF:
        raise RuntimeError("GITLAB_REF manquant (main/master).")
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    print("== GitLab MCP Access Check ==")
    print(f"- URL  : {GITLAB_MCP_URL}")
    print(f"- PID  : {GITLAB_PROJECT_ID}")
    print(f"- REF  : {GITLAB_REF}")
    print("--------------------------------")

    cm, read_stream, write_stream = await open_streamable_http_cm(GITLAB_MCP_URL)

    try:
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        if hasattr(session, "initialize"):
            await session.initialize()

        # 1) Vérifie tools
        tools_resp = await session.list_tools()
        tools_list = getattr(tools_resp, "tools", tools_resp)
        tool_names = []
        for t in tools_list:
            tool_names.append(getattr(t, "name", None) or t.get("name"))

        print(f"[OK] Tools dispo: {len(tool_names)}")
        if "get_file_contents" not in tool_names:
            raise RuntimeError("Tool 'get_file_contents' introuvable côté MCP GitLab.")

        # 2) Test lecture README
        for p in ["README.md", "readme.md", "Readme.md"]:
            try:
                txt = await get_file_contents(session, p)
                if txt.strip():
                    print(f"[OK] Lecture {p} : {len(txt)} chars")
                    print("----- PREVIEW -----")
                    print(txt[:800])
                    print("-------------------")
                    break
            except Exception:
                continue
        else:
            print("[WARN] README.md non lu (peut ne pas exister).")

        # 3) Test lecture convention
        for p in ["doc/convention.md", "docs/convention.md", "convention.md"]:
            try:
                txt = await get_file_contents(session, p)
                if txt.strip():
                    print(f"[OK] Lecture {p} : {len(txt)} chars")
                    print("----- PREVIEW -----")
                    print(txt[:800])
                    print("-------------------")
                    break
            except Exception as e:
                continue
        else:
            print("[WARN] convention.md non lu (peut ne pas exister ou path différent).")

        print("\n✅ Accès MCP GitLab OK (connexion + lecture fichier).")

        await session.__aexit__(None, None, None)

    finally:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())