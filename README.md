xpath = (

    f"//div[@data-id='record' "

    f"and .//span[@data-id='usergroup-user' "

    f"and contains(normalize-space(.), '{user_name}')]]"

    f"//div[@data-id='toggle-menu-button']"

)

