# Compatible PowerShell 5.1+

$token  = "TON_TOKEN"
$projId = 316

$baseUrl = "https://gitlab.com/api/v4/projects/$projId/pipeline_schedules"

$headers = @{
    "PRIVATE-TOKEN" = $token
}

function Get-TimeLeft {
    param ([string]$NextRunAt)

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

function Get-LastSchedulePipelineStatus {
    param (
        [int]$ScheduleId
    )

    try {
        $pipelines = Invoke-RestMethod `
            -Uri "$baseUrl/$ScheduleId/pipelines" `
            -Method Get `
            -Headers $headers

        if ($pipelines.Count -gt 0) {
            return $pipelines[0].status
        }

        return "Aucun run"
    }
    catch {
        return "Erreur"
    }
}

function Watch-Pipeline {
    param (
        [int]$ProjectId,
        [int]$PipelineId,
        [hashtable]$Headers
    )

    Write-Host "`nSurveillance du pipeline $PipelineId..." -ForegroundColor Cyan

    while ($true) {
        Start-Sleep -Seconds 5

        $pipeline = Invoke-RestMethod `
            -Uri "https://gitlab.com/api/v4/projects/$ProjectId/pipelines/$PipelineId" `
            -Method Get `
            -Headers $Headers

        $status = $pipeline.status

        Write-Host "Etat actuel : $status"

        switch ($status) {
            "success" {
                Write-Host "`nPipeline terminé avec succès." -ForegroundColor Green
                Write-Host "URL : $($pipeline.web_url)"
                return
            }

            "failed" {
                Write-Host "`nPipeline échoué." -ForegroundColor Red
                Write-Host "URL : $($pipeline.web_url)"
                return
            }

            "canceled" {
                Write-Host "`nPipeline annulé." -ForegroundColor Yellow
                Write-Host "URL : $($pipeline.web_url)"
                return
            }

            "skipped" {
                Write-Host "`nPipeline skipped." -ForegroundColor Yellow
                Write-Host "URL : $($pipeline.web_url)"
                return
            }
        }
    }
}

$schedules = Invoke-RestMethod `
    -Uri $baseUrl `
    -Method Get `
    -Headers $headers

Write-Host "`nSchedules GitLab :" -ForegroundColor Cyan

$schedules | ForEach-Object {

    $pipelineStatus = Get-LastSchedulePipelineStatus -ScheduleId $_.id

    if ($_.active -eq $true) {
        $timeLeft = Get-TimeLeft -NextRunAt $_.next_run_at

        Write-Host "ID: $($_.id) | Description: $($_.description) | Active: $($_.active) | Last status: $pipelineStatus | Next run: $($_.next_run_at) | Dans: $timeLeft"
    }
    else {
        Write-Host "ID: $($_.id) | Description: $($_.description) | Active: $($_.active) | Last status: $pipelineStatus"
    }
}

$scheduleId = Read-Host "`nEntre l'ID du schedule à modifier"

$selectedSchedule = $schedules | Where-Object { $_.id -eq [int]$scheduleId }

if (-not $selectedSchedule) {
    Write-Host "Schedule introuvable." -ForegroundColor Red
    exit 1
}

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
    $pipelineStatus = Get-LastSchedulePipelineStatus -ScheduleId $scheduleId

    Write-Host "Last status: $pipelineStatus"
    Write-Host "Next run: $($result.next_run_at)"
    Write-Host "Dans: $timeLeft"

    $runNow = Read-Host "`nTu veux lancer ce schedule maintenant ? Tape O pour oui, N pour non"

    if ($runNow.ToUpper() -eq "O") {
        $runResult = Invoke-RestMethod `
            -Uri "$baseUrl/$scheduleId/play" `
            -Method Post `
            -Headers $headers

        $pipelineId = $runResult.id

        Write-Host "`nPipeline lancé directement." -ForegroundColor Green
        Write-Host "Pipeline ID: $pipelineId"
        Write-Host "Etat initial : $($runResult.status)"
        Write-Host "URL : $($runResult.web_url)"

        $watch = Read-Host "`nTu veux surveiller son état ? Tape O pour oui, N pour non"

        if ($watch.ToUpper() -eq "O") {
            Watch-Pipeline `
                -ProjectId $projId `
                -PipelineId $pipelineId `
                -Headers $headers
        }
    }
}