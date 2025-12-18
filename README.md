# ------------------------------------------------------------
# Robot exit code
# ------------------------------------------------------------
$robotExitCode = $LASTEXITCODE
Write-Output "Robot exit code: $robotExitCode"

if ($robotExitCode -ne 0) {
    Write-Error "Robot tests FAILED"
}

# ------------------------------------------------------------
# Zip Robot Framework results
# ------------------------------------------------------------
Write-Output "Zipping Robot Framework results..."

$Workspace  = Get-Location
$ResultsDir = Join-Path $Workspace "results"
$ZipPath    = Join-Path $Workspace "results.zip"

if (!(Test-Path $ResultsDir)) {
    Write-Error "Results directory not found: $ResultsDir"
    exit 1
}

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive -Path "$ResultsDir\*" -DestinationPath $ZipPath

Write-Output "Results successfully zipped: $ZipPath"

# ------------------------------------------------------------
# Upload ZIP to Jira (attachments)
# ------------------------------------------------------------
Write-Output "Uploading results.zip to Jira..."

$JiraBaseUrl = "https://slc-toolset.common.airbusds.corp"
$IssueKey    = $ISSUE_KEY
$UploadUrl   = "$JiraBaseUrl/jira/rest/api/2/issue/$IssueKey/attachments"

$Headers = @{
    "X-Atlassian-Token" = "no-check"
}

try {
    Invoke-RestMethod `
        -Uri $UploadUrl `
        -Method Post `
        -Headers $Headers `
        -Credential (New-Object System.Management.Automation.PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Form @{ file = Get-Item $ZipPath }

    Write-Output "results.zip successfully attached to Jira issue $IssueKey"
}
catch {
    Write-Error "Failed to upload results.zip to Jira: $_"
    exit 1
}

# ------------------------------------------------------------
# Propagate Robot status to GitLab
# ------------------------------------------------------------
if ($robotExitCode -ne 0) {
    exit $robotExitCode
}

Write-Output "fetch_tests.ps1 finished successfully"
exit 0