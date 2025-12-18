$robotArgs = @(
    "-A", $OUTPUT_FILE,
    "--nostatusrc",
    "-L", "debug",
    "--outputdir", $RESULTS_DIR,
    "--output", "output.xml",
    "--log", "log.html",
    "--report", "report.html",
    $robotCampaignDirectory
)

if (-not [string]::IsNullOrEmpty($listenerPath)) {
    $robotArgs += @("--listener", $listenerPath)
}



& $robotPath @robotArgs
$robotExitCode = $LASTEXITCODE

Write-Output "Robot exit code: $robotExitCode"

if ($robotExitCode -ne 0) {
    Write-Error "Robot tests FAILED"
    exit $robotExitCode
}