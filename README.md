import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

def verify_call(self, bool=False, timeout_minutes=15, poll_seconds=5):
    """This function is used to the status of a call after research ..."""

    timeout = timeout_minutes * 60
    start_time = time.time()

    try:
        # Essai direct
        self.driver.find_element(By.XPATH, AUDITOR_TOGGLE_MENU_RESULT).click()

    except Exception:
        log_screenshot(self.driver)
        robot.api.logger.info("There is no item for your research")

        # Retry jusqu'au timeout
        while time.time() - start_time < timeout:
            try:
                robot.api.logger.info("Attempt")

                time.sleep(poll_seconds)

                # (tu l'avais 2 fois) : si c'est volontaire, garde; sinon enlève un des deux
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()

                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, AUDITOR_TOGGLE_MENU_RESULT))
                ).click()

                # OK -> on sort
                break

            except Exception:
                self.log.info("There is no item for your research")
                log_screenshot_web_global(self.driver, title="No call (retrying)")
                time.sleep(poll_seconds)

        else:
            # Le while a expiré (timeout)
            log_screenshot_web_global(self.driver, title="Timeout: No call after search")
            raise Exception(f"Timeout: no call found after {timeout_minutes} minutes")

    # Ensuite: lecture du statut
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
        log_screenshot_web_global(self.driver, title="Message not found")
        raise Exception("Message not found")