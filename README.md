#Requires -Version 5.1

# -------------------------------------------------------
# Configuration GitLab : valeurs à adapter
# -------------------------------------------------------

$gitLabUrl = "https://XXXX/gitlab"
$projectId = "XXXX"
$ref = "main"
$token = "XXXX"

# Supprime le dernier "/" s'il est présent
$gitLabUrl = $gitLabUrl.TrimEnd("/")


# -------------------------------------------------------
# Demande de l'Issue Key Jira
# -------------------------------------------------------

do {
    $issueKey = Read-Host "Entrez l'Issue Key Jira (exemple : PROJET-123)"

    if ([string]::IsNullOrWhiteSpace($issueKey)) {
        Write-Host "L'Issue Key est obligatoire."
    }
}
while ([string]::IsNullOrWhiteSpace($issueKey))

$issueKey = $issueKey.Trim().ToUpper()


# -------------------------------------------------------
# Demande de l'adresse e-mail
# -------------------------------------------------------

do {
    $email = Read-Host "Entrez votre adresse e-mail"

    $emailIsValid = (
        -not [string]::IsNullOrWhiteSpace($email) -and
        $email -match "^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    if (-not $emailIsValid) {
        Write-Host "Veuillez entrer une adresse e-mail valide."
    }
}
while (-not $emailIsValid)

$email = $email.Trim()


# -------------------------------------------------------
# Choix du LAB
# -------------------------------------------------------

$validLab = $false

do {
    Write-Host ""
    Write-Host "Choisissez le LAB :"
    Write-Host "1 - SolutionSYS02"
    Write-Host "2 - SolutionSYS03"
    Write-Host "3 - SolutionSYS04"

    $labChoice = Read-Host "Votre choix"

    switch ($labChoice) {
        "1" {
            $lab = "SolutionSYS02"
            $validLab = $true
        }

        "2" {
            $lab = "SolutionSYS03"
            $validLab = $true
        }

        "3" {
            $lab = "SolutionSYS04"
            $validLab = $true
        }

        default {
            Write-Host "Choix invalide. Entrez 1, 2 ou 3."
        }
    }
}
while (-not $validLab)


# -------------------------------------------------------
# Récapitulatif
# -------------------------------------------------------

Write-Host ""
Write-Host "Informations de lancement"
Write-Host "-------------------------"
Write-Host "Issue Key : $issueKey"
Write-Host "Email     : $email"
Write-Host "LAB       : $lab"
Write-Host "Branche   : $ref"
Write-Host ""

$confirmation = Read-Host "Lancer la pipeline ? (O/N)"

if ($confirmation -notin @("O", "o", "Oui", "oui", "Y", "y", "Yes", "yes")) {
    Write-Host "Lancement annulé."
    exit 0
}


# -------------------------------------------------------
# Préparation de la requête GitLab
# -------------------------------------------------------

$headers = @{
    "PRIVATE-TOKEN" = $token
}

$body = @{
    ref = $ref

    variables = @(
        @{
            key   = "ISSUE_KEY"
            value = $issueKey
        },
        @{
            key   = "EMAIL"
            value = $email
        },
        @{
            key   = "LAB"
            value = $lab
        }
    )
} | ConvertTo-Json -Depth 5

$triggerUrl = "$gitLabUrl/api/v4/projects/$projectId/pipeline"


# -------------------------------------------------------
# Déclenchement de la pipeline
# -------------------------------------------------------

Write-Host ""
Write-Host "Déclenchement de la pipeline..."

try {
    $response = Invoke-RestMethod `
        -Uri $triggerUrl `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $body `
        -ErrorAction Stop
}
catch {
    Write-Host ""
    Write-Host "Erreur lors du déclenchement de la pipeline."
    Write-Host $_.Exception.Message
    exit 1
}


# -------------------------------------------------------
# Informations de la pipeline créée
# -------------------------------------------------------

$pipelineId = $response.id
$pipelineWebUrl = $response.web_url
$pipelineApiUrl = "$gitLabUrl/api/v4/projects/$projectId/pipelines/$pipelineId"

Write-Host ""
Write-Host "Pipeline lancée."
Write-Host "ID  : $pipelineId"
Write-Host "URL : $pipelineWebUrl"
Write-Host ""
Write-Host "Suivi de la pipeline toutes les 2 secondes..."
Write-Host ""


# -------------------------------------------------------
# Suivi de l'état de la pipeline
# -------------------------------------------------------

$finalStatuses = @(
    "success",
    "failed",
    "canceled",
    "skipped",
    "manual"
)

$status = ""

do {
    try {
        $pipeline = Invoke-RestMethod `
            -Uri $pipelineApiUrl `
            -Method Get `
            -Headers $headers `
            -ErrorAction Stop

        $status = $pipeline.status

        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Statut : $status"
    }
    catch {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Impossible de récupérer le statut."
        Write-Host $_.Exception.Message
    }

    if ($status -notin $finalStatuses) {
        Start-Sleep -Seconds 2
    }
}
while ($status -notin $finalStatuses)


# -------------------------------------------------------
# Résultat final
# -------------------------------------------------------

Write-Host ""
Write-Host "Résultat final"
Write-Host "--------------"

switch ($status) {
    "success" {
        Write-Host "La pipeline s'est terminée avec succès."
        $exitCode = 0
    }

    "failed" {
        Write-Host "La pipeline a échoué."
        $exitCode = 1
    }

    "canceled" {
        Write-Host "La pipeline a été annulée."
        $exitCode = 1
    }

    "skipped" {
        Write-Host "La pipeline a été ignorée."
        $exitCode = 1
    }

    "manual" {
        Write-Host "La pipeline attend une action manuelle dans GitLab."
        $exitCode = 0
    }

    default {
        Write-Host "Statut final inconnu : $status"
        $exitCode = 1
    }
}

Write-Host "URL : $pipelineWebUrl"

exit $exitCode