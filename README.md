from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

VIDEO_CALLS_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='video-calls-video-call']"
VIDEO_ROWS_XPATH = VIDEO_CALLS_TABLE_XPATH + "//tbody//tr[@data-role='row-template']"


def verify_video_call(
    self,
    initiator_name,
    participant_name,
    call_result="Success",
    timeout=300,
    require_download_link=True,
):
    """
    Vérifie un video call (table video-calls-video-call).
    - Utilise retry() pour attendre que les résultats soient présents.
    - Ignore les lignes "template" vides (CallUuid vide).
    - Vérifie Initiator, Participants, CallState, et (optionnel) le lien de téléchargement.
    - Screenshot automatique en cas d'échec.
    """
    try:
        # 1) Attente résultats (ton retry basé sur no-records)
        self.retry(timeout=timeout)

        # 2) Attente table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, VIDEO_CALLS_TABLE_XPATH))
        )

        # 3) Récupération des lignes + filtrage des lignes "valides" (CallUuid non vide)
        rows = self.driver.find_elements(By.XPATH, VIDEO_ROWS_XPATH)

        valid_rows = []
        for r in rows:
            try:
                uuid = (r.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
                if uuid:
                    valid_rows.append(r)
            except Exception:
                continue

        if not valid_rows:
            html = self.driver.find_element(By.XPATH, VIDEO_CALLS_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[verify_video_call] table html: {html}")
            log_screenshot_web_global(self.driver, title="verify_video_call FAILED - no valid rows")
            raise Exception("No populated rows found (only template rows present)")

        row0 = valid_rows[0]
        call_uuid = (row0.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()

        if not call_uuid:
            # Normalement impossible avec le filtre, mais on garde une garde-fou
            html = row0.get_attribute("outerHTML")
            robot.api.logger.info(f"[verify_video_call] row outerHTML: {html}")
            raise Exception("Empty CallUuid in first valid row")

        robot.api.logger.info(f"verify_video_call - detected uuid={call_uuid}")

        # 4) Lecture des champs
        found_initiator = (row0.find_element(By.XPATH, ".//td[@data-role='Initiator']").text or "").strip()

        # D'après ton DOM : data-role="Participants"
        found_participant = (row0.find_element(By.XPATH, ".//td[@data-role='Participants']").text or "").strip()

        found_result = (row0.find_element(By.XPATH, ".//td[@data-role='CallState']").text or "").strip()

        # 5) Vérifs principales
        if found_initiator != initiator_name:
            raise Exception(f"Initiator mismatch: expected '{initiator_name}', got '{found_initiator}'")

        if found_participant != participant_name:
            raise Exception(f"Participant mismatch: expected '{participant_name}', got '{found_participant}'")

        if call_result is not None and found_result != call_result:
            raise Exception(f"Call result mismatch: expected '{call_result}', got '{found_result}'")

        # 6) Vérif du lien download vidéo
        if require_download_link:
            rec_td = row0.find_element(By.XPATH, ".//td[@data-role='SessionRecording']")
            dl = rec_td.find_elements(By.XPATH, ".//span[contains(@class,'download-link')]")
            if not dl:
                raise Exception("Download video session link not found")

            # Optionnel : s'assurer que c'est bien un "download"
            dl_text = (dl[0].text or "").strip()
            if dl_text and "Download" not in dl_text:
                raise Exception(f"Unexpected download link text: '{dl_text}'")

        robot.api.logger.info(f"verify_video_call OK for uuid={call_uuid}")

    except Exception as e:
        log_screenshot_web_global(self.driver, title=f"verify_video_call FAILED - {str(e)}")
        raise