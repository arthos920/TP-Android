Write-Output "==============================="
Write-Output "START JIRA UPLOAD (FULL CASCADE)"
Write-Output "==============================="

$resultsZip    = Join-Path $env:CI_PROJECT_DIR "results.zip"
$jiraIssueKey  = $ISSUE_KEY
$authString    = "${JIRA_USERNAME}:${JIRA_PASSWORD}"

# =========================
# OPTION 1 : XRAY IMPORT
# =========================
Write-Output ">>> OPTION 1 : XRAY import"

try {
    $cmd = @"
"$CURL_PATH" -k -X POST `
  -u "$authString" `
  -H "X-Atlassian-Token: no-check" `
  -F "file=@$resultsZip" `
  "$JIRA_URL_TEST_EXEC$jiraIssueKey"
"@

    Write-Output $cmd
    Invoke-Expression $cmd

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 1 SUCCESS"
        exit 0
    } else {
        Write-Warning "OPTION 1 FAILED (exit code $LASTEXITCODE)"
    }
}
catch {
    Write-Warning "OPTION 1 EXCEPTION"
    Write-Warning $_
}

# =========================
# OPTION 4 : JIRA COMMENT (SAFE FALLBACK)
# =========================
Write-Output ">>> OPTION 4 : JIRA comment"

try {
    $commentBody = @{
        body = @"
🧪 Robot Framework results available

Pipeline:
$CI_PIPELINE_URL

Artifacts:
$CI_PIPELINE_URL/artifacts/browse/results/

Main files:
- report.html
- log.html
- output.xml
- results.zip
"@
    } | ConvertTo-Json -Depth 5

    $commentUrl = "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/comment"

    Invoke-RestMethod `
        -Uri $commentUrl `
        -Method POST `
        -Body $commentBody `
        -ContentType "application/json" `
        -Credential (New-Object System.Management.Automation.PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Proxy $PROXY

    Write-Output "OPTION 4 SUCCESS – Comment added to Jira"
    exit 0
}
catch {
    Write-Warning "OPTION 4 FAILED"
    Write-Warning $_
}

Write-Error "ALL JIRA METHODS FAILED"
exit 1