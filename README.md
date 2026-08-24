"""Jira MCP -> LLM entreprise -> plan Alumnium mobile multi-device.

La connexion MCP et le tool-call reprennent la logique validee dans
jira_alumnium_runner.py. Ce module n'importe ni Selenium, ni GitLab, ni Jira
hors MCP. Il ne cree aucune session Appium.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI


TEST_TYPES = {
    "private_call",
    "video_call",
    "conference_call",
    "group_call",
    "incoming_call",
    "outgoing_call",
    "web_admin",
    "web_settings",
    "hybrid",
    "unknown",
}

MOBILE_TEST_TYPES = {
    "private_call",
    "video_call",
    "conference_call",
    "group_call",
    "incoming_call",
    "outgoing_call",
    "unknown",
}


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if hasattr(value, "model_dump"):
        return normalize(value.model_dump())
    if hasattr(value, "type") and hasattr(value, "text"):
        return {"type": getattr(value, "type"), "text": getattr(value, "text")}
    if hasattr(value, "__dict__"):
        return normalize(value.__dict__)
    return str(value)


def truncate(value: str, max_chars: int) -> str:
    text = value or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[TRUNCATED]..."


def extract_text(result: Any) -> str:
    value = normalize(result)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(extract_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in (
            "content",
            "text",
            "file_content",
            "body",
            "description",
            "data",
            "result",
        ):
            if key in value:
                extracted = extract_text(value[key])
                if extracted:
                    return extracted
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def extract_json_object(
    text: str,
    *,
    required_keys: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Extrait un objet JSON même après un bloc thought ou une fence Markdown.

    Les modèles reasoning peuvent produire du texte avant/après l'objet final.
    JSONDecoder.raw_decode permet de tester chaque accolade sans supprimer le
    contenu valide ni tenter d'interpréter du pseudo-JSON Python.
    """
    source = (text or "").strip().lstrip("\ufeff")
    if not source:
        return None

    try:
        direct = json.loads(source)
        if isinstance(direct, dict) and all(key in direct for key in required_keys):
            return direct
        if isinstance(direct, str):
            nested = extract_json_object(direct, required_keys=required_keys)
            if nested is not None:
                return nested
    except (json.JSONDecodeError, TypeError):
        pass

    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for position, character in enumerate(source):
        if character != "{":
            continue
        try:
            value, consumed = decoder.raw_decode(source[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and all(key in value for key in required_keys):
            candidates.append((position, consumed, value))

    if not candidates:
        return None

    # La réponse finale est normalement le dernier objet complet. En cas de
    # plusieurs candidats au même endroit, privilégier le plus grand.
    _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
    return selected


def completion_message_parts(message: Any) -> list[str]:
    """Normalise content et les champs reasoning non standard des gateways."""
    parts: list[str] = []
    for field_name in ("content", "reasoning_content", "reasoning"):
        value = getattr(message, field_name, None)
        if value is None:
            continue
        text = value.strip() if isinstance(value, str) else extract_text(value).strip()
        if text and text not in parts:
            parts.append(text)
    return parts


def completion_message_text(message: Any) -> str:
    parts = completion_message_parts(message)
    return "\n".join(parts)


def extract_message_json(
    message: Any, *, required_keys: tuple[str, ...]
) -> dict[str, Any] | None:
    # content contient normalement la réponse finale et doit gagner sur les
    # champs reasoning_content/reasoning propres à certaines gateways.
    for part in completion_message_parts(message):
        parsed = extract_json_object(part, required_keys=required_keys)
        if parsed is not None:
            return parsed
    return None


async def request_json_object(
    llm: AsyncOpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    required_keys: tuple[str, ...],
    label: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Demande un JSON puis répare une réponse reasoning non structurée."""
    response = await llm.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    message = response.choices[0].message
    first_text = completion_message_text(message)
    parsed = extract_message_json(message, required_keys=required_keys)
    if parsed is not None:
        if not first_text.lstrip().startswith("{"):
            print(
                f"[llm-json] {label}: JSON extrait apres un bloc de raisonnement.",
                flush=True,
            )
        return parsed

    finish_reason = getattr(response.choices[0], "finish_reason", None)
    print(
        f"[llm-json] {label}: aucun JSON exploitable "
        f"(finish_reason={finish_reason!r}); tentative de reformatage.",
        flush=True,
    )
    correction = (
        "Ta reponse precedente n'etait pas un objet JSON exploitable. "
        "Reprends la tache et renvoie maintenant UNIQUEMENT l'objet JSON final. "
        "Le premier caractere doit etre { et le dernier }. "
        "N'ajoute ni thought, ni explication, ni balise Markdown. "
        f"Cles obligatoires au niveau racine : {', '.join(required_keys)}."
    )
    repair_messages = [
        *messages,
        {"role": "assistant", "content": first_text[:16000]},
        {"role": "user", "content": correction},
    ]
    repair_arguments: dict[str, Any] = {
        "model": model,
        "messages": repair_messages,
        "temperature": 0.0,
        "max_tokens": max(max_tokens, 4096),
        "response_format": {"type": "json_object"},
    }
    try:
        repaired_response = await llm.chat.completions.create(**repair_arguments)
    except Exception as json_mode_error:
        # Certaines gateways OpenAI-compatible ne supportent pas JSON mode.
        print(
            f"[llm-json] {label}: JSON mode non supporte "
            f"({type(json_mode_error).__name__}); nouvelle tentative standard.",
            flush=True,
        )
        repair_arguments.pop("response_format", None)
        repaired_response = await llm.chat.completions.create(**repair_arguments)

    repaired_message = repaired_response.choices[0].message
    repaired_text = completion_message_text(repaired_message)
    repaired = extract_message_json(repaired_message, required_keys=required_keys)
    if repaired is not None:
        return repaired

    repaired_finish_reason = getattr(
        repaired_response.choices[0], "finish_reason", None
    )
    preview = repaired_text[:800].replace("\r", " ").replace("\n", " ")
    raise RuntimeError(
        f"{label}: aucun objet JSON apres deux tentatives "
        f"(finish_reason={repaired_finish_reason!r}). Apercu : {preview}"
    )


def find_tool_name(tool_names: list[str], preferred: list[str]) -> str | None:
    for preferred_name in preferred:
        if preferred_name in tool_names:
            return preferred_name
    lowered = [name.lower() for name in tool_names]
    for preferred_name in preferred:
        token = preferred_name.lower()
        for index, lowered_name in enumerate(lowered):
            if token in lowered_name:
                return tool_names[index]
    return None


def mcp_tools_to_openai(tools_response: Any) -> list[dict[str, Any]]:
    tools = getattr(tools_response, "tools", tools_response)
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema
                or {"type": "object", "properties": {}, "additionalProperties": True},
            },
        }
        for tool in tools
    ]


async def run_forced_tool_call(
    llm: AsyncOpenAI,
    mcp: ClientSession,
    openai_tools: list[dict[str, Any]],
    expected_tool: str,
    messages: list[dict[str, str]],
    model: str,
) -> Any:
    response = await llm.chat.completions.create(
        model=model,
        messages=messages,
        tools=openai_tools,
        tool_choice="auto",
        temperature=0.0,
    )
    message = response.choices[0].message
    if not message.tool_calls:
        raise RuntimeError(f"Aucun tool_call Jira genere. Message: {message.content}")

    tool_call = message.tool_calls[0]
    tool_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments or "{}")
    if tool_name != expected_tool:
        raise RuntimeError(
            f"Tool Jira inattendu : {tool_name} (attendu : {expected_tool})"
        )

    print(f"[jira-mcp] TOOL_CALL {tool_name} args={arguments}", flush=True)
    return await mcp.call_tool(tool_name, arguments)


async def jira_fetch_and_summarize(
    llm: AsyncOpenAI,
    *,
    jira_mcp_url: str,
    jira_key: str,
    model: str,
    max_chars: int,
) -> dict[str, Any]:
    async with streamable_http_client(jira_mcp_url) as streams:
        if not isinstance(streams, tuple) or len(streams) < 2:
            raise RuntimeError(f"Transport MCP inattendu : {streams!r}")
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as jira:
            await jira.initialize()
            tools_response = await jira.list_tools()
            openai_tools = mcp_tools_to_openai(tools_response)
            tool_names = [tool["function"]["name"] for tool in openai_tools]
            issue_tool = find_tool_name(
                tool_names,
                preferred=[
                    "get_issue",
                    "jira_get_issue",
                    "get_jira_issue",
                    "get_issue_by_key",
                    "issue_get",
                ],
            )
            if not issue_tool:
                raise RuntimeError(
                    "Aucun tool Jira de lecture de ticket trouve. "
                    f"Tools disponibles : {tool_names[:40]}"
                )

            issue_raw = await run_forced_tool_call(
                llm,
                jira,
                openai_tools,
                issue_tool,
                [
                    {
                        "role": "system",
                        "content": (
                            f"Tu dois appeler EXACTEMENT le tool {issue_tool} "
                            "pour lire un ticket Jira."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Recupere le ticket Jira '{jira_key}'. Utilise "
                            "l'argument exact attendu par le tool, par exemple "
                            "key ou issue_key."
                        ),
                    },
                ],
                model,
            )

    issue_text = truncate(extract_text(issue_raw), max_chars)
    response = await llm.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es QA Automation. Resume le ticket Jira pour produire "
                    "un test mobile multi-device. Retourne strictement les "
                    "sections suivantes : Titre, Objectif, Pre-conditions, "
                    "Roles/appareils, Etapes Given/When/Then, Donnees, "
                    "Resultats attendus, Points d'attention."
                ),
            },
            {
                "role": "user",
                "content": f"TICKET_KEY: {jira_key}\n\nCONTENU:\n{issue_text}",
            },
        ],
        temperature=0.2,
        max_tokens=1200,
    )
    summary = (response.choices[0].message.content or "").strip()
    if not summary:
        raise RuntimeError("Le modele a retourne un resume Jira vide.")
    return {
        "jira_key": jira_key,
        "issue_tool": issue_tool,
        "issue_summary": summary,
    }


async def classify_jira_test_type(
    llm: AsyncOpenAI, *, model: str, jira_summary: str
) -> dict[str, Any]:
    try:
        classification = await request_json_object(
            llm,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classe un ticket de test dans une seule valeur : "
                        "private_call, video_call, conference_call, group_call, "
                        "incoming_call, outgoing_call, web_admin, web_settings, "
                        "hybrid ou unknown. Reponds uniquement avec un JSON valide "
                        '{"test_type":"...","confidence":0.0,"reason":"..."}.'
                    ),
                },
                {"role": "user", "content": f"Resume Jira:\n{jira_summary}"},
            ],
            required_keys=("test_type",),
            label="Classification Jira",
            # Les modeles reasoning peuvent consommer une part importante de
            # la sortie avant de produire le petit objet final.
            max_tokens=1200,
        )
    except Exception as exc:
        # Une classification illisible ne doit pas faire perdre le diagnostic
        # du planner. Le type unknown reste admis pour un scénario mobile.
        classification = {
            "test_type": "unknown",
            "confidence": 0.0,
            "reason": f"Classification JSON indisponible : {exc}",
        }
    if classification.get("test_type") not in TEST_TYPES:
        classification["test_type"] = "unknown"
    try:
        classification["confidence"] = float(
            classification.get("confidence", 0.0)
        )
    except (TypeError, ValueError):
        classification["confidence"] = 0.0
    classification["reason"] = str(classification.get("reason", ""))
    return classification


def validate_multidevice_plan(
    plan: dict[str, Any], available_roles: list[str]
) -> dict[str, Any]:
    if plan.get("target") != "mobile":
        raise RuntimeError(
            f"Ce bundle accepte uniquement target='mobile', recu : {plan.get('target')!r}"
        )

    role_set = set(available_roles)

    def validate_step(step: Any, location: str) -> dict[str, Any]:
        if not isinstance(step, dict):
            raise RuntimeError(f"{location} doit etre un objet JSON.")
        role = str(step.get("role", "")).strip()
        kind = str(step.get("type", "")).strip().lower()
        instruction = str(step.get("instruction", "")).strip()
        if role not in role_set:
            raise RuntimeError(
                f"{location}: role {role!r} absent de {sorted(role_set)}."
            )
        if kind not in {"do", "check", "wait-check"}:
            raise RuntimeError(
                f"{location}: type {kind!r} non supporte (do/check/wait-check)."
            )
        if not instruction:
            raise RuntimeError(f"{location}: instruction vide.")
        normalized_step: dict[str, Any] = {
            "role": role,
            "type": kind,
            "instruction": instruction,
        }
        if kind == "wait-check":
            for option in ("timeout_seconds", "interval_seconds"):
                if option in step:
                    normalized_step[option] = float(step[option])
        return normalized_step

    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RuntimeError("Le plan Jira ne contient aucune etape executable.")

    normalized_steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw_steps, 1):
        if isinstance(item, dict) and "parallel" in item:
            parallel = item["parallel"]
            if not isinstance(parallel, list) or not parallel:
                raise RuntimeError(f"steps[{index}].parallel est vide ou invalide.")
            normalized_steps.append(
                {
                    "parallel": [
                        validate_step(step, f"steps[{index}].parallel[{minor}]")
                        for minor, step in enumerate(parallel, 1)
                    ]
                }
            )
        else:
            normalized_steps.append(validate_step(item, f"steps[{index}]"))

    missing_data = plan.get("missing_data", [])
    if not isinstance(missing_data, list):
        missing_data = [str(missing_data)]
    return {
        "target": "mobile",
        "goal": str(plan.get("goal", "")).strip(),
        "required_roles": sorted(
            {
                step["role"]
                for item in normalized_steps
                for step in item.get("parallel", [item])
            }
        ),
        "missing_data": [str(item) for item in missing_data if str(item).strip()],
        "steps": normalized_steps,
    }


async def build_multidevice_plan(
    llm: AsyncOpenAI,
    *,
    model: str,
    jira_summary: str,
    jira_classification: dict[str, Any],
    available_roles: list[str],
) -> dict[str, Any]:
    roles_json = json.dumps(available_roles, ensure_ascii=False)
    system = f"""Tu es un planner QA specialise dans Alumnium sur plusieurs telephones Android.
Transforme le ticket Jira en plan mobile executable et fidele.

ROLES AUTORISES : {roles_json}

REGLES :
- N'invente aucune etape, identifiant, numero, compte, mot de passe ou donnee.
- Si une donnee obligatoire manque, place-la dans missing_data.
- Chaque etape doit utiliser exactement un role autorise.
- Utilise "do" pour une action, "check" pour une assertion immediate et
  "wait-check" lorsqu'un autre telephone doit attendre un evenement, par
  exemple un appel entrant.
- Utilise un bloc parallel uniquement pour des operations reellement simultanees.
- Les instructions sont en langage naturel pour al.do() ou al.check().
- Aucun XPath, CSS, Appium ID ou locator technique.
- target doit toujours etre "mobile".
- Reponds uniquement avec du JSON valide, sans markdown.

FORMAT :
{{
  "target": "mobile",
  "goal": "...",
  "missing_data": [],
  "steps": [
    {{"role":"caller","type":"do","instruction":"..."}},
    {{"parallel":[
      {{"role":"caller","type":"check","instruction":"..."}},
      {{"role":"callee","type":"wait-check","instruction":"...","timeout_seconds":30}}
    ]}}
  ]
}}"""
    payload = {
        "jira_summary": jira_summary,
        "jira_classification": jira_classification,
        "available_roles": available_roles,
    }
    raw_plan = await request_json_object(
        llm,
        model=model,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ],
        required_keys=("target", "steps"),
        label="Plan multi-device",
        # 2500 etait trop court pour certains modeles Gemma reasoning : le
        # raisonnement peut preceder le JSON et epuiser le budget de sortie.
        max_tokens=6000,
    )
    return validate_multidevice_plan(raw_plan, available_roles)


async def fetch_jira_and_build_plan(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    proxy_url: str | None,
    default_headers: dict[str, str] | None,
    verify_tls: bool,
    timeout: float,
    jira_mcp_url: str,
    jira_key: str,
    max_chars: int,
    available_roles: list[str],
) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY manquant dans qa_config.py.")
    if not model:
        raise RuntimeError("OPENAI_MODEL manquant dans qa_config.py.")
    if not jira_mcp_url or not jira_key:
        raise RuntimeError("JIRA_MCP_URL / JIRA_KEY manquants dans qa_config.py.")
    if len(available_roles) < 2:
        raise RuntimeError("Le planner multi-device exige au moins deux roles.")

    async with httpx.AsyncClient(
        proxy=proxy_url,
        verify=verify_tls,
        follow_redirects=False,
        timeout=timeout,
    ) as http_client:
        client_arguments: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "http_client": http_client,
        }
        if default_headers:
            client_arguments["default_headers"] = default_headers
        llm = AsyncOpenAI(**client_arguments)

        jira = await jira_fetch_and_summarize(
            llm,
            jira_mcp_url=jira_mcp_url,
            jira_key=jira_key,
            model=model,
            max_chars=max_chars,
        )
        classification = await classify_jira_test_type(
            llm,
            model=model,
            jira_summary=jira["issue_summary"],
        )
        if classification["test_type"] not in MOBILE_TEST_TYPES:
            raise RuntimeError(
                "Le ticket est classe comme non mobile ou hybride "
                f"({classification['test_type']}). Ce bundle physique n'execute "
                "que les plans mobiles."
            )
        plan = await build_multidevice_plan(
            llm,
            model=model,
            jira_summary=jira["issue_summary"],
            jira_classification=classification,
            available_roles=available_roles,
        )
        return {
            **jira,
            "classification": classification,
            "plan": plan,
        }
