# ==================================================================
# fetch_tests.ps1
# Récupère les tests d'une Test Execution JIRA, lance Robot Framework
# dessus, puis publie résultats + statut sur JIRA.
# ==================================================================

param(
    [Parameter(Mandatory=$true)][string] $ISSUE_KEY,
    [Parameter(Mandatory=$true)][string] $LAB,
    [Parameter(Mandatory=$true)][string] $URL,
    [Parameter(Mandatory=$true)][string] $EMAIL
)

# --- Config labo ---
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $scriptDir 'lab_config.json'

if (-not (Test-Path $configPath)) {
    Write-Error "Configuration file not found: $configPath"
    exit 1
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not ($config.PSObject.Properties.Name -contains $LAB)) {
    Write-Error "Lab '$LAB' not found in $configPath"
    exit 1
}
$labCfg           = $config.$LAB
$robotCampaignDir = $labCfg.robotCampaignDirectory
$curlPath         = $labCfg.curlPath
$robotPath        = $labCfg.robotPath
$listenerPath     = $labCfg.listenerPath

# --- JIRA / proxy (TODO: passer le password en secret CI) ---
$jiraUser    = ''
$jiraPass    = ''
$proxy       = ''
$jiraBaseUrl = ''

$outputFile = 'robot_arg.txt'
$resultsDir = Join-Path (Get-Location) 'results'
$zipPath    = Join-Path (Get-Location) 'results.zip'

$jiraHooks = @{
    'IVX'     = "$jiraBaseUrl/rest/cb-automation/latest/hooks/"
    'AMCXSOL' = "$jiraBaseUrl/rest/cb-automation/latest/hooks/"
}
$prefix = $ISSUE_KEY.Split('-')[0]
if (-not $jiraHooks.ContainsKey($prefix)) {
    Write-Error "Unrecognized ISSUE_KEY prefix: $prefix"
    exit 1
}
$hookUrl     = $jiraHooks[$prefix]
$testsApiUrl = "$jiraBaseUrl/rest/raven/1.0/api/testexec/$ISSUE_KEY/test"

# --- data.json (payload du hook JIRA) ---
@{
    issues = @($ISSUE_KEY)
    data   = @{ initiatorEmail = $EMAIL; robotReportURL = $URL }
} | ConvertTo-Json -Depth 5 -Compress | Out-File (Join-Path $scriptDir 'data.json') -Encoding utf8

# ==================================================================
# Récupération des IDs de tests depuis JIRA
# ==================================================================
function Get-JiraTests {
    if (-not (Test-Path $curlPath)) {
        throw "curl not found at $curlPath — required to query JIRA"
    }
    # cookie jar nécessaire pour conserver le JSESSIONID posé par le 307 JIRA
    $cookieFile   = Join-Path $env:TEMP 'jira_session_cookies.txt'
    $responseFile = Join-Path $env:TEMP 'jira_response.json'
    Remove-Item $cookieFile, $responseFile -Force -ErrorAction SilentlyContinue

    $cmd = @(
        '-k', '-sS', '-L',
        '-c', $cookieFile, '-b', $cookieFile,
        '-o', $responseFile,
        '-w', 'HTTP_CODE=%{http_code}',
        '-u', "${jiraUser}:${jiraPass}",
        '-H', 'Accept: application/json',
        '-X', 'GET',
        '--proxy', $proxy,
        $testsApiUrl
    )
    # Write-Host obligatoire dans une fonction à valeur de retour (Write-Output pollue la sortie)
    Write-Host ">>> curl GET $testsApiUrl"
    $httpInfo = & $curlPath @cmd
    Write-Host "curl exit=$LASTEXITCODE $httpInfo"

    if ($LASTEXITCODE -ne 0)            { throw "curl failed (exit $LASTEXITCODE, $httpInfo)" }
    if (-not (Test-Path $responseFile)) { throw "curl response file missing: $responseFile" }

    # Lecture binaire + strip BOM UTF-8 (PS 5.1 ne le strippe pas toujours)
    $bytes = [System.IO.File]::ReadAllBytes($responseFile)
    Remove-Item $responseFile -Force
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    [System.Text.Encoding]::UTF8.GetString($bytes)
}

try   { $rawResponse = (Get-JiraTests).Trim() }
catch { Write-Error "JIRA request failed: $_"; exit 1 }

if ([string]::IsNullOrWhiteSpace($rawResponse)) {
    Write-Error "Empty JSON response. Check URL and credentials."
    exit 1
}
Write-Host $rawResponse

try   { $decoded = $rawResponse | ConvertFrom-Json }
catch { Write-Error "Cannot parse JIRA response as JSON: $_"; exit 1 }

# JIRA peut renvoyer un tableau direct OU un objet { tests: [...] }
$tests = if ($decoded -is [System.Collections.IEnumerable]) { $decoded } else { $decoded.tests }

$filters = @()
foreach ($t in $tests) {
    if ($t.PSObject.Properties.Name -contains 'key') {
        $filters += "--include $($t.key)"
        Write-Host "Test key: $($t.key)"
    }
}

if ($filters.Count -eq 0) {
    Set-Content -Path $outputFile -Value ''
    Write-Error "No tests found for ISSUE_KEY $ISSUE_KEY. Arg file is empty."
    exit 1
}
(($filters -join "`r`n") + "`r`n") | Set-Content -Path $outputFile -Encoding utf8
Write-Host "=== $outputFile ==="
Get-Content $outputFile

# ==================================================================
# Exécution Robot Framework
# ==================================================================
if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }

$robotArgs = @(
    '-A', $outputFile,
    '--nostatusrc',
    '-L', 'info',
    '--outputdir', $resultsDir,
    '--output', 'output.xml',
    '--log', 'log.html',
    '--report', 'report.html',
    '--listener', $listenerPath,
    $robotCampaignDir
)
Write-Host ">>> robot @robotArgs"
& $robotPath @robotArgs
$robotExitCode = $LASTEXITCODE
Write-Host "Robot exit code: $robotExitCode"
if ($robotExitCode -ne 0) {
    Write-Error "Robot tests FAILED (code $robotExitCode)"
    exit $robotExitCode
}

# ==================================================================
# Compression des résultats
# ==================================================================
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$resultsDir\*" -DestinationPath $zipPath -Force
if (-not (Test-Path $zipPath)) {
    Write-Error "results.zip was not created"
    exit 1
}

# ==================================================================
# Publication sur JIRA
# ==================================================================
Write-Host "JIRA: base=$jiraBaseUrl user=$jiraUser issue=$ISSUE_KEY proxy=$proxy"

# Out-Host : on veut voir la sortie curl à l'écran mais sans la mélanger à la valeur de retour
function Invoke-JiraCurl {
    param([string]$Label, [string[]]$CurlArgs)
    Write-Host ">>> $Label"
    & $curlPath @CurlArgs | Out-Host
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok) { Write-Warning "$Label failed (exit $LASTEXITCODE)" }
    return $ok
}

# 1. Attacher le zip au ticket
$zipToJiraSuccess = Invoke-JiraCurl `
    -Label "Attach zip to $ISSUE_KEY" `
    -CurlArgs @(
        '-k','-v','-D-',
        '-u', "$jiraUser`:$jiraPass",
        '-X','POST',
        '-H','X-Atlassian-Token: nocheck',
        '-F', "file=@$zipPath",
        "$jiraBaseUrl/rest/api/2/issue/$ISSUE_KEY/attachments"
    )

# 2. Import XRAY du rapport Robot
$robotOutput = Join-Path $resultsDir 'output.xml'
$xrayImportSuccess = $false
if (Test-Path $robotOutput) {
    $xrayImportSuccess = Invoke-JiraCurl `
        -Label "XRAY import $robotOutput" `
        -CurlArgs @(
            '-k','-v',
            '-u', "$jiraUser`:$jiraPass",
            '-X','POST',
            '-F', "file=@$robotOutput",
            "$jiraBaseUrl/rest/raven/1.0/import/execution/robot?testExecKey=$ISSUE_KEY"
        )
}
else {
    Write-Warning "output.xml NOT FOUND: $robotOutput"
}

# 3. Envoi du statut PASS/FAIL via le hook CB-Automation (retry sur plusieurs proxys)
function Invoke-HookOnce {
    param([string]$Label, [string]$JsonBody, [string]$HookUrl, [string]$Proxy = $null)
    Write-Host "---- $Label ----"
    $curlArgs = @(
        '-k','-sS','-D','-','-o','NUL',
        '-u', "$jiraUser`:$jiraPass",
        '-X','POST',
        '-H','Content-Type: application/json',
        '--data-binary', $JsonBody,
        $HookUrl
    )
    if ($Proxy) { $curlArgs = @('--proxy', $Proxy) + $curlArgs }
    & $curlPath @curlArgs | Out-Host
    return ($LASTEXITCODE -eq 0)
}

$hookStatusSuccess = $false
try {
    $status    = if ($robotExitCode -eq 0) { 'PASS' } else { 'FAIL' }
    $reportUrl = "$env:CI_PIPELINE_URL/artifacts/browse/results/report.html"
    $jsonBody  = @{
        issues = @($ISSUE_KEY)
        data   = @{ status = $status; initiatorEmail = $EMAIL; robotReportUrl = $reportUrl }
    } | ConvertTo-Json -Depth 6 -Compress

    $proxies = @($env:HTTPS_PROXY, $env:HTTP_PROXY, $proxy,
                 '',
                 '') `
        | Where-Object { $_ -and $_.Trim() } `
        | Select-Object -Unique

    if (Invoke-HookOnce -Label "NO PROXY" -JsonBody $jsonBody -HookUrl $hookUrl) {
        $hookStatusSuccess = $true
    }
    else {
        foreach ($p in $proxies) {
            if (Invoke-HookOnce -Label "WITH PROXY $p" -JsonBody $jsonBody -HookUrl $hookUrl -Proxy $p) {
                $hookStatusSuccess = $true
                break
            }
        }
    }
}
catch { Write-Warning "Hook status FAILED: $_" }

if (-not ($zipToJiraSuccess -or $xrayImportSuccess -or $hookStatusSuccess)) {
    Write-Error "ALL JIRA UPLOAD METHODS FAILED"
    exit 1
}
exit 0
