def wait_and_get_activation_code_js(self, timeout=30):
    """
    Attend que le code d'activation apparaisse dans le popup
    et le retourne via JavaScript (robuste headless / CI)
    """
    wait = WebDriverWait(self.driver, timeout)

    # attendre que le <strong> existe
    wait.until(lambda d: d.execute_script("""
        return document.querySelectorAll('.tokens-list strong').length > 0;
    """))

    # récupérer le texte
    code = self.driver.execute_script("""
        const el = document.querySelector('.tokens-list strong');
        return el ? el.innerText.trim() : null;
    """)

    return code




def mobile_activation_code_excel(self, alias, datafile="FROM_SETTINGS_FILE"):
    excelDict = KeyCloackModule().initialize(alias, datafile)
    username = excelDict["FirstName"]

    self.select_user(username)

    self.safe_click(By.XPATH, locators.ACTIVATION_NAVIGATION)
    log_screenshot_web_global(self.driver, title="Activation navigation")

    self.safe_click(By.XPATH, locators.MOBILE_ACTIVATION)
    log_screenshot_web_global(self.driver, title="Mobile activation")

    self.safe_click(By.XPATH, locators.SAVE_BUTTON)
    log_screenshot_web_global(self.driver, title="Save")

    # clic JS pour être sûr
    btn = self.driver.find_element(By.XPATH, locators.CONFIRM_MODAL_SAVE)
    self.driver.execute_script("arguments[0].click();", btn)
    log_screenshot_web_global(self.driver, title="Confirm modal save")

    # récupération robuste du code
    result = self.wait_and_get_activation_code_js(timeout=30)

    print(f"Activation code: {result}")

    self.safe_click(By.XPATH, locators.CLOSE_ACTIVATION_CODE)
    log_screenshot_web_global(self.driver, title="Close activation popup")

    return result