#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extraction ponctuelle des événements PTT depuis un output.xml Robot Framework.

Fonctionnement :
    1. prend un snapshot logique de la taille actuelle de output.xml ;
    2. lit uniquement ces octets en streaming ;
    3. extrait au maximum un événement par keyword "Use Ptt Release" ;
    4. reconstruit entièrement kpi_endurance.csv avec les compteurs cumulés ;
    5. remplace le CSV local de manière atomique ;
    6. crée ou met à jour la pièce jointe kpi_endurance.csv sur une page
       Confluence fixe ;
    7. termine immédiatement.

Le parseur XML n'est volontairement pas finalisé à EOF : si Robot Framework est
encore en train d'écrire la dernière balise / le dernier keyword, cette partie
incomplète est simplement ignorée jusqu'à l'exécution suivante du script.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.parsers import expat

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ===========================================================================
# CONFIGURATION
# ===========================================================================

# Fichier Robot Framework actuellement produit par l'endurance.
OUTPUT_XML = Path(r"C:\chemin\vers\output.xml")

# Copie locale du CSV généré à chaque exécution.
OUTPUT_CSV = Path(r"C:\chemin\vers\kpi_endurance.csv")

# Nom fixe de la pièce jointe Confluence.
CSV_FILENAME = "kpi_endurance.csv"
CSV_DELIMITER = ";"

# Taille de lecture du XML. Le fichier n'est jamais chargé entièrement en RAM.
XML_CHUNK_SIZE = 1024 * 1024  # 1 MiB

# Keyword Robot Framework et mobiles suivis.
TARGET_KEYWORD = "Use Ptt Release"
DRIVERS = tuple(f"driver{i}" for i in range(1, 7))
DRIVER_SET = set(DRIVERS)

# ---------------------------------------------------------------------------
# CONFLUENCE
# ---------------------------------------------------------------------------

CONFLUENCE_URL = ""
CONFLUENCE_TOKEN = ""

# Laisse vide si Confluence n'utilise pas de proxy.
CONFLUENCE_PROXY_URL = ""

# ID numérique de la page sur laquelle kpi_endurance.csv doit être envoyé.
# Exemple : pour .../pages/viewpage.action?pageId=123456 -> "123456"
CONFLUENCE_PAGE_ID = ""


# ===========================================================================
# DONNÉES MÉTIER
# ===========================================================================

PTT_SUCCESS = "PTT_SUCCESS"
PTT_FAIL = "PTT_FAIL"

@dataclass(slots=True)
class PttEvent:
    timestamp: str
    driver: str
    event: str


@dataclass(slots=True)
class KeywordContext:
    """Informations minimales conservées pour un Use Ptt Release ouvert."""

    depth: int
    driver: str
    success_timestamp: str | None = None
    success_seen_without_timestamp: bool = False
    final_status: str | None = None
    final_status_start: str | None = None


@dataclass(slots=True)
class MessageContext:
    """Texte d'un <msg> descendant du Use Ptt Release courant."""

    depth: int
    keyword: KeywordContext
    timestamp: str
    text_parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractionResult:
    events: list[PttEvent]
    snapshot_size: int
    xml_closed: bool
    skipped_missing_timestamp: int


# ===========================================================================
# HTTP / CONFLUENCE
# Logique de connexion reprise du script existant.
# ===========================================================================


def build_proxies(proxy_url: str) -> dict[str, str] | None:
    if not proxy_url:
        return None

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


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


def find_csv_attachment(
    session: requests.Session,
    page_id: str,
    filename: str,
) -> dict[str, Any] | None:
    response = session.get(
        f"{CONFLUENCE_URL}/rest/api/content/{page_id}/child/attachment",
        params={
            "filename": filename,
            "limit": 200,
            "expand": "version",
        },
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
    csv_path: Path,
    filename: str,
) -> None:
    url = (
        f"{CONFLUENCE_URL}/rest/api/content/"
        f"{page_id}/child/attachment"
    )

    with csv_path.open("rb") as csv_file:
        response = session.post(
            url,
            headers={
                "X-Atlassian-Token": "no-check",
            },
            files={
                "file": (
                    filename,
                    csv_file,
                    "text/csv",
                )
            },
            data={
                "comment": (
                    f"Mise à jour automatique de {filename}"
                )
            },
            timeout=60,
        )

    response.raise_for_status()
    print(f"Pièce jointe créée : {filename}")


def update_csv_attachment(
    session: requests.Session,
    page_id: str,
    attachment_id: str,
    csv_path: Path,
    filename: str,
) -> None:
    url = (
        f"{CONFLUENCE_URL}/rest/api/content/"
        f"{page_id}/child/attachment/"
        f"{attachment_id}/data"
    )

    with csv_path.open("rb") as csv_file:
        response = session.post(
            url,
            headers={
                "X-Atlassian-Token": "no-check",
            },
            files={
                "file": (
                    filename,
                    csv_file,
                    "text/csv",
                )
            },
            data={
                "comment": (
                    f"Mise à jour automatique de {filename}"
                )
            },
            timeout=60,
        )

    response.raise_for_status()
    print(f"Nouvelle version de la pièce jointe : {filename}")


def upload_csv_attachment(
    session: requests.Session,
    page_id: str,
    csv_path: Path,
    filename: str,
) -> None:
    attachment = find_csv_attachment(
        session=session,
        page_id=page_id,
        filename=filename,
    )

    if attachment is None:
        create_csv_attachment(
            session=session,
            page_id=page_id,
            csv_path=csv_path,
            filename=filename,
        )
    else:
        update_csv_attachment(
            session=session,
            page_id=page_id,
            attachment_id=str(attachment["id"]),
            csv_path=csv_path,
            filename=filename,
        )


# ===========================================================================
# EXTRACTION XML STREAMING
# ===========================================================================


def normalize_xml_name(name: str) -> str:
    """Retourne le nom local d'une balise XML éventuelle avec préfixe."""
    return name.rsplit(":", 1)[-1].lower()


def is_target_keyword(name: str) -> bool:
    return name.strip().casefold() == TARGET_KEYWORD.casefold()


def is_ptt_pressed_message(text: str) -> bool:
    # La règle demandée est volontairement simple et robuste aux petites
    # variantes : le message doit contenir PTT et pressed, sans tenir compte
    # de la casse ni des espaces.
    normalized = " ".join(text.split()).casefold()
    return "ptt" in normalized and "pressed" in normalized


def extract_ptt_events(xml_path: Path) -> ExtractionResult:
    """
    Analyse uniquement l'état du fichier présent au lancement du script.

    La taille du fichier est lue une fois au départ. Si Robot Framework ajoute
    des octets pendant l'analyse, ils seront volontairement traités lors de la
    prochaine exécution cron/pipeline.

    Le parseur Expat travaille en streaming et n'est jamais finalisé avec
    isfinal=True. Une fin de fichier temporairement incomplète est donc tolérée.
    Seuls les keywords Use Ptt Release complètement fermés génèrent un événement.
    """

    if not xml_path.is_file():
        raise FileNotFoundError(
            f"output.xml introuvable : {xml_path}"
        )

    try:
        snapshot_size = xml_path.stat().st_size
    except OSError as error:
        raise OSError(
            f"Impossible de lire la taille de {xml_path}: {error}"
        ) from error

    events: list[PttEvent] = []
    keyword_stack: list[KeywordContext] = []
    message_stack: list[MessageContext] = []

    depth = 0
    root_seen = False
    root_closed = False
    skipped_missing_timestamp = 0

    parser = expat.ParserCreate()

    def start_element(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, root_seen, root_closed

        depth += 1
        tag = normalize_xml_name(name)

        if depth == 1:
            root_seen = True
            root_closed = False

        # Un nouveau Use Ptt Release suivi est identifié par SON owner.
        if tag == "kw":
            keyword_name = str(attrs.get("name", ""))
            driver = str(attrs.get("owner", "")).strip().lower()

            if is_target_keyword(keyword_name) and driver in DRIVER_SET:
                keyword_stack.append(
                    KeywordContext(
                        depth=depth,
                        driver=driver,
                    )
                )

        if not keyword_stack:
            return

        current_keyword = keyword_stack[-1]

        # Un message peut être directement sous le keyword ou dans un helper
        # imbriqué : tant qu'il appartient au Use Ptt Release courant, il peut
        # confirmer le vrai PTT_SUCCESS.
        if tag == "msg":
            message_stack.append(
                MessageContext(
                    depth=depth,
                    keyword=current_keyword,
                    timestamp=str(attrs.get("time", "")).strip(),
                )
            )

        # Le FAIL est basé uniquement sur le status DIRECT du Use Ptt Release.
        # Si plusieurs status directs apparaissaient, le dernier rencontré
        # écrase les précédents et représente le status final direct.
        if (
            tag == "status"
            and depth == current_keyword.depth + 1
        ):
            current_keyword.final_status = (
                str(attrs.get("status", "")).strip().upper()
            )
            current_keyword.final_status_start = (
                str(attrs.get("start", "")).strip()
            )

    def character_data(data: str) -> None:
        if message_stack:
            message_stack[-1].text_parts.append(data)

    def end_element(name: str) -> None:
        nonlocal depth, root_closed, skipped_missing_timestamp

        tag = normalize_xml_name(name)

        # Termine le message avant de diminuer la profondeur.
        if (
            tag == "msg"
            and message_stack
            and message_stack[-1].depth == depth
        ):
            message = message_stack.pop()
            text = "".join(message.text_parts)

            if is_ptt_pressed_message(text):
                keyword = message.keyword

                # Le premier message PTT pressed horodaté suffit à confirmer
                # le succès. On ne crée toujours qu'un seul événement au END kw.
                if keyword.success_timestamp is None:
                    if message.timestamp:
                        keyword.success_timestamp = message.timestamp
                    else:
                        keyword.success_seen_without_timestamp = True

        # Un événement n'est créé qu'à la fermeture complète du keyword cible.
        if (
            tag == "kw"
            and keyword_stack
            and keyword_stack[-1].depth == depth
        ):
            keyword = keyword_stack.pop()

            if keyword.success_timestamp:
                events.append(
                    PttEvent(
                        timestamp=keyword.success_timestamp,
                        driver=keyword.driver,
                        event=PTT_SUCCESS,
                    )
                )

            elif keyword.success_seen_without_timestamp:
                # Un message confirme le succès mais ne permet pas de dater
                # l'événement : ne surtout pas le transformer en faux FAIL.
                skipped_missing_timestamp += 1

            elif keyword.final_status == "FAIL":
                if keyword.final_status_start:
                    events.append(
                        PttEvent(
                            timestamp=keyword.final_status_start,
                            driver=keyword.driver,
                            event=PTT_FAIL,
                        )
                    )
                else:
                    skipped_missing_timestamp += 1

        if depth == 1 and root_seen:
            root_closed = True

        depth -= 1

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data

    bytes_remaining = snapshot_size

    try:
        with xml_path.open("rb") as xml_file:
            while bytes_remaining > 0:
                chunk = xml_file.read(
                    min(XML_CHUNK_SIZE, bytes_remaining)
                )

                if not chunk:
                    # Le fichier a pu être tronqué/remplacé entre stat() et read().
                    # On utilise simplement ce qui a été réellement lu.
                    break

                bytes_remaining -= len(chunk)

                # IMPORTANT : isfinal=False même pour le dernier chunk.
                # Ainsi, un dernier token/balisage incomplet reste en attente
                # dans Expat au lieu de provoquer une erreur de fin de document.
                parser.Parse(chunk, False)

    except expat.ExpatError as error:
        raise ValueError(
            "XML mal formé avant la fin exploitable du snapshot "
            f"(ligne {error.lineno}, colonne {error.offset}) : {error}"
        ) from error

    # Pas de parser.Parse(b"", True) ici : cela transformerait précisément la
    # fin XML temporairement incomplète en ParseError.

    # ISO 8601 Robot Framework (YYYY-MM-DDTHH:MM:SS.ffffff) : l'ordre lexical
    # correspond à l'ordre chronologique pour les timestamps générés ici.
    events.sort(
        key=lambda item: (
            item.timestamp,
            item.driver,
            item.event,
        )
    )

    return ExtractionResult(
        events=events,
        snapshot_size=snapshot_size,
        xml_closed=(root_seen and root_closed and depth == 0),
        skipped_missing_timestamp=skipped_missing_timestamp,
    )


# ===========================================================================
# CSV ATOMIQUE
# ===========================================================================


def timestamp_to_minute(timestamp: str) -> str:
    """
    Convertit un timestamp Robot Framework en minute lisible.

    Exemple :
        2026-09-29T17:51:40.135684 -> 2026-09-29 17:51
    """
    value = timestamp.strip()

    if len(value) < 16:
        raise ValueError(
            f"Timestamp trop court ou invalide : {timestamp!r}"
        )

    return value[:16].replace("T", " ")


def write_csv_atomically(
    events: list[PttEvent],
    output_path: Path,
) -> None:
    """
    Reconstruit un CSV d'évolution cumulée, agrégé à la minute.

    Tous les événements appartenant à la même minute sont regroupés.
    Une seule ligne est écrite par minute, avec l'état cumulé des compteurs
    PASS/FAIL des 6 drivers ainsi que les trois totaux globaux après traitement
    de tous les événements de cette minute.

    Le fichier est d'abord écrit dans un fichier temporaire situé dans le même
    dossier, puis publié atomiquement avec os.replace().
    """

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path: Path | None = None

    # Compteurs cumulés utilisés pour construire la courbe d'évolution.
    counters = {
        driver: {
            PTT_SUCCESS: 0,
            PTT_FAIL: 0,
        }
        for driver in DRIVERS
    }

    total_success = 0
    total_fail = 0
    total_events = 0

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

            writer = csv.writer(
                temp_file,
                delimiter=CSV_DELIMITER,
                lineterminator="\n",
            )

            headers = ["timestamp"]

            for driver in DRIVERS:
                headers.extend(
                    [
                        f"{driver}_pass",
                        f"{driver}_fail",
                    ]
                )

            headers.extend(
                [
                    "pass_total",
                    "fail_total",
                    "total_events",
                ]
            )

            writer.writerow(headers)

            current_minute: str | None = None

            def write_current_snapshot(minute: str) -> None:
                row: list[str | int] = [minute]

                for driver in DRIVERS:
                    row.extend(
                        [
                            counters[driver][PTT_SUCCESS],
                            counters[driver][PTT_FAIL],
                        ]
                    )

                row.extend(
                    [
                        total_success,
                        total_fail,
                        total_events,
                    ]
                )

                writer.writerow(row)

            for event in events:
                event_minute = timestamp_to_minute(event.timestamp)

                # Quand on passe à une nouvelle minute, la minute précédente
                # est complète : on écrit un seul snapshot cumulé pour elle.
                if (
                    current_minute is not None
                    and event_minute != current_minute
                ):
                    write_current_snapshot(current_minute)

                current_minute = event_minute

                counters[event.driver][event.event] += 1
                total_events += 1

                if event.event == PTT_SUCCESS:
                    total_success += 1
                elif event.event == PTT_FAIL:
                    total_fail += 1

            # Dernière minute présente dans le snapshot XML.
            if current_minute is not None:
                write_current_snapshot(current_minute)

            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(
            temp_path,
            output_path,
        )
        temp_path = None

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


# ===========================================================================
# RÉSUMÉ CONSOLE
# ===========================================================================


def build_counters(
    events: list[PttEvent],
) -> dict[str, Counter[str]]:
    counters = {
        driver: Counter(
            {
                PTT_SUCCESS: 0,
                PTT_FAIL: 0,
            }
        )
        for driver in DRIVERS
    }

    for event in events:
        counters[event.driver][event.event] += 1

    return counters


def print_summary(
    result: ExtractionResult,
    output_path: Path,
) -> None:
    counters = build_counters(
        result.events
    )

    total_success = sum(
        counters[driver][PTT_SUCCESS]
        for driver in DRIVERS
    )
    total_fail = sum(
        counters[driver][PTT_FAIL]
        for driver in DRIVERS
    )

    print("=" * 58)
    print("ENDURANCE PTT EXTRACTION")
    print("=" * 58)
    print()

    for driver in DRIVERS:
        print(
            f"{driver} : "
            f"SUCCESS={counters[driver][PTT_SUCCESS]}  "
            f"FAIL={counters[driver][PTT_FAIL]}"
        )

    print()
    print("-" * 58)
    print()
    print(f"TOTAL SUCCESS = {total_success}")
    print(f"TOTAL FAIL    = {total_fail}")
    print(f"TOTAL EVENTS  = {len(result.events)}")
    print()
    print(f"XML snapshot  = {result.snapshot_size} bytes")

    if result.xml_closed:
        print("XML state     = document currently complete")
    else:
        print(
            "XML state     = document currently open/incomplete; "
            "unfinished tail ignored"
        )

    if result.skipped_missing_timestamp:
        print(
            "Warnings      = "
            f"{result.skipped_missing_timestamp} completed PTT keyword(s) "
            "ignored because the required timestamp was missing"
        )

    print()
    print("CSV generated:")
    print(output_path.resolve())
    print()
    print("=" * 58)


# ===========================================================================
# VALIDATION / MAIN
# ===========================================================================


def validate_configuration() -> None:
    page_id = str(
        CONFLUENCE_PAGE_ID
    ).strip()

    if not page_id or not page_id.isdigit():
        raise ValueError(
            "CONFLUENCE_PAGE_ID doit contenir l'ID numérique "
            "de la page Confluence de destination."
        )

    if not str(CONFLUENCE_URL).strip():
        raise ValueError(
            "CONFLUENCE_URL n'est pas renseigné."
        )

    if not str(CONFLUENCE_TOKEN).strip():
        raise ValueError(
            "CONFLUENCE_TOKEN n'est pas renseigné."
        )


def main() -> int:
    validate_configuration()

    xml_path = Path(
        OUTPUT_XML
    )
    csv_path = Path(
        OUTPUT_CSV
    )

    # 1. Lecture ponctuelle du snapshot actuel de output.xml.
    result = extract_ptt_events(
        xml_path
    )

    # 2. Reconstruction complète puis remplacement atomique du CSV local.
    write_csv_atomically(
        events=result.events,
        output_path=csv_path,
    )

    # 3. Résumé de cette exécution.
    print_summary(
        result=result,
        output_path=csv_path,
    )

    # 4. Création ou mise à jour de la pièce jointe Confluence.
    session = make_confluence_session()

    upload_csv_attachment(
        session=session,
        page_id=str(CONFLUENCE_PAGE_ID).strip(),
        csv_path=csv_path,
        filename=CSV_FILENAME,
    )

    print(
        f"Confluence upload OK : page {CONFLUENCE_PAGE_ID} / {CSV_FILENAME}"
    )

    # Exécution ponctuelle terminée : aucune boucle, aucun polling.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(
            f"ERREUR BLOQUANTE : {error}",
            file=sys.stderr,
        )
        sys.exit(1)