Write-Output "==============================="
Write-Output "START JIRA UPLOAD"
Write-Output "==============================="

$resultsZip = Join-Path $env:CI_PROJECT_DIR "results.zip"
$jiraIssueKey = $ISSUE_KEY

# -------------------------
# OPTION 1 : XRAY IMPORT
# -------------------------
Write-Output ">>> OPTION 1 : XRAY import"

$option1Ok = $false
try {
    $cmd = @"
$CURL_PATH -k -X POST `
  -u $JIRA_USERNAME`:$JIRA_PASSWORD `
  -H "X-Atlassian-Token: no-check" `
  -F "file=@$resultsZip" `
  "$JIRA_URL_TEST_EXEC$jiraIssueKey"
"@

    Write-Output $cmd
    $res = Invoke-Expression $cmd
    Write-Output $res

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 1 SUCCESS"
        $option1Ok = $true
    } else {
        Write-Warning "OPTION 1 FAILED"
    }
}
catch {
    Write-Warning "OPTION 1 EXCEPTION"
    Write-Warning $_
}

if ($option1Ok) {
    exit 0
}

# -------------------------
# OPTION 3 : JIRA COMMENT
# -------------------------
Write-Output ">>> OPTION 3 : JIRA comment (fallback)"

$option3Ok = $false
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

    $commentUrl = "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/comment"

    $headers = @{
        "Content-Type" = "application/json"
    }

    $res = Invoke-RestMethod `
        -Uri $commentUrl `
        -Method POST `
        -Headers $headers `
        -Body $commentBody `
        -Credential (New-Object System.Management.Automation.PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Proxy $PROXY

    Write-Output "OPTION 3 SUCCESS – Comment added to Jira"
    $option3Ok = $true
}
catch {
    Write-Warning "OPTION 3 FAILED"
    Write-Warning $_
}

if ($option3Ok) {
    exit 0
}

# -------------------------
# ALL FAILED
# -------------------------
Write-Error "ALL JIRA METHODS FAILED (OPTION 1 + OPTION 3)"
exit 1