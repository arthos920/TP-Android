def filter_by_user(self, user_name):
    self.type_text(
        user_name,
        By.XPATH,
        self.build_xpath()
            .element(class_word="ui selection dropdown optgroup search multiple")
            .element(tag="div", class_word="menu")
            .preceding_sibling()
            .element(tag="input", class_word="search")
    )