# =====================================================
# OPTION A : XRAY OFFICIAL ROBOT FRAMEWORK IMPORT
# (Equivalent Jenkins - THIS updates Jira status)
# =====================================================
Write-Output ">>> OPTION A : XRAY Robot Framework import (OFFICIAL)"

$optA = $false

try {
    $robotOutput = Join-Path $resultsDir "output.xml"

    if (!(Test-Path $robotOutput)) {
        throw "output.xml NOT FOUND: $robotOutput"
    }

    $xrayUrl = "$JIRA_BASE_URL/rest/raven/1.0/import/execution/robot?testExecKey=$jiraIssueKey"

    Write-Output "XRAY URL : $xrayUrl"
    Write-Output "Robot file : $robotOutput"

    $curlArgs = @(
        "-k"
        "-v"
        "-u", "$JIRA_USERNAME:$JIRA_PASSWORD"
        "-X", "POST"
        "-F", "file=@$robotOutput"
        $xrayUrl
    )

    Write-Output "Executing curl (XRAY import):"
    $curlArgs | ForEach-Object { Write-Output "  $_" }

    & "$CURL_PATH" @curlArgs

    if ($LASTEXITCODE -eq 0) {
        Write-Output "OPTION A SUCCESS → XRAY import completed"
        $optA = $true
    }
    else {
        Write-Warning "XRAY import failed (exit code $LASTEXITCODE)"
    }
}
catch {
    Write-Warning "OPTION A FAILED"
    Write-Warning $_
}

Exit-IfSuccess $optA "OPTION A (XRAY OFFICIAL)"