from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

def close_time_popup(driver):
    # ESC ferme souvent les popups Semantic UI
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()

    # Clique “dans le vide” pour perdre le focus (au cas où ESC ne suffit pas)
    driver.find_element(By.TAG_NAME, "body").click()

    # Attendre que le popup soit invisible (adapter le CSS si besoin)
    WebDriverWait(driver, 10).until(
        EC.invisibility_of_element_located((By.CSS_SELECTOR, ".sw-calendar-popup:not(.hidden)"))
    )