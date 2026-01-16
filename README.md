import time

def verify_attachment(self):
    timeout = 15 * 60   # 15 minutes en secondes
    start_time = time.time()
    fail_attachment = True

    try:
        WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, AUDITOR_TOGGLE_MENU_RESULT))
        ).click()
    except:
        robot.api.logger.info("There is no item for your research")

        while time.time() - start_time < timeout:
            try:
                robot.api.logger.info("Attempt")

                time.sleep(5)
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()
                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, AUDITOR_TOGGLE_MENU_RESULT))
                ).click()

                fail_attachment = False
                break

            except:
                self.log.info("Still no item, retrying...")
                time.sleep(5)

        # Si le timeout est dépassé
        if fail_attachment:
            log_screenshot_web_global(
                self.driver, title="Timeout: attachment not found after 15 minutes"
            )
            raise Exception("Timeout: attachment not found after 15 minutes")

    if not fail_attachment:
        result = WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, AUDITOR_ATTACHMENT_RESULT))
        )
        if result.text != "image":
            log_screenshot_web_global(
                self.driver, title="The message text found doesn't match"
            )
            raise Exception("The message text found doesn't match")