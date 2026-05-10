function Get-HttpResponse {
    # Si le binaire curl existe on l'utilise - c'est le plus simple pour les options proxy / -k
    if (Test-Path $curlPath) {
        # Fichier de cookie jar : nécessaire pour que -L conserve le JSESSIONID posé par le 307
        # (on n'utilise PAS -b "" car PowerShell 5.1 avale les chaînes vides dans les args natifs)
        $cookieFile = Join-Path $env:TEMP "jira_session_cookies.txt"
        if (Test-Path $cookieFile) { Remove-Item $cookieFile -Force }

        $cmd = @(
            "-k",                                # ignorer la validation du certificat
            "-sS",                               # silence la barre de progression mais garde les erreurs
            "-L",                                # suit les redirects (JIRA renvoie un 307 pour poser le JSESSIONID)
            "-c", $cookieFile,                   # écrit les cookies reçus -> active le cookie engine
            "-b", $cookieFile,                   # relit les cookies à chaque hop du redirect
            "-u", "${jiraUser}:${jiraPass}",
            "-H", "Accept: application/json",
            "-X", "GET",
            "--proxy", $proxy,
            $testsApiUrl
        )
        Write-Output ">>> Executing curl : $curlPath $($cmd -join ' ')"
        $response = & $curlPath @cmd
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "curl a échoué (exit code $exitCode). Réponse partielle : $response"
        }
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
