# -------------------------------------------------------
# Configuration GitLab
# -------------------------------------------------------

$gitLabUrl = "https://XXXX/gitlab"
$projectId = "XXXX"
$ref = "main"

# Option 1 : token directement dans le script
$token = "XXXX"

# Option 2 recommandée : token dans une variable d'environnement
# $token = $env:GITLAB_PRIVATE_TOKEN


# -------------------------------------------------------
# Saisie de l'Issue Key
# -------------------------------------------------------

do {
    $issueKey = Read-Host "Entrez l'Issue Key Jira (exemple : PROJET-123)"

    if ([string]::IsNullOrWhiteSpace($issueKey)) {
        Write-Host "L'Issue Key est obligatoire."
    }
}
while ([string]::IsNullOrWhiteSpace($issueKey))


# -------------------------------------------------------
# Saisie de l'adresse e-mail
# -------------------------------------------------------

do {
    $email = Read-Host "Entrez votre adresse e-mail"

    if ([string]::IsNullOrWhiteSpace($email)) {
        Write-Host "L'adresse e-mail est obligatoire."
    }
}
while ([string]::IsNullOrWhiteSpace($email))


# -------------------------------------------------------
# Choix du LAB
# -------------------------------------------------------

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
            $validLab = $false
        }
    }
}
while (-not $validLab)


# -------------------------------------------------------
# Récapitulatif
# -------------------------------------------------------

Write-Host ""
Write-Host "Informations de lancement :"
Write-Host "Issue Key : $issueKey"
Write-Host "Email     : $email"
Write-Host "LAB       : $lab"
Write-Host "Branche   : $ref"
Write-Host ""

$confirmation = Read-Host "Voulez-vous lancer la pipeline ? (O/N)"

if ($confirmation -notin @("O", "o", "Oui", "oui", "Y", "y", "Yes", "yes")) {
    Write-Host "Lancement annulé."
    exit 0
}


# -------------------------------------------------------
# Création de la requête GitLab
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


# -------------------------------------------------------
# Déclenchement de la pipeline
# -------------------------------------------------------

try {
    $response = Invoke-RestMethod `
        -Uri "$gitLabUrl/api/v4/projects/$projectId/pipeline" `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $body

    Write-Host ""
    Write-Host "Pipeline lancée avec succès."
    Write-Host "ID     : $($response.id)"
    Write-Host "Statut : $($response.status)"
    Write-Host "LAB    : $lab"
    Write-Host "URL    : $($response.web_url)"
}
catch {
    Write-Host ""
    Write-Host "Erreur lors du lancement de la pipeline."
    Write-Host $_.Exception.Message
    exit 1
}