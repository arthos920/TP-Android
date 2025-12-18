Write-Output "Uploading results.zip to Jira..."

$jiraIssueKey = $ISSUE_KEY
$zipPath = Join-Path (Get-Location) "results.zip"

if (!(Test-Path $zipPath)) {
    Write-Error "results.zip not found at $zipPath"
    exit 1
}

$jiraUrl = "https://slc-toolset.common.airbusds.corp/jira/rest/api/2/issue/$jiraIssueKey/attachments"

# Création du credential SANS encodage manuel
$securePassword = ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential ($JIRA_USERNAME, $securePassword)

try {
    Invoke-RestMethod `
        -Uri $jiraUrl `
        -Method Post `
        -InFile $zipPath `
        -ContentType "application/zip" `
        -Headers @{ "X-Atlassian-Token" = "no-check" } `
        -Credential $credential `
        -Proxy $PROXY

    Write-Output "results.zip successfully uploaded to Jira issue $jiraIssueKey"
}
catch {
    Write-Error "Failed to upload results.zip to Jira"
    Write-Error $_
    exit 1
}