${timeout}=    Convert Time    ${PTT_duration}
${start}=      Get Time    epoch

${driver1_ok_count}=      Set Variable    0
${driver2_ok_count}=      Set Variable    0
${driver1_fail_count}=    Set Variable    0
${driver2_fail_count}=    Set Variable    0

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

    ${driver1_ok}=    Run Keyword And Return Status    driver1.use_ptt_release
    Sleep    1s

    ${driver2_ok}=    Run Keyword And Return Status    driver2.use_ptt_release
    Sleep    1s

    IF    ${driver1_ok}
        ${driver1_ok_count}=    Evaluate    ${driver1_ok_count} + 1
    ELSE
        ${driver1_fail_count}=    Evaluate    ${driver1_fail_count} + 1
    END

    IF    ${driver2_ok}
        ${driver2_ok_count}=    Evaluate    ${driver2_ok_count} + 1
    ELSE
        ${driver2_fail_count}=    Evaluate    ${driver2_fail_count} + 1
    END

    ${now}=              Get Time    epoch
    ${elapsed}=          Evaluate    ${now} - ${start}
    ${total_ok}=         Evaluate    ${driver1_ok_count} + ${driver2_ok_count}
    ${total_fail}=       Evaluate    ${driver1_fail_count} + ${driver2_fail_count}
    ${total_attempts}=   Evaluate    ${total_ok} + ${total_fail}
    ${elapsed_minutes}=  Evaluate    ${elapsed} / 60.0
    ${avg_ptt}=          Evaluate    round(${total_ok} / max(${elapsed_minutes}, 0.01), 2)
    ${fail_rate}=        Evaluate    round((${total_fail} / max(${total_attempts}, 1)) * 100, 2)

    Log To Console    [ENDURANCE] Driver1=${driver1_ok_count} | Driver2=${driver2_ok_count} | Total=${total_ok} | Elapsed=${elapsed}s | Avg=${avg_ptt} PTT/min | Fail=${total_fail} (${fail_rate}%)
END