self.type_text(
    user_name,
    By.XPATH,
    self.build_xpath()
        .element(class_word="ui selection dropdown optgroup search multiple")
        .descendant()
        .element(tag="input", class_word="search")
)