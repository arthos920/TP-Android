param (
    [Parameter(Mandatory = $true)]
    [string]$OutputXml,

    [switch]$ExportCsv
)

# ============================================================
# CONFIGURATION
# ============================================================

# Accepte par exemple :
# Use Ptt Release
# Use PTT Release
# Use   Ptt   Release
$PttKeywordRegex = '(?i)^\s*Use\s+Ptt\s+Release\s*$'

# Message confirmant que le PTT a réellement été pris
# Accepte quelques variantes autour du texte
$PttPressedRegex = '(?i)\bPTT\b.*\bpressed\b'


# ============================================================
# FONCTIONS
# ============================================================

function Convert-ToDateTime {
    param (
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    try {
        return [datetime]::Parse(
            $Value,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        return $null
    }
}


function Get-Driver {
    param (
        [string]$Owner
    )

    if ($Owner -match '(?i)^driver\s*([1-6])$') {
        return "driver$($Matches[1])"
    }

    return $null
}


function Format-Duration {
    param (
        [datetime]$Start,
        [datetime]$End
    )

    $duration = $End - $Start

    return "{0}j {1}h {2}min {3}s" -f `
        $duration.Days,
        $duration.Hours,
        $duration.Minutes,
        $duration.Seconds
}


# ============================================================
# VERIFICATION DU FICHIER
# ============================================================

if (-not (Test-Path $OutputXml)) {
    Write-Host "Fichier introuvable : $OutputXml"
    exit 1
}

$OutputXml = (Resolve-Path $OutputXml).Path


# ============================================================
# INITIALISATION
# ============================================================

$attempts = @{}
$pttTotals = @{}
$failTotals = @{}
$daily = @{}

foreach ($i in 1..6) {

    $driver = "driver$i"

    $attempts[$driver] = New-Object System.Collections.ArrayList
    $pttTotals[$driver] = 0
    $failTotals[$driver] = 0
}


# Keyword PTT actuellement analysé
$activePtt = $null

# Lecture d'un <msg>
$inMsg = $false
$msgText = New-Object System.Text.StringBuilder
$msgTime = $null


# ============================================================
# LECTURE XML EN STREAMING
# ============================================================

Write-Host ""
Write-Host "Analyse de : $OutputXml"
Write-Host ""

$settings = New-Object System.Xml.XmlReaderSettings
$settings.IgnoreWhitespace = $false
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Ignore

$reader = $null

try {

    $reader = [System.Xml.XmlReader]::Create(
        $OutputXml,
        $settings
    )

    while ($reader.Read()) {

        # ====================================================
        # ELEMENT OUVRANT
        # ====================================================

        if ($reader.NodeType -eq [System.Xml.XmlNodeType]::Element) {

            # ------------------------------------------------
            # Détection du keyword Use Ptt Release
            # ------------------------------------------------

            if ($reader.Name -eq "kw") {

                $name = $reader.GetAttribute("name")
                $owner = $reader.GetAttribute("owner")

                $driver = Get-Driver -Owner $owner

                if (
                    $null -eq $activePtt -and
                    $null -ne $driver -and
                    $name -match $PttKeywordRegex
                ) {

                    $activePtt = [PSCustomObject]@{
                        Driver      = $driver
                        Depth       = $reader.Depth
                        Start       = $null
                        Status      = "UNKNOWN"
                        Pressed     = $false
                        PressedTime = $null
                    }
                }
            }


            # ------------------------------------------------
            # Message appartenant au keyword PTT
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "msg" -and
                $null -ne $activePtt
            ) {

                $inMsg = $true
                $msgText.Clear() | Out-Null

                $msgTime = Convert-ToDateTime `
                    -Value $reader.GetAttribute("time")
            }


            # ------------------------------------------------
            # Status DIRECT du Use Ptt Release
            #
            # Important :
            # On ne prend pas les status de ses sous-keywords.
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "status" -and
                $null -ne $activePtt -and
                $reader.Depth -eq ($activePtt.Depth + 1)
            ) {

                $status = $reader.GetAttribute("status")
                $start = $reader.GetAttribute("start")

                if (-not [string]::IsNullOrWhiteSpace($status)) {
                    $activePtt.Status = $status.ToUpper()
                }

                $startDate = Convert-ToDateTime -Value $start

                if ($null -ne $startDate) {
                    $activePtt.Start = $startDate
                }
            }
        }


        # ====================================================
        # TEXTE D'UN MESSAGE
        # ====================================================

        elseif (
            $inMsg -and (
                $reader.NodeType -eq [System.Xml.XmlNodeType]::Text -or
                $reader.NodeType -eq [System.Xml.XmlNodeType]::CDATA -or
                $reader.NodeType -eq [System.Xml.XmlNodeType]::SignificantWhitespace
            )
        ) {

            $msgText.Append($reader.Value) | Out-Null
        }


        # ====================================================
        # ELEMENT FERMANT
        # ====================================================

        elseif ($reader.NodeType -eq [System.Xml.XmlNodeType]::EndElement) {

            # ------------------------------------------------
            # Fin du message
            # ------------------------------------------------

            if (
                $reader.Name -eq "msg" -and
                $inMsg -and
                $null -ne $activePtt
            ) {

                $text = $msgText.ToString()

                if ($text -match $PttPressedRegex) {

                    # Une tentative ne compte qu'une seule fois
                    if (-not $activePtt.Pressed) {

                        $activePtt.Pressed = $true

                        if ($null -ne $msgTime) {
                            $activePtt.PressedTime = $msgTime
                        }
                    }
                }

                $inMsg = $false
                $msgText.Clear() | Out-Null
                $msgTime = $null
            }


            # ------------------------------------------------
            # Fin du keyword Use Ptt Release
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "kw" -and
                $null -ne $activePtt -and
                $reader.Depth -eq $activePtt.Depth
            ) {

                # Si pas de date start, on prend l'heure du PTT
                if (
                    $null -eq $activePtt.Start -and
                    $null -ne $activePtt.PressedTime
                ) {
                    $activePtt.Start = $activePtt.PressedTime
                }

                # --------------------------------------------
                # Sauvegarde de la tentative
                # --------------------------------------------

                $attempt = [PSCustomObject]@{
                    Driver      = $activePtt.Driver
                    Start       = $activePtt.Start
                    Status      = $activePtt.Status
                    Pressed     = $activePtt.Pressed
                    PressedTime = $activePtt.PressedTime
                }

                [void]$attempts[$activePtt.Driver].Add($attempt)


                # --------------------------------------------
                # PTT réellement pris
                # --------------------------------------------

                if ($activePtt.Pressed) {

                    $pttTotals[$activePtt.Driver]++

                    $dateForCount = $activePtt.PressedTime

                    if ($null -eq $dateForCount) {
                        $dateForCount = $activePtt.Start
                    }

                    if ($null -ne $dateForCount) {

                        $day = $dateForCount.ToString("yyyy-MM-dd")

                        if (-not $daily.ContainsKey($day)) {

                            $daily[$day] = @{
                                driver1 = 0
                                driver2 = 0
                                driver3 = 0
                                driver4 = 0
                                driver5 = 0
                                driver6 = 0
                            }
                        }

                        $daily[$day][$activePtt.Driver]++
                    }
                }


                # --------------------------------------------
                # FAIL
                # --------------------------------------------

                if ($activePtt.Status -eq "FAIL") {
                    $failTotals[$activePtt.Driver]++
                }


                $activePtt = $null
            }
        }
    }
}
catch {

    Write-Host ""
    Write-Host "Erreur pendant la lecture du XML :"
    Write-Host $_.Exception.Message

    exit 1
}
finally {

    if ($null -ne $reader) {
        $reader.Close()
    }
}


# ============================================================
# TOTAL DES PTT
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "          NOMBRE TOTAL DE PTT PRIS"
Write-Host "=========================================="
Write-Host ""

$totalPtt = 0
$totalRows = @()

foreach ($i in 1..6) {

    $driver = "driver$i"
    $count = $pttTotals[$driver]

    $totalPtt += $count

    $totalRows += [PSCustomObject]@{
        Driver = $driver
        PTT    = $count
    }
}

$totalRows | Format-Table -AutoSize

Write-Host "------------------------------------------"
Write-Host "TOTAL PTT : $totalPtt"
Write-Host ""


# ============================================================
# PTT PAR JOUR
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "             PTT PRIS PAR JOUR"
Write-Host "=========================================="
Write-Host ""

$dailyRows = @()

foreach ($day in ($daily.Keys | Sort-Object)) {

    $dayTotal = 0

    foreach ($i in 1..6) {
        $driver = "driver$i"
        $dayTotal += $daily[$day][$driver]
    }

    $dailyRows += [PSCustomObject]@{
        Date    = $day
        driver1 = $daily[$day]["driver1"]
        driver2 = $daily[$day]["driver2"]
        driver3 = $daily[$day]["driver3"]
        driver4 = $daily[$day]["driver4"]
        driver5 = $daily[$day]["driver5"]
        driver6 = $daily[$day]["driver6"]
        TOTAL   = $dayTotal
    }
}

$dailyRows | Format-Table -AutoSize


# ============================================================
# CREATION DES PLAGES DE FAIL
#
# Une plage commence au premier FAIL.
# Elle se termine lorsque le même driver retrouve un PASS.
# ============================================================

$failRanges = New-Object System.Collections.ArrayList

foreach ($i in 1..6) {

    $driver = "driver$i"

    $driverAttempts = $attempts[$driver] |
        Where-Object { $null -ne $_.Start } |
        Sort-Object Start

    $currentRange = $null

    foreach ($attempt in $driverAttempts) {

        # ----------------------------------------------------
        # FAIL
        # ----------------------------------------------------

        if ($attempt.Status -eq "FAIL") {

            if ($null -eq $currentRange) {

                $currentRange = [PSCustomObject]@{
                    Driver     = $driver
                    Start      = $attempt.Start
                    LastFail   = $attempt.Start
                    FailCount  = 1
                    Recovery   = $null
                }
            }
            else {

                $currentRange.LastFail = $attempt.Start
                $currentRange.FailCount++
            }
        }


        # ----------------------------------------------------
        # Premier PASS après une série de FAIL
        # => téléphone considéré comme revenu
        # ----------------------------------------------------

        elseif (
            $attempt.Status -eq "PASS" -and
            $null -ne $currentRange
        ) {

            $currentRange.Recovery = $attempt.Start

            [void]$failRanges.Add($currentRange)

            $currentRange = $null
        }
    }


    # --------------------------------------------------------
    # FAIL encore ouvert à la fin du fichier
    # --------------------------------------------------------

    if ($null -ne $currentRange) {
        [void]$failRanges.Add($currentRange)
    }
}


# ============================================================
# FAIL PAR TELEPHONE
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "            FAIL PAR TELEPHONE"
Write-Host "=========================================="
Write-Host ""

$failSummary = @()

foreach ($i in 1..6) {

    $driver = "driver$i"

    $numberOfRanges = @(
        $failRanges |
        Where-Object { $_.Driver -eq $driver }
    ).Count

    $failSummary += [PSCustomObject]@{
        Driver      = $driver
        NombreFails = $failTotals[$driver]
        NbPlages    = $numberOfRanges
    }
}

$failSummary | Format-Table -AutoSize


# ============================================================
# DETAIL DES PLAGES DE FAIL
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "             PLAGES DE FAIL"
Write-Host "=========================================="
Write-Host ""

$rangeRows = @()

foreach ($range in $failRanges) {

    if ($null -ne $range.Recovery) {

        $recoveryText = $range.Recovery.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )

        $durationText = Format-Duration `
            -Start $range.Start `
            -End $range.Recovery
    }
    else {

        $recoveryText = "PAS DE REPRISE DANS LE XML"
        $durationText = "OUVERT"
    }

    $rangeRows += [PSCustomObject]@{
        Driver       = $range.Driver
        DebutFail    = $range.Start.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
        DernierFail  = $range.LastFail.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
        Reprise      = $recoveryText
        NombreFails  = $range.FailCount
        Duree        = $durationText
    }
}

if ($rangeRows.Count -gt 0) {
    $rangeRows | Format-Table -AutoSize
}
else {
    Write-Host "Aucune plage de FAIL trouvee."
}


# ============================================================
# EXPORT CSV OPTIONNEL
# ============================================================

if ($ExportCsv) {

    $folder = Split-Path $OutputXml -Parent

    $dailyCsv = Join-Path $folder "ptt_par_jour.csv"
    $failCsv = Join-Path $folder "ptt_fail_par_telephone.csv"
    $rangesCsv = Join-Path $folder "ptt_plages_fail.csv"

    $dailyRows |
        Export-Csv `
            -Path $dailyCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8

    $failSummary |
        Export-Csv `
            -Path $failCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8

    $rangeRows |
        Export-Csv `
            -Path $rangesCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8

    Write-Host ""
    Write-Host "CSV generes :"
    Write-Host $dailyCsv
    Write-Host $failCsv
    Write-Host $rangesCsv
}

Write-Host ""
Write-Host "Analyse terminee."