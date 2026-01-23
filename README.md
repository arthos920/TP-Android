from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


PRIVATE_CALLS_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='audio-calls-call']"
PRIVATE_ROWS_XPATH = PRIVATE_CALLS_TABLE_XPATH + "//tbody//tr[@data-role='row-template']"


def verify_private_call(
    self,
    initiator_name,
    participant_name,
    call_result="Success",
    timeout=300,
    require_recording_controls=True,
):
    """
    Vérifie un private call.
    Récupère la durée directement depuis l'UI et vérifie qu'elle != 00:00:00.
    Screenshot automatique en cas d'échec.
    """

    try:
        # 1) Attente résultats
        self.retry(timeout=timeout)

        # 2) Attente table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, PRIVATE_CALLS_TABLE_XPATH))
        )

        rows = self.driver.find_elements(By.XPATH, PRIVATE_ROWS_XPATH)
        if not rows:
            raise Exception("No rows found in private calls table")

        # 3) On prend la première ligne
        row0 = rows[0]

        call_uuid = (row0.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
        if not call_uuid:
            raise Exception("Empty CallUuid in first row")

        found_initiator = (row0.find_element(By.XPATH, ".//td[@data-role='Initiator']").text or "").strip()
        found_participant = (row0.find_element(By.XPATH, ".//td[@data-role='Participant']").text or "").strip()
        found_result = (row0.find_element(By.XPATH, ".//td[@data-role='CallState']").text or "").strip()

        # 4) Vérifications principales
        if found_initiator != initiator_name:
            raise Exception(f"Initiator mismatch: expected '{initiator_name}', got '{found_initiator}'")

        if found_participant != participant_name:
            raise Exception(f"Participant mismatch: expected '{participant_name}', got '{found_participant}'")

        if call_result is not None and found_result != call_result:
            raise Exception(f"Call result mismatch: expected '{call_result}', got '{found_result}'")

        # 5) Vérification enregistrement audio
        rec_td = row0.find_element(By.XPATH, ".//td[@data-role='SessionRecording']")

        if require_recording_controls:
            play = rec_td.find_elements(
                By.XPATH, ".//*[@data-role='play' or contains(@class,'play-main') or contains(@class,'play')]"
            )
            dl = rec_td.find_elements(
                By.XPATH, ".//span[contains(@class,'download-link')]"
            )

            if not play:
                raise Exception("Recording play control not found")
            if not dl:
                raise Exception("Recording download control not found")

        # 6) Vérification durée ≠ 00:00:00
        dur_el = rec_td.find_element(By.XPATH, ".//*[@data-role='Duration']")
        found_duration = (dur_el.text or "").strip()

        if not found_duration:
            raise Exception("Recording duration is empty")

        if found_duration == "00:00:00":
            raise Exception("Recording duration is zero")

        robot.api.logger.info(
            f"verify_private_call OK for uuid={call_uuid} (duration={found_duration})"
        )

    except Exception as e:
        log_screenshot_web_global(
            self.driver,
            title=f"verify_private_call FAILED - {str(e)}"
        )
        raise