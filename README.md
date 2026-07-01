DP_RECORD_CLASS = "RecordTogglePanel"
DP_SUMMARY_TITLE_CLASS = "SummaryTitle_InfoLeft"
DP_USERGROUP_CLASS = "UserGroup_UserGroup"
DP_TOGGLE_MENU_BUTTON_CLASS = "RecordToggleMenuButton_ToggleMenuButton"

builder = (
    self.build_xpath()
        .element(class_word=DP_RECORD_CLASS)
        .has_descendant(class_word=DP_SUMMARY_TITLE_CLASS)
        .has_descendant(class_word=DP_USERGROUP_CLASS, text=user_name)
        .element(class_word=DP_TOGGLE_MENU_BUTTON_CLASS)
)