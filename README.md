#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# GLOBAL SETTINGS
# Garde ici tes valeurs actuelles de connexion.
# ---------------------------------------------------------------------------

# ---------- JIRA ----------
JIRA_URL = ""
JIRA_USER = ""
JIRA_TOKEN = ""

# ---------- CONFLUENCE ----------
CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""

# ---------- PROXY ----------
PROXY_URL = ""

# ---------- OTHER ----------
TEST_PLAN_KEY = ""
CONFLUENCE_PAGE_TITLE = "Dashboard night run automation"
CONFLUENCE_SPACE_KEY = "TEI"
TIMEZONE = "Europe/Paris"

# Champ Jira/Xray qui contient les statistiques du Test Plan.
XRAY_STATS_CUSTOM_FIELD = "customfield_11527"

# Marqueurs utilisés pour remplacer uniquement le dashboard géré par ce script.
# Tout ce qui se trouve en dehors de ces marqueurs reste intact.
DASHBOARD_START = "<!-- NIGHT_RUN_DASHBOARD_START -->"
DASHBOARD_END = "<!-- NIGHT_RUN_DASHBOARD_END -->"


# ---------------------------------------------------------------------------
# SESSION HELPER
# Proxy + Bearer token Confluence
# ---------------------------------------------------------------------------

def make_session():
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
# JIRA - STATS
# Cette fonction conserve la logique montrée dans ton code.
# ---------------------------------------------------------------------------

def get_jira_stats(issue_key):
    url = f"{JIRA_URL}/rest/api/2/issue/{issue_key}"
    auth = (JIRA_USER, JIRA_TOKEN)

    print(f"🔎 Requête JIRA ({JIRA_USER}) ...")

    resp = requests.get(
        url,
        auth=auth,
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    summary = data["fields"]["summary"]
    stats_data = data["fields"].get(XRAY_STATS_CUSTOM_FIELD)

    if not stats_data:
        raise ValueError(
            f"Champ {XRAY_STATS_CUSTOM_FIELD} absent ou vide."
        )

    stats = {}

    for status in stats_data.get("statuses", []):
        stats[status["name"]] = {
            "count": status["statusCount"],
            "percent": status["statusPercent"],
        }

    return {
        "summary": summary,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# CONFLUENCE - SEARCH PAGE
# Cette fonction conserve la logique montrée dans ton code.
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


# ---------------------------------------------------------------------------
# CONFLUENCE - PAGE INFO
# Cette fonction conserve la logique montrée dans ton code.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CONFLUENCE - GET CURRENT BODY
# Nécessaire pour conserver les autres tableaux et contenus de la page.
# ---------------------------------------------------------------------------

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
# HELPERS - VALUES
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


# ---------------------------------------------------------------------------
# HISTORY - READ EXISTING DAILY SNAPSHOTS
# ---------------------------------------------------------------------------

def extract_managed_dashboard(page_body):
    pattern = re.compile(
        re.escape(DASHBOARD_START)
        + r".*?"
        + re.escape(DASHBOARD_END),
        flags=re.DOTALL,
    )

    match = pattern.search(page_body)

    if not match:
        return ""

    return match.group(0)


def parse_existing_history(page_body):
    """
    Lit uniquement les lignes historiques ajoutées par ce script.

    Retour :
    {
        "2026-07-16": {
            "pass": 120,
            "fail": 4,
            "todo": 2,
            "pass_rate": 96.77
        }
    }
    """

    managed_dashboard = extract_managed_dashboard(page_body)

    if not managed_dashboard:
        return {}

    history = {}

    row_pattern = re.compile(
        r'<tr data-night-run-day="([^"]+)">\s*'
        r'<td[^>]*>.*?</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>([\d.,]+)\s*%</td>\s*'
        r'</tr>',
        flags=re.DOTALL,
    )

    for match in row_pattern.finditer(managed_dashboard):
        day, pass_count, fail_count, todo_count, pass_rate = match.groups()

        history[day] = {
            "pass": int(pass_count),
            "fail": int(fail_count),
            "todo": int(todo_count),
            "pass_rate": float(pass_rate.replace(",", ".")),
        }

    return history


# ---------------------------------------------------------------------------
# HTML - HISTORY TABLE
# ---------------------------------------------------------------------------

def build_history_rows(history):
    rows = []

    for day in sorted(history):
        result = history[day]

        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        rows.append(
            f"""
<tr data-night-run-day="{escape(day)}">
    <td style="padding:8px;">{escape(display_day)}</td>
    <td style="padding:8px;text-align:center;">{result["pass"]}</td>
    <td style="padding:8px;text-align:center;">{result["fail"]}</td>
    <td style="padding:8px;text-align:center;">{result["todo"]}</td>
    <td style="padding:8px;text-align:center;">{result["pass_rate"]:.2f} %</td>
</tr>
""".strip()
        )

    return "\n".join(rows)


# ---------------------------------------------------------------------------
# HTML - CHART DATA
# Le tableau placé dans la macro Chart ne contient que Date / PASS / FAIL.
# ---------------------------------------------------------------------------

def build_chart_rows(history):
    rows = []

    for day in sorted(history):
        result = history[day]

        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        rows.append(
            f"""
<tr>
    <td>{escape(display_day)}</td>
    <td>{result["pass"]}</td>
    <td>{result["fail"]}</td>
</tr>
""".strip()
        )

    return "\n".join(rows)


def build_chart_macro(history):
    chart_rows = build_chart_rows(history)

    return f"""
<ac:structured-macro ac:name="chart" ac:schema-version="1">
    <ac:parameter ac:name="type">line</ac:parameter>
    <ac:parameter ac:name="title">Évolution quotidienne des tests PASS / FAIL</ac:parameter>
    <ac:parameter ac:name="legend">true</ac:parameter>
    <ac:parameter ac:name="displayData">false</ac:parameter>
    <ac:parameter ac:name="showShapes">true</ac:parameter>
    <ac:rich-text-body>
        <table>
            <tbody>
                <tr>
                    <th>Date</th>
                    <th>PASS</th>
                    <th>FAIL</th>
                </tr>
                {chart_rows}
            </tbody>
        </table>
    </ac:rich-text-body>
</ac:structured-macro>
""".strip()


# ---------------------------------------------------------------------------
# HTML - BUILD MANAGED DASHBOARD
# ---------------------------------------------------------------------------

def build_dashboard_html(summary, stats, page_body):
    """
    Construit uniquement le bloc géré par le script.

    Les autres tableaux et contenus de la page sont conservés par
    merge_dashboard_into_page().
    """

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

    now = datetime.now(
        ZoneInfo(TIMEZONE)
    )

    today_iso = now.strftime("%Y-%m-%d")
    last_update = now.strftime("%d/%m/%Y à %H:%M")

    history = parse_existing_history(page_body)

    # Une seule entrée par jour :
    # si le script est relancé le même jour, l'état du jour est remplacé.
    history[today_iso] = {
        "pass": pass_count,
        "fail": fail_count,
        "todo": todo_count,
        "pass_rate": pass_rate,
    }

    history_rows = build_history_rows(history)
    chart_macro = build_chart_macro(history)

    safe_summary = escape(str(summary))
    safe_test_plan_key = escape(str(TEST_PLAN_KEY))

    return f"""
{DASHBOARD_START}

<h1>Dashboard Night Run Automation</h1>

<p>
    <strong>Test Plan :</strong>
    {safe_summary}
    (<a href="{escape(JIRA_URL)}/browse/{safe_test_plan_key}">
        <code>{safe_test_plan_key}</code>
    </a>)
</p>

<h2>État actuel du banc de test</h2>

<table border="1" style="width:100%;border-collapse:collapse;">
    <thead>
        <tr>
            <th style="padding:8px;">Statut</th>
            <th style="padding:8px;text-align:center;">Nombre</th>
            <th style="padding:8px;text-align:center;">Pourcentage Xray</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td style="padding:8px;">PASS</td>
            <td style="padding:8px;text-align:center;">{pass_count}</td>
            <td style="padding:8px;text-align:center;">{pass_status["percent"]:.2f} %</td>
        </tr>
        <tr>
            <td style="padding:8px;">FAIL</td>
            <td style="padding:8px;text-align:center;">{fail_count}</td>
            <td style="padding:8px;text-align:center;">{fail_status["percent"]:.2f} %</td>
        </tr>
        <tr>
            <td style="padding:8px;">TODO</td>
            <td style="padding:8px;text-align:center;">{todo_count}</td>
            <td style="padding:8px;text-align:center;">{todo_status["percent"]:.2f} %</td>
        </tr>
    </tbody>
</table>

<p>
    <strong>Taux de réussite sur les tests terminés :</strong>
    {pass_rate:.2f} %
</p>

<h2>Évolution dans le temps</h2>

{chart_macro}

<h2>Historique quotidien</h2>

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
        {history_rows}
    </tbody>
</table>

<p>
    <em>Dernière mise à jour automatique : {escape(last_update)}</em>
</p>

{DASHBOARD_END}
""".strip()


# ---------------------------------------------------------------------------
# MERGE - PRESERVE OTHER TABLES AND CONTENT
# ---------------------------------------------------------------------------

def merge_dashboard_into_page(existing_body, dashboard_html):
    """
    Si le bloc existe déjà, il est remplacé.

    Sinon, il est ajouté à la fin de la page.

    Aucun autre tableau ou contenu Confluence n'est supprimé.
    """

    pattern = re.compile(
        re.escape(DASHBOARD_START)
        + r".*?"
        + re.escape(DASHBOARD_END),
        flags=re.DOTALL,
    )

    if pattern.search(existing_body):
        return pattern.sub(
            dashboard_html,
            existing_body,
            count=1,
        )

    separator = "<p><br /></p>" if existing_body.strip() else ""

    return existing_body + separator + dashboard_html


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
        # 1. JIRA - récupération de l'état consolidé du Test Plan
        print("🚀 Extraction des statistiques JIRA ...")

        jira_info = get_jira_stats(TEST_PLAN_KEY)
        summary = jira_info["summary"]
        stats = jira_info["stats"]

        print(f"📊 Summary : {summary}")
        print(f"📊 Stats : {stats}")

        # 2. CONFLUENCE - recherche de la page
        page_id = find_page_id(sess)

        print(f"✅ Page trouvée - ID : {page_id}")

        # 3. Version et titre exacts
        version, exact_title = get_page_info(
            sess,
            page_id,
        )

        print(
            f"🔎 Page '{exact_title}' "
            f"- version actuelle : {version}"
        )

        # 4. Contenu actuel de la page
        current_body = get_page_body(
            sess,
            page_id,
        )

        # 5. Bloc dashboard avec snapshot journalier
        dashboard_html = build_dashboard_html(
            summary,
            stats,
            current_body,
        )

        # 6. Fusion avec la page existante
        # Les autres tableaux restent intacts.
        full_page_body = merge_dashboard_into_page(
            current_body,
            dashboard_html,
        )

        # 7. Mise à jour Confluence
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