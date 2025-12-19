Write-Output ">>> OPTION 6 : JIRA PASS / FAIL status"

$opt6 = $false

try {
    # ----------------------------------------
    # Determine status from Robot exit code
    # ----------------------------------------
    if ($robotExitCode -eq 0) {
        $testStatus = "PASS"
    } else {
        $testStatus = "FAIL"
    }

    Write-Output "Robot exit code : $robotExitCode"
    Write-Output "Computed status  : $testStatus"

    # ----------------------------------------
    # JSON payload (same as Jenkins logic)
    # ----------------------------------------
    $jsonBody = @{
        issues = @($jiraIssueKey)
        data = @{
            status = $testStatus
            robotReportUrl = "$CI_PIPELINE_URL/artifacts/browse/results/report.html"
        }
    } | ConvertTo-Json -Depth 5 -Compress

    Write-Output "JSON payload:"
    Write-Output $jsonBody

    # ----------------------------------------
    # Webhook URL
    # ----------------------------------------
    $hookUrl = "$JIRA_BASE_URL/rest/cb-automation/latest/hooks/108930444f44d31d6664b391e30c2656c6103c"

    # ----------------------------------------
    # Build curl arguments SAFELY
    # ----------------------------------------
    $curlArgs = @(
        "-k"
        "-v"
        "-u", "${JIRA_USERNAME}:${JIRA_PASSWORD}"
        "-X", "POST"
        "-H", "Content-Type: application/json"
        "-d", $jsonBody
        $hookUrl
    )

    Write-Output "Executing curl:"
    $curlArgs | ForEach-Object { Write-Output "  $_" }

    & "$CURL_PATH" @curlArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 6 SUCCESS – Status sent to Jira ($testStatus)"
        $opt6 = $true
    } else {
        Write-Warning "curl exited with code $LASTEXITCODE"
    }
}
catch {
    Write-Warning "OPTION 6 FAILED"
    Write-Warning $_
}

Exit-IfSuccess $opt6 "OPTION 6 (PASS / FAIL)"