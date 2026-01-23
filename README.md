import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


NO_RECORDS_XPATH = "//*[@data-role='no-records']"

def retry(self, timeout=300, poll_interval=5):
    """
    Refresh via 2 clics tant que l'élément data-role='no-records' est présent (visible).
    Sort dès qu'il est absent => on considère que les résultats sont affichés.
    Timeout global -> FAIL.
    """
    end_time = time.monotonic() + timeout
    attempt = 0

    while time.monotonic() < end_time:
        attempt += 1

        # 1) Refresh via les 2 clics
        WebDriverWait(self.driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, AUDIT_SERVER_OPEN_FILTER_BUTTON))
        ).click()

        time.sleep(3)

        WebDriverWait(self.driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, AUDIT_SERVER_SUBMIT_FILTER))
        ).click()

        # 2) Condition de sortie basée sur présence/absence de no-records
        try:
            # On attend un court instant : si no-records apparaît => on continue
            no_records_el = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.XPATH, NO_RECORDS_XPATH))
            )

            # si présent mais pas affiché (rare), on considère absent => sortie
            if not no_records_el.is_displayed():
                return

            # présent + affiché => on continue à boucler
            robot.api.logger.info(f"[retry] attempt {attempt}: no-records visible, retrying...")
            time.sleep(poll_interval)
            continue

        except TimeoutException:
            # no-records absent => sortie OK
            robot.api.logger.info(f"[retry] attempt {attempt}: no-records absent -> exit retry")
            return

    log_screenshot_web_global(self.driver, title=f"Retry timeout after {timeout}s (no-records still present)")
    raise Exception(f"Timeout after {timeout}s: no-records still present")