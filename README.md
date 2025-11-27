initiator_element = WebDriverWait(self.driver, 10).until(
    EC.visibility_of_element_located((
        By.XPATH,
        "//div[@data-id='title' and contains(., 'Initiator')]/following::div[@data-id='value'][1]//span[@data-id='usergroup-user']"
    ))
)
actual_initiator = initiator_element.text.strip()

if expected_initiator not in actual_initiator:
    raise Exception(f"Initiator mismatch. Expected: {expected_initiator}, Actual: {actual_initiator}")