import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

VIDEO_CALLS_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='video-calls-video-call']"
VIDEO_ROWS_XPATH = VIDEO_CALLS_TABLE_XPATH + "//tbody//tr[@data-role='row-template']"


def _wait_for_valid_video_row(self, timeout=60, poll_interval=1):
    end = time.monotonic() + timeout

    while time.monotonic() < end:
        rows = self.driver.find_elements(By.XPATH, VIDEO_ROWS_XPATH)

        for r in rows:
            try:
                uuid = (r.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
                if uuid:
                    return r
            except:
                pass

        time.sleep(poll_interval)

    return None


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
    Gère correctement le chargement asynchrone UI.
    Screenshot automatique en cas d'échec.
    """
    try:
        # 1) Attente résultats backend
        self.retry(timeout=timeout)

        # 2) Attente table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, VIDEO_CALLS_TABLE_XPATH))
        )

        # 3) Attente vraie ligne non vide
        row0 = self._wait_for_valid_video_row(timeout=60)
        if not row0:
            html = self.driver.find_element(By.XPATH, VIDEO_CALLS_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[verify_video_call] table html: {html}")
            log_screenshot_web_global(self.driver, title="verify_video_call FAILED - no populated rows")
            raise Exception("No populated rows found (UI async not finished)")

        call_uuid = (row0.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
        robot.api.logger.info(f"verify_video_call - detected uuid={call_uuid}")

        # 4) Lecture colonnes
        found_initiator = (row0.find_element(By.XPATH, ".//td[@data-role='Initiator']").text or "").strip()
        found_participant = (row0.find_element(By.XPATH, ".//td[@data-role='Participants']").text or "").strip()
        found_result = (row0.find_element(By.XPATH, ".//td[@data-role='CallState']").text or "").strip()

        # 5) Vérifs
        if found_initiator != initiator_name:
            raise Exception(f"Initiator mismatch: expected '{initiator_name}', got '{found_initiator}'")

        if found_participant != participant_name:
            raise Exception(f"Participant mismatch: expected '{participant_name}', got '{found_participant}'")

        if call_result and found_result != call_result:
            raise Exception(f"Call result mismatch: expected '{call_result}', got '{found_result}'")

        # 6) Vérif download vidéo
        if require_download_link:
            rec_td = row0.find_element(By.XPATH, ".//td[@data-role='SessionRecording']")
            dl = rec_td.find_elements(By.XPATH, ".//span[contains(@class,'download-link')]")
            if not dl:
                raise Exception("Download video session link not found")

        robot.api.logger.info(f"verify_video_call OK for uuid={call_uuid}")

    except Exception as e:
        log_screenshot_web_global(self.driver, title=f"verify_video_call FAILED - {str(e)}")
        raise