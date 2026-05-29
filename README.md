# Out-Host : on veut voir la sortie curl a l'ecran mais sans la melanger a la valeur de retour
function Invoke-JiraCurl {
    param([string]$Label, [string[]]$CurlArgs)
    Write-Host ">>> $Label"
    & $curlPath @CurlArgs | Out-Host
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok) { Write-Warning "$Label failed (exit $LASTEXITCODE)" }
    return $ok
}

# Supprime tous les attachments existants d'une issue (GET la liste puis DELETE chacun)
function Remove-JiraAttachments {
    param([string]$IssueKey)

    $cookieFile   = Join-Path $env:TEMP 'jira_session_cookies.txt'
    $responseFile = Join-Path $env:TEMP 'jira_attachments.json'
    Remove-Item $cookieFile, $responseFile -Force -ErrorAction SilentlyContinue

    # 1. Recuperer la liste des attachments de l'issue
    $getCmd = @(
        '-k', '-sS', '-L',
        '-c', $cookieFile, '-b', $cookieFile,
        '-o', $responseFile,
        '-w', 'HTTP_CODE=%{http_code}',
        '-u', "${jiraUser}:${jiraPass}",
        '-H', 'Accept: application/json',
        '-X', 'GET',
        '--proxy', $proxy,
        "$jiraBaseUrl/rest/api/2/issue/${IssueKey}?fields=attachment"
    )
    Write-Host ">>> GET attachments de $IssueKey"
    $info = & $getCmd[0]; $info = & $curlPath @getCmd
    Write-Host "curl exit=$LASTEXITCODE $info"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $responseFile)) {
        Write-Warning "Impossible de recuperer les attachments de $IssueKey - on continue"
        return
    }

    # Lecture BOM-safe + parse
    $bytes = [System.IO.File]::ReadAllBytes($responseFile)
    Remove-Item $responseFile -Force
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $json = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        $json = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    try   { $attachments = ($json | ConvertFrom-Json).fields.attachment }
    catch { Write-Warning "Parse JSON attachments impossible - on continue"; return }

    if (-not $attachments -or @($attachments).Count -eq 0) {
        Write-Host "Aucun attachment a supprimer sur $IssueKey"
        return
    }

    # 2. Supprimer chaque attachment (DELETE = X-Atlassian-Token: nocheck obligatoire)
    foreach ($att in $attachments) {
        Write-Host ">>> DELETE attachment id=$($att.id) ($($att.filename))"
        $delCmd = @(
            '-k', '-sS', '-L',
            '-c', $cookieFile, '-b', $cookieFile,
            '-u', "${jiraUser}:${jiraPass}",
            '-H', 'X-Atlassian-Token: nocheck',
            '-X', 'DELETE',
            '--proxy', $proxy,
            "$jiraBaseUrl/rest/api/2/attachment/$($att.id)"
        )
        & $curlPath @delCmd | Out-Host
        if ($LASTEXITCODE -ne 0) { Write-Warning "Echec DELETE attachment $($att.id) (exit $LASTEXITCODE)" }
    }
}

# 0. Supprimer les attachments existants de la Test Execution (repartir propre)
Remove-JiraAttachments -IssueKey $ISSUE_KEY

# 1. Attacher le zip au ticket
