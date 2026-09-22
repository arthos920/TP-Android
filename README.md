#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrait les Test Runs des Test Executions portant une Fix Version.

Python 3.10+ ; dépendances : requests, urllib3.

Une ligne = Test Execution + Test Case + ID du Test Run Xray.
Les dates viennent du Test Run, pas des champs created/updated de Jira.
Une date absente reste vide. Les fuseaux fournis par Xray sont conservés.

Le CSV complet est reconstruit à chaque lancement, puis la même pièce jointe
Confluence est créée ou mise à jour. Les anciens snapshots de statistiques
ne sont pas repris. Aucun filtre de date ni limite d'historique n'est appliqué.
L'extraction reflète l'état courant des Test Runs accessibles : elle ne relit
pas l'historique des changements de statut d'un même Test Run.
"""

import csv
import io
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ===========================================================================
# CONFIGURATION
# ===========================================================================

JIRA_URL = ""
JIRA_USER = ""
JIRA_TOKEN = ""
JIRA_PROXY_URL = ""

# Filtre appliqué aux Test Executions, pas aux Test Cases.
FIX_VERSION = "toto"
TEST_EXECUTION_ISSUE_TYPE = "Test Execution"

# Vide = tous les projets accessibles ayant cette Fix Version.
JIRA_PROJECT_KEY = ""

JIRA_PAGE_SIZE = 100
# Ne doit pas dépasser la limite configurée dans Xray.
XRAY_PAGE_SIZE = 100

CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""
CONFLUENCE_PROXY_URL = ""

CONFLUENCE_PAGE_TITLE = "Dashboard night run automation"
CONFLUENCE_SPACE_KEY = "TEI"

# Cette pièce jointe contiendra désormais le détail des Test Runs.
CSV_FILENAME = "night_run_dashboard.csv"
LOCAL_CSV_PATH = Path(CSV_FILENAME)
CSV_DELIMITER = ";"

CSV_HEADERS = [
    "Fix version",
    "Test Execution",
    "Nom Test Execution",
    "Test Case",
    "Nom Test Case",
    "ID Test Run",
    "Statut",
    "Date début",
    "Date fin",
    "Date extraction",
    "URL Test Execution",
    "URL Test Case",
]


# ===========================================================================
# HTTP - LOGIQUE DE CONNEXION REPRISE SANS MODIFICATION
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
# JIRA - TEST EXECUTIONS FILTRÉES PAR FIX VERSION
# ===========================================================================

def jql_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_jql() -> str:
    if not FIX_VERSION.strip():
        raise ValueError("Renseigner FIX_VERSION.")

    clauses = [
        f"issuetype = {jql_string(TEST_EXECUTION_ISSUE_TYPE)}",
        f"fixVersion = {jql_string(FIX_VERSION)}",
    ]
    if JIRA_PROJECT_KEY.strip():
        clauses.append(f"project = {jql_string(JIRA_PROJECT_KEY)}")

    return " AND ".join(clauses) + " ORDER BY key ASC"


def get_test_executions() -> list[dict[str, Any]]:
    jql = build_jql()
    print(f"Recherche Jira : {jql}")

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    start_at = 0

    while True:
        payload = jira_get(
            f"{JIRA_URL}/rest/api/2/search",
            params={
                "jql": jql,
                "fields": "summary",
                "startAt": start_at,
                "maxResults": JIRA_PAGE_SIZE,
            },
        ).json()

        if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
            raise ValueError("Réponse Jira inattendue pour la recherche.")

        issues = payload["issues"]
        total = int(payload["total"])
        if not issues:
            if start_at < total:
                raise ValueError("Pagination Jira interrompue avant la fin des résultats.")
            break

        for issue in issues:
            key = issue["key"]
            if key in seen_keys:
                raise ValueError(f"Pagination Jira répétée pour {key}. Relancer l'extraction.")
            seen_keys.add(key)
            results.append(issue)

        # Jira peut renvoyer moins de résultats que maxResults.
        start_at += len(issues)
        if start_at >= total:
            break

    if not results:
        raise ValueError(
            f"Aucune Test Execution accessible pour la Fix Version {FIX_VERSION!r}. "
            "Le CSV n'a pas été modifié."
        )

    print(f"{len(results)} Test Execution(s) trouvée(s).")
    return results


# ===========================================================================
# XRAY - ASSOCIATIONS ET DÉTAIL DES TEST RUNS
# ===========================================================================

def unpack_test_run_page(
    payload: Any,
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """Accepte la liste Xray v1 et les réponses enveloppées avec métadonnées."""
    total = None
    is_last = False

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = None
        for name in ("results", "tests", "entries", "values"):
            if name in payload:
                items = payload[name]
                break
        if payload.get("total") is not None:
            total = int(payload["total"])
        is_last = payload.get("isLast") is True
    else:
        items = None

    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Réponse Xray inattendue pour la liste des tests.")

    return items, total, is_last


def get_test_runs(test_execution_key: str) -> list[dict[str, Any]]:
    url = f"{JIRA_URL}/rest/raven/1.0/api/testexec/{test_execution_key}/test"
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    page = 1
    expected_total = None

    while True:
        payload = jira_get(
            url,
            params={"page": page, "limit": XRAY_PAGE_SIZE},
        ).json()
        items, total, is_last = unpack_test_run_page(payload)
        if total is not None:
            expected_total = total

        if not items:
            if expected_total is not None and len(results) < expected_total:
                raise ValueError(f"Liste Xray incomplète pour {test_execution_key}.")
            break

        for item in items:
            test_key = str(item.get("key") or item.get("testKey") or "").strip()
            run_id = str(item.get("id") or item.get("testRunId") or "").strip()
            if not test_key:
                raise ValueError(f"Clé de Test Case absente dans {test_execution_key}.")

            identity = (test_key, run_id)
            if identity in seen:
                raise ValueError(
                    f"Pagination Xray répétée pour {test_execution_key}, page {page}. "
                    "Vérifier la prise en charge du paramètre page par votre version Xray."
                )
            seen.add(identity)
            results.append({"test_key": test_key, "run_id": run_id})

        if expected_total is not None and len(results) >= expected_total:
            break
        if is_last:
            if expected_total is not None and len(results) < expected_total:
                raise ValueError(f"Dernière page Xray incomplète pour {test_execution_key}.")
            break

        # Une liste sans total nécessite de poursuivre jusqu'à une page vide.
        # Ne pas utiliser len(items) < XRAY_PAGE_SIZE : le serveur peut limiter
        # lui-même la taille des pages.
        page += 1

    return results


def get_test_run_details(
    test_execution_key: str,
    test_key: str,
    run_id: str,
) -> dict[str, Any]:
    """Le détail du run expose startedOn/finishedOn en dates absolues."""
    url = f"{JIRA_URL}/rest/raven/1.0/api/testrun"
    if run_id:
        response = jira_get(f"{url}/{run_id}")
    else:
        response = jira_get(
            url,
            params={
                "testExecIssueKey": test_execution_key,
                "testIssueKey": test_key,
            },
        )

    run = response.json()
    if not isinstance(run, dict) or not run.get("status"):
        raise ValueError(f"Détail ou statut Xray absent pour {test_execution_key}/{test_key}.")

    for field, expected in (("testExecKey", test_execution_key), ("testKey", test_key)):
        if run.get(field) and str(run[field]) != expected:
            raise ValueError(f"Test Run incohérent pour {test_execution_key}/{test_key}.")
    if run_id and run.get("id") is not None and str(run["id"]) != run_id:
        raise ValueError(f"ID Test Run incohérent pour {test_execution_key}/{test_key}.")

    return run


def normalize_status_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("status") or value.get("key")
    return str(value or "UNKNOWN").upper().strip()


def get_test_case_summary(test_key: str, cache: dict[str, str]) -> str:
    # Seul le nom est mutualisé : jamais le statut ou les dates d'exécution.
    if test_key not in cache:
        payload = jira_get(
            f"{JIRA_URL}/rest/api/2/issue/{test_key}",
            params={"fields": "summary"},
        ).json()
        cache[test_key] = str(payload.get("fields", {}).get("summary") or test_key)
    return cache[test_key]


def jira_issue_url(issue_key: str) -> str:
    return f"{JIRA_URL.rstrip('/')}/browse/{issue_key}"


def build_extraction_rows(
    executions: list[dict[str, Any]],
    extracted_at: datetime,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    summary_cache: dict[str, str] = {}
    extraction_date = extracted_at.isoformat(timespec="seconds")

    for index, execution in enumerate(executions, start=1):
        execution_key = execution["key"]
        execution_name = str(execution.get("fields", {}).get("summary") or execution_key)
        associations = get_test_runs(execution_key)
        print(f"[{index}/{len(executions)}] {execution_key} : {len(associations)} Test Run(s).")

        for association in associations:
            test_key = association["test_key"]
            run = get_test_run_details(execution_key, test_key, association["run_id"])

            # Chaque association conserve ses propres résultat et dates.
            # Le même Test Case dans deux Test Executions donne deux lignes.
            rows.append({
                "Fix version": FIX_VERSION,
                "Test Execution": execution_key,
                "Nom Test Execution": execution_name,
                "Test Case": test_key,
                "Nom Test Case": get_test_case_summary(test_key, summary_cache),
                "ID Test Run": str(run.get("id") or association["run_id"]),
                "Statut": normalize_status_name(run["status"]),
                "Date début": str(run.get("startedOn") or ""),
                "Date fin": str(run.get("finishedOn") or ""),
                "Date extraction": extraction_date,
                "URL Test Execution": jira_issue_url(execution_key),
                "URL Test Case": jira_issue_url(test_key),
            })

    return rows


# ===========================================================================
# CONFLUENCE - MÊME RECHERCHE DE PAGE ET MÊME ENVOI MULTIPART
# ===========================================================================

def find_page_id(session: requests.Session) -> str:
    cql = (
        f'title ~ "{CONFLUENCE_PAGE_TITLE}" '
        f'AND space = "{CONFLUENCE_SPACE_KEY}"'
    )
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/search",
        params={"cql": cql, "start": 0, "limit": 10},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"Page Confluence '{CONFLUENCE_PAGE_TITLE}' introuvable.")

    page_id = str(results[0]["content"]["id"])
    print(f"Page Confluence trouvée : {page_id}")
    return page_id


def find_csv_attachment(
    session: requests.Session,
    page_id: str,
) -> dict[str, Any] | None:
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
        params={"filename": CSV_FILENAME, "limit": 200, "expand": "version"},
        timeout=30,
    )
    response.raise_for_status()
    for attachment in response.json().get("results", []):
        if attachment.get("title") == CSV_FILENAME:
            return attachment
    return None


def create_csv_attachment(
    session: requests.Session,
    page_id: str,
    csv_content: bytes,
) -> None:
    response = session.post(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
        headers={"X-Atlassian-Token": "no-check"},
        files={"file": (CSV_FILENAME, io.BytesIO(csv_content), "text/csv")},
        data={"comment": f"Extraction Xray des Test Runs - Fix Version {FIX_VERSION}"},
        timeout=60,
    )
    response.raise_for_status()
    print(f"Pièce jointe créée : {CSV_FILENAME}")


def update_csv_attachment(
    session: requests.Session,
    page_id: str,
    attachment_id: str,
    csv_content: bytes,
) -> None:
    response = session.post(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data",
        headers={"X-Atlassian-Token": "no-check"},
        files={"file": (CSV_FILENAME, io.BytesIO(csv_content), "text/csv")},
        data={"comment": f"Extraction Xray des Test Runs - Fix Version {FIX_VERSION}"},
        timeout=60,
    )
    response.raise_for_status()
    print(f"Nouvelle version de la pièce jointe : {CSV_FILENAME}")


# ===========================================================================
# CSV ET MAIN
# ===========================================================================

def generate_csv_content(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_HEADERS,
        delimiter=CSV_DELIMITER,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def main() -> None:
    confluence_session = make_confluence_session()

    # L'extraction doit aboutir entièrement avant toute écriture du CSV.
    extracted_at = datetime.now().astimezone()
    executions = get_test_executions()
    rows = build_extraction_rows(executions, extracted_at)
    csv_content = generate_csv_content(rows)

    LOCAL_CSV_PATH.write_bytes(csv_content)
    print(f"CSV local généré : {LOCAL_CSV_PATH.resolve()} ({len(rows)} lignes).")

    page_id = find_page_id(confluence_session)
    attachment = find_csv_attachment(confluence_session, page_id)
    if attachment is None:
        create_csv_attachment(confluence_session, page_id, csv_content)
    else:
        update_csv_attachment(confluence_session, page_id, str(attachment["id"]), csv_content)

    print(
        f"Terminé : {len(executions)} Test Execution(s), {len(rows)} Test Run(s). "
        "Le contenu de la page Confluence n'a pas été modifié."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Une erreur est survenue : {error}")
        sys.exit(1)
