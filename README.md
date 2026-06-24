def verify_call_type(self, expected_call_type: str):
    xpath = (
        f"//div[@data-id='call-info']"
        f"//div[contains(@class,'CallInfo_CallType')]"
        f"[contains(normalize-space(.), '{expected_call_type}')]"
    )
    self.assert_component_exists(By.XPATH, xpath)