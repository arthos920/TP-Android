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
import base64
import hashlib
import json
import os
import random
import re
import sys
import pathlib
import subprocess
import threading
import time
from collections import deque
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
# VISION (validation visuelle d'expected via LLM multimodal)
# =============================================================================

VISION_ENABLED = os.getenv("VISION_ENABLED", "0").strip() in ("1", "true", "True", "yes", "YES")
VISION_MODEL   = os.getenv("VISION_MODEL", "qwen2.5vl:7b").strip()
# Ollama compatible : "qwen2.5vl:7b", "qwen2.5vl:3b", "llava:7b", "llava:13b",
# "moondream:v2" (très petit, rapide), "llama3.2-vision:11b", "gemma3:12b", "gemma3:27b" (avec vision).
# Le serveur LLM_BASE_URL sert aussi pour la vision (Ollama supporte plusieurs modèles).

# =============================================================================
# RATE LIMITING + CACHE LLM (pour APIs avec quota par minute, type DAISE 30/min)
# =============================================================================

# Limite préventive : on évite de cogner le quota. Marge de sécurité : 28/30.
LLM_RATE_LIMIT_MAX      = int(os.getenv("LLM_RATE_LIMIT_MAX", "28"))
LLM_RATE_LIMIT_PERIOD_S = float(os.getenv("LLM_RATE_LIMIT_PERIOD_S", "60.0"))
# Délai d'attente après un 429 effectif (selon doc DAISE : 2 minutes).
LLM_RATE_LIMIT_PENALTY_S = float(os.getenv("LLM_RATE_LIMIT_PENALTY_S", "120.0"))

# Cache idempotent pour les fonctions LLM dont l'output ne dépend que de l'input
# (extract_app_info, classify_jira_test_type, generate_plan).
LLM_CACHE_DIR = pathlib.Path(os.getenv(
    "LLM_CACHE_DIR", str(pathlib.Path(__file__).parent / "knowledge_base" / "llm_cache")))
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "1").strip() in ("1", "true", "True", "yes")


class AsyncRateLimiter:
    """Sliding window : max N appels par period_s secondes. Bloque (async) si plein."""
    def __init__(self, max_calls: int = 28, period_s: float = 60.0):
        self.max_calls = max_calls
        self.period_s = period_s
        self._calls: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Purge des appels hors fenêtre
            while self._calls and self._calls[0] <= now - self.period_s:
                self._calls.popleft()
            # Si plein, attendre jusqu'à libération du plus vieux
            if len(self._calls) >= self.max_calls:
                wait_s = self.period_s - (now - self._calls[0]) + 0.1
                if DEBUG_TOOLS:
                    print(f"  [RATE_LIMIT] {len(self._calls)}/{self.max_calls} in window, "
                          f"sleeping {wait_s:.1f}s")
                await asyncio.sleep(max(0.0, wait_s))
                now = time.monotonic()
                while self._calls and self._calls[0] <= now - self.period_s:
                    self._calls.popleft()
            self._calls.append(now)


# Instance globale partagée par toutes les coroutines (drivers parallèles inclus)
LLM_RATE_LIMITER = AsyncRateLimiter(LLM_RATE_LIMIT_MAX, LLM_RATE_LIMIT_PERIOD_S)


def _cache_key(scope: str, *parts: Any) -> str:
    """Hash stable d'une combinaison de strings → 16 chars hex pour nom de fichier."""
    h = hashlib.sha256()
    h.update(scope.encode("utf-8"))
    for p in parts:
        h.update(b"\x00")
        h.update(str(p).encode("utf-8"))
    return h.hexdigest()[:16]


async def cached_call(scope: str, key_parts: List[Any], coro_factory) -> Any:
    """
    Cache idempotent : si la clé existe, retourne le résultat caché.
    Sinon appelle coro_factory() (qui doit retourner une coroutine), sauve le résultat,
    le retourne.
    """
    if not LLM_CACHE_ENABLED:
        return await coro_factory()
    key = _cache_key(scope, *key_parts)
    cache_file = LLM_CACHE_DIR / scope / f"{key}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if DEBUG_TOOLS:
                print(f"  [CACHE HIT] {scope}/{key}")
            return data
        except Exception:
            pass  # cache corrompu : on régénère
    result = await coro_factory()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        if DEBUG_TOOLS:
            print(f"  [CACHE MISS+SAVED] {scope}/{key}")
    except Exception as e:
        if DEBUG_TOOLS:
            print(f"  [CACHE] save failed: {e}")
    return result

# =============================================================================
# KNOWLEDGE BASE (apprentissage cross-runs)
# =============================================================================

KB_DIR = pathlib.Path(os.getenv(
    "KB_DIR", str(pathlib.Path(__file__).parent / "knowledge_base")))
KB_FEWSHOT_K = int(os.getenv("KB_FEWSHOT_K", "2"))  # nombre d'exemples à injecter

# Liste fermée des catégories de test. Surchargeable via env JIRA_TEST_TYPES.
KB_TEST_TYPES_DEFAULT = (
    "semi-duplex call (ptt call)", "video_call", "conference_call",
    "group_call", "incoming_call", "outgoing_call",
    "browser_search", "browser_navigation", "settings_change",
    "form_submission", "media_playback",
    "unknown",
)
KB_TEST_TYPES = tuple(
    t.strip() for t in os.getenv("JIRA_TEST_TYPES",
                                  ",".join(KB_TEST_TYPES_DEFAULT)).split(",")
    if t.strip()
)


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


def _stable_hash(s: str) -> str:
    """Hash court et stable pour détecter qu'un écran n'a pas changé entre 2 observes."""
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()[:16]


async def safe_chat(ac: AsyncOpenAI, **kw):
    """
    Wrap chat.completions.create avec :
      - Rate limiter préventif (sliding window) pour éviter les 429
      - Retry avec backoff sur erreurs transitoires
      - Pénalité spécifique de 120s sur 429 effectif (selon doc DAISE)
    """
    last: Optional[Exception] = None
    for i in range(5):  # 5 tentatives max pour absorber 1-2 pénalités 429
        await LLM_RATE_LIMITER.acquire()
        try:
            return await ac.chat.completions.create(**kw)
        except Exception as e:
            last = e
            msg = str(e).lower()
            is_rate_limit = (
                "429" in msg or "rate limit" in msg or "rate_limit" in msg
                or "too many requests" in msg
            )
            if is_rate_limit:
                wait = LLM_RATE_LIMIT_PENALTY_S + random.uniform(0, 5)
                if DEBUG_TOOLS:
                    print(f"  [RATE_LIMIT] 429 hit (attempt {i+1}/5), "
                          f"sleeping {wait:.1f}s")
                await asyncio.sleep(wait)
            else:
                # Erreur transitoire : backoff exponentiel court + jitter
                wait = (2 ** i) * 0.5 + random.uniform(0, 0.5)
                await asyncio.sleep(wait)
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

# Force UTF-8 partout : sinon Python sous Windows lit les pipes en cp1252
# et crash dès qu'appium-mcp loggue un caractère non-ASCII.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
        encoding="utf-8",
        errors="replace",
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

def _python_exe() -> str:
    # sys.executable = Python courant. Portable Windows/Linux/Docker
    # (évite "python" hardcodé qui n'existe pas toujours sous Linux).
    if sys.executable and pathlib.Path(sys.executable).exists():
        return sys.executable
    return "python"


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
    async def _do() -> Dict[str, str]:
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
    return await cached_call("extract_app_info", [MODEL, summary], _do)


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
    async def _do() -> List[Dict[str, str]]:
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
    return await cached_call("generate_plan", [MODEL, summary], _do)


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
    # appium_screenshot ne prend aucun paramètre : il écrit dans SCREENSHOTS_DIR
    # (env passée à chaque subprocess via _stdio_params → ctx.session_dir).
    try:
        async with ctx.lock:
            await ctx.mcp.call("appium_screenshot", {})

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
    last_clicked_was_editable: bool = False  # True si dernier ui_click sur EditText/TextField
    last_locators_hash: str = ""              # hash de la dernière observation
    last_screen_was_static: bool = False      # True si dernier observe == observe précédent


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


def _build_compact_view(locators_raw: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Construit une vue compacte des éléments interactifs/affichés pour le LLM.
    Évite d'envoyer 7000 chars de XML + JSON brut à chaque observe.
    Garde max `limit` items avec text/desc/rid/clickable/editable.
    """
    items = parse_generate_locators_payload(locators_raw)
    compact: List[Dict[str, Any]] = []
    for it in items:
        if not it.get("displayed", True):
            continue
        text = str(it.get("text") or "").strip()
        desc = str(it.get("contentDesc") or it.get("content-desc") or "").strip()
        rid_full = str(it.get("resourceId") or "")
        rid = rid_full.split("/")[-1] if "/" in rid_full else rid_full
        # Filtre les containers vides (rien de cliquable comme libellé)
        if not (text or desc or rid):
            continue
        entry: Dict[str, Any] = {
            "i": len(compact) + 1,
            "clickable": bool(it.get("clickable", False)),
            "editable": _is_editable_tag(it.get("tagName")),
        }
        if text:
            entry["text"] = text[:80]
        if desc and desc.lower() != text.lower():
            entry["desc"] = desc[:80]
        if rid and rid.lower() != text.lower() and rid.lower() != desc.lower():
            entry["rid"] = rid[:30]
        compact.append(entry)
        if len(compact) >= limit:
            break
    return compact


# Patterns de tagName indiquant un champ de saisie (Android + iOS).
# Génériques : couvre EditText, TextField, SearchView, etc.
EDITABLE_TAG_PATTERNS = (
    "edittext",                       # android.widget.EditText
    "autocompletetextview",           # AutoCompleteTextView
    "searchview",                     # SearchView Android
    "xcuielementtypetextfield",       # iOS UITextField
    "xcuielementtypesecuretextfield", # iOS password field
    "xcuielementtypesearchfield",     # iOS search field
)


def _is_editable_tag(tag: Optional[str]) -> bool:
    """True si le tagName correspond à un champ de saisie texte."""
    t = (tag or "").lower()
    return any(p in t for p in EDITABLE_TAG_PATTERNS)


def _expected_visible(expected: str, locators_raw: str) -> bool:
    """
    Heuristique : True si le `expected` du plan est visible dans la dernière observation.
    Priorité :
      1. Strings entre quotes dans `expected` (ex: "toto", "Search bar")
      2. Texte complet du `expected` (tronqué à 60 chars)
      3. Premier fragment avant un séparateur (`.`, ` ou `, `,`, `:`, `(`)
    Tous les matches sont case-insensitive et sur `locators_raw` brut.
    """
    if not expected or not locators_raw:
        return False
    haystack = locators_raw.lower()

    # (1) Strings entre quotes — le plus distinctif
    for quoted in re.findall(r"['\"]([^'\"]+)['\"]", expected):
        if len(quoted) >= 3 and quoted.lower() in haystack:
            return True

    # (2) Texte complet (tronqué)
    short = expected.strip().lower()[:60]
    if len(short) >= 8 and short in haystack:
        return True

    # (3) Fragment avant le 1er séparateur
    exp_low = expected.lower()
    for sep in (".", " ou ", " or ", ",", ":", "("):
        if sep in exp_low:
            part = exp_low.split(sep)[0].strip()
            if len(part) >= 8 and part in haystack:
                return True
            break

    return False


_VISION_PROMPT = """Tu es un expert QA mobile.
Voici un screenshot d'écran Android pris JUSTE APRÈS une action UI.
L'état attendu sur cet écran est : "{expected}"

Réponds UNIQUEMENT en JSON strict, sans markdown :
{{"match": <true|false>, "confidence": <0.0 à 1.0>, "reason": "<courte explication, max 80 chars>"}}

Règles :
- match=true SEULEMENT si tu vois clairement l'état décrit dans le screenshot
- En cas de doute, match=false avec confidence<=0.5
- reason : ce que tu vois (ou ne vois pas) qui justifie ta réponse
"""


async def visual_check(screenshot_path: pathlib.Path, expected: str,
                       ac: AsyncOpenAI) -> Dict[str, Any]:
    """
    Demande à un LLM vision si le screenshot montre l'état attendu.
    Retourne {match: bool, confidence: float, reason: str}.
    Si VISION_ENABLED=0 ou erreur, retourne match=False sans bloquer.
    """
    if not VISION_ENABLED or not expected or not screenshot_path:
        return {"match": False, "confidence": 0.0, "reason": "vision disabled or no input"}
    try:
        if not screenshot_path.exists():
            return {"match": False, "confidence": 0.0, "reason": "screenshot file not found"}
        png_bytes = screenshot_path.read_bytes()
        b64 = base64.b64encode(png_bytes).decode("ascii")
        resp = await safe_chat(
            ac, model=VISION_MODEL, temperature=0.0, max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT.format(expected=expected[:150])},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        )
        content = (resp.choices[0].message.content or "").strip()
        content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
        data = json.loads(content)
        return {
            "match": bool(data.get("match", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "reason": str(data.get("reason", ""))[:120],
        }
    except Exception as e:
        return {"match": False, "confidence": 0.0, "reason": f"vision check failed: {e}"[:120]}


def find_item_for_target(items: List[Dict[str, Any]], target_text: str) -> Optional[Dict[str, Any]]:
    """
    Retourne l'item complet (dict, avec tagName/locators/...) qui correspond à target_text.
    Réutilise la logique de match exact puis partiel de find_best_locator.
    """
    tl = (target_text or "").lower().strip()
    if not tl:
        return None

    def fields(it: Dict[str, Any]) -> List[str]:
        out = []
        for k in ("text", "contentDesc", "content-desc", "label", "name", "resourceId"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        return out

    # Passe 1 : match exact
    for it in items:
        vals = [v.lower() for v in fields(it)]
        if any(v == tl for v in vals):
            return it
    # Passe 2 : match partiel
    for it in items:
        vals = [v.lower() for v in fields(it)]
        if any(tl in v for v in vals):
            return it
    return None


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
    # Le full locators_raw est gardé en ctx pour find_best_locator + substring match.
    ctx.last_locators_raw = locs

    # Détection de changement d'écran (signale au LLM si une action a eu un effet).
    new_hash = _stable_hash(locs)
    had_prev = bool(ctx.last_locators_hash)
    screen_changed = (not had_prev) or (new_hash != ctx.last_locators_hash)
    ctx.last_screen_was_static = had_prev and (new_hash == ctx.last_locators_hash)
    ctx.last_locators_hash = new_hash

    snap = await _save_screenshot(ctx, "observe")

    # Vue compacte pour le LLM (~1500 chars vs 7000 avant) : éléments visibles
    # avec text/desc/rid/clickable/editable. Le full raw reste accessible via ctx.
    elements = _build_compact_view(locs, limit=25)

    _append_trace(
        ctx.session_dir,
        {
            "ts": datetime.now().isoformat(),
            "step": ctx.step,
            "action": "observe",
            "device": ctx.device_id,
            "ok_page_source": ok_src,
            "ok_locators": ok_locs,
            "screen_changed": screen_changed,
            "elements_count": len(elements),
            "locators_raw": trunc(locs),  # trace garde le full pour debug
        },
    )

    return json.dumps(
        {
            "driver": ctx.name,
            "device": ctx.device_id,
            "screenshot_saved": str(snap) if snap else "",
            "screen_changed": screen_changed,
            "elements": elements,
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
        ok, out = await ctx.mcp.call("appium_activate_app", {"id": p})
    await _save_screenshot(ctx, "launch_app")
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_terminate_app(ctx: DriverContext, pkg: Optional[str] = None) -> str:
    p = (pkg or ctx.app_package).strip()
    async with ctx.lock:
        ok, out = await ctx.mcp.call("appium_terminate_app", {"id": p})
    await _save_screenshot(ctx, "terminate_app")
    return json.dumps({"ok": ok, "package": p, "output": (out or "")[:300]}, ensure_ascii=False)


async def tool_ui_click(ctx: DriverContext, target_text: str) -> str:
    """
    Clique via:
      1) generate_locators -> pick best locator -> find_element -> click
      2) fallback heuristiques xpath/accessibility id
    Met à jour ctx.last_clicked_was_editable selon le tagName de l'item cliqué
    (utilisé par le guard ReAct pour forcer ui_type après click sur un input).
    """
    items = parse_generate_locators_payload(ctx.last_locators_raw)
    matched_item = find_item_for_target(items, target_text)
    uv = find_best_locator(items, target_text)

    # Reset par défaut, on positionnera True si on confirme un click sur input
    ctx.last_clicked_was_editable = False

    if uv:
        using, value = uv
        ok_find, out_find = await appium_find_element(ctx, using, value)
        el = _extract_element_uuid(out_find)
        if ok_find and el:
            ok_click, out_click = await appium_click_uuid(ctx, el)
            await _save_screenshot(ctx, f"click_{_safe_slug(target_text, 20)}")
            if ok_click and matched_item:
                ctx.last_clicked_was_editable = _is_editable_tag(matched_item.get("tagName"))
            return json.dumps(
                {"ok": ok_click, "strategy": "generate_locators", "using": using, "value": value,
                 "elementUUID": el, "editable": ctx.last_clicked_was_editable,
                 "tagName": (matched_item or {}).get("tagName", ""),
                 "output": (out_click or "")[:300]},
                ensure_ascii=False,
            )

    # fallback heuristics — pas d'item info disponible, on garde editable=False
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
                {"ok": ok_click, "strategy": using, "selector": value, "elementUUID": el,
                 "output": (out_click or "")[:300]},
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


async def tool_ui_type(ctx: DriverContext, text: str, submit: bool = False) -> str:
    """
    Tape `text` dans le champ focused.
    Si `submit=True` : envoie aussi "\\n" qui déclenche l'action IME Android
    (équivalent Enter/Search/Go/Done selon le champ). Utilisé pour lancer une
    recherche, soumettre un formulaire, valider une saisie.
    """
    # focused field
    ok_find, out_find = await appium_find_element(ctx, "xpath", "//*[@focused='true']")
    el = _extract_element_uuid(out_find)
    if not ok_find or not el:
        return json.dumps({"ok": False,
                           "error": "No focused field. Use ui_click on input first."},
                          ensure_ascii=False)

    text_to_send = text + ("\n" if submit else "")
    ok_set, out_set = await appium_set_value_uuid(ctx, el, text_to_send)
    label_suffix = "_submit" if submit else ""
    await _save_screenshot(ctx, f"type_{_safe_slug(text, 20)}{label_suffix}")
    return json.dumps({"ok": ok_set, "elementUUID": el, "submitted": submit,
                       "output": (out_set or "")[:300]},
                      ensure_ascii=False)


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
        _t("ui_type",
           "Tape `text` dans le champ focus (barre URL, formulaire). "
           "Si tu veux VALIDER la saisie (lancer la recherche, soumettre le "
           "formulaire, déclencher l'action du clavier), passe submit=true : "
           "ça équivaut à appuyer sur Enter/Search/Go/Done sur Android.",
           {"text":   {"type": "string"},
            "submit": {"type": "boolean",
                       "description": "true pour valider après la saisie (Enter)"}},
           ["text"]),
        _t("ui_swipe", "Swipe/scroll", {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}}, []),
        _t("scroll_to_element", "Scroll jusqu'à voir l'élément", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("get_text", "Lit le texte d'un élément", {"target_text": {"type": "string"}}, ["target_text"]),
        _t("sync_barrier", "Synchronise 2 drivers", {}, []),
        _t("finish", "Termine", {"status": {"type": "string", "enum": ["success", "failure", "blocked"]}, "notes": {"type": "string"}}, ["status"]),
    ]


# =============================================================================
# REACT LOOP
# =============================================================================

# =============================================================================
# CLASSIFICATION DU TICKET JIRA + KNOWLEDGE BASE (Phase 1+2)
# =============================================================================

_CLASSIFY_PROMPT_TMPL = """Tu es un classificateur de tickets Jira de tests mobiles.
À partir du résumé du ticket, détermine le type de test parmi cette liste FERMÉE :
{types_list}

Réponds UNIQUEMENT avec un JSON valide de cette forme :
{{
  "test_type": "<un des types ci-dessus, exactement>",
  "confidence": 0.0,
  "reason": "explication courte"
}}
Ne mets aucun markdown, aucun commentaire. Si rien ne matche, retourne "unknown"."""


async def classify_jira_test_type(ac: AsyncOpenAI, jira_summary: str) -> Dict[str, Any]:
    """Classifie un résumé Jira parmi KB_TEST_TYPES."""
    types_list = "\n".join(f"- {t}" for t in KB_TEST_TYPES)
    types_key = "|".join(KB_TEST_TYPES)  # invalide le cache si la liste change

    async def _do() -> Dict[str, Any]:
        system = _CLASSIFY_PROMPT_TMPL.format(types_list=types_list)
        data: Dict[str, Any] = {"test_type": "unknown", "confidence": 0.0, "reason": ""}
        try:
            resp = await safe_chat(
                ac, model=MODEL, temperature=0.0, max_tokens=300,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Résumé Jira:\n{jira_summary}"},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            content = re.sub(r"^```[a-z]*\n?", "", content).rstrip("`").strip()
            parsed = json.loads(content)
            data = {
                "test_type": str(parsed.get("test_type", "unknown")),
                "confidence": float(parsed.get("confidence", 0.0)),
                "reason": str(parsed.get("reason", "")),
            }
        except Exception as e:
            data["reason"] = f"classify failed: {e}"
        if data["test_type"] not in KB_TEST_TYPES:
            data["test_type"] = "unknown"
        return data

    return await cached_call("classify", [MODEL, types_key, jira_summary], _do)


def _kb_runs_dir(test_type: str) -> pathlib.Path:
    d = KB_DIR / "runs" / _safe_slug(test_type, 40)
    d.mkdir(parents=True, exist_ok=True)
    return d


def kb_save_run(test_type: str, ticket: str, summary: str,
                plan: List[Dict[str, Any]],
                action_trace: List[Dict[str, Any]],
                result: Dict[str, Any]) -> Optional[pathlib.Path]:
    """Persiste un run dans la KB pour réutilisation future."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rd = _kb_runs_dir(test_type) / f"{_safe_slug(ticket, 20)}_{ts}"
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "summary.txt").write_text(summary or "", encoding="utf-8")
        (rd / "plan.json").write_text(
            json.dumps(plan or [], indent=2, ensure_ascii=False), encoding="utf-8")
        (rd / "action_trace.json").write_text(
            json.dumps(action_trace or [], indent=2, ensure_ascii=False), encoding="utf-8")
        (rd / "result.json").write_text(
            json.dumps(result or {}, indent=2, ensure_ascii=False), encoding="utf-8")
        return rd
    except Exception as e:
        if DEBUG_TOOLS:
            print(f"  [KB] save failed: {e}")
        return None


def kb_load_fewshot(test_type: str, k: int = KB_FEWSHOT_K) -> List[Dict[str, Any]]:
    """
    Charge jusqu'à k runs PRÉCÉDEMMENT RÉUSSIS du même test_type.
    Retourne des structures compactes : {ticket, plan, key_actions, notes}.
    """
    if not test_type or test_type == "unknown":
        return []
    type_dir = KB_DIR / "runs" / _safe_slug(test_type, 40)
    if not type_dir.exists():
        return []
    examples: List[Dict[str, Any]] = []
    # Tri par nom décroissant (timestamp dans nom => récents en premier)
    for rd in sorted(type_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not rd.is_dir():
            continue
        try:
            result = json.loads((rd / "result.json").read_text(encoding="utf-8"))
            if result.get("status") != "success":
                continue
            plan = json.loads((rd / "plan.json").read_text(encoding="utf-8"))
            actions = json.loads((rd / "action_trace.json").read_text(encoding="utf-8"))
            # Compactage : ne garder que les UI actions (pas observe/finish)
            key_actions = [
                a for a in actions
                if a.get("tool") and a["tool"] not in ("observe", "finish")
            ][:10]
            examples.append({
                "ticket": rd.name,
                "plan": plan or [],
                "key_actions": key_actions,
                "notes": str(result.get("notes", ""))[:120],
            })
            if len(examples) >= k:
                break
        except Exception:
            continue
    return examples


def kb_format_fewshot_for_prompt(examples: List[Dict[str, Any]],
                                  test_type: str) -> str:
    """Formate les exemples pour injection dans le system prompt (compact)."""
    if not examples:
        return ""
    lines = [f"## Tests similaires précédemment RÉUSSIS (catégorie : {test_type})", ""]
    for i, ex in enumerate(examples, 1):
        lines.append(f"### Exemple {i} — run {ex.get('ticket', '?')}")
        plan = ex.get("plan", [])
        if plan:
            lines.append("Plan suivi :")
            for step in plan[:6]:
                intent = str(step.get("intent", "?"))[:60]
                expected = str(step.get("expected", ""))[:50]
                lines.append(f"  - Étape {step.get('step','?')}: {intent} → attendu: {expected}")
        actions = ex.get("key_actions", [])
        if actions:
            lines.append("Actions clés (séquence qui a marché) :")
            for a in actions[:8]:
                tool = a.get("tool", "?")
                target = str(a.get("target", ""))[:50]
                lines.append(f"  - {tool}({target!r})")
        notes = ex.get("notes", "")
        if notes:
            lines.append(f"Conclusion : {notes}")
        lines.append("")
    lines.append("Ces exemples sont INDICATIFS : adapte-toi au ticket actuel, "
                 "mais inspire-toi des séquences qui ont déjà fonctionné.")
    return "\n".join(lines)


SYSTEM_REACT = """Tu es un agent QA mobile autonome qui pilote une app Android.
RÈGLES IMPÉRATIVES (à respecter sans exception) :

1) Au tour 1 : appelle observe pour voir l'écran initial.

2) INTERDICTION ABSOLUE d'appeler observe deux fois de suite.
   Après un observe, ton tool call SUIVANT doit OBLIGATOIREMENT être l'un de :
   ui_click, ui_type, ui_swipe, scroll_to_element, handle_alert, launch_app,
   terminate_app, get_text, sync_barrier, ou finish.
   Si tu ne sais pas quoi cliquer, choisis le 1er bouton/lien visible dans les locators.

3) Pour cliquer : utilise ui_click avec le texte EXACT visible (champ "text" ou
   "contentDesc" d'un item dans la réponse de observe). Privilégie les éléments
   où clickable=true.

4) Après CHAQUE action (ui_click, ui_type, ui_swipe, scroll_to_element, handle_alert,
   double_tap, launch_app, terminate_app), TU DOIS appeler observe au tour suivant.
   Sans observe, tu ne peux PAS savoir si l'action a eu l'effet attendu : un click
   peut sembler réussir techniquement mais ne pas faire avancer l'app.
   Pattern obligatoire : observe → action → observe → action → ... → finish.

5) Si une alerte/popup apparaît : handle_alert(accept) immédiatement.

6) Termine par finish(status="success") dès que l'objectif du plan est atteint,
   ou finish(status="blocked") si tu es vraiment coincé après plusieurs tentatives.

7) RÈGLE CRITIQUE pour la saisie de texte : si tu viens de cliquer sur une barre d'URL,
   une barre de recherche, ou tout champ de saisie (target_text contenait "Search", "URL",
   "type", "search box", "input", "rechercher"), TON ACTION SUIVANTE doit OBLIGATOIREMENT être
   ui_type(text="<texte du plan>"). Ne PAS cliquer sur autre chose entre temps.
   Ne PAS observe puis re-cliquer un autre élément.

8) FORMAT D'ARGUMENTS : pour ui_click utilise EXACTEMENT {"target_text": "..."}.
   Pour ui_type utilise EXACTEMENT {"text": "..."}.
   Pour observe utilise EXACTEMENT {} (objet vide, AUCUN argument).
   NE PAS inventer des clés comme "action", "locator", "response", "selector".

EXEMPLE de séquence valide (PATTERN GÉNÉRIQUE — adapte les valeurs à TON ticket Jira) :
  Tour 1: observe                                          # voir l'écran initial
  Tour 2: ui_click(target_text="<bouton du plan>")         # ex: Suivant, OK, Continuer, Accepter
  Tour 3: observe                                          # vérifier l'effet du click
  Tour 4: ui_click(target_text="<champ de saisie>")        # ex: barre URL, champ email, numéro
  Tour 5: observe
  Tour 6: ui_type(text="<texte exact du plan>")            # saisie du texte attendu
  Tour 7: observe                                          # voir que le texte est bien saisi
  Tour 8: finish(status="success", notes="objectif atteint")

NE COPIE PAS les libellés de l'exemple — utilise UNIQUEMENT les éléments visibles dans
les `elements` retournés par observe, qui correspondent au plan de TON ticket.
""".strip()


async def run_react(ac: AsyncOpenAI, ctx: DriverContext, barrier: Barrier,
                    summary: str, test_type: str = "unknown") -> Dict[str, Any]:
    tools = build_tools()

    # ── Knowledge Base : charger les few-shots pour ce test_type ──────────────
    kb_examples = kb_load_fewshot(test_type, KB_FEWSHOT_K)
    fewshot_block = kb_format_fewshot_for_prompt(kb_examples, test_type)
    if DEBUG_TOOLS:
        print(f"  [KB] {ctx.device_id}: test_type={test_type!r}, "
              f"few-shot examples loaded={len(kb_examples)}")

    # Accumule toutes les actions du run pour persistance KB en fin de session
    local_action_trace: List[Dict[str, Any]] = []

    def _norm_target(args: Dict[str, Any]) -> str:
        """Normalise les args malformés : qwen peut produire text/locator/element/target au lieu de target_text."""
        for k in ("target_text", "text", "target", "label", "name"):
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # xpath/locator-shaped args : extraire le texte ou contentDesc visé
        for loc_key in ("locator", "selector", "element", "xpath"):
            loc = args.get(loc_key)
            if isinstance(loc, str) and loc.strip():
                m = re.search(r"@(?:content-desc|text)=['\"]([^'\"]+)['\"]", loc)
                if m:
                    return m.group(1)
        return ""

    async def _dispatch(name: str, args: Dict[str, Any]) -> str:
        if name == "observe":
            return await tool_observe_rich(ctx)
        if name == "handle_alert":
            return await tool_handle_alert(ctx, args.get("action", "accept"))
        if name == "launch_app":
            return await tool_launch_app(ctx, args.get("packageName") or args.get("id"))
        if name == "terminate_app":
            return await tool_terminate_app(ctx, args.get("packageName") or args.get("id"))
        if name == "ui_click":
            return await tool_ui_click(ctx, _norm_target(args))
        if name == "ui_type":
            txt = args.get("text") or args.get("target_text") or args.get("value") or ""
            # Tolère submit / press_enter / enter / validate comme alias
            submit = bool(args.get("submit") or args.get("press_enter")
                          or args.get("enter") or args.get("validate"))
            return await tool_ui_type(ctx, str(txt), submit=submit)
        if name == "ui_swipe":
            return await tool_ui_swipe(ctx, args.get("direction", "down"))
        if name == "scroll_to_element":
            return await tool_scroll_to_element(ctx, _norm_target(args))
        if name == "get_text":
            return await tool_get_text(ctx, _norm_target(args))
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

    # Enrichir le system prompt avec les exemples de la KB si disponibles
    enriched_system = SYSTEM_REACT
    if fewshot_block:
        enriched_system = SYSTEM_REACT + "\n\n" + fewshot_block

    msgs: List[Dict[str, Any]] = [
        {"role": "system", "content": enriched_system},
        {"role": "user", "content": (
            f"Résumé Jira:\n{summary}\n\n"
            f"Driver: {ctx.name} | Device: {ctx.device_id} | App: {ctx.app_name} ({ctx.app_package})\n\n"
            f"PLAN:\n{plan_txt}\n\n"
            "Commence par observe."
        )},
    ]

    final: Dict[str, Any] = {"status": "blocked", "notes": "no finish called", "driver": ctx.name, "device": ctx.device_id}

    last_tool_name = ""  # garde-fou pour alterner observe / action
    last_click_target = ""  # pour détecter "click sur barre URL"
    recent_ui_actions: deque = deque(maxlen=3)  # (tool, target) des 3 dernières actions UI (pas observe)
    plan_completed_hint = ""  # auto-finish : texte du expected matché dans le dernier observe
    current_step_index = 0  # step tracking : index de l'étape en cours dans le plan
    ACTION_TOOLS = {"ui_click", "ui_type", "ui_swipe", "scroll_to_element",
                    "double_tap", "handle_alert", "launch_app", "terminate_app", "get_text"}
    URL_BAR_KEYWORDS = ("search or type", "search google", "address bar", "url",
                        "type url", "search box", "rechercher", "taper", "type web")

    # Extraire le texte à saisir depuis le résumé (plusieurs patterns par ordre de fiabilité)
    text_to_type_from_plan = ""
    for pat in (
        r'(?:Données|Donnees|Inputs?|Data)[^=\n]*=\s*["\']([^"\']+)["\']',  # "Données ... = \"X\""
        r'ui_type[^"\']*["\']text["\']?\s*[:=]\s*["\']([^"\']+)["\']',       # ui_type avec text="X"
        r'\b[Tt]ape[r]?\s+(?:exactement\s+)?["\']([^"\']+)["\']',             # "Tape exactement \"X\""
        r'(?:saisir|écris?|input)\s+["\']([^"\']+)["\']',                     # "saisir \"X\""
    ):
        mm = re.search(pat, summary)
        if mm and mm.group(1).strip():
            text_to_type_from_plan = mm.group(1).strip()
            break
    if DEBUG_TOOLS:
        print(f"  [PLAN] {ctx.device_id}: text_to_type extracted = {text_to_type_from_plan!r}")

    def _is_url_bar_target(target: str) -> bool:
        t = (target or "").lower()
        return any(k in t for k in URL_BAR_KEYWORDS)

    for turn in range(1, MAX_TURNS_PER_DRIVER + 1):
        # ── Auto-finish : si la dernière observe a matché le `expected` du dernier step ──
        if plan_completed_hint:
            msgs.append({
                "role": "user",
                "content": (
                    f"✅ OBJECTIF ATTEINT : la dernière observation contient "
                    f"'{plan_completed_hint[:70]}', qui correspond au 'expected' du DERNIER step "
                    "du plan. Tu DOIS appeler MAINTENANT finish(status=\"success\", "
                    "notes=\"objectif atteint\") pour clôturer le test. AUCUNE autre action."
                ),
            })
            plan_completed_hint = ""  # consommé

        # ── Plan refresh : rappel COMPACT du step en cours à chaque tour ──
        # Évite que le LLM dérive vers des menus annexes en perdant de vue le plan.
        if plan and current_step_index < len(plan):
            cs = plan[current_step_index]
            intent = str(cs.get("intent", "?"))[:80]
            expected = str(cs.get("expected", "?"))[:80]
            msgs.append({
                "role": "user",
                "content": (
                    f"📋 PLAN EN COURS — étape {current_step_index + 1}/{len(plan)} : "
                    f"{intent} → attendu après action : {expected}. "
                    "Reste concentré sur cette étape, ne dérive pas vers des menus annexes."
                ),
            })

        # ── Anti-loop & screen-static warnings (génériques, indépendants de l'app) ──
        warnings_msg: List[str] = []

        # (1) Anti-loop : 2 actions UI identiques consécutives ⇒ pivoter
        if len(recent_ui_actions) >= 2:
            a, b = list(recent_ui_actions)[-2:]
            if a == b and a[0] != "finish":
                warnings_msg.append(
                    f"⚠️ BOUCLE DÉTECTÉE : tu as fait {a[0]}('{a[1]}') deux fois de suite "
                    "sans effet utile. Ne refais PAS cette action. "
                    "Choisis (a) un autre target visible dans la dernière observation, "
                    "(b) ui_swipe(direction='down') pour explorer, "
                    "ou (c) finish(status='blocked', notes='loop on this target')."
                )

        # (2) Screen-static : dernier observe identique au précédent ⇒ action sans effet
        if ctx.last_screen_was_static:
            warnings_msg.append(
                "⚠️ ÉCRAN INCHANGÉ : la dernière observation est IDENTIQUE à la précédente. "
                "Ton action UI précédente n'a eu AUCUN effet (élément introuvable, non interactif, "
                "ou popup invisible). Ne répète pas la même action — change de target."
            )
            ctx.last_screen_was_static = False  # consommé

        if warnings_msg:
            msgs.append({"role": "user", "content": "\n".join(warnings_msg)})

        # Garde-fou GÉNÉRIQUE : si le dernier click était sur un champ de saisie
        # (EditText / TextField / SearchView…), forcer ui_type au prochain tour.
        # Fallback : si on n'a pas pu détecter l'item (click via XPath fallback),
        # on regarde les keywords du target ("search/url/...") pour rester safe.
        clicked_input = (
            ctx.last_clicked_was_editable
            or (_is_url_bar_target(last_click_target) and last_click_target != "")
        )
        if (last_tool_name == "observe" and clicked_input and text_to_type_from_plan):
            # Détecte si le plan demande une VALIDATION après la saisie
            # (recherche, soumettre, valider, lancer, send, search...)
            submit_keywords = ("rechercher", "recherche google", "lance la recherche",
                               "valid", "soumets", "submit", "search", "envoie", "send",
                               "appui sur entr", "press enter", "press search", "go")
            lower_summary = (summary or "").lower()
            needs_submit = any(k in lower_summary for k in submit_keywords)
            submit_hint = " et passe submit=true (le plan demande de valider/lancer)" \
                          if needs_submit else ""
            msgs.append({
                "role": "user",
                "content": (
                    f"Tu viens de cliquer un champ de saisie ('{last_click_target}'). "
                    f"TON UNIQUE TOOL CALL POSSIBLE MAINTENANT est : "
                    f'ui_type(text="{text_to_type_from_plan}"{submit_hint}). '
                    "Ne clique pas un autre élément. Ne fais pas finish. Tape ce texte EXACT."
                ),
            })
            # consommé : reset des deux signaux pour ne pas reboucler
            last_click_target = ""
            ctx.last_clicked_was_editable = False
        # Si le tour précédent était observe : interdire un 2e observe → forcer action
        elif last_tool_name == "observe":
            msgs.append({
                "role": "user",
                "content": (
                    "Tu viens d'observer. INTERDIT d'appeler observe à nouveau. "
                    "Choisis MAINTENANT une action concrète parmi : ui_click, ui_type, "
                    "ui_swipe, scroll_to_element, handle_alert, launch_app, terminate_app, "
                    "get_text, finish. Pour ui_click, prends un texte visible dans la "
                    "dernière observation (champ text ou contentDesc d'un élément clickable)."
                ),
            })
        # Si le tour précédent était une action UI : forcer observe pour voir l'effet
        elif last_tool_name in ACTION_TOOLS:
            msgs.append({
                "role": "user",
                "content": (
                    f"Tu viens de faire l'action '{last_tool_name}'. Appelle observe MAINTENANT "
                    "pour voir le nouvel écran et vérifier si l'action a réussi. "
                    "(L'écran a peut-être changé. Ne fais PAS une autre action sans observer d'abord.)"
                ),
            })

        resp = await safe_chat(
            ac, model=MODEL, messages=msgs, tools=tools, tool_choice="auto",
            temperature=0.2, max_tokens=1200
        )
        msg = resp.choices[0].message
        msgs.append({"role": "assistant", "content": msg.content or ""})

        if DEBUG_TOOLS and msg.content:
            print(f"  [TURN {turn:02d}] [{ctx.device_id}] LLM say: {trunc(msg.content)[:200]}")

        calls = getattr(msg, "tool_calls", None)
        if not calls:
            msgs.append({"role": "user", "content": "Appelle un tool (ui_click/finish/...) maintenant."})
            last_tool_name = ""
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
                local_action_trace.append({"turn": turn, "tool": "finish",
                                           "status": final["status"],
                                           "notes": final["notes"][:200]})
                # Persist run to KB
                kb_path = kb_save_run(test_type, TICKET_KEY, summary, plan,
                                      local_action_trace, final)
                if DEBUG_TOOLS and kb_path:
                    print(f"  [KB] {ctx.device_id}: run saved → {kb_path}")
                return final

            out = await _dispatch(tc.function.name, args)
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            last_tool_name = tc.function.name
            target_key = (args.get("target_text") or args.get("text")
                          or args.get("target") or args.get("direction") or "")
            if tc.function.name == "ui_click":
                # _norm_target gère les args malformés ; on récupère la cible effective
                last_click_target = (args.get("target_text") or args.get("text")
                                     or args.get("target") or "") or ""
            # Tracker les actions UI pour la détection de boucle (exclure observe/finish)
            if tc.function.name not in ("observe", "finish"):
                recent_ui_actions.append((tc.function.name, str(target_key)))
            # KB action trace : on capture toutes les actions (incluant observes)
            local_action_trace.append({
                "turn": turn, "tool": tc.function.name,
                "target": str(target_key), "args": {k: v for k, v in args.items()
                                                    if k != "screenshot"},
            })
            # Step tracking : si l'expected du STEP COURANT est visible, on avance
            if tc.function.name == "observe" and plan:
                # Récupérer le dernier screenshot pour la validation visuelle (si activée)
                last_screenshot: Optional[pathlib.Path] = None
                if VISION_ENABLED:
                    snaps = sorted(ctx.session_dir.glob("step_*_observe.png"),
                                   key=lambda p: p.stat().st_mtime)
                    if snaps:
                        last_screenshot = snaps[-1]

                # Validation séquentielle : avancer tant que les expecteds successifs matchent.
                # Match accepté si : (a) substring dans locators OU (b) LLM vision confirme.
                while current_step_index < len(plan):
                    cur_exp = (plan[current_step_index].get("expected") or "").strip()
                    if not cur_exp:
                        break
                    substring_ok = _expected_visible(cur_exp, ctx.last_locators_raw)
                    vision_ok = False
                    vision_info: Dict[str, Any] = {}
                    if not substring_ok and VISION_ENABLED and last_screenshot:
                        vision_info = await visual_check(last_screenshot, cur_exp, ac)
                        vision_ok = vision_info.get("match", False) and \
                                    vision_info.get("confidence", 0.0) >= 0.6
                    if substring_ok or vision_ok:
                        current_step_index += 1
                        if DEBUG_TOOLS:
                            src = "substring" if substring_ok else \
                                  f"vision(conf={vision_info.get('confidence', 0):.2f})"
                            print(f"  [STEP] [{ctx.device_id}] step "
                                  f"{current_step_index}/{len(plan)} validated via {src}: "
                                  f"{cur_exp[:60]!r}")
                        if vision_ok and vision_info.get("reason"):
                            print(f"  [VISION] [{ctx.device_id}] reason: "
                                  f"{vision_info['reason'][:100]!r}")
                    else:
                        break

                # Auto-finish : (i) tous les steps validés, (ii) ou expected du dernier step matché
                if current_step_index >= len(plan):
                    plan_completed_hint = "tous les steps du plan validés"
                    if DEBUG_TOOLS:
                        print(f"  [AUTO-FINISH] [{ctx.device_id}] all {len(plan)} steps validated")
                else:
                    last_exp = (plan[-1].get("expected") or "").strip()
                    last_substring = last_exp and _expected_visible(last_exp, ctx.last_locators_raw)
                    last_vision = False
                    if not last_substring and VISION_ENABLED and last_screenshot and last_exp:
                        vc = await visual_check(last_screenshot, last_exp, ac)
                        last_vision = vc.get("match", False) and vc.get("confidence", 0) >= 0.7
                    if last_substring or last_vision:
                        plan_completed_hint = last_exp
                        # FIX conflit : bumper current_step_index pour que le plan refresh
                        # ne contredise plus l'auto-finish au tour suivant.
                        current_step_index = len(plan)
                        if DEBUG_TOOLS:
                            src = "substring" if last_substring else "vision"
                            print(f"  [AUTO-FINISH] [{ctx.device_id}] last expected matched "
                                  f"via {src}: {last_exp[:60]!r}")

    # Sortie de boucle SANS finish (max_turns atteint) → persister aussi le run
    kb_path = kb_save_run(test_type, TICKET_KEY, summary, plan,
                          local_action_trace, final)
    if DEBUG_TOOLS and kb_path:
        print(f"  [KB] {ctx.device_id}: run saved (no finish) → {kb_path}")
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

        print("\n(2b) Classification du ticket Jira (Knowledge Base)...")
        try:
            classification = await classify_jira_test_type(ac, summary)
            test_type = classification.get("test_type", "unknown")
            print(f"    → test_type={test_type!r} "
                  f"(confidence={classification.get('confidence', 0):.2f}, "
                  f"reason={classification.get('reason', '')[:80]!r})")
        except Exception as e:
            print(f"[WARN] classify_jira_test_type a échoué ({e}). test_type=unknown.")
            test_type = "unknown"

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
                results = await asyncio.gather(*[run_react(ac, ctx, barrier, summary, test_type) for ctx in ctxs], return_exceptions=True)
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
