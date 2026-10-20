
def navigate_to_message_view(self):
    """
    Navigate to conversation tab from any screen.
    """

    if self.driver.current_package != APP_PACKAGE:
        self.driver.activate_app(APP_PACKAGE)

    try:
        WebDriverWait(self.driver, 3).until(
            EC.visibility_of_element_located(
                (By.ID, MENU_MSG_BUTTON)
            )
        )

    except TimeoutException:
        # Return directly to main activity
        self.driver.execute_script(
            "mobile: startActivity",
            {
                "component": f"{APP_PACKAGE}/{APP_MAIN}",
                "action": "android.intent.action.MAIN",
                "categories": [
                    "android.intent.category.LAUNCHER"
                ],
                "flags": "0x34000000",
                "wait": True,
                "stop": False
            }
        )

    try:
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located(
                (By.ID, MENU_MSG_BUTTON)
            )
        )

        WebDriverWait(self.driver, 10).until(
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
        raise Exception(
            "Failed to navigate to message view"
        )
