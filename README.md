Write-Output "===== JIRA CONFIG CHECK ====="
Write-Output "JIRA_BASE_URL      = '$JIRA_BASE_URL'"
Write-Output "JIRA_USERNAME      = '$JIRA_USERNAME'"
Write-Output "ISSUE_KEY          = '$ISSUE_KEY'"
Write-Output "PROXY              = '$PROXY'"
Write-Output "CURL_PATH          = '$CURL_PATH'"
Write-Output "============================="

if ([string]::IsNullOrWhiteSpace($JIRA_BASE_URL)) {
    Write-Error "JIRA_BASE_URL IS EMPTY"
    exit 1
}

if ($JIRA_BASE_URL -notmatch '^https?://') {
    Write-Error "JIRA_BASE_URL INVALID (must start with http/https)"
    exit 1
}