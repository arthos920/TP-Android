def waiting_for_events(
    self,
    expected_events: int,
    timeout: int = 1200,
    poll_interval: int = 5
):
    """
    Wait until the expected number of events appears on Secure Recorder UI.

    Args:
        expected_events: Number of events expected on the UI.
        timeout: Maximum waiting time in seconds.
        poll_interval: Time between each retry in seconds.
    """

    end_time = time.monotonic() + timeout
    last_exception = None

    target_locator = (
        By.XPATH,
        self.build_xpath().element(
            class_word=SR_RECORD_PANEL_CLASS
        )
    )

    while time.monotonic() < end_time:

        # Refresh Secure Recorder UI
        try:
            self.click_component(
                By.XPATH,
                self.build_xpath().element(
                    class_word=SR_CLASS_SWAP_BUTTON
                )
            )

            self.click_component(
                By.XPATH,
                self.build_xpath().element(
                    class_word=SR_CLASS_SWAP_BUTTON
                )
            )

        except Exception:
            pass

        try:

            def expected_number_of_events(driver):
                elements = driver.find_elements(*target_locator)

                visible_events = [
                    element
                    for element in elements
                    if element.is_displayed()
                ]

                return len(visible_events) >= expected_events

            WebDriverWait(
                self.driver,
                5
            ).until(
                expected_number_of_events
            )

            return

        except TimeoutException as e:
            last_exception = e
            time.sleep(poll_interval)

    error_msg = (
        f"Timeout after {timeout}s: "
        f"{expected_events} event(s) expected but never appeared."
    )

    raise TerminalException(
        error_msg,
        self
    ) from last_exception