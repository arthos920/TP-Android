def mobile_activation_code_excel(self, alias, datafile="FROM_SETTINGS_FILE"):
    excelDict = KeyCloackModule().initialize(alias, datafile)
    username = excelDict["FirstName"]

    self.select_user(username)

    self.safe_click(By.XPATH, locators.ACTIVATION_NAVIGATION)
    self.safe_click(By.XPATH, locators.MOBILE_ACTIVATION)
    self.safe_click(By.XPATH, locators.SAVE_BUTTON)
    self.safe_click(By.XPATH, locators.CONFIRM_MODAL_SAVE)

    elem = WebDriverWait(self.driver, 20).until(
        EC.visibility_of_element_located(
            (By.XPATH, locators.MOBILE_ACTIVATION_CODE)
        )
    )

    result = elem.text
    print(f"Activation code: {result}")

    self.safe_click(By.XPATH, locators.CLOSE_ACTIVATION_CODE)

    return result