def close_call_if_needed(self):
    """
    Clôture proprement tout appel encore actif.
    Fonction robuste utilisant self.driver.wait.
    """

    try:
        # -------------------------
        # 1. Si le bouton "hang up" (raccrocher) est présent
        # -------------------------
        hangup_btn = self.driver.wait(
            timeout=2,
            locator=('id', 'com.example.app:id/btn_hangup'),
            raise_exception=False
        )
        if hangup_btn:
            hangup_btn.click()
            return True

        # -------------------------
        # 2. Sinon on navigue vers la vue message
        # -------------------------
        if hasattr(self, "navigation_to_message_view"):
            self.navigation_to_message_view()

        # -------------------------
        # 3. Si le bouton Join est présent → cliquer
        # -------------------------
        join_btn = self.driver.wait(
            timeout=2,
            locator=('id', 'com.example.app:id/btn_join'),
            raise_exception=False
        )
        if join_btn:
            join_btn.click()

            # On tente de raccrocher juste après
            hangup_btn = self.driver.wait(
                timeout=4,
                locator=('id', 'com.example.app:id/btn_hangup'),
                raise_exception=False
            )
            if hangup_btn:
                hangup_btn.click()
            return True

        # -------------------------
        # 4. Si un texte "On going" apparaît → on clique puis raccrocher
        # -------------------------
        ongoing_cell = self.driver.wait(
            timeout=2,
            locator=('xpath', "//*[contains(@text, 'On going')]"),
            raise_exception=False
        )
        if ongoing_cell:
            ongoing_cell.click()

            hangup_btn = self.driver.wait(
                timeout=4,
                locator=('id', 'com.example.app:id/btn_hangup'),
                raise_exception=False
            )
            if hangup_btn:
                hangup_btn.click()
            return True

        return False  # Aucun call détecté

    except Exception as e:
        print(f"[close_call_if_needed] WARNING: Exception: {e}")
        return False
