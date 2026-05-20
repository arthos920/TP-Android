button = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@class,'x-btn') and contains(normalize-space(.),'Appliquer la configuration')]")))

button.click()