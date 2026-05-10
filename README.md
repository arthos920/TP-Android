# ==================================================================
# fetch_tests.ps1
# Récupération des IDs de tests JIRA + exécution Robot Framework
# + publication sur JIRA (attachment, XRAY import, hook CB-Automation)
# ==================================================================

# ===========================
# 1  Paramètres d'appel
# ===========================
param(
    [Parameter(Mandatory=$true)][string] $ISSUE_KEY,
    [Parameter(Mandatory=$true)][string] $LAB,
    [Parameter(Mandatory=$true)][string] $URL,
    [Parameter(Mandatory=$true)][string] $EMAIL
)

# ===========================
# 2  Chargement de la configuration du labo
# ===========================
$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath  = Join-Path $scriptDir 'lab_config.json'

if (-not (Test-Path $configPath)) {
    Write-Error "Impossible de trouver le fichier de configuration : $configPath"
    exit 1
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json

if (-not ($config.PSObject.Properties.Name -contains $LAB)) {
    Write-Error "Configuration for lab '$LAB' not found in $configPath"
    exit 1
}
$labCfg = $config.$LAB

# Extraction des chemins / paramètres spécifiques au labo
$robotCampaignDir  = $labCfg.robotCampaignDirectory
$runnerTag         = $labCfg.runnerTag
$checkActorFile    = $labCfg.checkActorFile
$curlPath          = $labCfg.curlPath           # ex : "C:\Program Files\curl\curl.exe"
$robotPath         = $labCfg.robotPath          # ex : "C:\Python\Scripts\robot.exe"
$listenerPath      = $labCfg.listenerPath
$pythonPath        = $labCfg.pythonPath

# ===========================
# 3  Paramètres JIRA / Proxy
# ===========================
$jiraUser     = ''
$jiraPass     = ''    # <- à sécuriser dans un secret CI
$proxy        = ''

$logFile      = 'log.html'
$outputFile   = 'robot_arg.txt'           # fichier contenant les filtres --include
$resultsDir   = Join-Path (Get-Location) 'results'
$zipPath      = Join-Path (Get-Location) 'results.zip'

$jiraBaseUrl  = ''
$jiraTestExec = ""


# ===========================
# 4  Création du fichier 'data.json' (hook JIRA)
# ===========================
$jsonFile = Join-Path $scriptDir 'data.json'
$jsonContent = @{
    issues = @($ISSUE_KEY)
    data   = @{
        initiatorEmail = $EMAIL
        robotReportURL = $URL
    }
} | ConvertTo-Json -Depth 5 -Compress
$jsonContent | Out-File -FilePath $jsonFile -Encoding utf8

# ===========================
# 5  Récupération des ID de tests JIRA
# ===========================
# 5.1 - Vérifie que le pré-fixe du issue-key possède un hook défini
$prefix = $ISSUE_KEY.Split('-')[0]
if (-not $jiraHooks.ContainsKey($prefix)) {
    Write-Error "Unrecognized ISSUE_KEY prefix: $prefix"
    exit 1
}
$hookUrl = $jiraHooks[$prefix]

# 5.2 - Construction de l'URL de l'API Test-Execution
$testsApiUrl = "${jiraTestExec}${ISSUE_KEY}/test"

# 5.3 - Fonction d'accès HTTP (cURL ou Invoke-RestMethod)
function Get-HttpResponse {
    # Si le binaire curl existe on l'utilise - c'est le plus simple pour les options proxy / -k
    if (Test-Path $curlPath) {
        $cmd = @(
            "-k",                                # ignorer la validation du certificat
            "-sS",                               # silence la barre de progression mais garde les erreurs
            "-L",                                # suit les redirects (JIRA renvoie un 307 pour poser le JSESSIONID)
            "-b", "",                            # active le cookie engine (sinon le cookie de session n'est pas reposté)
            "-u", "${jiraUser}:${jiraPass}",
            "-H", "Accept: application/json",
            "-X", "GET",
            "--proxy", $proxy,
            $testsApiUrl
        )
        Write-Output ">>> Executing curl : $curlPath $($cmd -join ' ')"
        $response = & $curlPath @cmd
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "curl a échoué (exit code $exitCode). Réponse partielle : $response"
        }
        return $response
    }
    else {
        # Sinon on utilise Invoke-RestMethod (PowerShell natif)
        $cred = New-Object System.Management.Automation.PSCredential(
            $jiraUser,
            (ConvertTo-SecureString $jiraPass -AsPlainText -Force)
        )
        $headers = @{ "Content-Type" = "application/json" }

        # Bypass du certificat auto-signé (équivalent de -k)
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.ServerCertificateCustomValidationCallback = { $true }
        $httpClient = New-Object System.Net.Http.HttpClient($handler)

        Write-Output ">>> Invoking REST (PowerShell) : $testsApiUrl"
        $response = Invoke-RestMethod -Uri $testsApiUrl `
                                      -Method GET `
                                      -Headers $headers `
                                      -Credential $cred `
                                      -HttpClient $httpClient
        return $response
    }
}

# 5.4 - Récupération et journalisation brute
try {
    $rawResponse = Get-HttpResponse
}
catch {
    Write-Error "Échec de la requête JIRA : $_"
    exit 1
}

# Si la réponse est vide (null ou chaîne vide) on signale l'erreur rapidement
if ($null -eq $rawResponse -or ($rawResponse -is [string] -and $rawResponse.Trim() -eq "")) {
    Write-Error "La réponse JSON est nulle. Vérifiez l'URL et les identifiants."
    exit 1
}

Write-Output $rawResponse

# 5.5 - Conversion JSON (peut être un tableau ou un objet avec .tests)
try {
    $decoded = $rawResponse | ConvertFrom-Json
}
catch {
    Write-Error "Impossible de convertir la réponse en JSON : $_"
    exit 1
}

Write-Output "=== Objet JSON décodé ==="
$decoded | Format-List -Force

# 5.6 - Extraction des clés de test
$filters = @()
# Cas 1 : réponse directe sous forme de tableau (ex : [ {"key":"AMCXSOL-3395-TC01"}, ... ])
if ($decoded -and $decoded -is [System.Collections.IEnumerable] -and $decoded.Count -gt 0) {
    foreach ($obj in $decoded) {
        if ($obj.PSObject.Properties.Name -contains 'key') {
            $filters += "--include $($obj.key)"
            Write-Output "Test key (direct) : $($obj.key)"
        }
    }
}
# Cas 2 : réponse contenant un sous-objet nommé 'tests'
elseif ($decoded.tests -and $decoded.tests -is [System.Collections.IEnumerable]) {
    foreach ($obj in $decoded.tests) {
        if ($obj.PSObject.Properties.Name -contains 'key') {
            $filters += "--include $($obj.key)"
            Write-Output "Test key (tests) : $($obj.key)"
        }
    }
}
else {
    Write-Warning "Aucun tableau de tests détecté dans la réponse JSON."
}

# 5.7 - Écriture du fichier 'robot_arg.txt'
if ($filters.Count -gt 0) {
    $filtersText = ($filters -join "`r`n") + "`r`n"
    Set-Content -Path $outputFile -Value $filtersText -Encoding utf8
    Write-Output "Test IDs written to $outputFile"
}
else {
    # Aucun filtre -> on bloque la pipeline (évite l'exécution globale)
    Set-Content -Path $outputFile -Value ""    # crée le fichier vide pour la traçabilité
    Write-Error "ERREUR FATALE : Aucun test n'a été trouvé pour l'ISSUE_KEY $ISSUE_KEY. Le fichier d'arguments est vide."
    exit 1
}

# 5.8 - Affichage du contenu du fichier d'arguments (debug)
Write-Output "=== Contenu de $outputFile ==="
Get-Content $outputFile

# ===========================
# 6  Exécution de Robot Framework
# ===========================
if (-not (Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }

$robotArgs = @(
    "-A", $outputFile,                # fichier d'arguments contenant les --include
    "--nostatusrc",
    "-L", "info",
    "--outputdir", $resultsDir,
    "--output", "output.xml",
    "--log", $logFile,
    "--report", "report.html",
    "--listener", $listenerPath,
    $robotCampaignDir
)

Write-Output ">>> Lancement de Robot Framework : $robotPath @robotArgs"
& $robotPath @robotArgs
$robotExitCode = $LASTEXITCODE
Write-Output "Robot exit code: $robotExitCode"

if ($robotExitCode -ne 0) {
    Write-Error "Robot tests FAILED (code $robotExitCode)"
    exit $robotExitCode
}

# ===========================
# 7  Compression des résultats
# ===========================
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$resultsDir\*" -DestinationPath $zipPath -Force
if (-not (Test-Path $zipPath)) {
    Write-Error "results.zip was not created"
    exit 1
}
Write-Output "Results zipped: $zipPath"

# ===========================
# 8  Publication sur JIRA
# ===========================
Write-Output "===== JIRA CONFIG CHECK ====="
Write-Output "JIRA_BASE_URL = $jiraBaseUrl"
Write-Output "JIRA_USERNAME = $jiraUser"
Write-Output "ISSUE_KEY     = $ISSUE_KEY"
Write-Output "PROXY         = $proxy"
Write-Output "CURL_PATH     = $curlPath"
Write-Output "============================="

# ----------
# Helper : exit if une étape réussit (pour éviter les étapes suivantes)
# ----------
function Exit-IfSuccess {
    param($ok, $label)
    if ($ok) {
        Write-Output "$label SUCCESS"
        exit 0
    }
}

# ----------
# Helper : création d'un credential JIRA (utile pour les appels curl)
# ----------
function New-JiraCredential {
    return New-Object PSCredential $jiraUser, (ConvertTo-SecureString $jiraPass -AsPlainText -Force)
}

# ----------
# 8a. Attacher le zip aux tickets JIRA
# ----------
$zipToJiraSuccess = $false
try {
    $attachUrl = "$jiraBaseUrl/rest/api/2/issue/$ISSUE_KEY/attachments"
    $curlArgs = @(
        "-k","-v","-D-",
        "-u", "$jiraUser`:$jiraPass",
        "-X","POST",
        "-H","X-Atlassian-Token: nocheck",
        "-F","file=@$zipPath",
        $attachUrl
    )
    Write-Output ">>> Envoi du zip à JIRA (attachments)..."
    & $curlPath @curlArgs
    if ($LASTEXITCODE -eq 0) {
        $zipToJiraSuccess = $true
        Write-Output "Attachment zip_to_jira SUCCESS"
    }
    else {
        Write-Warning "curl exited with code $LASTEXITCODE while attaching zip"
    }
}
catch { Write-Warning "Attach zip FAILED : $_" }

# ----------
# 8b. Import du rapport Robot dans XRAY
# ----------
$xrayImportSuccess = $false
try {
    $robotOutput = Join-Path $resultsDir 'output.xml'
    if (-not (Test-Path $robotOutput)) { throw "output.xml NOT FOUND : $robotOutput" }

    $xrayUrl = "$jiraBaseUrl/rest/raven/1.0/import/execution/robot?testExecKey=$ISSUE_KEY"
    $curlArgs = @(
        "-k","-v",
        "-u", "$jiraUser`:$jiraPass",
        "-X","POST",
        "-F","file=@$robotOutput",
        $xrayUrl
    )
    Write-Output ">>> Import XRAY du fichier $robotOutput..."
    & $curlPath @curlArgs
    if ($LASTEXITCODE -eq 0) {
        $xrayImportSuccess = $true
        Write-Output "XRAY import completed"
    }
    else {
        Write-Warning "XRAY import failed (exit code $LASTEXITCODE)"
    }
}
catch { Write-Warning "XRAY import FAILED : $_" }

# ----------
# 8c. Envoi du statut PASS/FAIL via le hook CB-Automation
# ----------
$hookStatusSuccess = $false
try {
    $status    = if ($robotExitCode -eq 0) { 'PASS' } else { 'FAIL' }
    $reportUrl = "$env:CI_PIPELINE_URL/artifacts/browse/results/report.html"

    $payload = @{
        issues = @($ISSUE_KEY)
        data   = @{
            status         = $status
            initiatorEmail = $EMAIL
            robotReportUrl = $reportUrl
        }
    }
    $jsonBody = $payload | ConvertTo-Json -Depth 6 -Compress

    # Fonction d'appel curl (avec ou sans proxy)
    function Invoke-CurlOnce {
        param([string]$Label, [string]$Proxy = $null)
        Write-Output "---- $Label ----"
        $auth = "$jiraUser`:$jiraPass"
        $args = @(
            "-k","-sS","-D","-","-o","NUL",
            "-u",$auth,
            "-X","POST",
            "-H","Content-Type: application/json",
            "--data-binary",$jsonBody,
            $hookUrl
        )
        if ($Proxy) { $args = @("--proxy",$Proxy) + $args }
        & $curlPath @args
        return ($LASTEXITCODE -eq 0)
    }

    # Liste de proxys à tester (inclut le « no-proxy »)
    $proxies = @(
        $null,
        $env:HTTPS_PROXY,
        $env:HTTP_PROXY,
        $proxy,
        '',
        ''
    ) | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique

    # Essai sans proxy d'abord
    if (Invoke-CurlOnce -Label "NO PROXY") {
        $hookStatusSuccess = $true
    }
    else {
        foreach ($p in $proxies) {
            if (Invoke-CurlOnce -Label "WITH PROXY $p" -Proxy $p) {
                $hookStatusSuccess = $true
                break
            }
        }
    }
}
catch { Write-Warning "Hook status FAILED : $_" }

# ----------
# 9  Si aucune des méthodes d'upload ne réussit -> échec global
# ----------
if (-not ($zipToJiraSuccess -or $xrayImportSuccess -or $hookStatusSuccess)) {
    Write-Error "ALL JIRA UPLOAD METHODS FAILED"
    exit 1
}

# Sinon, le script se termine avec succès (exit 0)
exit 0
