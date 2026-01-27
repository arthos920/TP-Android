# Variables métier
${STARTED_OWNER}=    Set Variable    Christ1 Christ1
${JOINED_OWNERS}=    Set Variable    Dispatcher_Christ Dispatcher_Christ|Christ2 Christ2|Christ3 Christ3
${LEFT_OWNERS}=      Set Variable    Christ3 Christ3|Christ2 Christ2
${ENDED_OWNER}=      Set Variable    Christ1 Christ1

# Paramètres techniques
${TIMEOUT}=          Set Variable    120
${POLL_INTERVAL}=   Set Variable    2

auditor_verify_streaming_video_strict_order
...    started_owner=${STARTED_OWNER}
...    joined_owners=${JOINED_OWNERS}
...    left_owners=${LEFT_OWNERS}
...    ended_owner=${ENDED_OWNER}
...    timeout=${TIMEOUT}
...    poll_interval=${POLL_INTERVAL}