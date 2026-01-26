import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


VIDEO_CALLS_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='video-calls-video-call']"
VIDEO_ROWS_XPATH = VIDEO_CALLS_TABLE_XPATH + "//tbody/tr"


def verify_video_call(
    self,
    initiator_name,
    participant_name,
    call_result="Success",
    timeout=120,
    poll_interval=2,
    require_download_link=True,
):
    """
    Vérifie un video call (table video-calls-video-call) avec XPaths corrigés.
    - Attend qu'une ligne "valide" apparaisse (uuid dans td CallUuid OU data-call-uuid sur download-link)
    - Vérifie Initiator, Participants, CallState
    - Vérifie la présence du lien download (optionnel)
    - Screenshot + HTML dump en cas d'échec
    """

    try:
        # 1) Attendre la table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, VIDEO_CALLS_TABLE_XPATH))
        )

        # 2) Attendre une ligne valide (UI async)
        end_time = time.monotonic() + timeout
        row0 = None
        last_table_html = None

        while time.monotonic() < end_time:
            rows = self.driver.find_elements(By.XPATH, VIDEO_ROWS_XPATH)

            valid_rows = []
            for r in rows:
                # uuid via td
                try:
                    td_uuid = (r.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
                except Exception:
                    td_uuid = ""

                # uuid via attribut sur download link
                try:
                    attr_uuid = (
                        r.find_element(
                            By.XPATH,
                            ".//td[@data-role='SessionRecording']//span[contains(@class,'download-link')]"
                        ).get_attribute("data-call-uuid") or ""
                    ).strip()
                except Exception:
                    attr_uuid = ""

                if td_uuid or attr_uuid:
                    valid_rows.append(r)

            if valid_rows:
                row0 = valid_rows[0]
                break

            # garder un HTML pour debug si timeout
            try:
                last_table_html = self.driver.find_element(By.XPATH, VIDEO_CALLS_TABLE_XPATH).get_attribute("outerHTML")
            except Exception:
                last_table_html = None

            time.sleep(poll_interval)

        if not row0:
            if last_table_html:
                robot.api.logger.info(f"[verify_video_call] table html: {last_table_html}")
            log_screenshot_web_global(self.driver, title="verify_video_call FAILED - no populated rows")
            raise Exception("No populated rows found (UI async not finished)")

        # 3) Récupérer le call_uuid (td d'abord, sinon attribut)
        call_uuid = ""
        try:
            call_uuid = (row0.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
        except Exception:
            call_uuid = ""

        if not call_uuid:
            try:
                call_uuid = (
                    row0.find_element(
                        By.XPATH,
                        ".//td[@data-role='SessionRecording']//span[contains(@class,'download-link')]"
                    ).get_attribute("data-call-uuid") or ""
                ).strip()
            except Exception:
                call_uuid = ""

        if not call_uuid:
            row_html = row0.get_attribute("outerHTML")
            robot.api.logger.info(f"[verify_video_call] row outerHTML: {row_html}")
            log_screenshot_web_global(self.driver, title="verify_video_call FAILED - empty uuid")
            raise Exception("Empty CallUuid in first valid row")

        robot.api.logger.info(f"verify_video_call - detected uuid={call_uuid}")

        # 4) Lire les champs principaux
        found_initiator = (row0.find_element(By.XPATH, ".//td[@data-role='Initiator']").text or "").strip()
        found_participant = (row0.find_element(By.XPATH, ".//td[@data-role='Participants']").text or "").strip()
        found_result = (row0.find_element(By.XPATH, ".//td[@data-role='CallState']").text or "").strip()

        # 5) Vérifs
        if found_initiator != initiator_name:
            raise Exception(f"Initiator mismatch: expected '{initiator_name}', got '{found_initiator}'")

        if found_participant != participant_name:
            raise Exception(f"Participant mismatch: expected '{participant_name}', got '{found_participant}'")

        if call_result is not None and found_result != call_result:
            raise Exception(f"Call result mismatch: expected '{call_result}', got '{found_result}'")

        # 6) Vérif lien download (optionnel)
        if require_download_link:
            rec_td = row0.find_element(By.XPATH, ".//td[@data-role='SessionRecording']")
            dl = rec_td.find_elements(By.XPATH, ".//span[contains(@class,'download-link')]")
            if not dl:
                raise Exception("Download video session link not found")

        robot.api.logger.info(f"verify_video_call OK for uuid={call_uuid}")
        return call_uuid

    except Exception as e:
        # screenshot systématique
        log_screenshot_web_global(self.driver, title=f"verify_video_call FAILED - {str(e)}")
        # dump HTML table pour debug
        try:
            html = self.driver.find_element(By.XPATH, VIDEO_CALLS_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[verify_video_call] table html: {html}")
        except Exception:
            pass
        raise