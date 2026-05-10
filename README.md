# 5.4 - Récupération et journalisation brute
try {
    $rawResponse = Get-HttpResponse
}
catch {
    Write-Error "Échec de la requête JIRA : $_"
    exit 1
}

# Si curl renvoie plusieurs lignes, PowerShell fait un tableau de strings.
# On force en une seule chaîne avant tout test/parsing.
$rawResponse = ($rawResponse -join "`n").Trim()

# Si la réponse est vide on signale l'erreur rapidement
if ([string]::IsNullOrWhiteSpace($rawResponse)) {
    Write-Error "La réponse JSON est nulle. Vérifiez l'URL et les identifiants."
    exit 1
}

Write-Output $rawResponse
