NO_RECORDS_XPATH = "//*[@data-role='no-records']"

def retry(self, timeout=300, poll_interval=5):
    end_time = time.monotonic() + timeout
    attempt = 0

    while time.monotonic() < end_time:
        attempt += 1

        # refresh (tes 2 clicks)
        WebDriverWait(self.driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, AUDIT_SERVER_OPEN_FILTER_BUTTON))
        ).click()

        time.sleep(3)

        WebDriverWait(self.driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, AUDIT_SERVER_SUBMIT_FILTER))
        ).click()

        # ✅ condition basée sur la VISIBILITÉ
        try:
            # si visible => on continue (pas de résultats)
            WebDriverWait(self.driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, NO_RECORDS_XPATH))
            )
            robot.api.logger.info(f"[retry] attempt {attempt}: no-records visible -> retrying...")
            time.sleep(poll_interval)
            continue

        except TimeoutException:
            # ✅ pas visible => soit display:none soit absent => OK
            robot.api.logger.info(f"[retry] attempt {attempt}: no-records NOT visible -> exit retry")
            return

    log_screenshot_web_global(self.driver, title=f"Retry timeout after {timeout}s (no-records still visible)")
    raise Exception(f"Timeout after {timeout}s: no-records still visible")