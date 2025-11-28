from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def verify_PTT_call(self, alias_initiator, alias_participant, call_type=None,
                    floor_time=None, datafile="FROM_SETTINGS_FILE"):
    """
    Version avec énormément de stratégies pour trouver l'élément Initiator.
    À toi ensuite de garder celles qui fonctionnent le mieux.
    """

    # -------------------------------------------------
    # 1. Récupération des données attendues (Excel)
    # -------------------------------------------------
    excelDict_initiator = SecureRecorderModule().initialize(alias_initiator, datafile)
    expected_initiator = f"{excelDict_initiator['FirstName']} {excelDict_initiator['LastName']}"

    excelDict_participant = SecureRecorderModule().initialize(alias_participant, datafile)
    expected_participant = f"{excelDict_participant['FirstName']} {excelDict_participant['LastName']}"

    if call_type is None:
        call_type = "PTT Call"
    expected_floor_time = floor_time

    # -------------------------------------------------
    # 2. Ouverture du toggle menu (ton code existant)
    # -------------------------------------------------
    try:
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-id='toggle-menu-button']"))
        ).click()
    except Exception:
        log_screenshot(self.driver)
        robot.api.logger.info("There is no item for your research")
        for i in range(7):
            time.sleep(5)
            try:
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()
                WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-id='toggle-menu-button']"))
                ).click()
                break
            except Exception:
                log_screenshot(self.driver)
        else:
            raise Exception("No item found after multiple attempts")

    # -------------------------------------------------
    # 3. Fonction interne : essaye un locator dans
    #    tous les iframes possibles + root
    # -------------------------------------------------
    def try_locator_everywhere(by, locator, timeout=5):
        """
        Essaie de trouver l'élément :
        - d'abord dans le root
        - puis dans chaque iframe
        Retourne (element, description_contexte) ou (None, None)
        """
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
        for index, frame in enumerate(frames):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(frame)
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, locator))
                )
                return el, f"{by} | {locator} | iframe index {index}"
            except Exception:
                continue
            finally:
                self.driver.switch_to.default_content()

        return None, None

    # -------------------------------------------------
    # 4. Toutes les stratégies possibles pour Initiator
    # -------------------------------------------------
    locator_strategies = [
        # 1) XPath le plus précis (title -> value -> span)
        (
            By.XPATH,
            "//div[@data-id='call-info']"
            "//div[@data-id='title' and contains(normalize-space(), 'Initiator')]"
            "/following-sibling::div[@data-id='value'][1]"
            "//span[@data-id='usergroup-user']",
            "call-info + title 'Initiator' → value → span"
        ),
        # 2) Même XPath mais sans ancrage call-info
        (
            By.XPATH,
            "//div[@data-id='title' and contains(normalize-space(), 'Initiator')]"
            "/following-sibling::div[@data-id='value'][1]"
            "//span[@data-id='usergroup-user']",
            "title 'Initiator' → value → span"
        ),
        # 3) Uniquement dans call-info : n'importe quel span usergroup-user
        (
            By.XPATH,
            "//div[@data-id='call-info']//span[@data-id='usergroup-user']",
            "call-info → span[data-id='usergroup-user']"
        ),
        # 4) Tous les span usergroup-user
        (
            By.XPATH,
            "//span[@data-id='usergroup-user']",
            "span[data-id='usergroup-user'] (global)"
        ),
        # 5) Variante contains() sur data-id (XPath)
        (
            By.XPATH,
            "//*[contains(@data-id,'usergroup-user')]",
            "contains(@data-id,'usergroup-user') (global)"
        ),
        # 6) CSS : call-info + span usergroup-user
        (
            By.CSS_SELECTOR,
            "div[data-id='call-info'] span[data-id='usergroup-user']",
            "CSS : call-info span[data-id='usergroup-user']"
        ),
        # 7) CSS : span usergroup-user global
        (
            By.CSS_SELECTOR,
            "span[data-id='usergroup-user']",
            "CSS : span[data-id='usergroup-user'] (global)"
        ),
        # 8) CSS : [data-id='usergroup-user'] (tous types d'éléments)
        (
            By.CSS_SELECTOR,
            "[data-id='usergroup-user']",
            "CSS : [data-id='usergroup-user'] (global)"
        ),
    ]

    initiator_element = None
    used_strategy = None

    # -------------------------------------------------
    # 5. On essaye toutes les stratégies ci-dessus
    # -------------------------------------------------
    for by, loc, desc in locator_strategies:
        robot.api.logger.info(f"Trying initiator locator: {desc}")
        el, context = try_locator_everywhere(by, loc, timeout=5)
        if el is not None:
            initiator_element = el
            used_strategy = context
            robot.api.logger.info(f"Initiator element FOUND with: {context}")
            break

    # -------------------------------------------------
    # 6. Fallback JavaScript direct (querySelector)
    # -------------------------------------------------
    if initiator_element is None:
        try:
            js = (
                "return document.querySelector("
                "'div[data-id=\"call-info\"] span[data-id=\"usergroup-user\"]')"
            )
            el = self.driver.execute_script(js)
            if el:
                initiator_element = el
                used_strategy = "JS querySelector call-info span[data-id='usergroup-user']"
                robot.api.logger.info("Initiator element FOUND with JS querySelector (call-info).")
        except Exception:
            pass

    if initiator_element is None:
        try:
            js = "return document.querySelector('span[data-id=\"usergroup-user\"]')"
            el = self.driver.execute_script(js)
            if el:
                initiator_element = el
                used_strategy = "JS querySelector span[data-id='usergroup-user']"
                robot.api.logger.info("Initiator element FOUND with JS querySelector (global).")
        except Exception:
            pass

    # Si après tout ça on n'a rien trouvé → erreur claire
    if initiator_element is None:
        log_screenshot(self.driver)
        raise Exception("Initiator element NOT FOUND with any strategy.")

    robot.api.logger.info(f"Initiator element resolved using: {used_strategy}")

    # -------------------------------------------------
    # 7. Attendre que React remplisse le texte
    # -------------------------------------------------
    actual_initiator = ""
    for _ in range(25):   # ~5 secondes max
        text1 = initiator_element.text.strip()
        text2 = (initiator_element.get_attribute("textContent") or "").strip()
        actual_initiator = text1 or text2
        if actual_initiator:
            break
        time.sleep(0.2)

    if not actual_initiator:
        log_screenshot(self.driver)
        raise Exception("Initiator element found but text is EMPTY (React hydration issue).")

    robot.api.logger.info(f"Initiator text found: '{actual_initiator}'")

    # -------------------------------------------------
    # 8. Comparaison avec la valeur attendue
    # -------------------------------------------------
    if expected_initiator not in actual_initiator:
        log_screenshot(self.driver)
        raise Exception(
            f"Initiator mismatch. Expected: {expected_initiator}, Actual: {actual_initiator}"
        )

    robot.api.logger.info(f"Initiator OK: expected '{expected_initiator}', got '{actual_initiator}'")

    # -------------------------------------------------
    # 9. ICI tu peux continuer avec :
    #    - vérification du participant
    #    - vérification du call_type
    #    - vérification du floor_time
    #    etc.
    # -------------------------------------------------
    # ... ton code de vérification complémentaire ...