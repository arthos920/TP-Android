from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

# MCP
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


# =========================
# CONFIG A ADAPTER
# =========================

# Jira MCP (streamable-http)
JIRA_MCP_URL = "http://localhost:20000/mcp"
JIRA_MCP_HEADERS = None  # ex: {"Authorization": "Bearer XXX"}

# Mobile MCP (stdio node)
MOBILE_NODE_COMMAND = "node"
MOBILE_NODE_SCRIPT = r"C:/ads mcp/mobile-mcp-main/lib/index.js"  # <-- ton chemin
MOBILE_ENV = None

# LLM endpoint OpenAI-compatible
LLM_API_KEY = "xxx"
LLM_BASE_URL = "xxx/api/v1"

# Proxy LLM si besoin
PROXY_URL = "xxxx"  # "" si pas de proxy

# Modèles
PLANNER_MODEL = "magistral-2509"
EXECUTOR_MODEL = "magistral-2509"


Message = Dict[str, Any]


# =========================
# MCP wrappers
# =========================
class MCPRemoteHTTP:
    """MCP remote via streamable-http (URL)."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {}
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPRemoteHTTP":
        transport = await self._stack.enter_async_context(
            streamable_http_client(self.url, headers=self.headers)
        )
        read_stream, write_stream = transport
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)


class MCPStdioNode:
    """MCP server en local via stdio (node index.js)."""

    def __init__(self, command: str, script_path: str, env: Optional[Dict[str, str]] = None):
        self.command = command
        self.script_path = script_path
        self.env = env
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPStdioNode":
        params = StdioServerParameters(command=self.command, args=[self.script_path], env=self.env)
        transport = await self._stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = transport
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._stack.aclose()

    async def list_tools(self):
        resp = await self.session.list_tools()
        return resp.tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)


def mcp_tools_to_openai_tools(mcp_tools) -> List[dict]:
    tools = []
    for t in mcp_tools:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


# =========================
# STREAMING parse (robuste)
# =========================
def _safe_choices(chunk):
    return getattr(chunk, "choices", None)


def _delta_content(choice0) -> Optional[str]:
    delta = getattr(choice0, "delta", None)
    if delta is None:
        return None
    return getattr(delta, "content", None)


def _delta_tool_calls(choice0):
    delta = getattr(choice0, "delta", None)
    if delta is None:
        return None
    return getattr(delta, "tool_calls", None)


@dataclass
class ToolCallAcc:
    id: Optional[str] = None
    name: str = ""
    arguments: str = ""


def _ensure_list_size(lst: list, size: int):
    while len(lst) < size:
        lst.append(ToolCallAcc())


async def _stream_completion_collect(
    async_client: AsyncOpenAI,
    *,
    model: str,
    messages: List[Message],
    tools: List[dict],
    temperature: float,
    max_tokens: int,
    label: str,
) -> Tuple[str, List[ToolCallAcc]]:
    """
    Stream texte en live + collecte tool_calls streamés.
    """
    print(f"\n--- {label} ---\n", end="", flush=True)

    text_chunks: List[str] = []
    tool_calls_acc: List[ToolCallAcc] = []

    stream = await async_client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    async for chunk in stream:
        choices = _safe_choices(chunk)
        if not choices:
            continue

        choice0 = choices[0]

        piece = _delta_content(choice0)
        if piece:
            print(piece, end="", flush=True)
            text_chunks.append(piece)

        tcs = _delta_tool_calls(choice0)
        if tcs:
            for tc in tcs:
                idx = getattr(tc, "index", 0)
                _ensure_list_size(tool_calls_acc, idx + 1)
                acc = tool_calls_acc[idx]

                tc_id = getattr(tc, "id", None)
                if tc_id:
                    acc.id = tc_id

                fn = getattr(tc, "function", None)
                if fn is not None:
                    fn_name = getattr(fn, "name", None)
                    if fn_name:
                        acc.name = fn_name
                    fn_args = getattr(fn, "arguments", None)
                    if fn_args:
                        acc.arguments += fn_args

    print("\n")
    full_text = "".join(text_chunks).strip()
    tool_calls_acc = [tc for tc in tool_calls_acc if tc.name]
    return full_text, tool_calls_acc


def _result_to_text(result) -> str:
    try:
        return json.dumps(result.content, ensure_ascii=False)
    except Exception:
        return str(getattr(result, "content", result))


async def run_model_with_mcp_streaming(
    async_client: AsyncOpenAI,
    *,
    model: str,
    messages: List[Message],
    tools_openai: List[dict],
    mcp_session,
    temperature: float,
    max_tokens: int,
    label: str,
) -> Tuple[List[Message], str]:
    """
    LLM streaming -> tool_calls -> MCP -> tool results -> boucle.
    """
    last_text = ""

    while True:
        assistant_text, tool_calls = await _stream_completion_collect(
            async_client,
            model=model,
            messages=messages,
            tools=tools_openai,
            temperature=temperature,
            max_tokens=max_tokens,
            label=label,
        )

        last_text = assistant_text
        messages.append({"role": "assistant", "content": assistant_text})

        if not tool_calls:
            return messages, last_text

        for tc in tool_calls:
            args = {}
            if tc.arguments:
                try:
                    args = json.loads(tc.arguments)
                except Exception:
                    args = {"_raw": tc.arguments}

            result = await mcp_session.call_tool(tc.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id or f"{tc.name}_noid",
                    "content": _result_to_text(result),
                }
            )


# =========================
# Prompts adaptés à tes tools mobile
# =========================
SYSTEM_PLANNER = """Tu es IA-PLANNER (Jira Reader). Tu as UNIQUEMENT les outils Jira.

But:
- Lire un ticket Jira et produire un plan mobile actionnable.

Règles:
- Utilise Jira tools pour récupérer: description, critères d'acceptation, données, prérequis.
- Ne devine pas les éléments UI si tu ne les as pas.
- Ton plan doit être compatible avec les outils mobiles suivants:
  - mobile_list_available_devices, mobile_list_apps, mobile_launch_app
  - mobile_list_elements_on_screen (pour obtenir textes/labels + coordonnées)
  - mobile_click_on_screen_at_coordinates, mobile_double_tap_on_screen, mobile_long_press_on_screen_at_coordinates
  - mobile_swipe_on_screen, mobile_type_keys
  - mobile_take_screenshot / mobile_save_screenshot
  - mobile_press_button, mobile_open_url
- Plan en étapes numérotées, chaque étape avec:
  ACTION: tap/type/wait/verify/swipe/open_url/press_button/launch_app
  TARGET_TEXT: texte/label à chercher via mobile_list_elements_on_screen (ou 'N/A')
  COORD_HINT: si tu as une idée (sinon N/A)
  DATA: si saisie (sinon N/A)
  CHECK: critère observable (ex: "texte X visible", "écran Y affiché")

Termine par:
PLAN_DONE: yes/no
NEXT: (une phrase)
"""

SYSTEM_EXECUTOR = """Tu es IA-EXECUTOR (Mobile Operator). Tu as UNIQUEMENT les outils Mobile.

Règles d'exécution (IMPORTANT):
1) Si plusieurs devices: appelle mobile_list_available_devices puis CHOISIS un device (demande à l'utilisateur si nécessaire).
2) Avant chaque tap: appelle mobile_list_elements_on_screen pour trouver le bon élément (par display text / accessibility label).
3) Pour cliquer: utilise mobile_click_on_screen_at_coordinates(x,y). Si besoin: double_tap ou long_press.
4) Pour saisir: mobile_type_keys (après focus).
5) Pour preuve: mobile_take_screenshot puis mobile_save_screenshot(path) si possible.
6) Si tu ne trouves pas l'élément: swipe, reliste les éléments, ou demande une clarification au Planner.

Rapport obligatoire après exécution:
RESULT: success/failed/blocked
DONE_STEPS: [..]
FAILED_STEP: n (si applicable)
ERROR: ...
OBSERVATIONS: ...
EVIDENCE: (paths screenshots si dispo)
NEXT: ...
"""


# =========================
# Orchestrateur DUO
# =========================
@dataclass
class DuoConfig:
    rounds: int = 6
    planner_temperature: float = 0.2
    executor_temperature: float = 0.2
    max_tokens: int = 900


async def duo_jira_to_mobile_async_streaming(
    async_client: AsyncOpenAI,
    *,
    planner_model: str,
    executor_model: str,
    cfg: DuoConfig,
    user_goal: str,
) -> None:
    async with MCPRemoteHTTP(JIRA_MCP_URL, JIRA_MCP_HEADERS) as jira_mcp, MCPStdioNode(
        MOBILE_NODE_COMMAND, MOBILE_NODE_SCRIPT, MOBILE_ENV
    ) as mobile_mcp:

        jira_tools = mcp_tools_to_openai_tools(await jira_mcp.list_tools())
        mobile_tools = mcp_tools_to_openai_tools(await mobile_mcp.list_tools())

        planner_msgs: List[Message] = [
            {"role": "system", "content": SYSTEM_PLANNER},
            {"role": "user", "content": user_goal},
        ]

        executor_msgs: List[Message] = [
            {"role": "system", "content": SYSTEM_EXECUTOR},
            {"role": "user", "content": "Attends les instructions du Planner, puis exécute sur mobile."},
        ]

        last_executor_report = ""

        for r in range(cfg.rounds):
            if last_executor_report:
                planner_msgs.append({"role": "user", "content": f"Retour Executor:\n{last_executor_report}"})

            # 1) Planner (Jira tools)
            planner_msgs, planner_text = await run_model_with_mcp_streaming(
                async_client,
                model=planner_model,
                messages=planner_msgs,
                tools_openai=jira_tools,
                mcp_session=jira_mcp,
                temperature=cfg.planner_temperature,
                max_tokens=cfg.max_tokens,
                label=f"PLANNER | round {r+1} | {planner_model}",
            )

            # 2) Executor (Mobile tools)
            executor_msgs.append({"role": "user", "content": f"Plan du Planner:\n{planner_text}"})

            executor_msgs, executor_text = await run_model_with_mcp_streaming(
                async_client,
                model=executor_model,
                messages=executor_msgs,
                tools_openai=mobile_tools,
                mcp_session=mobile_mcp,
                temperature=cfg.executor_temperature,
                max_tokens=cfg.max_tokens,
                label=f"EXECUTOR | round {r+1} | {executor_model}",
            )

            last_executor_report = executor_text

            if "result: success" in executor_text.lower():
                print("\n✅ DONE: executor a terminé (RESULT: success)\n")
                return

        print("\n⚠️ Fin des rounds atteinte (pas de success explicite).\n")


# =========================
# MAIN
# =========================
async def main():
    proxy = httpx.Proxy(url=PROXY_URL) if PROXY_URL else None

    async with httpx.AsyncClient(proxy=proxy, verify=False, follow_redirects=False, timeout=120.0) as http_client:
        async_client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            http_client=http_client,
        )

        goal = (
            "Objectif: traiter un ticket Jira et exécuter les actions sur mobile.\n"
            "Planner: trouve un ticket Jira à traiter (le plus récent ou selon un filtre), puis écris un plan d'étapes.\n"
            "Executor: exécute ce plan sur mobile avec les outils disponibles.\n"
            "Commence par lister les tickets Jira pertinents, puis choisis-en un."
        )

        cfg = DuoConfig(rounds=6, planner_temperature=0.2, executor_temperature=0.2, max_tokens=900)

        await duo_jira_to_mobile_async_streaming(
            async_client,
            planner_model=PLANNER_MODEL,
            executor_model=EXECUTOR_MODEL,
            cfg=cfg,
            user_goal=goal,
        )


if __name__ == "__main__":
    asyncio.run(main())