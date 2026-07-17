if (-not ($zipToJiraSuccess -or $xrayImportSuccess -or $hookStatusSuccess)) {
    Write-Error "ALL JIRA UPLOAD METHODS FAILED"
    exit 1
}

# --------------------------------------------------
# Activate Python virtual environment
# --------------------------------------------------
$venvPath = "C:\Users\labadmin\.virtualenvs\tr_pmr_agent_test_automation-g5sg01gvm"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

$dashboardScript = "C:\Users\labadmin\Documents\dashboard_confluence.py"

try {
    Write-Host "Activating Python virtual environment..."

    if (-not (Test-Path $activateScript)) {
        throw "Virtual environment activation script not found: $activateScript"
    }

    # Le point permet d'activer l'environnement dans la session PowerShell actuelle
    . $activateScript

    Write-Host "Launching dashboard script..."

    if (-not (Test-Path $dashboardScript)) {
        throw "Dashboard script not found: $dashboardScript"
    }

    & $pythonExe $dashboardScript

    if ($LASTEXITCODE -ne 0) {
        throw "Dashboard script failed with exit code $LASTEXITCODE"
    }

    Write-Host "Dashboard script completed successfully"
}
catch {
    Write-Error "Dashboard execution FAILED: $_"
    exit 1
}

exit 0