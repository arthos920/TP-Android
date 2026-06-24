option = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((
        By.XPATH,
        f"//div[@data-id='option-selector' and contains(., '{user_name}')]"
    ))
)

option.click()