Write-Output "==============================="
Write-Output "START JIRA UPLOAD (STABLE MODE)"
Write-Output "==============================="

$jiraIssueKey = $ISSUE_KEY
$resultsZip   = Join-Path $env:CI_PROJECT_DIR "results.zip"

# BASE JIRA URL (OBLIGATOIRE)
$JIRA_BASE_URL = "https://slc-toolset.common.airbusds.corp/jira"

# =====================================================
# OPTION 1 : XRAY IMPORT (curl DIRECT, sans Invoke-Expression)
# =====================================================
Write-Output ">>> OPTION 1 : XRAY import"

try {
    & $CURL_PATH `
        -k `
        -X POST `
        -u "$JIRA_USERNAME:$JIRA_PASSWORD" `
        -H "X-Atlassian-Token: no-check" `
        -F "file=@$resultsZip" `
        "$JIRA_URL_TEST_EXEC$jiraIssueKey"

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 1 SUCCESS"
        exit 0
    }
}
catch {
    Write-Warning "OPTION 1 FAILED"
}

# =====================================================
# OPTION 4 : JIRA COMMENT (ULTRA SAFE – PROXY FRIENDLY)
# =====================================================
Write-Output ">>> OPTION 4 : JIRA comment (fallback)"

try {
    $commentText = @"
📎 Robot Framework results available

Pipeline:
$CI_PIPELINE_URL

Artifacts:
$CI_PIPELINE_URL/artifacts/browse/results/

Files:
- report.html
- log.html
- output.xml
- results.zip
"@

    $commentBody = @{
        body = $commentText
    } | ConvertTo-Json -Depth 5

    Invoke-RestMethod `
        -Uri "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/comment" `
        -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $commentBody `
        -Credential (New-Object PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Proxy $PROXY `
        -ErrorAction Stop

    Write-Output "OPTION 4 SUCCESS – Jira comment added"
    exit 0
}
catch {
    Write-Error "ALL JIRA METHODS FAILED"
    Write-Error $_
    exit 1
}