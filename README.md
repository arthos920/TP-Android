def wait_and_get_activation_code_js(self, timeout=15):
    """
    Attend l'apparition d'un code d'activation dans une modale (ex : bloc .tokens-popup/.tokens-list)
    et renvoie le code sous forme de texte. Si le code n'apparaît pas dans le délai `timeout`, 
    une exception est levée.
    """
    # Prérequis d'import (à placer en haut du module utilisant cette fonction) :
    # from selenium.webdriver.common.by import By
    # from selenium.webdriver.support.ui import WebDriverWait
    # from selenium.webdriver.support import expected_conditions as EC
    # from selenium.common.exceptions import TimeoutException
    
    code_text = None
    
    # Étape 1 : Attendre la présence d'au moins un élément <strong> dans .tokens-list (visible ou non)
    print("[Info] Tentative 1 : attente d'un élément <strong> dans .tokens-list ...")
    log_screenshot_web_global(self.driver, title="Avant tentative 1 - attente .tokens-list")
    try:
        elements = WebDriverWait(self.driver, timeout).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".tokens-list strong"))
        )
        # Récupérer le texte de chaque <strong> trouvé (même si l'élément est potentiellement caché)
        codes = []
        for el in elements:
            text = el.get_attribute("textContent") or ""
            text = text.strip()
            if text:
                codes.append(text)
        if codes:
            code_text = " ".join(codes)
            print(f"[Info] Code d'activation trouvé via .tokens-list : {code_text}")
    except Exception as e:
        print(f"[Debug] Tentative 1 échouée : {e}")
    finally:
        log_screenshot_web_global(self.driver, title="Après tentative 1 - présence .tokens-list")
    if code_text:
        return code_text
    
    # Étape 2 : Si rien n'a été trouvé, tenter via un élément <strong> dans .tokens-popup (structure alternative)
    print("[Info] Tentative 2 : attente d'un élément <strong> dans .tokens-popup ...")
    log_screenshot_web_global(self.driver, title="Avant tentative 2 - attente .tokens-popup")
    try:
        elements = WebDriverWait(self.driver, timeout).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".tokens-popup strong"))
        )
        # Récupérer le texte de chaque <strong> trouvé dans .tokens-popup
        codes = []
        for el in elements:
            text = el.get_attribute("textContent") or ""
            text = text.strip()
            if text:
                codes.append(text)
        if codes:
            code_text = " ".join(codes)
            print(f"[Info] Code d'activation trouvé via .tokens-popup : {code_text}")
    except Exception as e:
        print(f"[Debug] Tentative 2 échouée : {e}")
    finally:
        log_screenshot_web_global(self.driver, title="Après tentative 2 - présence .tokens-popup")
    if code_text:
        return code_text
    
    # Étape 3 : En dernier recours, extraction via l'exécution d'un script JavaScript parcourant le DOM
    print("[Info] Tentative 3 : recherche du code via exécution JavaScript...")
    log_screenshot_web_global(self.driver, title="Avant tentative 3 - exécution JS")
    try:
        script = """
            const listElems = document.querySelectorAll('.tokens-list strong');
            const popupElems = document.querySelectorAll('.tokens-popup strong');
            let texts = [];
            listElems.forEach(el => texts.push(el.textContent.trim()));
            if (texts.length === 0) {
                popupElems.forEach(el => texts.push(el.textContent.trim()));
            }
            texts = texts.filter(t => t);  // supprimer les entrées vides
            return texts.join(' ');
        """
        result = self.driver.execute_script(script)
        if result:
            code_text = str(result).strip()
            print(f"[Info] Code d'activation obtenu via JS : {code_text}")
    except Exception as e:
        print(f"[Debug] Tentative 3 échouée (JS) : {e}")
    finally:
        log_screenshot_web_global(self.driver, title="Après tentative 3 - résultat JS")
    if code_text:
        return code_text
    
    # Si aucun code n'a été trouvé à ce stade, lever une exception explicite pour signaler l'échec
    message = f"Code d'activation introuvable après {timeout} secondes d'attente"
    print(f"[Erreur] {message}")
    raise TimeoutException(message)