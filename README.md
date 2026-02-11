# jira_to_robot_duo_async_streaming.py
# Flow 2 IA (Planner -> JSON spec) + (Writer -> Robot Framework file)
# Async + streaming, MCP streamable-http (Jira/Confluence + GitLab)
#
# Prérequis:
#   pip install openai httpx anyio
#   + ton package MCP python déjà utilisé (celui qui fournit streamable_http_client + ClientSession)
#
# Variables d'env attendues:
#   OPENAI_API_KEY
#   OPENAI_BASE_URL           (optionnel, ex: http://localhost:xxxx/api/v1)
#   OPENAI_MODEL_PLANNER      (ex: "magistral-2509")
#   OPENAI_MODEL_WRITER       (ex: "magistral-2509")
#
#   JIRA_MCP_URL              (ex: "http://localhost:9000/mcp")
#   GITLAB_MCP_URL            (ex: "http://localhost:9001/mcp")
#
#   OUTPUT_DIR                (optionnel, défaut: "./generated")
#
# Notes:
# - Le Planner cherche sur Confluence avec le mot-clé "architecture".
# - Le Writer lit en priorité doc/convention.md (obligatoire) puis explore le repo.
# - Pas de commit / push GitLab: génération locale uniquement.

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
# On essaye plusieurs imports compatibles.
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
JIRA_KEY = "6"
CONFLUENCE_SEARCH_KEYWORD = "architecture"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip() or None
MODEL_PLANNER = os.environ.get("OPENAI_MODEL_PLANNER", "magistral-2509").strip()
MODEL_WRITER = os.environ.get("OPENAI_MODEL_WRITER", "magistral-2509").strip()

JIRA_MCP_URL = os.environ.get("JIRA_MCP_URL", "").strip()
GITLAB_MCP_URL = os.environ.get("GITLAB_MCP_URL", "").strip()

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./generated")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _print_stream(prefix: str, text: str) -> None:
    print(f"{prefix}{text}", end="", flush=True)


def extract_json_object(text: str) -> Dict[str, Any]:
    """
    Récupère un JSON objet depuis une sortie modèle (peut contenir du bruit).
    """
    text = text.strip()
    if not text:
        raise ValueError("Réponse vide, impossible de parser le JSON.")

    # 1) Déjà JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) Premier {...} équilibré
    m = re.search(r"\{", text)
    if not m:
        raise ValueError("Aucun '{' trouvé, impossible de parser le JSON.")

    start = m.start()
    brace = 0
    end = None
    for i in range(start, len(text)):
        if text[i] == "{":
            brace += 1
        elif text[i] == "}":
            brace -= 1
            if brace == 0:
                end = i + 1
                break

    if end is None:
        raise ValueError("JSON non équilibré, impossible de parser.")

    candidate = text[start:end]
    obj = json.loads(candidate)
    if not isinstance(obj, dict):
        raise ValueError("JSON parsé mais ce n'est pas un objet.")
    return obj


async def maybe_await(x):
    if inspect.isawaitable(x):
        return await x
    return x


def normalize_mcp_content(content: Any) -> Any:
    """
    Évite "TextContent is not JSON serializable".
    Transforme en dict/list/str.
    """
    if content is None:
        return None
    if isinstance(content, (str, int, float, bool)):
        return content
    if isinstance(content, dict):
        return {k: normalize_mcp_content(v) for k, v in content.items()}
    if isinstance(content, list):
        return [normalize_mcp_content(x) for x in content]

    # TextContent-like: .type / .text
    if hasattr(content, "type") and hasattr(content, "text"):
        return {"type": getattr(content, "type"), "text": getattr(content, "text")}

    if hasattr(content, "__dict__"):
        return {k: normalize_mcp_content(v) for k, v in content.__dict__.items()}

    return str(content)


# -----------------------------------------------------------------------------
# MCP Adapter (FIXED)
# -----------------------------------------------------------------------------
@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]


async def open_streamable_http_cm(
    url: str,
    headers: Optional[Dict[str, str]] = None,
):
    """
    FIX IMPORTANT:
    - On conserve le *context manager* streamable_http_client(...) vivant
    - On appelle __aexit__(exc_type, exc, tb) plus tard, dans le même flow
    => évite anyio cancel scope errors + "client closed".
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
        # fallback rare: retour tuple direct
        if isinstance(cm, tuple) and len(cm) >= 2:
            read_stream, write_stream = cm[0], cm[1]
            return None, read_stream, write_stream
        raise RuntimeError(f"streamable_http_client inattendu: {cm}")

    entered = await cm.__aenter__()
    if not isinstance(entered, tuple) or len(entered) < 2:
        # parfois le cm retourne un objet transport ; dans ce cas tu devras adapter
        raise RuntimeError(f"Format retour streamable_http_client inconnu: {entered}")

    read_stream, write_stream = entered[0], entered[1]
    return cm, read_stream, write_stream


class MCPClient:
    """
    Client MCP minimal:
    - Connect streamable-http
    - list_tools
    - call_tool
    FIX: fermeture propre du context manager streamable_http_client (pas de closer bricolé)
    """

    def __init__(self, url: str):
        if MCP_IMPORT_ERROR is not None:
            raise RuntimeError(f"Impossible d'importer le client MCP python. Erreur: {MCP_IMPORT_ERROR}")
        if not url:
            raise ValueError("URL MCP vide.")
        self.url = url
        self._session: Optional[ClientSession] = None
        self._transport_cm = None  # <= on garde le CM vivant

    async def __aenter__(self) -> "MCPClient":
        self._transport_cm, read_stream, write_stream = await open_streamable_http_cm(self.url)

        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()

        # Certaines implémentations nécessitent initialize()
        if hasattr(self._session, "initialize"):
            await self._session.initialize()

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # 1) fermer la session MCP
        if self._session is not None:
            try:
                await self._session.__aexit__(exc_type, exc, tb)
            except Exception:
                pass
            self._session = None

        # 2) fermer le transport CM streamable_http_client
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

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        assert self._session is not None
        resp = await self._session.call_tool(name, arguments)
        if hasattr(resp, "content"):
            return normalize_mcp_content(resp.content)
        return normalize_mcp_content(resp)


# -----------------------------------------------------------------------------
# OpenAI Tool loop (async + streaming)
# -----------------------------------------------------------------------------
def mcp_tools_to_openai(tools: List[MCPTool]) -> List[Dict[str, Any]]:
    openai_tools = []
    for t in tools:
        schema = t.input_schema or {}
        if not schema:
            schema = {"type": "object", "properties": {}, "additionalProperties": True}

        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            }
        )
    return openai_tools


async def chat_with_tools_streaming(
    client: AsyncOpenAI,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_executor,  # async fn(name, args)->result
    prefix: str,
    max_rounds: int = 12,
    temperature: float = 0.2,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Loop tool-calling avec streaming.
    Retourne: (final_text, final_messages)
    """
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
# Prompts
# -----------------------------------------------------------------------------
PLANNER_SYSTEM = f"""
Tu es IA1 (PLANNER). Ton job: produire une SPEC Robot Framework en JSON STRICT, sans markdown, sans texte autour.

Objectif:
- Lire le ticket Jira: {JIRA_KEY}
- Chercher sur Confluence avec le mot-clé: "{CONFLUENCE_SEARCH_KEYWORD}"
- Lire la page Confluence la plus pertinente pour l'architecture/conventions du framework de test
- Produire un JSON strict avec:
  - meta (jira_key, title, etc.)
  - confluence.sources[] (page_id, title, space_key si dispo)
  - confluence.rules (tags obligatoires, naming, setup/teardown, patterns)
  - rf.target_path (chemin proposé pour le test)
  - rf.test_cases[] (1 ou plusieurs cas)
  - writer_constraints.must_read_files = ["doc/convention.md"]

Contraintes:
- N'invente pas de keywords spécifiques GitLab. Écris des intentions (Given/When/Then) propres, que IA2 mappera.
- Ta sortie finale DOIT être un JSON valide (objet).
""".strip()

PLANNER_USER = f"""
Récupère et résume le ticket Jira {JIRA_KEY}. Ensuite, récupère la doc Confluence pertinente en cherchant "{CONFLUENCE_SEARCH_KEYWORD}".
Enfin, génère la SPEC Robot Framework complète en JSON strict.
""".strip()

WRITER_SYSTEM = """
Tu es IA2 (WRITER). Ton job: générer un fichier Robot Framework .robot conforme au framework existant dans GitLab.

Règles obligatoires:
1) Lire d'abord le fichier "doc/convention.md" (obligatoire) via GitLab MCP.
2) Explorer le repo (tree + exemples) pour trouver un test similaire et les resources/variables utilisées.
3) Réutiliser les keywords existants du framework quand possible (ne pas réinventer).
4) Générer le contenu final du fichier .robot (pas de markdown), prêt à être écrit en local.
5) Ne fais PAS de commit/push. Read-only.

Sortie finale:
- Donne uniquement le contenu du .robot (texte brut).
""".strip()


# -----------------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------------
async def planner_make_spec_json(openai_client: AsyncOpenAI) -> Dict[str, Any]:
    async with MCPClient(JIRA_MCP_URL) as jira_mcp:
        mcp_tools = await jira_mcp.list_tools()
        tools_openai = mcp_tools_to_openai(mcp_tools)

        async def exec_tool(name: str, args: Dict[str, Any]) -> Any:
            return await jira_mcp.call_tool(name, args)

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": PLANNER_USER},
        ]

        text, _ = await chat_with_tools_streaming(
            client=openai_client,
            model=MODEL_PLANNER,
            messages=messages,
            tools=tools_openai,
            tool_executor=exec_tool,
            prefix="[PLANNER] ",
            max_rounds=12,
            temperature=0.2,
        )

        _print_stream("\n", "\n\n--- PLANNER OUTPUT (raw) ---\n")
        print(text)

        spec = extract_json_object(text)
        return spec


async def writer_generate_robot(openai_client: AsyncOpenAI, spec: Dict[str, Any]) -> str:
    async with MCPClient(GITLAB_MCP_URL) as git_mcp:
        mcp_tools = await git_mcp.list_tools()
        tools_openai = mcp_tools_to_openai(mcp_tools)

        async def exec_tool(name: str, args: Dict[str, Any]) -> Any:
            return await git_mcp.call_tool(name, args)

        writer_user = (
            "Voici la SPEC JSON (Planner). Utilise-la pour générer le fichier Robot Framework.\n\n"
            f"SPEC_JSON:\n{json.dumps(spec, ensure_ascii=False, indent=2)}\n\n"
            "IMPORTANT:\n"
            "- Tu dois appeler get_file_contents sur 'doc/convention.md' en premier.\n"
            "- Ensuite, explore le repo pour retrouver les bons imports/resources et un exemple proche.\n"
            "- Puis génère le contenu final .robot.\n"
        )

        messages = [
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": writer_user},
        ]

        text, _ = await chat_with_tools_streaming(
            client=openai_client,
            model=MODEL_WRITER,
            messages=messages,
            tools=tools_openai,
            tool_executor=exec_tool,
            prefix="[WRITER] ",
            max_rounds=16,
            temperature=0.1,
        )

        return text.strip()


def choose_output_path(spec: Dict[str, Any]) -> Path:
    target = (
        spec.get("rf", {}).get("target_path")
        or spec.get("rf", {}).get("output_path")
        or f"tests/generated/{JIRA_KEY}.robot"
    )
    rel = Path(str(target)).as_posix().lstrip("/")
    return OUTPUT_DIR / rel


async def main() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY manquant.")
    if not JIRA_MCP_URL:
        raise RuntimeError("JIRA_MCP_URL manquant.")
    if not GITLAB_MCP_URL:
        raise RuntimeError("GITLAB_MCP_URL manquant.")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    print(f"== Flow 2 IA :: Jira={JIRA_KEY} ==")
    print(f"- Planner model: {MODEL_PLANNER}")
    print(f"- Writer  model: {MODEL_WRITER}")
    print(f"- JIRA MCP URL : {JIRA_MCP_URL}")
    print(f"- GIT  MCP URL : {GITLAB_MCP_URL}")
    print(f"- OUTPUT_DIR   : {OUTPUT_DIR}")
    print("-----------------------------------------------------")

    # 1) Planner -> JSON spec
    spec = await planner_make_spec_json(client)

    spec_path = OUTPUT_DIR / f"{JIRA_KEY}_spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Spec JSON écrit: {spec_path}")

    # 2) Writer -> robot file content
    robot_text = await writer_generate_robot(client, spec)

    out_path = choose_output_path(spec)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(robot_text + "\n", encoding="utf-8")
    print(f"\n[OK] Robot généré en local: {out_path}")

    print("\n--- DONE ---")
    print(f"Spec : {spec_path}")
    print(f"Robot: {out_path}")


if __name__ == "__main__":
    # Windows: parfois nécessaire
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    except Exception:
        pass

    asyncio.run(main())