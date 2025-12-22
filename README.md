def safe_click(self, by, locator, timeout=30):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    wait = WebDriverWait(self.driver, timeout)

    element = wait.until(EC.presence_of_element_located((by, locator)))
    wait.until(EC.visibility_of(element))
    wait.until(EC.element_to_be_clickable((by, locator)))

    # scroll obligatoire en CI
    self.driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});",
        element
    )

    # petit délai UI (stable)
    WebDriverWait(self.driver, 5).until(
        lambda d: element.is_displayed() and element.is_enabled()
    )

    try:
        element.click()
    except Exception:
        # fallback JS click (CI friendly)
        self.driver.execute_script("arguments[0].click();", element)