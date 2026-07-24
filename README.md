#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
import urllib3

from datamanager import DataManager


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ===========================================================================
# CONFIGURATION
# ===========================================================================

# ---------------------------------------------------------------------------
# JIRA / XRAY
# ---------------------------------------------------------------------------

JIRA_URL = ""
JIRA_USER = ""
JIRA_TOKEN = ""

# Laisse vide si Jira n'utilise pas de proxy.
JIRA_PROXY_URL = ""

# Test Plan Xray ciblé.
TEST_PLAN_KEY = ""

# Champ Xray contenant les statistiques consolidées.
XRAY_STATS_CUSTOM_FIELD = "customfield_11527"


# ---------------------------------------------------------------------------
# CONFLUENCE
# ---------------------------------------------------------------------------

CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""

# Laisse vide si Confluence n'utilise pas de proxy.
CONFLUENCE_PROXY_URL = ""

CONFLUENCE_PAGE_TITLE = "Dashboard night run automation"
CONFLUENCE_SPACE_KEY = "TEI"

# La même pièce jointe est mise à jour à chaque lancement.
CSV_FILENAME = "night_run_dashboard.csv"

# Copie locale créée à chaque lancement.
LOCAL_CSV_PATH = Path(CSV_FILENAME)


# ---------------------------------------------------------------------------
# HISTORIQUE
# ---------------------------------------------------------------------------

# Nombre maximal de journées conservées pour le Test Plan et les
# Test Executions.
MAX_HISTORY_DAYS = 7

# Décalage utilisé uniquement pour les tests :
# 0 = aujourd'hui, 1 = J+1, 2 = J+2...
TEST_DAY_OFFSET = 0

# Séparateur adapté à Excel et aux macros CSV en environnement français.
CSV_DELIMITER = ";"

# Les pourcentages restent des nombres bruts dans le CSV :
# 96.88 et non "96.88 %".
CSV_FLOAT_DECIMALS = 2


# ---------------------------------------------------------------------------
# COMPOSANTS / DATAMANAGER
#
# Les composants sont également stockés dans le CSV long avec :
# Niveau = Composant
#
# Leur Date reste vide, car ils ne constituent pas un historique journalier.
# À chaque lancement, les anciennes lignes Composant sont remplacées.
# ---------------------------------------------------------------------------

INCLUDE_COMPONENTS_IN_CSV = True
COMPONENTS_DATAFILE = "FROM_SETTINGS_FILE"

COMPONENT_SETTINGS = [
    {
        "name": "Toto composant",
        "alias": "TOTO",
        "url_key": "url",
    },
    {
        "name": "Composant 2",
        "alias": "COMPONENT_2",
        "url_key": "url",
    },
    {
        "name": "Composant 3",
        "alias": "COMPONENT_3",
        "url_key": "url",
    },
    {
        "name": "Composant 4",
        "alias": "COMPONENT_4",
        "url_key": "url",
    },
    {
        "name": "Composant 5",
        "alias": "COMPONENT_5",
        "url_key": "url",
    },
    {
        "name": "Composant 6",
        "alias": "COMPONENT_6",
        "url_key": "url",
    },
]


# ===========================================================================
# FORMAT LONG DU CSV
# ===========================================================================

DATE_COLUMN = "Date"
UPDATE_TIME_COLUMN = "Heure de mise à jour"
LEVEL_COLUMN = "Niveau"
NAME_COLUMN = "Nom"
KEY_COLUMN = "Clé"
URL_COLUMN = "URL"
TOTAL_COLUMN = "Total"
PASS_COLUMN = "PASS"
FAIL_COLUMN = "FAIL"
TODO_COLUMN = "TODO"
SUCCESS_RATE_COLUMN = "Réussite (%)"

CSV_HEADERS = [
    DATE_COLUMN,
    UPDATE_TIME_COLUMN,
    LEVEL_COLUMN,
    NAME_COLUMN,
    KEY_COLUMN,
    URL_COLUMN,
    TOTAL_COLUMN,
    PASS_COLUMN,
    FAIL_COLUMN,
    TODO_COLUMN,
    SUCCESS_RATE_COLUMN,
]

LEVEL_TEST_PLAN = "Test Plan"
LEVEL_TEST_EXECUTION = "Test Execution"
LEVEL_COMPONENT = "Composant"

ISSUE_KEY_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]*-\d+$",
    re.IGNORECASE,
)


# ===========================================================================
# HTTP
# ===========================================================================

def build_proxies(proxy_url: str) -> dict[str, str] | None:
    if not proxy_url:
        return None

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def jira_get(
    url: str,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    response = requests.get(
        url,
        params=params,
        auth=(JIRA_USER, JIRA_TOKEN),
        proxies=build_proxies(JIRA_PROXY_URL),
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    return response


def make_confluence_session() -> requests.Session:
    """
    Ne définit pas Content-Type globalement.

    requests construira automatiquement multipart/form-data lors de
    l'envoi de la pièce jointe.
    """

    session = requests.Session()
    session.verify = False

    session.proxies.update(
        build_proxies(CONFLUENCE_PROXY_URL) or {}
    )

    session.headers.update(
        {
            "Authorization": f"Bearer {CONFLUENCE_TOKEN}",
            "Accept": "application/json",
        }
    )

    return session


# ===========================================================================
# DATAMANAGER / COMPOSANTS
# ===========================================================================

def get_component_url(
    obj_alias: str,
    url_key: str,
    datafile: str = COMPONENTS_DATAFILE,
) -> str:
    """
    Reprend la logique utilisée dans ton module Keycloak :

        DataManager(datafile=datafile, actor=obj_alias)
        returnExcelDict(obj_alias)
    """

    data_manager = DataManager(
        datafile=datafile,
        actor=obj_alias,
    )

    excel_dict = data_manager.returnExcelDict(
        obj_alias
    )

    if not isinstance(excel_dict, dict) or not excel_dict:
        raise ValueError(
            f"Aucune donnée Excel trouvée pour l'alias "
            f"'{obj_alias}'."
        )

    if url_key not in excel_dict:
        available_keys = ", ".join(
            sorted(str(key) for key in excel_dict)
        )

        raise KeyError(
            f"La clé '{url_key}' est absente pour l'alias "
            f"'{obj_alias}'. Clés disponibles : {available_keys}"
        )

    component_url = str(
        excel_dict[url_key]
    ).strip()

    if not component_url:
        raise ValueError(
            f"L'URL est vide pour l'alias '{obj_alias}' "
            f"et la clé '{url_key}'."
        )

    return component_url


def build_component_rows() -> list[dict[str, str]]:
    if not INCLUDE_COMPONENTS_IN_CSV:
        return []

    rows = []

    for setting in COMPONENT_SETTINGS:
        component_name = str(
            setting["name"]
        ).strip()

        component_alias = str(
            setting["alias"]
        ).strip()

        url_key = str(
            setting["url_key"]
        ).strip()

        print(
            f"🔎 DataManager : {component_name} "
            f"(alias={component_alias}, clé={url_key})"
        )

        component_url = get_component_url(
            obj_alias=component_alias,
            url_key=url_key,
        )

        rows.append(
            empty_long_row(
                level=LEVEL_COMPONENT,
                name=component_name,
                key=component_alias,
                url=component_url,
            )
        )

    return rows


# ===========================================================================
# XRAY - STATISTIQUES
# ===========================================================================

def parse_xray_stats(
    stats_data: dict[str, Any] | None,
) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}

    if not stats_data:
        return stats

    for status in stats_data.get("statuses", []):
        status_name = str(
            status.get("name", "")
        ).upper().strip()

        if not status_name:
            continue

        stats[status_name] = {
            "count": float(
                status.get("statusCount", 0) or 0
            ),
            "percent": float(
                status.get("statusPercent", 0) or 0
            ),
        }

    return stats


def normalize_status_name(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("status")
            or value.get("key")
        )

    return str(value or "UNKNOWN").upper().strip()


def build_metrics(
    issue_key: str,
    summary: str,
    stats: dict[str, dict[str, float]],
) -> dict[str, Any]:
    counts = {
        status_name: int(
            status_value.get("count", 0)
        )
        for status_name, status_value in stats.items()
    }

    pass_count = counts.get("PASS", 0)
    fail_count = counts.get("FAIL", 0)

    todo_count = (
        counts.get("TODO", 0)
        + counts.get("TO DO", 0)
        + counts.get("NOT EXECUTED", 0)
    )

    # Le total garde également les éventuels statuts Xray personnalisés.
    total_count = sum(counts.values())

    completed_count = pass_count + fail_count

    success_rate = (
        round(
            pass_count / completed_count * 100,
            CSV_FLOAT_DECIMALS,
        )
        if completed_count
        else 0.0
    )

    return {
        "key": issue_key,
        "summary": summary,
        "total": total_count,
        "pass": pass_count,
        "fail": fail_count,
        "todo": todo_count,
        "success_rate": success_rate,
    }


def get_issue_metrics_from_custom_field(
    issue_key: str,
) -> dict[str, Any] | None:
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}"

    response = jira_get(
        url,
        params={
            "fields": (
                f"summary,{XRAY_STATS_CUSTOM_FIELD}"
            ),
        },
    )

    issue = response.json()
    fields = issue.get("fields", {})

    summary = str(
        fields.get("summary", issue_key)
    ).strip()

    stats = parse_xray_stats(
        fields.get(XRAY_STATS_CUSTOM_FIELD)
    )

    if not stats:
        return None

    return build_metrics(
        issue_key=issue_key,
        summary=summary,
        stats=stats,
    )


def get_test_runs(
    test_execution_key: str,
) -> list[dict[str, Any]]:
    """
    Lit les Test Runs d'une Test Execution.
    """

    url = (
        f"{JIRA_URL}/rest/raven/1.0/api/testexec/"
        f"{test_execution_key}/test"
    )

    results: list[dict[str, Any]] = []
    start = 0
    limit = 100

    while True:
        response = jira_get(
            url,
            params={
                "start": start,
                "limit": limit,
            },
        )

        payload = response.json()

        if isinstance(payload, list):
            current_results = payload
            total = len(payload)

        elif isinstance(payload, dict):
            current_results = (
                payload.get("results")
                or payload.get("tests")
                or payload.get("entries")
                or payload.get("values")
                or []
            )

            total = int(
                payload.get(
                    "total",
                    len(current_results),
                )
            )

        else:
            current_results = []
            total = 0

        current_results = [
            result
            for result in current_results
            if isinstance(result, dict)
        ]

        results.extend(
            current_results
        )

        if not current_results:
            break

        start += len(current_results)

        if start >= total:
            break

        if len(current_results) < limit:
            break

    return results


def get_test_execution_metrics_from_runs(
    test_execution_key: str,
) -> dict[str, Any]:
    issue_url = (
        f"{JIRA_URL}/rest/api/2/issue/"
        f"{test_execution_key}"
    )

    issue_response = jira_get(
        issue_url,
        params={"fields": "summary"},
    )

    summary = str(
        issue_response.json()
        .get("fields", {})
        .get("summary", test_execution_key)
    ).strip()

    status_counts: dict[str, int] = {}

    for test_run in get_test_runs(
        test_execution_key
    ):
        status = normalize_status_name(
            test_run.get("status")
            or test_run.get("testRunStatus")
            or test_run.get("executionStatus")
        )

        status_counts[status] = (
            status_counts.get(status, 0) + 1
        )

    stats = {
        status_name: {
            "count": count,
            "percent": 0,
        }
        for status_name, count in status_counts.items()
    }

    return build_metrics(
        issue_key=test_execution_key,
        summary=summary,
        stats=stats,
    )


def get_test_plan_metrics() -> dict[str, Any]:
    print(
        f"🔎 Statistiques du Test Plan "
        f"{TEST_PLAN_KEY}"
    )

    metrics = get_issue_metrics_from_custom_field(
        TEST_PLAN_KEY
    )

    if metrics is None:
        raise ValueError(
            f"Le champ {XRAY_STATS_CUSTOM_FIELD} est absent "
            f"ou vide sur le Test Plan {TEST_PLAN_KEY}."
        )

    return metrics


def extract_test_execution_keys(
    payload: Any,
) -> list[str]:
    if isinstance(payload, dict):
        for container_name in (
            "testExecutions",
            "results",
            "issues",
            "values",
            "entries",
        ):
            if container_name in payload:
                payload = payload[container_name]
                break
        else:
            payload = [payload]

    if not isinstance(payload, list):
        raise ValueError(
            "Format Xray inattendu pour les Test Executions."
        )

    keys: list[str] = []

    for item in payload:
        candidate = None

        if isinstance(item, str):
            candidate = item

        elif isinstance(item, dict):
            candidate = (
                item.get("key")
                or item.get("issueKey")
                or item.get("testExecutionKey")
            )

        if (
            candidate
            and ISSUE_KEY_PATTERN.match(
                str(candidate)
            )
        ):
            keys.append(
                str(candidate).upper()
            )

    return list(
        dict.fromkeys(keys)
    )


def get_test_execution_keys() -> list[str]:
    url = (
        f"{JIRA_URL}/rest/raven/1.0/api/testplan/"
        f"{TEST_PLAN_KEY}/testexecution"
    )

    print(
        f"🔎 Test Executions liées au Test Plan "
        f"{TEST_PLAN_KEY}"
    )

    response = jira_get(url)

    keys = extract_test_execution_keys(
        response.json()
    )

    if not keys:
        raise ValueError(
            f"Aucune Test Execution trouvée pour "
            f"{TEST_PLAN_KEY}."
        )

    print(
        f"✅ {len(keys)} Test Execution(s) : "
        + ", ".join(keys)
    )

    return keys


def get_all_test_execution_metrics() -> list[dict[str, Any]]:
    results = []

    for test_execution_key in get_test_execution_keys():
        metrics = get_issue_metrics_from_custom_field(
            test_execution_key
        )

        if metrics is None:
            print(
                f"⚠️ Champ Xray absent sur "
                f"{test_execution_key}. "
                "Lecture des Test Runs."
            )

            metrics = (
                get_test_execution_metrics_from_runs(
                    test_execution_key
                )
            )

        results.append(
            metrics
        )

        print(
            f"📊 {metrics['summary']} : "
            f"Total={metrics['total']} | "
            f"PASS={metrics['pass']} | "
            f"FAIL={metrics['fail']} | "
            f"TODO={metrics['todo']} | "
            f"Réussite={metrics['success_rate']:.2f}%"
        )

    return sorted(
        results,
        key=lambda item: item["summary"].lower(),
    )


# ===========================================================================
# CONSTRUCTION DES LIGNES LONGUES
# ===========================================================================

def format_float(value: float) -> str:
    return f"{float(value):.{CSV_FLOAT_DECIMALS}f}"


def jira_issue_url(issue_key: str) -> str:
    return (
        f"{JIRA_URL.rstrip('/')}/browse/"
        f"{issue_key}"
    )


def empty_long_row(
    level: str = "",
    name: str = "",
    key: str = "",
    url: str = "",
) -> dict[str, str]:
    return {
        DATE_COLUMN: "",
        UPDATE_TIME_COLUMN: "",
        LEVEL_COLUMN: level,
        NAME_COLUMN: name,
        KEY_COLUMN: key,
        URL_COLUMN: url,
        TOTAL_COLUMN: "",
        PASS_COLUMN: "",
        FAIL_COLUMN: "",
        TODO_COLUMN: "",
        SUCCESS_RATE_COLUMN: "",
    }


def metrics_to_long_row(
    metrics: dict[str, Any],
    level: str,
    snapshot_datetime: datetime,
) -> dict[str, str]:
    row = empty_long_row(
        level=level,
        name=str(metrics["summary"]),
        key=str(metrics["key"]),
        url=jira_issue_url(
            str(metrics["key"])
        ),
    )

    row[DATE_COLUMN] = (
        snapshot_datetime.strftime(
            "%d/%m/%Y"
        )
    )

    row[UPDATE_TIME_COLUMN] = (
        snapshot_datetime.strftime(
            "%H:%M:%S"
        )
    )

    row[TOTAL_COLUMN] = str(
        metrics["total"]
    )
    row[PASS_COLUMN] = str(
        metrics["pass"]
    )
    row[FAIL_COLUMN] = str(
        metrics["fail"]
    )
    row[TODO_COLUMN] = str(
        metrics["todo"]
    )
    row[SUCCESS_RATE_COLUMN] = format_float(
        metrics["success_rate"]
    )

    return row


def build_snapshot_rows(
    test_plan_metrics: dict[str, Any],
    execution_metrics: list[dict[str, Any]],
    snapshot_datetime: datetime,
) -> list[dict[str, str]]:
    rows = [
        metrics_to_long_row(
            metrics=test_plan_metrics,
            level=LEVEL_TEST_PLAN,
            snapshot_datetime=snapshot_datetime,
        )
    ]

    rows.extend(
        metrics_to_long_row(
            metrics=metrics,
            level=LEVEL_TEST_EXECUTION,
            snapshot_datetime=snapshot_datetime,
        )
        for metrics in execution_metrics
    )

    return rows


# ===========================================================================
# CONFLUENCE - PAGE ET PIÈCE JOINTE
# ===========================================================================

def find_page_id(
    session: requests.Session,
) -> str:
    cql = (
        f'title ~ "{CONFLUENCE_PAGE_TITLE}" '
        f'AND space = "{CONFLUENCE_SPACE_KEY}"'
    )

    url = (
        f"{CONFLUENCE_URL}/rest/api/search"
    )

    response = session.get(
        url,
        params={
            "cql": cql,
            "start": 0,
            "limit": 10,
        },
        timeout=30,
    )
    response.raise_for_status()

    results = response.json().get(
        "results",
        [],
    )

    if not results:
        raise ValueError(
            f"Page Confluence "
            f"'{CONFLUENCE_PAGE_TITLE}' introuvable."
        )

    page_id = str(
        results[0]["content"]["id"]
    )

    print(
        f"✅ Page Confluence trouvée : "
        f"{page_id}"
    )

    return page_id


def find_csv_attachment(
    session: requests.Session,
    page_id: str,
) -> dict[str, Any] | None:
    url = (
        f"{CONFLUENCE_URL}/rest/api/content/"
        f"{page_id}/child/attachment"
    )

    response = session.get(
        url,
        params={
            "filename": CSV_FILENAME,
            "limit": 200,
            "expand": "version",
        },
        timeout=30,
    )
    response.raise_for_status()

    for attachment in response.json().get(
        "results",
        [],
    ):
        if attachment.get("title") == CSV_FILENAME:
            return attachment

    return None


def make_absolute_confluence_url(
    link: str,
) -> str:
    """
    Préserve le context path Confluence.

    Exemple :
        CONFLUENCE_URL = https://serveur/confluence
        link = /download/attachments/123/fichier.csv

    Résultat :
        https://serveur/confluence/download/attachments/123/fichier.csv
    """

    if link.startswith(
        ("http://", "https://")
    ):
        return link

    parsed_base = urlparse(
        CONFLUENCE_URL.rstrip("/")
    )

    origin = (
        f"{parsed_base.scheme}://"
        f"{parsed_base.netloc}"
    )

    context_path = parsed_base.path.rstrip("/")
    normalized_link = "/" + link.lstrip("/")

    if (
        context_path
        and (
            normalized_link == context_path
            or normalized_link.startswith(
                context_path + "/"
            )
        )
    ):
        return origin + normalized_link

    return (
        origin
        + context_path
        + normalized_link
    )


def download_attachment_content(
    session: requests.Session,
    page_id: str,
    attachment: dict[str, Any],
) -> bytes:
    download_link = (
        attachment.get("_links", {})
        .get("download")
    )

    if download_link:
        download_url = make_absolute_confluence_url(
            download_link
        )
    else:
        download_url = (
            f"{CONFLUENCE_URL.rstrip('/')}"
            f"/download/attachments/"
            f"{page_id}/{quote(CSV_FILENAME)}"
        )

    response = session.get(
        download_url,
        timeout=30,
    )
    response.raise_for_status()

    return response.content


def create_csv_attachment(
    session: requests.Session,
    page_id: str,
    csv_content: bytes,
) -> None:
    url = (
        f"{CONFLUENCE_URL}/rest/api/content/"
        f"{page_id}/child/attachment"
    )

    response = session.post(
        url,
        headers={
            "X-Atlassian-Token": "no-check",
        },
        files={
            "file": (
                CSV_FILENAME,
                io.BytesIO(csv_content),
                "text/csv",
            )
        },
        data={
            "comment": (
                "Création automatique du CSV long "
                "du dashboard night run"
            )
        },
        timeout=60,
    )
    response.raise_for_status()

    print(
        f"✅ Pièce jointe créée : "
        f"{CSV_FILENAME}"
    )


def update_csv_attachment(
    session: requests.Session,
    page_id: str,
    attachment_id: str,
    csv_content: bytes,
) -> None:
    url = (
        f"{CONFLUENCE_URL}/rest/api/content/"
        f"{page_id}/child/attachment/"
        f"{attachment_id}/data"
    )

    response = session.post(
        url,
        headers={
            "X-Atlassian-Token": "no-check",
        },
        files={
            "file": (
                CSV_FILENAME,
                io.BytesIO(csv_content),
                "text/csv",
            )
        },
        data={
            "comment": (
                "Mise à jour automatique du CSV long "
                "du dashboard night run"
            )
        },
        timeout=60,
    )
    response.raise_for_status()

    print(
        f"✅ Nouvelle version de la pièce jointe : "
        f"{CSV_FILENAME}"
    )


# ===========================================================================
# LECTURE / MIGRATION DU CSV
# ===========================================================================

def read_csv_content(
    csv_content: bytes | None,
) -> tuple[list[str], list[dict[str, str]]]:
    if not csv_content:
        return [], []

    text = csv_content.decode(
        "utf-8-sig"
    )

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter=CSV_DELIMITER,
    )

    if not reader.fieldnames:
        return [], []

    rows = [
        {
            str(key): (
                "" if value is None else str(value)
            )
            for key, value in row.items()
        }
        for row in reader
    ]

    return list(reader.fieldnames), rows


def is_long_format(
    headers: list[str],
) -> bool:
    return {
        DATE_COLUMN,
        LEVEL_COLUMN,
        NAME_COLUMN,
        TOTAL_COLUMN,
        PASS_COLUMN,
        FAIL_COLUMN,
        TODO_COLUMN,
        SUCCESS_RATE_COLUMN,
    }.issubset(set(headers))


def normalize_long_row(
    row: dict[str, str],
) -> dict[str, str]:
    return {
        header: str(
            row.get(header, "")
        ).strip()
        for header in CSV_HEADERS
    }


def migrate_wide_csv_to_long(
    headers: list[str],
    wide_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """
    Convertit automatiquement l'ancien CSV large vers le nouveau format long.

    Ancien exemple :
        Date;Global - PASS;Web - PASS;Web - Réussite (%)

    Nouveau :
        une ligne Test Plan + une ligne par Test Execution et par date.
    """

    if not wide_rows:
        return []

    print(
        "🔄 Ancien format large détecté : "
        "migration automatique vers le format long."
    )

    execution_names = []

    for header in headers:
        suffix = " - Total"

        if (
            header.endswith(suffix)
            and header != "Global - Total"
        ):
            execution_name = header[
                :-len(suffix)
            ]

            expected_columns = {
                f"{execution_name} - Total",
                f"{execution_name} - PASS",
                f"{execution_name} - FAIL",
                f"{execution_name} - TODO",
                f"{execution_name} - Réussite (%)",
            }

            if expected_columns.issubset(
                set(headers)
            ):
                execution_names.append(
                    execution_name
                )

    long_rows = []

    for wide_row in wide_rows:
        date_value = str(
            wide_row.get("Date", "")
        ).strip()

        if not date_value:
            continue

        update_time = str(
            wide_row.get(
                "Heure de mise à jour",
                "",
            )
        ).strip()

        test_plan_key = str(
            wide_row.get(
                "Test Plan - Clé",
                TEST_PLAN_KEY,
            )
        ).strip()

        test_plan_name = str(
            wide_row.get(
                "Test Plan - Nom",
                TEST_PLAN_KEY,
            )
        ).strip()

        plan_row = empty_long_row(
            level=LEVEL_TEST_PLAN,
            name=test_plan_name,
            key=test_plan_key,
            url=(
                jira_issue_url(test_plan_key)
                if test_plan_key
                else ""
            ),
        )

        plan_row.update(
            {
                DATE_COLUMN: date_value,
                UPDATE_TIME_COLUMN: update_time,
                TOTAL_COLUMN: str(
                    wide_row.get(
                        "Global - Total",
                        "",
                    )
                ).strip(),
                PASS_COLUMN: str(
                    wide_row.get(
                        "Global - PASS",
                        "",
                    )
                ).strip(),
                FAIL_COLUMN: str(
                    wide_row.get(
                        "Global - FAIL",
                        "",
                    )
                ).strip(),
                TODO_COLUMN: str(
                    wide_row.get(
                        "Global - TODO",
                        "",
                    )
                ).strip(),
                SUCCESS_RATE_COLUMN: str(
                    wide_row.get(
                        "Global - Réussite (%)",
                        "",
                    )
                ).strip(),
            }
        )

        long_rows.append(
            plan_row
        )

        for execution_name in execution_names:
            total_value = str(
                wide_row.get(
                    f"{execution_name} - Total",
                    "",
                )
            ).strip()

            pass_value = str(
                wide_row.get(
                    f"{execution_name} - PASS",
                    "",
                )
            ).strip()

            fail_value = str(
                wide_row.get(
                    f"{execution_name} - FAIL",
                    "",
                )
            ).strip()

            todo_value = str(
                wide_row.get(
                    f"{execution_name} - TODO",
                    "",
                )
            ).strip()

            rate_value = str(
                wide_row.get(
                    f"{execution_name} - Réussite (%)",
                    "",
                )
            ).strip()

            if not any(
                (
                    total_value,
                    pass_value,
                    fail_value,
                    todo_value,
                    rate_value,
                )
            ):
                continue

            execution_row = empty_long_row(
                level=LEVEL_TEST_EXECUTION,
                name=execution_name,
            )

            execution_row.update(
                {
                    DATE_COLUMN: date_value,
                    UPDATE_TIME_COLUMN: update_time,
                    TOTAL_COLUMN: total_value,
                    PASS_COLUMN: pass_value,
                    FAIL_COLUMN: fail_value,
                    TODO_COLUMN: todo_value,
                    SUCCESS_RATE_COLUMN: rate_value,
                }
            )

            long_rows.append(
                execution_row
            )

    print(
        f"✅ Migration terminée : "
        f"{len(long_rows)} ligne(s) longues créées."
    )

    return long_rows


def load_existing_long_rows(
    csv_content: bytes | None,
) -> list[dict[str, str]]:
    headers, rows = read_csv_content(
        csv_content
    )

    if not rows:
        return []

    if is_long_format(headers):
        return [
            normalize_long_row(row)
            for row in rows
        ]

    return migrate_wide_csv_to_long(
        headers=headers,
        wide_rows=rows,
    )


# ===========================================================================
# MISE À JOUR ET RÉTENTION
# ===========================================================================

def parse_date(
    date_value: str,
) -> datetime | None:
    try:
        return datetime.strptime(
            date_value,
            "%d/%m/%Y",
        )
    except ValueError:
        return None


def long_row_identity(
    row: dict[str, str],
) -> tuple[str, str, str]:
    """
    Identité métier d'une ligne :
        Date + Niveau + Clé

    Si la Clé n'est pas disponible dans un ancien historique migré,
    le Nom est utilisé.
    """

    key_or_name = (
        row.get(KEY_COLUMN, "").strip()
        or row.get(NAME_COLUMN, "").strip()
    )

    return (
        row.get(DATE_COLUMN, "").strip(),
        row.get(LEVEL_COLUMN, "").strip(),
        key_or_name,
    )


def deduplicate_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows_by_identity: dict[
        tuple[str, str, str],
        dict[str, str],
    ] = {}

    component_rows: dict[
        tuple[str, str],
        dict[str, str],
    ] = {}

    for row in rows:
        level = row.get(
            LEVEL_COLUMN,
            "",
        ).strip()

        if level == LEVEL_COMPONENT:
            component_identity = (
                row.get(
                    KEY_COLUMN,
                    "",
                ).strip(),
                row.get(
                    NAME_COLUMN,
                    "",
                ).strip(),
            )

            component_rows[
                component_identity
            ] = row

            continue

        identity = long_row_identity(
            row
        )

        rows_by_identity[
            identity
        ] = row

    return (
        list(rows_by_identity.values())
        + list(component_rows.values())
    )


def replace_snapshot_date(
    existing_rows: list[dict[str, str]],
    snapshot_rows: list[dict[str, str]],
    snapshot_date: str,
) -> list[dict[str, str]]:
    """
    Au même jour, toutes les anciennes lignes Test Plan/Test Execution
    sont supprimées puis remplacées par le snapshot actuel.
    """

    retained_rows = []

    removed_count = 0

    for row in existing_rows:
        level = row.get(
            LEVEL_COLUMN,
            "",
        ).strip()

        date_value = row.get(
            DATE_COLUMN,
            "",
        ).strip()

        if (
            level in {
                LEVEL_TEST_PLAN,
                LEVEL_TEST_EXECUTION,
            }
            and date_value == snapshot_date
        ):
            removed_count += 1
            continue

        retained_rows.append(
            row
        )

    if removed_count:
        print(
            f"🔄 {removed_count} ancienne(s) ligne(s) "
            f"du {snapshot_date} remplacée(s)."
        )
    else:
        print(
            f"➕ Nouveau snapshot pour le "
            f"{snapshot_date}."
        )

    return (
        retained_rows
        + snapshot_rows
    )


def replace_component_rows(
    rows: list[dict[str, str]],
    component_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    retained_rows = [
        row
        for row in rows
        if row.get(
            LEVEL_COLUMN,
            "",
        ).strip() != LEVEL_COMPONENT
    ]

    return (
        retained_rows
        + component_rows
    )


def retain_last_history_days(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    available_dates = sorted(
        {
            row.get(
                DATE_COLUMN,
                "",
            ).strip()
            for row in rows
            if (
                row.get(
                    LEVEL_COLUMN,
                    "",
                ).strip()
                in {
                    LEVEL_TEST_PLAN,
                    LEVEL_TEST_EXECUTION,
                }
                and parse_date(
                    row.get(
                        DATE_COLUMN,
                        "",
                    ).strip()
                )
                is not None
            )
        },
        key=lambda value: parse_date(value),
    )

    retained_dates = set(
        available_dates[
            -MAX_HISTORY_DAYS:
        ]
    )

    return [
        row
        for row in rows
        if (
            row.get(
                LEVEL_COLUMN,
                "",
            ).strip()
            == LEVEL_COMPONENT
            or row.get(
                DATE_COLUMN,
                "",
            ).strip()
            in retained_dates
        )
    ]


def sort_long_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    level_order = {
        LEVEL_TEST_PLAN: 0,
        LEVEL_TEST_EXECUTION: 1,
        LEVEL_COMPONENT: 2,
    }

    def sort_key(
        row: dict[str, str],
    ) -> tuple[Any, ...]:
        level = row.get(
            LEVEL_COLUMN,
            "",
        ).strip()

        parsed_date = parse_date(
            row.get(
                DATE_COLUMN,
                "",
            ).strip()
        )

        date_sort_value = (
            parsed_date
            if parsed_date is not None
            else datetime.max
        )

        return (
            date_sort_value,
            level_order.get(level, 99),
            row.get(
                NAME_COLUMN,
                "",
            ).lower(),
        )

    return sorted(
        rows,
        key=sort_key,
    )


# ===========================================================================
# GÉNÉRATION DU CSV
# ===========================================================================

def generate_csv_content(
    rows: list[dict[str, str]],
) -> bytes:
    buffer = io.StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_HEADERS,
        delimiter=CSV_DELIMITER,
        extrasaction="ignore",
        lineterminator="\n",
    )

    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                header: row.get(
                    header,
                    "",
                )
                for header in CSV_HEADERS
            }
        )

    # BOM UTF-8 pour l'ouverture directe dans Excel.
    return buffer.getvalue().encode(
        "utf-8-sig"
    )


# ===========================================================================
# MAIN
# ===========================================================================

def main() -> None:
    confluence_session = (
        make_confluence_session()
    )

    # 1. Lecture de l'état actuel dans Jira/Xray.
    test_plan_metrics = (
        get_test_plan_metrics()
    )

    execution_metrics = (
        get_all_test_execution_metrics()
    )

    # 2. Date du snapshot.
    now = datetime.now().astimezone()

    snapshot_datetime = (
        now
        + timedelta(
            days=TEST_DAY_OFFSET
        )
    )

    snapshot_date = (
        snapshot_datetime.strftime(
            "%d/%m/%Y"
        )
    )

    # 3. Construction des lignes longues du jour.
    snapshot_rows = build_snapshot_rows(
        test_plan_metrics=test_plan_metrics,
        execution_metrics=execution_metrics,
        snapshot_datetime=snapshot_datetime,
    )

    component_rows = (
        build_component_rows()
    )

    # 4. Recherche de la page et de la pièce jointe.
    page_id = find_page_id(
        confluence_session
    )

    attachment = find_csv_attachment(
        confluence_session,
        page_id,
    )

    existing_csv_content = None

    if attachment is not None:
        print(
            f"📥 Téléchargement de "
            f"{CSV_FILENAME}"
        )

        existing_csv_content = (
            download_attachment_content(
                confluence_session,
                page_id,
                attachment,
            )
        )
    else:
        print(
            f"ℹ️ La pièce jointe "
            f"{CSV_FILENAME} n'existe pas encore."
        )

    # 5. Lecture ou migration de l'ancien CSV.
    existing_rows = load_existing_long_rows(
        existing_csv_content
    )

    print(
        f"📚 Lignes existantes relues : "
        f"{len(existing_rows)}"
    )

    # 6. Remplacement complet du jour courant.
    updated_rows = replace_snapshot_date(
        existing_rows=existing_rows,
        snapshot_rows=snapshot_rows,
        snapshot_date=snapshot_date,
    )

    # 7. Remplacement des lignes Composant.
    updated_rows = replace_component_rows(
        rows=updated_rows,
        component_rows=component_rows,
    )

    # 8. Déduplication et conservation des sept derniers jours.
    updated_rows = deduplicate_rows(
        updated_rows
    )

    updated_rows = retain_last_history_days(
        updated_rows
    )

    updated_rows = sort_long_rows(
        updated_rows
    )

    retained_dates = {
        row.get(
            DATE_COLUMN,
            "",
        ).strip()
        for row in updated_rows
        if row.get(
            LEVEL_COLUMN,
            "",
        ).strip()
        in {
            LEVEL_TEST_PLAN,
            LEVEL_TEST_EXECUTION,
        }
    }

    print(
        f"📅 Journées conservées : "
        f"{len(retained_dates)}/{MAX_HISTORY_DAYS}"
    )

    print(
        f"📄 Nombre total de lignes CSV : "
        f"{len(updated_rows)}"
    )

    # 9. Génération du CSV.
    new_csv_content = generate_csv_content(
        updated_rows
    )

    LOCAL_CSV_PATH.write_bytes(
        new_csv_content
    )

    print(
        f"💾 CSV local généré : "
        f"{LOCAL_CSV_PATH.resolve()}"
    )

    # 10. Création ou mise à jour de la pièce jointe.
    if attachment is None:
        create_csv_attachment(
            session=confluence_session,
            page_id=page_id,
            csv_content=new_csv_content,
        )
    else:
        update_csv_attachment(
            session=confluence_session,
            page_id=page_id,
            attachment_id=str(
                attachment["id"]
            ),
            csv_content=new_csv_content,
        )

    print(
        "✅ Terminé : CSV long mis à jour. "
        "Le contenu de la page Confluence n'a pas été modifié."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"❌ Une erreur est survenue : "
            f"{error}"
        )
        sys.exit(1)