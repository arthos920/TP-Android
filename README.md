import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

def verify_call(self, bool=False, timeout_minutes=15, poll_seconds=5):
    """This function is used to the status of a call after research ..."""

    timeout = timeout_minutes * 60
    start_time = time.time()
    found = False

    try:
        # Essai direct
        self.driver.find_element(By.XPATH, AUDITOR_TOGGLE_MENU_RESULT).click()
        found = True

    except Exception:
        robot.api.logger.info("There is no item for your research")

        # Retry jusqu'au timeout
        while time.time() - start_time < timeout:
            try:
                robot.api.logger.info("Attempt")

                time.sleep(poll_seconds)

                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()

                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, AUDITOR_TOGGLE_MENU_RESULT))
                ).click()

                found = True
                break

            except Exception:
                self.log.info("Still no item, retrying...")
                time.sleep(poll_seconds)

    # ❌ Échec définitif → UN SEUL SCREENSHOT
    if not found:
        log_screenshot_web_global(
            self.driver,
            title=f"Timeout: No call after {timeout_minutes} minutes"
        )
        raise Exception(f"Timeout: no call found after {timeout_minutes} minutes")

    # ✅ Lecture du résultat
    try:
        result = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, AUDITOR_CALL_RESULT))
        )

        if result.text == "compromised":
            if bool is True:
                print("The receiver did not respond")

        if result.text == "verified":
            print("The receiver did respond")

    except Exception:
        # ❌ Un seul screenshot aussi ici
        log_screenshot_web_global(self.driver, title="Message not found")
        raise Exception("Message not found")