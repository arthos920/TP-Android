Write-Output "==============================="
Write-Output "START JIRA UPLOAD (FULL CASCADE)"
Write-Output "==============================="

$jiraIssueKey = $ISSUE_KEY
$resultsDir   = Join-Path $env:CI_PROJECT_DIR "results"
$resultsZip   = Join-Path $env:CI_PROJECT_DIR "results.zip"

if (!(Test-Path $resultsZip)) {
    Write-Error "results.zip NOT FOUND: $resultsZip"
    exit 1
}

# -----------------------------------------------------
# Helper: exit if success
# -----------------------------------------------------
function Exit-IfSuccess($ok, $label) {
    if ($ok) {
        Write-Output "$label SUCCESS → STOP CASCADE"
        exit 0
    }
}

# =====================================================
# OPTION 1 : XRAY IMPORT (ZIP)
# =====================================================
Write-Output ">>> OPTION 1 : XRAY import"

$opt1 = $false
try {
    $cmd = @"
"$CURL_PATH" -k -X POST `
-u "$JIRA_USERNAME:$JIRA_PASSWORD" `
-H "X-Atlassian-Token: no-check" `
-F "file=@$resultsZip" `
"$JIRA_URL_TEST_EXEC$jiraIssueKey"
"@
    Write-Output $cmd
    Invoke-Expression $cmd | Write-Output

    if ($LASTEXITCODE -eq 0) {
        $opt1 = $true
    }
}
catch {
    Write-Warning $_
}
Exit-IfSuccess $opt1 "OPTION 1 (XRAY)"

# =====================================================
# OPTION 2 : JIRA ATTACHMENT (results.zip)
# =====================================================
Write-Output ">>> OPTION 2 : JIRA attachment (results.zip)"

$opt2 = $false
try {
    $attachUrl = "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/attachments"

    Invoke-RestMethod `
        -Uri $attachUrl `
        -Method POST `
        -Headers @{ "X-Atlassian-Token" = "no-check" } `
        -InFile $resultsZip `
        -ContentType "application/zip" `
        -Credential (New-Object PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Proxy $PROXY `
        -ErrorAction Stop

    $opt2 = $true
}
catch {
    Write-Warning $_
}
Exit-IfSuccess $opt2 "OPTION 2 (ZIP ATTACHMENT)"

# =====================================================
# OPTION 3 : JIRA ATTACHMENT (HTML/XML files)
# =====================================================
Write-Output ">>> OPTION 3 : JIRA attachment (HTML/XML)"

$opt3 = $false
try {
    $files = @("report.html", "log.html", "output.xml")

    foreach ($f in $files) {
        $path = Join-Path $resultsDir $f
        if (Test-Path $path) {
            Write-Output "Uploading $f"
            Invoke-RestMethod `
                -Uri "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/attachments" `
                -Method POST `
                -Headers @{ "X-Atlassian-Token" = "no-check" } `
                -InFile $path `
                -ContentType "text/html" `
                -Credential (New-Object PSCredential(
                    $JIRA_USERNAME,
                    (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
                )) `
                -Proxy $PROXY `
                -ErrorAction Stop
        }
    }
    $opt3 = $true
}
catch {
    Write-Warning $_
}
Exit-IfSuccess $opt3 "OPTION 3 (HTML/XML ATTACHMENTS)"

# =====================================================
# OPTION 4 : JIRA COMMENT (ULTIMATE FALLBACK)
# =====================================================
Write-Output ">>> OPTION 4 : JIRA comment (fallback)"

$opt4 = $false
try {
    $commentText = @'
📎 Robot Framework results available

Pipeline:
__PIPELINE__

Artifacts:
__PIPELINE__/artifacts/browse/results/

Files:
- report.html
- log.html
- output.xml
- results.zip
'@

    $commentText = $commentText -replace '__PIPELINE__', $CI_PIPELINE_URL

    $commentBody = @{ body = $commentText } | ConvertTo-Json -Depth 5

    Invoke-RestMethod `
        -Uri "$JIRA_URL/rest/api/2/issue/$jiraIssueKey/comment" `
        -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $commentBody `
        -Credential (New-Object PSCredential(
            $JIRA_USERNAME,
            (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
        )) `
        -Proxy $PROXY `
        -ErrorAction Stop

    $opt4 = $true
}
catch {
    Write-Warning $_
}
Exit-IfSuccess $opt4 "OPTION 4 (COMMENT)"

# =====================================================
# ALL FAILED
# =====================================================
Write-Error "❌ ALL JIRA UPLOAD METHODS FAILED"
exit 1