def filter_by_date_range(self):
    """
    Filters communications using a default time range.
    """
    now = datetime.now()

    target_dt = now - timedelta(hours=2, minutes=3)
    target_dt_end = now - timedelta(hours=1, minutes=58)

    start_date = target_dt.strftime("%m/%d/%Y")
    start_time = target_dt.strftime("%H:%M")
    end_date = target_dt_end.strftime("%m/%d/%Y")
    end_time = target_dt_end.strftime("%H:%M")

    date_fields = self.get_components(
        By.XPATH,
        self.build_xpath()
        .element(class_word="timeframe")
        .descendant()
        .element(
            tag="input",
            placeholder=_SERVER_TEXT_SET_DATE,
            type=_SERVER_TYPE_FIELD
        )
        .has_ancestor.none_of(
            self.build_xpath()
            .element(style_contains="display: none")
        )
    )

    time_fields = self.get_components(
        By.XPATH,
        self.build_xpath()
        .element(class_word="timeframe")
        .descendant()
        .element(
            tag="input",
            placeholder=_SERVER_TEXT_SET_TIME,
            type=_SERVER_TYPE_FIELD
        )
        .has_ancestor.none_of(
            self.build_xpath()
            .element(style_contains="display: none")
        )
    )

    assert len(date_fields) == 2, "Expected 2 date fields"
    assert len(time_fields) == 2, "Expected 2 time fields"

    self._set_calendar_field(date_fields[0], start_date)
    self._set_calendar_field(date_fields[1], end_date)
    self._set_calendar_field(time_fields[0], start_time)
    self._set_calendar_field(time_fields[1], end_time)


def _set_calendar_field(self, component, value):
    self.driver.execute_script(
        "arguments[0].removeAttribute('readonly');",
        component
    )
    component.clear()
    component.send_keys(value)