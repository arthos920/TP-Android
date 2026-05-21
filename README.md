*** Settings ***
Library    DateTime
Library    OperatingSystem


*** Variables ***
${conversation_name}      SMOKE_TEST_AUTO
${PTT_duration}           24 hours
${CONTROL_FILE}           continue.txt


*** Keywords ***
Create Endurance Control File
    Create File    ${CONTROL_FILE}    endurance running

Check Endurance Control
    ${exists}=    File Should Exist    ${CONTROL_FILE}
    ...    msg=Stop requested: ${CONTROL_FILE} was removed

Stop Apps
    driver1.stop_app
    driver2.stop_app


*** Test Cases ***
Endurance between Smartphone and Smartphone
    [Setup]    Create Endurance Control File
    [Teardown]    Stop Apps

    driver1.setup_device    desired_capabilities=${desired_capabilities_SMARTPHONE1}
    driver2.setup_device    desired_capabilities=${desired_capabilities_SMARTPHONE2}

    driver1.navigate to talk group view
    driver2.navigate to talk group view

    driver1.Connect Group    ${conversation_name}
    driver2.Connect Group    ${conversation_name}

    Sleep    2s

    driver1.open ptt view
    driver2.open ptt view

    ${timeout}=    Convert Time    ${PTT_duration}
    ${start}=      Get Time    epoch

    WHILE    ${True}
        ${status}=    Run Keyword And Return Status    File Should Exist    ${CONTROL_FILE}
        IF    not ${status}
            Log To Console    [ENDURANCE] Stop requested by removing ${CONTROL_FILE}
            Exit For Loop
        END

        ${now}=        Get Time    epoch
        ${elapsed}=    Evaluate    ${now} - ${start}

        IF    ${elapsed} >= ${timeout}
            Log To Console    [ENDURANCE] Duration reached: ${PTT_duration}
            Exit For Loop
        END

        Run Keyword And Continue On Failure    driver1.run_ptt_release
        Run Keyword And Continue On Failure    driver1.Check Reception    False

        Sleep    1s

        Run Keyword And Continue On Failure    driver2.run_ptt_release
        Run Keyword And Continue On Failure    driver2.Check Reception    False

        Sleep    1s
    END

    driver1.Quit ptt
    driver2.Quit ptt

    driver1.navigate to talk group view
    driver1.Disconnect Group    ${conversation_name}

    driver2.navigate to talk group view
    driver2.Disconnect Group    ${conversation_name}