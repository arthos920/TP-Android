# =====================================================
# OPTION 5 : JIRA ATTACHMENT (curl Jenkins style - FIXED)
# =====================================================
Write-Output ">>> OPTION 5 : JIRA attachment (curl Jenkins style)"

$opt5 = $false

try {
    $attachUrl = "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/attachments"

    Write-Output "Attach URL : $attachUrl"
    Write-Output "File       : $resultsZip"
    Write-Output "Curl path  : $CURL_PATH"

    if (!(Test-Path $resultsZip)) {
        throw "results.zip not found"
    }

    $curlArgs = @(
        "-k",
        "-v",
        "-D", "-",
        "-u", "$JIRA_USERNAME`:$JIRA_PASSWORD",
        "-X", "POST",
        "-H", "X-Atlassian-Token: nocheck",
        "-F", "file=@$resultsZip",
        $attachUrl
    )

    Write-Output "Executing curl with arguments:"
    $curlArgs | ForEach-Object { Write-Output "  $_" }

    & "$CURL_PATH" @curlArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION 5 SUCCESS"
        $opt5 = $true
    }
    else {
        Write-Warning "curl exited with code $LASTEXITCODE"
    }
}
catch {
    Write-Warning "OPTION 5 FAILED"
    Write-Warning $_
}

Exit-IfSuccess $opt5 "OPTION 5 (CURL JENKINS ATTACHMENT)"