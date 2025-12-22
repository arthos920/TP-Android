btn = self.driver.find_element(By.XPATH, locators.CONFIRM_MODAL_SAVE)
self.driver.execute_script("arguments[0].click();", btn)