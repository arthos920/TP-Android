# gitlab_writer_only_async_streaming.py
# IA WRITER uniquement (GitLab MCP) -> génère un fichier .robot en local
# Async + streaming, MCP streamable-http
#
# Prérequis:
#   pip install openai httpx anyio
#   + ton package MCP python (streamable_http_client + ClientSession)
#
# Variables d'env attendues:
#   OPENAI_API_KEY
#   OPENAI_BASE_URL           (optionnel)
#   OPENAI_MODEL_WRITER       (ex: "magistral-2509")
#
#   GITLAB_MCP_URL            (ex: "http://localhost:9001/mcp")
#   GITLAB_PROJECT_ID         (recommandé si ton toolset le demande)
#   GITLAB_REF                (optionnel: "main" / "master")
#
#   SPEC_JSON_PATH            (ex: "./generated/AMCXSQL-1706_spec.json")
#   OUTPUT_DIR                (optionnel, défaut: "./generated")
#
# Notes:
# - Pas de commit/push: génération locale uniquement.
# - Le Writer DOIT lire "doc/convention.md" en premier.

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
# MCP imports (les chemins exacts dépendent de ton client MCP python)
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
# Config
# -----------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None
MODEL_WRITER = os.environ.get("OPENAI_MODEL_WRITER", "magistral-2509").strip()

GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()
GITLAB_PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID", "").strip()  # recommandé
GITLAB_REF = os.environ.get("GITLAB_REF", "").strip() or None

SPEC_JSON_PATH = os.environ.get("SPEC_JSON_PATH", "").strip()
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./generated")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _print_stream(prefix: str, text: str) -> None:
    print(f"{prefix}{text}", end="", flush=True)


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


async def maybe_await(x):
    if inspect.isawaitable(x):
        return await x
    return x


async def open_streamable_http(url: str, headers: Optional[Dict[str, str]] = None):
    """
    Supporte variations streamable_http_client:
    - async context manager qui return (read, write) ou (read, write, close)
    - ou tuple direct
    """
    sig = None
    try:
        sig = inspect.signature(streamable_http_client)
    except Exception:
        sig = None

    kwargs = {}
    if headers and sig and "headers" in sig.parameters:
        kwargs["headers"] = headers

    res = streamable_http_client(url, **kwargs) if kwargs else streamable_http_client(url)

    if hasattr(res, "__aenter__"):
        cm = res
        entered = await cm.__aenter__()
        if isinstance(entered, tuple):
            if len(entered) == 2:
                return entered[0], entered[1], cm.__aexit__
            if len(entered) >= 3:
                closer = entered[2] if callable(entered[2]) else cm.__aexit__
                return entered[0], entered[1], closer
        raise RuntimeError(f"Format streamable_http_client inconnu: {entered}")

    if isinstance(res, tuple):
        if len(res) == 2:
            return res[0], res[1], None
        if len(res) >= 3:
            return res[0], res[1], res[2]

    raise RuntimeError(f"Format streamable_http_client inattendu: {res}")


# -----------------------------------------------------------------------------
# MCP Adapter
# -----------------------------------------------------------------------------
@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]


class MCPClient:
    def __init__(self, url: str):
        if MCP_IMPORT_ERROR is not None:
            raise RuntimeError(f"Impossible d'importer MCP python. Erreur: {MCP_IMPORT_ERROR}")
        if not url:
            raise ValueError("URL MCP vide.")
        self.url = url
        self._session = None
        self._transport_close = None

    async def __aenter__(self) -> "MCPClient":
        read_stream, write_stream, closer = await open_streamable_http(self.url)
        self._session = ClientSession(read_stream, write_stream)
        self._transport_close = closer

        await self._session.__aenter__()
        if hasattr(self._session, "initialize"):
            await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
        if callable(self._transport_close):
            try:
                await maybe_await(self._transport_close(exc_type, exc, tb))
            except Exception:
                pass

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

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        assert self._session is not None
        resp = await self._session.call_tool(name, arguments)
        if hasattr(resp, "content"):
            return normalize_mcp_content(resp.content)
        return normalize_mcp_content(resp)


def mcp_tools_to_openai(tools: List[MCPTool]) -> List[Dict[str, Any]]:
    out = []
    for t in tools:
        schema = t.input_schema or {"type": "object", "properties": {}, "additionalProperties": True}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            }
        )
    return out


# -----------------------------------------------------------------------------
# Tool loop OpenAI (async + streaming)
# -----------------------------------------------------------------------------
async def chat_with_tools_streaming(
    client: AsyncOpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_executor,
    prefix: str,
    max_rounds: int = 16,
    temperature: float = 0.1,
) -> Tuple[str, List[Dict[str, Any]]]:
    final_text = ""

    for round_idx in range(1, max_rounds + 1):
        _print_stream(prefix, f"\n--- round {round_idx} ---\n")

        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
            temperature=temperature,
        )

        assistant_text_parts: List[str] = []
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}

        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta

            if delta and getattr(delta, "content", None):
                txt = delta.content
                assistant_text_parts.append(txt)
                _print_stream(prefix, txt)

            if delta and getattr(delta, "tool_calls", None):
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
            final_text = assistant_text

        if tool_calls_acc:
            messages.append({"role": "assistant", "content": assistant_text or ""})

            for _, tc in sorted(tool_calls_acc.items(), key=lambda x: x[0]):
                name = tc["name"]
                args_str = tc["arguments"] or "{}"
                try:
                    args = json.loads(args_str) if args_str.strip() else {}
                except Exception:
                    args = {"_raw": args_str}

                _print_stream(prefix, f"\n[TOOL_CALL] {name} args={args}\n")
                result = await tool_executor(name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"] or f"toolcall-{name}",
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        return final_text, messages

    return final_text, messages


# -----------------------------------------------------------------------------
# Writer prompt
# -----------------------------------------------------------------------------
WRITER_SYSTEM = """
Tu es IA2 (WRITER). Ton job: générer un fichier Robot Framework .robot conforme au framework existant dans GitLab.

Règles obligatoires:
1) Lire d'abord le fichier "doc/convention.md" via GitLab MCP (OBLIGATOIRE).
2) Explorer le repo (tree + exemples) pour trouver un test similaire et les resources/variables utilisées.
3) Réutiliser les keywords existants du framework quand possible (ne pas réinventer).
4) Générer le contenu final du fichier .robot (PAS de markdown), prêt à être écrit en local.
5) Read-only: PAS de commit/push.

Aides:
- Si tu as besoin du project_id ou ref et qu'ils ne sont pas inclus, demande au toolset (search_repositories / get_project / get_repository_tree) ou utilise les variables fournies.
- Ne sors que le contenu final du .robot (texte brut).
""".strip()


def load_spec_json() -> Dict[str, Any]:
    if not SPEC_JSON_PATH:
        raise RuntimeError("SPEC_JSON_PATH manquant. Donne le chemin vers la spec JSON du Planner.")
    p = Path(SPEC_JSON_PATH)
    if not p.exists():
        raise RuntimeError(f"SPEC_JSON_PATH introuvable: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def choose_output_path(spec: Dict[str, Any]) -> Path:
    target = (
        spec.get("rf", {}).get("target_path")
        or spec.get("rf", {}).get("output_path")
        or "tests/generated/generated_from_spec.robot"
    )
    rel = Path(str(target)).as_posix().lstrip("/")
    return OUTPUT_DIR / rel


async def main() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")
    if MCP_IMPORT_ERROR is not None:
        raise RuntimeError(f"Lib MCP python non importable: {MCP_IMPORT_ERROR}")

    spec = load_spec_json()

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    print("== WRITER ONLY (GitLab MCP) ==")
    print(f"- Model       : {MODEL_WRITER}")
    print(f"- GITLAB_MCP  : {GITLAB_MCP_URL}")
    print(f"- PROJECT_ID  : {GITLAB_PROJECT_ID or '(non fourni)'}")
    print(f"- REF         : {GITLAB_REF or '(non fourni)'}")
    print(f"- SPEC_JSON   : {SPEC_JSON_PATH}")
    print(f"- OUTPUT_DIR  : {OUTPUT_DIR}")
    print("-----------------------------------------------------")

    async with MCPClient(GITLAB_MCP_URL) as git_mcp:
        tools = await git_mcp.list_tools()
        tools_openai = mcp_tools_to_openai(tools)

        async def exec_tool(name: str, args: Dict[str, Any]) -> Any:
            # Injecte project_id / ref automatiquement si tes tools les demandent
            # (ça évite de répéter partout)
            if GITLAB_PROJECT_ID:
                for k in ("project_id", "projectId", "project"):
                    if k in (tools_map.get(name, set())) and k not in args:
                        args[k] = GITLAB_PROJECT_ID
            if GITLAB_REF:
                for k in ("ref", "branch", "branch_name"):
                    if k in (tools_map.get(name, set())) and k not in args:
                        args[k] = GITLAB_REF
            return await git_mcp.call_tool(name, args)

        # petit index pour savoir si un tool attend project_id/ref (best-effort)
        tools_map: Dict[str, set] = {}
        for t in tools:
            props = (t.input_schema or {}).get("properties", {}) or {}
            tools_map[t.name] = set(props.keys())

        writer_user = (
            "Tu vas générer un fichier Robot Framework à partir de cette SPEC JSON.\n\n"
            f"SPEC_JSON:\n{json.dumps(spec, ensure_ascii=False, indent=2)}\n\n"
            "Contraintes OBLIGATOIRES:\n"
            "1) Appelle get_file_contents sur 'doc/convention.md' EN PREMIER.\n"
            "2) Ensuite explore le repo pour retrouver ressources/tests similaires.\n"
            "3) Puis génère le contenu final .robot (texte brut uniquement).\n\n"
            "Infos techniques:\n"
            f"- project_id (si nécessaire): {GITLAB_PROJECT_ID or 'NON FOURNI'}\n"
            f"- ref/branch (si nécessaire): {GITLAB_REF or 'NON FOURNI'}\n"
        )

        messages = [
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": writer_user},
        ]

        robot_text, _ = await chat_with_tools_streaming(
            client=client,
            model=MODEL_WRITER,
            messages=messages,
            tools=tools_openai,
            tool_executor=exec_tool,
            prefix="[WRITER] ",
            max_rounds=18,
            temperature=0.1,
        )

    robot_text = robot_text.strip()
    if not robot_text:
        raise RuntimeError("Le modèle n'a produit aucun contenu Robot Framework.")

    out_path = choose_output_path(spec)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(robot_text + "\n", encoding="utf-8")
    print(f"\n[OK] Robot généré en local: {out_path}")
    print("\n--- DONE ---")


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass
    asyncio.run(main())