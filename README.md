initiator_element = WebDriverWait(self.driver, 5).until(
    EC.visibility_of_element_located((
        By.XPATH,
        "//div[@data-id='title']/div[contains(text(),'Initiator')]/../../following-sibling::div//span[@data-id='usergroup-user']"
    ))
)