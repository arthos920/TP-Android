param (
    [Parameter(Mandatory = $true)]
    [string]$OutputXml,

    [switch]$ExportCsv,

    # Duree reelle du test : HH:MM:SS
    # Peut depasser 24h, par exemple 86:18:13
    [string]$ActualDuration = "86:18:13",

    # Duree theorique prevue du test
    [double]$PlannedHours = 120,

    # Duree moyenne d'une iteration complete
    [double]$IterationSeconds = 44
)


# ============================================================
# CONFIGURATION
# ============================================================

# Keyword Robot Framework correspondant a une tentative PTT
$PttKeywordRegex = '(?i)^\s*Use\s+Ptt\s+Release\s*$'

# Message indiquant que le PTT a reellement ete pris.
# Accepte par exemple :
#
# PTT pressed
# PTT pressed (long hold started)
#
$PttPressedRegex = '(?is)\bPTT\b.*?\bpressed\b'


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

        try {
            return [datetime]::Parse($Value)
        }
        catch {
            return $null
        }
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
        [double]$Seconds
    )

    if ($Seconds -lt 0) {
        $Seconds = 0
    }

    $span = [TimeSpan]::FromSeconds($Seconds)

    $hours = [math]::Floor(
        $span.TotalHours
    )

    return "{0}h {1}min {2}s" -f `
        $hours,
        $span.Minutes,
        $span.Seconds
}


# ============================================================
# VERIFICATION DU FICHIER
# ============================================================

if (-not (Test-Path $OutputXml)) {

    Write-Host ""
    Write-Host "Fichier introuvable : $OutputXml"
    exit 1
}

$OutputXml = (Resolve-Path $OutputXml).Path


# ============================================================
# CONVERSION DE LA DUREE REELLE
# ============================================================

if ($ActualDuration -match '^(\d+):(\d{1,2}):(\d{1,2})$') {

    $actualHours = [int]$Matches[1]
    $actualMinutes = [int]$Matches[2]
    $actualSecondsPart = [int]$Matches[3]

    $actualSeconds = `
        ($actualHours * 3600) +
        ($actualMinutes * 60) +
        $actualSecondsPart
}
else {

    Write-Host ""
    Write-Host "Format ActualDuration incorrect."
    Write-Host "Format attendu : HH:MM:SS"
    Write-Host "Exemple : 86:18:13"
    exit 1
}


$plannedSeconds = $PlannedHours * 3600


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


# Keyword PTT actuellement analyse
$activePtt = $null

# Etat de lecture d'un message <msg>
$inMsg = $false

$msgText = New-Object System.Text.StringBuilder

$msgTime = $null


# Premier et dernier timestamp observes
$firstKnownTime = $null
$lastKnownTime = $null


# ============================================================
# LECTURE DU OUTPUT.XML EN STREAMING
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "        ANALYSE ROBOT FRAMEWORK"
Write-Host "=========================================="
Write-Host ""
Write-Host "Fichier : $OutputXml"
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

        if (
            $reader.NodeType -eq
            [System.Xml.XmlNodeType]::Element
        ) {


            # ------------------------------------------------
            # KEYWORD
            # ------------------------------------------------

            if ($reader.Name -eq "kw") {

                $name = $reader.GetAttribute("name")

                $owner = $reader.GetAttribute("owner")

                $driver = Get-Driver -Owner $owner


                # Detection du keyword :
                #
                # <kw name="Use Ptt Release" owner="driverX">
                #
                if (
                    $null -eq $activePtt -and
                    $null -ne $driver -and
                    $name -match $PttKeywordRegex
                ) {

                    $activePtt = [PSCustomObject]@{

                        Driver = $driver

                        Depth = $reader.Depth

                        Start = $null

                        Status = "UNKNOWN"

                        Pressed = $false

                        PressedTime = $null
                    }
                }
            }


            # ------------------------------------------------
            # MESSAGE
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "msg" -and
                $null -ne $activePtt
            ) {

                $inMsg = $true

                $msgText.Clear() |
                    Out-Null

                $msgTime = Convert-ToDateTime `
                    -Value $reader.GetAttribute("time")
            }


            # ------------------------------------------------
            # STATUS DIRECT DU KEYWORD Use Ptt Release
            #
            # On ne prend pas le status des sous-keywords.
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "status" -and
                $null -ne $activePtt -and
                $reader.Depth -eq ($activePtt.Depth + 1)
            ) {

                $status = $reader.GetAttribute("status")

                $start = $reader.GetAttribute("start")


                if (
                    -not
                    [string]::IsNullOrWhiteSpace($status)
                ) {

                    $activePtt.Status = $status.ToUpper()
                }


                $startDate = Convert-ToDateTime `
                    -Value $start


                if ($null -ne $startDate) {

                    $activePtt.Start = $startDate
                }
            }
        }


        # ====================================================
        # TEXTE DU MESSAGE
        # ====================================================

        elseif (
            $inMsg -and
            (
                $reader.NodeType -eq
                [System.Xml.XmlNodeType]::Text -or

                $reader.NodeType -eq
                [System.Xml.XmlNodeType]::CDATA -or

                $reader.NodeType -eq
                [System.Xml.XmlNodeType]::SignificantWhitespace
            )
        ) {

            $msgText.Append(
                $reader.Value
            ) |
                Out-Null
        }


        # ====================================================
        # ELEMENT FERMANT
        # ====================================================

        elseif (
            $reader.NodeType -eq
            [System.Xml.XmlNodeType]::EndElement
        ) {


            # ------------------------------------------------
            # FIN DU MESSAGE
            # ------------------------------------------------

            if (
                $reader.Name -eq "msg" -and
                $inMsg -and
                $null -ne $activePtt
            ) {

                $text = $msgText.ToString()


                # Message confirmant une prise de PTT
                if ($text -match $PttPressedRegex) {

                    # Une tentative ne compte qu'une fois
                    if (-not $activePtt.Pressed) {

                        $activePtt.Pressed = $true


                        if ($null -ne $msgTime) {

                            $activePtt.PressedTime = $msgTime
                        }
                    }
                }


                $inMsg = $false

                $msgText.Clear() |
                    Out-Null

                $msgTime = $null
            }


            # ------------------------------------------------
            # FIN DU KEYWORD Use Ptt Release
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "kw" -and
                $null -ne $activePtt -and
                $reader.Depth -eq $activePtt.Depth
            ) {


                # Si le status ne contient pas de date,
                # on prend l'heure du message PTT.
                if (
                    $null -eq $activePtt.Start -and
                    $null -ne $activePtt.PressedTime
                ) {

                    $activePtt.Start =
                        $activePtt.PressedTime
                }


                # --------------------------------------------
                # PREMIER / DERNIER TIMESTAMP
                # --------------------------------------------

                if ($null -ne $activePtt.Start) {

                    if (
                        $null -eq $firstKnownTime -or
                        $activePtt.Start -lt $firstKnownTime
                    ) {

                        $firstKnownTime =
                            $activePtt.Start
                    }


                    if (
                        $null -eq $lastKnownTime -or
                        $activePtt.Start -gt $lastKnownTime
                    ) {

                        $lastKnownTime =
                            $activePtt.Start
                    }
                }


                # --------------------------------------------
                # SAUVEGARDE DE LA TENTATIVE
                # --------------------------------------------

                $attempt = [PSCustomObject]@{

                    Driver =
                        $activePtt.Driver

                    Start =
                        $activePtt.Start

                    Status =
                        $activePtt.Status

                    Pressed =
                        $activePtt.Pressed

                    PressedTime =
                        $activePtt.PressedTime
                }


                [void]$attempts[
                    $activePtt.Driver
                ].Add(
                    $attempt
                )


                # --------------------------------------------
                # PTT REELLEMENT PRIS
                # --------------------------------------------

                if ($activePtt.Pressed) {

                    $pttTotals[
                        $activePtt.Driver
                    ]++


                    $dateForCount =
                        $activePtt.PressedTime


                    if ($null -eq $dateForCount) {

                        $dateForCount =
                            $activePtt.Start
                    }


                    if ($null -ne $dateForCount) {

                        $day =
                            $dateForCount.ToString(
                                "yyyy-MM-dd"
                            )


                        if (
                            -not
                            $daily.ContainsKey($day)
                        ) {

                            $daily[$day] = @{

                                driver1 = 0

                                driver2 = 0

                                driver3 = 0

                                driver4 = 0

                                driver5 = 0

                                driver6 = 0
                            }
                        }


                        $daily[$day][
                            $activePtt.Driver
                        ]++
                    }
                }


                # --------------------------------------------
                # FAIL DU KEYWORD
                # --------------------------------------------

                if (
                    $activePtt.Status -eq "FAIL"
                ) {

                    $failTotals[
                        $activePtt.Driver
                    ]++
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
# TOTAL PTT
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "          NOMBRE TOTAL DE PTT"
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

        PTT = $count
    }
}


$totalRows |
    Format-Table -AutoSize


Write-Host "------------------------------------------"
Write-Host "TOTAL PTT : $totalPtt"
Write-Host ""


# ============================================================
# PTT PAR JOUR
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "             PTT PAR JOUR"
Write-Host "=========================================="
Write-Host ""


$dailyRows = @()


foreach (
    $day in
    ($daily.Keys | Sort-Object)
) {

    $dayTotal = 0


    foreach ($i in 1..6) {

        $driver = "driver$i"

        $dayTotal +=
            $daily[$day][$driver]
    }


    $dailyRows += [PSCustomObject]@{

        Date = $day

        driver1 =
            $daily[$day]["driver1"]

        driver2 =
            $daily[$day]["driver2"]

        driver3 =
            $daily[$day]["driver3"]

        driver4 =
            $daily[$day]["driver4"]

        driver5 =
            $daily[$day]["driver5"]

        driver6 =
            $daily[$day]["driver6"]

        TOTAL =
            $dayTotal
    }
}


if ($dailyRows.Count -gt 0) {

    $dailyRows |
        Format-Table -AutoSize
}
else {

    Write-Host "Aucun PTT confirme trouve."
}


# ============================================================
# CONSTRUCTION DES PLAGES DE FAIL
#
# Une plage commence au premier FAIL consecutif.
#
# Elle se termine lorsque le meme driver obtient
# a nouveau un PASS.
# ============================================================

$failRanges =
    New-Object System.Collections.ArrayList


foreach ($i in 1..6) {

    $driver = "driver$i"


    $driverAttempts =
        $attempts[$driver] |
        Where-Object {
            $null -ne $_.Start
        } |
        Sort-Object Start


    $currentRange = $null


    foreach (
        $attempt in
        $driverAttempts
    ) {


        # ----------------------------------------------------
        # FAIL
        # ----------------------------------------------------

        if (
            $attempt.Status -eq "FAIL"
        ) {

            if (
                $null -eq $currentRange
            ) {

                $currentRange =
                    [PSCustomObject]@{

                        Driver =
                            $driver

                        Start =
                            $attempt.Start

                        LastFail =
                            $attempt.Start

                        FailCount =
                            1

                        Recovery =
                            $null
                    }
            }
            else {

                $currentRange.LastFail =
                    $attempt.Start

                $currentRange.FailCount++
            }
        }


        # ----------------------------------------------------
        # RETOUR AU PASS
        # ----------------------------------------------------

        elseif (
            $attempt.Status -eq "PASS" -and
            $null -ne $currentRange
        ) {

            $currentRange.Recovery =
                $attempt.Start


            [void]$failRanges.Add(
                $currentRange
            )


            $currentRange = $null
        }
    }


    # --------------------------------------------------------
    # PLAGE TOUJOURS OUVERTE A LA FIN DU XML
    # --------------------------------------------------------

    if (
        $null -ne $currentRange
    ) {

        [void]$failRanges.Add(
            $currentRange
        )
    }
}


# ============================================================
# FAIL PAR TELEPHONE
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "           FAIL PAR TELEPHONE"
Write-Host "=========================================="
Write-Host ""


$failSummary = @()


foreach ($i in 1..6) {

    $driver = "driver$i"


    $driverRanges = @(
        $failRanges |
        Where-Object {
            $_.Driver -eq $driver
        }
    )


    $failSummary += [PSCustomObject]@{

        Driver =
            $driver

        NombreFails =
            $failTotals[$driver]

        NombrePlages =
            $driverRanges.Count
    }
}


$failSummary |
    Format-Table -AutoSize


# ============================================================
# DETAIL DES PLAGES DE FAIL
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "            PLAGES DE FAIL"
Write-Host "=========================================="
Write-Host ""


$rangeRows = @()


foreach ($range in $failRanges) {


    if ($null -ne $range.Recovery) {

        $rangeEnd =
            $range.Recovery

        $recoveryText =
            $range.Recovery.ToString(
                "yyyy-MM-dd HH:mm:ss"
            )
    }
    elseif (
        $null -ne $lastKnownTime
    ) {

        $rangeEnd =
            $lastKnownTime

        $recoveryText =
            "PAS DE REPRISE AVANT FIN XML"
    }
    else {

        $rangeEnd =
            $range.LastFail

        $recoveryText =
            "INCONNU"
    }


    $durationSeconds = 0


    if (
        $rangeEnd -gt
        $range.Start
    ) {

        $durationSeconds =
            (
                $rangeEnd -
                $range.Start
            ).TotalSeconds
    }


    $rangeRows += [PSCustomObject]@{

        Driver =
            $range.Driver

        DebutFail =
            $range.Start.ToString(
                "yyyy-MM-dd HH:mm:ss"
            )

        DernierFail =
            $range.LastFail.ToString(
                "yyyy-MM-dd HH:mm:ss"
            )

        Reprise =
            $recoveryText

        NombreFails =
            $range.FailCount

        Duree =
            Format-Duration `
                -Seconds $durationSeconds
    }
}


if ($rangeRows.Count -gt 0) {

    $rangeRows |
        Format-Table -AutoSize
}
else {

    Write-Host "Aucune plage de FAIL trouvee."
}


# ============================================================
# TEMPS EN FAIL / DISPONIBILITE ESTIMEE
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "      TEMPS EN FAIL PAR TELEPHONE"
Write-Host "=========================================="
Write-Host ""


$availabilityRows = @()


foreach ($i in 1..6) {

    $driver = "driver$i"


    $driverRanges = @(
        $failRanges |
        Where-Object {
            $_.Driver -eq $driver
        }
    )


    $totalFailSeconds = 0

    $longestFailSeconds = 0


    foreach ($range in $driverRanges) {


        if (
            $null -ne
            $range.Recovery
        ) {

            $rangeEnd =
                $range.Recovery
        }
        elseif (
            $null -ne
            $lastKnownTime
        ) {

            $rangeEnd =
                $lastKnownTime
        }
        else {

            continue
        }


        if (
            $rangeEnd -gt
            $range.Start
        ) {

            $seconds =
                (
                    $rangeEnd -
                    $range.Start
                ).TotalSeconds


            $totalFailSeconds +=
                $seconds


            if (
                $seconds -gt
                $longestFailSeconds
            ) {

                $longestFailSeconds =
                    $seconds
            }
        }
    }


    if (
        $actualSeconds -gt 0
    ) {

        $failPercent =
            (
                $totalFailSeconds /
                $actualSeconds
            ) * 100
    }
    else {

        $failPercent = 0
    }


    if ($failPercent -gt 100) {
        $failPercent = 100
    }


    $availabilityPercent =
        100 - $failPercent


    $availabilityRows +=
        [PSCustomObject]@{

            Driver =
                $driver

            Nb_Plages_FAIL =
                $driverRanges.Count

            Temps_en_FAIL =
                Format-Duration `
                    -Seconds $totalFailSeconds

            Plus_Long_FAIL =
                Format-Duration `
                    -Seconds $longestFailSeconds

            Indispo_Estimee =
                "{0:N2} %" -f $failPercent

            Dispo_Estimee =
                "{0:N2} %" -f $availabilityPercent
        }
}


$availabilityRows |
    Format-Table -AutoSize


# ============================================================
# KPI ENDURANCE GLOBAL
# ============================================================

$expectedIterationsAtStop =
    [math]::Floor(
        $actualSeconds /
        $IterationSeconds
    )


$targetIterations =
    [math]::Floor(
        $plannedSeconds /
        $IterationSeconds
    )


# 6 telephones :
# 1 PTT par telephone et par iteration
$expectedPttAtStop =
    $expectedIterationsAtStop * 6


$targetPtt =
    $targetIterations * 6


# ------------------------------------------------------------
# Progression temps
# ------------------------------------------------------------

if (
    $plannedSeconds -gt 0
) {

    $timeProgress =
        (
            $actualSeconds /
            $plannedSeconds
        ) * 100
}
else {

    $timeProgress = 0
}


# ------------------------------------------------------------
# PTT reels / PTT attendus au moment de l'arret
# ------------------------------------------------------------

if (
    $expectedPttAtStop -gt 0
) {

    $pttEfficiency =
        (
            $totalPtt /
            $expectedPttAtStop
        ) * 100
}
else {

    $pttEfficiency = 0
}


# ------------------------------------------------------------
# Progression vers objectif final
# ------------------------------------------------------------

if (
    $targetPtt -gt 0
) {

    $finalProgress =
        (
            $totalPtt /
            $targetPtt
        ) * 100
}
else {

    $finalProgress = 0
}


# ------------------------------------------------------------
# Debit reel
# ------------------------------------------------------------

$actualHoursDecimal =
    $actualSeconds / 3600


if (
    $actualHoursDecimal -gt 0
) {

    $actualPttPerHour =
        $totalPtt /
        $actualHoursDecimal
}
else {

    $actualPttPerHour = 0
}


# ------------------------------------------------------------
# Debit theorique
# ------------------------------------------------------------

$theoreticalPttPerHour =
    (
        3600 /
        $IterationSeconds
    ) * 6


# ------------------------------------------------------------
# Projection 120h avec debit reel
# ------------------------------------------------------------

$projectedPtt120h =
    [math]::Round(
        $actualPttPerHour *
        $PlannedHours
    )


# ------------------------------------------------------------
# PTT manquants
# ------------------------------------------------------------

$missingDuringRun =
    $expectedPttAtStop -
    $totalPtt


if (
    $missingDuringRun -lt 0
) {

    $missingDuringRun = 0
}


$missingDueToEarlyStop =
    $targetPtt -
    $expectedPttAtStop


if (
    $missingDueToEarlyStop -lt 0
) {

    $missingDueToEarlyStop = 0
}


$missingToFinalTarget =
    $targetPtt -
    $totalPtt


if (
    $missingToFinalTarget -lt 0
) {

    $missingToFinalTarget = 0
}


# ------------------------------------------------------------
# Temps non execute
# ------------------------------------------------------------

$remainingSeconds =
    $plannedSeconds -
    $actualSeconds


if (
    $remainingSeconds -lt 0
) {

    $remainingSeconds = 0
}


# ============================================================
# AFFICHAGE KPI GLOBAL
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "             KPI ENDURANCE"
Write-Host "=========================================="
Write-Host ""

Write-Host "Duree prevue                  : $PlannedHours h"

Write-Host "Duree executee                : $ActualDuration"

Write-Host (
    "Temps non execute              : {0}" -f
    (
        Format-Duration `
            -Seconds $remainingSeconds
    )
)

Write-Host ""

Write-Host (
    "Progression temporelle         : {0:N2} %" -f
    $timeProgress
)

Write-Host ""

Write-Host "Duree moyenne iteration       : $IterationSeconds s"

Write-Host "Iterations attendues a l'arret: $expectedIterationsAtStop"

Write-Host "Iterations prevues a 120h     : $targetIterations"

Write-Host ""

Write-Host "PTT reels confirmes           : $totalPtt"

Write-Host "PTT attendus a l'arret        : $expectedPttAtStop"

Write-Host "PTT objectif a 120h           : $targetPtt"

Write-Host ""

Write-Host (
    "PTT reels / attendus a l'arret: {0:N2} %" -f
    $pttEfficiency
)

Write-Host (
    "Progression objectif final    : {0:N2} %" -f
    $finalProgress
)

Write-Host ""

Write-Host (
    "Debit theorique               : {0:N2} PTT/h" -f
    $theoreticalPttPerHour
)

Write-Host (
    "Debit reel                    : {0:N2} PTT/h" -f
    $actualPttPerHour
)

Write-Host ""

Write-Host "PTT manquants pendant le run  : $missingDuringRun"

Write-Host "PTT non realises arret anticipe: $missingDueToEarlyStop"

Write-Host "PTT manquants objectif 120h   : $missingToFinalTarget"

Write-Host ""

Write-Host "Projection PTT a 120h au debit reel : $projectedPtt120h"


# ============================================================
# DUREE OBSERVEE DANS LE XML
# ============================================================

if (
    $null -ne $firstKnownTime -and
    $null -ne $lastKnownTime
) {

    $xmlDurationSeconds =
        (
            $lastKnownTime -
            $firstKnownTime
        ).TotalSeconds


    Write-Host ""

    Write-Host (
        "Premier PTT analyse           : {0}" -f
        $firstKnownTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )

    Write-Host (
        "Dernier PTT analyse           : {0}" -f
        $lastKnownTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )

    Write-Host (
        "Duree observee dans le XML    : {0}" -f
        (
            Format-Duration `
                -Seconds $xmlDurationSeconds
        )
    )
}


# ============================================================
# KPI COMPLET PAR TELEPHONE
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "        KPI COMPLET PAR TELEPHONE"
Write-Host "=========================================="
Write-Host ""


$phoneKpi = @()


foreach ($i in 1..6) {

    $driver = "driver$i"


    $ptt =
        $pttTotals[$driver]


    $attemptCount =
        @(
            $attempts[$driver]
        ).Count


    $failCount =
        $failTotals[$driver]


    # --------------------------------------------------------
    # Taux de PTT confirme par rapport aux tentatives
    # --------------------------------------------------------

    if (
        $attemptCount -gt 0
    ) {

        $pressRate =
            (
                $ptt /
                $attemptCount
            ) * 100
    }
    else {

        $pressRate = 0
    }


    # --------------------------------------------------------
    # Plages de FAIL
    # --------------------------------------------------------

    $driverRanges = @(
        $failRanges |
        Where-Object {
            $_.Driver -eq $driver
        }
    )


    $totalFailSeconds = 0

    $longestFailSeconds = 0


    foreach (
        $range in
        $driverRanges
    ) {


        if (
            $null -ne
            $range.Recovery
        ) {

            $rangeEnd =
                $range.Recovery
        }
        elseif (
            $null -ne
            $lastKnownTime
        ) {

            $rangeEnd =
                $lastKnownTime
        }
        else {

            continue
        }


        if (
            $rangeEnd -gt
            $range.Start
        ) {

            $seconds =
                (
                    $rangeEnd -
                    $range.Start
                ).TotalSeconds


            $totalFailSeconds +=
                $seconds


            if (
                $seconds -gt
                $longestFailSeconds
            ) {

                $longestFailSeconds =
                    $seconds
            }
        }
    }


    # --------------------------------------------------------
    # Pourcentage du temps en FAIL
    # --------------------------------------------------------

    if (
        $actualSeconds -gt 0
    ) {

        $failPercent =
            (
                $totalFailSeconds /
                $actualSeconds
            ) * 100
    }
    else {

        $failPercent = 0
    }


    if (
        $failPercent -gt 100
    ) {

        $failPercent = 100
    }


    $availabilityPercent =
        100 - $failPercent


    # --------------------------------------------------------
    # Ecart a la reference theorique
    # --------------------------------------------------------

    $difference =
        $ptt -
        $expectedIterationsAtStop


    $missingPtt =
        $expectedIterationsAtStop -
        $ptt


    if (
        $missingPtt -lt 0
    ) {

        $missingPtt = 0
    }


    # --------------------------------------------------------
    # KPI TELEPHONE
    # --------------------------------------------------------

    $phoneKpi +=
        [PSCustomObject]@{

            Driver =
                $driver

            Tentatives =
                $attemptCount

            PTT =
                $ptt

            FAIL =
                $failCount

            Plages_FAIL =
                $driverRanges.Count

            Temps_FAIL =
                Format-Duration `
                    -Seconds $totalFailSeconds

            Plus_Long_FAIL =
                Format-Duration `
                    -Seconds $longestFailSeconds

            Indispo_Estimee =
                "{0:N2} %" -f $failPercent

            Dispo_Estimee =
                "{0:N2} %" -f $availabilityPercent

            Taux_PTT =
                "{0:N2} %" -f $pressRate

            PTT_Attendus =
                $expectedIterationsAtStop

            PTT_Manquants =
                $missingPtt

            Ecart =
                $difference

            Objectif_120h =
                $targetIterations
        }
}


$phoneKpi |
    Format-Table -AutoSize


# ============================================================
# EXPORT CSV OPTIONNEL
# ============================================================

if ($ExportCsv) {

    $folder =
        Split-Path `
            $OutputXml `
            -Parent


    $totalCsv =
        Join-Path `
            $folder `
            "ptt_total.csv"


    $dailyCsv =
        Join-Path `
            $folder `
            "ptt_par_jour.csv"


    $failCsv =
        Join-Path `
            $folder `
            "ptt_fail_par_telephone.csv"


    $rangesCsv =
        Join-Path `
            $folder `
            "ptt_plages_fail.csv"


    $availabilityCsv =
        Join-Path `
            $folder `
            "ptt_disponibilite.csv"


    $kpiCsv =
        Join-Path `
            $folder `
            "ptt_kpi_complet.csv"


    $totalRows |
        Export-Csv `
            -Path $totalCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8


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


    $availabilityRows |
        Export-Csv `
            -Path $availabilityCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8


    $phoneKpi |
        Export-Csv `
            -Path $kpiCsv `
            -Delimiter ";" `
            -NoTypeInformation `
            -Encoding UTF8


    Write-Host ""
    Write-Host "=========================================="
    Write-Host "              EXPORT CSV"
    Write-Host "=========================================="
    Write-Host ""

    Write-Host $totalCsv
    Write-Host $dailyCsv
    Write-Host $failCsv
    Write-Host $rangesCsv
    Write-Host $availabilityCsv
    Write-Host $kpiCsv
}


Write-Host ""
Write-Host "=========================================="
Write-Host "           ANALYSE TERMINEE"
Write-Host "=========================================="
Write-Host ""