# Compatible PowerShell 5.1+

$token  = "TON_TOKEN"
$projId = 316

$baseUrl = "https://gitlab.com/api/v4/projects/$projId/pipeline_schedules"

$headers = @{
    "PRIVATE-TOKEN" = $token
}

function Get-TimeLeft {
    param (
        [string]$NextRunAt
    )

    if (-not $NextRunAt) {
        return "N/A"
    }

    $nextRunDate = [datetime]$NextRunAt
    $remaining = $nextRunDate.ToUniversalTime() - (Get-Date).ToUniversalTime()

    if ($remaining.TotalSeconds -lt 0) {
        return "Déjà passé"
    }

    return "{0}j {1}h {2}m" -f `
        $remaining.Days, `
        $remaining.Hours, `
        $remaining.Minutes
}

# 1. Récupérer les schedules
$schedules = Invoke-RestMethod `
    -Uri $baseUrl `
    -Method Get `
    -Headers $headers

Write-Host "`nSchedules GitLab :" -ForegroundColor Cyan

$schedules | ForEach-Object {
    if ($_.active -eq $true) {
        $timeLeft = Get-TimeLeft -NextRunAt $_.next_run_at
        Write-Host "ID: $($_.id) | Description: $($_.description) | Active: $($_.active) | Next run: $($_.next_run_at) | Dans: $timeLeft"
    }
    else {
        Write-Host "ID: $($_.id) | Description: $($_.description) | Active: $($_.active)"
    }
}

# 2. Choisir un schedule
$scheduleId = Read-Host "`nEntre l'ID du schedule à modifier"

$selectedSchedule = $schedules | Where-Object { $_.id -eq [int]$scheduleId }

if (-not $selectedSchedule) {
    Write-Host "Schedule introuvable." -ForegroundColor Red
    exit 1
}

# 3. Activer ou désactiver
$choice = Read-Host "`nTape A pour activer, D pour désactiver"

switch ($choice.ToUpper()) {
    "A" { $activeValue = "true" }
    "D" { $activeValue = "false" }
    default {
        Write-Host "Choix invalide. Utilise A ou D." -ForegroundColor Red
        exit 1
    }
}

$headersUpdate = @{
    "PRIVATE-TOKEN" = $token
    "Content-Type"  = "application/x-www-form-urlencoded"
}

$body = "active=$activeValue"

$result = Invoke-RestMethod `
    -Uri "$baseUrl/$scheduleId" `
    -Method Put `
    -Headers $headersUpdate `
    -Body $body

Write-Host "`nSchedule mis à jour :" -ForegroundColor Green
Write-Host "ID: $($result.id)"
Write-Host "Description: $($result.description)"
Write-Host "Active: $($result.active)"

if ($result.active -eq $true) {
    $timeLeft = Get-TimeLeft -NextRunAt $result.next_run_at
    Write-Host "Next run: $($result.next_run_at)"
    Write-Host "Dans: $timeLeft"

    $runNow = Read-Host "`nTu veux lancer ce schedule maintenant ? Tape O pour oui, N pour non"

    if ($runNow.ToUpper() -eq "O") {
        $runResult = Invoke-RestMethod `
            -Uri "$baseUrl/$scheduleId/play" `
            -Method Post `
            -Headers $headers

        Write-Host "`nPipeline lancé directement." -ForegroundColor Green
        Write-Host "Pipeline ID: $($runResult.id)"
        Write-Host "Status: $($runResult.status)"
        Write-Host "Web URL: $($runResult.web_url)"
    }
}