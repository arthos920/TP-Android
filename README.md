Write-Output "==============================="
Write-Output "START JIRA UPLOAD (FULL CASCADE)"
Write-Output "==============================="

$jiraIssueKey = $ISSUE_KEY
$resultsDir  = Join-Path $env:CI_PROJECT_DIR "results"
$resultsZip  = Join-Path $env:CI_PROJECT_DIR "results.zip"
$robotXml    = Join-Path $resultsDir "output.xml"

function Exit-IfSuccess($ok, $label) {
    if ($ok) {
        Write-Output "$label SUCCESS → STOP CASCADE"
        exit 0
    }
}

function New-JiraCredential {
    return New-Object PSCredential(
        $JIRA_USERNAME,
        (ConvertTo-SecureString $JIRA_PASSWORD -AsPlainText -Force)
    )
}

# =====================================================
# OPTION 1 : XRAY IMPORT (Robot Framework XML) – OFFICIEL
# =====================================================
Write-Output ">>> OPTION 1 : XRAY Robot Framework import"

$opt1 = $false
if (Test-Path $robotXml) {
    try {
        $xrayUrl = "$JIRA_BASE_URL/rest/raven/1.0/import/execution/robot?testExecKey=$jiraIssueKey"

        & "$CURL_PATH" `
            -k `
            -u "$JIRA_USERNAME:$JIRA_PASSWORD" `
            -H "X-Atlassian-Token: no-check" `
            -F "file=@$robotXml" `
            "$xrayUrl"

        if ($LASTEXITCODE -eq 0) {
            $opt1 = $true
        }
    }
    catch {
        Write-Warning $_
    }
} else {
    Write-Warning "output.xml NOT FOUND → skip XRAY"
}
Exit-IfSuccess $opt1 "OPTION 1 (XRAY)"

# =====================================================
# OPTION 2 : JIRA ATTACHMENT (results.zip)
# =====================================================
Write-Output ">>> OPTION 2 : JIRA attachment (results.zip)"

$opt2 = $false
if (Test-Path $resultsZip) {
    try {
        Invoke-RestMethod `
            -Uri "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/attachments" `
            -Method POST `
            -Headers @{ "X-Atlassian-Token" = "no-check" } `
            -InFile $resultsZip `
            -ContentType "application/zip" `
            -Credential (New-JiraCredential) `
            -Proxy $PROXY `
            -ErrorAction Stop

        $opt2 = $true
    }
    catch {
        Write-Warning $_
    }
}
Exit-IfSuccess $opt2 "OPTION 2 (ZIP ATTACHMENT)"

# =====================================================
# OPTION 3 : JIRA ATTACHMENT (HTML / XML)
# =====================================================
Write-Output ">>> OPTION 3 : JIRA attachment (HTML/XML)"

$opt3 = $false
try {
    $files = @(
        @{ Name = "report.html"; Type = "text/html" },
        @{ Name = "log.html";    Type = "text/html" },
        @{ Name = "output.xml"; Type = "application/xml" }
    )

    foreach ($f in $files) {
        $path = Join-Path $resultsDir $f.Name
        if (Test-Path $path) {
            Write-Output "Uploading $($f.Name)"
            Invoke-RestMethod `
                -Uri "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/attachments" `
                -Method POST `
                -Headers @{ "X-Atlassian-Token" = "no-check" } `
                -InFile $path `
                -ContentType $f.Type `
                -Credential (New-JiraCredential) `
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
    $commentBody = @{
        body = @"
📎 Robot Framework results available

Pipeline:
$CI_PIPELINE_URL

Artifacts:
$CI_PIPELINE_URL/artifacts/browse/results/

Files:
- report.html
- log.html
- output.xml
- results.zip
"@
    } | ConvertTo-Json -Depth 5

    Invoke-RestMethod `
        -Uri "$JIRA_BASE_URL/rest/api/2/issue/$jiraIssueKey/comment" `
        -Method POST `
        -Headers @{ "Content-Type" = "application/json" } `
        -Body $commentBody `
        -Credential (New-JiraCredential) `
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
Write-Error "ALL JIRA UPLOAD METHODS FAILED"
exit 1