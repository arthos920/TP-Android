def wait_for_text(self, by, locator, timeout=30):

    def _text_present(driver):
        try:
            el = driver.find_element(by, locator)
            return el.text.strip() != ""
        except:
            return False

    WebDriverWait(self.driver, timeout).until(_text_present)
    return self.driver.find_element(by, locator).text.strip()