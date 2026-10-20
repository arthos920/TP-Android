def navigate_to_message_view(self):

    try:
        WebDriverWait(self.driver, 3).until(
            EC.visibility_of_element_located(
                (By.ID, MENU_MSG_BUTTON)
            )
        )

    except TimeoutException:
        # Restart application to return to home screen
        self.driver.terminate_app(APP_PACKAGE)
        self.driver.activate_app(APP_PACKAGE)

    try:
        WebDriverWait(self.driver, 15).until(
            EC.visibility_of_element_located(
                (By.ID, NEW_MESSAGE_BUTTON)
            )
        )

    except TimeoutException:
        log_screenshot_web_global(
            self.driver,
            title="Failed to navigate to message view",
            keyword="navigate_to_message_view"
        )
        raise Exception("Failed to navigate to message view")