"""
script_jira_appium_v3_stdiofix.py — Runner Jira + Appium MCP (STDIO FIX + LOCATORS FORMAT FIX)

✅ Ce script inclut TOUTES les corrections demandées :

1) ✅ FIX MAJEUR : corruption JSON-RPC (logs appium-mcp sur stdout)
   -> Ajout d’un wrapper "stdio filter proxy" (mcp_stdio_filter.py) généré automatiquement
   -> Le wrapper ne laisse passer sur stdout QUE les lignes JSON-RPC valides.
      Tout le reste va sur stderr (logs), donc plus de "Invalid JSON trailing characters".

2) ✅ FIX generate_locators format :
   -> Ton locators_trace montre "locators_raw" = JSON STRING contenant {"interactableElements":[...]}
      parfois double-encodé (string JSON dans un champ JSON).
   -> Le script parse correctement :
      - list
      - dict {interactableElements:[...]}
      - string JSON double-encodée

3) ✅ FIX click/get_text :
   -> appium_get_text attend elementUUID (pas elementId)
   -> appium_click attend elementUUID (suivant versions). On supporte les deux.
   -> On détecte automatiquement si la réponse find_element contient elementId/elementUUID.

4) ✅ FIX find_element paramètres :
   -> Supporte {using,value} ET {strategy,selector} ET formes directes (xpath/id/accessibility id)

5) ✅ OFFLINE SAFE :
   -> Si Jira MCP 401 ou LLM 401 : le script continue (fallback env + plan minimal)

Tu peux lancer tel quel.

Variables d’environnement clés :
- GLOBAL_PACKAGE / DRIVER1_PACKAGE / DRIVER2_PACKAGE
- APP_ACTIVITY (optionnel)
- DEVICE_1_ID / DEVICE_2_ID
- APPIUM_SERVER_URL
- LLM_BASE_URL / LLM_API_KEY (optionnel, sinon fallback)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import pathlib
import subprocess
import threading
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

DEVICE_1_ID = os.getenv("DEVICE_1_ID", "").strip()
DEVICE_2_ID = os.getenv("DEVICE_2_ID", "").strip()

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


def _safe_slug(s: str, maxlen: int = 30) -> str:
    return re.sub(r"[^\w\-]", "_", s)[:maxlen]


async def safe_chat(ac: AsyncOpenAI, **kw):
    last: Optional[Exception] = None
    for i in range(3):
        try:
            return await ac.chat.completions.create(**kw)
        except Exception as e:
            last = e
            await asyncio.sleep(0.5 * (i + 1))
    raise last  # type: ignore[misc]


def _maybe_json_loads(s: str) -> Any:
    """
    Parse JSON robuste: supporte double-encodage (string JSON qui contient du JSON).
    """
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    # enlever ```json etc
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    try:
        obj = json.loads(raw)
    except Exception:
        return None

    # double-encodage: obj est une string JSON
    if isinstance(obj, str):
        inner = obj.strip()
        if inner.startswith("{") or inner.startswith("["):
            try:
                return json.loads(inner)
            except Exception:
                return obj
    return obj


def _extract_element_uuid(text: str) -> Optional[str]:
    """
    Réponse appium-mcp : peut contenir elementUUID ou elementId.
    On extrait n'importe quel UUID.
    """
    if not text:
        return None
    m = re.search(
        r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
        text,
        re.I,
    )
    return m.group(1) if m else None


# =============================================================================
# FIX STDIO JSON-RPC: wrapper filter proxy (auto-généré)
# =============================================================================

def ensure_stdio_filter(path: pathlib.Path) -> pathlib.Path:
    """
    Crée un petit proxy python qui filtre stdout du serveur MCP:
    - forward uniquement les lignes JSON valides contenant "jsonrpc":"2.0" vers stdout
    - tout le reste va en stderr
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path

    code = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, threading

def pump(src, dst):
    for line in iter(src.readline, ''):
        if not line:
            break
        dst.write(line)
        dst.flush()

def is_jsonrpc(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        obj = json.loads(s)
    except Exception:
        return False
    return isinstance(obj, dict) and obj.get("jsonrpc") == "2.0"

def main():
    if len(sys.argv) < 2:
        print("Usage: mcp_stdio_filter.py <cmd> [args...]", file=sys.stderr)
        return 2

    cmd = sys.argv[1:]
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    t_err = threading.Thread(target=pump, args=(p.stderr, sys.stderr), daemon=True)
    t_err.start()

    def pump_stdin():
        try:
            for line in iter(sys.stdin.readline, ''):
                if not line:
                    break
                p.stdin.write(line)
                p.stdin.flush()
        except Exception:
            pass
        try:
            p.stdin.close()
        except Exception:
            pass

    t_in = threading.Thread(target=pump_stdin, daemon=True)
    t_in.start()

    for line in iter(p.stdout.readline, ''):
        if not line:
            break
        if is_jsonrpc(line):
            sys.stdout.write(line)
            sys.stdout.flush()
        else:
            sys.stderr.write(line)
            sys.stderr.flush()

    return p.wait()

if __name__ == "__main__":
    raise SystemExit(main())
'''
    path.write_text(code, encoding="utf-8")
    try:
        os.chmod(path, 0o755)
    except Exception:
        pass
    return path


# =============================================================================
# TRANSPORT STDIO (Appium MCP) — avec stdio filter proxy
# =============================================================================

def _stdio_params(screenshots_dir: pathlib.Path) -> StdioServerParameters:
    pt = os.path.join(ANDROID_HOME, "platform-tools")
    tls = os.path.join(ANDROID_HOME, "tools")
    pth = os.environ.get("PATH", "")
    for p in [pt, tls]:
        if p and p not in pth:
            pth = p + os.pathsep + pth

    # proxy file
    proxy = ensure_stdio_filter(pathlib.Path(APPIUM_MCP_DIR) / "mcp_stdio_filter.py")

    # IMPORTANT: on lance python proxy -> node server
    return StdioServerParameters(
        command="python",
        args=[
            str(proxy),
            "node",
            os.path.join(APPIUM_MCP_DIR, "dist", "index.js"),
            "--transport=stdio",
        ],
        cwd=APPIUM_MCP_DIR,
        env={
            **os.environ,
            "ANDROID_HOME": ANDROID_HOME,
            "ANDROID_SDK_ROOT": ANDROID_HOME,
            "PATH": pth,
            "NO_UI": "1",
            "SCREENSHOTS_DIR": str(screenshots_dir),
            # même si appium-mcp loggue encore, le proxy filtrera.
            "LOG_LEVEL": "info",
            "APPIUM_LOG_LEVEL": "info",
            "APPIUM_MCP_LOG_LEVEL": "info",
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

        # cache tools
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

    def has_tool(self, name: str) -> bool:
        return name in self.tools_by_name if self.tools_by_name else True

    async def raw(self, tool: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        assert self.session is not None
        resp = await asyncio.wait_for(
            self.session.call_tool(tool, args),  # type: ignore
            timeout=TOOL_TIMEOUT_S,
        )
        text = mcp_to_text(resp)

        is_error = getattr(resp, "isError", None)
        if isinstance(is_error, bool):
            return (not is_error), text

        tl = (text or "").lower()
        if any(s in tl for s in ["invalid arguments", "traceback", "error:", "[err]", "exception", "mcp error"]):
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
# BRIQUE 1 — EXTRACTION APP INFO (LLM) + fallback
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
    data = json.loads(raw)
    return {
        "appPackage": str(data.get("appPackage", "")),
        "appActivity": str(data.get("appActivity", "")),
        "appName": str(data.get("appName", "Application")),
        "platform": str(data.get("platform", "android")),
    }


def resolve_app_info(llm_info: Dict[str, str], driver_index: int = 1) -> Dict[str, str]:
    info = dict(llm_info)
    per_driver = DRIVER1_PACKAGE if driver_index == 1 else DRIVER2_PACKAGE

    pkg = per_driver or GLOBAL_PACKAGE or info.get("appPackage", "")
    act = info.get("appActivity", "")

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
# PLANNER (LLM) + fallback
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
    data = json.loads(raw)
    plan = data.get("plan", [])
    if isinstance(plan, list) and plan:
        return plan
    return [{"step": 1, "intent": "Ouvrir l'app", "expected": ""}]


# =============================================================================
# TRACE
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
    session_dir: pathlib.Path
    step: int = 0
    last_locators_raw: str = ""


# =============================================================================
# LOCATORS PARSING (FIXED for your format)
# =============================================================================

def parse_generate_locators_payload(raw: str) -> List[Dict[str, Any]]:
    """
    Supporte:
      - list directement
      - dict {interactableElements:[...]}
      - string JSON double encodée
    """
    obj = _maybe_json_loads(raw)
    if obj is None:
        return []
    if isinstance(obj, list):
        return [it for it in obj if isinstance(it, dict)]
    if isinstance(obj, dict):
        for k in ("interactableElements", "elements", "items", "result"):
            v = obj.get(k)
            if isinstance(v, list):
                return [it for it in v if isinstance(it, dict)]
    return []


def find_best_locator(items: List[Dict[str, Any]], target_text: str) -> Optional[Tuple[str, str]]:
    tl = target_text.lower().strip()

    def pick_using_value(it: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        # ton format: {"locators": {"xpath": "...", "class name": "..."}}
        locs = it.get("locators") or it.get("locator") or it.get("Locators") or {}
        if isinstance(locs, dict):
            # priorité: accessibility id / id / xpath
            for key in ("accessibility id", "id", "xpath"):
                if key in locs and locs[key]:
                    return key, str(locs[key])
            # sinon premier locator dispo
            for k, v in locs.items():
                if v:
                    return str(k), str(v)
        return None

    def fields(it: Dict[str, Any]) -> List[str]:
        out = []
        for k in ("text", "contentDesc", "content-desc", "label", "name", "resourceId"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        return out

    # exact
    for it in items:
        vals = [v.lower() for v in fields(it)]
        if any(v == tl for v in vals):
            uv = pick_using_value(it)
            if uv:
                return uv

    # partial
    for it in items:
        vals = [v.lower() for v in fields(it)]
        if any(tl in v for v in vals):
            uv = pick_using_value(it)
            if uv:
                return uv

    return None


# =============================================================================
# APPIUM COMPAT HELPERS (elementUUID vs elementId)
# =============================================================================

def normalize_locator_strategy(strategy: str) -> str:
    s = (strategy or "").strip().lower()
    # appium-mcp accepte généralement: "xpath", "id", "accessibility id", "class name"
    return s


async def appium_find_element(ctx: DriverContext, strategy: str, selector: str) -> Tuple[bool, str]:
    """
    Support {using,value} ET {strategy,selector} et quelques raccourcis.
    """
    strategy = normalize_locator_strategy(strategy)
    selector = str(selector)

    # attempt W3C
    ok, out = await ctx.mcp.call("appium_find_element", {"using": strategy, "value": selector})
    if ok:
        return ok, out

    # attempt legacy
    ok2, out2 = await ctx.mcp.call("appium_find_element", {"strategy": strategy, "selector": selector})
    if ok2:
        return ok2, out2

    # attempt direct keys (some servers accept {"xpath": "..."} etc.)
    if strategy in ("xpath", "id", "accessibility id", "class name"):
        ok3, out3 = await ctx.mcp.call("appium_find_element", {strategy: selector})
        return ok3, out3

    return False, out2


async def appium_click_uuid(ctx: DriverContext, element_uuid: str) -> Tuple[bool, str]:
    """
    Certains schémas appium-mcp utilisent elementUUID, d'autres elementId.
    On tente les deux.
    """
    ok, out = await ctx.mcp.call("appium_click", {"elementUUID": element_uuid})
    if ok:
        return ok, out
    ok2, out2 = await ctx.mcp.call("appium_click", {"elementId": element_uuid})
    return ok2, out2


async def appium_get_text_uuid(ctx: DriverContext, element_uuid: str) -> Tuple[bool, str]:
    ok, out = await ctx.mcp.call("appium_get_text", {"elementUUID": element_uuid})
    if ok:
        return ok, out
    ok2, out2 = await ctx.mcp.call("appium_get_text", {"elementId": element_uuid})
    return ok2, out2


async def appium_set_value_uuid(ctx: DriverContext, element_uuid: str, text: str) -> Tuple[bool, str]:
    ok, out = await ctx.mcp.call("appium_set_value", {"elementUUID": element_uuid, "text": text})
    if ok:
        return ok, out
    ok2, out2 = await ctx.mcp.call("appium_set_value", {"elementId": element_uuid, "text": text})
    return ok2, out2


# =============================================================================
# TOOLS: observe/click/type/swipe/get_text/scroll_to_element/alerts/app mgmt
# =============================================================================

async def tool_observe_rich(ctx: DriverContext) -> str:
    async with ctx.lock:
        ok_src, src = await ctx.mcp.call("appium_get_page_source", {})
        ok_locs, locs = await ctx.mcp.call("generate_locators", {})
    ctx.last_locators_raw = locs
    snap = await _save_screenshot(ctx, "observe")

    _append_trace(
        ctx.session_dir,
        {
            "ts": datetime.now().isoformat(),
            "step": ctx.step,
            "action": "observe",
            "device": ctx.device_id,
            "ok_page_source": ok_src,
            "ok_locators": ok_locs,
            "locators_raw": trunc(locs),
        },
    )

    return json.dumps(
        {
            "driver": ctx.name,
            "device": ctx.device_id,
            "page_source": (src or "")[:4000],
            "screenshot_saved": str(snap) if snap else "",
            "locators_raw": (locs or "")[:3000],
        },
        ensure_ascii=False,
    )


async def tool_handle_alert(ctx: DriverContext, action: str = "accept") -> str:
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_handle_alert", {"action": action})
    await _save_screenshot(ctx, f"alert_{action}")
    return json.dumps({"ok": ok, "action": action, "output": (out or "")[:400]}, ensure_ascii=False)


async def tool_launch_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    p = (pkg or ctx.app_package).strip()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_activate_app", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_activate_app", {"packageName": p})
    await _save_screenshot(ctx, "launch_app")
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_terminate_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    p = (pkg or ctx.app_package).strip()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_terminateApp", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_terminateApp", {"packageName": p})
    await _save_screenshot(ctx, "terminate_app")
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    Clique via:
      1) generate_locators -> pick best locator -> find_element -> click
      2) fallback heuristiques xpath/accessibility id
    """
    items = parse_generate_locators_payload(ctx.last_locators_raw)
    uv = find_best_locator(items, target_text)
    if uv:
        using, value = uv
        ok_find, out_find = await appium_find_element(ctx, using, value)
        el = _extract_element_uuid(out_find)
        if ok_find and el:
            ok_click, out_click = await appium_click_uuid(ctx, el)
            await _save_screenshot(ctx, f"click_{_safe_slug(target_text, 20)}")
            return json.dumps(
                {"ok": ok_click, "strategy": "generate_locators", "using": using, "value": value, "elementUUID": el, "output": (out_click or "")[:300]},
                ensure_ascii=False,
            )

    # fallback heuristics
    candidates = [
        ("accessibility id", target_text),
        ("xpath", f'//*[@text={json.dumps(target_text)}]'),
        ("xpath", f'//*[@content-desc={json.dumps(target_text)}]'),
        ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
        ("xpath", f'//*[contains(@content-desc,{json.dumps(target_text)})]'),
    ]
    for using, value in candidates:
        ok_find, out_find = await appium_find_element(ctx, using, value)
        el = _extract_element_uuid(out_find)
        if ok_find and el:
            ok_click, out_click = await appium_click_uuid(ctx, el)
            await _save_screenshot(ctx, f"click_{_safe_slug(target_text, 20)}")
            return json.dumps(
                {"ok": ok_click, "strategy": using, "selector": value, "elementUUID": el, "output": (out_click or "")[:300]},
                ensure_ascii=False,
            )

    return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"}, ensure_ascii=False)


async def tool_get_text(ctx: DriverContext, target_text: str) -> str:
    """
    Fix ton erreur:
      MCP error -32602: appium_get_text parameter validation failed: elementUUID expected string, received undefined
    => ça arrivait quand tu appelais get_text sans elementUUID.
    Ici on fait TOUJOURS find_element puis get_text(elementUUID).
    """
    items = parse_generate_locators_payload(ctx.last_locators_raw)
    uv = find_best_locator(items, target_text)
    candidates = []
    if uv:
        candidates.append(uv)
    candidates += [
        ("accessibility id", target_text),
        ("xpath", f'//*[@text={json.dumps(target_text)}]'),
        ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
    ]

    for using, value in candidates:
        ok_find, out_find = await appium_find_element(ctx, using, value)
        el = _extract_element_uuid(out_find)
        if ok_find and el:
            ok_txt, txt = await appium_get_text_uuid(ctx, el)
            return json.dumps({"ok": ok_txt, "element": target_text, "elementUUID": el, "text": (txt or "")[:500]}, ensure_ascii=False)

    return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"}, ensure_ascii=False)


async def tool_ui_type(ctx: DriverContext, text: str) -> str:
    # focused field
    ok_find, out_find = await appium_find_element(ctx, "xpath", "//*[@focused='true']")
    el = _extract_element_uuid(out_find)
    if not ok_find or not el:
        return json.dumps({"ok": False, "error": "No focused field. Use ui_click on input first."}, ensure_ascii=False)

    ok_set, out_set = await appium_set_value_uuid(ctx, el, text)
    await _save_screenshot(ctx, f"type_{_safe_slug(text, 20)}")
    return json.dumps({"ok": ok_set, "elementUUID": el, "output": (out_set or "")[:300]}, ensure_ascii=False)


async def tool_ui_swipe(ctx: DriverContext, direction: str = "down") -> str:
    d = (direction or "down").strip().lower()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_scroll", {"direction": d})
        if not ok:
            ok, out = await ctx.mcp.call("appium_swipe", {"direction": d})
    await _save_screenshot(ctx, f"swipe_{d}")
    return json.dumps({"ok": ok, "direction": d, "output": (out or "")[:300]}, ensure_ascii=False)


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
    await _save_screenshot(ctx, f"scroll_{_safe_slug(target_text, 20)}")
    return json.dumps({"ok": ok, "target": target_text, "output": (out or "")[:300]}, ensure_ascii=False)


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
# OPENAI TOOLS
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
        _t("observe", "Observe UI complète: locators + page_source + screenshot.", {}, []),
        _t("handle_alert", "Accepte/refuse popup ou permission système", {"action": {"type": "string", "enum": ["accept", "dismiss"]}}, []),
        _t("launch_app", "Lance / ramène l'app au premier plan", {"packageName": {"type": "string"}}, []),
        _t("terminate_app", "Ferme l'app", {"packageName": {"type": "string"}}, []),
        _t("ui_click", "Clique un élément par texte", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("ui_type", "Tape dans le champ focus", {"text": {"type": "string"}}, ["text"]),
        _t("ui_swipe", "Swipe/scroll", {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}}, []),
        _t("scroll_to_element", "Scroll jusqu'à voir l'élément", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("get_text", "Lit le texte d'un élément", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("sync_barrier", "Synchronise 2 drivers", {}, []),
        _t("finish", "Termine", {"status": {"type": "string", "enum": ["success", "failure", "blocked"]}, "notes": {"type": "string"}}, ["status"]),
    ]


# =============================================================================
# REACT LOOP
# =============================================================================

SYSTEM_REACT = """Tu es un agent QA mobile autonome (ReAct).
Règles strictes :
1) Commence par observe.
2) Après chaque action, observe.
3) Si alerte : handle_alert(accept).
4) Clique uniquement des éléments présents dans les locators.
5) Si bloqué : scroll_to_element ou ui_swipe puis observe.
6) Termine par finish.
""".strip()


async def run_react(ac: AsyncOpenAI, ctx: DriverContext, barrier: Barrier, summary: str) -> Dict[str, Any]:
    tools = build_tools()

    async def _dispatch(name: str, args: Dict[str, Any]) -> str:
        if name == "observe":
            return await tool_observe_rich(ctx)
        if name == "handle_alert":
            return await tool_handle_alert(ctx, args.get("action", "accept"))
        if name == "launch_app":
            return await tool_launch_app(ctx, args.get("packageName"))
        if name == "terminate_app":
            return await tool_terminate_app(ctx, args.get("packageName"))
        if name == "ui_click":
            return await tool_ui_click(ctx, args.get("target_text", ""))
        if name == "ui_type":
            return await tool_ui_type(ctx, args.get("text", ""))
        if name == "ui_swipe":
            return await tool_ui_swipe(ctx, args.get("direction", "down"))
        if name == "scroll_to_element":
            return await tool_scroll_to_element(ctx, args.get("target_text", ""))
        if name == "get_text":
            return await tool_get_text(ctx, args.get("target_text", ""))
        if name == "sync_barrier":
            return await barrier.wait(ctx.name)
        if name == "finish":
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": f"Unknown tool {name}"})

    # plan
    plan: List[Dict[str, str]]
    try:
        plan = await generate_plan(summary, ac)
    except Exception as e:
        print(f"[WARN] LLM plan non dispo ({e}). Plan fallback.")
        plan = [
            {"step": 1, "intent": "Lancer l'app", "expected": ""},
            {"step": 2, "intent": "Observer l'écran principal", "expected": ""},
        ]

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
            f"PLAN:\n{plan_txt}\n\n"
            "Commence par observe."
        )},
    ]

    final: Dict[str, Any] = {"status": "blocked", "notes": "no finish called", "driver": ctx.name, "device": ctx.device_id}

    for turn in range(1, MAX_TURNS_PER_DRIVER + 1):
        resp = await safe_chat(
            ac, model=MODEL, messages=msgs, tools=tools, tool_choice="auto",
            temperature=0.2, max_tokens=1200
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

            out = await _dispatch(tc.function.name, args)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})

    return final


# =============================================================================
# JIRA FETCH + SUMMARIZE (fallback)
# =============================================================================

_JIRA_SYS = f"""Tu es QA Automation. Ticket cible: {TICKET_KEY}.
Résume le ticket au format strict:
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

        print("\n" + "=" * 60)
        print("(1) JIRA — fetch + résumé")
        print("=" * 60)
        try:
            summary = await jira_fetch_and_summarize(ac)
        except Exception as e:
            print(f"[WARN] Jira MCP non dispo ({e}). Résumé par défaut.")
            summary = (
                "- Titre: Test générique\n"
                "- test details(customfiled_11504): N/A\n"
                "- Objectif: Ouvrir l'app et vérifier l'écran principal\n"
                "- Plateforme: Android\n"
                "- App (package Android si connu): (non spécifié)\n"
                "- Données: aucune\n"
                "- Résultats attendus: L'app s'ouvre et affiche son écran d'accueil."
            )
        print(summary)

        print("\n(2) Extraction app info depuis le résumé...")
        try:
            app_info = await extract_app_info(summary, ac)
        except Exception as e:
            print(f"[WARN] LLM extract_app_info non dispo ({e}). Fallback env uniquement.")
            app_info = {"appPackage": "", "appActivity": "", "appName": "Application", "platform": "android"}
        print(f"    → {app_info}")

        print("\n(3) Ouverture sessions Appium MCP (stdio)...")
        resolved = [resolve_app_info(app_info, i + 1) for i in range(len(devices))]
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
            pairs: List[Tuple[MCPStdio, str, Dict[str, str]]] = [(mcp1, devices[0], resolved[0])]
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
                    {"platform": "android", "remoteServerUrl": APPIUM_SERVER_URL, "capabilities": caps},
                    attempts=2,
                )
                print(f"    [{dev}] create_session: {'OK' if ok else 'FAIL'} — {trunc(out)[:140]}")

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
                results = await asyncio.gather(*[run_react(ac, ctx, barrier, summary) for ctx in ctxs], return_exceptions=True)
            finally:
                for mcp in ([mcp1, mcp2] if len(devices) > 1 else [mcp1]):
                    await mcp.call("delete_session", {})

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