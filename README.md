param(
    [Parameter(Mandatory = $true)]
    [string]$ISSUE_KEY,

    [Parameter(Mandatory = $true)]
    [string]$LAB,

    [Parameter(Mandatory = $true)]
    [string]$URL,

    [Parameter(Mandatory = $true)]
    [string]$EMAIL
)

Write-Output "===== CHECK ACTORS LAUNCH ====="
Write-Output "LAB        : $LAB"
Write-Output "ISSUE_KEY  : $ISSUE_KEY"
Write-Output "PIPELINE   : $URL"
Write-Output "EMAIL      : $EMAIL"

# ------------------------------------------------------------
# Récupérer le répertoire du script
# ------------------------------------------------------------
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Output "Script directory: $scriptDirectory"

# ------------------------------------------------------------
# Charger la configuration JSON
# ------------------------------------------------------------
$configFilePath = Join-Path -Path $scriptDirectory -ChildPath "lab_config.json"

if (-Not (Test-Path $configFilePath)) {
    Write-Error "Configuration file not found: $configFilePath"
    exit 1
}

$config = Get-Content -Path $configFilePath | ConvertFrom-Json

# ------------------------------------------------------------
# Vérifier que le LAB existe dans la config
# ------------------------------------------------------------
if (-not ($config.PSObject.Properties.Name -contains $LAB)) {
    Write-Error "Configuration for lab '$LAB' not found in lab_config.json"
    exit 1
}

$labConfig = $config.$LAB

$robotCampaignDirectory = $labConfig.robotCampaignDirectory
$checkActorFile         = $labConfig.checkActorFile
$robotPath              = $labConfig.robotPath
$listenerPath           = $labConfig.listenerPath
$pythonPath             = $labConfig.pythonPath

Write-Output "Robot path              : $robotPath"
Write-Output "Robot campaign directory: $robotCampaignDirectory"
Write-Output "Check actor file        : $checkActorFile"

# ------------------------------------------------------------
# Se placer dans le bon dossier
# ------------------------------------------------------------
if (-Not (Test-Path $robotCampaignDirectory)) {
    Write-Error "Robot campaign directory not found: $robotCampaignDirectory"
    exit 1
}

Set-Location $robotCampaignDirectory

# ------------------------------------------------------------
# Fichiers de sortie Robot
# ------------------------------------------------------------
$outputFile = "check_actors.xml"
$logFile    = "log_actors.html"
$reportFile = "report_actors.html"

# ------------------------------------------------------------
# Lancer Robot Framework
# ------------------------------------------------------------
Write-Output "Launching Robot Framework..."

& $robotPath `
    -L debug `
    --output $outputFile `
    --log $logFile `
    --report $reportFile `
    $checkActorFile

$robotExitCode = $LASTEXITCODE

Write-Output "Robot exit code: $robotExitCode"

# ------------------------------------------------------------
# Propager le résultat vers GitLab
# ------------------------------------------------------------
if ($robotExitCode -ne 0) {
    Write-Error "❌ Robot tests FAILED"
    exit $robotExitCode
}

Write-Output "✅ Robot tests PASSED"
exit 0
            
