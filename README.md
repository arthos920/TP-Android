Write-Output ">>> OPTION 6 : JIRA PASS / FAIL status"

$opt6 = $false

try {

    if ($robotExitCode -eq 0) {
        $testStatus = "PASS"
    } else {
        $testStatus = "FAIL"
    }

    Write-Output "Robot exit code : $robotExitCode"
    Write-Output "Computed status  : $testStatus"

    $payload = @{
        issues = @($jiraIssueKey)
        data = @{
            status = $testStatus
            robotReportUrl = ($CI_PIPELINE_URL + "/artifacts/browse/results/report.html")
        }
    }

    $jsonBody = $payload | ConvertTo-Json -Depth 6 -Compress

    Write-Output "JSON payload:"
    Write-Output $jsonBody

    $hookUrl = "$JIRA_BASE_URL/rest/cb-automation/latest/hooks/108930444f44d31d6664b391e30c2656c6103c"

    $curlArgs = @(
        "-k"
        "-v"
        "-u", ("{0}:{1}" -f $JIRA_USERNAME, $JIRA_PASSWORD)
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