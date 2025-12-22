def wait_and_get_activation_code_js(self, timeout=30):
    wait = WebDriverWait(self.driver, timeout)

    # 1️⃣ attendre que le popup existe ET soit visible
    wait.until(lambda d: d.execute_script("""
        const popup = document.querySelector('.tokens-popup');
        if (!popup) return false;
        const style = window.getComputedStyle(popup);
        return style && style.display !== 'none' && style.visibility !== 'hidden';
    """))

    # 2️⃣ attendre que le code soit injecté
    wait.until(lambda d: d.execute_script("""
        const el = document.querySelector('.tokens-popup .tokens-list strong');
        return el && el.textContent.trim().length > 0;
    """))

    # 3️⃣ récupérer le code
    code = self.driver.execute_script("""
        return document.querySelector('.tokens-popup .tokens-list strong').textContent.trim();
    """)

    log_screenshot_web_global(self.driver, title="activation_code_popup_visible")
    return code