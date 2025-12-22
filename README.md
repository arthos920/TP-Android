

result = wait_for_text(
    self.driver,
    By.XPATH,
    locators.MOBILE_ACTIVATION_CODE,
    timeout=40
)

print(f"Activation code: {result}")




def wait_for_text(driver, by, locator, timeout=30):
    def _text_present(d):
        try:
            el = d.find_element(by, locator)
            return el.text.strip() != ""
        except:
            return False

    WebDriverWait(driver, timeout).until(_text_present)
    return driver.find_element(by, locator).text.strip()