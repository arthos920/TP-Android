#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from datetime import datetime
from html import escape, unescape

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# GLOBAL SETTINGS
# Remets ici exactement tes valeurs actuelles.
# ---------------------------------------------------------------------------

# ---------- JIRA ----------
JIRA_URL = ""
JIRA_USER = ""
JIRA_TOKEN = ""

# Proxy Jira dédié. Laisse vide si Jira n'utilise pas de proxy.
JIRA_PROXY_URL = ""

# ---------- CONFLUENCE ----------
CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""

# ---------- PROXY CONFLUENCE ----------
PROXY_URL = ""

# ---------- OTHER ----------
TEST_PLAN_KEY = ""
CONFLUENCE_PAGE_TITLE = "Dashboard night run automation"
CONFLUENCE_SPACE_KEY = "TEI"

# Champ Xray contenant les statistiques consolidées.
XRAY_STATS_CUSTOM_FIELD = "customfield_11527"

# Le tableau par Test Execution conserve au maximum 7 journées enregistrées.
MAX_TEST_EXECUTION_HISTORY_DAYS = 7

# Seuils de couleur du pourcentage PASS par Test Execution.
# >= 90 % : vert
# >= 75 % et < 90 % : orange
# < 75 % : rouge
PASS_RATE_GREEN_MIN = 90.0
PASS_RATE_ORANGE_MIN = 75.0

# Anchors persistantes du dashboard principal.
START_ANCHOR_NAME = "night-run-dashboard-start"
END_ANCHOR_NAME = "night-run-dashboard-end"

# Anchors persistantes de la table des Test Executions.
EXECUTIONS_START_ANCHOR_NAME = "night-run-executions-start"
EXECUTIONS_END_ANCHOR_NAME = "night-run-executions-end"


# ---------------------------------------------------------------------------
# HTTP HELPERS
# ---------------------------------------------------------------------------

def get_jira_proxies():
    if not JIRA_PROXY_URL:
        return None

    return {
        "http": JIRA_PROXY_URL,
        "https": JIRA_PROXY_URL,
    }


def jira_get(url, params=None):
    response = requests.get(
        url,
        params=params,
        auth=(JIRA_USER, JIRA_TOKEN),
        proxies=get_jira_proxies(),
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    return response


def make_session():
    """
    Session Confluence : proxy + Bearer token.
    """
    sess = requests.Session()
    sess.verify = False

    if PROXY_URL:
        sess.proxies = {
            "http": PROXY_URL,
            "https": PROXY_URL,
        }

    sess.headers.update(
        {
            "Authorization": f"Bearer {CONFLUENCE_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )

    return sess


# ---------------------------------------------------------------------------
# JIRA - STATS DU TEST PLAN
# La logique existante est conservée.
# ---------------------------------------------------------------------------

def parse_xray_stats(stats_data):
    stats = {}

    if not stats_data:
        return stats

    for status in stats_data.get("statuses", []):
        status_name = str(status.get("name", "")).upper().strip()

        if not status_name:
            continue

        stats[status_name] = {
            "count": status.get("statusCount", 0),
            "percent": status.get("statusPercent", 0),
        }

    return stats


def get_jira_stats(issue_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}"

    print(f"🔎 Requête JIRA ({JIRA_USER}) ...")

    resp = jira_get(url)
    data = resp.json()

    summary = data["fields"]["summary"]
    stats_data = data["fields"].get(XRAY_STATS_CUSTOM_FIELD)

    if not stats_data:
        raise ValueError(
            f"Champ {XRAY_STATS_CUSTOM_FIELD} absent ou vide."
        )

    return {
        "summary": summary,
        "stats": parse_xray_stats(stats_data),
    }


# ---------------------------------------------------------------------------
# XRAY - TEST EXECUTIONS DU TEST PLAN
# ---------------------------------------------------------------------------

ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$", re.IGNORECASE)


def extract_test_execution_keys(payload):
    """
    Accepte les différentes formes courantes de réponse Xray :
    - ["PROJ-1", "PROJ-2"]
    - [{"key": "PROJ-1"}, ...]
    - {"testExecutions": [...]}
    - {"results": [...]}
    """

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
            "Format inattendu pour la liste des Test Executions Xray."
        )

    keys = []

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

        if candidate and ISSUE_KEY_PATTERN.match(str(candidate)):
            keys.append(str(candidate).upper())

    # Supprime les doublons sans modifier l'ordre.
    return list(dict.fromkeys(keys))


def get_test_execution_keys(test_plan_key):
    url = (
        f"{JIRA_URL}/rest/raven/1.0/api/testplan/"
        f"{test_plan_key}/testexecution"
    )

    print(
        f"🔎 Récupération des Test Executions du Test Plan "
        f"{test_plan_key} ..."
    )

    response = jira_get(url)
    keys = extract_test_execution_keys(response.json())

    if not keys:
        raise ValueError(
            f"Aucune Test Execution trouvée pour {test_plan_key}."
        )

    print(
        f"✅ {len(keys)} Test Execution(s) trouvée(s) : "
        + ", ".join(keys)
    )

    return keys


def get_test_execution_run_pass_percent(test_execution_key):
    """
    Solution de secours si le champ de statistiques Xray n'est pas présent
    sur la Test Execution : compte les statuts des Test Runs.
    """

    url = (
        f"{JIRA_URL}/rest/raven/1.0/api/testexec/"
        f"{test_execution_key}/test"
    )

    response = jira_get(url)
    payload = response.json()

    if isinstance(payload, dict):
        test_runs = (
            payload.get("results")
            or payload.get("tests")
            or payload.get("entries")
            or []
        )
    elif isinstance(payload, list):
        test_runs = payload
    else:
        test_runs = []

    pass_count = 0
    total_count = 0

    for test_run in test_runs:
        if not isinstance(test_run, dict):
            continue

        status = test_run.get("status")

        if isinstance(status, dict):
            status = (
                status.get("name")
                or status.get("status")
                or status.get("key")
            )

        total_count += 1

        if str(status or "").upper().strip() == "PASS":
            pass_count += 1

    if total_count == 0:
        return 0.0

    return round(pass_count / total_count * 100, 2)


def get_one_test_execution_pass_stats(test_execution_key):
    """
    Retour :
    {
        "key": "PROJ-123",
        "summary": "Night Run Web",
        "pass_percent": 96.50
    }
    """

    url = f"{JIRA_URL}/rest/api/2/issue/{test_execution_key}"

    response = jira_get(
        url,
        params={
            "fields": f"summary,{XRAY_STATS_CUSTOM_FIELD}",
        },
    )

    issue = response.json()
    fields = issue.get("fields", {})

    summary = fields.get("summary", test_execution_key)
    stats_data = fields.get(XRAY_STATS_CUSTOM_FIELD)
    stats = parse_xray_stats(stats_data)

    if "PASS" in stats:
        pass_percent = float(stats["PASS"].get("percent", 0))
    else:
        print(
            f"⚠️ Champ de statistiques absent sur {test_execution_key}. "
            "Calcul depuis les Test Runs."
        )
        pass_percent = get_test_execution_run_pass_percent(
            test_execution_key
        )

    return {
        "key": test_execution_key,
        "summary": summary,
        "pass_percent": round(pass_percent, 2),
    }


def get_test_executions_pass_stats(test_plan_key):
    execution_keys = get_test_execution_keys(test_plan_key)
    results = []

    for execution_key in execution_keys:
        execution_result = get_one_test_execution_pass_stats(
            execution_key
        )
        results.append(execution_result)

        print(
            f"📊 {execution_key} : "
            f"{execution_result['pass_percent']:.2f} % PASS"
        )

    return results


# ---------------------------------------------------------------------------
# CONFLUENCE - PAGE
# La recherche et la récupération de la page restent inchangées.
# ---------------------------------------------------------------------------

def find_page_id(sess):
    """CQL search : retourne l'identifiant API de la page."""

    cql = (
        f'title ~ "{CONFLUENCE_PAGE_TITLE}" '
        f'AND space = "{CONFLUENCE_SPACE_KEY}"'
    )

    url = f"{CONFLUENCE_URL}/rest/api/search"
    params = {
        "cql": cql,
        "start": 0,
        "limit": 10,
    }

    print(f"🔎 Recherche Confluence (CQL) : {cql}")

    resp = sess.get(
        url,
        params=params,
        timeout=30,
    )
    resp.raise_for_status()

    results = resp.json().get("results", [])

    if not results:
        raise Exception(
            f"Page '{CONFLUENCE_PAGE_TITLE}' introuvable."
        )

    return results[0]["content"]["id"]


def get_page_info(sess, page_id):
    """
    Retourne (current_version, exact_title).
    """

    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"

    resp = sess.get(
        url,
        timeout=30,
    )

    if resp.status_code != 200:
        raise Exception(
            f"Erreur récupération page ({resp.status_code}) : {resp.text}"
        )

    data = resp.json()

    return data["version"]["number"], data["title"]


def get_page_body(sess, page_id):
    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"

    resp = sess.get(
        url,
        params={"expand": "body.storage"},
        timeout=30,
    )

    if resp.status_code != 200:
        raise Exception(
            f"Erreur récupération du contenu Confluence "
            f"({resp.status_code}) : {resp.text}"
        )

    data = resp.json()

    try:
        return data["body"]["storage"]["value"]
    except KeyError as exc:
        raise Exception(
            "Le body.storage de la page Confluence est absent."
        ) from exc


# ---------------------------------------------------------------------------
# VALUE HELPERS
# ---------------------------------------------------------------------------

def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_status(stats, status_name):
    value = stats.get(
        status_name,
        {
            "count": 0,
            "percent": 0,
        },
    )

    return {
        "count": to_int(value.get("count")),
        "percent": to_float(value.get("percent")),
    }


def html_to_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def build_pass_rate_badge(pass_percent):
    """
    Retourne une valeur colorée pour le tableau des Test Executions.

    Vert   : taux >= PASS_RATE_GREEN_MIN
    Orange : taux >= PASS_RATE_ORANGE_MIN
    Rouge  : taux < PASS_RATE_ORANGE_MIN
    """

    if pass_percent >= PASS_RATE_GREEN_MIN:
        background_color = "#E3FCEF"
        text_color = "#006644"
        label = "VERT"
    elif pass_percent >= PASS_RATE_ORANGE_MIN:
        background_color = "#FFF0B3"
        text_color = "#974F0C"
        label = "ORANGE"
    else:
        background_color = "#FFEBE6"
        text_color = "#BF2600"
        label = "ROUGE"

    return (
        f'<span title="{label}" '
        f'style="display:inline-block;'
        f'min-width:72px;'
        f'padding:3px 8px;'
        f'border-radius:12px;'
        f'background-color:{background_color};'
        f'color:{text_color};'
        f'font-weight:bold;'
        f'text-align:center;">'
        f'{pass_percent:.2f} %'
        f'</span>'
    )


# ---------------------------------------------------------------------------
# PERSISTENT ANCHORS
# ---------------------------------------------------------------------------

def build_anchor_macro(anchor_name):
    return f"""
<ac:structured-macro ac:name="anchor" ac:schema-version="1">
    <ac:parameter ac:name="">{escape(anchor_name)}</ac:parameter>
</ac:structured-macro>
""".strip()


def anchor_macro_pattern(anchor_name):
    return (
        r'<ac:structured-macro\b'
        r'(?=[^>]*\bac:name="anchor")'
        r'[^>]*>'
        r'.*?'
        r'<ac:parameter\b[^>]*\bac:name=""[^>]*>'
        r'\s*'
        + re.escape(anchor_name)
        + r'\s*'
        r'</ac:parameter>'
        r'.*?'
        r'</ac:structured-macro>'
    )


def anchored_block_pattern(start_anchor, end_anchor):
    return re.compile(
        anchor_macro_pattern(start_anchor)
        + r".*?"
        + anchor_macro_pattern(end_anchor),
        flags=re.DOTALL | re.IGNORECASE,
    )


def dashboard_block_pattern():
    return anchored_block_pattern(
        START_ANCHOR_NAME,
        END_ANCHOR_NAME,
    )


def executions_block_pattern():
    return anchored_block_pattern(
        EXECUTIONS_START_ANCHOR_NAME,
        EXECUTIONS_END_ANCHOR_NAME,
    )


def extract_managed_blocks(page_body):
    return dashboard_block_pattern().findall(page_body)


# ---------------------------------------------------------------------------
# HISTORIQUE GÉNÉRAL PASS / FAIL / TODO
# ---------------------------------------------------------------------------

def add_history_value(
    history,
    date_value,
    pass_count,
    fail_count,
    todo_count,
    pass_rate,
):
    try:
        parsed_date = datetime.strptime(
            date_value,
            "%d/%m/%Y",
        )
    except ValueError:
        return

    day_iso = parsed_date.strftime("%Y-%m-%d")

    history[day_iso] = {
        "pass": int(pass_count),
        "fail": int(fail_count),
        "todo": int(todo_count),
        "pass_rate": float(
            str(pass_rate).replace(",", ".")
        ),
    }


def parse_general_history_table(block, history):
    heading_match = re.search(
        r"<h2>\s*Historique général\s*</h2>\s*"
        r"(<table\b.*?</table>)",
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not heading_match:
        return

    table_html = heading_match.group(1)

    row_pattern = re.compile(
        r"<tr>\s*"
        r"<td[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</td>\s*"
        r"<td[^>]*>\s*(\d+)\s*</td>\s*"
        r"<td[^>]*>\s*(\d+)\s*</td>\s*"
        r"<td[^>]*>\s*(\d+)\s*</td>\s*"
        r"<td[^>]*>\s*([\d.,]+)\s*%\s*</td>\s*"
        r"</tr>",
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in row_pattern.finditer(table_html):
        add_history_value(
            history,
            *match.groups(),
        )


def parse_legacy_daily_tables(page_body, history):
    daily_pattern = re.compile(
        r"<h3>\s*Night run du\s+"
        r"(\d{2}/\d{2}/\d{4})\s*</h3>\s*"
        r"(<table\b.*?</table>)",
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in daily_pattern.finditer(page_body):
        display_day = match.group(1)
        table_html = match.group(2)

        def read_count(label):
            label_match = re.search(
                rf"<td[^>]*>\s*{re.escape(label)}\s*</td>\s*"
                r"<td[^>]*>\s*(\d+)\s*</td>",
                table_html,
                flags=re.DOTALL | re.IGNORECASE,
            )
            return int(label_match.group(1)) if label_match else 0

        rate_match = re.search(
            r"<td[^>]*>\s*"
            r"(?:<strong>)?\s*Taux de réussite\s*(?:</strong>)?"
            r"\s*</td>\s*"
            r"<td[^>]*>.*?"
            r"([\d.,]+)\s*%",
            table_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        pass_rate = (
            float(rate_match.group(1).replace(",", "."))
            if rate_match
            else 0.0
        )

        add_history_value(
            history,
            display_day,
            read_count("PASS"),
            read_count("FAIL"),
            read_count("TODO"),
            pass_rate,
        )


def parse_legacy_history_rows(page_body, history):
    row_pattern = re.compile(
        r'<tr[^>]*(?:data-night-run-day="[^"]+")?[^>]*>\s*'
        r'<td[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</td>\s*'
        r'<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*([\d.,]+)\s*%\s*</td>\s*'
        r'</tr>',
        flags=re.DOTALL | re.IGNORECASE,
    )

    for match in row_pattern.finditer(page_body):
        add_history_value(
            history,
            *match.groups(),
        )


def parse_existing_history(page_body):
    history = {}

    for block in extract_managed_blocks(page_body):
        parse_general_history_table(
            block,
            history,
        )

    parse_legacy_daily_tables(
        page_body,
        history,
    )
    parse_legacy_history_rows(
        page_body,
        history,
    )

    return history


# ---------------------------------------------------------------------------
# HISTORIQUE DES TEST EXECUTIONS - 7 JOURS
#
# Structure :
# {
#   "2026-07-16": {
#       "PROJ-123": {"summary": "...", "pass_percent": 95.0}
#   }
# }
# ---------------------------------------------------------------------------

def parse_execution_history_table(page_body):
    history = {}

    blocks = executions_block_pattern().findall(page_body)

    for block in blocks:
        table_match = re.search(
            r"<table\b.*?</table>",
            block,
            flags=re.DOTALL | re.IGNORECASE,
        )

        if not table_match:
            continue

        table_html = table_match.group(0)

        header_row_match = re.search(
            r"<thead>.*?<tr>(.*?)</tr>.*?</thead>",
            table_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        if not header_row_match:
            continue

        header_cells = re.findall(
            r"<th[^>]*>(.*?)</th>",
            header_row_match.group(1),
            flags=re.DOTALL | re.IGNORECASE,
        )

        if len(header_cells) < 2:
            continue

        days = []

        for header_cell in header_cells[1:]:
            date_text = html_to_text(header_cell)

            try:
                day_iso = datetime.strptime(
                    date_text,
                    "%d/%m/%Y",
                ).strftime("%Y-%m-%d")
            except ValueError:
                day_iso = None

            days.append(day_iso)

        tbody_match = re.search(
            r"<tbody>(.*?)</tbody>",
            table_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        if not tbody_match:
            continue

        row_html_list = re.findall(
            r"<tr>(.*?)</tr>",
            tbody_match.group(1),
            flags=re.DOTALL | re.IGNORECASE,
        )

        for row_html in row_html_list:
            cells = re.findall(
                r"<td[^>]*>(.*?)</td>",
                row_html,
                flags=re.DOTALL | re.IGNORECASE,
            )

            if not cells:
                continue

            first_cell_text = html_to_text(cells[0])
            key_match = re.search(
                r"\b([A-Z][A-Z0-9_]*-\d+)\b",
                first_cell_text,
                flags=re.IGNORECASE,
            )

            if not key_match:
                continue

            execution_key = key_match.group(1).upper()
            summary = first_cell_text.replace(
                key_match.group(1),
                "",
                1,
            ).strip(" -–—:")

            if not summary:
                summary = execution_key

            for index, cell in enumerate(cells[1:]):
                if index >= len(days) or not days[index]:
                    continue

                value_text = html_to_text(cell)

                if not value_text or value_text in {"-", "—"}:
                    continue

                percent_match = re.search(
                    r"([\d.,]+)",
                    value_text,
                )

                if not percent_match:
                    continue

                pass_percent = float(
                    percent_match.group(1).replace(",", ".")
                )

                history.setdefault(
                    days[index],
                    {},
                )[execution_key] = {
                    "summary": summary,
                    "pass_percent": pass_percent,
                }

    return history


def keep_last_execution_history_days(history):
    kept_days = sorted(history)[
        -MAX_TEST_EXECUTION_HISTORY_DAYS:
    ]

    return {
        day: history[day]
        for day in kept_days
    }


def update_execution_history(
    page_body,
    today_iso,
    current_execution_stats,
):
    history = parse_execution_history_table(page_body)

    # Le run du jour remplace entièrement le snapshot du même jour.
    history[today_iso] = {
        item["key"]: {
            "summary": item["summary"],
            "pass_percent": item["pass_percent"],
        }
        for item in current_execution_stats
    }

    return keep_last_execution_history_days(history)


def build_execution_history_table(history):
    if not history:
        return "<p>Aucune donnée de Test Execution disponible.</p>"

    ordered_days = sorted(history)

    execution_metadata = {}

    for day in ordered_days:
        for execution_key, result in history[day].items():
            execution_metadata[execution_key] = result.get(
                "summary",
                execution_key,
            )

    ordered_execution_keys = sorted(
        execution_metadata,
        key=lambda key: (
            execution_metadata[key].lower(),
            key,
        ),
    )

    header_cells = []

    for day in ordered_days:
        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        header_cells.append(
            f'<th style="padding:8px;text-align:center;">'
            f"{escape(display_day)}</th>"
        )

    rows = []

    for execution_key in ordered_execution_keys:
        summary = execution_metadata[execution_key]
        safe_key = escape(execution_key)
        safe_summary = escape(summary)
        jira_link = (
            f"{escape(JIRA_URL.rstrip('/'))}/browse/{safe_key}"
        )

        value_cells = []

        for day in ordered_days:
            result = history[day].get(execution_key)

            if result is None:
                value_cells.append(
                    '<td style="padding:8px;text-align:center;">—</td>'
                )
            else:
                pass_percent = float(result["pass_percent"])
                pass_rate_badge = build_pass_rate_badge(
                    pass_percent
                )

                value_cells.append(
                    '<td style="padding:8px;text-align:center;">'
                    f"{pass_rate_badge}"
                    "</td>"
                )

        rows.append(
            f"""
<tr>
    <td style="padding:8px;">
        <a href="{jira_link}"><code>{safe_key}</code></a>
        - {safe_summary}
    </td>
    {''.join(value_cells)}
</tr>
""".strip()
        )

    start_anchor = build_anchor_macro(
        EXECUTIONS_START_ANCHOR_NAME
    )
    end_anchor = build_anchor_macro(
        EXECUTIONS_END_ANCHOR_NAME
    )

    return f"""
{start_anchor}

<h2>Pourcentage PASS par Test Execution — 7 derniers jours</h2>

<p>
    Une ligne par Test Execution. Les colonnes correspondent aux
    sept dernières journées enregistrées.
</p>

<table border="1" style="width:100%;border-collapse:collapse;">
    <thead>
        <tr>
            <th style="padding:8px;">Test Execution</th>
            {''.join(header_cells)}
        </tr>
    </thead>
    <tbody>
        {''.join(rows)}
    </tbody>
</table>

{end_anchor}
""".strip()


# ---------------------------------------------------------------------------
# GRAPHIQUE GÉNÉRAL PASS / FAIL
# ---------------------------------------------------------------------------

def build_chart_macro(history):
    ordered_days = sorted(history)

    if not ordered_days:
        return "<p>Aucune donnée disponible pour le graphique.</p>"

    date_headers = []
    pass_values = []
    fail_values = []

    for day in ordered_days:
        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        date_headers.append(
            f"<th>{escape(display_day)}</th>"
        )
        pass_values.append(
            f"<td>{history[day]['pass']}</td>"
        )
        fail_values.append(
            f"<td>{history[day]['fail']}</td>"
        )

    return f"""
<ac:structured-macro ac:name="chart" ac:schema-version="1">
    <ac:parameter ac:name="type">line</ac:parameter>
    <ac:parameter ac:name="title">Évolution quotidienne des tests PASS / FAIL</ac:parameter>
    <ac:parameter ac:name="legend">true</ac:parameter>
    <ac:parameter ac:name="dataOrientation">horizontal</ac:parameter>
    <ac:parameter ac:name="dataDisplay">false</ac:parameter>
    <ac:parameter ac:name="showShapes">true</ac:parameter>
    <ac:parameter ac:name="width">1100</ac:parameter>
    <ac:parameter ac:name="height">420</ac:parameter>
    <ac:parameter ac:name="xLabel">Date</ac:parameter>
    <ac:parameter ac:name="yLabel">Nombre de tests</ac:parameter>
    <ac:parameter ac:name="categoryLabelPosition">down45</ac:parameter>
    <ac:rich-text-body>
        <table>
            <tbody>
                <tr>
                    <th>Statut</th>
                    {''.join(date_headers)}
                </tr>
                <tr>
                    <th>PASS</th>
                    {''.join(pass_values)}
                </tr>
                <tr>
                    <th>FAIL</th>
                    {''.join(fail_values)}
                </tr>
            </tbody>
        </table>
    </ac:rich-text-body>
</ac:structured-macro>
""".strip()


def build_general_history_table(history):
    rows = []

    for day in sorted(history, reverse=True):
        result = history[day]

        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        rows.append(
            f"""
<tr>
    <td style="padding:8px;">{escape(display_day)}</td>
    <td style="padding:8px;text-align:center;">{result["pass"]}</td>
    <td style="padding:8px;text-align:center;">{result["fail"]}</td>
    <td style="padding:8px;text-align:center;">{result["todo"]}</td>
    <td style="padding:8px;text-align:center;">{result["pass_rate"]:.2f} %</td>
</tr>
""".strip()
        )

    return f"""
<h2>Historique général</h2>

<table border="1" style="width:100%;border-collapse:collapse;">
    <thead>
        <tr>
            <th style="padding:8px;">Date</th>
            <th style="padding:8px;text-align:center;">PASS</th>
            <th style="padding:8px;text-align:center;">FAIL</th>
            <th style="padding:8px;text-align:center;">TODO</th>
            <th style="padding:8px;text-align:center;">Taux de réussite</th>
        </tr>
    </thead>
    <tbody>
        {''.join(rows)}
    </tbody>
</table>
""".strip()


# ---------------------------------------------------------------------------
# BUILD DASHBOARD
# ---------------------------------------------------------------------------

def build_dashboard_html(
    summary,
    stats,
    execution_stats,
    page_body,
):
    pass_status = get_status(stats, "PASS")
    fail_status = get_status(stats, "FAIL")
    todo_status = get_status(stats, "TODO")

    pass_count = pass_status["count"]
    fail_count = fail_status["count"]
    todo_count = todo_status["count"]

    completed_count = pass_count + fail_count

    if completed_count:
        pass_rate = round(
            pass_count / completed_count * 100,
            2,
        )
    else:
        pass_rate = 0.0

    now = datetime.now().astimezone()
    today_iso = now.strftime("%Y-%m-%d")
    last_update = now.strftime("%d/%m/%Y à %H:%M")

    # Historique général.
    history = parse_existing_history(page_body)

    history[today_iso] = {
        "pass": pass_count,
        "fail": fail_count,
        "todo": todo_count,
        "pass_rate": pass_rate,
    }

    # Historique par Test Execution limité à 7 journées.
    execution_history = update_execution_history(
        page_body,
        today_iso,
        execution_stats,
    )

    chart_macro = build_chart_macro(history)
    execution_history_table = build_execution_history_table(
        execution_history
    )
    general_history_table = build_general_history_table(
        history
    )

    safe_summary = escape(str(summary))
    safe_test_plan_key = escape(str(TEST_PLAN_KEY))
    safe_jira_url = escape(str(JIRA_URL).rstrip("/"))

    start_anchor = build_anchor_macro(
        START_ANCHOR_NAME
    )
    end_anchor = build_anchor_macro(
        END_ANCHOR_NAME
    )

    return f"""
{start_anchor}

<h1>Dashboard Night Run Automation</h1>

<p>
    <strong>Test Plan :</strong>
    {safe_summary}
    (
        <a href="{safe_jira_url}/browse/{safe_test_plan_key}">
            <code>{safe_test_plan_key}</code>
        </a>
    )
</p>

<p>
    <em>Dernière mise à jour automatique : {escape(last_update)}</em>
</p>

<h2>Évolution globale PASS / FAIL</h2>

{chart_macro}

<p><br /></p>

{execution_history_table}

<p><br /></p>

{general_history_table}

{end_anchor}
""".strip()


# ---------------------------------------------------------------------------
# NETTOYAGE DES ANCIENNES VERSIONS
# ---------------------------------------------------------------------------

def remove_legacy_daily_dashboard_blocks(page_body):
    legacy_pattern = re.compile(
        r"<h1>\s*Dashboard Night Run Automation\s*</h1>"
        r".*?"
        r"<h2>\s*Résultats journaliers\s*</h2>"
        r"(?:"
        r"\s*(?:<!--.*?-->\s*)?"
        r"<h3>\s*Night run du\s+\d{2}/\d{2}/\d{4}\s*</h3>"
        r"\s*<table\b.*?</table>"
        r"\s*(?:<p>\s*<br\s*/?>\s*</p>)?"
        r")+",
        flags=re.DOTALL | re.IGNORECASE,
    )

    return legacy_pattern.subn(
        "",
        page_body,
    )


def remove_legacy_single_history_blocks(page_body):
    legacy_pattern = re.compile(
        r"<h1>\s*Dashboard Night Run Automation\s*</h1>"
        r".*?"
        r"<h[23]>\s*Historique quotidien\s*</h[23]>"
        r"\s*<table\b.*?</table>"
        r"(?:\s*<p>.*?Dernière mise à jour automatique.*?</p>)?",
        flags=re.DOTALL | re.IGNORECASE,
    )

    return legacy_pattern.subn(
        "",
        page_body,
    )


# ---------------------------------------------------------------------------
# MERGE
# ---------------------------------------------------------------------------

def merge_dashboard_into_page(existing_body, dashboard_html):
    body = existing_body

    body, managed_count = dashboard_block_pattern().subn(
        "",
        body,
    )

    body, legacy_daily_count = remove_legacy_daily_dashboard_blocks(
        body
    )
    body, legacy_history_count = remove_legacy_single_history_blocks(
        body
    )

    removed_count = (
        managed_count
        + legacy_daily_count
        + legacy_history_count
    )

    print(
        f"🧹 Blocs dashboard supprimés avant reconstruction : "
        f"{removed_count}"
    )

    remaining_body = body.strip()

    if not remaining_body:
        return dashboard_html

    return (
        dashboard_html
        + "<p><br /></p>"
        + remaining_body
    )


# ---------------------------------------------------------------------------
# CONFLUENCE - UPDATE PAGE
# ---------------------------------------------------------------------------

def update_confluence_page(
    sess,
    page_id,
    html,
    current_version,
    title,
):
    """PUT : met à jour la page avec version + 1."""

    url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"

    payload = {
        "id": str(page_id),
        "type": "page",
        "title": title,
        "version": {
            "number": current_version + 1,
        },
        "body": {
            "storage": {
                "value": html,
                "representation": "storage",
            }
        },
    }

    print(
        f"📤 Envoi du PUT Confluence "
        f"(version {current_version + 1}) ..."
    )

    resp = sess.put(
        url,
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201, 204):
        raise Exception(
            f"Erreur update Confluence "
            f"({resp.status_code}) : {resp.text}"
        )

    print("✅ Dashboard mis à jour avec succès.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sess = make_session()

    try:
        # 1. Statistiques consolidées du Test Plan.
        print("🚀 Extraction des statistiques JIRA ...")

        jira_info = get_jira_stats(TEST_PLAN_KEY)
        summary = jira_info["summary"]
        stats = jira_info["stats"]

        print(f"📊 Summary : {summary}")
        print(f"📊 Stats : {stats}")

        # 2. Pourcentage PASS de chaque Test Execution liée au Test Plan.
        execution_stats = get_test_executions_pass_stats(
            TEST_PLAN_KEY
        )

        # 3. Recherche de la page Confluence.
        page_id = find_page_id(sess)

        print(f"✅ Page trouvée - ID : {page_id}")

        # 4. Version et titre exacts.
        version, exact_title = get_page_info(
            sess,
            page_id,
        )

        print(
            f"🔎 Page '{exact_title}' "
            f"- version actuelle : {version}"
        )

        # 5. Contenu actuel.
        current_body = get_page_body(
            sess,
            page_id,
        )

        # 6. Construction du dashboard.
        dashboard_html = build_dashboard_html(
            summary,
            stats,
            execution_stats,
            current_body,
        )

        # 7. Remplacement du dashboard unique.
        full_page_body = merge_dashboard_into_page(
            current_body,
            dashboard_html,
        )

        # 8. Mise à jour Confluence.
        update_confluence_page(
            sess,
            page_id,
            full_page_body,
            version,
            exact_title,
        )

    except Exception as error:
        print(f"❌ Une erreur est survenue : {error}")
        sys.exit(1)