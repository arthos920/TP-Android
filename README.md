# =====================================================
# OPTION 5 : JIRA ATTACHMENT (CURL – Jenkins proven)
# =====================================================
Write-Output ">>> OPTION 5 : JIRA attachment (curl Jenkins style)"

$opt5 = $false
try {
    $attachUrl = "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/attachments"

    Write-Output "Attach URL = $attachUrl"
    Write-Output "File       = $resultsZip"

    if (!(Test-Path $resultsZip)) {
        throw "results.zip not found"
    }

    $cmd = @(
        "`"$CURL_PATH`"",
        "-k",
        "-v",
        "-D", "-",
        "-u", "`"$JIRA_USERNAME`:$JIRA_PASSWORD`"",
        "-X", "POST",
        "-H", "`"X-Atlassian-Token: nocheck`"",
        "-F", "`"file=@$resultsZip`"",
        "`"$attachUrl`""
    ) -join " "

    Write-Output "Executing:"
    Write-Output $cmd

    Invoke-Expression $cmd

    if ($LASTEXITCODE -eq 0) {
        $opt5 = $true
    }
}
catch {
    Write-Warning "OPTION 5 FAILED"
    Write-Warning $_
}

Exit-IfSuccess $opt5 "OPTION 5 (CURL JENKINS ATTACHMENT)"