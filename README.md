def play_audio(self):
    """
    This function is used to press play button on UI.
    """

    self.click_component(By.XPATH, PLAY_AUDIO)

    self.assert_component_with_attribute_exists(
        By.XPATH,
        "//div[@data-id='player-progress-bar']//div[contains(@class,'ProgressBar_InnerBar')]",
        "style",
        "width: 100%"
    )