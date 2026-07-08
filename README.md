def filter_by_user(self, user_name):
    self.type_text(
        user_name,
        By.XPATH,
        self.build_xpath()
            .element(data_role="users-selector-section")
            .element(tag="*", data_role="users-selector")
            .following_sibling()
            .element(tag="input", class_word="search")
    )