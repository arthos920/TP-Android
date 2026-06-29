xpath = (
    f"//div[@data-id='record'"
    f" and .//div[@data-id='summary-title-info-left']"
    f"//span[@data-id='usergroup-user'"
    f" and contains(normalize-space(.), '{user_name}')]]"
    f"//div[@data-id='toggle-menu-button']"
)