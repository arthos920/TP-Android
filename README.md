#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

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

# Champ Xray contenant les statistiques du Test Plan et des Test Executions.
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

# Le même fichier est créé puis versionné sur la page.
CSV_FILENAME = "night_run_dashboard.csv"

# Copie locale créée à chaque lancement pour faciliter le diagnostic.
LOCAL_CSV_PATH = Path(CSV_FILENAME)


# ---------------------------------------------------------------------------
# HISTORIQUE
# ---------------------------------------------------------------------------

# Nombre maximal de journées conservées dans le CSV.
MAX_HISTORY_DAYS = 7

# Décalage uniquement destiné aux tests :
# 0 = aujourd'hui, 1 = J+1, 2 = J+2...
TEST_DAY_OFFSET = 0

# Séparateur adapté à Excel en environnement français.
CSV_DELIMITER = ";"

# Les pourcentages sont écrits comme des nombres bruts :
# 96.88 et non "96.88 %".
CSV_FLOAT_DECIMALS = 2


# ---------------------------------------------------------------------------
# COMPOSANTS / DATAMANAGER
#
# Les données des composants sont conservées dans le CSV sous forme de
# colonnes fixes. Mets INCLUDE_COMPONENTS_IN_CSV = False pour les retirer.
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
# CONSTANTES DU CSV
# ===========================================================================

DATE_COLUMN = "Date"
UPDATE_TIME_COLUMN = "Heure de mise à jour"
TEST_PLAN_KEY_COLUMN = "Test Plan - Clé"
TEST_PLAN_NAME_COLUMN = "Test Plan - Nom"

GLOBAL_TOTAL_COLUMN = "Global - Total"
GLOBAL_PASS_COLUMN = "Global - PASS"
GLOBAL_FAIL_COLUMN = "Global - FAIL"
GLOBAL_TODO_COLUMN = "Global - TODO"
GLOBAL_RATE_COLUMN = "Global - Réussite (%)"

FIXED_HEADERS = [
    DATE_COLUMN,
    UPDATE_TIME_COLUMN,
    TEST_PLAN_KEY_COLUMN,
    TEST_PLAN_NAME_COLUMN,
    GLOBAL_TOTAL_COLUMN,
    GLOBAL_PASS_COLUMN,
    GLOBAL_FAIL_COLUMN,
    GLOBAL_TODO_COLUMN,
    GLOBAL_RATE_COLUMN,
]

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
    Ne met volontairement pas Content-Type=application/json.

    Lors de l'upload du CSV, requests doit construire automatiquement
    l'en-tête multipart/form-data.
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
    Reprend la logique utilisée dans le module Keycloak :

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


def load_components_from_excel() -> list[dict[str, str]]:
    if not INCLUDE_COMPONENTS_IN_CSV:
        return []

    components = []

    for index, setting in enumerate(
        COMPONENT_SETTINGS,
        start=1,
    ):
        component_name = str(
            setting["name"]
        ).strip()

        component_alias = str(
            setting["alias"]
        ).strip()

        component_url_key = str(
            setting["url_key"]
        ).strip()

        print(
            f"🔎 DataManager composant {index} : "
            f"{component_name} "
            f"(alias={component_alias}, clé={component_url_key})"
        )

        component_url = get_component_url(
            obj_alias=component_alias,
            url_key=component_url_key,
        )

        components.append(
            {
                "index": str(index),
                "name": component_name,
                "url": component_url,
            }
        )

    return components


def get_component_headers() -> list[str]:
    if not INCLUDE_COMPONENTS_IN_CSV:
        return []

    headers = []

    for index in range(
        1,
        len(COMPONENT_SETTINGS) + 1,
    ):
        headers.extend(
            [
                f"Composant {index} - Nom",
                f"Composant {index} - URL",
            ]
        )

    return headers


def add_components_to_row(
    row: dict[str, str],
    components: list[dict[str, str]],
) -> None:
    for component in components:
        index = component["index"]

        row[f"Composant {index} - Nom"] = (
            component["name"]
        )
        row[f"Composant {index} - URL"] = (
            component["url"]
        )


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

    # Le total garde aussi les éventuels statuts personnalisés Xray.
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

    stats_data = fields.get(
        XRAY_STATS_CUSTOM_FIELD
    )

    stats = parse_xray_stats(
        stats_data
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
    Lit les Test Runs d'une Test Execution avec pagination lorsque
    l'endpoint Xray la fournit.
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

    # Le nom est unique selon la règle métier donnée.
    return sorted(
        results,
        key=lambda item: item["summary"].lower(),
    )


# ===========================================================================
# COLONNES DYNAMIQUES DES TEST EXECUTIONS
# ===========================================================================

def get_execution_columns(
    execution_name: str,
) -> list[str]:
    return [
        f"{execution_name} - Total",
        f"{execution_name} - PASS",
        f"{execution_name} - FAIL",
        f"{execution_name} - TODO",
        f"{execution_name} - Réussite (%)",
    ]


def add_execution_metrics_to_row(
    row: dict[str, str],
    execution_metrics: list[dict[str, Any]],
) -> None:
    for metrics in execution_metrics:
        execution_name = metrics["summary"]
        columns = get_execution_columns(
            execution_name
        )

        row[columns[0]] = str(
            metrics["total"]
        )
        row[columns[1]] = str(
            metrics["pass"]
        )
        row[columns[2]] = str(
            metrics["fail"]
        )
        row[columns[3]] = str(
            metrics["todo"]
        )
        row[columns[4]] = format_float(
            metrics["success_rate"]
        )


# ===========================================================================
# CONFLUENCE - PAGE ET PIÈCE JOINTE
# ===========================================================================

def find_page_id(
    session: requests.Session,
) -> str:
    """
    Garde la recherche CQL utilisée précédemment.
    """

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
    if link.startswith(
        ("http://", "https://")
    ):
        return link

    parsed_base = urlparse(
        CONFLUENCE_URL
    )

    origin = (
        f"{parsed_base.scheme}://"
        f"{parsed_base.netloc}"
    )

    if link.startswith("/"):
        return urljoin(
            origin + "/",
            link.lstrip("/"),
        )

    return urljoin(
        CONFLUENCE_URL.rstrip("/") + "/",
        link,
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
        download_url = (
            make_absolute_confluence_url(
                download_link
            )
        )
    else:
        download_url = (
            f"{CONFLUENCE_URL}/download/attachments/"
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
                "Création automatique des données "
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
                "Mise à jour automatique des données "
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
# CSV
# ===========================================================================

def format_float(
    value: float,
) -> str:
    return f"{float(value):.{CSV_FLOAT_DECIMALS}f}"


def read_existing_csv(
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


def build_csv_headers(
    existing_headers: list[str],
    execution_metrics: list[dict[str, Any]],
) -> list[str]:
    headers = []

    for header in (
        FIXED_HEADERS
        + get_component_headers()
    ):
        if header not in headers:
            headers.append(header)

    # Les anciennes colonnes sont conservées pour préserver l'historique
    # et la configuration des graphiques manuels.
    for header in existing_headers:
        if header not in headers:
            headers.append(header)

    # Une nouvelle Test Execution ajoute ses cinq colonnes à la fin.
    for metrics in execution_metrics:
        for header in get_execution_columns(
            metrics["summary"]
        ):
            if header not in headers:
                headers.append(header)

    return headers


def parse_row_date(
    row: dict[str, str],
) -> datetime | None:
    date_value = str(
        row.get(DATE_COLUMN, "")
    ).strip()

    try:
        return datetime.strptime(
            date_value,
            "%d/%m/%Y",
        )
    except ValueError:
        return None


def retain_last_days(
    rows_by_date: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    dated_rows = []

    for date_value, row in rows_by_date.items():
        try:
            parsed_date = datetime.strptime(
                date_value,
                "%d/%m/%Y",
            )
        except ValueError:
            continue

        dated_rows.append(
            (
                parsed_date,
                date_value,
                row,
            )
        )

    dated_rows.sort(
        key=lambda item: item[0]
    )

    retained = dated_rows[
        -MAX_HISTORY_DAYS:
    ]

    return {
        date_value: row
        for _, date_value, row in retained
    }


def build_current_row(
    existing_row: dict[str, str] | None,
    test_plan_metrics: dict[str, Any],
    execution_metrics: list[dict[str, Any]],
    components: list[dict[str, str]],
    snapshot_datetime: datetime,
) -> dict[str, str]:
    # Part de l'ancienne ligne afin de ne pas effacer une ancienne colonne
    # qui n'est plus remontée par le Test Plan.
    row = dict(
        existing_row or {}
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

    row[TEST_PLAN_KEY_COLUMN] = (
        test_plan_metrics["key"]
    )
    row[TEST_PLAN_NAME_COLUMN] = (
        test_plan_metrics["summary"]
    )

    row[GLOBAL_TOTAL_COLUMN] = str(
        test_plan_metrics["total"]
    )
    row[GLOBAL_PASS_COLUMN] = str(
        test_plan_metrics["pass"]
    )
    row[GLOBAL_FAIL_COLUMN] = str(
        test_plan_metrics["fail"]
    )
    row[GLOBAL_TODO_COLUMN] = str(
        test_plan_metrics["todo"]
    )
    row[GLOBAL_RATE_COLUMN] = format_float(
        test_plan_metrics["success_rate"]
    )

    add_components_to_row(
        row,
        components,
    )

    add_execution_metrics_to_row(
        row,
        execution_metrics,
    )

    return row


def update_rows_for_current_day(
    existing_rows: list[dict[str, str]],
    current_row: dict[str, str],
) -> list[dict[str, str]]:
    rows_by_date: dict[str, dict[str, str]] = {}

    for row in existing_rows:
        parsed_date = parse_row_date(row)

        if parsed_date is None:
            continue

        normalized_date = parsed_date.strftime(
            "%d/%m/%Y"
        )

        rows_by_date[normalized_date] = row

    current_date = current_row[
        DATE_COLUMN
    ]

    if current_date in rows_by_date:
        print(
            f"🔄 Remplacement de la ligne CSV "
            f"du {current_date}"
        )
    else:
        print(
            f"➕ Ajout de la ligne CSV "
            f"du {current_date}"
        )

    rows_by_date[current_date] = (
        current_row
    )

    rows_by_date = retain_last_days(
        rows_by_date
    )

    rows = list(
        rows_by_date.values()
    )

    rows.sort(
        key=lambda row: (
            parse_row_date(row)
            or datetime.min
        )
    )

    return rows


def generate_csv_content(
    headers: list[str],
    rows: list[dict[str, str]],
) -> bytes:
    buffer = io.StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        buffer,
        fieldnames=headers,
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
                for header in headers
            }
        )

    # utf-8-sig ajoute un BOM utile pour l'ouverture directe dans Excel.
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

    # 1. Récupération de toutes les données Xray.
    test_plan_metrics = (
        get_test_plan_metrics()
    )

    execution_metrics = (
        get_all_test_execution_metrics()
    )

    # 2. Lecture des composants via DataManager.
    components = (
        load_components_from_excel()
    )

    # 3. Recherche de la page et de la pièce jointe.
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
            f"📥 Téléchargement de la pièce jointe "
            f"existante : {CSV_FILENAME}"
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
            f"ℹ️ La pièce jointe {CSV_FILENAME} "
            "n'existe pas encore."
        )

    # 4. Lecture de l'historique CSV.
    existing_headers, existing_rows = (
        read_existing_csv(
            existing_csv_content
        )
    )

    print(
        f"📚 Historique CSV relu : "
        f"{len(existing_rows)} ligne(s)"
    )

    # 5. Snapshot du jour.
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

    existing_today_row = next(
        (
            row
            for row in existing_rows
            if str(
                row.get(DATE_COLUMN, "")
            ).strip() == snapshot_date
        ),
        None,
    )

    current_row = build_current_row(
        existing_row=existing_today_row,
        test_plan_metrics=test_plan_metrics,
        execution_metrics=execution_metrics,
        components=components,
        snapshot_datetime=snapshot_datetime,
    )

    updated_rows = (
        update_rows_for_current_day(
            existing_rows=existing_rows,
            current_row=current_row,
        )
    )

    headers = build_csv_headers(
        existing_headers=existing_headers,
        execution_metrics=execution_metrics,
    )

    new_csv_content = generate_csv_content(
        headers=headers,
        rows=updated_rows,
    )

    # Copie locale.
    LOCAL_CSV_PATH.write_bytes(
        new_csv_content
    )

    print(
        f"💾 CSV local généré : "
        f"{LOCAL_CSV_PATH.resolve()}"
    )

    print(
        f"📅 Jours conservés : "
        f"{len(updated_rows)}/{MAX_HISTORY_DAYS}"
    )

    # 6. Création ou mise à jour de la pièce jointe.
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
        "✅ Terminé : le corps de la page "
        "Confluence n'a pas été modifié."
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