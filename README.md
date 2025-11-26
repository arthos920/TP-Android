from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def click_group(self, user_name):
    xpath = f"""
    //div[
        (translate(normalize-space(text()),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') = '{user_name.lower()}'
        or starts-with(translate(normalize-space(text()),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), concat('{user_name.lower()}', ' (')))
        and @data-id='option-selector'
    ]
    """

    # 1️⃣ Attendre que les éléments soient présents dans le DOM
    elements = WebDriverWait(self.driver, 10).until(
        EC.presence_of_all_elements_located((By.XPATH, xpath))
    )

    target = None
    user_lower = user_name.lower()

    # 2️⃣ Trouver l'élément exact en vérifiant son texte en Python
    for el in elements:
        text = el.text.strip().lower()
        # match exact ou match avec chiffre entre parenthèses
        if text == user_lower or text.startswith(f"{user_lower} ("):
            target = el
            break

    if target is None:
        raise Exception(f"⚠️ Aucun élément ne correspond à '{user_name}'")

    # 3️⃣ Essayer de cliquer normalement
    try:
        WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(target))
        target.click()
        print(f"✅ Élément '{user_name}' cliqué avec Selenium.")
        return
    except Exception:
        print("⚠️ Clic Selenium impossible, tentative via JavaScript…")

    # 4️⃣ Fallback JavaScript
    self.driver.execute_script("arguments[0].click();", target)
    print(f"✅ Élément '{user_name}' cliqué via JavaScript.")