def type_text(self, text: str, *locator, open_keyboard_dummy: bool = False, **kwargs):
    """
    CI-safe text typing with full JS event simulation
    """

    driver = self.driver
    field = self.get_component(*locator, **kwargs)

    # Screenshot avant
    log_screenshot_web_global(driver, title="type_text_before")

    # 1️⃣ Focus explicite
    driver.execute_script("arguments[0].focus();", field)

    # 2️⃣ Clear robuste (send_keys + JS)
    try:
        field.clear()
    except Exception:
        pass

    driver.execute_script("arguments[0].value = '';", field)

    # 3️⃣ Taper caractère par caractère (plus fiable en CI)
    for char in text:
        field.send_keys(char)
        time.sleep(0.02)

    # 4️⃣ Forcer TOUS les events JS importants
    driver.execute_script("""
        const el = arguments[0];

        el.dispatchEvent(new Event('keydown', { bubbles: true }));
        el.dispatchEvent(new Event('keyup', { bubbles: true }));
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));

        // Certains frameworks écoutent ça
        el.dispatchEvent(new Event('focusout', { bubbles: true }));
    """, field)

    # 5️⃣ Sécurité : forcer la valeur si JS l’a mangée
    value = field.get_attribute("value")
    if value != text:
        driver.execute_script("arguments[0].value = arguments[1];", field, text)

    # 6️⃣ Forcer validation du formulaire si présent
    driver.execute_script("""
        const el = arguments[0];
        const form = el.closest('form');
        if (form) {
            form.dispatchEvent(new Event('input', { bubbles: true }));
            form.dispatchEvent(new Event('change', { bubbles: true }));
        }
    """, field)

    # Screenshot après
    log_screenshot_web_global(driver, title="type_text_after")