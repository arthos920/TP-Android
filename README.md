# =====================================================
# OPTION 6 : CB-AUTOMATION HOOK (PASS / FAIL)
# =====================================================
Write-Output ">>> OPTION 6 : Jira PASS / FAIL status (cb-automation hook)"

$opt6 = $false

try {
    # --- Déterminer le status depuis Robot exit code ---
    # Priorité: $robotExitCode (variable déjà dans ton script), sinon env ROBOT_EXIT_CODE
    $exitCode = $null
    if (Get-Variable -Name robotExitCode -Scope Script -ErrorAction SilentlyContinue) {
        $exitCode = [int]$robotExitCode
    } elseif ($env:ROBOT_EXIT_CODE) {
        $exitCode = [int]$env:ROBOT_EXIT_CODE
    } else {
        # fallback si tu n'as rien: considère PASS (à adapter si besoin)
        $exitCode = 0
    }

    $testStatus = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

    Write-Output "Robot exit code : $exitCode"
    Write-Output "Computed status : $testStatus"

    # --- Construire le payload JSON (sans here-string) ---
    $reportUrl = "$env:CI_PIPELINE_URL/artifacts/browse/results/report.html"

    $payload = [ordered]@{
        issues = @($jiraIssueKey)
        data   = [ordered]@{
            status        = $testStatus
            initiatorEmail = $env:EMAIL
            robotReportUrl = $reportUrl
        }
    }

    $jsonBody = $payload | ConvertTo-Json -Depth 6 -Compress
    Write-Output "JSON payload:"
    Write-Output $jsonBody

    # --- URL du hook (à garder EXACTEMENT comme dans ton Jenkins) ---
    # Exemple attendu: https://.../jira/rest/cb-automation/latest/hooks/<hookId>
    $hookUrl = "$JIRA_BASE_URL/rest/cb-automation/latest/hooks/$JIRA_HOOK_ID"
    Write-Output "Hook URL: $hookUrl"

    if ([string]::IsNullOrWhiteSpace($JIRA_HOOK_ID)) {
        throw "JIRA_HOOK_ID is empty. Set it (env var / config) to the hook id used in Jenkins."
    }

    # --- Helpers : exécuter curl proprement ---
    function Invoke-CurlOnce {
        param(
            [string]$Label,
            [string]$ProxyUrl = $null
        )

        Write-Output "----"
        Write-Output "OPTION 6 TRY: $Label"
        if ($ProxyUrl) { Write-Output "Proxy: $ProxyUrl" } else { Write-Output "Proxy: (none)" }

        $basicAuth = ("{0}:{1}" -f $JIRA_USERNAME, $JIRA_PASSWORD)

        # Note: -sS => silencieux mais affiche erreurs ; -D - => dump headers ; -o NUL => pas de body
        $curlArgs = @(
            "-k",
            "-sS",
            "-D", "-",
            "-o", "NUL",
            "-u", $basicAuth,
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "--data-binary", $jsonBody,
            $hookUrl
        )

        # Proxy : on essaye d'abord sans, puis avec
        if ($ProxyUrl) {
            $curlArgs = @("--proxy", $ProxyUrl) + $curlArgs
        }

        Write-Output "Executing curl:"
        $curlArgs | ForEach-Object { Write-Output "  $_" }

        $out = & $CURL_PATH @curlArgs 2>&1
        $out | ForEach-Object { Write-Output $_ }

        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        return $false
    }

    # --- Liste des proxies à tester (unique, non vides) ---
    $proxyCandidates = @()
    $proxyCandidates += $null                             # no proxy
    $proxyCandidates += $env:HTTPS_PROXY
    $proxyCandidates += $env:HTTP_PROXY
    $proxyCandidates += $PROXY
    $proxyCandidates += ""
    $proxyCandidates += ""

    $proxyCandidates =
        $proxyCandidates |
        Where-Object { $_ -ne $null -and $_.ToString().Trim() -ne "" } |
        Select-Object -Unique

    # 1) Essai SANS proxy d'abord
    if (Invoke-CurlOnce -Label "NO PROXY" -ProxyUrl $null) {
        Write-Output "OPTION 6 SUCCESS (no proxy) -> Status sent: $testStatus"
        $opt6 = $true
    }
    else {
        # 2) Essais AVEC proxies
        foreach ($p in $proxyCandidates) {
            if (Invoke-CurlOnce -Label "WITH PROXY" -ProxyUrl $p) {
                Write-Output "OPTION 6 SUCCESS (proxy=$p) -> Status sent: $testStatus"
                $opt6 = $true
                break
            }
        }
    }
}
catch {
    Write-Warning "OPTION 6 FAILED"
    Write-Warning $_
}

Exit-IfSuccess $opt6 "OPTION 6 (PASS/FAIL)"