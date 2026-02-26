from __future__ import annotations

import asyncio
import json
import os
import re
import sys
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

SCREENSHOTS_DIR = pathlib.Path(os.getenv("SCREENSHOTS_DIR", "./screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

LLM_API_KEY = os.getenv("LLM_API_KEY", "no-key")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
PROXY_URL = os.getenv("PROXY_URL", "")

DEVICE_1_ID = os.getenv("DEVICE_1_ID", "").strip()
DEVICE_2_ID = os.getenv("DEVICE_2_ID", "").strip()

# Stabilité d'abord : par défaut on fait 1 device.
# Pour activer 2 devices: export USE_TWO_DEVICES=1
USE_TWO_DEVICES = os.getenv("USE_TWO_DEVICES", "0").strip() in ("1", "true", "True", "yes", "YES")

GLOBAL_PACKAGE = os.getenv("GLOBAL_PACKAGE", "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", "").strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", "").strip()
APP_ACTIVITY = os.getenv("APP_ACTIVITY", "").strip()

# Stabilité (timing / retries)
ACTION_DELAY_S = float(os.getenv("ACTION_DELAY_S", "0.9"))          # pause courte après action
VERIFY_RETRIES = int(os.getenv("VERIFY_RETRIES", "3"))              # retries verify per step
ACTION_RETRIES = int(os.getenv("ACTION_RETRIES", "2"))              # retries action (click/type)
ALERT_DRAIN_MAX = int(os.getenv("ALERT_DRAIN_MAX", "3"))            # gérer popups automatiquement
SCROLL_TRIES = int(os.getenv("SCROLL_TRIES", "2"))                  # scroll_to_element retries
SWIPE_TRIES = int(os.getenv("SWIPE_TRIES", "2"))                    # swipe fallback retries

MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))
MAX_TOOL_LINES = int(os.getenv("MAX_TOOL_LINES", "300"))
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "60"))
TOOL_ATTEMPTS = int(os.getenv("TOOL_ATTEMPTS", "3"))

DEBUG = os.getenv("DEBUG", "0").strip() in ("1", "true", "True", "yes", "YES")


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


def _safe_slug(s: str, maxlen: int = 40) -> str:
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


def _maybe_json_loads(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    try:
        obj = json.loads(raw)
    except Exception:
        return None

    # double-encodage
    if isinstance(obj, str):
        inner = obj.strip()
        if inner.startswith("{") or inner.startswith("["):
            try:
                return json.loads(inner)
            except Exception:
                return obj
    return obj


def _extract_uuid(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(
        r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
        text,
        re.I,
    )
    return m.group(1) if m else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# =============================================================================
# JSON-RPC STDIO PROXY (anti logs sur stdout)
# =============================================================================

def ensure_stdio_filter(path: pathlib.Path) -> pathlib.Path:
    """
    Proxy python: forward uniquement JSON-RPC sur stdout.
    Tout le reste -> stderr.
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


def _python_exe() -> str:
    if sys.executable and pathlib.Path(sys.executable).exists():
        return sys.executable
    return "python"


def _stdio_params(screenshots_dir: pathlib.Path) -> StdioServerParameters:
    # PATH adb
    pt = os.path.join(ANDROID_HOME, "platform-tools")
    tls = os.path.join(ANDROID_HOME, "tools")
    pth = os.environ.get("PATH", "")
    for p in [pt, tls]:
        if p and p not in pth:
            pth = p + os.pathsep + pth

    proxy = ensure_stdio_filter(pathlib.Path(APPIUM_MCP_DIR) / "mcp_stdio_filter.py")

    return StdioServerParameters(
        command=_python_exe(),
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
            # les logs peuvent exister, proxy filtre.
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

    async def __aenter__(self) -> "MCPStdio":
        r, w = await self._stack.enter_async_context(stdio_client(server=self._p))
        self.session = await self._stack.enter_async_context(ClientSession(r, w))
        await self.session.initialize()
        return self

    async def __aexit__(self, *a):
        await self._stack.aclose()

    async def call(self, tool: str, args: Dict[str, Any], attempts: int = TOOL_ATTEMPTS) -> Tuple[bool, str]:
        assert self.session is not None
        last = ""
        for i in range(1, attempts + 1):
            try:
                resp = await asyncio.wait_for(self.session.call_tool(tool, args), timeout=TOOL_TIMEOUT_S)  # type: ignore
                txt = mcp_to_text(resp)
                is_error = getattr(resp, "isError", None)
                if isinstance(is_error, bool):
                    return (not is_error), txt
                # heuristique
                low = (txt or "").lower()
                if "mcp error" in low or "invalid arguments" in low or "traceback" in low:
                    return False, txt
                return True, txt
            except Exception as e:
                last = f"[ERR] {tool}: {e}"
                if i >= attempts:
                    return False, last
                await asyncio.sleep(0.6 * i)
        return False, last


# =============================================================================
# Jira MCP (optionnel)
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
            r, w = t.read_stream, t.write_stream  # type: ignore
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
# APP INFO RESOLUTION
# =============================================================================

_EXTRACT_PROMPT = """
Tu reçois un résumé de ticket Jira pour des tests mobiles Android.
Extrais UNIQUEMENT ces infos en JSON strict (sans markdown) :
{
  "appPackage":  "",
  "appActivity": "",
  "appName":     "Application",
  "platform":    "android"
}
Règles :
- Si non mentionné: appPackage/appActivity vides.
- Réponds uniquement le JSON.
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


def resolve_app_info(llm_info: Dict[str, str], driver_index: int) -> Dict[str, str]:
    info = dict(llm_info)
    per_driver = DRIVER1_PACKAGE if driver_index == 1 else DRIVER2_PACKAGE
    pkg = per_driver or GLOBAL_PACKAGE or info.get("appPackage", "")
    act = info.get("appActivity", "")

    if per_driver or GLOBAL_PACKAGE:
        act = APP_ACTIVITY or act

    if not pkg:
        raise SystemExit(
            "[ERREUR] Aucun package défini. Renseigne GLOBAL_PACKAGE (ou DRIVERx_PACKAGE)."
        )

    info["appPackage"] = pkg
    info["appActivity"] = act
    if pkg != llm_info.get("appPackage", ""):
        info["appName"] = pkg.split(".")[-1].capitalize() or info.get("appName", "Application")
    return info


# =============================================================================
# PLAN (LLM optionnel) — mais exécution déterministe
# =============================================================================

_PLANNER_PROMPT = """Tu es QA mobile.
À partir du résumé Jira, produis un plan JSON strict:
{
  "plan":[
    {"step":1,"intent":"Lancer l'app","expected":"Home"},
    {"step":2,"intent":"Ouvrir Contacts","expected":"Contacts"}
  ]
}
Règles:
- 3 à 8 étapes.
- intent: action simple.
- expected: texte indicateur visible (court) ou vide.
- JSON uniquement.
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
        # normalize
        out = []
        for s in plan:
            if isinstance(s, dict):
                out.append({
                    "step": str(s.get("step", "")),
                    "intent": str(s.get("intent", "")),
                    "expected": str(s.get("expected", "")),
                })
        return out
    return [{"step": "1", "intent": "Lancer l'app", "expected": ""}]


# =============================================================================
# TRACE + SCREENSHOTS
# =============================================================================

def trace_jsonl(session_dir: pathlib.Path, row: Dict[str, Any]) -> None:
    try:
        f = session_dir / "trace.jsonl"
        with f.open("a", encoding="utf-8") as w:
            w.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def save_screenshot(mcp: MCPStdio, session_dir: pathlib.Path, step_i: int, label: str) -> Optional[str]:
    try:
        ok, out = await mcp.call("appium_screenshot", {"outputDir": str(session_dir)})
        if not ok:
            return None
        # fichier le plus récent
        files = sorted(session_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        latest = files[-1]
        dest = session_dir / f"step_{step_i:03d}_{_safe_slug(label)}.png"
        if latest.name != dest.name:
            try:
                latest.rename(dest)
            except Exception:
                pass
        return str(dest)
    except Exception:
        return None


# =============================================================================
# LOCATORS PARSING + PRIORITY
# =============================================================================

def parse_locators(raw: str) -> List[Dict[str, Any]]:
    obj = _maybe_json_loads(raw)
    if obj is None:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for k in ("interactableElements", "elements", "items", "result"):
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def locator_candidates_from_item(it: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Retourne une liste (using,value) triée par priorité.
    On supporte des clés comme:
      it["locators"] = {"id": "...", "accessibility id":"...", "xpath":"..."}
      ou {"resource-id": "..."} etc.
    """
    locs = it.get("locators") or it.get("Locators") or it.get("locator") or {}
    if not isinstance(locs, dict):
        return []

    # normalisation clés
    norm: Dict[str, str] = {}
    for k, v in locs.items():
        if not v:
            continue
        key = str(k).strip().lower()
        val = str(v).strip()
        if not val:
            continue
        # alias
        if key in ("resource-id", "resourceid", "android:id", "androidid"):
            key = "id"
        if key in ("accessibility", "accessibilityid", "content-desc", "contentdesc"):
            key = "accessibility id"
        norm[key] = val

    # priorité
    order = ["id", "accessibility id", "xpath", "class name"]
    out: List[Tuple[str, str]] = []
    for k in order:
        if k in norm:
            out.append((k, norm[k]))
    # reste
    for k, v in norm.items():
        if (k, v) not in out:
            out.append((k, v))
    return out


def item_text_fields(it: Dict[str, Any]) -> List[str]:
    keys = ["text", "label", "name", "contentDesc", "content-desc", "resourceId", "resource-id"]
    vals = []
    for k in keys:
        v = it.get(k)
        if isinstance(v, str) and v.strip():
            vals.append(v.strip())
    return vals


def best_locator_for_target(items: List[Dict[str, Any]], target: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """
    Renvoie (using,value,item) pour le meilleur match target.
    - exact match sur text/label/contentDesc/resourceId
    - puis partial
    - puis None
    """
    t = target.lower().strip()
    if not t:
        return None

    # exact
    for it in items:
        fields = [x.lower() for x in item_text_fields(it)]
        if any(x == t for x in fields):
            cands = locator_candidates_from_item(it)
            if cands:
                using, value = cands[0]
                return using, value, it

    # partial
    for it in items:
        fields = [x.lower() for x in item_text_fields(it)]
        if any(t in x for x in fields):
            cands = locator_candidates_from_item(it)
            if cands:
                using, value = cands[0]
                return using, value, it

    return None


# =============================================================================
# APPIUM WRAPPERS (compat)
# =============================================================================

def norm_strategy(s: str) -> str:
    return (s or "").strip().lower()


async def appium_find(mcp: MCPStdio, using: str, value: str) -> Tuple[bool, str]:
    using = norm_strategy(using)
    # W3C format
    ok, out = await mcp.call("appium_find_element", {"using": using, "value": value})
    if ok:
        return ok, out
    # legacy
    ok2, out2 = await mcp.call("appium_find_element", {"strategy": using, "selector": value})
    if ok2:
        return ok2, out2
    # direct key sometimes
    ok3, out3 = await mcp.call("appium_find_element", {using: value})
    return ok3, out3


async def appium_click(mcp: MCPStdio, element_uuid: str) -> Tuple[bool, str]:
    ok, out = await mcp.call("appium_click", {"elementUUID": element_uuid})
    if ok:
        return ok, out
    ok2, out2 = await mcp.call("appium_click", {"elementId": element_uuid})
    return ok2, out2


async def appium_get_text(mcp: MCPStdio, element_uuid: str) -> Tuple[bool, str]:
    ok, out = await mcp.call("appium_get_text", {"elementUUID": element_uuid})
    if ok:
        return ok, out
    ok2, out2 = await mcp.call("appium_get_text", {"elementId": element_uuid})
    return ok2, out2


async def appium_set_value(mcp: MCPStdio, element_uuid: str, text: str) -> Tuple[bool, str]:
    ok, out = await mcp.call("appium_set_value", {"elementUUID": element_uuid, "text": text})
    if ok:
        return ok, out
    ok2, out2 = await mcp.call("appium_set_value", {"elementId": element_uuid, "text": text})
    return ok2, out2


# =============================================================================
# ALERT DRAIN (anti chaos)
# =============================================================================

ALERT_KEYWORDS = [
    # EN
    "allow", "while using", "only this time", "ok", "accept", "agree",
    # FR
    "autoriser", "uniquement", "ok", "accepter", "autorisation", "continuer",
    # Generic
    "permission", "permissions", "dialog", "alert",
]

def looks_like_alert(page_source: str) -> bool:
    s = (page_source or "").lower()
    return any(k in s for k in ALERT_KEYWORDS)


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
    session_dir: pathlib.Path
    step_counter: int = 0
    last_page_source: str = ""
    last_locators_raw: str = ""
    last_locators_items: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# OBSERVE (stable)
# =============================================================================

async def observe(ctx: DriverContext, reason: str) -> None:
    ok_src, src = await ctx.mcp.call("appium_get_page_source", {})
    ok_loc, loc = await ctx.mcp.call("generate_locators", {})

    ctx.last_page_source = src if ok_src else (src or "")
    ctx.last_locators_raw = loc if ok_loc else (loc or "")
    ctx.last_locators_items = parse_locators(ctx.last_locators_raw)

    ctx.step_counter += 1
    ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"observe_{reason}")

    trace_jsonl(ctx.session_dir, {
        "ts": _now(),
        "event": "observe",
        "reason": reason,
        "device": ctx.device_id,
        "ok_page_source": ok_src,
        "ok_locators": ok_loc,
        "screenshot": ss,
        "locators_count": len(ctx.last_locators_items),
    })

    if DEBUG:
        print(f"[{ctx.device_id}] observe({reason}) locators={len(ctx.last_locators_items)} ss={ss}")


async def drain_alerts(ctx: DriverContext) -> bool:
    """
    Essaie d'accepter les popups si détectées.
    Retourne True si une action alert a été faite.
    """
    acted = False
    for i in range(ALERT_DRAIN_MAX):
        if not looks_like_alert(ctx.last_page_source):
            return acted
        ok, out = await ctx.mcp.call("appium_handle_alert", {"action": "accept"})
        ctx.step_counter += 1
        ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"alert_accept_{i+1}")
        trace_jsonl(ctx.session_dir, {
            "ts": _now(),
            "event": "handle_alert",
            "attempt": i + 1,
            "device": ctx.device_id,
            "ok": ok,
            "output": trunc(out),
            "screenshot": ss,
        })
        acted = True
        await asyncio.sleep(ACTION_DELAY_S)
        await observe(ctx, "post_alert")
    return acted


# =============================================================================
# VERIFY (stable)
# =============================================================================

def verify_expected_in_source(page_source: str, expected: str) -> bool:
    exp = (expected or "").strip()
    if not exp:
        return True
    s = (page_source or "").lower()
    e = exp.lower()
    # match "contains" mais sur un expected court
    return e in s


# =============================================================================
# TARGET INFERENCE (stable-first)
# =============================================================================

TARGET_HINT_PROMPT = """
Tu es QA mobile.
On te donne:
- intent (action humaine)
- un extrait des éléments (texts/labels/resourceIds) visibles

Tu dois retourner UNIQUEMENT une string courte = le meilleur libellé à cliquer (target_text).
Règles:
- Retourne un texte qui existe déjà dans la liste si possible.
- Si rien: retourne une string vide.
Pas de JSON, pas d'explication.
""".strip()


def quick_guess_target(intent: str) -> str:
    """
    Heuristique: extrait un mot clé probable dans l'intent.
    """
    s = (intent or "").strip()
    if not s:
        return ""
    # si l'intent contient un mot entre guillemets
    m = re.search(r"[\"'“”‘’]([^\"'“”‘’]{2,50})[\"'“”‘’]", s)
    if m:
        return m.group(1).strip()
    # sinon prend le dernier mot “significatif”
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9_]{3,}", s)
    if not tokens:
        return ""
    # on évite les verbes fréquents
    blacklist = {"open", "ouvrir", "launch", "lancer", "click", "cliquer", "tap", "appuye", "aller", "go", "navigate", "verifier", "check"}
    tokens2 = [t for t in tokens if t.lower() not in blacklist]
    if not tokens2:
        return tokens[-1]
    return tokens2[-1]


async def infer_target_text(ac: AsyncOpenAI, intent: str, items: List[Dict[str, Any]]) -> str:
    """
    Stabilité: d’abord heuristique, ensuite LLM (optionnel).
    """
    guess = quick_guess_target(intent)
    if guess:
        return guess

    # LLM fallback (si dispo)
    # On envoie seulement un extrait des champs textuels pour limiter le bruit.
    choices: List[str] = []
    for it in items[:60]:
        for v in item_text_fields(it):
            if v and v not in choices:
                choices.append(v)
        if len(choices) >= 60:
            break

    prompt = f"intent: {intent}\n\nVISIBLE_TEXTS:\n" + "\n".join(f"- {c}" for c in choices)
    try:
        resp = await safe_chat(ac, model=MODEL, temperature=0, messages=[
            {"role": "system", "content": TARGET_HINT_PROMPT},
            {"role": "user", "content": prompt},
        ])
        out = (resp.choices[0].message.content or "").strip()
        out = re.sub(r"^```[a-z]*\n?", "", out).rstrip("`").strip()
        # garde court
        return out[:60]
    except Exception:
        return ""


# =============================================================================
# ACTIONS (stable)
# =============================================================================

async def click_stable(ctx: DriverContext, target_text: str) -> Tuple[bool, str]:
    """
    Click deterministe:
      1) generate_locators match target -> best locator
      2) find_element -> click
      3) verify by re-observe handled outside
    """
    if not target_text:
        return False, "empty target_text"

    # 1) via generate_locators
    best = best_locator_for_target(ctx.last_locators_items, target_text)
    if best:
        using, value, it = best
        ok_find, out_find = await appium_find(ctx.mcp, using, value)
        el = _extract_uuid(out_find)
        trace_jsonl(ctx.session_dir, {
            "ts": _now(),
            "event": "find_for_click",
            "device": ctx.device_id,
            "target_text": target_text,
            "using": using, "value": value,
            "ok_find": ok_find,
            "found_uuid": el or "",
            "out_find": trunc(out_find),
        })
        if ok_find and el:
            ok_click, out_click = await appium_click(ctx.mcp, el)
            ctx.step_counter += 1
            ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"click_{target_text}")
            trace_jsonl(ctx.session_dir, {
                "ts": _now(),
                "event": "click",
                "device": ctx.device_id,
                "strategy": "generate_locators",
                "target_text": target_text,
                "elementUUID": el,
                "ok": ok_click,
                "output": trunc(out_click),
                "screenshot": ss,
            })
            return ok_click, out_click

    # 2) fallback selectors (moins stable)
    fallbacks = [
        ("accessibility id", target_text),
        ("xpath", f'//*[@text={json.dumps(target_text)}]'),
        ("xpath", f'//*[@content-desc={json.dumps(target_text)}]'),
        ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
        ("xpath", f'//*[contains(@content-desc,{json.dumps(target_text)})]'),
    ]
    for using, value in fallbacks:
        ok_find, out_find = await appium_find(ctx.mcp, using, value)
        el = _extract_uuid(out_find)
        if ok_find and el:
            ok_click, out_click = await appium_click(ctx.mcp, el)
            ctx.step_counter += 1
            ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"click_{target_text}")
            trace_jsonl(ctx.session_dir, {
                "ts": _now(),
                "event": "click",
                "device": ctx.device_id,
                "strategy": using,
                "target_text": target_text,
                "elementUUID": el,
                "ok": ok_click,
                "output": trunc(out_click),
                "screenshot": ss,
            })
            return ok_click, out_click

    return False, "not found"


async def type_stable(ctx: DriverContext, text: str) -> Tuple[bool, str]:
    # find focused
    ok_find, out_find = await appium_find(ctx.mcp, "xpath", "//*[@focused='true']")
    el = _extract_uuid(out_find)
    if not ok_find or not el:
        return False, "no focused field"
    ok_set, out_set = await appium_set_value(ctx.mcp, el, text)
    ctx.step_counter += 1
    ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"type_{text}")
    trace_jsonl(ctx.session_dir, {
        "ts": _now(),
        "event": "type",
        "device": ctx.device_id,
        "elementUUID": el,
        "ok": ok_set,
        "text": text[:80],
        "output": trunc(out_set),
        "screenshot": ss,
    })
    return ok_set, out_set


async def scroll_to_stable(ctx: DriverContext, target_text: str) -> Tuple[bool, str]:
    # try xpath contains text first, then accessibility id
    ok, out = await ctx.mcp.call("appium_scroll_to_element", {
        "strategy": "xpath",
        "selector": f'//*[contains(@text,{json.dumps(target_text)})]',
    })
    if not ok:
        ok, out = await ctx.mcp.call("appium_scroll_to_element", {
            "strategy": "accessibility id",
            "selector": target_text,
        })
    ctx.step_counter += 1
    ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"scroll_to_{target_text}")
    trace_jsonl(ctx.session_dir, {
        "ts": _now(),
        "event": "scroll_to_element",
        "device": ctx.device_id,
        "target_text": target_text,
        "ok": ok,
        "output": trunc(out),
        "screenshot": ss,
    })
    return ok, out


async def swipe_stable(ctx: DriverContext, direction: str) -> Tuple[bool, str]:
    d = (direction or "down").strip().lower()
    ok, out = await ctx.mcp.call("appium_scroll", {"direction": d})
    if not ok:
        ok, out = await ctx.mcp.call("appium_swipe", {"direction": d})
    ctx.step_counter += 1
    ss = await save_screenshot(ctx.mcp, ctx.session_dir, ctx.step_counter, f"swipe_{d}")
    trace_jsonl(ctx.session_dir, {
        "ts": _now(),
        "event": "swipe",
        "device": ctx.device_id,
        "direction": d,
        "ok": ok,
        "output": trunc(out),
        "screenshot": ss,
    })
    return ok, out


# =============================================================================
# DETERMINISTIC EXECUTOR
# =============================================================================

async def execute_plan_deterministic(ac: AsyncOpenAI, ctx: DriverContext, plan: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Exécution déterministe:
      - observe
      - pour chaque step:
         observe -> drain_alerts
         choisir target_text depuis intent
         action (launch/click/type/scroll) via règles
         observe -> drain_alerts
         verify expected
    """
    await observe(ctx, "init")
    await drain_alerts(ctx)

    # Always launch app at start (stable)
    ok_launch, out_launch = await ctx.mcp.call("appium_activate_app", {"packageName": ctx.app_package})
    trace_jsonl(ctx.session_dir, {"ts": _now(), "event": "launch_app", "device": ctx.device_id, "ok": ok_launch, "output": trunc(out_launch)})
    await asyncio.sleep(ACTION_DELAY_S)
    await observe(ctx, "post_launch")
    await drain_alerts(ctx)

    for i, step in enumerate(plan, start=1):
        intent = (step.get("intent") or "").strip()
        expected = (step.get("expected") or "").strip()

        trace_jsonl(ctx.session_dir, {"ts": _now(), "event": "step_start", "device": ctx.device_id, "i": i, "intent": intent, "expected": expected})

        # Always fresh observe before step
        await observe(ctx, f"pre_step_{i}")
        await drain_alerts(ctx)

        # Decide action type deterministically from intent
        intent_low = intent.lower()

        # If intent clearly says type/write/enter
        is_type = any(k in intent_low for k in ["taper", "saisir", "enter", "type", "write"])
        is_scroll = any(k in intent_low for k in ["scroll", "scroller", "descendre", "monter", "swipe"])
        is_click = any(k in intent_low for k in ["click", "cliquer", "tap", "appuyer", "ouvrir", "open", "select", "choisir", "aller"])

        # Extract text to type if any: after ":" or quotes
        text_to_type = ""
        if is_type:
            m = re.search(r":\s*(.+)$", intent)
            if m:
                text_to_type = m.group(1).strip()
            if not text_to_type:
                m2 = re.search(r"[\"'“”‘’]([^\"'“”‘’]{1,80})[\"'“”‘’]", intent)
                if m2:
                    text_to_type = m2.group(1).strip()

        # Target to click/scroll
        target_text = ""
        if is_click or is_scroll:
            target_text = await infer_target_text(ac, intent, ctx.last_locators_items)
            if not target_text:
                # fallback heuristic on intent
                target_text = quick_guess_target(intent)

        # Execute action with retries + scrolling fallback
        action_ok = True
        action_note = ""

        if is_type and text_to_type:
            # type stable
            ok, out = await type_stable(ctx, text_to_type)
            action_ok = ok
            action_note = f"type:{text_to_type[:40]}"

        elif is_scroll and target_text:
            # scroll to element (stable)
            ok, out = await scroll_to_stable(ctx, target_text)
            action_ok = ok
            action_note = f"scroll_to:{target_text}"

        elif is_click and target_text:
            # click with retries + scroll fallback
            ok = False
            last_out = ""
            for a in range(ACTION_RETRIES):
                ok, last_out = await click_stable(ctx, target_text)
                if ok:
                    break
                # try scroll_to_element then observe
                for st in range(SCROLL_TRIES):
                    await scroll_to_stable(ctx, target_text)
                    await asyncio.sleep(ACTION_DELAY_S)
                    await observe(ctx, f"post_scroll_try_{i}_{st+1}")
                    ok, last_out = await click_stable(ctx, target_text)
                    if ok:
                        break
                if ok:
                    break
                # final swipe fallback
                for sw in range(SWIPE_TRIES):
                    await swipe_stable(ctx, "down")
                    await asyncio.sleep(ACTION_DELAY_S)
                    await observe(ctx, f"post_swipe_try_{i}_{sw+1}")
                    ok, last_out = await click_stable(ctx, target_text)
                    if ok:
                        break
                if ok:
                    break

            action_ok = ok
            action_note = f"click:{target_text} out={trunc(last_out)[:120]}"

        else:
            # Nothing actionable -> just verify
            action_ok = True
            action_note = "no_action_detected"

        await asyncio.sleep(ACTION_DELAY_S)
        await observe(ctx, f"post_action_{i}")
        await drain_alerts(ctx)

        # Verify expected deterministically with retries
        verified = True
        if expected:
            verified = False
            for vr in range(VERIFY_RETRIES):
                if verify_expected_in_source(ctx.last_page_source, expected):
                    verified = True
                    break
                # try a light swipe down/up to refresh view then observe
                await swipe_stable(ctx, "down")
                await asyncio.sleep(ACTION_DELAY_S)
                await observe(ctx, f"verify_retry_{i}_{vr+1}")

        trace_jsonl(ctx.session_dir, {
            "ts": _now(),
            "event": "step_end",
            "device": ctx.device_id,
            "i": i,
            "intent": intent,
            "target_text": target_text,
            "action_ok": action_ok,
            "action_note": action_note,
            "expected": expected,
            "verified": verified,
        })

        if not action_ok or not verified:
            return {
                "status": "blocked",
                "notes": f"Step {i} failed: action_ok={action_ok} verified={verified} intent='{intent}' target='{target_text}' expected='{expected}'",
            }

    return {"status": "success", "notes": "All steps executed and verified (deterministic)."}  # ok


# =============================================================================
# Jira Summary
# =============================================================================

_JIRA_SYS = f"""Tu es QA Automation. Ticket cible: {TICKET_KEY}.
Résume au format strict :
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

    if not USE_TWO_DEVICES:
        devices = devices[:1]

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

        print("\n(2) App info (LLM optionnel, fallback env)...")
        try:
            llm_app = await extract_app_info(summary, ac)
        except Exception as e:
            print(f"[WARN] LLM extract_app_info non dispo ({e}).")
            llm_app = {"appPackage": "", "appActivity": "", "appName": "Application", "platform": "android"}

        resolved = [resolve_app_info(llm_app, i + 1) for i in range(len(devices))]
        for i, r in enumerate(resolved):
            print(f"  driver{i+1}: {r['appPackage']} / {r['appActivity']}  [{r['appName']}]")

        print("\n(3) Plan (LLM optionnel, fallback)...")
        try:
            plan = await generate_plan(summary, ac)
        except Exception as e:
            print(f"[WARN] LLM generate_plan non dispo ({e}). Plan fallback.")
            plan = [{"step": "1", "intent": "Lancer l'app", "expected": ""}]

        plan_txt = "\n".join([f"- {p.get('step')}: {p.get('intent')} (expected: {p.get('expected')})" for p in plan])
        print(plan_txt)

        # run dir
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = SCREENSHOTS_DIR / f"{_safe_slug(TICKET_KEY)}_{run_ts}"
        run_dir.mkdir(parents=True, exist_ok=True)

        print("\n(4) Sessions Appium MCP + exécution déterministe...")
        results: List[Dict[str, Any]] = []

        # On ouvre une session stdio par device (simple, stable)
        for idx, dev in enumerate(devices):
            rinfo = resolved[idx]
            session_dir = run_dir / _safe_slug(dev.replace(":", "_"))
            session_dir.mkdir(parents=True, exist_ok=True)

            async with MCPStdio(session_dir) as mcp:
                # select platform
                await mcp.call("select_platform", {"platform": "android"}, attempts=2)

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

                ok_sess, out_sess = await mcp.call("create_session", {
                    "platform": "android",
                    "remoteServerUrl": APPIUM_SERVER_URL,
                    "capabilities": caps,
                }, attempts=2)

                print(f"  [{dev}] create_session: {'OK' if ok_sess else 'FAIL'} — {trunc(out_sess)[:160]}")
                trace_jsonl(session_dir, {"ts": _now(), "event": "create_session", "device": dev, "ok": ok_sess, "output": trunc(out_sess)})

                if not ok_sess:
                    results.append({"device": dev, "status": "blocked", "notes": f"create_session failed: {trunc(out_sess)[:160]}"})
                    continue

                ctx = DriverContext(
                    name=f"driver{idx+1}",
                    device_id=dev,
                    app_package=rinfo["appPackage"],
                    app_activity=rinfo["appActivity"],
                    app_name=rinfo["appName"],
                    mcp=mcp,
                    session_dir=session_dir,
                )

                # sauvegarde plan
                try:
                    (session_dir / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
                    (session_dir / "summary.txt").write_text(summary, encoding="utf-8")
                except Exception:
                    pass

                # execute
                res = await execute_plan_deterministic(ac, ctx, plan)
                res["device"] = dev
                results.append(res)

                await mcp.call("delete_session", {})

        print("\n" + "=" * 60)
        print("BILAN")
        print("=" * 60)
        overall_ok = True
        for r in results:
            icon = "✅" if r.get("status") == "success" else "❌"
            print(f"  [{r.get('device')}] {icon} {r.get('status')} — {str(r.get('notes',''))[:140]}")
            if r.get("status") != "success":
                overall_ok = False
        print("RÉSULTAT :", "✅ PASS" if overall_ok else "❌ FAIL")
        print(f"📁 Artifacts: {run_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())