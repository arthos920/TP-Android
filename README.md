import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

NO_MSG_TEXT = "No messages or attachments"


def retry(self, timeout=300, poll_interval=5):
    """
    Rejoue les 2 clics (refresh) pendant max `timeout` secondes
    tant que le message affiché est "No messages or attachments".

    Retourne le texte final (quand il n'est plus NO_MSG_TEXT).
    Si timeout atteint en restant sur NO_MSG_TEXT -> raise Exception.
    """
    end_time = time.monotonic() + timeout
    last_text = None
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

        # 2) Lire le message
        try:
            el = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.XPATH, AUDIT_SERVER_RESULT_CONTENT_MESSAGE))
            )
            last_text = (el.text or "").strip()
        except Exception:
            # si on ne peut pas lire, on retente
            time.sleep(poll_interval)
            continue

        # 3) Condition d'arrêt
        if last_text != NO_MSG_TEXT:
            return last_text

        time.sleep(poll_interval)

    log_screenshot_web_global(
        self.driver,
        title=f"Retry timeout after {timeout}s (still '{NO_MSG_TEXT}')"
    )
    raise Exception(f"Timeout after {timeout}s: still '{NO_MSG_TEXT}'")