function Get-HttpResponse {
    # Si le binaire curl existe on l'utilise - c'est le plus simple pour les options proxy / -k
    if (Test-Path $curlPath) {
        # Fichier de cookie jar : nécessaire pour que -L conserve le JSESSIONID posé par le 307
        $cookieFile = Join-Path $env:TEMP "jira_session_cookies.txt"
        if (Test-Path $cookieFile) { Remove-Item $cookieFile -Force }

        # On fait écrire curl dans un fichier (-o) au lieu de capturer via PowerShell,
        # pour éviter les soucis de split sur newline, BOM, encoding, etc.
        $responseFile = Join-Path $env:TEMP "jira_response.json"
        if (Test-Path $responseFile) { Remove-Item $responseFile -Force }

        $cmd = @(
            "-k",                                # ignorer la validation du certificat
            "-sS",                               # silence la barre de progression mais garde les erreurs
            "-L",                                # suit les redirects (JIRA renvoie un 307 pour poser le JSESSIONID)
            "-c", $cookieFile,                   # écrit les cookies reçus -> active le cookie engine
            "-b", $cookieFile,                   # relit les cookies à chaque hop du redirect
            "-o", $responseFile,                 # écrit le body dans un fichier
            "-w", "HTTP_CODE=%{http_code}",      # affiche le code HTTP final sur stdout
            "-u", "${jiraUser}:${jiraPass}",
            "-H", "Accept: application/json",
            "-X", "GET",
            "--proxy", $proxy,
            $testsApiUrl
        )
        Write-Output ">>> Executing curl : $curlPath $($cmd -join ' ')"
        $httpInfo = & $curlPath @cmd
        $exitCode = $LASTEXITCODE
        Write-Output "curl exit code: $exitCode, $httpInfo"

        if ($exitCode -ne 0) {
            throw "curl a échoué (exit code $exitCode, $httpInfo)"
        }
        if (-not (Test-Path $responseFile)) {
            throw "Fichier de réponse curl introuvable : $responseFile"
        }
        # Lecture en UTF-8 brute, en une seule chaîne
        $response = Get-Content $responseFile -Raw -Encoding UTF8
        Remove-Item $responseFile -Force
        return $response
    }
    else {
        # Sinon on utilise Invoke-RestMethod (PowerShell natif)
        $cred = New-Object System.Management.Automation.PSCredential(
            $jiraUser,
            (ConvertTo-SecureString $jiraPass -AsPlainText -Force)
        )
        $headers = @{ "Content-Type" = "application/json" }

        # Bypass du certificat auto-signé (équivalent de -k)
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.ServerCertificateCustomValidationCallback = { $true }
        $httpClient = New-Object System.Net.Http.HttpClient($handler)

        Write-Output ">>> Invoking REST (PowerShell) : $testsApiUrl"
        $response = Invoke-RestMethod -Uri $testsApiUrl `
                                      -Method GET `
                                      -Headers $headers `
                                      -Credential $cred `
                                      -HttpClient $httpClient
        return $response
    }
}

# 5.4 - Récupération et journalisation brute
try {
    $rawResponse = Get-HttpResponse
}
catch {
    Write-Error "Échec de la requête JIRA : $_"
    exit 1
}
