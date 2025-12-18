Write-Output "Zipping Robot Framework results..."

$resultsDir = Join-Path (Get-Location) "results"
$zipPath = Join-Path (Get-Location) "results.zip"

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path "$resultsDir\*" -DestinationPath $zipPath

if (!(Test-Path $zipPath)) {
    Write-Error "results.zip was not created"
    exit 1
}

Write-Output "Results successfully zipped: $zipPath"
Write-Output "Uploading results.zip to Jira..."

$jiraUrl = "https://slc-toolset.common.airbusds.corp/jira/rest/api/2/issue/$ISSUE_KEY/attachments"
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$JIRA_USERNAME:$JIRA_PASSWORD"))

$headers = @{
    "Authorization" = "Basic $auth"
    "X-Atlassian-Token" = "no-check"
}

try {
    Invoke-RestMethod `
        -Uri $jiraUrl `
        -Method Post `
        -Headers $headers `
        -InFile $zipPath `
        -ContentType "application/zip"

    Write-Output "✅ Results successfully uploaded to Jira issue $ISSUE_KEY"
}
catch {
    Write-Error "❌ Failed to upload results.zip to Jira"
    Write-Error $_
    exit 1
}