def waiting_for_event(self, timeout=1200, poll_interval=5):
    end_time = time.monotonic() + timeout
    last_exception = None

    while time.monotonic() < end_time:
        try:
            self.click_component(
                By.XPATH,
                self.build_xpath().element(class_word=SR_CLASS_SWAP_BUTTON)
            )
            self.click_component(
                By.XPATH,
                self.build_xpath().element(class_word=SR_CLASS_SWAP_BUTTON)
            )
        except Exception:
            pass

        try:
            target_locator = (
                By.XPATH,
                self.build_xpath().element(class_word=SR_TOGGLE_BUTTON_CLASS)
            )

            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located(target_locator)
            )
            return

        except TimeoutException as e:
            last_exception = e
            time.sleep(poll_interval)

    error_msg = f"Timeout after {timeout}s: Element never appeared."
    raise TerminalException(error_msg, self) from last_exception