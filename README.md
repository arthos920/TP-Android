#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""POC Alumnium/Appium coordonne sur plusieurs appareils Android.

Ce script reste volontairement independant de Jira, Jira MCP, GitLab,
Selenium et de toute logique metier. Le plan Settings est en dur. Plus tard,
le planner Jira pourra produire le meme format avec des roles et des delais.

Exemples PowerShell depuis le bundle portable :

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\run.ps1

    # Surcharger les associations de roles sans modifier le fichier config :
    .\\run.ps1 -Role "caller=phone_1","callee=phone_2"

    # Verifier uniquement la configuration, ADB et Appium :
    .\\run.ps1 -PreflightOnly
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


PRINT_LOCK = threading.Lock()


def log(message: str = "") -> None:
    """Evite de melanger les lignes produites par plusieurs workers."""
    with PRINT_LOCK:
        print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute un plan Alumnium coordonne sur plusieurs Android."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("qa_config.py")),
        help="Fichier Python de configuration (defaut : qa_config.py).",
    )
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="ROLE=DEVICE",
        help=(
            "Association role/appareil. Peut etre repetee. Si presente, "
            "remplace MULTI_DEVICE_ROLES du fichier config."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Valide config, ADB et Appium, sans creer de session ni appeler l'IA.",
    )
    parser.add_argument(
        "--skip-ai-preflight",
        action="store_true",
        help="Saute uniquement l'appel IA simple effectue avant les sessions.",
    )
    parser.add_argument(
        "--plan-source",
        choices=("fixed", "jira"),
        default=None,
        help="Source du plan. Surcharge PLAN_SOURCE du fichier config.",
    )
    parser.add_argument(
        "--jira-key",
        default=None,
        help="Cle Jira a utiliser. Surcharge JIRA_KEY du fichier config.",
    )
    parser.add_argument(
        "--jira-plan-only",
        action="store_true",
        help="Recupere Jira et genere le plan sans ADB, Appium ni Alumnium.",
    )
    return parser.parse_args()


def resolve_config_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    candidates = (
        [path]
        if path.is_absolute()
        else [Path.cwd() / path, Path(__file__).resolve().parent / path]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    searched = "\n  - ".join(str(candidate.resolve()) for candidate in candidates)
    raise FileNotFoundError(
        f"Fichier de configuration introuvable : {raw_path}\n"
        f"Chemins recherches :\n  - {searched}"
    )


def load_python_config(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("qa_multidevice_config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger la configuration : {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARGS = parse_args()
CONFIG_PATH = resolve_config_path(ARGS.config)
CONFIG = load_python_config(CONFIG_PATH)


def cfg(name: str, default: Any = None) -> Any:
    return getattr(CONFIG, name, default)


def env_or_config(name: str, default: Any = None) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    configured = cfg(name, default)
    return "" if configured is None else str(configured)


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Valeur booleenne invalide : {value!r}")


REQUIRED_CONFIG_NAMES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "PROXY_URL",
    "JIRA_MCP_URL",
    "JIRA_KEY",
    "PLAN_SOURCE",
    "ALUMNIUM_MODEL",
    "ALUMNIUM_LOG_LEVEL",
    "ALUMNIUM_CHANGE_ANALYSIS",
    "ALUMNIUM_RETRIES",
    "START",
    "NEW_COMMAND_TIMEOUT",
    "APPIUM_SERVER_URL",
    "DEVICES",
    "MULTI_DEVICE_ROLES",
)
MISSING_CONFIG = [name for name in REQUIRED_CONFIG_NAMES if not hasattr(CONFIG, name)]
if MISSING_CONFIG:
    raise RuntimeError(
        f"Configuration invalide ({CONFIG_PATH}) : variables manquantes : "
        + ", ".join(MISSING_CONFIG)
    )


# alumnium-cli herite de l'environnement du processus Python. Toutes ces
# variables doivent donc etre positionnees avant l'import de alumnium.
for env_name in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_CUSTOM_URL",
    "OPENAI_DEFAULT_HEADERS",
    "ALUMNIUM_MODEL",
    "ALUMNIUM_LOG_LEVEL",
    "ALUMNIUM_CHANGE_ANALYSIS",
    "ALUMNIUM_RETRIES",
    "ALUMNIUM_CACHE",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "PROXY_URL",
    "JIRA_MCP_URL",
    "JIRA_KEY",
):
    configured_value = env_or_config(env_name)
    if configured_value:
        os.environ[env_name] = configured_value

# OPENAI_BASE_URL est le nom utilise par le framework existant ; Alumnium
# attend OPENAI_CUSTOM_URL. Une valeur explicite OPENAI_CUSTOM_URL gagne.
if not os.environ.get("OPENAI_CUSTOM_URL", "").strip():
    openai_base_url = env_or_config("OPENAI_BASE_URL")
    if openai_base_url:
        os.environ["OPENAI_CUSTOM_URL"] = openai_base_url

os.environ["ALUMNIUM_LOG_LEVEL"] = os.environ["ALUMNIUM_LOG_LEVEL"].lower()
os.environ["ALUMNIUM_CHANGE_ANALYSIS"] = str(
    bool_value(os.environ["ALUMNIUM_CHANGE_ANALYSIS"])
).lower()
if "ALUMNIUM_CACHE" in os.environ:
    os.environ["ALUMNIUM_CACHE"] = str(bool_value(os.environ["ALUMNIUM_CACHE"])).lower()


def parse_role_overrides(raw_values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_value in raw_values:
        role, separator, device_name = raw_value.partition("=")
        role = role.strip()
        device_name = device_name.strip()
        if not separator or not role or not device_name:
            raise ValueError(
                f"--role invalide : {raw_value!r}. Format attendu : ROLE=DEVICE"
            )
        if role in result:
            raise ValueError(f"Role duplique dans les arguments : {role}")
        result[role] = device_name
    return result


ROLE_TO_DEVICE = parse_role_overrides(ARGS.role) or dict(CONFIG.MULTI_DEVICE_ROLES)
DEVICES: dict[str, dict[str, Any]] = dict(CONFIG.DEVICES)
PLAN_SOURCE = str(ARGS.plan_source or cfg("PLAN_SOURCE", "fixed")).strip().lower()
if ARGS.jira_plan_only:
    PLAN_SOURCE = "jira"
if PLAN_SOURCE not in {"fixed", "jira"}:
    raise ValueError(f"PLAN_SOURCE invalide : {PLAN_SOURCE!r}")

LLM_API_KEY = env_or_config("OPENAI_API_KEY")
LLM_BASE_URL = env_or_config("OPENAI_BASE_URL") or None
LLM_MODEL = env_or_config("OPENAI_MODEL", "magistral-2509")
PROXY_URL = env_or_config("PROXY_URL") or None
JIRA_MCP_URL = env_or_config("JIRA_MCP_URL")
JIRA_KEY = str(ARGS.jira_key or env_or_config("JIRA_KEY")).strip()
LLM_VERIFY_TLS = bool_value(cfg("LLM_VERIFY_TLS", False))
LLM_TIMEOUT = float(cfg("LLM_TIMEOUT", 180))
MAX_CHARS = int(cfg("MAX_CHARS", 12000))
FAIL_ON_MISSING_DATA = bool_value(cfg("FAIL_ON_MISSING_DATA", True))

APPIUM_SERVER_URL_FROM_ENV = bool(os.environ.get("APPIUM_SERVER_URL", "").strip())
APPIUM_SERVER_URL = env_or_config("APPIUM_SERVER_URL", CONFIG.APPIUM_SERVER_URL).rstrip("/")
START = env_or_config("START", CONFIG.START)
SCENARIO_START = str(cfg("MULTI_DEVICE_START", START))
NEW_COMMAND_TIMEOUT = int(env_or_config("ANDROID_NEW_COMMAND_TIMEOUT", CONFIG.NEW_COMMAND_TIMEOUT))
MAX_WORKERS = max(1, int(cfg("MAX_WORKERS", len(ROLE_TO_DEVICE))))
FAIL_FAST = bool_value(cfg("FAIL_FAST", True))
WAIT_TIMEOUT = float(cfg("MULTI_DEVICE_WAIT_TIMEOUT", 30))
WAIT_INTERVAL = float(cfg("MULTI_DEVICE_WAIT_INTERVAL", 2))
STEP_DELAY = float(cfg("MULTI_DEVICE_STEP_DELAY", 1))
ARTIFACTS_ROOT = Path(__file__).resolve().parent / str(cfg("ARTIFACTS_DIR", "artifacts"))
PLANNER = bool_value(cfg("ALUMNIUM_PLANNER", True))
CHANGE_ANALYSIS = bool_value(cfg("ALUMNIUM_CHANGE_ANALYSIS", False))
PLAN_CONTEXT: dict[str, Any] = {}


# Le plan reste en dur pendant ce POC. Un bloc "parallel" execute ses sous-
# etapes en meme temps. Chaque operation ne voit que l'UI de son propre role.
FIXED_MULTI_DEVICE_TEST_PLAN: list[dict[str, Any]] = [
    {
        "parallel": [
            {
                "role": "caller",
                "type": "check",
                "instruction": "The main Android Settings screen is displayed",
            },
            {
                "role": "callee",
                "type": "check",
                "instruction": "The main Android Settings screen is displayed",
            },
        ]
    },
    {
        "role": "caller",
        "type": "do",
        "instruction": "Open the Battery settings",
    },
    {
        "parallel": [
            {
                "role": "caller",
                "type": "check",
                "instruction": "The Battery settings screen is displayed",
            },
            {
                "role": "callee",
                "type": "check",
                "instruction": "The main Android Settings screen is displayed",
            },
        ]
    },
    {
        "role": "callee",
        "type": "do",
        "instruction": "Open the Network & internet settings",
    },
    {
        "parallel": [
            {
                "role": "caller",
                "type": "check",
                "instruction": "The Battery settings screen is displayed",
            },
            {
                "role": "callee",
                "type": "check",
                "instruction": "The Network & internet settings screen is displayed",
            },
        ]
    },
    {
        "parallel": [
            {
                "role": "caller",
                "type": "do",
                "instruction": (
                    "Tap the Navigate up button in the top-left corner to return "
                    "to the main Settings screen"
                ),
            },
            {
                "role": "callee",
                "type": "do",
                "instruction": (
                    "Tap the Navigate up button in the top-left corner to return "
                    "to the main Settings screen"
                ),
            },
        ]
    },
    {
        "parallel": [
            {
                "role": "caller",
                "type": "check",
                "instruction": "The main Android Settings screen is displayed",
            },
            {
                "role": "callee",
                "type": "check",
                "instruction": "The main Android Settings screen is displayed",
            },
        ]
    },
]

# Remplace par le plan genere depuis Jira avant la validation des roles lorsque
# PLAN_SOURCE=jira. Le plan fixe reste disponible pour le diagnostic Settings.
MULTI_DEVICE_TEST_PLAN: list[dict[str, Any]] = FIXED_MULTI_DEVICE_TEST_PLAN


@dataclass
class StepResult:
    number: str
    role: str
    kind: str
    instruction: str
    passed: bool
    duration_seconds: float
    detail: str = ""
    error_type: str = ""
    traceback: str = ""


@dataclass
class DeviceRuntime:
    role: str
    device_name: str
    settings: dict[str, Any]
    driver: Any = None
    alumni: Any = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def udid(self) -> str:
        return str(self.settings["udid"])

    @property
    def appium_url(self) -> str:
        if APPIUM_SERVER_URL_FROM_ENV:
            return APPIUM_SERVER_URL
        return str(self.settings.get("appium_url", APPIUM_SERVER_URL)).rstrip("/")


def command(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), capture_output=True, text=True, timeout=timeout, check=False
    )


def adb(runtime: DeviceRuntime, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return command("adb", "-s", runtime.udid, *args, timeout=timeout)


def parse_adb_devices() -> dict[str, str]:
    result = command("adb", "devices")
    if result.returncode != 0:
        raise RuntimeError(f"adb devices a echoue :\n{result.stderr or result.stdout}")
    states: dict[str, str] = {}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            states[parts[0]] = parts[1]
    return states


def validate_role_configuration() -> dict[str, DeviceRuntime]:
    if len(ROLE_TO_DEVICE) < 2:
        raise RuntimeError("Le POC multi-device exige au moins deux roles.")

    runtimes: dict[str, DeviceRuntime] = {}
    for role, device_name in ROLE_TO_DEVICE.items():
        if device_name not in DEVICES:
            raise RuntimeError(
                f"Le role {role!r} utilise un appareil inconnu {device_name!r}."
            )
        settings = dict(DEVICES[device_name])
        if not bool_value(settings.get("enabled", True)):
            raise RuntimeError(f"L'appareil {device_name!r} est desactive.")
        required = (
            "udid",
            "system_port",
            "chromedriver_port",
            "webview_devtools_port",
        )
        missing = [name for name in required if name not in settings]
        if missing:
            raise RuntimeError(
                f"Configuration incomplete pour {device_name!r} : {', '.join(missing)}"
            )
        if str(settings["udid"]).startswith("REPLACE_"):
            raise RuntimeError(
                f"UDID non configure pour {device_name!r}. Lancez diagnostic.ps1, "
                "puis copiez le numero de serie affiche par 'adb devices -l' "
                "dans qa_config.py."
            )
        runtimes[role] = DeviceRuntime(role, device_name, settings)

    unique_fields = (
        "udid",
        "system_port",
        "chromedriver_port",
        "webview_devtools_port",
    )
    for field_name in unique_fields:
        seen: dict[str, str] = {}
        for role, runtime in runtimes.items():
            value = str(runtime.settings[field_name])
            if value in seen:
                raise RuntimeError(
                    f"Collision {field_name}={value} entre {seen[value]} et {role}."
                )
            seen[value] = role

    plan_roles = {
        step["role"]
        for item in MULTI_DEVICE_TEST_PLAN
        for step in item.get("parallel", [item])
    }
    unknown_roles = sorted(plan_roles - set(runtimes))
    if unknown_roles:
        raise RuntimeError(
            "Roles requis par le plan mais absents de la configuration : "
            + ", ".join(unknown_roles)
        )
    return runtimes


def appium_preflight(urls: set[str]) -> None:
    import httpx

    for url in sorted(urls):
        response = httpx.get(f"{url}/status", timeout=10)
        response.raise_for_status()
        payload = response.json()
        value = payload.get("value", payload)
        if not value.get("ready"):
            raise RuntimeError(f"Appium n'est pas pret sur {url} : {payload}")
        log(f"[preflight] APPIUM OK  {url}  version={value.get('build', {}).get('version', '?')}")


def devices_preflight(runtimes: dict[str, DeviceRuntime]) -> None:
    states = parse_adb_devices()
    for role, runtime in runtimes.items():
        state = states.get(runtime.udid, "absent")
        if state != "device":
            raise RuntimeError(
                f"ADB {role}/{runtime.udid} : etat {state!r}, attendu 'device'."
            )
        boot = adb(runtime, "shell", "getprop", "sys.boot_completed").stdout.strip()
        if boot != "1":
            raise RuntimeError(f"Android n'a pas fini son boot sur {runtime.udid}.")
        log(
            f"[preflight] ADB OK     role={role:<8} device={runtime.device_name:<24} "
            f"udid={runtime.udid} systemPort={runtime.settings['system_port']}"
        )


def ai_preflight() -> None:
    """Valide une seule fois le provider avant de creer plusieurs sessions."""
    import httpx

    model_value = os.environ["ALUMNIUM_MODEL"]
    provider, separator, model = model_value.partition("/")
    if not separator:
        provider, model = model_value, model_value

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY manquant pour le modele Anthropic.")
        url = "https://api.anthropic.com/v1/messages"
        log(f"[preflight] IA POST {url}  model={model}")
        response = httpx.post(
            url,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            },
            timeout=60,
        )
    elif provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        base_url = os.environ.get("OPENAI_CUSTOM_URL", "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY manquant pour le modele OpenAI-compatible.")
        if not base_url:
            base_url = "https://api.openai.com/v1"
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        raw_default_headers = os.environ.get("OPENAI_DEFAULT_HEADERS", "").strip()
        if raw_default_headers:
            headers.update(json.loads(raw_default_headers))
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 16,
        }
        # Reproduit le comportement Alumnium 0.21.0 pour verifier les gateways
        # locales avant que deux ou trois sessions envoient des requetes.
        if "gpt-4o" not in model:
            payload["reasoning"] = {"effort": "low", "summary": "auto"}
        log(f"[preflight] IA POST {url}  model={model}")
        response = httpx.post(url, headers=headers, json=payload, timeout=60)
    else:
        log(
            f"[preflight] IA non implementee pour provider={provider!r}; "
            "la validation sera faite par Alumni()."
        )
        return

    log(f"[preflight] IA HTTP {response.status_code}")
    if response.status_code >= 400:
        raise RuntimeError(
            f"Le provider IA a refuse le preflight : HTTP {response.status_code}\n"
            f"{response.text[:2000]}"
        )


def generate_plan_from_jira() -> dict[str, Any]:
    """Execute Jira MCP puis le planner entreprise avant toute session Appium."""
    if not LLM_API_KEY or LLM_API_KEY.startswith("REPLACE_"):
        raise RuntimeError("OPENAI_API_KEY manquant dans qa_config.py.")
    if not LLM_MODEL:
        raise RuntimeError("OPENAI_MODEL manquant dans qa_config.py.")
    if not JIRA_MCP_URL or JIRA_MCP_URL.startswith("REPLACE_"):
        raise RuntimeError("JIRA_MCP_URL manquant dans qa_config.py.")
    if not JIRA_KEY or JIRA_KEY.startswith("REPLACE_"):
        raise RuntimeError("JIRA_KEY manquant dans qa_config.py.")

    raw_default_headers = env_or_config("OPENAI_DEFAULT_HEADERS")
    default_headers: dict[str, str] | None = None
    if raw_default_headers:
        parsed_headers = json.loads(raw_default_headers)
        if not isinstance(parsed_headers, dict):
            raise RuntimeError("OPENAI_DEFAULT_HEADERS doit etre un objet JSON.")
        default_headers = {
            str(name): str(value) for name, value in parsed_headers.items()
        }

    from jira_mcp_planner import fetch_jira_and_build_plan

    log("\n" + "=" * 76)
    log("JIRA MCP -> LLM PLANNER -> PLAN MULTI-DEVICE")
    log("=" * 76)
    log(f"JIRA_MCP_URL = {JIRA_MCP_URL}")
    log(f"JIRA_KEY     = {JIRA_KEY}")
    log(f"LLM_MODEL    = {LLM_MODEL}")
    log(f"ROLES        = {', '.join(sorted(ROLE_TO_DEVICE))}")

    context = asyncio.run(
        fetch_jira_and_build_plan(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            proxy_url=PROXY_URL,
            default_headers=default_headers,
            verify_tls=LLM_VERIFY_TLS,
            timeout=LLM_TIMEOUT,
            jira_mcp_url=JIRA_MCP_URL,
            jira_key=JIRA_KEY,
            max_chars=MAX_CHARS,
            available_roles=sorted(ROLE_TO_DEVICE),
        )
    )

    log("\n--- RESUME JIRA ---")
    log(context["issue_summary"])
    log("\n--- CLASSIFICATION ---")
    log(json.dumps(context["classification"], ensure_ascii=False, indent=2))
    log("\n--- GENERATED ALUMNIUM MULTI-DEVICE PLAN ---")
    log(json.dumps(context["plan"], ensure_ascii=False, indent=2))
    return context


def go_to_start(runtime: DeviceRuntime) -> None:
    display_size = runtime.settings.get("display_size")
    display_density = runtime.settings.get("display_density")
    if display_size:
        resized = adb(runtime, "shell", "wm", "size", str(display_size))
        if resized.returncode != 0:
            raise RuntimeError(
                f"Echec wm size sur {runtime.udid}: {resized.stderr or resized.stdout}"
            )
    if display_density:
        redensified = adb(runtime, "shell", "wm", "density", str(display_density))
        if redensified.returncode != 0:
            raise RuntimeError(
                f"Echec wm density sur {runtime.udid}: "
                f"{redensified.stderr or redensified.stdout}"
            )
    if display_size or display_density:
        log(
            f"[adb:{runtime.role}] affichage normalise size={display_size or 'native'} "
            f"density={display_density or 'native'}"
        )

    if SCENARIO_START == "home":
        result = adb(runtime, "shell", "input", "keyevent", "KEYCODE_HOME")
    elif SCENARIO_START.startswith("intent:"):
        action = SCENARIO_START.split(":", 1)[1].strip()
        if not action:
            raise RuntimeError("MULTI_DEVICE_START contient un intent vide.")
        resolved = adb(
            runtime,
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            action,
        )
        component = next(
            (line.strip() for line in reversed(resolved.stdout.splitlines()) if "/" in line),
            "",
        )
        if resolved.returncode != 0 or not component:
            raise RuntimeError(
                f"Impossible de resoudre l'intent {action!r} sur {runtime.udid}:\n"
                f"{resolved.stderr or resolved.stdout}"
            )
        package = component.split("/", 1)[0]
        stopped = adb(runtime, "shell", "am", "force-stop", package)
        if stopped.returncode != 0:
            raise RuntimeError(
                f"Echec force-stop {package} sur {runtime.udid}:\n"
                f"{stopped.stderr or stopped.stdout}"
            )
        result = adb(
            runtime,
            "shell",
            "am",
            "start",
            "-S",
            "-W",
            "-a",
            action,
            "-f",
            "0x10008000",
        )
        log(
            f"[adb:{runtime.role}] intent={action} resolu={component} "
            f"sur {runtime.udid}"
        )
    elif "/" in SCENARIO_START:
        package = SCENARIO_START.split("/", 1)[0]
        adb(runtime, "shell", "am", "force-stop", package)
        result = adb(runtime, "shell", "am", "start", "-W", "-n", SCENARIO_START)
    else:
        adb(runtime, "shell", "am", "force-stop", SCENARIO_START)
        result = adb(
            runtime,
            "shell",
            "monkey",
            "-p",
            SCENARIO_START,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"Impossible de positionner {runtime.role}/{runtime.udid} sur {SCENARIO_START}:\n"
            f"{result.stderr or result.stdout}"
        )
    log(f"[adb:{runtime.role}] START={SCENARIO_START} sur {runtime.udid}")


def build_runtime(runtime: DeviceRuntime, alumni_class: Any) -> None:
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    settings = runtime.settings
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.udid = runtime.udid
    options.no_reset = True
    options.new_command_timeout = NEW_COMMAND_TIMEOUT
    options.set_capability("appium:autoLaunch", False)
    options.set_capability("appium:appWaitActivity", "*")
    options.set_capability("appium:systemPort", int(settings["system_port"]))
    options.set_capability("appium:chromedriverPort", int(settings["chromedriver_port"]))
    options.set_capability("appium:webviewDevtoolsPort", int(settings["webview_devtools_port"]))

    log(
        f"[appium:{runtime.role}] creation session url={runtime.appium_url} "
        f"udid={runtime.udid} systemPort={settings['system_port']}"
    )
    runtime.driver = webdriver.Remote(runtime.appium_url, options=options)
    log(
        f"[appium:{runtime.role}] SESSION OK id={runtime.driver.session_id} "
        f"automation={runtime.driver.capabilities.get('automationName', '?')}"
    )

    log(f"[alumnium:{runtime.role}] initialisation...")
    runtime.alumni = alumni_class(
        runtime.driver,
        planner=PLANNER,
        change_analysis=CHANGE_ANALYSIS,
    )
    if runtime.alumni.driver.platform != "uiautomator2":
        log(
            f"[alumnium:{runtime.role}] correction plateforme "
            f"{runtime.alumni.driver.platform} -> uiautomator2"
        )
        runtime.alumni.driver.platform = "uiautomator2"
    log(
        f"[alumnium:{runtime.role}] INIT OK session={runtime.alumni.client.session_id} "
        f"server={runtime.alumni.client.base_url}"
    )


def run_parallel(
    tasks: dict[str, Callable[[], Any]], max_workers: int | None = None
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    workers = min(max_workers or MAX_WORKERS, len(tasks))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_name = {executor.submit(task): name for name, task in tasks.items()}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            results[name] = future.result()
    return results


def failure_artifacts(run_dir: Path, runtime: DeviceRuntime, number: str) -> None:
    safe_role = "".join(char if char.isalnum() or char in "-_" else "_" for char in runtime.role)
    prefix = run_dir / f"failure-{number.replace('.', '-')}-{safe_role}"
    try:
        runtime.driver.get_screenshot_as_file(str(prefix.with_suffix(".png")))
    except Exception as exc:  # diagnostic secondaire
        log(f"[artifact:{runtime.role}] screenshot impossible : {exc}")
    try:
        prefix.with_suffix(".xml").write_text(runtime.driver.page_source, encoding="utf-8")
    except Exception as exc:  # diagnostic secondaire
        log(f"[artifact:{runtime.role}] page source impossible : {exc}")


def execute_step(
    number: str,
    step: dict[str, Any],
    runtimes: dict[str, DeviceRuntime],
    run_dir: Path,
) -> StepResult:
    role = str(step["role"])
    kind = str(step["type"]).lower()
    instruction = str(step["instruction"])
    runtime = runtimes[role]
    started = time.monotonic()
    log(f"\n[{number}][{role}] {kind.upper()} {instruction}")

    try:
        if kind == "do":
            result = runtime.alumni.do(instruction)
            executed_tools = [
                tool
                for executed_step in getattr(result, "steps", [])
                for tool in getattr(executed_step, "tools", [])
            ]
            if not executed_tools:
                explanation = getattr(result, "explanation", str(result))
                raise RuntimeError(
                    "Alumnium n'a execute aucun outil pour cette instruction. "
                    f"Explication du modele : {explanation}"
                )
            detail = (
                f"{getattr(result, 'explanation', str(result))} | "
                f"tools={executed_tools}"
            )
        elif kind == "check":
            detail = str(runtime.alumni.check(instruction))
        elif kind == "wait-check":
            timeout = float(step.get("timeout_seconds", WAIT_TIMEOUT))
            interval = float(step.get("interval_seconds", WAIT_INTERVAL))
            deadline = time.monotonic() + timeout
            attempts = 0
            last_assertion = ""
            while True:
                attempts += 1
                try:
                    detail = str(runtime.alumni.check(instruction))
                    detail = f"condition atteinte apres {attempts} tentative(s): {detail}"
                    break
                except AssertionError as exc:
                    last_assertion = str(exc)
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Condition non atteinte apres {timeout:.1f}s et {attempts} "
                            f"tentative(s). Derniere assertion : {last_assertion}"
                        ) from exc
                    time.sleep(interval)
        else:
            raise ValueError(f"Type d'etape inconnu : {kind!r}")

        duration = time.monotonic() - started
        log(f"[{number}][{role}] [PASS] {duration:.1f}s")
        return StepResult(number, role, kind, instruction, True, duration, detail=detail)
    except Exception as exc:  # on veut capturer toute la pile Alumnium/Appium
        duration = time.monotonic() - started
        full_traceback = traceback.format_exc()
        error_detail = str(exc)
        provider_detail = ""
        # requests.HTTPError conserve la réponse du daemon Alumnium. Le corps
        # contient l'erreur réelle du provider (timeout, json_schema, tools,
        # paramètre refusé...), alors que raise_for_status() n'affiche que 500.
        response = getattr(exc, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", "?")
            response_url = getattr(response, "url", "")
            try:
                response_body = str(response.text).strip()
            except Exception as body_error:  # diagnostic secondaire
                response_body = f"<corps illisible: {body_error}>"
            response_body = response_body[:6000] or "<corps vide>"
            provider_detail = (
                "ALUMNIUM SERVER RESPONSE\n"
                f"status={status_code} url={response_url}\n"
                f"body={response_body}"
            )
            error_detail = f"{error_detail}\n{provider_detail}"

        log(
            f"[{number}][{role}] [FAIL] {duration:.1f}s "
            f"{type(exc).__name__}: {exc}"
        )
        if provider_detail:
            log(f"[{number}][{role}] {provider_detail}")
        log(full_traceback)
        failure_artifacts(run_dir, runtime, number)
        return StepResult(
            number,
            role,
            kind,
            instruction,
            False,
            duration,
            error_type=type(exc).__name__,
            detail=error_detail,
            traceback=full_traceback,
        )


def execute_plan(
    runtimes: dict[str, DeviceRuntime], run_dir: Path
) -> list[StepResult]:
    results: list[StepResult] = []
    for major_number, item in enumerate(MULTI_DEVICE_TEST_PLAN, 1):
        if "parallel" in item:
            steps = list(item["parallel"])
            log(f"\n--- BLOC PARALLELE #{major_number} ({len(steps)} appareils) ---")
            tasks = {
                f"{major_number}.{minor_number}": (
                    lambda number=f"{major_number}.{minor_number}", step=step: execute_step(
                        number, step, runtimes, run_dir
                    )
                )
                for minor_number, step in enumerate(steps, 1)
            }
            block_results = run_parallel(tasks)
            ordered = [block_results[f"{major_number}.{minor}"] for minor in range(1, len(steps) + 1)]
            results.extend(ordered)
            block_failed = any(not result.passed for result in ordered)
            if block_failed and FAIL_FAST:
                break
        else:
            result = execute_step(str(major_number), item, runtimes, run_dir)
            results.append(result)
            if not result.passed and FAIL_FAST:
                break
        time.sleep(STEP_DELAY)
    return results


def close_runtime(runtime: DeviceRuntime) -> None:
    try:
        if runtime.alumni is not None:
            try:
                runtime.stats = runtime.alumni.stats
            except Exception as exc:
                log(f"[stats:{runtime.role}] indisponibles : {exc}")
            runtime.alumni.quit()
        elif runtime.driver is not None:
            runtime.driver.quit()
        log(f"[cleanup:{runtime.role}] session fermee")
    except Exception:
        log(f"[cleanup:{runtime.role}] ECHEC\n{traceback.format_exc()}")


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def write_report(
    run_dir: Path,
    runtimes: dict[str, DeviceRuntime],
    results: list[StepResult],
    started_at: str,
) -> Path:
    payload = {
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "config": str(CONFIG_PATH),
        "plan_source": PLAN_SOURCE,
        "jira": (
            {
                "jira_key": PLAN_CONTEXT.get("jira_key"),
                "issue_tool": PLAN_CONTEXT.get("issue_tool"),
                "issue_summary": PLAN_CONTEXT.get("issue_summary"),
                "classification": PLAN_CONTEXT.get("classification"),
            }
            if PLAN_SOURCE == "jira"
            else None
        ),
        "generated_plan": PLAN_CONTEXT.get(
            "plan",
            {
                "target": "mobile",
                "goal": "Fixed Android Settings multi-device smoke test",
                "missing_data": [],
                "steps": MULTI_DEVICE_TEST_PLAN,
            },
        ),
        "model": os.environ.get("ALUMNIUM_MODEL", ""),
        "appium_server": APPIUM_SERVER_URL,
        "roles": {
            role: {
                "device_name": runtime.device_name,
                "udid": runtime.udid,
                "appium_url": runtime.appium_url,
                "system_port": runtime.settings["system_port"],
                "appium_session": getattr(runtime.driver, "session_id", None),
                "stats": json_safe(runtime.stats),
            }
            for role, runtime in runtimes.items()
        },
        "summary": {
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
            "total": len(results),
        },
        "steps": [asdict(result) for result in results],
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def print_configuration(runtimes: dict[str, DeviceRuntime]) -> None:
    log("=" * 76)
    log("smoke_alumnium_multidevice.py : POC coordonne multi-device")
    log("=" * 76)
    log(f"CONFIG_FILE          = {CONFIG_PATH}")
    log(f"PLAN_SOURCE          = {PLAN_SOURCE}")
    if PLAN_SOURCE == "jira":
        log(f"JIRA_KEY             = {JIRA_KEY}")
    log(f"ALUMNIUM_MODEL       = {os.environ['ALUMNIUM_MODEL']}")
    log(f"ALUMNIUM_PLANNER     = {PLANNER}")
    log(f"CHANGE_ANALYSIS      = {CHANGE_ANALYSIS}")
    log(f"APPIUM_SERVER_URL    = {APPIUM_SERVER_URL}")
    log(f"MULTI_DEVICE_START   = {SCENARIO_START}")
    log(f"MAX_WORKERS          = {MAX_WORKERS}")
    log(f"FAIL_FAST            = {FAIL_FAST}")
    for role, runtime in runtimes.items():
        log(
            f"ROLE {role:<10} = {runtime.device_name:<24} udid={runtime.udid:<14} "
            f"systemPort={runtime.settings['system_port']}"
        )


def main() -> int:
    global MULTI_DEVICE_TEST_PLAN, PLAN_CONTEXT

    started_at = datetime.now().astimezone().isoformat()
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = ARTIFACTS_ROOT / "multidevice" / run_stamp

    # Le preflight infrastructure reste utilisable sans Jira ni endpoint IA.
    if ARGS.preflight_only:
        runtimes = validate_role_configuration()
        print_configuration(runtimes)
        devices_preflight(runtimes)
        appium_preflight({runtime.appium_url for runtime in runtimes.values()})
        log("\n>>> PREFLIGHT MULTI-DEVICE : SUCCES <<<")
        return 0

    if PLAN_SOURCE == "jira":
        try:
            PLAN_CONTEXT = generate_plan_from_jira()
            MULTI_DEVICE_TEST_PLAN = list(PLAN_CONTEXT["plan"]["steps"])
            run_dir.mkdir(parents=True, exist_ok=True)
            plan_path = run_dir / "generated-jira-plan.json"
            plan_path.write_text(
                json.dumps(PLAN_CONTEXT, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(f"\n[artifact] Plan Jira : {plan_path}")
        except Exception:
            log("\n>>> ECHEC COUCHE JIRA MCP / LLM PLANNER <<<")
            log(traceback.format_exc())
            return 1

        missing_data = PLAN_CONTEXT["plan"].get("missing_data", [])
        if missing_data:
            log("\n[WARN] Donnees obligatoires manquantes dans Jira :")
            for item in missing_data:
                log(f"  - {item}")
            if FAIL_ON_MISSING_DATA and not ARGS.jira_plan_only:
                log(
                    "\n>>> EXECUTION BLOQUEE : completez Jira ou passez "
                    "FAIL_ON_MISSING_DATA=False dans qa_config.py. <<<"
                )
                return 1

        if ARGS.jira_plan_only:
            log("\n>>> JIRA MCP + GENERATION DU PLAN : SUCCES <<<")
            return 0
    else:
        PLAN_CONTEXT = {
            "plan": {
                "target": "mobile",
                "goal": "Fixed Android Settings multi-device smoke test",
                "missing_data": [],
                "steps": MULTI_DEVICE_TEST_PLAN,
            }
        }

    runtimes = validate_role_configuration()
    print_configuration(runtimes)

    devices_preflight(runtimes)
    appium_preflight({runtime.appium_url for runtime in runtimes.values()})

    if not ARGS.skip_ai_preflight:
        ai_preflight()

    run_dir.mkdir(parents=True, exist_ok=True)

    # L'import est differe : alumnium et le binaire alumnium-cli voient toutes
    # les variables configurees au debut du processus.
    from alumnium import Alumni

    results: list[StepResult] = []
    try:
        log("\n--- POSITIONNEMENT DES APPAREILS ---")
        run_parallel(
            {
                role: (lambda runtime=runtime: go_to_start(runtime))
                for role, runtime in runtimes.items()
            }
        )
        time.sleep(2.5)

        log("\n--- CREATION DES SESSIONS APPIUM + ALUMNIUM ---")
        run_parallel(
            {
                role: (
                    lambda runtime=runtime: build_runtime(runtime, Alumni)
                )
                for role, runtime in runtimes.items()
            }
        )

        log("\n--- EXECUTION DU PLAN COORDONNE ---")
        results = execute_plan(runtimes, run_dir)
    except Exception:
        log("\n>>> ECHEC D'INITIALISATION/ORCHESTRATION <<<")
        log(traceback.format_exc())
    finally:
        log("\n--- FERMETURE DES SESSIONS ---")
        run_parallel(
            {
                role: (lambda runtime=runtime: close_runtime(runtime))
                for role, runtime in runtimes.items()
            }
        )

    report_path = write_report(run_dir, runtimes, results, started_at)
    passed = sum(result.passed for result in results)
    failed = sum(not result.passed for result in results)
    expected = sum(
        len(item.get("parallel", [item])) for item in MULTI_DEVICE_TEST_PLAN
    )

    log("\n" + "=" * 76)
    log("RESUME MULTI-DEVICE")
    log("=" * 76)
    log(f"Etapes attendues : {expected}")
    log(f"Etapes executees : {len(results)}")
    log(f"PASS             : {passed}")
    log(f"FAIL             : {failed}")
    for role, runtime in runtimes.items():
        totals = runtime.stats.get("total", {}) if isinstance(runtime.stats, dict) else {}
        log(
            f"TOKENS {role:<10}: input={totals.get('input_tokens', '?')} "
            f"output={totals.get('output_tokens', '?')} total={totals.get('total_tokens', '?')}"
        )
    log(f"Rapport          : {report_path}")

    success = failed == 0 and len(results) == expected
    log("\n>>> " + ("SUCCES MULTI-DEVICE" if success else "ECHEC MULTI-DEVICE") + " <<<")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
