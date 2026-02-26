"""
script_jira_appium_v2_fixed.py — Runner Jira + Appium MCP générique (FIXED)

Correctifs appliqués (par rapport à ton v2) :
  ✅ (A) Dump des tools + schémas (optionnel via DEBUG_TOOLS=1)
  ✅ (B) Robustesse Appium MCP : call_any() + compat args (using/value vs strategy/selector)
  ✅ (C) generate_locators : ne suppose PLUS elementId. On récupère un locator (using/value) puis find_element → elementId → click.
  ✅ (D) find_element wrapper : essaie W3C {using,value} puis legacy {strategy,selector}
  ✅ (E) activate/terminate : essaie bundleId/packageName (Android) sur les tools connus du repo
  ✅ (F) ok plus fiable : on exploite isError quand présent (sinon fallback texte)

Nota:
- Le repo indique : appium_terminateApp / appium_installApp / appium_uninstallApp / appium_activate_app etc.
- Les schémas exacts peuvent varier => wrappers tolérants.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import pathlib
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

# =============================================================================
# CONFIG
# =============================================================================

JIRA_MCP_URL = os.getenv("JIRA_MCP_URL", "http://localhost:9000/mcp")
TICKET_KEY = os.getenv("TICKET_KEY", "XXXX-0001")

ANDROID_HOME = os.getenv("ANDROID_HOME", "/opt/android-sdk").strip()
APPIUM_MCP_DIR = os.getenv("APPIUM_MCP_DIR", "/app/appium-mcp").strip()
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723").strip()

SCREENSHOTS_DIR = pathlib.Path(os.getenv("SCREENSHOTS_DIR", "/app/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

LLM_API_KEY = os.getenv("LLM_API_KEY", "no-key")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
PROXY_URL = os.getenv("PROXY_URL", "")

DEVICE_1_ID = os.getenv("DEVICE_1_ID", "emulator-5554").strip()
DEVICE_2_ID = os.getenv("DEVICE_2_ID", "emulator-5556").strip()

GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", "").strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", "").strip()
APP_ACTIVITY = os.getenv("APP_ACTIVITY", "").strip()

MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))
MAX_TURNS_PER_DRIVER = int(os.getenv("MAX_TURNS_PER_DRIVER", "30"))
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "60"))
TOOL_ATTEMPTS = int(os.getenv("TOOL_ATTEMPTS", "3"))

DEBUG_TOOLS = os.getenv("DEBUG_TOOLS", "0").strip() in ("1", "true", "True", "yes", "YES")


# =============================================================================
# UTILS
# =============================================================================

def _strip_ctrl(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


def trunc(text: Any) -> str:
    text = _strip_ctrl(str(text))
    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED]..."
    return text[:MAX_TOOL_CHARS]


def mcp_to_text(r: Any) -> str:
    c = getattr(r, "content", r)
    if isinstance(c, list):
        return trunc("\n".join((getattr(i, "text", None) or str(i)) for i in c))
    return trunc(str(c) if not isinstance(c, str) else c)


async def safe_chat(ac: AsyncOpenAI, **kw):
    last: Optional[Exception] = None
    for i in range(3):
        try:
            return await ac.chat.completions.create(**kw)
        except Exception as e:
            last = e
            await asyncio.sleep(0.5 * (i + 1))
    raise last  # type: ignore[misc]


def _safe_slug(s: str, maxlen: int = 30) -> str:
    return re.sub(r"[^\w\-]", "_", s)[:maxlen]


def _el_id(text: str) -> Optional[str]:
    m = re.search(
        r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
        text,
        re.I,
    )
    return m.group(1) if m else None


# =============================================================================
# TRANSPORT STDIO (Appium MCP)
# =============================================================================

def _stdio_params(screenshots_dir: pathlib.Path) -> StdioServerParameters:
    pt = os.path.join(ANDROID_HOME, "platform-tools")
    tls = os.path.join(ANDROID_HOME, "tools")
    pth = os.environ.get("PATH", "")
    for p in [pt, tls]:
        if p and p not in pth:
            pth = p + os.pathsep + pth

    return StdioServerParameters(
        command="node",
        args=[os.path.join(APPIUM_MCP_DIR, "dist", "index.js"), "--transport=stdio"],
        cwd=APPIUM_MCP_DIR,
        env={
            **os.environ,
            "ANDROID_HOME": ANDROID_HOME,
            "ANDROID_SDK_ROOT": ANDROID_HOME,
            "PATH": pth,
            "NO_UI": "1",
            "SCREENSHOTS_DIR": str(screenshots_dir),
            # IMPORTANT: éviter de corrompre stdout JSON-RPC
            "LOG_LEVEL": "error",
            "APPIUM_LOG_LEVEL": "error",
            "APPIUM_MCP_LOG_LEVEL": "error",
            "DEBUG": "",
        },
    )


class MCPStdio:
    def __init__(self, screenshots_dir: pathlib.Path):
        self._p = _stdio_params(screenshots_dir)
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None
        self.tools_by_name: Dict[str, Dict[str, Any]] = {}

    async def __aenter__(self) -> "MCPStdio":
        r, w = await self._stack.enter_async_context(stdio_client(server=self._p))
        self.session = await self._stack.enter_async_context(ClientSession(r, w))
        await self.session.initialize()

        # Cache tools + schemas (utile pour debug / compat)
        try:
            tools = await self.session.list_tools()  # type: ignore
            for t in tools.tools:
                schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}
                props = (schema or {}).get("properties", {}) if isinstance(schema, dict) else {}
                self.tools_by_name[t.name] = {"schema": schema, "props": props}
            if DEBUG_TOOLS:
                print("\n[APPIUM_MCP] Tools disponibles:")
                for name, meta in sorted(self.tools_by_name.items()):
                    keys = list((meta.get("props") or {}).keys())
                    print(f"  - {name}   keys={keys}")
        except Exception as e:
            if DEBUG_TOOLS:
                print("[APPIUM_MCP] list_tools failed:", e)

        return self

    async def __aexit__(self, *a):
        await self._stack.aclose()

    async def raw(self, tool: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Retourne (ok, text). ok s'appuie sur isError si présent, sinon heuristique sur texte.
        """
        assert self.session is not None
        resp = await asyncio.wait_for(
            self.session.call_tool(tool, args),  # type: ignore
            timeout=TOOL_TIMEOUT_S,
        )
        text = mcp_to_text(resp)

        # ok via isError quand dispo
        is_error = getattr(resp, "isError", None)
        if isinstance(is_error, bool):
            return (not is_error), text

        # fallback heuristique texte
        tl = (text or "").lower()
        if any(s in tl for s in ["invalid arguments", "traceback", "error:", "[err]", "exception"]):
            return False, text
        return True, text

    async def call(self, tool: str, args: Dict[str, Any], attempts: int = TOOL_ATTEMPTS) -> Tuple[bool, str]:
        last = ""
        for i in range(1, attempts + 1):
            try:
                ok, out = await self.raw(tool, args)
                return ok, out
            except Exception as e:
                last = f"[ERR] {tool}: {e}"
                if i >= attempts:
                    return False, last
                await asyncio.sleep(0.6 * i)
        return False, last

    def has_tool(self, name: str) -> bool:
        return name in self.tools_by_name


# =============================================================================
# TRANSPORT HTTP (Jira MCP)
# =============================================================================

class MCPHttp:
    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPHttp":
        t = await self._stack.enter_async_context(streamable_http_client(self.url))
        if isinstance(t, (tuple, list)) and len(t) >= 2:
            r, w = t[0], t[1]
        else:
            r, w = t.read_stream, t.write_stream  # type: ignore[attr-defined]
        self.session = await self._stack.enter_async_context(ClientSession(r, w))
        await self.session.initialize()
        return self

    async def __aexit__(self, *a):
        await self._stack.aclose()

    async def list_tools(self):
        assert self.session is not None
        return (await self.session.list_tools()).tools

    async def call_tool(self, name: str, args: Dict[str, Any]):
        assert self.session is not None
        return await self.session.call_tool(name, args)


# =============================================================================
# BRIQUE 1 — EXTRACTION APP INFO (LLM)
# =============================================================================

_EXTRACT_PROMPT = """
Tu reçois un résumé de ticket Jira pour des tests mobiles Android.
Extrais UNIQUEMENT ces infos en JSON strict (sans markdown, sans explication) :
{
  "appPackage":  "com.example.app",
  "appActivity": ".MainActivity",
  "appName":     "Nom lisible de l'app",
  "platform":    "android"
}
Règles :
- Si l'app n'est PAS explicitement mentionnée dans le ticket, retourne des chaînes VIDES pour appPackage et appActivity.
- appActivity commence toujours par un point ou un chemin complet si elle est connue.
- platform est toujours "android" sauf si iOS explicitement mentionné.
Réponds UNIQUEMENT avec le JSON.
""".strip()


async def extract_app_info(summary: str, ac: AsyncOpenAI) -> Dict[str, str]:
    resp = await safe_chat(
        ac,
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": summary},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        data = json.loads(raw)
        return {
            "appPackage": str(data.get("appPackage", "")),
            "appActivity": str(data.get("appActivity", "")),
            "appName": str(data.get("appName", "Application")),
            "platform": str(data.get("platform", "android")),
        }
    except Exception:
        return {"appPackage": "", "appActivity": "", "appName": "Application", "platform": "android"}


def resolve_app_info(llm_info: Dict[str, str], driver_index: int = 1) -> Dict[str, str]:
    info = dict(llm_info)
    per_driver = DRIVER1_PACKAGE if driver_index == 1 else DRIVER2_PACKAGE

    pkg = per_driver or GLOBAL_PACKAGE or info.get("appPackage", "")
    act = info.get("appActivity", "")

    # si package vient d'env → on peut override activity via APP_ACTIVITY
    if per_driver or GLOBAL_PACKAGE:
        act = APP_ACTIVITY or act

    if not pkg:
        raise SystemExit(
            "[ERREUR] Aucun package défini.\n"
            "  → Renseigne GLOBAL_PACKAGE (ou DRIVER1_PACKAGE / DRIVER2_PACKAGE)."
        )

    info["appPackage"] = pkg
    info["appActivity"] = act
    if pkg != llm_info.get("appPackage", ""):
        info["appName"] = pkg.split(".")[-1].capitalize() or info.get("appName", "Application")
    return info


# =============================================================================
# PLANNER
# =============================================================================

_PLANNER_PROMPT = """Tu es un agent QA mobile expert.
À partir du résumé Jira ci-dessous, génère un plan de test COURT et ACTIONNABLE en JSON strict :
{
  "plan": [
    {"step": 1, "intent": "Lancer l'app", "expected": "Écran principal visible"},
    {"step": 2, "intent": "Cliquer sur Notifications", "expected": "Page Notifications ouverte"}
  ]
}
Règles :
- 3 à 8 étapes max.
- intent = action humaine simple.
- expected = élément/texte attendu visible après l'action.
- Réponds UNIQUEMENT avec le JSON.
""".strip()


async def generate_plan(summary: str, ac: AsyncOpenAI) -> List[Dict[str, str]]:
    resp = await safe_chat(
        ac,
        model=MODEL,
        temperature=0.1,
        messages=[
            {"role": "system", "content": _PLANNER_PROMPT},
            {"role": "user", "content": summary},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        data = json.loads(raw)
        plan = data.get("plan", [])
        if isinstance(plan, list) and plan:
            return plan
    except Exception:
        pass
    return [{"step": 1, "intent": "Ouvrir l'app et vérifier l'écran principal", "expected": "Accueil"}]


# =============================================================================
# TRACE LOCATORS
# =============================================================================

def _append_trace(session_dir: pathlib.Path, entry: Dict[str, Any]) -> None:
    try:
        trace_file = session_dir / "locators_trace.json"
        rows: List[Dict[str, Any]] = []
        if trace_file.exists():
            try:
                rows = json.loads(trace_file.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        rows.append(entry)
        trace_file.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


async def _save_screenshot(ctx: "DriverContext", label: str) -> Optional[pathlib.Path]:
    try:
        async with ctx.lock:
            await ctx.mcp.call("appium_screenshot", {"outputDir": str(ctx.session_dir)})

        files = sorted(ctx.session_dir.glob("*.png"), key=lambda f: f.stat().st_mtime)
        if not files:
            return None
        latest = files[-1]
        slug = _safe_slug(label)
        ctx.step += 1
        dest = ctx.session_dir / f"step_{ctx.step:03d}_{slug}.png"
        if latest.name != dest.name:
            try:
                latest.rename(dest)
            except Exception:
                pass
        return dest
    except Exception:
        return None


# =============================================================================
# DRIVER CONTEXT
# =============================================================================

@dataclass
class DriverContext:
    name: str
    device_id: str
    app_package: str
    app_activity: str
    app_name: str
    mcp: MCPStdio
    lock: asyncio.Lock
    session_dir: pathlib.Path = field(default_factory=lambda: SCREENSHOTS_DIR)
    step: int = 0
    last_locators: str = ""


# =============================================================================
# COMPAT HELPERS (critical fixes)
# =============================================================================

async def call_any(mcp: MCPStdio, names: List[str], args: Dict[str, Any], attempts: int = 1) -> Tuple[bool, str, str]:
    """
    Essaie plusieurs noms de tool (selon variations de versions) et renvoie (ok,out,used_name).
    """
    last_out = ""
    for nm in names:
        if mcp.tools_by_name and not mcp.has_tool(nm):
            continue
        ok, out = await mcp.call(nm, args, attempts=attempts)
        last_out = out
        if ok:
            return True, out, nm
    return False, last_out, (names[-1] if names else "")


async def appium_find(ctx: DriverContext, strategy: str, selector: str) -> Tuple[bool, str]:
    """
    FIX (D): Supporte W3C {using,value} puis legacy {strategy,selector}.
    """
    # W3C
    ok, out = await ctx.mcp.call("appium_find_element", {"using": strategy, "value": selector})
    if ok:
        return ok, out
    # legacy
    ok2, out2 = await ctx.mcp.call("appium_find_element", {"strategy": strategy, "selector": selector})
    return ok2, out2


def _best_locator_from_generate_locators(locators_raw: str, target_text: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """
    FIX (C): Parse generate_locators output.
    Retourne (using, value, item) si match text/contentDesc/resourceId.
    """
    if not locators_raw:
        return None
    try:
        items = json.loads(locators_raw)
        if not isinstance(items, list):
            return None
    except Exception:
        return None

    tl = target_text.lower().strip()

    def extract_using_value(item: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        loc = item.get("locator") or item.get("bestLocator") or item.get("best_locator") or {}
        if isinstance(loc, dict):
            using = loc.get("using") or loc.get("strategy")
            value = loc.get("value") or loc.get("selector")
            if using and value:
                return str(using), str(value)
        # parfois c'est directement au niveau root
        using2 = item.get("using") or item.get("strategy")
        value2 = item.get("value") or item.get("selector")
        if using2 and value2:
            return str(using2), str(value2)
        return None

    # passe 1: match exact text/desc/label
    for item in items:
        if not isinstance(item, dict):
            continue
        for k in ("text", "contentDesc", "content-desc", "label", "name", "accessibilityLabel"):
            v = str(item.get(k, "") or "").strip()
            if v and v.lower() == tl:
                uv = extract_using_value(item)
                if uv:
                    return uv[0], uv[1], item

    # passe 2: match partiel
    for item in items:
        if not isinstance(item, dict):
            continue
        for k in ("text", "contentDesc", "content-desc", "label", "name", "accessibilityLabel"):
            v = str(item.get(k, "") or "").strip()
            if v and tl in v.lower():
                uv = extract_using_value(item)
                if uv:
                    return uv[0], uv[1], item

    # passe 3: resourceId
    for item in items:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("resourceId", "") or "")
        if rid and tl in rid.lower():
            uv = extract_using_value(item)
            if uv:
                return uv[0], uv[1], item

    return None


# =============================================================================
# OBSERVE RICHE
# =============================================================================

async def tool_observe_rich(ctx: DriverContext) -> str:
    async with ctx.lock:
        _, src = await ctx.mcp.call("appium_get_page_source", {})
        _, locs = await ctx.mcp.call("generate_locators", {})
    ctx.last_locators = locs
    snap = await _save_screenshot(ctx, "observe")

    _append_trace(
        ctx.session_dir,
        {
            "ts": datetime.now().isoformat(),
            "step": ctx.step,
            "action": "observe",
            "device": ctx.device_id,
            "locators_raw": (locs or "")[:3000],
        },
    )

    if DEBUG_TOOLS:
        print(
            f"  [DEBUG observe] [{ctx.device_id}] locators({len(locs)}ch): {trunc(locs)[:300]}..."
        )

    return json.dumps(
        {
            "driver": ctx.name,
            "device": ctx.device_id,
            "page_source": (src or "")[:4000],
            "screenshot_saved": str(snap) if snap else "",
            "locators": (locs or "")[:3000],
        },
        ensure_ascii=False,
    )


# =============================================================================
# HANDLE ALERT
# =============================================================================

async def tool_handle_alert(ctx: DriverContext, action: str = "accept") -> str:
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_handle_alert", {"action": action})
    return json.dumps({"ok": ok, "action": action, "output": (out or "")[:400]}, ensure_ascii=False)


# =============================================================================
# APPIUM WRAPPERS (FIXED)
# =============================================================================

async def tool_launch_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    """
    repo: appium_activate_app  (bundleId)
    Sur Android, on tente bundleId puis packageName.
    """
    p = (pkg or ctx.app_package).strip()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_activate_app", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_activate_app", {"packageName": p})
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_terminate_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    """
    repo: appium_terminateApp
    On tente bundleId puis packageName.
    """
    p = (pkg or ctx.app_package).strip()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_terminateApp", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_terminateApp", {"packageName": p})
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    FIX (C)(D):
      - Stratégie 1: generate_locators => (using,value) => find_element => elementId => click
      - Stratégie 2: find_element (accessibility id / xpath variants)
    """
    # Stratégie 1: locator généré
    gen = _best_locator_from_generate_locators(ctx.last_locators, target_text)
    if gen:
        using, value, item = gen
        ok_find, out_find = await appium_find(ctx, using, value)
        el = _el_id(out_find)
        if ok_find and el:
            async with ctx.lock:
                ok_click, out_click = await ctx.mcp.call("appium_click", {"elementId": el})
            return json.dumps(
                {
                    "ok": ok_click,
                    "strategy": "generated_locator",
                    "target_text": target_text,
                    "using": using,
                    "value": value,
                    "element_id": el,
                    "click_output": (out_click or "")[:300],
                },
                ensure_ascii=False,
            )

    # Stratégie 2: heuristiques
    locators = [
        ("accessibility id", target_text),
        ("xpath", f'//*[@text={json.dumps(target_text)}]'),
        ("xpath", f'//*[@content-desc={json.dumps(target_text)}]'),
        ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
        ("xpath", f'//*[contains(@content-desc,{json.dumps(target_text)})]'),
    ]

    for strat, sel in locators:
        ok, out = await appium_find(ctx, strat, sel)
        if not ok:
            continue
        el = _el_id(out)
        if not el:
            continue
        async with ctx.lock:
            ok2, out2 = await ctx.mcp.call("appium_click", {"elementId": el})
        return json.dumps(
            {"ok": ok2, "strategy": strat, "element_id": el, "click_output": (out2 or "")[:300]},
            ensure_ascii=False,
        )

    return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"}, ensure_ascii=False)


async def tool_ui_type(ctx: DriverContext, text: str) -> str:
    async with ctx.lock:
        # focused field
        ok, out = await ctx.mcp.call("appium_find_element", {"xpath": "//*[@focused='true']"})
        if not ok:
            # compat fallback
            ok, out = await appium_find(ctx, "xpath", "//*[@focused='true']")
        if not ok:
            return json.dumps({"ok": False, "error": "No focused field. Call ui_click on an input first."}, ensure_ascii=False)

        el = _el_id(out)
        if not el:
            return json.dumps({"ok": False, "error": "focused element id not found"}, ensure_ascii=False)

        ok2, out2 = await ctx.mcp.call("appium_set_value", {"elementId": el, "text": text})
    return json.dumps({"ok": ok2, "element_id": el, "output": (out2 or "")[:300]}, ensure_ascii=False)


async def tool_ui_swipe(ctx: DriverContext, direction: str = "down") -> str:
    d = (direction or "down").strip().lower()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_scroll", {"direction": d})
        if not ok:
            ok, out = await ctx.mcp.call("appium_swipe", {"direction": d})
    return json.dumps({"ok": ok, "direction": d, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_get_text(ctx: DriverContext, target_text: str) -> str:
    locators = [
        ("accessibility id", target_text),
        ("xpath", f'//*[@text={json.dumps(target_text)}]'),
        ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
    ]
    for strat, sel in locators:
        ok, out = await appium_find(ctx, strat, sel)
        if not ok:
            continue
        el = _el_id(out)
        if not el:
            continue
        async with ctx.lock:
            ok2, txt = await ctx.mcp.call("appium_get_text", {"elementId": el})
        return json.dumps({"ok": ok2, "element": target_text, "text": (txt or "")[:500]}, ensure_ascii=False)

    return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"}, ensure_ascii=False)


async def tool_scroll_to_element(ctx: DriverContext, target_text: str) -> str:
    async with ctx.lock:
        ok, out = await ctx.mcp.call(
            "appium_scroll_to_element",
            {"strategy": "xpath", "selector": f'//*[contains(@text,{json.dumps(target_text)})]'},
        )
        if not ok:
            ok, out = await ctx.mcp.call(
                "appium_scroll_to_element",
                {"strategy": "accessibility id", "selector": target_text},
            )
    return json.dumps({"ok": ok, "target": target_text, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_double_tap(ctx: DriverContext, target_text: str) -> str:
    ok, out = await appium_find(ctx, "xpath", f'//*[contains(@text,{json.dumps(target_text)})]')
    if not ok:
        return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"}, ensure_ascii=False)

    el = _el_id(out)
    if not el:
        return json.dumps({"ok": False, "error": "element id not found"}, ensure_ascii=False)

    async with ctx.lock:
        ok2, out2 = await ctx.mcp.call("appium_double_tap", {"elementId": el})
    return json.dumps({"ok": ok2, "element": target_text, "output": (out2 or "")[:300]}, ensure_ascii=False)


# =============================================================================
# BARRIER
# =============================================================================

class Barrier:
    def __init__(self):
        self._cond = asyncio.Condition()
        self._n = 0
        self._gen = 0

    async def wait(self, who: str) -> str:
        async with self._cond:
            g = self._gen
            self._n += 1
            if self._n >= 2:
                self._n = 0
                self._gen += 1
                self._cond.notify_all()
                return f"[BARRIER] released gen={self._gen} (last={who})"
            while g == self._gen:
                await self._cond.wait()
            return f"[BARRIER] released gen={self._gen} (waiter={who})"


# =============================================================================
# OPENAI TOOL DEFINITIONS — ReAct enrichi
# =============================================================================

def _t(name, desc, props, req=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req or []},
        },
    }


def build_tools() -> List[Dict[str, Any]]:
    return [
        _t("observe", "Observe UI complète: locators + page_source + screenshot. À appeler après chaque action.", {}, []),
        _t("handle_alert", "Accepte/refuse popup ou permission système", {"action": {"type": "string", "enum": ["accept", "dismiss"]}}, []),
        _t("launch_app", "Lance ou ramène l'app au premier plan", {"packageName": {"type": "string"}}, []),
        _t("terminate_app", "Ferme l'app", {"packageName": {"type": "string"}}, []),
        _t("ui_click", "Clique un élément par son texte visible ou accessibility id", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("ui_type", "Tape dans le champ focalisé (cliquer le champ d'abord si besoin)", {"text": {"type": "string"}}, ["text"]),
        _t("ui_swipe", "Scroll/swipe dans une direction", {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}}, []),
        _t("scroll_to_element", "Scrolle jusqu'à rendre visible un élément par son texte", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("get_text", "Lit la valeur textuelle d'un élément visible sur l'écran", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("double_tap", "Double-tap sur un élément par son texte visible", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("sync_barrier", "Synchronise les deux drivers avant de continuer", {}, []),
        _t("finish", "Termine le test avec un statut et des notes", {"status": {"type": "string", "enum": ["success", "failure", "blocked"]}, "notes": {"type": "string"}}, ["status"]),
    ]


# =============================================================================
# REACT LOOP
# =============================================================================

SYSTEM_REACT = """Tu es un agent QA mobile autonome (ReAct : Observe → Raisonne → Agis).
Tu exécutes un PLAN DE TEST structuré fourni au départ. Tu pilotes une app Android via
Appium MCP en utilisant UNIQUEMENT les tools fournis.

Processus strict :
1. Commence TOUJOURS par "observe".
2. Suit le plan étape par étape. Après chaque action, appelle "observe".
3. Si une popup/permission apparaît → handle_alert("accept") immédiatement.
4. N'agis QUE sur des éléments vus dans les locators de la dernière observation.
5. Si l'état attendu n'est pas visible, essaie scroll_to_element ou ui_swipe puis observe.
6. Quand toutes les étapes sont validées → finish(status="success") avec un résumé.
""".strip()


async def run_react(ac: AsyncOpenAI, ctx: DriverContext, barrier: Barrier, summary: str) -> Dict[str, Any]:
    tools = build_tools()

    async def _verify_expected(expected: str) -> bool:
        if not expected:
            return True
        try:
            async with ctx.lock:
                ok, src = await ctx.mcp.call("appium_get_page_source", {})
            if not ok:
                return True
            return expected.lower()[:30] in (src or "").lower()
        except Exception:
            return True

    async def _dispatch(name: str, args: Dict[str, Any], expected: str = "") -> str:
        if name == "observe":
            return await tool_observe_rich(ctx)

        if name == "sync_barrier":
            return await barrier.wait(ctx.name)

        if name == "finish":
            return json.dumps({"ok": True})

        if name == "handle_alert":
            act = args.get("action", "accept")
            out = await tool_handle_alert(ctx, act)
            await _save_screenshot(ctx, f"alert_{act}")
            return out

        if name == "launch_app":
            out = await tool_launch_app(ctx, args.get("packageName"))
            await _save_screenshot(ctx, "launch_app")
            return out

        if name == "terminate_app":
            out = await tool_terminate_app(ctx, args.get("packageName"))
            await _save_screenshot(ctx, "terminate_app")
            return out

        if name == "ui_click":
            tgt = args.get("target_text", "")
            out = await tool_ui_click(ctx, tgt)
            await _save_screenshot(ctx, f"click_{_safe_slug(tgt, 20)}")
            _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "ui_click", "target": tgt, "expected": expected, "device": ctx.device_id})
            # petite validation (soft)
            try:
                if expected and not await _verify_expected(expected):
                    out += f' [WARN expected not visible: "{expected[:40]}"]'
            except Exception:
                pass
            return out

        if name == "ui_type":
            txt = args.get("text", "")
            out = await tool_ui_type(ctx, txt)
            await _save_screenshot(ctx, f"type_{_safe_slug(txt, 20)}")
            _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "ui_type", "text": txt[:80], "device": ctx.device_id})
            return out

        if name == "ui_swipe":
            d = args.get("direction", "down")
            out = await tool_ui_swipe(ctx, d)
            await _save_screenshot(ctx, f"swipe_{d}")
            return out

        if name == "scroll_to_element":
            tgt = args.get("target_text", "")
            out = await tool_scroll_to_element(ctx, tgt)
            await _save_screenshot(ctx, f"scroll_to_{_safe_slug(tgt, 20)}")
            _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "scroll_to_element", "target": tgt, "device": ctx.device_id})
            return out

        if name == "get_text":
            tgt = args.get("target_text", "")
            out = await tool_get_text(ctx, tgt)
            _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "get_text", "target": tgt, "result": out[:200], "device": ctx.device_id})
            return out

        if name == "double_tap":
            tgt = args.get("target_text", "")
            out = await tool_double_tap(ctx, tgt)
            await _save_screenshot(ctx, f"doubletap_{_safe_slug(tgt, 20)}")
            _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "double_tap", "target": tgt, "device": ctx.device_id})
            return out

        return json.dumps({"ok": False, "error": f"Unknown tool {name}"})

    plan = await generate_plan(summary, ac)
    plan_txt = "\n".join(
        f"  Étape {s.get('step','?')}: {s.get('intent','?')} → attendu: {s.get('expected','?')}"
        for s in plan
    )
    print(f"  📋 Plan ({len(plan)} étapes) :\n{plan_txt}")

    try:
        (ctx.session_dir / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_REACT},
        {"role": "user", "content": (
            f"Résumé Jira:\n{summary}\n\n"
            f"Driver: {ctx.name} | Device: {ctx.device_id} | App: {ctx.app_name} ({ctx.app_package})\n\n"
            f"PLAN DE TEST À SUIVRE :\n{plan_txt}\n\n"
            "Commence par observe, puis exécute le plan en ordre. "
            "Après CHAQUE action, appelle observe."
        )},
    ]

    final: Dict[str, Any] = {"status": "blocked", "notes": "no finish called", "driver": ctx.name, "device": ctx.device_id}

    # astuce: injecter l'expected courant dans les messages en rappel user (soft guidance)
    def _expected_for_step_idx(idx: int) -> str:
        if idx < 0 or idx >= len(plan):
            return ""
        return str(plan[idx].get("expected", "") or "")

    step_idx = 0  # index logique (soft) du plan
    current_expected = _expected_for_step_idx(step_idx)

    for turn in range(1, MAX_TURNS_PER_DRIVER + 1):
        # rappeler l'étape en cours
        if turn == 1 or (turn % 3 == 0):
            msgs.append({"role": "user", "content": f"Étape courante attendue: {current_expected or '(aucune)'}"})

        resp = await safe_chat(
            ac,
            model=MODEL,
            messages=msgs,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=1400,
        )
        msg = resp.choices[0].message
        msgs.append({"role": "assistant", "content": msg.content or ""})

        calls = getattr(msg, "tool_calls", None)
        if not calls:
            msgs.append({"role": "user", "content": "Appelle un tool (observe/ui_click/...) ou finish."})
            continue

        for tc in calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if DEBUG_TOOLS:
                print(f"  [TURN {turn:02d}] [{ctx.device_id}] LLM→ {tc.function.name}({trunc(json.dumps(args, ensure_ascii=False))[:160]})")

            if tc.function.name == "finish":
                final = {
                    "status": args.get("status", "blocked"),
                    "notes": args.get("notes", ""),
                    "turn": turn,
                    "driver": ctx.name,
                    "device": ctx.device_id,
                    "plan": plan,
                }
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"ok": True})})
                _append_trace(ctx.session_dir, {"ts": datetime.now().isoformat(), "step": ctx.step, "action": "finish", "status": final["status"], "notes": final["notes"][:200], "device": ctx.device_id})
                return final

            out = await _dispatch(tc.function.name, args, current_expected)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})

            # soft progression : si l'agent observe après une action, on peut tenter d'avancer
            # (pas parfait, mais aide à injecter expected suivant)
            if tc.function.name == "observe" and step_idx < len(plan) - 1:
                # si expected actuel est vu, on avance
                try:
                    if current_expected and await _verify_expected(current_expected):
                        step_idx += 1
                        current_expected = _expected_for_step_idx(step_idx)
                except Exception:
                    pass

    return final


# =============================================================================
# JIRA FETCH + SUMMARIZE
# =============================================================================

_JIRA_SYS = f"""Tu es QA Automation. Ticket cible: {TICKET_KEY}.
Résume le ticket de façon actionnable en te basant sur les test details du ticket qui correspondent au  customfiled_11504. Retourne STRICTEMENT :
- Titre:
- test details(customfiled_11504)
- Objectif:
- Plateforme:
- App (package Android si connu):
- Données (inputs):
- Résultats attendus:
""".strip()


async def jira_fetch_and_summarize(ac: AsyncOpenAI) -> str:
    async with MCPHttp(JIRA_MCP_URL) as jira:
        tools = await jira.list_tools()
        oa_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]

        msgs: List[Dict[str, Any]] = [
            {"role": "system", "content": _JIRA_SYS},
            {"role": "user", "content": f"Récupère le ticket {TICKET_KEY}."},
        ]

        for _ in range(12):
            r = await safe_chat(ac, model=MODEL, messages=msgs, tools=oa_tools, tool_choice="auto", temperature=0.2, max_tokens=4000)
            m = r.choices[0].message
            msgs.append({"role": "assistant", "content": m.content or ""})
            if not getattr(m, "tool_calls", None):
                break
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                res = await jira.call_tool(tc.function.name, args)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": mcp_to_text(res)})

        msgs.append({"role": "user", "content": "Résumé final au format demandé."})
        fin = await safe_chat(ac, model=MODEL, messages=msgs, temperature=0.2, max_tokens=1800)
        return fin.choices[0].message.content or ""


# =============================================================================
# MAIN
# =============================================================================

def _make_http() -> httpx.AsyncClient:
    kw: Dict[str, Any] = dict(verify=False, follow_redirects=False, timeout=120.0)
    if PROXY_URL:
        try:
            return httpx.AsyncClient(proxy=PROXY_URL, **kw)  # type: ignore[arg-type]
        except Exception:
            return httpx.AsyncClient(proxies=PROXY_URL, **kw)  # type: ignore[arg-type]
    return httpx.AsyncClient(**kw)


async def main():
    devices = [d for d in [DEVICE_1_ID, DEVICE_2_ID] if d]
    if not devices:
        raise SystemExit("Définis DEVICE_1_ID (et optionnellement DEVICE_2_ID).")

    async with _make_http() as http:
        ac = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, http_client=http)

        # 1) Jira summary
        print("\n" + "=" * 60)
        print("(1) JIRA — fetch + résumé")
        print("=" * 60)
        try:
            summary = await jira_fetch_and_summarize(ac)
        except Exception as e:
            print(f"[WARN] Jira MCP non dispo ({e}). Résumé par défaut.")
            summary = (
                "- Titre: Test générique\n"
                "- Objectif: Ouvrir l'app et vérifier l'écran principal\n"
                "- Plateforme: Android\n"
                "- App (package Android si connu): (non spécifié)\n"
                "- Données: aucune\n"
                "- Résultats attendus: L'app s'ouvre et affiche son écran d'accueil."
            )
        print(summary)

        # 2) extract app info
        print("\n(2) Extraction app info depuis le résumé...")
        app_info = await extract_app_info(summary, ac)
        print(f"    → {app_info}")

        # 3) create sessions
        print("\n(3) Ouverture sessions Appium MCP (stdio)...")
        resolved = [resolve_app_info(app_info, i + 1) for i in range(len(devices))]
        print("    App cible par driver :")
        for i, r in enumerate(resolved):
            print(f"      driver{i+1}: {r['appPackage']} / {r['appActivity']}  [{r['appName']}]")

        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        app_slug = _safe_slug(resolved[0]["appName"], 20)
        run_dir = SCREENSHOTS_DIR / f"{_safe_slug(TICKET_KEY)}_{app_slug}_{run_ts}"
        session_dirs: List[pathlib.Path] = []
        for dev in devices:
            sd = run_dir / _safe_slug(dev.replace(":", "_"), 30)
            sd.mkdir(parents=True, exist_ok=True)
            session_dirs.append(sd)
        print(f"    📁 Screenshots → {run_dir}")

        barrier = Barrier()

        async with (
            MCPStdio(session_dirs[0]) as mcp1,
            MCPStdio(session_dirs[1] if len(devices) > 1 else session_dirs[0]) as mcp2,
        ):
            pairs: List[Tuple[MCPStdio, str, Dict[str, str]]] = [
                (mcp1, devices[0], resolved[0]),
            ]
            if len(devices) > 1:
                pairs.append((mcp2, devices[1], resolved[1]))

            # create_session per device
            for mcp, dev, rinfo in pairs:
                caps = {
                    "platformName": "Android",
                    "appium:automationName": "UiAutomator2",
                    "appium:udid": dev,
                    "appium:appPackage": rinfo["appPackage"],
                    "appium:appActivity": rinfo["appActivity"],
                    "appium:autoGrantPermissions": True,
                    "appium:newCommandTimeout": 300,
                    "appium:noReset": True,
                    "appium:fullReset": False,
                }

                ok, out = await mcp.call("select_platform", {"platform": "android"}, attempts=2)
                if DEBUG_TOOLS:
                    print(f"    [{dev}] select_platform: {'OK' if ok else 'FAIL'} — {trunc(out)[:120]}")

                ok, out = await mcp.call(
                    "create_session",
                    {
                        "platform": "android",
                        "remoteServerUrl": APPIUM_SERVER_URL,
                        "capabilities": caps,
                    },
                    attempts=2,
                )
                print(f"    [{dev}] create_session ({rinfo['appPackage']}): {'OK' if ok else 'FAIL'} — {trunc(out)[:140]}")

            # contexts
            ctxs: List[DriverContext] = []
            for i, dev in enumerate(devices):
                ctxs.append(
                    DriverContext(
                        name=f"driver{i+1}",
                        device_id=dev,
                        app_package=resolved[i]["appPackage"],
                        app_activity=resolved[i]["appActivity"],
                        app_name=resolved[i]["appName"],
                        mcp=[mcp1, mcp2][i] if len(devices) > 1 else mcp1,
                        lock=asyncio.Lock(),
                        session_dir=session_dirs[i],
                    )
                )

            try:
                print("\n(4) ReAct en parallèle...")
                tasks = [run_react(ac, ctx, barrier, summary) for ctx in ctxs]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                for mcp in ([mcp1, mcp2] if len(devices) > 1 else [mcp1]):
                    await mcp.call("delete_session", {})

    # bilan
    print("\n" + "=" * 60)
    print("BILAN")
    print("=" * 60)
    overall_ok = True
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  driver{i+1}: ❌ EXCEPTION — {r}")
            overall_ok = False
        else:
            icon = "✅" if r.get("status") == "success" else "❌"  # type: ignore
            print(f"  driver{i+1} [{r.get('device')}]: {icon} {r.get('status','?').upper()} — {str(r.get('notes',''))[:100]}")  # type: ignore
            if r.get("status") != "success":  # type: ignore
                overall_ok = False
    print("RÉSULTAT :", "✅ PASS" if overall_ok else "❌ FAIL")


if __name__ == "__main__":
    asyncio.run(main())