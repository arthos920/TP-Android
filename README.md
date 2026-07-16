#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from datetime import datetime
from html import escape

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

# ---------- CONFLUENCE ----------
CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""

# ---------- PROXY ----------
PROXY_URL = ""

# ---------- OTHER ----------
TEST_PLAN_KEY = ""
CONFLUENCE_PAGE_TITLE = "Dashboard night run automation"
CONFLUENCE_SPACE_KEY = "TEI"

# Champ Xray contenant les statistiques consolidées du Test Plan.
XRAY_STATS_CUSTOM_FIELD = "customfield_11527"

# Le script ne modifie que le contenu placé entre ces deux marqueurs.
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
# Logique de récupération Jira conservée.
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
# Logique de recherche de la page conservée.
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
# Logique de récupération de la page conservée.
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
# CONFLUENCE - CURRENT BODY
# Sert uniquement à préserver les autres tableaux de la page.
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


# ---------------------------------------------------------------------------
# HISTORY - READ EXISTING SNAPSHOTS
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
    Récupère les résultats des jours précédents.

    La fonction sait lire :
    - le nouveau format avec NIGHT_RUN_SNAPSHOT ;
    - l'ancien tableau historique créé par la version précédente.
    """

    managed_dashboard = extract_managed_dashboard(page_body)

    if not managed_dashboard:
        return {}

    history = {}

    # Nouveau format : commentaire technique placé avant chaque tableau journalier.
    snapshot_pattern = re.compile(
        r"<!--\s*NIGHT_RUN_SNAPSHOT\s+"
        r"date=(\d{4}-\d{2}-\d{2})\s+"
        r"pass=(\d+)\s+"
        r"fail=(\d+)\s+"
        r"todo=(\d+)\s+"
        r"rate=([\d.,]+)\s*-->",
        flags=re.IGNORECASE,
    )

    for match in snapshot_pattern.finditer(managed_dashboard):
        day, pass_count, fail_count, todo_count, pass_rate = match.groups()

        history[day] = {
            "pass": int(pass_count),
            "fail": int(fail_count),
            "todo": int(todo_count),
            "pass_rate": float(pass_rate.replace(",", ".")),
        }

    # Compatibilité avec le tableau historique de la version précédente.
    old_row_pattern = re.compile(
        r'<tr data-night-run-day="([^"]+)">\s*'
        r'<td[^>]*>.*?</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>(\d+)</td>\s*'
        r'<td[^>]*>([\d.,]+)\s*%</td>\s*'
        r'</tr>',
        flags=re.DOTALL,
    )

    for match in old_row_pattern.finditer(managed_dashboard):
        day, pass_count, fail_count, todo_count, pass_rate = match.groups()

        if day not in history:
            history[day] = {
                "pass": int(pass_count),
                "fail": int(fail_count),
                "todo": int(todo_count),
                "pass_rate": float(pass_rate.replace(",", ".")),
            }

    return history


# ---------------------------------------------------------------------------
# CHART
# Un seul graphique, avec deux séries : PASS et FAIL.
# Les dates deviennent les catégories de l'axe horizontal.
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


# ---------------------------------------------------------------------------
# DAILY TABLES
# Un tableau séparé par journée, du plus récent au plus ancien.
# ---------------------------------------------------------------------------

def build_daily_tables(history):
    blocks = []

    for day in sorted(history, reverse=True):
        result = history[day]

        display_day = datetime.strptime(
            day,
            "%Y-%m-%d",
        ).strftime("%d/%m/%Y")

        snapshot = (
            f"<!-- NIGHT_RUN_SNAPSHOT "
            f"date={day} "
            f"pass={result['pass']} "
            f"fail={result['fail']} "
            f"todo={result['todo']} "
            f"rate={result['pass_rate']:.2f} -->"
        )

        blocks.append(
            f"""
{snapshot}

<h3>Night run du {escape(display_day)}</h3>

<table border="1" style="width:100%;border-collapse:collapse;">
    <thead>
        <tr>
            <th style="padding:8px;">Statut</th>
            <th style="padding:8px;text-align:center;">Nombre</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td style="padding:8px;">PASS</td>
            <td style="padding:8px;text-align:center;">{result["pass"]}</td>
        </tr>
        <tr>
            <td style="padding:8px;">FAIL</td>
            <td style="padding:8px;text-align:center;">{result["fail"]}</td>
        </tr>
        <tr>
            <td style="padding:8px;">TODO</td>
            <td style="padding:8px;text-align:center;">{result["todo"]}</td>
        </tr>
        <tr>
            <td style="padding:8px;"><strong>Taux de réussite</strong></td>
            <td style="padding:8px;text-align:center;">
                <strong>{result["pass_rate"]:.2f} %</strong>
            </td>
        </tr>
    </tbody>
</table>
""".strip()
        )

    return "\n<p><br /></p>\n".join(blocks)


# ---------------------------------------------------------------------------
# BUILD DASHBOARD
# En haut : le graphique général.
# En dessous : uniquement les tableaux journaliers.
# ---------------------------------------------------------------------------

def build_dashboard_html(summary, stats, page_body):
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

    # Utilise directement le fuseau horaire configuré sur Windows / le runner.
    # Cela évite l'erreur ZoneInfo "No time zone found".
    now = datetime.now().astimezone()

    today_iso = now.strftime("%Y-%m-%d")
    last_update = now.strftime("%d/%m/%Y à %H:%M")

    history = parse_existing_history(page_body)

    # Une seule valeur par journée :
    # un nouveau lancement le même jour remplace l'état de cette journée.
    history[today_iso] = {
        "pass": pass_count,
        "fail": fail_count,
        "todo": todo_count,
        "pass_rate": pass_rate,
    }

    chart_macro = build_chart_macro(history)
    daily_tables = build_daily_tables(history)

    safe_summary = escape(str(summary))
    safe_test_plan_key = escape(str(TEST_PLAN_KEY))
    safe_jira_url = escape(str(JIRA_URL).rstrip("/"))

    return f"""
{DASHBOARD_START}

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

<h2>Résultats journaliers</h2>

{daily_tables}

{DASHBOARD_END}
""".strip()


# ---------------------------------------------------------------------------
# MERGE
# Le dashboard est toujours replacé au début de la page.
# Les autres tableaux/contenus sont conservés en dessous.
# ---------------------------------------------------------------------------

def merge_dashboard_into_page(existing_body, dashboard_html):
    pattern = re.compile(
        re.escape(DASHBOARD_START)
        + r".*?"
        + re.escape(DASHBOARD_END),
        flags=re.DOTALL,
    )

    # Retire uniquement l'ancienne version du dashboard.
    body_without_dashboard = pattern.sub(
        "",
        existing_body,
        count=1,
    ).strip()

    if not body_without_dashboard:
        return dashboard_html

    return (
        dashboard_html
        + "<p><br /></p>"
        + body_without_dashboard
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
        # 1. JIRA - stats du Test Plan
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

        # 4. Contenu actuel, pour préserver les autres tableaux
        current_body = get_page_body(
            sess,
            page_id,
        )

        # 5. Dashboard : graphique général + tableaux journaliers
        dashboard_html = build_dashboard_html(
            summary,
            stats,
            current_body,
        )

        # 6. Dashboard en haut, autres contenus conservés dessous
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