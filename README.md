*** Settings ***
Library    SikuliLibrary
Library    BuiltIn

*** Keywords ***
Find Image On Any Screen (Keep Found Id)
    [Documentation]    Cherche ${image_path} sur tous les écrans. 
    ...                Si trouvé: exécute `Setup Test` et laisse le Screen Id sur celui où l’image a été trouvée.
    [Arguments]    ${image_path}    ${timeout}=2
    ${screen_count}=    Get Number Of Screens

    :FOR    ${id}    IN RANGE    ${screen_count}
    \    Change Screen Id    ${id}
    \    ${found}=    Exists    ${image_path}    ${timeout}
    \    Run Keyword If    ${found}    Run Keywords
    \    ...    Setup Test
    \    ...    AND    Return From Keyword    ${id}

    Fail    Image not found on any screen (scanned ${screen_count} screens)
