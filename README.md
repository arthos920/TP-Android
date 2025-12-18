Write-Output "=== START JIRA UPLOAD ==="

$resultsDir = Join-Path (Get-Location) "results"
$outputXml  = Join-Path $resultsDir "output.xml"
$zipPath    = Join-Path (Get-Location) "results.zip"

$jiraBase = "https://slc-toolset.common.airbusds.corp"
$xrayUrl  = "$jiraBase/jira/rest/raven/1.0/import/execution/robot?testExecKey=$ISSUE_KEY"
$attachUrl = "$jiraBase/jira/rest/api/2/issue/$ISSUE_KEY/attachments"

$headers = @{ "X-Atlassian-Token" = "no-check" }

# Zip results
if (-not (Test-Path $zipPath)) {
    Write-Output "Zipping Robot Framework results..."
    Compress-Archive -Path "$resultsDir\*" -DestinationPath $zipPath -Force
}

# ------------------------------------------------------------
# OPTION 1 — XRAY IMPORT (output.xml)
# ------------------------------------------------------------
try {
    Write-Output ">>> OPTION 1: XRAY import"

    Invoke-RestMethod `
        -Uri $xrayUrl `
        -Method Post `
        -InFile $outputXml `
        -ContentType "application/xml" `
        -Credential (New-Object System.Management.Automation.PSCredential($JIRA_USERNAME,(ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force))) `
        -ErrorAction Stop

    Write-Output "OPTION 1 SUCCESS (XRAY IMPORT)"
    exit 0
}
catch {
    Write-Warning "OPTION 1 FAILED"
}

# ------------------------------------------------------------
# OPTION 2 — ZIP ATTACHMENT (NO PROXY)
# ------------------------------------------------------------
try {
    Write-Output ">>> OPTION 2: ZIP upload (NO PROXY)"

    [System.Net.WebRequest]::DefaultWebProxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()

    Invoke-RestMethod `
        -Uri $attachUrl `
        -Method Post `
        -InFile $zipPath `
        -ContentType "application/zip" `
        -Headers $headers `
        -Credential (New-Object System.Management.Automation.PSCredential($JIRA_USERNAME,(ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force))) `
        -ErrorAction Stop

    Write-Output "OPTION 2 SUCCESS (ZIP NO PROXY)"
    exit 0
}
catch {
    Write-Warning "OPTION 2 FAILED"
}

# ------------------------------------------------------------
# OPTION 3 — ZIP ATTACHMENT (WITH PROXY)
# ------------------------------------------------------------
try {
    Write-Output ">>> OPTION 3: ZIP upload (WITH PROXY)"

    Invoke-RestMethod `
        -Uri $attachUrl `
        -Method Post `
        -InFile $zipPath `
        -ContentType "application/zip" `
        -Headers $headers `
        -Credential (New-Object System.Management.Automation.PSCredential($JIRA_USERNAME,(ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force))) `
        -Proxy $PROXY `
        -ErrorAction Stop

    Write-Output "OPTION 3 SUCCESS (ZIP WITH PROXY)"
    exit 0
}
catch {
    Write-Error "ALL JIRA UPLOAD METHODS FAILED"
    exit 1
}