
*** Test Cases ***
Comparer les coordonnées dans Liste 1 et Liste 2
    :FOR    ${index1}    IN RANGE    0    ${len(list1)}
    \    ${name1}=    Get From List    ${list1}    ${index1}    0
    \    ${coords1}=    Get From List    ${list1}    ${index1}    1
    
    # Chercher si le nom de Liste 1 existe dans Liste 2
    ${found}=    Set Variable    False
    :FOR    ${index2}    IN RANGE    0    ${len(list2)}
    \    ${name2}=    Get From List    ${list2}    ${index2}    0
    \    Run Keyword If    '${name1}' == '${name2}'    Set Variable    True
    \    Run Keyword If    ${found}    Break

    # Si le nom n'est pas trouvé, échouer le test
    Run Keyword If    not ${found}    Fail    Le nom ${name1} n'a pas été trouvé dans Liste 2

    # Si le nom est trouvé, comparer les coordonnées
    ${coords2}=    Get From List    ${list2}    ${index2}    1
    ${x1}, ${y1}=    Split String    ${coords1}    *    # Séparer les coordonnées à partir de "*"
    ${x2}, ${y2}=    Split String    ${coords2}    \n    # Séparer les coordonnées à partir de "\n"
    
    # Arrondir les coordonnées à 4 chiffres après la virgule
    ${x1_rounded}=    Evaluate    round(${x1}, 4)
    ${y1_rounded}=    Evaluate    round(${y1}, 4)
    ${x2_rounded}=    Evaluate    round(${x2}, 4)
    ${y2_rounded}=    Evaluate    round(${y2}, 4)

    # Comparer les coordonnées
    Run Keyword If    '${x1_rounded}' == '${x2_rounded}' AND '${y1_rounded}' == '${y2_rounded}'    Log    Les coordonnées pour ${name1} sont égales
    Run Keyword If    '${x1_rounded}' != '${x2_rounded}' OR '${y1_rounded}' != '${y2_rounded}'    Fail    Les coordonnées de ${name1} ne correspondent pas : ${x1_rounded}, ${y1_rounded} != ${x2_rounded}, ${y2_rounded}
