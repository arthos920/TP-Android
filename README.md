$robotCommand = "`"$robotPath`" -A `"$OUTPUT_FILE`" --nostatusrc -L debug --outputdir `"$RESULTS_DIR`" --output output.xml --log log.html --report report.html"





# Définir le dossier de résultats
$workspace   = Get-Location
$RESULTS_DIR = Join-Path $workspace "results"

if (!(Test-Path $RESULTS_DIR)) {
    New-Item -ItemType Directory -Path $RESULTS_DIR | Out-Null
}

# Construire la commande pour lancer les tests Robot Framework
$robotCommand = @"
"$robotPath" `
  -A "$OUTPUT_FILE" `
  --nostatusrc `
  -L debug `
  --outputdir "$RESULTS_DIR" `
  --output output.xml `
  --log log.html `
  --report report.html
"@

# Ajouter le paramètre listener si listenerPath n'est pas vide
if (-not [string]::IsNullOrEmpty($listenerPath)) {
    $robotCommand += " --listener $listenerPath"
}

# Ajouter le dossier de campagne Robot
$robotCommand += " $robotCampaignDirectory"

try {
    Invoke-Expression $robotCommand
} catch {
    Write-Output "Erreur lors du lancement des tests Robot Framework : $_"
    exit
}

Write-Output "Tests Robot Framework ont été lancés avec succès."



















& $robotPath `
  -L debug `
  --outputdir $RESULTS_DIR `
  --output check_actors.xml `
  --log log_actors.html `
  --report report_actors.html `
  $checkActorFile




# ------------------------------
# Dossier de sortie Robot
# ------------------------------
$RESULTS_DIR = Join-Path $workspace "results"

if (!(Test-Path $RESULTS_DIR)) {
    New-Item -ItemType Directory -Path $RESULTS_DIR | Out-Null
}

Write-Output "Robot results directory: $RESULTS_DIR"

$outputFile = Join-Path $RESULTS_DIR "check_actors.xml"
$logFile    = Join-Path $RESULTS_DIR "log_actors.html"
$reportFile = Join-Path $RESULTS_DIR "report_actors.html"








def log_screenshot(driver):
    import os, time
    from robot.api import logger

    base_dir = os.environ.get("ROBOT_OUTPUT_DIR", "results")
    screenshots_dir = os.path.join(base_dir, "screenshots")

    os.makedirs(screenshots_dir, exist_ok=True)

    filename = f"screenshot_{int(time.time()*1000)}.png"
    img_path = os.path.join(screenshots_dir, filename)

    driver.get_screenshot_as_file(img_path)

    # 🔥 CHEMIN RELATIF
    rel_path = os.path.join("screenshots", filename)

    logger.info(
        f'<a href="{rel_path}"><img src="{rel_path}" width="400px"></a>',
        html=True
    )