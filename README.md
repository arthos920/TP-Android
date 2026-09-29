if ($AfterJob) {
    $jobStatus = ([string]$env:CI_JOB_STATUS).Trim()

    if ([string]::IsNullOrWhiteSpace($jobStatus)) {
        Write-Error 'CI_JOB_STATUS est absent.' -ErrorAction Continue
        exit 1
    }

    if ($jobStatus -notin @('failed', 'timedout')) {
        Write-Host "Job status is '$jobStatus': no Jira reset."
        exit 0
    }

    Write-Host "Job status is '$jobStatus': remise des tests a TODO."
}