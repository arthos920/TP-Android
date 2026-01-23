from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


AUDIO_CALLS_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='audio-calls-ptt']"
ROWS_XPATH = AUDIO_CALLS_TABLE_XPATH + "//tbody//tr[@data-role='row-template']"


def verify_call(
    self,
    started_call_initiator_name,
    joined_call_name,
    took_the_floor_name,
    released_the_floor_name,
    left_call_name,
    ended_call_name,
    timeout=300,
):
    """
    Vérifie la cohérence EventType -> EventOwner (initiator) pour le call affiché.
    Screenshot automatique en cas d'échec.
    """

    try:
        # 1) Attente résultats
        self.retry(timeout=timeout)

        # 2) Attente table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, AUDIO_CALLS_TABLE_XPATH))
        )

        rows = self.driver.find_elements(By.XPATH, ROWS_XPATH)
        if not rows:
            raise Exception("No rows found in calls table")

        # 3) Auto-détection call_uuid
        call_uuid = (rows[0].find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
        if not call_uuid:
            raise Exception("Empty CallUuid in first row")

        robot.api.logger.info(f"verify_call - detected uuid={call_uuid}")

        # 4) Règles attendues
        expected_owner_by_type = {
            "Started call": started_call_initiator_name,
            "Joined call": joined_call_name,
            "Took the floor": took_the_floor_name,
            "Released the floor": released_the_floor_name,
            "Left call": left_call_name,
            "Ended call": ended_call_name,
        }

        # 5) Collecte des events trouvés
        found_owners_by_type = {k: [] for k in expected_owner_by_type}

        for r in rows:
            uuid = (r.find_element(By.XPATH, ".//td[@data-role='CallUuid']").text or "").strip()
            if uuid != call_uuid:
                continue

            etype = (r.find_element(By.XPATH, ".//td[@data-role='EventType']").text or "").strip()
            owner = (r.find_element(By.XPATH, ".//td[@data-role='EventOwner']").text or "").strip()

            if etype in found_owners_by_type:
                found_owners_by_type[etype].append(owner)

        # 6) Vérifications
        missing_types = []
        mismatches = []

        for etype, expected_owner in expected_owner_by_type.items():
            owners = found_owners_by_type.get(etype, [])

            if not owners:
                missing_types.append(etype)
                continue

            bad = [o for o in owners if o != expected_owner]
            if bad:
                mismatches.append(
                    f"{etype}: expected '{expected_owner}', got {sorted(set(owners))}"
                )

        if missing_types or mismatches:
            details = []
            if missing_types:
                details.append(f"Missing event types: {missing_types}")
            if mismatches:
                details.append("Initiator mismatches: " + " | ".join(mismatches))
            raise Exception(" ; ".join(details))

        robot.api.logger.info(f"verify_call OK for uuid={call_uuid}")

    except Exception as e:
        # 📸 Screenshot automatique
        log_screenshot_web_global(
            self.driver,
            title=f"verify_call FAILED - {str(e)}"
        )
        raise