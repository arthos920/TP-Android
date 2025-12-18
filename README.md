# =========================
# JIRA ATTACH UPLOAD - 3 OPTIONS TEST
# =========================

$ErrorActionPreference = "Stop"

# --- Inputs (à adapter) ---
$JIRA_URL  = "https://slc-toolset.common.airbusds.corp/jira"
$ISSUE_KEY = $env:ISSUE_KEY
$ZIP_PATH  = (Join-Path (Get-Location) "results.zip")

$JIRA_USERNAME = $env:JIRA_USERNAME
$JIRA_PASSWORD = $env:JIRA_PASSWORD

# Proxy (si tu veux tester)
$PROXY = "http://10.38.143.185:8080"

if (-not (Test-Path $ZIP_PATH)) {
  Write-Error "ZIP introuvable: $ZIP_PATH"
}

$attachUrl = "$JIRA_URL/rest/api/2/issue/$ISSUE_KEY/attachments"

function Run-CurlUpload {
  param(
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][string[]]$Args
  )

  Write-Host "======================================="
  Write-Host ">>> $Label"
  Write-Host "CMD: curl.exe $($Args -join ' ')"
  Write-Host "---------------------------------------"

  $tmpOut = Join-Path $env:TEMP "jira_upload_out_$Label.txt"
  $tmpErr = Join-Path $env:TEMP "jira_upload_err_$Label.txt"

  # curl: on récupère le code HTTP dans la sortie
  $httpCode = & curl.exe @Args 1> $tmpOut 2> $tmpErr

  Write-Host "HTTP_CODE: $httpCode"
  Write-Host "--- STDOUT ---"
  Get-Content $tmpOut -ErrorAction SilentlyContinue | Select-Object -First 50
  Write-Host "--- STDERR ---"
  Get-Content $tmpErr -ErrorAction SilentlyContinue | Select-Object -First 50

  return $httpCode
}

function Run-IWRUpload {
  Write-Host "======================================="
  Write-Host ">>> OPTION 3: Invoke-WebRequest multipart (PS5.1 compatible)"
  Write-Host "---------------------------------------"

  try {
    $boundary = [System.Guid]::NewGuid().ToString("N")
    $fileBytes = [System.IO.File]::ReadAllBytes($ZIP_PATH)
    $fileName = [System.IO.Path]::GetFileName($ZIP_PATH)

    $pre  = "--$boundary`r`n"
    $pre += "Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"`r`n"
    $pre += "Content-Type: application/zip`r`n`r`n"

    $post = "`r`n--$boundary--`r`n"

    $preBytes  = [System.Text.Encoding]::UTF8.GetBytes($pre)
    $postBytes = [System.Text.Encoding]::UTF8.GetBytes($post)

    $ms = New-Object System.IO.MemoryStream
    $ms.Write($preBytes, 0, $preBytes.Length) | Out-Null
    $ms.Write($fileBytes, 0, $fileBytes.Length) | Out-Null
    $ms.Write($postBytes, 0, $postBytes.Length) | Out-Null
    $ms.Position = 0

    # Auth Basic (géré par .NET). Tu ne fais PAS de base64 “à la main”.
    $pair = "$JIRA_USERNAME`:$JIRA_PASSWORD"
    $b64  = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))

    $headers = @{
      "X-Atlassian-Token" = "no-check"
      "Authorization"     = "Basic $b64"
    }

    # Proxy: pour tester sans proxy, commente la ligne suivante
    $webProxy = New-Object System.Net.WebProxy($PROXY, $true)

    $resp = Invoke-WebRequest -Method Post -Uri $attachUrl `
      -Headers $headers `
      -ContentType "multipart/form-data; boundary=$boundary" `
      -Body $ms.ToArray() `
      -Proxy $webProxy `
      -UseBasicParsing

    Write-Host "HTTP_CODE: $($resp.StatusCode)"
    Write-Host ($resp.Content | Select-Object -First 1)
    return $resp.StatusCode
  }
  catch {
    Write-Host "ECHEC OPTION 3: $($_.Exception.Message)"
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
      Write-Host "HTTP_CODE: $([int]$_.Exception.Response.StatusCode)"
    }
    return "ERROR"
  }
}

# -------- OPTION 1: curl.exe SANS proxy --------
$code1 = Run-CurlUpload -Label "OPTION_1_NO_PROXY" -Args @(
  "-sS", "-o", "jira_attach_resp_no_proxy.json",
  "-w", "%{http_code}",
  "-u", "$JIRA_USERNAME`:$JIRA_PASSWORD",
  "-H", "X-Atlassian-Token: no-check",
  "-F", "file=@$ZIP_PATH",
  $attachUrl
)

# -------- OPTION 2: curl.exe AVEC proxy --------
$code2 = Run-CurlUpload -Label "OPTION_2_WITH_PROXY" -Args @(
  "-sS", "-o", "jira_attach_resp_with_proxy.json",
  "-w", "%{http_code}",
  "--proxy", $PROXY,
  "-u", "$JIRA_USERNAME`:$JIRA_PASSWORD",
  "-H", "X-Atlassian-Token: no-check",
  "-F", "file=@$ZIP_PATH",
  $attachUrl
)

# -------- OPTION 2b: curl.exe AVEC proxy + insecure (si inspection SSL) --------
$code2b = Run-CurlUpload -Label "OPTION_2B_WITH_PROXY_INSECURE" -Args @(
  "-k",
  "-sS", "-o", "jira_attach_resp_with_proxy_insecure.json",
  "-w", "%{http_code}",
  "--proxy", $PROXY,
  "-u", "$JIRA_USERNAME`:$JIRA_PASSWORD",
  "-H", "X-Atlassian-Token: no-check",
  "-F", "file=@$ZIP_PATH",
  $attachUrl
)

# -------- OPTION 3: Invoke-WebRequest multipart --------
$code3 = Run-IWRUpload

Write-Host "======================================="
Write-Host "RESULTS:"
Write-Host "  Option1 (no proxy)        : $code1"
Write-Host "  Option2 (with proxy)      : $code2"
Write-Host "  Option2b (proxy + -k)     : $code2b"
Write-Host "  Option3 (Invoke-WebRequest): $code3"
Write-Host "======================================="