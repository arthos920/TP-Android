def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        # --- Récupérer les coordonnées du bouton ---
        loc = ptt_button.location
        size = ptt_button.size

        x = int(loc["x"] + size["width"] / 2)
        y = int(loc["y"] + size["height"] / 2)

        robot.api.logger.info(f"PTT coords: {x},{y}")

        # --- Appuyer ---
        self.driver.execute_script("mobile: touch:down", {"x": x, "y": y})
        robot.api.logger.info("PTT pressed")

        time.sleep(1)   # durée d'appui → modifiable

        # --- Relâcher ---
        self.driver.execute_script("mobile: touch:up", {"x": x, "y": y})
        robot.api.logger.info("PTT released")

    except Exception as e:
        robot.api.logger.error("Does not manage to press/release PTT: " + str(e))
        raise Exception("Does not manage to press/release PTT")