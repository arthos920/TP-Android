from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException

def wait_for_text(self, by, locator, timeout=30):

    def _text_present(driver):
        try:
            el = driver.find_element(by, locator)
            text = el.text.strip()
            return text != ""
        except StaleElementReferenceException:
            return False
        except Exception:
            return False

    WebDriverWait(self.driver, timeout).until(_text_present)
    return self.driver.find_element(by, locator).text.strip()