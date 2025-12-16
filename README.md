Write-Output "Executing Robot Framework tests..."

& $robotPath `
    -L debug `
    --output $outputFile `
    --log $logFile `
    --report $reportFile `
    $checkActorFile

$robotExitCode = $LASTEXITCODE

Write-Output "Robot exit code: $robotExitCode"

if ($robotExitCode -ne 0) {
    Write-Error "Robot tests FAILED"
    exit $robotExitCode
}

Write-Output "Robot tests PASSED"
exit 0





            
