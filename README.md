def filter_by_date_range(self):
    """
    Filters communications using a default time range.
    """
    target_dt = datetime.now() - timedelta(hours=2, minutes=3)
    target_dt_end = datetime.now() - timedelta(hours=1, minutes=58)

    start_date = target_dt.strftime("%m/%d/%Y")
    start_time = target_dt.strftime("%I:%M %p")
    end_date = target_dt_end.strftime("%m/%d/%Y")
    end_time = target_dt_end.strftime("%I:%M %p")

    element = self.driver.find_element(
        By.XPATH,
        self.build_xpath()
            .element(data_id=SR_SELECT_START_DATE)
            .descendant()
            .element(tag="input")
    )
    self.driver.execute_script("arguments[0].removeAttribute('readonly');", element)
    element.clear()
    element.send_keys(start_date)

    element = self.driver.find_element(
        By.XPATH,
        self.build_xpath()
            .element(data_id=SR_SELECT_START_TIME)
            .descendant()
            .element(tag="input")
    )
    self.driver.execute_script("arguments[0].removeAttribute('readonly');", element)
    element.clear()
    element.send_keys(start_time)

    element = self.driver.find_element(
        By.XPATH,
        self.build_xpath()
            .element(data_id=SR_SELECT_END_DATE)
            .descendant()
            .element(tag="input")
    )
    self.driver.execute_script("arguments[0].removeAttribute('readonly');", element)
    element.clear()
    element.send_keys(end_date)

    element = self.driver.find_element(
        By.XPATH,
        self.build_xpath()
            .element(data_id=SR_SELECT_END_TIME)
            .descendant()
            .element(tag="input")
    )
    self.driver.execute_script("arguments[0].removeAttribute('readonly');", element)
    element.clear()
    element.send_keys(end_time)