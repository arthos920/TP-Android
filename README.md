#requires -Version 5.1

<#
Appel normal :
    Controle des acteurs avec retry toutes les 5 secondes.

Appel -AfterJob :
    Utilise dans after_script du meme job GitLab.
    Remet les tests a TODO uniquement si CI_JOB_STATUS vaut failed.

ISSUE_KEY doit etre la cle de la Test Execution concernee.

Le statut controle est celui de ce job.
Un echec dans un autre job execute ensuite n'est pas traite ici.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ISSUE_KEY,

    [Parameter(Mandatory = $true)]
    [string]$LAB,

    [Parameter(Mandatory = $true)]
    [string]$URL,

    [Parameter(Mandatory = $true)]
    [string]$EMAIL,

    [switch]$AfterJob
)

$ErrorActionPreference = 'Stop'

# Les codes de sortie des programmes sont controles explicitement.
$PSNativeCommandUseErrorActionPreference = $false


# ----------------------------------------------------------------------
# Verification du statut du job lors de l'appel depuis after_script
# ----------------------------------------------------------------------

if ($AfterJob) {
    $jobStatus = [string]$env:CI_JOB_STATUS

    if ([string]::IsNullOrWhiteSpace($jobStatus)) {
        Write-Error `
            'CI_JOB_STATUS is missing. Use -AfterJob from the GitLab after_script section.' `
            -ErrorAction Continue

        exit 1
    }

    if ($jobStatus -ne 'failed') {
        Write-Host "Job status is '$jobStatus': no Jira reset."
        exit 0
    }

    Write-Host 'GitLab job failed: reset its Test Execution to TODO.'
}


# ----------------------------------------------------------------------
# Configuration Jira
# Reprendre les valeurs de ton script Jira qui fonctionne
# ----------------------------------------------------------------------

$JIRA_URL = 'xxxxx'
$JIRA_USERNAME = 'xxxx'
$JIRA_PASSWORD = 'xxxx'

$curlPath = 'curl.exe'

$proxy = $env:HTTPS_PROXY

if ([string]::IsNullOrWhiteSpace($proxy)) {
    $proxy = $env:HTTP_PROXY
}

# Si ton script utilise un proxy explicite, renseigner sa valeur ici :
# $proxy = 'http://ton-proxy:port'

$jiraPageSize = 100


# ----------------------------------------------------------------------
# Requete Jira avec curl
# ----------------------------------------------------------------------

function Invoke-JiraRequest {
    param(
        [ValidateSet('GET', 'PUT')]
        [string]$Method,

        [string]$RequestUrl
    )

    $responseFile = Join-Path `
        $script:jiraTempDirectory `
        'response.json'

    Remove-Item `
        -LiteralPath $responseFile `
        -Force `
        -ErrorAction SilentlyContinue

    # Authentification, redirections, cookies et proxy.
    $curlArgs = @(
        '-k', '-sS', '-L',
        '-c', $script:jiraCookieFile,
        '-b', $script:jiraCookieFile,
        '-o', $responseFile,
        '-w', 'HTTP_CODE=%{http_code}',
        '-u', "${JIRA_USERNAME}:${JIRA_PASSWORD}",
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-X', $Method,
        '--connect-timeout', '30',
        '--max-time', '120'
    )

    if (-not [string]::IsNullOrWhiteSpace($proxy)) {
        $curlArgs += @('--proxy', $proxy)
    }

    $curlArgs += $RequestUrl

    $httpInfo = (& $curlPath @curlArgs) -join ''
    $curlExitCode = $LASTEXITCODE

    if ($curlExitCode -ne 0) {
        throw "curl failed: exit $curlExitCode; $Method $RequestUrl"
    }

    # Verifier egalement le statut HTTP.
    if ($httpInfo -notmatch 'HTTP_CODE=(\d{3})\s*$') {
        throw "Missing HTTP status: $Method $RequestUrl"
    }

    $httpStatus = [int]$Matches[1]

    if ($httpStatus -lt 200 -or $httpStatus -ge 300) {
        throw "Jira HTTP $httpStatus : $Method $RequestUrl"
    }

    if (-not (Test-Path -LiteralPath $responseFile)) {
        throw 'curl response file missing.'
    }

    # Lecture UTF-8 et retrait du BOM.
    $bytes = [System.IO.File]::ReadAllBytes($responseFile)

    if (
        $bytes.Length -ge 3 -and
        $bytes[0] -eq 0xEF -and
        $bytes[1] -eq 0xBB -and
        $bytes[2] -eq 0xBF
    ) {
        return [System.Text.Encoding]::UTF8.GetString(
            $bytes,
            3,
            $bytes.Length - 3
        )
    }

    return [System.Text.Encoding]::UTF8.GetString($bytes)
}


# ----------------------------------------------------------------------
# Recuperation de tous les tests de la Test Execution
# ----------------------------------------------------------------------

function Get-JiraTests {
    $testKeys = New-Object 'System.Collections.Generic.List[string]'
    $seenKeys = @{}

    $executionKey = [uri]::EscapeDataString($ISSUE_KEY)
    $page = 1

    while ($true) {
        $testsApiUrl = "$script:jiraRoot/rest/raven/1.0/api/testexec/$executionKey/test?page=$page&limit=$jiraPageSize"

        $rawResponse = (
            Invoke-JiraRequest `
                -Method GET `
                -RequestUrl $testsApiUrl
        ).Trim()

        if ([string]::IsNullOrWhiteSpace($rawResponse)) {
            throw "Empty Jira response, page $page."
        }

        $decoded = ConvertFrom-Json `
            -InputObject $rawResponse `
            -ErrorAction Stop

        # Tableau direct ou objet contenant une propriete tests.
        if ($rawResponse.StartsWith('[')) {
            $tests = @(
                $decoded |
                    Where-Object { $null -ne $_ }
            )
        }
        elseif (
            $null -ne $decoded -and
            $decoded.PSObject.Properties['tests']
        ) {
            $tests = @(
                $decoded.tests |
                    Where-Object { $null -ne $_ }
            )
        }
        else {
            throw "Unexpected Jira response format, page $page."
        }

        if ($tests.Count -eq 0) {
            break
        }

        $newKeys = 0

        foreach ($test in $tests) {
            $testKey = [string]$test.key

            if ([string]::IsNullOrWhiteSpace($testKey)) {
                throw "Test without a key, page $page. No updates performed."
            }

            if (-not $seenKeys.ContainsKey($testKey)) {
                $seenKeys[$testKey] = $true
                $testKeys.Add($testKey)
                $newKeys++
            }
        }

        Write-Host "Jira page $page : $($tests.Count) tests; $($testKeys.Count) unique keys."

        if ($newKeys -eq 0) {
            throw 'Jira returned a repeated page. Check pagination; no updates performed.'
        }

        # Continuer jusqu'a une page vide.
        $page++
    }

    return $testKeys.ToArray()
}


# ----------------------------------------------------------------------
# Passage a TODO des Test Runs de cette Test Execution
# ----------------------------------------------------------------------

function Set-JiraTestsTodo {
    $testKeys = @(Get-JiraTests)

    if ($testKeys.Count -eq 0) {
        throw "No tests found for Test Execution $ISSUE_KEY."
    }

    Write-Host "Test Execution $ISSUE_KEY : $($testKeys.Count) tests found."

    # Identifier les Test Runs avant de modifier leurs statuts.
    $runs = New-Object 'System.Collections.Generic.List[object]'

    $executionKey = [uri]::EscapeDataString($ISSUE_KEY)

    foreach ($testKey in $testKeys) {
        $encodedTestKey = [uri]::EscapeDataString($testKey)

        $runUrl = "$script:jiraRoot/rest/raven/1.0/api/testrun?testExecIssueKey=$executionKey&testIssueKey=$encodedTestKey"

        $rawRun = Invoke-JiraRequest `
            -Method GET `
            -RequestUrl $runUrl

        $run = ConvertFrom-Json `
            -InputObject $rawRun `
            -ErrorAction Stop

        # Verifier que le Test Run appartient au bon test
        # et a la bonne Test Execution.
        if (
            $null -eq $run -or
            [string]$run.id -notmatch '^[1-9][0-9]*$' -or
            $run.testKey -ne $testKey -or
            $run.testExecKey -ne $ISSUE_KEY
        ) {
            throw "Invalid Test Run for $ISSUE_KEY / $testKey. No updates performed."
        }

        $runs.Add($run)
    }

    $updated = 0
    $alreadyTodo = 0

    $failedKeys = New-Object 'System.Collections.Generic.List[string]'

    foreach ($run in $runs) {
        try {
            if ([string]$run.status -eq 'TODO') {
                $alreadyTodo++

                Write-Host "$($run.testKey) : already TODO."

                continue
            }

            $statusUrl = "$script:jiraRoot/rest/raven/1.0/api/testrun/$($run.id)/status"

            $null = Invoke-JiraRequest `
                -Method PUT `
                -RequestUrl "${statusUrl}?status=TODO"

            # Relire le statut pour verifier la modification.
            $actualStatus = (
                Invoke-JiraRequest `
                    -Method GET `
                    -RequestUrl $statusUrl
            ).Trim().Trim('"')

            if ($actualStatus -ne 'TODO') {
                throw "Status after update is '$actualStatus', expected TODO."
            }

            $updated++

            Write-Host "$($run.testKey) : $($run.status) -> TODO (run $($run.id))."
        }
        catch {
            $failedKeys.Add([string]$run.testKey)

            Write-Warning "$($run.testKey) : $($_.Exception.Message)"
        }
    }

    Write-Host "Summary $ISSUE_KEY : total=$($runs.Count); updated=$updated; already TODO=$alreadyTodo; errors=$($failedKeys.Count)."

    if ($failedKeys.Count -gt 0) {
        throw "TODO reset incomplete. Failed tests: $($failedKeys -join ', ')"
    }
}


# ----------------------------------------------------------------------
# Traitement Jira apres l'echec du job
# ----------------------------------------------------------------------

if ($AfterJob) {
    $script:jiraTempDirectory = $null
    $resetExitCode = 0

    try {
        if (
            $JIRA_URL -notmatch '^https?://' -or
            [string]::IsNullOrWhiteSpace($JIRA_USERNAME) -or
            $JIRA_USERNAME -eq 'xxxx' -or
            [string]::IsNullOrWhiteSpace($JIRA_PASSWORD) -or
            $JIRA_PASSWORD -eq 'xxxx'
        ) {
            throw 'Configure JIRA_URL, JIRA_USERNAME and JIRA_PASSWORD in this script.'
        }

        $curlPath = (
            Get-Command `
                $curlPath `
                -CommandType Application `
                -ErrorAction Stop
        ).Source

        $script:jiraRoot = $JIRA_URL.TrimEnd('/')

        $script:jiraTempDirectory = Join-Path `
            ([System.IO.Path]::GetTempPath()) `
            ("jira_todo_" + [guid]::NewGuid().ToString('N'))

        $null = New-Item `
            -ItemType Directory `
            -Path $script:jiraTempDirectory

        $script:jiraCookieFile = Join-Path `
            $script:jiraTempDirectory `
            'jira_session_cookies.txt'

        Write-Host "Reset Jira tests to TODO: execution=$ISSUE_KEY; pipeline=$URL"

        Set-JiraTestsTodo
    }
    catch {
        Write-Error `
            "Jira TODO reset failed: $($_.Exception.Message)" `
            -ErrorAction Continue

        $resetExitCode = 1
    }
    finally {
        if ($script:jiraTempDirectory) {
            Remove-Item `
                -LiteralPath $script:jiraTempDirectory `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }

    exit $resetExitCode
}


# ----------------------------------------------------------------------
# Controle des acteurs
# ----------------------------------------------------------------------

Write-Output '===== CHECK ACTORS LAUNCH ====='
Write-Output "LAB       : $LAB"
Write-Output "ISSUE_KEY : $ISSUE_KEY"
Write-Output "PIPELINE  : $URL"
Write-Output "EMAIL     : $EMAIL"

try {
    # Repertoire du script.
    $scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

    Write-Output "Script directory: $scriptDirectory"

    # Chargement de lab_config.json.
    $configFilePath = Join-Path `
        -Path $scriptDirectory `
        -ChildPath 'lab_config.json'

    if (-not (Test-Path -LiteralPath $configFilePath)) {
        throw "Configuration file not found: $configFilePath"
    }

    $config = Get-Content `
        -LiteralPath $configFilePath `
        -Raw |
        ConvertFrom-Json

    if (-not ($config.PSObject.Properties.Name -contains $LAB)) {
        throw "Configuration for lab '$LAB' not found in lab_config.json"
    }

    $labConfig = $config.$LAB

    $robotCampaignDirectory = $labConfig.robotCampaignDirectory
    $checkActorFile = $labConfig.checkActorFile
    $robotPath = $labConfig.robotPath
    $listenerPath = $labConfig.listenerPath
    $pythonPath = $labConfig.pythonPath

    Write-Output "Robot path               : $robotPath"
    Write-Output "Robot campaign directory : $robotCampaignDirectory"
    Write-Output "Check actor file         : $checkActorFile"

    if (-not (Test-Path -LiteralPath $robotCampaignDirectory)) {
        throw "Robot campaign directory not found: $robotCampaignDirectory"
    }

    $workspace = Get-Location

    # Dossier des resultats Robot.
    $RESULTS_DIR = Join-Path $workspace 'results'

    if (-not (Test-Path -LiteralPath $RESULTS_DIR)) {
        $null = New-Item `
            -ItemType Directory `
            -Path $RESULTS_DIR
    }

    Write-Output "Robot results directory: $RESULTS_DIR"
    Write-Output "gitlab workspace: $workspace"

    Push-Location $robotCampaignDirectory

    try {
        $outputFile = Join-Path $RESULTS_DIR 'check_actors.xml'
        $logFile = Join-Path $RESULTS_DIR 'log_actors.html'
        $reportFile = Join-Path $RESULTS_DIR 'report_actors.html'

        $robotExitCode = 1

        while ($robotExitCode -ne 0) {
            Write-Output 'Launching Robot Framework...'

            & $robotPath `
                -L debug `
                --outputdir $RESULTS_DIR `
                --output check_actors.xml `
                --log log_actors.html `
                --report report_actors.html `
                $checkActorFile

            $robotExitCode = $LASTEXITCODE

            Write-Output "Robot exit code: $robotExitCode"

            if ($robotExitCode -ne 0) {
                Write-Output 'Robot failed. Retrying in 5 seconds...'

                Start-Sleep -Seconds 5
            }
        }
    }
    finally {
        Pop-Location
    }

    Write-Output 'Robot tests PASSED'

    exit 0
}
catch {
    Write-Error `
        "Check actors failed: $($_.Exception.Message)" `
        -ErrorAction Continue

    exit 1
}