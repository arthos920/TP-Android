Write-Output "=== START JIRA UPLOAD STRATEGY ==="

$resultsDir = Join-Path (Get-Location) "results"
$outputXml  = Join-Path $resultsDir "output.xml"
$zipPath    = Join-Path (Get-Location) "results.zip"

$jiraBase   = "https://slc-toolset.common.airbusds.corp"
$xrayUrl    = "$jiraBase/jira/rest/raven/1.0/import/execution/robot?testExecKey=$ISSUE_KEY"
$attachUrl  = "$jiraBase/jira/rest/api/2/issue/$ISSUE_KEY/attachments"

$credential = New-Object System.Management.Automation.PSCredential(
    $JIRA_USERNAME,
    (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
)

$headers = @{ "X-Atlassian-Token" = "no-check" }

# Zip results
if (-not (Test-Path $zipPath)) {
    Write-Output "Zipping results directory..."
    Compress-Archive -Path "$resultsDir\*" -DestinationPath $zipPath -Force
}

# ------------------------------------------------------------
# OPTION 1 — XRAY IMPORT (output.xml)
# ------------------------------------------------------------
try {
    Write-Output ">>> OPTION 1: Xray import (output.xml)"
    Invoke-RestMethod `
        -Uri $xrayUrl `
        -Method Post `
        -InFile $outputXml `
        -ContentType "application/xml" `
        -Credential $credential `
        -ErrorAction Stop

    Write-Output "OPTION 1 SUCCESS (Xray import)"
    exit 0
}
catch {
    Write-Warning "OPTION 1 FAILED"
    Write-Warning $_
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
        -Credential $credential `
        -ErrorAction Stop

    Write-Output "OPTION 2 SUCCESS (ZIP no proxy)"
    exit 0
}
catch {
    Write-Warning "OPTION 2 FAILED"
    Write-Warning $_
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
        -Credential $credential `
        -Proxy $PROXY `
        -ErrorAction Stop

    Write-Output "OPTION 3 SUCCESS (ZIP with proxy)"
    exit 0
}
catch {
    Write-Error "OPTION 3 FAILED — ALL METHODS FAILED"
    Write-Error $_
    exit 1
}