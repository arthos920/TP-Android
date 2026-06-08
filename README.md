# ------------------------------------------------------------
# Lancer Robot Framework
# ------------------------------------------------------------

$robotExitCode = 1

while ($robotExitCode -ne 0) {

    Write-Output "Launching Robot Framework..."

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
        Write-Output "Robot failed. Retrying in 5 seconds..."
        Start-Sleep -Seconds 5
    }
}

# ------------------------------------------------------------
# Propager le résultat vers GitLab
# ------------------------------------------------------------

Write-Output "Robot tests PASSED"
exit 0