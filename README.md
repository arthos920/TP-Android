#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrait les releases Enable d'un tableau de paramètres Confluence.

Python 3.10+ ; dépendances : requests, urllib3.
Sous Windows, installer aussi tzdata si Europe/Paris n'est pas disponible.

Une ligne = Test Execution + Test Case + ID du Test Run Xray.
Les dates viennent du Test Run, pas des champs created/updated de Jira.
Une date absente reste vide. Les fuseaux fournis par Xray sont conservés.

Colonnes attendues : Status, Release, Jira Project, Confluence Page,
Beg. Date (ou Beg_Date), End Date. Seules les lignes Enable sont traitées.
Pour chaque ligne, deux fichiers sont envoyés à la page Confluence indiquée :
<release>_brut.csv et <release>_post_processing.csv.
Avec DEBUG = True, tous les CSV sont envoyés à DEBUG_CONFLUENCE_PAGE_ID.
La période du post-processing va de Beg. Date à End Date, bornes incluses.

Les deux CSV sont reconstruits à chaque lancement et envoyés à Confluence.
Le post-processing est calculé exclusivement à partir du CSV brut généré.
Pour chaque jour, il retient le dernier statut daté de chaque Test Case.
TOTAL est le nombre de Test Cases distincts du brut, fixe sur toute la période.
Avant le premier statut daté, le test est compté TODO par convention.
Les jours futurs restent vides, sauf date et TOTAL.
EXECUTED_IN_DAY = (PASS du jour - PASS de la veille)
                + (FAIL du jour - FAIL de la veille).
Cette variation signée peut être négative et ne compte pas les relances.

Aucun filtre de date ni limite d'historique n'est appliqué au brut.
L'extraction reflète l'état courant des Test Runs accessibles : elle ne relit
pas l'historique des changements de statut d'un même Test Run.
"""

import csv
import io
import re
import sys
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, unquote_plus, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

# Les filtres release/projet viennent du tableau Confluence.
TEST_EXECUTION_ISSUE_TYPE = "Test Execution"

JIRA_PAGE_SIZE = 100
# Ne doit pas dépasser la limite configurée dans Xray.
XRAY_PAGE_SIZE = 100

CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""
CONFLUENCE_PROXY_URL = ""

# Page contenant le tableau des paramètres. Un ID renseigné est prioritaire.
# Exemple : pour une URL .../pages/viewpage.action?pageId=123456, mettre "123456".
CONFLUENCE_CONFIG_PAGE_ID = ""
CONFLUENCE_CONFIG_PAGE_TITLE = "JIRA extraction needs for reporting"
CONFLUENCE_CONFIG_SPACE_KEY = "TEI"

# Mode test : tous les CSV sont envoyés sur cette unique page Confluence.
# Renseigner son ID numérique avant de lancer le script en mode debug.
# False = utiliser la colonne Confluence Page de chaque ligne du tableau.
DEBUG = True
DEBUG_CONFLUENCE_PAGE_ID = ""

# Copies locales regroupées par ID de page de destination pour éviter les
# collisions si deux pages utilisent le même nom de release.
OUTPUT_DIRECTORY = Path("jira_exports")
CSV_DELIMITER = ","
REPORT_TIMEZONE = "Europe/Paris"

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

POST_PROCESSING_HEADERS = [
    "date", "NA", "PASS", "FAIL", "ABORTED", "TODO", "EXECUTING",
    "TOTAL", "EXECUTED_IN_DAY",
]

# Statut du brut -> colonne de la synthèse. N/A reste N/A dans le brut.
POST_PROCESSING_STATUS_COLUMNS = {
    "N/A": "NA",
    "PASS": "PASS",
    "FAIL": "FAIL",
    "ABORTED": "ABORTED",
    "TODO": "TODO",
    "TO DO": "TODO",
    "EXECUTING": "EXECUTING",
}


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


def build_jql(fix_version: str, project_key: str) -> str:
    if not fix_version.strip() or not project_key.strip():
        raise ValueError("Release et Jira Project sont obligatoires pour une ligne Enable.")

    clauses = [
        f"issuetype = {jql_string(TEST_EXECUTION_ISSUE_TYPE)}",
        f"fixVersion = {jql_string(fix_version)}",
        f"project = {jql_string(project_key)}",
    ]

    return " AND ".join(clauses) + " ORDER BY key ASC"


def get_test_executions(fix_version: str, project_key: str) -> list[dict[str, Any]]:
    jql = build_jql(fix_version, project_key)
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
            f"Aucune Test Execution accessible pour {project_key}/{fix_version}. "
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
    fix_version: str,
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
                "Fix version": fix_version,
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
# CONFLUENCE - RECHERCHE DE PAGE ET ENVOI MULTIPART
# ===========================================================================

def find_page_id(session: requests.Session, title: str, space_key: str) -> str:
    cql = (
        f'type = page AND title = {jql_string(title)} '
        f'AND space = {jql_string(space_key)}'
    )
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/search",
        params={"cql": cql, "start": 0, "limit": 2},
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        raise ValueError(f"Page Confluence {title!r} introuvable dans {space_key}.")
    if len(results) != 1:
        raise ValueError(f"Plusieurs pages correspondent à {title!r}. Utiliser un lien avec pageId.")

    page_id = str(results[0]["content"]["id"])
    print(f"Page Confluence trouvée : {page_id}")
    return page_id


def find_csv_attachment(
    session: requests.Session,
    page_id: str,
    filename: str,
) -> dict[str, Any] | None:
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
        params={"filename": filename, "limit": 200, "expand": "version"},
        timeout=30,
    )
    response.raise_for_status()
    for attachment in response.json().get("results", []):
        if attachment.get("title") == filename:
            return attachment
    return None


def create_csv_attachment(
    session: requests.Session,
    page_id: str,
    csv_content: bytes,
    filename: str,
) -> None:
    response = session.post(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
        headers={"X-Atlassian-Token": "no-check"},
        files={"file": (filename, io.BytesIO(csv_content), "text/csv")},
        data={"comment": f"Mise à jour automatique de {filename}"},
        timeout=60,
    )
    response.raise_for_status()
    print(f"Pièce jointe créée : {filename}")


def update_csv_attachment(
    session: requests.Session,
    page_id: str,
    attachment_id: str,
    csv_content: bytes,
    filename: str,
) -> None:
    response = session.post(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data",
        headers={"X-Atlassian-Token": "no-check"},
        files={"file": (filename, io.BytesIO(csv_content), "text/csv")},
        data={"comment": f"Mise à jour automatique de {filename}"},
        timeout=60,
    )
    response.raise_for_status()
    print(f"Nouvelle version de la pièce jointe : {filename}")


def upload_csv_attachment(
    session: requests.Session,
    page_id: str,
    filename: str,
    csv_content: bytes,
) -> None:
    attachment = find_csv_attachment(session, page_id, filename)
    if attachment is None:
        create_csv_attachment(session, page_id, csv_content, filename)
    else:
        update_csv_attachment(session, page_id, str(attachment["id"]), csv_content, filename)


# ===========================================================================
# POST-PROCESSING SUR LA PÉRIODE CONFIGURÉE, À PARTIR DU CSV BRUT
# ===========================================================================

def read_raw_csv_content(csv_content: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(
        io.StringIO(csv_content.decode("utf-8-sig")),
        delimiter=CSV_DELIMITER,
    )
    required = {"Test Case", "Statut", "Date début", "Date fin", "Date extraction"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError("Le CSV brut ne contient pas les colonnes nécessaires au post-processing.")

    rows = []
    for line_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Ligne {line_number} incomplète ou mal formée dans le CSV brut.")
        rows.append(row)
    return rows


def parse_run_datetime(value: str, report_timezone: ZoneInfo) -> datetime | None:
    """Normalise les dates du brut en UTC ; une date vide reste inconnue."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Date non ISO dans le CSV brut : {value!r}.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=report_timezone)
    return parsed.astimezone(timezone.utc)


def build_post_processing_rows(
    raw_rows: list[dict[str, str]],
    as_of: datetime,
    begin_date: date,
    end_date: date,
) -> list[dict[str, str]]:
    """Dernier statut connu de chaque test à la fin de chaque journée.

    Date d'effet : début pour EXECUTING ; fin, sinon début pour les autres.
    On ne déduit jamais un ancien statut EXECUTING d'un run actuellement PASS.
    Un TODO sans date ne remplace pas un résultat daté d'une autre exécution.
    Un autre statut sans date est seulement connu au moment de l'extraction :
    il prend effet à cette date, avec un message explicite.

    Le premier jour est comparé à sa veille, calculée à partir de tout le brut
    disponible, même avant Beg. Date. Aujourd'hui est limité à l'heure as_of.
    """
    try:
        report_timezone = ZoneInfo(REPORT_TIMEZONE)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            f"Fuseau {REPORT_TIMEZONE!r} indisponible. Installer tzdata : pip install tzdata"
        ) from error
    if as_of.tzinfo is None:
        raise ValueError("La date de référence du post-processing doit contenir un fuseau horaire.")

    today = as_of.astimezone(report_timezone).date()
    as_of_utc = as_of.astimezone(timezone.utc)
    if begin_date > end_date:
        raise ValueError("Beg. Date doit être antérieure ou égale à End Date.")
    if end_date == date.max:
        raise ValueError("End Date doit être antérieure au 31/12/9999.")
    first_day = begin_date
    last_day = end_date

    test_keys: set[str] = set()
    # Un événement correspond à une observation datée, pas à une relance.
    events_by_identity: dict[tuple[datetime, str], str] = {}
    undated_observations = 0

    for line_number, row in enumerate(raw_rows, start=2):
        test_key = row.get("Test Case", "").strip()
        if not test_key:
            raise ValueError(f"Test Case absent à la ligne {line_number} du CSV brut.")
        test_keys.add(test_key)
        status = normalize_status_name(row.get("Statut"))
        if status not in POST_PROCESSING_STATUS_COLUMNS:
            raise ValueError(
                f"Statut {status!r} non prévu dans la synthèse pour {test_key}. "
                "Compléter POST_PROCESSING_STATUS_COLUMNS avant de recalculer."
            )
        column = POST_PROCESSING_STATUS_COLUMNS[status]
        started_at = parse_run_datetime(row.get("Date début", ""), report_timezone)
        finished_at = parse_run_datetime(row.get("Date fin", ""), report_timezone)
        effective_at = started_at if column == "EXECUTING" else finished_at or started_at

        if effective_at is None:
            if column == "TODO":
                # TODO sert d'état initial ; une ligne sans date ne permet
                # pas d'établir un retour à TODO après un résultat connu.
                continue
            effective_at = parse_run_datetime(row.get("Date extraction", ""), report_timezone)
            if effective_at is None:
                raise ValueError(f"Aucune date disponible pour le statut {status} de {test_key}.")
            undated_observations += 1

        if effective_at > as_of_utc:
            continue
        identity = (effective_at, test_key)
        previous_column = events_by_identity.get(identity)
        if previous_column is not None and previous_column != column:
            raise ValueError(
                f"Deux statuts différents de {test_key} portent la même date "
                f"{effective_at.isoformat()}. Impossible de choisir le plus récent."
            )
        events_by_identity[identity] = column

    if undated_observations:
        print(
            f"{undated_observations} statut(s) sans date d'exécution : "
            "pris en compte au jour de leur extraction, sans les reporter dans le passé."
        )

    events = sorted(
        (timestamp, test_key, column)
        for (timestamp, test_key), column in events_by_identity.items()
    )
    counts = {column: 0 for column in ("NA", "PASS", "FAIL", "ABORTED", "TODO", "EXECUTING")}
    counts["TODO"] = len(test_keys)
    latest_status = {test_key: "TODO" for test_key in test_keys}
    event_index = 0

    def apply_events_before(cutoff: datetime) -> None:
        nonlocal event_index
        while event_index < len(events) and events[event_index][0] < cutoff:
            _, test_key, new_status = events[event_index]
            counts[latest_status[test_key]] -= 1
            counts[new_status] += 1
            latest_status[test_key] = new_status
            event_index += 1

    # État de la veille de Beg. Date, y compris les années antérieures.
    period_start = datetime(
        first_day.year, first_day.month, first_day.day, tzinfo=report_timezone
    ).astimezone(timezone.utc)
    apply_events_before(period_start)
    previous_pass_fail = counts["PASS"] + counts["FAIL"]

    rows = []
    current_day = first_day
    while current_day <= last_day:
        row = {header: "" for header in POST_PROCESSING_HEADERS}
        row["date"] = current_day.isoformat()
        row["TOTAL"] = str(len(test_keys))

        if current_day <= today:
            next_day = current_day + timedelta(days=1)
            next_midnight = datetime(
                next_day.year, next_day.month, next_day.day, tzinfo=report_timezone
            ).astimezone(timezone.utc)
            apply_events_before(next_midnight)
            row.update({column: str(count) for column, count in counts.items()})
            pass_fail = counts["PASS"] + counts["FAIL"]
            row["EXECUTED_IN_DAY"] = str(pass_fail - previous_pass_fail)
            previous_pass_fail = pass_fail

        rows.append(row)
        current_day += timedelta(days=1)

    return rows


# ===========================================================================
# TABLEAU DE PARAMÈTRES CONFLUENCE
# ===========================================================================

class ConfigurationTableParser(HTMLParser):
    """Lit les tables HTML rendues, leurs textes, liens et dates Confluence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self.depth = 0
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self.depth == 0:
                self.table = []
                self.tables.append(self.table)
            elif self.cell is not None:
                self.cell["invalid"] = True
            self.depth += 1
            return
        if self.depth != 1:
            return
        if tag == "tr":
            self.row = []
            self.table.append(self.row)
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = {
                "parts": [], "links": [], "dates": [],
                "invalid": any(attributes.get(name, "1") != "1" for name in ("rowspan", "colspan")),
            }
            self.row.append(self.cell)
        elif self.cell is not None:
            if tag == "a":
                self.cell["links"].append(attributes)
            elif tag == "time" and attributes.get("datetime"):
                self.cell["dates"].append(attributes["datetime"])
            elif tag in {"br", "p", "div"}:
                self.cell["parts"].append(" ")

    def handle_data(self, data: str) -> None:
        if self.depth == 1 and self.cell is not None:
            self.cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self.depth = max(0, self.depth - 1)
            if self.depth == 0:
                self.table = self.row = self.cell = None
        elif self.depth == 1:
            if tag in {"td", "th"}:
                self.cell = None
            elif tag == "tr":
                self.row = None
                self.cell = None
            elif tag in {"p", "div"} and self.cell is not None:
                self.cell["parts"].append(" ")


def cell_text(cell: dict[str, Any]) -> str:
    return " ".join("".join(cell["parts"]).split())


def normalized_column(cell: dict[str, Any]) -> str:
    return re.sub(r"[^a-z0-9]", "", cell_text(cell).lower())


def parse_configuration_date(cell: dict[str, Any]) -> date:
    dates = set(cell["dates"])
    if len(dates) > 1:
        raise ValueError("Plusieurs dates sont présentes dans une même cellule.")
    value = next(iter(dates)) if dates else cell_text(cell)
    for format_string in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            pass
    raise ValueError(f"Date {value!r} invalide : utiliser JJ/MM/AAAA ou une date Confluence.")


def parse_enabled_rows(html: str) -> tuple[list[dict[str, Any]], list[str]]:
    parser = ConfigurationTableParser()
    parser.feed(html)
    parser.close()
    required = {"status", "release", "jiraproject", "confluencepage", "begdate", "enddate"}
    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    matched_tables = 0

    for table_number, table in enumerate(parser.tables, start=1):
        columns = None
        for row_number, cells in enumerate(table, start=1):
            labels = [normalized_column(cell) for cell in cells]
            if required.issubset(set(labels)):
                if any(cell["invalid"] for cell in cells) or any(labels.count(label) > 1 for label in required):
                    raise ValueError("En-têtes fusionnés ou dupliqués dans le tableau de paramètres.")
                if columns is None:
                    matched_tables += 1
                columns = {label: labels.index(label) for label in required}
                continue
            if columns is None or len(cells) <= columns["status"]:
                continue
            # Disabled et les lignes vides sont ignorés avant de lire leurs dates.
            if cell_text(cells[columns["status"]]).casefold() not in {"enable", "enabled"}:
                continue
            location = f"tableau {table_number}, ligne {row_number}"
            try:
                if len(cells) <= max(columns.values()) or any(cell["invalid"] for cell in cells):
                    raise ValueError("Cellules manquantes, fusionnées ou tableau imbriqué.")
                release = cell_text(cells[columns["release"]])
                project = cell_text(cells[columns["jiraproject"]])
                if not release or not project:
                    raise ValueError("Release et Jira Project sont obligatoires.")
                begin = parse_configuration_date(cells[columns["begdate"]])
                end = parse_configuration_date(cells[columns["enddate"]])
                if begin > end or end == date.max:
                    raise ValueError("La période Beg. Date / End Date est invalide.")
                jobs.append({
                    "location": location, "release": release, "project": project,
                    "begin_date": begin, "end_date": end,
                    "page_cell": cells[columns["confluencepage"]],
                })
            except ValueError as error:
                errors.append(f"{location} : {error}")

    if not matched_tables:
        raise ValueError(
            "Tableau introuvable. Colonnes attendues : Status, Release, Jira Project, "
            "Confluence Page, Beg. Date, End Date."
        )
    return jobs, errors


def resolve_target_page(
    session: requests.Session, cell: dict[str, Any], default_space: str,
) -> str:
    """Accepte les liens natifs, pageId, /spaces/.../pages/id et /display/..."""
    links = cell["links"]
    text = cell_text(cell)
    # Deux liens strictement identiques dans une cellule désignent la même page.
    links = list({tuple(sorted(link.items())): link for link in links}.values())
    if len(links) > 1:
        raise ValueError("Confluence Page contient plusieurs liens ; conserver une seule destination.")
    if not links:
        if text.isdigit():
            return text
        if text.startswith(("http://", "https://", "/")):
            links = [{"href": text}]
        elif text:
            return find_page_id(session, text, default_space)
        else:
            raise ValueError("Confluence Page est vide.")

    link = links[0]
    parsed = urlparse(link.get("href") or "")
    base = urlparse(CONFLUENCE_URL)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise ValueError("Le lien de destination doit être un lien de page Confluence.")
    if parsed.netloc and parsed.netloc.casefold() != base.netloc.casefold():
        raise ValueError("Le lien de destination appartient à un autre serveur Confluence.")
    if link.get("data-linked-resource-type") not in {None, "", "page"}:
        raise ValueError("Le lien de destination ne désigne pas une page.")

    page_id = link.get("data-linked-resource-id") or parse_qs(parsed.query).get("pageId", [""])[0]
    if page_id:
        if not str(page_id).isdigit():
            raise ValueError("L'identifiant de la page Confluence doit être numérique.")
        return str(page_id)
    match = re.search(r"/pages/(\d+)(?:/|$)", parsed.path)
    if match:
        return match.group(1)
    match = re.search(r"/display/([^/]+)/(.+)", parsed.path)
    if match:
        return find_page_id(session, unquote_plus(match.group(2)), unquote(match.group(1)))
    raise ValueError(
        "Lien Confluence non reconnu. Insérer un lien natif vers la page, "
        "une URL contenant pageId, ou son ID numérique."
    )


def release_filename_stem(release: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", release)
    stem = re.sub(r"\s+", "_", stem).strip(" .")
    if not stem or len(stem) > 180:
        raise ValueError("Le nom de release est vide ou trop long pour un nom de fichier.")
    if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        stem = "_" + stem
    return stem


def get_enabled_jobs(session: requests.Session) -> tuple[list[dict[str, Any]], list[str]]:
    debug_page_id = str(DEBUG_CONFLUENCE_PAGE_ID).strip() if DEBUG else ""
    if DEBUG:
        if not re.fullmatch(r"[0-9]+", debug_page_id):
            raise ValueError(
                "DEBUG est activé : renseigner DEBUG_CONFLUENCE_PAGE_ID avec "
                "l'ID numérique de la page de test. Aucun CSV n'a été envoyé."
            )
        print(f"DEBUG actif : tous les CSV seront envoyés sur la page {debug_page_id}.")

    page_id = CONFLUENCE_CONFIG_PAGE_ID.strip()
    if page_id and not page_id.isdigit():
        raise ValueError("CONFLUENCE_CONFIG_PAGE_ID doit contenir uniquement l'ID numérique.")
    if not page_id:
        page_id = find_page_id(session, CONFLUENCE_CONFIG_PAGE_TITLE, CONFLUENCE_CONFIG_SPACE_KEY)
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}",
        params={"expand": "body.view,space"}, timeout=30,
    )
    response.raise_for_status()
    page = response.json()
    html = page.get("body", {}).get("view", {}).get("value", "")
    if not html:
        raise ValueError("Le contenu rendu de la page de paramètres est vide ou inaccessible.")
    jobs, errors = parse_enabled_rows(html)
    default_space = page.get("space", {}).get("key") or CONFLUENCE_CONFIG_SPACE_KEY

    destinations: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str]] = set()
    for job in jobs:
        try:
            job["page_id"] = (
                debug_page_id if DEBUG
                else resolve_target_page(session, job["page_cell"], default_space)
            )
            stem = release_filename_stem(job["release"])
            job["raw_filename"] = f"{stem}_brut.csv"
            job["post_filename"] = f"{stem}_post_processing.csv"
            identity = (job["page_id"], stem.casefold())
            if identity in destinations:
                conflicts.add(identity)
                raise ValueError(
                    f"Deux lignes Enable produisent les mêmes fichiers sur la page {job['page_id']}. "
                    "Ces lignes ne seront pas traitées."
                )
            destinations[identity] = job
        except (ValueError, requests.RequestException) as error:
            errors.append(f"{job['location']} ({job['release']}) : {error}")

    return [job for identity, job in destinations.items() if identity not in conflicts], errors


# ===========================================================================
# CSV ET TRAITEMENT DE CHAQUE RELEASE
# ===========================================================================

def generate_csv_content(
    rows: list[dict[str, str]],
    headers: list[str] | None = None,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_HEADERS if headers is None else headers,
        delimiter=CSV_DELIMITER,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def process_release(session: requests.Session, job: dict[str, Any]) -> None:
    release = job["release"]
    project = job["project"]
    print(
        f"Traitement {project}/{release} : {job['begin_date']:%d/%m/%Y} "
        f"au {job['end_date']:%d/%m/%Y}, page {job['page_id']}."
    )
    output_directory = OUTPUT_DIRECTORY / job["page_id"]
    output_directory.mkdir(parents=True, exist_ok=True)
    raw_path = output_directory / job["raw_filename"]
    post_path = output_directory / job["post_filename"]
    # L'extraction doit aboutir entièrement avant toute écriture du CSV.
    extracted_at = datetime.now().astimezone()
    executions = get_test_executions(release, project)
    rows = build_extraction_rows(executions, extracted_at, release)
    csv_content = generate_csv_content(rows)

    raw_path.write_bytes(csv_content)
    print(f"CSV brut généré : {raw_path.resolve()} ({len(rows)} lignes).")

    # Le calcul relit réellement le brut qui vient d'être généré.
    # En cas de données non interprétables, le brut reste envoyé à Confluence
    # et l'ancienne synthèse n'est pas remplacée par des résultats incomplets.
    post_processing_error = None
    post_processing_content = None
    try:
        raw_rows = read_raw_csv_content(raw_path.read_bytes())
        post_processing_rows = build_post_processing_rows(
            raw_rows, datetime.now().astimezone(), job["begin_date"], job["end_date"]
        )
        post_processing_content = generate_csv_content(
            post_processing_rows, POST_PROCESSING_HEADERS
        )
        post_path.write_bytes(post_processing_content)
        print(
            f"Post-processing généré : {post_path.resolve()} "
            f"({len(post_processing_rows)} jours)."
        )
    except (ValueError, OSError) as error:
        post_processing_error = error

    upload_csv_attachment(session, job["page_id"], job["raw_filename"], csv_content)
    if post_processing_error is not None:
        raise ValueError(
            f"Le brut a été envoyé ; le post-processing n'a pas été mis à jour : "
            f"{post_processing_error}"
        ) from post_processing_error
    upload_csv_attachment(
        session, job["page_id"], job["post_filename"], post_processing_content
    )

    print(
        f"Terminé : {len(executions)} Test Execution(s), {len(rows)} Test Run(s). "
        "Brut et post-processing envoyés. Le contenu de la page Confluence n'a pas été modifié."
    )


def main() -> None:
    session = make_confluence_session()
    jobs, errors = get_enabled_jobs(session)
    for error in errors:
        print(f"Erreur de configuration : {error}")
    print(f"{len(jobs)} ligne(s) Enable à traiter.")
    succeeded = 0
    for job in jobs:
        try:
            process_release(session, job)
            succeeded += 1
        except (ValueError, OSError, requests.RequestException) as error:
            message = f"{job['project']}/{job['release']} : {error}"
            errors.append(message)
            print(f"Erreur : {message}")
    print(f"Bilan : {succeeded}/{len(jobs)} release(s) traitée(s), {len(errors)} erreur(s).")
    if errors:
        raise ValueError("Certaines lignes n'ont pas pu être traitées. Voir les erreurs ci-dessus.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Une erreur est survenue : {error}")
        sys.exit(1)
