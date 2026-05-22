# Compatible PowerShell 5.1+

$token  = "TON_TOKEN"
$projId = 316

$baseUrl = "https://gitlab.com/api/v4/projects/$projId/pipeline_schedules"

$headers = @{
    "PRIVATE-TOKEN" = $token
}

# 1. Récupérer la liste des schedules
$schedules = Invoke-RestMethod `
    -Uri $baseUrl `
    -Method Get `
    -Headers $headers

Write-Host "`nSchedules GitLab :" -ForegroundColor Cyan

$schedules | ForEach-Object {
    Write-Host "ID: $($_.id) | Description: $($_.description) | Active: $($_.active)"
}

# 2. Demander le schedule à modifier
$scheduleId = Read-Host "`nEntre l'ID du schedule à modifier"

$selectedSchedule = $schedules | Where-Object { $_.id -eq [int]$scheduleId }

if (-not $selectedSchedule) {
    Write-Host "Schedule introuvable." -ForegroundColor Red
    exit 1
}

Write-Host "`nSchedule sélectionné :"
Write-Host "ID: $($selectedSchedule.id)"
Write-Host "Description: $($selectedSchedule.description)"
Write-Host "État actuel Active: $($selectedSchedule.active)"

# 3. Demander activation ou désactivation
$choice = Read-Host "`nTu veux l'activer ou le désactiver ? Tape A pour activer, D pour désactiver"

switch ($choice.ToUpper()) {
    "A" { $activeValue = "true" }
    "D" { $activeValue = "false" }
    default {
        Write-Host "Choix invalide. Utilise A ou D." -ForegroundColor Red
        exit 1
    }
}

$body = "active=$activeValue"

$headersUpdate = @{
    "PRIVATE-TOKEN" = $token
    "Content-Type"  = "application/x-www-form-urlencoded"
}

# 4. Modifier le schedule
$result = Invoke-RestMethod `
    -Uri "$baseUrl/$scheduleId" `
    -Method Put `
    -Headers $headersUpdate `
    -Body $body

Write-Host "`nSchedule mis à jour :" -ForegroundColor Green
Write-Host "ID: $($result.id)"
Write-Host "Description: $($result.description)"
Write-Host "Active: $($result.active)"