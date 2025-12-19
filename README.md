Write-Output "==============================="
Write-Output "START JIRA UPLOAD"
Write-Output "==============================="

$resultsZip   = Join-Path $env:CI_PROJECT_DIR "results.zip"
$jiraIssueKey = $ISSUE_KEY

# -------------------------
# OPTION 1 : XRAY import (direct)
# -------------------------
Write-Output ">>> OPTION 1 : XRAY import (direct)"
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
# OPTION 2 : XRAY import (via proxy)
# -------------------------
Write-Output ">>> OPTION 2 : XRAY import (via proxy)"
$option2Ok = $false
if ($env:PROXY -and $env:PROXY -ne "") {
    try {
        $cmd = @"
$CURL_PATH -k -X POST `
  -x $PROXY `
  -u $JIRA_USERNAME`:$JIRA_PASSWORD `
  -H "X-Atlassian-Token: no-check" `
  -F "file=@$resultsZip" `
  "$JIRA_URL_TEST_EXEC$jiraIssueKey"
"@
        Write-Output $cmd
        $res = Invoke-Expression $cmd
        Write-Output $res

        if ($LASTEXITCODE -eq 0) {
            Write-Output "OPTION 2 SUCCESS"
            $option2Ok = $true
        } else {
            Write-Warning "OPTION 2 FAILED"
        }
    }
    catch {
        Write-Warning "OPTION 2 EXCEPTION"
        Write-Warning $_
    }
} else {
    Write-Output "Aucun proxy configuré, passage à l’option suivante"
}

if ($option2Ok) {
    exit 0
}

# -------------------------
# OPTION 3 : Attacher le fichier dans Jira
# -------------------------
Write-Output ">>> OPTION 3 : Attach results.zip to Jira issue"
$option3Ok = $false
try {
    if ($env:PROXY -and $env:PROXY -ne "") {
        $cmd = @"
$CURL_PATH -k -X POST `
  -x $PROXY `
  -u $JIRA_USERNAME`:$JIRA_PASSWORD `
  -H "X-Atlassian-Token: no-check" `
  -F "file=@$resultsZip" `
  "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/attachments"
"@
    } else {
        $cmd = @"
$CURL_PATH -k -X POST `
  -u $JIRA_USERNAME`:$JIRA_PASSWORD `
  -H "X-Atlassian-Token: no-check" `
  -F "file=@$resultsZip" `
  "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/attachments"
"@
    }
    Write-Output $cmd
    $res = Invoke-Expression $cmd
    Write-Output $res

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 3 SUCCESS – Attached results.zip to Jira issue"
        $option3Ok = $true
    } else {
        Write-Warning "OPTION 3 FAILED"
    }
}
catch {
    Write-Warning "OPTION 3 EXCEPTION"
    Write-Warning $_
}

if ($option3Ok) {
    exit 0
}

# -------------------------
# OPTION 4 : JIRA comment (fallback)
# -------------------------
Write-Output ">>> OPTION 4 : JIRA comment (fallback)"
$option4Ok = $false
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
    $headers = @{ "Content-Type" = "application/json" }

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

    Write-Output "OPTION 4 SUCCESS – Comment added to Jira"
    $option4Ok = $true
}
catch {
    Write-Warning "OPTION 4 FAILED"
    Write-Warning $_
}

if ($option4Ok) {
    exit 0
}

# -------------------------
# ALL FAILED
# -------------------------
Write-Error "ALL JIRA METHODS FAILED (OPTION 1 + OPTION 2 + OPTION 3 + OPTION 4)"
exit 1