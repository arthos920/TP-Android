from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC

def safe_click(driver, by, locator, timeout=20):
    wait = WebDriverWait(driver, timeout)

    # attendre présence
    wait.until(EC.presence_of_element_located((by, locator)))

    # attendre visibilité
    element = wait.until(EC.visibility_of_element_located((by, locator)))

    # attendre cliquable
    element = wait.until(EC.element_to_be_clickable((by, locator)))

    # scroll explicite
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)

    # click JS fallback
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)