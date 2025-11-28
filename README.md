def verify_call_type(self, expected_call_type):
    """
    Vérifie le Call Type avec toutes les stratégies possibles.
    Fonction robuste compatible React Fiber, SVG, hydration lente
    et potentiels iframes.
    """

    import time
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # ----------------------------------------------------------
    # Fonction interne : tester un locator dans root + iframes
    # ----------------------------------------------------------
    def try_locator_everywhere(by, locator, timeout=5):
        # 1) root
        try:
            el = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, locator))
            )
            return el, f"{by} | {locator} | root"
        except Exception:
            pass

        # 2) iframes
        frames = self.driver.find_elements(By.TAG_NAME, "iframe")
        for idx, frame in enumerate(frames):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(frame)
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, locator))
                )
                return el, f"{by} | {locator} | iframe {idx}"
            except Exception:
                continue
            finally:
                self.driver.switch_to.default_content()

        return None, None

    # ----------------------------------------------------------
    # Toutes les stratégies possibles pour identifier Call Type
    # ----------------------------------------------------------
    strategies = [

        # 1 — XPath exact structure (le plus fiable)
        (
            By.XPATH,
            "//div[@data-id='title' and contains(normalize-space(), 'Call type')]"
            "/following-sibling::div[@data-id='value'][1]//*[not(self::svg)]",
            "XPath exact (title → value)"
        ),

        # 2 — XPath moins strict
        (
            By.XPATH,
            "//div[@data-id='title' and contains(normalize-space(), 'Call type')]"
            "/following-sibling::div[@data-id='value'][1]//*",
            "XPath title→value"
        ),

        # 3 — Dans call-info uniquement
        (
            By.XPATH,
            "//div[@data-id='call-info']//div[@data-id='value']//*[not(self::svg)]",
            "XPath call-info value"
        ),

        # 4 — cherche directement le texte du call type
        (
            By.XPATH,
            f"//*[contains(normalize-space(), '{expected_call_type}')]",
            "XPath text contains expected call type"
        ),

        # 5 — Value globale
        (
            By.XPATH,
            "//div[@data-id='value']//*[not(self::svg)]",
            "XPath global value"
        ),

        # 6 — CSS call-info + value
        (
            By.CSS_SELECTOR,
            "div[data-id='call-info'] div[data-id='value']",
            "CSS call-info > value"
        ),

        # 7 — CSS Value global
        (
            By.CSS_SELECTOR,
            "div[data-id='value']",
            "CSS value global"
        ),

        # 8 — classe spécifique CallType
        (
            By.CSS_SELECTOR,
            "div[class*='CallInfo_CallType']",
            "CSS class contains CallInfo_CallType"
        ),

        # 9 — XPath classe CallType
        (
            By.XPATH,
            "//*[contains(@class,'CallInfo_CallType')]",
            "XPath class contains CallInfo_CallType"
        )
    ]

    # ----------------------------------------------------------
    # Test de toutes les stratégies
    # ----------------------------------------------------------
    call_type_element = None
    strategy_used = None

    for by, loc, desc in strategies:
        try:
            robot.api.logger.info(f"[CALL TYPE] Trying locator: {desc}")
            el, ctx = try_locator_everywhere(by, loc)
            if el:
                call_type_element = el
                strategy_used = ctx
                robot.api.logger.info(f"[CALL TYPE] Found using: {ctx}")
                break
        except:
            continue

    # ----------------------------------------------------------
    # Fallback JS querySelector
    # ----------------------------------------------------------
    if call_type_element is None:
        try:
            js = "return document.querySelector(\"div[class*='CallInfo_CallType']\");"
            el = self.driver.execute_script(js)
            if el:
                call_type_element = el
                strategy_used = "JS querySelector div[class*='CallInfo_CallType']"
        except:
            pass

    if call_type_element is None:
        log_screenshot(self.driver)
        raise Exception("[CALL TYPE] Not found with ANY strategy")

    # ----------------------------------------------------------
    # Attente de l’hydratation React (texte vide pendant ~200ms)
    # ----------------------------------------------------------
    actual_call_type = ""
    for _ in range(20):
        text1 = call_type_element.text.strip()
        text2 = (call_type_element.get_attribute("textContent") or "").strip()
        actual_call_type = text1 or text2
        if actual_call_type:
            break
        time.sleep(0.2)

    if not actual_call_type:
        raise Exception("[CALL TYPE] Element found but text is EMPTY (React hydration)")

    robot.api.logger.info(f"[CALL TYPE] Value = '{actual_call_type}' "
                          f"(found with: {strategy_used})")

    # ----------------------------------------------------------
    # Vérification finale
    # ----------------------------------------------------------
    if expected_call_type not in actual_call_type:
        log_screenshot(self.driver)
        raise Exception(f"[CALL TYPE] MISMATCH — Expected: {expected_call_type}, "
                        f"Actual: {actual_call_type}")

    robot.api.logger.info(f"[CALL TYPE] OK — Expected '{expected_call_type}' found.")