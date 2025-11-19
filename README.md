def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        # ---- 1) Appui long (tu gardes ton ActionChains de maintien) ----
        ActionChains(self.driver).move_to_element(ptt_button).pause(1).click_and_hold().perform()
        robot.api.logger.info("Press on PTT OK")

        WebDriverWait(self.driver, 2).until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(@text, 'Transm')]"))
        )
        robot.api.logger.info("PTT in progress")

        # Maintien 5 secondes
        time.sleep(5)

        # ---- 2) RELÂCHEMENT TACTILE ----
        # → Click en dehors du bouton (ex : x=10, y=10)
        self.driver.execute_script("mobile: clickGesture", {"x": 10, "y": 10})
        robot.api.logger.info("PTT released")

    except TimeoutException:
        robot.api.logger.info("Does not manage to take the PTT")
        raise Exception("Does not manage to take the PTT")

    if screenshots:
        log_screenshot(self.driver)