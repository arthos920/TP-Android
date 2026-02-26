"""
script_jira_appium_v2.py — Runner Jira + Appium MCP générique

Nouveautés vs v1 :
  1. extract_app_info()  : LLM extrait package/activity depuis le résumé Jira
  2. tool_observe_rich() : observe = screenshot + page_source + generate_locators
  3. tool_handle_alert() : gère les popups/permissions système
  4. Tools ReAct enrichis : handle_alert, generate_locators exposés au LLM
  => Fonctionne avec n'importe quelle app et n'importe quel résumé Jira.
"""
from __future__ import annotations

import asyncio, base64, json, os, re, time, pathlib
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

JIRA_MCP_URL  = os.getenv("JIRA_MCP_URL",  "http://localhost:9000/mcp")
TICKET_KEY    = os.getenv("TICKET_KEY",    "XXXX-0001")

# Chemins résolus depuis l'env (définis dans le Dockerfile ou docker_load_and_run.bat).
# Les valeurs ci-dessous sont les chemins DANS LE CONTAINER (/app/...).
# Sur machine Windows directe (hors Docker), surcharger via variable d'env.
ANDROID_HOME   = os.getenv("ANDROID_HOME",   "/opt/android-sdk").strip()
APPIUM_MCP_DIR = os.getenv("APPIUM_MCP_DIR", "/app/appium-mcp").strip()
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723").strip()
SCREENSHOTS_DIR   = pathlib.Path(
                       os.getenv("SCREENSHOTS_DIR", "/app/screenshots"))
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

LLM_API_KEY  = os.getenv("LLM_API_KEY",  "no-key")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
MODEL        = os.getenv("LLM_MODEL",    "gpt-4o-mini")
PROXY_URL    = os.getenv("PROXY_URL",    "")

DEVICE_1_ID     = os.getenv("DEVICE_1_ID",     "emulator-5554").strip()
DEVICE_2_ID     = os.getenv("DEVICE_2_ID",     "emulator-5556").strip()

# App cible — SOURCE UNIQUE : docker_load_and_run.bat
# Priorité : DRIVER{n}_PACKAGE > GLOBAL_PACKAGE > LLM (Jira)
# Ne pas hardcoder ici — tout passe par les variables d'environnement.
GLOBAL_PACKAGE  = os.getenv("GLOBAL_PACKAGE",  "").strip()
DRIVER1_PACKAGE = os.getenv("DRIVER1_PACKAGE", "").strip()
DRIVER2_PACKAGE = os.getenv("DRIVER2_PACKAGE", "").strip()
APP_ACTIVITY    = os.getenv("APP_ACTIVITY",    "").strip()

MAX_TOOL_CHARS       = int(os.getenv("MAX_TOOL_CHARS",       "12000"))
MAX_TOOL_LINES       = int(os.getenv("MAX_TOOL_LINES",       "300"))
MAX_TURNS_PER_DRIVER = int(os.getenv("MAX_TURNS_PER_DRIVER", "30"))
TOOL_TIMEOUT_S       = float(os.getenv("TOOL_TIMEOUT_S",     "60"))
TOOL_ATTEMPTS        = int(os.getenv("TOOL_ATTEMPTS",        "3"))

# =============================================================================
# UTILS
# =============================================================================

def _strip_ctrl(s: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)

def trunc(text: str) -> str:
    text = _strip_ctrl(str(text))
    lines = text.splitlines()
    if len(lines) > MAX_TOOL_LINES:
        text = "\n".join(lines[:MAX_TOOL_LINES]) + "\n...[TRUNCATED]..."
    return text[:MAX_TOOL_CHARS]

def mcp_to_text(r: Any) -> str:
    c = getattr(r, "content", r)
    if isinstance(c, list):
        return trunc("\n".join(
            (getattr(i, "text", None) or str(i)) for i in c))
    return trunc(str(c) if not isinstance(c, str) else c)

async def safe_chat(ac: AsyncOpenAI, **kw):
    for i in range(3):
        try:
            return await ac.chat.completions.create(**kw)
        except Exception as e:
            await asyncio.sleep(0.5 * (i + 1))
            last = e
    raise last  # type: ignore

# =============================================================================
# TRANSPORT STDIO (Appium MCP)
# =============================================================================

def _stdio_params(screenshots_dir: pathlib.Path) -> StdioServerParameters:
    pt  = os.path.join(ANDROID_HOME, "platform-tools")
    tls = os.path.join(ANDROID_HOME, "tools")
    pth = os.environ.get("PATH", "")
    for p in [pt, tls]:
        if p not in pth:
            pth = p + os.pathsep + pth
    return StdioServerParameters(
        command="node",
        args=[os.path.join(APPIUM_MCP_DIR, "dist", "index.js"), "--transport=stdio"],
        cwd=APPIUM_MCP_DIR,
        env={**os.environ,
             "ANDROID_HOME": ANDROID_HOME, "ANDROID_SDK_ROOT": ANDROID_HOME,
             "PATH": pth, "NO_UI": "1",
             "SCREENSHOTS_DIR": str(screenshots_dir),
             # FIX 1 : supprime les logs appium-mcp sur stdout
             # qui corrompaient le flux JSON-RPC
             "LOG_LEVEL": "error",
             "APPIUM_LOG_LEVEL": "error",
             "APPIUM_MCP_LOG_LEVEL": "error",
             "DEBUG": "",
             },
    )

class MCPStdio:
    def __init__(self, screenshots_dir: pathlib.Path = SCREENSHOTS_DIR):
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

    async def raw(self, tool: str, args: Dict[str, Any]) -> str:
        resp = await asyncio.wait_for(
            self.session.call_tool(tool, args),  # type: ignore
            timeout=TOOL_TIMEOUT_S)
        return mcp_to_text(resp)

    async def call(self, tool: str, args: Dict[str, Any],
                   attempts: int = TOOL_ATTEMPTS) -> Tuple[bool, str]:
        for i in range(1, attempts + 1):
            try:
                out = await self.raw(tool, args)
                if "invalid arguments" in out.lower():
                    return False, out
                return True, out
            except Exception as e:
                if i >= attempts:
                    return False, f"[ERR] {tool}: {e}"
                await asyncio.sleep(0.6 * i)
        return False, "unreachable"

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
        r, w = (t[0], t[1]) if isinstance(t, (tuple, list)) else \
               (t.read_stream, t.write_stream)
        self.session = await self._stack.enter_async_context(ClientSession(r, w))
        await self.session.initialize()
        return self

    async def __aexit__(self, *a):
        await self._stack.aclose()

    async def list_tools(self):
        return (await self.session.list_tools()).tools  # type: ignore

    async def call_tool(self, name: str, args: Dict[str, Any]):
        return await self.session.call_tool(name, args)  # type: ignore

# =============================================================================
# BRIQUE 1 — EXTRACTION DYNAMIQUE : LLM lit le résumé Jira → app info
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
"""

async def extract_app_info(summary: str, ac: AsyncOpenAI) -> Dict[str, str]:
    """
    Utilise le LLM pour extraire package/activity depuis le résumé Jira.
    Si non trouvé → retourne des chaînes vides (l'env var GLOBAL_PACKAGE prendra le relais).
    """
    resp = await safe_chat(ac, model=MODEL, temperature=0,
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user",   "content": summary},
        ])
    raw = (resp.choices[0].message.content or "").strip()
    # Nettoie éventuels blocs ```json
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        data = json.loads(raw)
        return {
            "appPackage":  str(data.get("appPackage",  "")),
            "appActivity": str(data.get("appActivity", "")),
            "appName":     str(data.get("appName",     "Application")),
            "platform":    str(data.get("platform",    "android")),
        }
    except Exception:
        return {"appPackage": "", "appActivity": "", "appName": "Application", "platform": "android"}

# =============================================================================
# BRIQUE 1b — OVERRIDE PAR ENV (GLOBAL/DRIVER/APP_PACKAGE)
# =============================================================================

def resolve_app_info(llm_info: Dict[str, str], driver_index: int = 1) -> Dict[str, str]:
    """
    Applique l'override d'app cible selon priorité décroissante :
      1. DRIVER{n}_PACKAGE (spécifique au driver)  ← dans docker_load_and_run.bat
      2. GLOBAL_PACKAGE    (commun aux 2 drivers)  ← dans docker_load_and_run.bat
      3. LLM               (extrait du résumé Jira)
    APP_ACTIVITY (docker_load_and_run.bat) remplace l'activity si un package env est défini.
    Lève une erreur claire si aucune source ne fournit de package.
    """
    info = dict(llm_info)

    per_driver = DRIVER1_PACKAGE if driver_index == 1 else DRIVER2_PACKAGE
    pkg = per_driver or GLOBAL_PACKAGE or info["appPackage"]
    act = info["appActivity"]

    if per_driver or GLOBAL_PACKAGE:
        act = APP_ACTIVITY or act

    if not pkg:
        raise SystemExit(
            "[ERREUR] Aucun package défini.\n"
            "  → Renseigne GLOBAL_PACKAGE dans docker_load_and_run.bat\n"
            "    (ou DRIVER1_PACKAGE / DRIVER2_PACKAGE pour des apps différentes par device)."
        )

    info["appPackage"]  = pkg
    info["appActivity"] = act
    if pkg != llm_info["appPackage"]:
        info["appName"] = pkg.split(".")[-1].capitalize()
    return info

# =============================================================================
# BRIQUE 2a — PLANNER : LLM génère un plan structuré avant la boucle ReAct
# =============================================================================

_PLANNER_PROMPT = """Tu es un agent QA mobile expert.
À partir du résumé Jira ci-dessous, génère un plan de test COURT et ACTIONNABLE en JSON strict :
{
  "plan": [
    {"step": 1, "intent": "Lancer l'app", "expected": "Écran principal visible"},
    {"step": 2, "intent": "Cliquer sur Notifications", "expected": "Page Notifications ouverte"},
    ...
  ]
}
Règles :
- 3 à 8 étapes max.
- intent = action humaine simple.
- expected = élément ou texte attendu visible après l'action.
- Réponds UNIQUEMENT avec le JSON.
"""

async def generate_plan(summary: str, ac: AsyncOpenAI) -> List[Dict[str, str]]:
    """Génère un plan de test structuré depuis le résumé Jira."""
    resp = await safe_chat(ac, model=MODEL, temperature=0.1,
        messages=[
            {"role": "system", "content": _PLANNER_PROMPT},
            {"role": "user",   "content": summary},
        ])
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        data = json.loads(raw)
        return data.get("plan", [])
    except Exception:
        return [{"step": 1, "intent": "Ouvrir l'app et vérifier l'écran principal",
                 "expected": "Écran principal visible"}]

# =============================================================================
# BRIQUE 2b — LOCATOR TRACE : journal de tous les locators/actions par run
# =============================================================================

def _append_trace(session_dir: pathlib.Path, entry: Dict[str, Any]) -> None:
    """Ajoute une entrée dans locators_trace.json (crée si absent)."""
    try:
        trace_file = session_dir / "locators_trace.json"
        rows: List[Dict] = []
        if trace_file.exists():
            try:
                rows = json.loads(trace_file.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        rows.append(entry)
        trace_file.write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    except Exception:
        pass

# =============================================================================
# SCREENSHOT HELPER
# =============================================================================

def _safe_slug(s: str, maxlen: int = 30) -> str:
    """Transforme une chaîne en slug safe pour un nom de fichier."""
    return re.sub(r"[^\w\-]", "_", s)[:maxlen]

async def _save_screenshot(ctx: "DriverContext", label: str) -> Optional[pathlib.Path]:
    """
    Prend un screenshot via Appium MCP (FIX 2 : outputDir passé explicitement).
    Sauvegarde dans session_dir avec nom step_NNN_<label>.png.
    """
    try:
        async with ctx.lock:
            # FIX 2 : passer outputDir pour que appium-mcp sache où sauvegarder
            await ctx.mcp.call("appium_screenshot",
                               {"outputDir": str(ctx.session_dir)})
        # Trouver le fichier le plus récent dans session_dir
        files = sorted(ctx.session_dir.glob("*.png"), key=lambda f: f.stat().st_mtime)
        if not files:
            return None
        latest = files[-1]
        slug  = _safe_slug(label)
        ctx.step += 1
        dest  = ctx.session_dir / f"step_{ctx.step:03d}_{slug}.png"
        if latest.name != dest.name:
            try:
                latest.rename(dest)
            except Exception:
                pass
        return dest
    except Exception:
        return None

# =============================================================================
# DATACLASS DRIVER CONTEXT
# =============================================================================

@dataclass
class DriverContext:
    name:         str
    device_id:    str
    app_package:  str
    app_activity: str
    app_name:     str
    mcp:          MCPStdio
    lock:         asyncio.Lock
    session_dir:  pathlib.Path = field(default_factory=lambda: SCREENSHOTS_DIR)
    step:         int          = field(default=0)
    # FIX 6 : stocke les locators du dernier observe pour click rapide
    last_locators: str         = field(default="")

# =============================================================================
# BRIQUE 2 — OBSERVE RICHE : screenshot + page_source + generate_locators
# =============================================================================

async def tool_observe_rich(ctx: DriverContext) -> str:
    """
    Observation complète de l'UI :
      - appium_get_page_source → arbre XML complet
      - generate_locators      → locators intelligents pour tous les éléments interactifs
      - _save_screenshot       → screenshot (FIX 3 : un seul appel, via _save_screenshot)
    Trace les locators dans locators_trace.json pour aide à la décision.
    """
    # FIX 3 : page_source + locators sous lock (pas de screenshot ici)
    async with ctx.lock:
        _, src  = await ctx.mcp.call("appium_get_page_source", {})
        _, locs = await ctx.mcp.call("generate_locators", {})
    # FIX 6 : stocker les locators pour tool_ui_click
    ctx.last_locators = locs
    # FIX 3 : screenshot via _save_screenshot UNIQUEMENT (évite le doublon)
    snap = await _save_screenshot(ctx, "observe")
    # Tracer les locators disponibles
    _append_trace(ctx.session_dir, {
        "ts": datetime.now().isoformat(), "step": ctx.step,
        "action": "observe", "device": ctx.device_id,
        "locators_raw": locs[:2000],
    })
    # FIX 5 : debug — afficher locators bruts reçus
    print(f"  [DEBUG observe] [{ctx.device_id}] locators({len(locs)}ch): "
          f"{locs[:300]}...")
    return json.dumps({
        "driver": ctx.name, "device": ctx.device_id,
        "page_source": src[:4000],
        "screenshot_saved": str(snap) if snap else "",
        "locators": locs[:3000],
    }, ensure_ascii=False)

# =============================================================================
# BRIQUE 3 — HANDLE ALERT : popup / permission system
# =============================================================================

async def tool_handle_alert(ctx: DriverContext, action: str = "accept") -> str:
    """
    Accepte ou refuse une alerte/popup système (permission, dialog, etc.).
    action = 'accept' | 'dismiss'
    """
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_handle_alert", {"action": action})
        return json.dumps({"ok": ok, "action": action, "output": out[:400]},
                          ensure_ascii=False)

# =============================================================================
# AUTRES WRAPPERS APPIUM
# =============================================================================

def _el_id(text: str) -> Optional[str]:
    """Extrait un UUID d'élément depuis une réponse appium-mcp."""
    m = re.search(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
                  text, re.I)
    return m.group(1) if m else None

# =============================================================================
# FIX 6 — CLICK VIA LOCATORS generate_locators
# =============================================================================

def _find_el_in_locators(locators_raw: str, target_text: str) -> Optional[str]:
    """
    FIX 6 : Cherche target_text dans la réponse JSON de generate_locators.
    Retourne l'elementId si trouvé (match exact ou partiel sur text/contentDesc/resourceId).
    """
    if not locators_raw or not locators_raw.strip().startswith("["):
        return None
    try:
        items = json.loads(locators_raw)
        tl = target_text.lower().strip()
        # Passe 1 : match exact
        for item in items:
            for field_name in ("text", "contentDesc", "content-desc", "label"):
                v = str(item.get(field_name, "") or "").strip()
                if v.lower() == tl and item.get("elementId"):
                    return str(item["elementId"])
        # Passe 2 : match partiel
        for item in items:
            for field_name in ("text", "contentDesc", "content-desc", "label"):
                v = str(item.get(field_name, "") or "").strip()
                if tl in v.lower() and item.get("elementId"):
                    return str(item["elementId"])
        # Passe 3 : resourceId (last segment)
        for item in items:
            rid = str(item.get("resourceId", "") or "")
            if tl in rid.lower() and item.get("elementId"):
                return str(item["elementId"])
    except Exception:
        pass
    return None

async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    FIX 6 : Clique un élément.
    Stratégie 1 (rapide) : cherche dans ctx.last_locators (generate_locators).
    Stratégie 2 (fallback) : appium_find_element avec XPath/accessibility id.
    """
    # --- Stratégie 1 : locators du dernier observe ---
    el_from_loc = _find_el_in_locators(ctx.last_locators, target_text)
    if el_from_loc:
        async with ctx.lock:
            ok2, out2 = await ctx.mcp.call("appium_click", {"elementId": el_from_loc})
        return json.dumps({"ok": ok2, "strategy": "locators_cache",
                           "element_id": el_from_loc, "click_output": out2[:300]},
                          ensure_ascii=False)

    # --- Stratégie 2 : find_element XPath/accessibility ---
    async with ctx.lock:
        locators = [
            ("accessibility id", target_text),
            ("xpath", f'//*[@text={json.dumps(target_text)}]'),
            ("xpath", f'//*[@content-desc={json.dumps(target_text)}]'),
            ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
            ("xpath", f'//*[contains(@content-desc,{json.dumps(target_text)})]'),
        ]
        for strat, sel in locators:
            ok, out = await ctx.mcp.call("appium_find_element",
                                         {"strategy": strat, "selector": sel})
            if not ok:
                continue
            el = _el_id(out)
            if not el:
                continue
            ok2, out2 = await ctx.mcp.call("appium_click", {"elementId": el})
            return json.dumps({"ok": ok2, "strategy": strat, "element_id": el,
                                "click_output": out2[:300]}, ensure_ascii=False)
    return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"},
                      ensure_ascii=False)

async def tool_ui_type(ctx: DriverContext, text: str) -> str:
    """Tape dans le champ focalisé (cliquer d'abord si besoin)."""
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_find_element",
            {"strategy": "xpath", "selector": "//*[@focused='true']"})
        if not ok:
            return json.dumps({"ok": False,
                "error": "No focused field. Call ui_click on an input first."},
                ensure_ascii=False)
        el = _el_id(out)
        if not el:
            return json.dumps({"ok": False, "error": "focused element id not found"},
                               ensure_ascii=False)
        ok2, out2 = await ctx.mcp.call("appium_set_value",
                                        {"elementId": el, "text": text})
        return json.dumps({"ok": ok2, "element_id": el, "output": out2[:300]},
                          ensure_ascii=False)

async def tool_ui_swipe(ctx: DriverContext, direction: str = "down") -> str:
    """Scroll/swipe dans une direction."""
    async with ctx.lock:
        d = direction.strip().lower()
        ok, out = await ctx.mcp.call("appium_scroll", {"direction": d})
        if not ok:
            ok, out = await ctx.mcp.call("appium_swipe", {"direction": d})
        return json.dumps({"ok": ok, "direction": d, "output": out[:300]},
                          ensure_ascii=False)

async def tool_launch_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    """Lance/ramène au premier plan l'application."""
    async with ctx.lock:
        p = (pkg or ctx.app_package).strip()
        ok, out = await ctx.mcp.call("appium_activate_app", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_activate_app", {"packageName": p})
        return json.dumps({"ok": ok, "package": p, "output": out[:300]},
                          ensure_ascii=False)

async def tool_terminate_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    """Ferme de force l'application."""
    async with ctx.lock:
        p = (pkg or ctx.app_package).strip()
        ok, out = await ctx.mcp.call("appium_terminateApp", {"bundleId": p})
        if not ok:
            ok, out = await ctx.mcp.call("appium_terminateApp", {"packageName": p})
        return json.dumps({"ok": ok, "package": p, "output": out[:300]},
                          ensure_ascii=False)

async def tool_get_text(ctx: DriverContext, target_text: str) -> str:
    """Lit le texte d'un élément par son texte/label visible."""
    async with ctx.lock:
        locators = [
            ("accessibility id", target_text),
            ("xpath", f'//*[@text={json.dumps(target_text)}]'),
            ("xpath", f'//*[contains(@text,{json.dumps(target_text)})]'),
        ]
        for strat, sel in locators:
            ok, out = await ctx.mcp.call("appium_find_element",
                                          {"strategy": strat, "selector": sel})
            if not ok:
                continue
            el = _el_id(out)
            if not el:
                continue
            ok2, txt = await ctx.mcp.call("appium_get_text", {"elementId": el})
            return json.dumps({"ok": ok2, "element": target_text, "text": txt[:500]},
                              ensure_ascii=False)
        return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"})

async def tool_scroll_to_element(ctx: DriverContext, target_text: str) -> str:
    """Scrolle jusqu'à ce qu'un élément avec ce texte soit visible."""
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_scroll_to_element",
            {"strategy": "xpath",
             "selector": f'//*[contains(@text,{json.dumps(target_text)})]'})
        if not ok:
            ok, out = await ctx.mcp.call("appium_scroll_to_element",
                {"strategy": "accessibility id", "selector": target_text})
        return json.dumps({"ok": ok, "target": target_text, "output": out[:300]},
                          ensure_ascii=False)

async def tool_double_tap(ctx: DriverContext, target_text: str) -> str:
    """Double-tap sur un élément par son texte visible."""
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_find_element",
            {"strategy": "xpath", "selector": f'//*[contains(@text,{json.dumps(target_text)})]'})
        if not ok:
            return json.dumps({"ok": False, "error": f"Element '{target_text}' not found"})
        el = _el_id(out)
        if not el:
            return json.dumps({"ok": False, "error": "element id not found"})
        ok2, out2 = await ctx.mcp.call("appium_double_tap", {"elementId": el})
        return json.dumps({"ok": ok2, "element": target_text, "output": out2[:300]},
                          ensure_ascii=False)

# =============================================================================
# BARRIER (synchronisation 2 drivers)
# =============================================================================

class Barrier:
    def __init__(self):
        self._cond = asyncio.Condition()
        self._n = 0; self._gen = 0

    async def wait(self, who: str) -> str:
        async with self._cond:
            g = self._gen; self._n += 1
            if self._n >= 2:
                self._n = 0; self._gen += 1
                self._cond.notify_all()
                return f"[BARRIER] released gen={self._gen} (last={who})"
            while g == self._gen:
                await self._cond.wait()
            return f"[BARRIER] released gen={self._gen} (waiter={who})"

# =============================================================================
# OPENAI TOOL DEFINITIONS — ReAct enrichi
# =============================================================================

def _t(name, desc, props, req=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": req or []}}}

def build_tools() -> List[Dict[str, Any]]:
    return [
        _t("observe",        "Observe UI complète: locators + page_source + screenshot. À appeler après chaque action.", {}, []),
        _t("handle_alert",   "Accepte/refuse popup ou permission système",
           {"action": {"type": "string", "enum": ["accept", "dismiss"]}}, []),
        _t("launch_app",     "Lance ou ramène l'app au premier plan",
           {"packageName": {"type": "string"}}, []),
        _t("terminate_app",  "Ferme l'app",
           {"packageName": {"type": "string"}}, []),
        _t("ui_click",       "Clique un élément par son texte visible ou accessibility id",
           {"target_text": {"type": "string"}}, ["target_text"]),
        _t("ui_type",        "Tape dans le champ focalisé (cliquer le champ d'abord si besoin)",
           {"text": {"type": "string"}}, ["text"]),
        _t("ui_swipe",       "Scroll/swipe dans une direction",
           {"direction": {"type": "string", "enum": ["up","down","left","right"]}}, []),
        _t("scroll_to_element", "Scrolle jusqu'à rendre visible un élément par son texte",
           {"target_text": {"type": "string"}}, ["target_text"]),
        _t("get_text",       "Lit la valeur textuelle d'un élément visible sur l'écran",
           {"target_text": {"type": "string"}}, ["target_text"]),
        _t("double_tap",     "Double-tap sur un élément par son texte visible",
           {"target_text": {"type": "string"}}, ["target_text"]),
        _t("sync_barrier",   "Synchronise les deux drivers avant de continuer", {}, []),
        _t("finish",         "Termine le test avec un statut et des notes",
           {"status": {"type": "string", "enum": ["success","failure","blocked"]},
            "notes":  {"type": "string"}}, ["status"]),
    ]

# =============================================================================
# REACT LOOP
# =============================================================================

SYSTEM_REACT = """Tu es un agent QA mobile autonome (ReAct : Observe → Raisonne → Agis).
Tu exécutes un PLAN DE TEST structuré fourni au départ. Tu pilotes une app Android via
Appium MCP en utilisant UNIQUEMENT les tools fournis.

Processus strict :
1. Commence TOUJOURS par "observe" pour voir l'UI et les locators réels.
2. Suit le plan étape par étape. Après chaque action, appelle "observe" pour vérifier que
   l'état attendu ("expected") est atteint.
3. Si l'état attendu n'est pas visible après 2 tentatives, essaie scroll_to_element ou
   ui_swipe puis observe de nouveau. Si toujours bloqué → finish(status="blocked").
4. N'agis QUE sur des éléments vus dans les locators de la dernière observation.
5. Si une popup/permission apparaît → handle_alert("accept") immédiatement.
6. Si un texte doit être lu/vérifié → use get_text.
7. Quand toutes les étapes sont validées → finish(status="success") avec un résumé.

Tools disponibles : observe, handle_alert, launch_app, terminate_app,
  ui_click, ui_type, ui_swipe, scroll_to_element, get_text, double_tap,
  sync_barrier, finish.
"""

async def run_react(ac: AsyncOpenAI, ctx: DriverContext,
                    barrier: Barrier, summary: str) -> Dict[str, Any]:
    tools = build_tools()

    # ── Validation post-action : vérifie si un texte attendu est présent ──
    async def _verify_expected(expected: str) -> bool:
        """Retourne True si `expected` est détectable dans la page_source."""
        if not expected:
            return True
        try:
            _, src = await ctx.mcp.call("appium_get_page_source", {})
            return expected.lower()[:30] in src.lower()
        except Exception:
            return True  # en cas d'erreur, on ne bloque pas

    # ── Dispatcher des tools ───────────────────────────────────────────────
    async def _dispatch(name: str, args: Dict[str, Any],
                        expected: str = "") -> str:
        if name == "observe":          return await tool_observe_rich(ctx)
        if name == "sync_barrier":     return await barrier.wait(ctx.name)
        if name == "finish":           return json.dumps({"ok": True})
        if name == "get_text":
            tgt = args.get("target_text", "")
            out = await tool_get_text(ctx, tgt)
            _append_trace(ctx.session_dir, {
                "ts": datetime.now().isoformat(), "step": ctx.step,
                "action": "get_text", "target": tgt, "result": out[:200],
                "device": ctx.device_id})
            return out
        if name == "scroll_to_element":
            tgt = args.get("target_text", "")
            out = await tool_scroll_to_element(ctx, tgt)
            await _save_screenshot(ctx, f"scroll_to_{_safe_slug(tgt, 20)}")
            _append_trace(ctx.session_dir, {
                "ts": datetime.now().isoformat(), "step": ctx.step,
                "action": "scroll_to_element", "target": tgt, "device": ctx.device_id})
            return out
        if name == "double_tap":
            tgt = args.get("target_text", "")
            out = await tool_double_tap(ctx, tgt)
            await _save_screenshot(ctx, f"doubletap_{_safe_slug(tgt, 20)}")
            _append_trace(ctx.session_dir, {
                "ts": datetime.now().isoformat(), "step": ctx.step,
                "action": "double_tap", "target": tgt, "device": ctx.device_id})
            return out
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
            result = json.loads(out) if out.startswith("{") else {}
            ok_click = result.get("ok", False)
            # Trace avec résultat click
            _append_trace(ctx.session_dir, {
                "ts": datetime.now().isoformat(), "step": ctx.step,
                "action": "ui_click", "target": tgt,
                "ok": ok_click, "expected": expected, "device": ctx.device_id})
            # Validation post-action (retry simple)
            if ok_click and expected and not await _verify_expected(expected):
                out += f' [WARN: expected "{expected[:40]}" not yet visible]'
            return out
        if name == "ui_type":
            txt = args.get("text", "")
            out = await tool_ui_type(ctx, txt)
            await _save_screenshot(ctx, f"type_{_safe_slug(txt, 20)}")
            _append_trace(ctx.session_dir, {
                "ts": datetime.now().isoformat(), "step": ctx.step,
                "action": "ui_type", "text": txt[:80], "device": ctx.device_id})
            return out
        if name == "ui_swipe":
            d = args.get("direction", "down")
            out = await tool_ui_swipe(ctx, d)
            await _save_screenshot(ctx, f"swipe_{d}")
            return out
        return json.dumps({"ok": False, "error": f"Unknown tool {name}"})

    # ── Génération du plan de test ─────────────────────────────────────────
    plan = await generate_plan(summary, ac)
    plan_txt = "\n".join(
        f"  Étape {s.get('step','?')}: {s.get('intent','?')} → attendu: {s.get('expected','?')}"
        for s in plan)
    print(f"  📋 Plan ({len(plan)} étapes) :\n{plan_txt}")
    # Sauvegarder le plan dans le dossier de run
    try:
        (ctx.session_dir / "plan.json").write_text(
            json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_REACT},
        {"role": "user", "content": (
            f"Résumé Jira:\n{summary}\n\n"
            f"Driver: {ctx.name} | Device: {ctx.device_id} | "
            f"App: {ctx.app_name} ({ctx.app_package})\n\n"
            f"PLAN DE TEST À SUIVRE :\n{plan_txt}\n\n"
            "Commence par observer l'UI, puis exécute chaque étape du plan en ordre.")},
    ]

    final: Dict[str, Any] = {"status": "blocked", "notes": "no finish called",
                              "driver": ctx.name, "device": ctx.device_id}

    # Contexte de suivi du plan pour fournir l'expected courant au dispatcher
    current_expected = ""
    for turn in range(1, MAX_TURNS_PER_DRIVER + 1):
        resp = await safe_chat(ac, model=MODEL, messages=msgs, tools=tools,
                               tool_choice="auto", temperature=0.2, max_tokens=1400)
        msg = resp.choices[0].message
        msgs.append({"role": "assistant", "content": msg.content or ""})

        calls = getattr(msg, "tool_calls", None)
        if not calls:
            msgs.append({"role": "user",
                         "content": "Appelle un tool du plan ou finish si terminé."})
            continue

        for tc in calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}

            # FIX 5 : debug — afficher chaque tool call du LLM
            print(f"  [TURN {turn:02d}] [{ctx.device_id}] LLM→ "
                  f"{tc.function.name}({json.dumps(args, ensure_ascii=False)[:120]})")

            if tc.function.name == "finish":
                final = {
                    "status":  args.get("status", "blocked"),
                    "notes":   args.get("notes", ""),
                    "turn":    turn,
                    "driver":  ctx.name,
                    "device":  ctx.device_id,
                    "plan":    plan,
                }
                msgs.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps({"ok": True})})
                # Enregistrer le bilan dans trace
                _append_trace(ctx.session_dir, {
                    "ts": datetime.now().isoformat(), "step": ctx.step,
                    "action": "finish", "status": final["status"],
                    "notes": final["notes"][:200], "device": ctx.device_id})
                return final

            out = await _dispatch(tc.function.name, args, current_expected)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})

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
"""

async def jira_fetch_and_summarize(ac: AsyncOpenAI) -> str:
    async with MCPHttp(JIRA_MCP_URL) as jira:
        tools = await jira.list_tools()
        oa_tools = [{"type": "function", "function": {
            "name": t.name,
            "description": getattr(t, "description", "") or "",
            "parameters": getattr(t, "inputSchema", None) or {"type":"object","properties":{}},
        }} for t in tools]

        msgs: List[Dict[str, Any]] = [
            {"role": "system", "content": _JIRA_SYS},
            {"role": "user",   "content": f"Récupère le ticket {TICKET_KEY}."},
        ]
        for _ in range(12):
            r = await safe_chat(ac, model=MODEL, messages=msgs, tools=oa_tools,
                                tool_choice="auto", temperature=0.2, max_tokens=4000)
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
                msgs.append({"role": "tool", "tool_call_id": tc.id,
                             "content": mcp_to_text(res)})

        msgs.append({"role": "user", "content": "Résumé final au format demandé."})
        fin = await safe_chat(ac, model=MODEL, messages=msgs,
                              temperature=0.2, max_tokens=1800)
        return fin.choices[0].message.content or ""

# =============================================================================
# MAIN
# =============================================================================

def _make_http() -> httpx.AsyncClient:
    kw: Dict[str, Any] = dict(verify=False, follow_redirects=False, timeout=120.0)
    if PROXY_URL:
        try:    return httpx.AsyncClient(proxy=PROXY_URL, **kw)
        except: return httpx.AsyncClient(proxies=PROXY_URL, **kw)  # type: ignore
    return httpx.AsyncClient(**kw)

async def main():
    devices = [d for d in [DEVICE_1_ID, DEVICE_2_ID] if d]
    if not devices:
        raise SystemExit("Définis DEVICE_1_ID (et optionnellement DEVICE_2_ID).")

    async with _make_http() as http:
        ac = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, http_client=http)

        # ── 1. Jira fetch (ou résumé inline si JIRA_MCP_URL non dispo) ──────
        print("\n" + "="*60)
        print("(1) JIRA — fetch + résumé")
        print("="*60)
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

        # ── 2. LLM extrait package/activity depuis le résumé ────────────────
        print("\n(2) Extraction app info depuis le résumé...")
        app_info = await extract_app_info(summary, ac)
        print(f"    → {app_info}")

        # ── 3. Créer sessions Appium + lancer ReAct en parallèle ────────────
        print("\n(3) Ouverture sessions Appium MCP (stdio)...")
        # Résoudre l'app cible par driver (env > LLM)
        resolved = [resolve_app_info(app_info, i + 1) for i in range(len(devices))]
        print("    App cible par driver :")
        for i, r in enumerate(resolved):
            print(f"      driver{i+1}: {r['appPackage']} / {r['appActivity']}  [{r['appName']}]")

        # ── Structure de dossiers screenshots ────────────────────────────────
        # screenshots/<TICKET>_<AppName>_<YYYYMMDD_HHMMSS>/<device_serial>/
        run_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        app_slug = _safe_slug(resolved[0]["appName"], 20)
        run_dir  = SCREENSHOTS_DIR / f"{_safe_slug(TICKET_KEY)}_{app_slug}_{run_ts}"
        session_dirs = []
        for dev in devices:
            sd = run_dir / _safe_slug(dev.replace(":", "_"), 30)
            sd.mkdir(parents=True, exist_ok=True)
            session_dirs.append(sd)
        print(f"    📁 Screenshots → {run_dir}")

        barrier = Barrier()

        async with (MCPStdio(session_dirs[0]) as mcp1,
                    MCPStdio(session_dirs[1] if len(devices) > 1 else session_dirs[0]) as mcp2):
            # create_session pour chaque device avec son app résolue
            pairs = [(mcp1, devices[0], resolved[0]),
                     (mcp2, devices[1], resolved[1]) if len(devices) > 1
                     else (mcp1, devices[0], resolved[0])]
            for mcp, dev, rinfo in pairs:
                caps = {
                    "platformName":                  "Android",
                    "appium:automationName":         "UiAutomator2",
                    "appium:udid":                   dev,
                    "appium:appPackage":             rinfo["appPackage"],
                    "appium:appActivity":            rinfo["appActivity"],
                    "appium:autoGrantPermissions":   True,
                    "appium:newCommandTimeout":      300,
                    # FIX 4 : ne PAS effacer le cache/données de l'app entre runs
                    "appium:noReset":                True,
                    "appium:fullReset":              False,
                }
                await mcp.call("select_platform", {"platform": "android"})
                ok, out = await mcp.call("create_session", {
                    "platform": "android",
                    "remoteServerUrl": APPIUM_SERVER_URL,
                    "capabilities": caps,
                }, attempts=2)
                print(f"    [{dev}] create_session ({rinfo['appPackage']}): "
                      f"{'OK' if ok else 'FAIL'} — {out[:100]}")

            ctxs = [
                DriverContext(f"driver{i+1}", dev,
                              resolved[i]["appPackage"], resolved[i]["appActivity"],
                              resolved[i]["appName"],
                              [mcp1, mcp2][i] if len(devices) > 1 else mcp1,
                              asyncio.Lock(),
                              session_dirs[i])
                for i, dev in enumerate(devices)
            ]

            try:
                print("\n(4) ReAct en parallèle...")
                tasks = [run_react(ac, ctx, barrier, summary) for ctx in ctxs]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                for mcp in ([mcp1, mcp2] if len(devices) > 1 else [mcp1]):
                    await mcp.call("delete_session", {})

    # ── Bilan ────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("BILAN")
    print("="*60)
    overall_ok = True
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  driver{i+1}: ❌ EXCEPTION — {r}")
            overall_ok = False
        else:
            icon = "✅" if r.get("status") == "success" else "❌"  # type: ignore
            print(f"  driver{i+1} [{r.get('device')}]: {icon} {r.get('status','?').upper()} — {r.get('notes','')[:100]}")  # type: ignore
            if r.get("status") != "success":  # type: ignore
                overall_ok = False
    print("RÉSULTAT :", "✅ PASS" if overall_ok else "❌ FAIL")

if __name__ == "__main__":
    asyncio.run(main())
