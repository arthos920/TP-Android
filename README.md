def filter_by_user(self, user_name):
    self.type_text(
        user_name,
        By.XPATH,
        self.build_xpath()
            .element(class_word="row with-selector", role="users-selector-section")
            .element(class_word="ui selection dropdown optgroup search multiple")
            .element(tag="input", class_word="search")
    )