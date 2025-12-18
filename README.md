Write-Output "======================================"
Write-Output "START JIRA UPLOAD TESTS"
Write-Output "======================================"

$zipPath = "$PWD\results.zip"
$jiraAttachmentUrl = "$JIRA_URL/rest/api/2/issue/$ISSUE_KEY/attachments"

if (!(Test-Path $zipPath)) {
    Write-Error "results.zip not found"
    exit 1
}

# -------------------------------------------------
# OPTION 1 – XRAY IMPORT (robot output.xml)
# -------------------------------------------------
Write-Output ">>> OPTION 1: XRAY import"

try {
    $xrayUrl = "$JIRA_URL/rest/raven/1.0/import/execution/robot?testExecKey=$ISSUE_KEY"

    curl.exe -k `
        -u "$JIRA_USERNAME:$JIRA_PASSWORD" `
        -F "file=@results\output.xml" `
        $xrayUrl

    Write-Output "⚠️ OPTION 1 executed (check Xray UI)"
}
catch {
    Write-Warning "OPTION 1 FAILED"
}

# -------------------------------------------------
# OPTION 2 – CURL ZIP ATTACHMENT
# -------------------------------------------------
Write-Output ">>> OPTION 2: ZIP upload via curl"

try {
    curl.exe -k `
        -u "$JIRA_USERNAME:$JIRA_PASSWORD" `
        -H "X-Atlassian-Token: no-check" `
        -F "file=@$zipPath" `
        "$jiraAttachmentUrl"

    Write-Output "⚠️ OPTION 2 executed (curl)"
}
catch {
    Write-Warning "OPTION 2 FAILED"
}

# -------------------------------------------------
# OPTION 3 – POWERSHELL INVOKE-RESTMETHOD (RECOMMANDÉ)
# -------------------------------------------------
Write-Output ">>> OPTION 3: ZIP upload via Invoke-RestMethod"

try {
    $headers = @{
        "X-Atlassian-Token" = "no-check"
    }

    $cred = New-Object System.Management.Automation.PSCredential(
        $JIRA_USERNAME,
        (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
    )

    Invoke-RestMethod `
        -Uri $jiraAttachmentUrl `
        -Method Post `
        -Headers $headers `
        -Credential $cred `
        -InFile $zipPath `
        -ContentType "application/zip"

    Write-Output "✅ OPTION 3 SUCCESS"
    Write-Output "======================================"
    Write-Output "JIRA UPLOAD SUCCESSFUL"
    Write-Output "======================================"
    exit 0
}
catch {
    Write-Warning "OPTION 3 FAILED"
}

Write-Error "❌ ALL JIRA UPLOAD METHODS FAILED"
exit 1