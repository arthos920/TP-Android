#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnostic progressif d'un endpoint OpenAI-compatible pour Alumnium 0.21.

Le script utilise le runtime Python portable et HTTPX deja livres dans le
bundle. Il envoie des requetes Chat Completions explicites afin de conserver
la reponse JSON brute du provider. Il ne journalise jamais la cle API ni les
valeurs des en-tetes.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste chat, tools et JSON Schema sur le provider d'Alumnium."
    )
    parser.add_argument(
        "--config",
        default=str(ROOT / "qa_config.py"),
        help="Configuration Python utilisee par le bundle.",
    )
    parser.add_argument(
        "--test",
        action="append",
        choices=("basic", "tools", "structured", "alumnium"),
        help="Test a executer. Repetable. Par defaut : tous, sequentiellement.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Timeout de chaque requete en secondes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche seulement la forme des payloads, sans appel reseau.",
    )
    return parser.parse_args()


def load_config(path: Path) -> ModuleType:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Configuration introuvable : {resolved}")
    spec = importlib.util.spec_from_file_location("provider_doctor_config", resolved)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger : {resolved}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured(config: ModuleType, name: str, default: Any = "") -> str:
    env_value = os.environ.get(name, "").strip()
    if env_value:
        return env_value
    value = getattr(config, name, default)
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_url(value: str) -> str:
    """Supprime credentials, query et fragment avant journalisation."""
    parts = urlsplit(value)
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port:
        netloc = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def prompt_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
        else:
            total += len(json.dumps(content, ensure_ascii=False))
    return total


def redact(value: str, secrets: list[str]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "<REDACTED_SECRET>")
    result = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"}]+",
        r"\1<REDACTED>",
        result,
    )
    result = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,'\"}]+", r"\1<REDACTED>", result)
    return result


def text_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        )
    return "" if content is None else str(content)


WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Retourne la meteo d'une ville.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}

CLICK_TOOL = {
    "type": "function",
    "function": {
        "name": "ClickTool",
        "description": "Click an Android element identified in the accessibility tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The exact element id from the accessibility tree.",
                }
            },
            "required": ["id"],
        },
    },
}

SIMPLE_SCHEMA = {
    "name": "simple_action",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "target": {"type": "string"},
        },
        "required": ["action", "target"],
        "additionalProperties": False,
    },
}

PLAN_SCHEMA = {
    "name": "extract",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "explanation": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["explanation", "actions"],
        "additionalProperties": False,
    },
}

RETRIEVER_SCHEMA = {
    "name": "extract",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "explanation": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["explanation", "value"],
        "additionalProperties": False,
    },
}

FAKE_TREE = (
    '<android.widget.FrameLayout id="root">'
    '<android.widget.TextView id="battery" text="Battery" clickable="true" />'
    "</android.widget.FrameLayout>"
)


def build_cases(model: str) -> list[dict[str, Any]]:
    return [
        {
            "group": "basic",
            "name": "1_chat_basique",
            "expect": "content",
            "payload": {
                "model": model,
                "messages": [
                    {"role": "user", "content": "Réponds uniquement par OK."}
                ],
            },
        },
        {
            "group": "tools",
            "name": "2a_tool_auto_comme_actor",
            "expect": "tool",
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Quel temps fait-il à Paris ? Utilise obligatoirement "
                            "l'outil get_weather. Ne réponds pas en texte."
                        ),
                    }
                ],
                "tools": [WEATHER_TOOL],
            },
        },
        {
            "group": "tools",
            "name": "2b_tool_force",
            "expect": "tool",
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Appelle get_weather pour la ville de Paris.",
                    }
                ],
                "tools": [WEATHER_TOOL],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "get_weather"},
                },
            },
        },
        {
            "group": "structured",
            "name": "3_structured_json_schema",
            "expect": "structured",
            "required_fields": ["action", "target"],
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Décris l'action ouvrir et la cible Battery.",
                    }
                ],
                "response_format": {"type": "json_schema", "json_schema": SIMPLE_SCHEMA},
            },
        },
        {
            "group": "alumnium",
            "name": "4a_alumnium_planner_json_schema",
            "expect": "structured",
            "required_fields": ["explanation", "actions"],
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Plan one or more concise UI actions for the given goal.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Goal: Open Battery settings.\nAccessibility tree:\n" + FAKE_TREE
                        ),
                    },
                ],
                "response_format": {"type": "json_schema", "json_schema": PLAN_SCHEMA},
            },
        },
        {
            "group": "alumnium",
            "name": "4b_alumnium_actor_tools",
            "expect": "tool",
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Execute the requested UI step using the declared tools. "
                            "Return a tool call, not a textual description."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Goal: Open Battery settings.\nStep: Click Battery.\n"
                            "Accessibility tree:\n" + FAKE_TREE
                        ),
                    },
                ],
                "tools": [CLICK_TOOL],
            },
        },
        {
            "group": "alumnium",
            "name": "4c_alumnium_retriever_json_schema",
            "expect": "structured",
            "required_fields": ["explanation", "value"],
            "payload": {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Retrieve the requested information from the Android "
                            "accessibility tree. Return value as a string."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Accessibility tree:\n"
                            + FAKE_TREE
                            + "\nRetrieve the following information: Is the following "
                            "true or false - The Battery settings entry is displayed"
                        ),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": RETRIEVER_SCHEMA,
                },
            },
        },
    ]


def request_summary(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages", [])
    return {
        "payload_keys": sorted(payload),
        "message_count": len(messages),
        "prompt_chars": prompt_chars(messages),
        "tools_present": "tools" in payload,
        "tools_count": len(payload.get("tools", [])),
        "tool_choice_present": "tool_choice" in payload,
        "response_format_present": "response_format" in payload,
        "response_format_type": payload.get("response_format", {}).get("type"),
    }


def evaluate_response(
    case: dict[str, Any], status: int, body: Any
) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {
        "finish_reason": None,
        "content_present": False,
        "content_chars": 0,
        "tool_calls_present": False,
        "tool_calls_count": 0,
        "tool_names": [],
        "tool_arguments_json_valid": [],
        "legacy_function_call_present": False,
        "structured_json_valid": False,
        "reasoning_present": False,
        "reasoning_chars": 0,
    }
    if status >= 400 or not isinstance(body, dict):
        return False, details
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        details["protocol_error"] = "choices absent ou vide"
        return False, details
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    details["finish_reason"] = choice.get("finish_reason")
    content = text_content(message)
    details["content_present"] = bool(content.strip())
    details["content_chars"] = len(content)
    details["legacy_function_call_present"] = bool(message.get("function_call"))
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(reasoning, str):
        details["reasoning_present"] = bool(reasoning.strip())
        details["reasoning_chars"] = len(reasoning)
    elif reasoning is not None:
        serialized_reasoning = json.dumps(reasoning, ensure_ascii=False)
        details["reasoning_present"] = bool(serialized_reasoning)
        details["reasoning_chars"] = len(serialized_reasoning)

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []
    details["tool_calls_present"] = bool(tool_calls)
    details["tool_calls_count"] = len(tool_calls)
    for tool_call in tool_calls:
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        name = function.get("name") if isinstance(function, dict) else None
        arguments = function.get("arguments") if isinstance(function, dict) else None
        details["tool_names"].append(name)
        try:
            json.loads(arguments) if isinstance(arguments, str) else arguments
            details["tool_arguments_json_valid"].append(isinstance(arguments, (str, dict)))
        except json.JSONDecodeError:
            details["tool_arguments_json_valid"].append(False)

    if case["expect"] == "content":
        if not details["content_present"] and details["reasoning_present"]:
            details["diagnostic"] = (
                "Le provider a produit du raisonnement mais aucun contenu final."
            )
        return details["content_present"], details
    if case["expect"] == "tool":
        if not tool_calls and content:
            details["diagnostic"] = (
                "Le modele a renvoye du texte mais aucun message.tool_calls; "
                "Alumnium ActorAgent le convertira en actions=[]."
            )
        elif details["legacy_function_call_present"] and not tool_calls:
            details["diagnostic"] = (
                "Le provider utilise function_call legacy au lieu de tool_calls."
            )
        valid_args = details["tool_arguments_json_valid"]
        return bool(tool_calls) and all(valid_args), details

    try:
        structured = json.loads(content)
        required_fields = case.get("required_fields", [])
        details["structured_json_valid"] = isinstance(structured, dict) and all(
            field in structured for field in required_fields
        )
    except (json.JSONDecodeError, TypeError):
        details["diagnostic"] = (
            "message.content n'est pas un objet JSON conforme au json_schema."
        )
    return details["structured_json_valid"], details


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    api_key = configured(config, "OPENAI_API_KEY")
    base_url = configured(config, "OPENAI_CUSTOM_URL") or configured(
        config, "OPENAI_BASE_URL"
    )
    explicit_openai_model = os.environ.get("OPENAI_MODEL", "").strip()
    explicit_alumnium_model = os.environ.get("ALUMNIUM_MODEL", "").strip()
    model = explicit_openai_model or str(
        getattr(config, "OPENAI_MODEL", "gpt-oss-120b")
    ).strip()
    alumnium_model = explicit_alumnium_model or (
        "" if explicit_openai_model else str(getattr(config, "ALUMNIUM_MODEL", "")).strip()
    )
    if alumnium_model.startswith("openai/"):
        model = alumnium_model.split("/", 1)[1]
    proxy_url = configured(config, "PROXY_URL") or None
    verify_tls = as_bool(getattr(config, "LLM_VERIFY_TLS", True))
    timeout = args.timeout or float(getattr(config, "ALUMNIUM_MODEL_TIMEOUT", 120))

    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL/OPENAI_CUSTOM_URL manquant.")
    if not model:
        raise RuntimeError("OPENAI_MODEL/ALUMNIUM_MODEL manquant.")
    if not api_key and not args.dry_run:
        raise RuntimeError("OPENAI_API_KEY manquante. Sa valeur ne sera jamais affichee.")

    endpoint = chat_completions_url(base_url)
    raw_headers = configured(config, "OPENAI_DEFAULT_HEADERS")
    default_headers: dict[str, str] = {}
    if raw_headers:
        parsed_headers = json.loads(raw_headers)
        if not isinstance(parsed_headers, dict):
            raise ValueError("OPENAI_DEFAULT_HEADERS doit etre un objet JSON.")
        default_headers = {str(key): str(value) for key, value in parsed_headers.items()}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **default_headers,
    }
    sensitive_values = [api_key, *default_headers.values()]

    try:
        openai_version = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError:
        openai_version = "absent"
    try:
        alumnium_version = importlib.metadata.version("alumnium")
    except importlib.metadata.PackageNotFoundError:
        alumnium_version = "absent"

    print("=" * 76)
    print("DIAGNOSTIC PROVIDER OPENAI-COMPATIBLE POUR ALUMNIUM")
    print("=" * 76)
    print(f"Python              : {sys.version.split()[0]} ({sys.executable})")
    print(f"alumnium            : {alumnium_version}")
    print(f"openai Python       : {openai_version} (information; requetes brutes HTTPX)")
    print(f"httpx               : {httpx.__version__}")
    print(f"model               : {model}")
    print(f"base_url            : {safe_url(base_url)}")
    print(f"endpoint final      : {safe_url(endpoint)}")
    print(f"proxy               : {'configure' if proxy_url else 'absent'}")
    print(f"TLS verify          : {verify_tls}")
    print(f"timeout             : {timeout:.1f}s")
    print(f"en-tetes additionnels: {sorted(default_headers)} (valeurs masquees)")
    print("API key             : presente (masquee)" if api_key else "API key             : absente")

    requested_groups = set(args.test or ("basic", "tools", "structured", "alumnium"))
    cases = [case for case in build_cases(model) if case["group"] in requested_groups]
    report: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "runtime": {
            "python": sys.version.split()[0],
            "alumnium": alumnium_version,
            "openai": openai_version,
            "httpx": httpx.__version__,
        },
        "provider": {
            "model": model,
            "base_url": safe_url(base_url),
            "endpoint": safe_url(endpoint),
            "proxy_configured": bool(proxy_url),
            "verify_tls": verify_tls,
        },
        "results": [],
    }

    failures = 0
    client = None
    if not args.dry_run:
        client = httpx.Client(
            proxy=proxy_url,
            verify=verify_tls,
            timeout=httpx.Timeout(timeout),
        )
    try:
        for case in cases:
            summary = request_summary(case["payload"])
            print("\n" + "-" * 76)
            print(case["name"])
            print("-" * 76)
            print(f"payload_keys         : {summary['payload_keys']}")
            print(f"messages             : {summary['message_count']}")
            print(f"prompt_chars approx. : {summary['prompt_chars']}")
            print(f"tools                : {summary['tools_present']} ({summary['tools_count']})")
            print(f"tool_choice          : {summary['tool_choice_present']}")
            print(
                f"response_format       : {summary['response_format_present']} "
                f"({summary['response_format_type']})"
            )

            record: dict[str, Any] = {"test": case["name"], "request": summary}
            if args.dry_run:
                record["status"] = "DRY_RUN"
                report["results"].append(record)
                print("resultat             : DRY-RUN")
                continue

            started = time.monotonic()
            try:
                assert client is not None
                response = client.post(endpoint, headers=headers, json=case["payload"])
                duration = time.monotonic() - started
                try:
                    body: Any = response.json()
                except ValueError:
                    body = {"non_json_body": response.text[:4000]}
                passed, details = evaluate_response(case, response.status_code, body)
                print(f"HTTP status          : {response.status_code}")
                print(f"duree                : {duration:.2f}s")
                print(f"finish_reason        : {details.get('finish_reason')!r}")
                print(f"content_present      : {details.get('content_present')}")
                print(f"content_chars        : {details.get('content_chars')}")
                print(f"reasoning_present    : {details.get('reasoning_present')}")
                print(f"reasoning_chars      : {details.get('reasoning_chars')}")
                print(f"tool_calls_present   : {details.get('tool_calls_present')}")
                print(f"tool_calls_count     : {details.get('tool_calls_count')}")
                print(f"tool_names           : {details.get('tool_names')}")
                if "diagnostic" in details:
                    print(f"diagnostic           : {details['diagnostic']}")
                if response.status_code >= 400:
                    safe_error = redact(
                        json.dumps(body, ensure_ascii=False), sensitive_values
                    )[:4000]
                    print(f"provider_error       : {safe_error}")
                print(f"resultat             : {'PASS' if passed else 'FAIL'}")
                if not passed:
                    failures += 1
                record.update(
                    {
                        "status": "PASS" if passed else "FAIL",
                        "http_status": response.status_code,
                        "duration_seconds": round(duration, 3),
                        "response": details,
                    }
                )
                if response.status_code >= 400:
                    record["provider_error"] = redact(
                        json.dumps(body, ensure_ascii=False), sensitive_values
                    )[:4000]
            except Exception as exc:
                duration = time.monotonic() - started
                failures += 1
                safe_error = redact(
                    f"{type(exc).__name__}: {exc}", sensitive_values
                )
                print(f"duree                : {duration:.2f}s")
                print(f"transport_error      : {safe_error}")
                print("resultat             : FAIL")
                record.update(
                    {
                        "status": "FAIL",
                        "duration_seconds": round(duration, 3),
                        "transport_error": safe_error,
                    }
                )
            report["results"].append(record)
    finally:
        if client is not None:
            client.close()

    artifacts = ROOT / "artifacts" / "provider-doctor"
    artifacts.mkdir(parents=True, exist_ok=True)
    report_path = artifacts / f"provider-doctor-{datetime.now():%Y%m%d-%H%M%S}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n" + "=" * 76)
    print(f"rapport              : {report_path}")
    if args.dry_run:
        print("resume               : DRY-RUN, aucun appel reseau")
        return 0
    print(f"resume               : {len(cases) - failures} PASS / {failures} FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDiagnostic interrompu.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        # La redaction principale s'applique aux erreurs provider. Cette garde
        # evite aussi tout dump automatique de la configuration et de ses cles.
        print(f"ERREUR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
