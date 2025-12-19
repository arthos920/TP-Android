

$RESULTS_DIR = Join-Path $env:CI_PROJECT_DIR "results"
$RESULTS_ZIP = Join-Path $env:CI_PROJECT_DIR "results.zip"

$ISSUE = $ISSUE_KEY



Write-Output "========================================"
Write-Output " START JIRA UPLOAD (FULL CASCADE)"
Write-Output "========================================"

$success = $false

function Test-Exit {
    param ($label)
    if ($LASTEXITCODE -eq 0) {
        Write-Output "$label SUCCESS"
        return $true
    }
    Write-Warning "$label FAILED (exit=$LASTEXITCODE)"
    return $false
}

# ------------------------------------------------
# OPTION 1 — XRAY IMPORT (curl, no proxy)
# ------------------------------------------------
Write-Output ">>> OPTION 1 : XRAY import (NO PROXY)"

$XRAY_URL = "$JIRA_BASE_URL/rest/raven/1.0/api/testexec/$ISSUE"

& $CURL_PATH `
    -k `
    -u "$JIRA_USER`:$JIRA_PASS" `
    -H "X-Atlassian-Token: no-check" `
    -F "file=@$RESULTS_ZIP" `
    "$XRAY_URL"

if (Test-Exit "OPTION 1") { exit 0 }

# ------------------------------------------------
# OPTION 2 — XRAY IMPORT (curl + MAIN proxy)
# ------------------------------------------------
Write-Output ">>> OPTION 2 : XRAY import (MAIN PROXY)"

& $CURL_PATH `
    -k `
    -u "$JIRA_USER`:$JIRA_PASS" `
    -x "$PROXY_MAIN" `
    -H "X-Atlassian-Token: no-check" `
    -F "file=@$RESULTS_ZIP" `
    "$XRAY_URL"

if (Test-Exit "OPTION 2") { exit 0 }

# ------------------------------------------------
# OPTION 3 — ATTACH ZIP TO ISSUE (curl)
# ------------------------------------------------
Write-Output ">>> OPTION 3 : Attach ZIP to Jira issue"

$ATTACH_URL = "$JIRA_BASE_URL/rest/api/2/issue/$ISSUE/attachments"

& $CURL_PATH `
    -k `
    -u "$JIRA_USER`:$JIRA_PASS" `
    -H "X-Atlassian-Token: no-check" `
    -F "file=@$RESULTS_ZIP" `
    "$ATTACH_URL"

if (Test-Exit "OPTION 3") { exit 0 }

# ------------------------------------------------
# OPTION 4 — COMMENT JIRA (Invoke-RestMethod)
# ------------------------------------------------
Write-Output ">>> OPTION 4 : Jira comment fallback"

$commentText = @"
🤖 Robot Framework results available

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

try {
    Invoke-RestMethod `
        -Uri "$JIRA_BASE_URL/rest/api/2/issue/$ISSUE/comment" `
        -Method POST `
        -ContentType "application/json" `
        -Body $commentBody `
        -Credential (New-Object System.Management.Automation.PSCredential(
            $JIRA_USER,
            (ConvertTo-SecureString $JIRA_PASS -AsPlainText -Force)
        )) `
        -Proxy $PROXY_MAIN

    Write-Output "OPTION 4 SUCCESS"
    exit 0
}
catch {
    Write-Warning "OPTION 4 FAILED"
    Write-Warning $_
}

# ------------------------------------------------
# ALL FAILED
# ------------------------------------------------
Write-Error "ALL JIRA UPLOAD METHODS FAILED"
exit 1