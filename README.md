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

# Les commentaires HTML utilisés précédemment ne sont pas toujours conservés
# par Confluence. On utilise maintenant deux macros Anchor persistantes.
START_ANCHOR_NAME = "night-run-dashboard-start"
END_ANCHOR_NAME = "night-run-dashboard-end"


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
# Sert uniquement à préserver les autres contenus de la page.
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
# PERSISTENT ANCHORS
# ---------------------------------------------------------------------------

def build_anchor_macro(anchor_name):
    return f"""
<ac:structured-macro ac:name="anchor" ac:schema-version="1">
    <ac:parameter ac:name="">{escape(anchor_name)}</ac:parameter>
</ac:structured-macro>
""".strip()


def anchor_macro_pattern(anchor_name):
    """
    Regex tolérante aux attributs supplémentaires ajoutés par Confluence,
    par exemple ac:macro-id.
    """

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


def dashboard_block_pattern():
    return re.compile(
        anchor_macro_pattern(START_ANCHOR_NAME)
        + r".*?"
        + anchor_macro_pattern(END_ANCHOR_NAME),
        flags=re.DOTALL | re.IGNORECASE,
    )


def extract_managed_blocks(page_body):
    return dashboard_block_pattern().findall(page_body)


# ---------------------------------------------------------------------------
# HISTORY - READ EXISTING VALUES
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
    """
    Lit le tableau général de la nouvelle version :

    Date | PASS | FAIL | TODO | Taux de réussite
    """

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
    """
    Récupère les données des tableaux journaliers déjà présents,
    y compris dans les copies dupliquées actuelles.
    """

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
    """
    Compatibilité avec l'ancien tableau historique horizontal.
    """

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
    """
    Consolide l'historique des versions précédentes et de la version actuelle.
    Une date n'apparaît qu'une fois dans le dictionnaire final.
    """

    history = {}

    # Nouvelle version avec anchors.
    for block in extract_managed_blocks(page_body):
        parse_general_history_table(
            block,
            history,
        )

    # Anciennes versions actuellement dupliquées.
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
# CHART
# Un seul graphique, avec deux séries : PASS et FAIL.
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
# ONE GENERAL HISTORY TABLE
# Une seule ligne par journée.
# Un nouveau run le même jour remplace les valeurs de cette journée.
# ---------------------------------------------------------------------------

def build_general_history_table(history):
    rows = []

    # Les dates les plus récentes apparaissent en premier.
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
# Un graphique + un tableau général.
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

    now = datetime.now().astimezone()
    today_iso = now.strftime("%Y-%m-%d")
    last_update = now.strftime("%d/%m/%Y à %H:%M")

    # Récupère les données des blocs actuels, y compris les copies dupliquées.
    history = parse_existing_history(page_body)

    # Une seule entrée par date.
    # Deux exécutions le même jour mettent à jour la même ligne.
    history[today_iso] = {
        "pass": pass_count,
        "fail": fail_count,
        "todo": todo_count,
        "pass_rate": pass_rate,
    }

    chart_macro = build_chart_macro(history)
    history_table = build_general_history_table(history)

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

{history_table}

{end_anchor}
""".strip()


# ---------------------------------------------------------------------------
# LEGACY CLEANUP
# Supprime précisément les dashboards générés par les deux versions précédentes.
# Les autres tableaux de la page sont conservés.
# ---------------------------------------------------------------------------

def remove_legacy_daily_dashboard_blocks(page_body):
    """
    Ancienne version :
    H1 Dashboard...
    ...
    H2 Résultats journaliers
    H3 Night run du ...
    table
    """

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
    """
    Version encore plus ancienne :
    H1 Dashboard...
    H2 État actuel...
    H2/H3 Historique quotidien
    table historique
    """

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
# Supprime tous les dashboards gérés, y compris les copies dupliquées,
# puis ajoute exactement un dashboard au début de la page.
# ---------------------------------------------------------------------------

def merge_dashboard_into_page(existing_body, dashboard_html):
    body = existing_body

    # 1. Retire toutes les copies de la nouvelle version avec anchors.
    body, managed_count = dashboard_block_pattern().subn(
        "",
        body,
    )

    # 2. Nettoie les copies créées par les versions précédentes.
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

    # Le dashboard reste en haut.
    # Les autres tableaux et contenus existants restent en dessous.
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

        # 5. Construit un seul dashboard
        dashboard_html = build_dashboard_html(
            summary,
            stats,
            current_body,
        )

        # 6. Supprime toutes les anciennes copies et insère le dashboard unique
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