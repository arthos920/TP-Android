def wait_and_get_activation_code_js(self, timeout=30):
    wait = WebDriverWait(self.driver, timeout)

    # attendre que le code existe ET soit non vide
    wait.until(lambda d: d.execute_script("""
        const el = document.querySelector('.tokens-list strong');
        return el && el.textContent.trim().length > 0;
    """))

    # récupérer la valeur
    code = self.driver.execute_script("""
        return document.querySelector('.tokens-list strong').textContent.trim();
    """)

    log_screenshot_web_global(self.driver, title="activation_code_popup")
    return code