param (
    [Parameter(Mandatory = $true)]
    [string]$OutputXml,

    [switch]$ExportCsv,

    # Duree reelle du run au format HH:MM:SS
    # Peut depasser 24h
    [string]$ActualDuration = "86:18:13",

    # Duree initialement prevue
    [double]$PlannedHours = 120,

    # Duree nominale d'une iteration lorsque tout fonctionne
    [double]$IterationSeconds = 44
)


# ============================================================
# CONFIGURATION
# ============================================================

# Keyword PTT
$PttKeywordRegex = '(?i)^\s*Use\s+Ptt\s+Release\s*$'

# Message confirmant qu'un PTT a reellement ete pris
# Exemple :
# PTT pressed (long hold started)
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

    $attempts[$driver] =
        New-Object System.Collections.ArrayList

    $pttTotals[$driver] = 0

    $failTotals[$driver] = 0
}


# Keyword PTT actuellement analyse
$activePtt = $null

# Lecture des messages
$inMsg = $false

$msgText =
    New-Object System.Text.StringBuilder

$msgTime = $null


# ------------------------------------------------------------
# Timestamps des TENTATIVES
# Base : <status start="...">
# ------------------------------------------------------------

$firstAttemptTime = $null
$lastAttemptTime = $null


# ------------------------------------------------------------
# Timestamps des PTT REELLEMENT CONFIRMES
# Base : <msg time="...">PTT pressed...</msg>
# ------------------------------------------------------------

$firstPttTime = $null
$lastPttTime = $null


# ============================================================
# LECTURE OUTPUT.XML
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "        ANALYSE ROBOT FRAMEWORK"
Write-Host "=========================================="
Write-Host ""

Write-Host "Fichier : $OutputXml"
Write-Host ""


$settings =
    New-Object System.Xml.XmlReaderSettings

$settings.IgnoreWhitespace = $false

$settings.DtdProcessing =
    [System.Xml.DtdProcessing]::Ignore


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

                $name =
                    $reader.GetAttribute("name")

                $owner =
                    $reader.GetAttribute("owner")

                $driver =
                    Get-Driver -Owner $owner


                # Detection :
                #
                # <kw name="Use Ptt Release"
                #     owner="driverX">
                #
                if (
                    $null -eq $activePtt -and
                    $null -ne $driver -and
                    $name -match $PttKeywordRegex
                ) {

                    $activePtt =
                        [PSCustomObject]@{

                            Driver = $driver

                            Depth =
                                $reader.Depth

                            Start = $null

                            Status =
                                "UNKNOWN"

                            Pressed =
                                $false

                            PressedTime =
                                $null
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


                $msgTime =
                    Convert-ToDateTime `
                        -Value $reader.GetAttribute("time")
            }


            # ------------------------------------------------
            # STATUS DIRECT DU Use Ptt Release
            #
            # Important :
            # on ne prend pas le status d'un sous-keyword.
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "status" -and
                $null -ne $activePtt -and
                $reader.Depth -eq ($activePtt.Depth + 1)
            ) {

                $status =
                    $reader.GetAttribute("status")

                $start =
                    $reader.GetAttribute("start")


                if (
                    -not
                    [string]::IsNullOrWhiteSpace($status)
                ) {

                    $activePtt.Status =
                        $status.ToUpper()
                }


                $startDate =
                    Convert-ToDateTime `
                        -Value $start


                if ($null -ne $startDate) {

                    $activePtt.Start =
                        $startDate
                }
            }
        }


        # ====================================================
        # TEXTE D'UN MESSAGE
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

                $text =
                    $msgText.ToString()


                if (
                    $text -match $PttPressedRegex
                ) {

                    # Une tentative ne doit compter
                    # qu'un seul PTT.
                    if (
                        -not $activePtt.Pressed
                    ) {

                        $activePtt.Pressed =
                            $true


                        # IMPORTANT :
                        # timestamp directement issu du
                        # <msg time="...">
                        if (
                            $null -ne $msgTime
                        ) {

                            $activePtt.PressedTime =
                                $msgTime
                        }
                    }
                }


                $inMsg = $false

                $msgText.Clear() |
                    Out-Null

                $msgTime = $null
            }


            # ------------------------------------------------
            # FIN DU Use Ptt Release
            # ------------------------------------------------

            elseif (
                $reader.Name -eq "kw" -and
                $null -ne $activePtt -and
                $reader.Depth -eq $activePtt.Depth
            ) {


                # Si aucun start n'est disponible,
                # fallback sur l'heure du message PTT.
                if (
                    $null -eq $activePtt.Start -and
                    $null -ne $activePtt.PressedTime
                ) {

                    $activePtt.Start =
                        $activePtt.PressedTime
                }


                # =================================================
                # PREMIERE / DERNIERE TENTATIVE
                # =================================================

                if (
                    $null -ne $activePtt.Start
                ) {

                    if (
                        $null -eq $firstAttemptTime -or
                        $activePtt.Start -lt $firstAttemptTime
                    ) {

                        $firstAttemptTime =
                            $activePtt.Start
                    }


                    if (
                        $null -eq $lastAttemptTime -or
                        $activePtt.Start -gt $lastAttemptTime
                    ) {

                        $lastAttemptTime =
                            $activePtt.Start
                    }
                }


                # =================================================
                # SAUVEGARDE DE LA TENTATIVE
                # =================================================

                $attempt =
                    [PSCustomObject]@{

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


                # =================================================
                # PTT REELLEMENT CONFIRME
                # =================================================

                if (
                    $activePtt.Pressed
                ) {

                    $pttTotals[
                        $activePtt.Driver
                    ]++


                    # Priorite absolue au timestamp du :
                    #
                    # <msg time="...">
                    # PTT pressed...
                    #
                    $dateForCount =
                        $activePtt.PressedTime


                    # Fallback uniquement si le <msg>
                    # n'a pas de timestamp.
                    if (
                        $null -eq $dateForCount
                    ) {

                        $dateForCount =
                            $activePtt.Start
                    }


                    # ---------------------------------------------
                    # Premier et dernier PTT CONFIRMES
                    # ---------------------------------------------

                    if (
                        $null -ne $dateForCount
                    ) {

                        if (
                            $null -eq $firstPttTime -or
                            $dateForCount -lt $firstPttTime
                        ) {

                            $firstPttTime =
                                $dateForCount
                        }


                        if (
                            $null -eq $lastPttTime -or
                            $dateForCount -gt $lastPttTime
                        ) {

                            $lastPttTime =
                                $dateForCount
                        }


                        # -----------------------------------------
                        # PTT PAR JOUR
                        # -----------------------------------------

                        $day =
                            $dateForCount.ToString(
                                "yyyy-MM-dd"
                            )


                        if (
                            -not $daily.ContainsKey($day)
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


                # =================================================
                # FAIL
                # =================================================

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

    if (
        $null -ne $reader
    ) {

        $reader.Close()
    }
}


# ============================================================
# TOTAL PTT CONFIRMES
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

    $count =
        $pttTotals[$driver]


    $totalPtt +=
        $count


    $totalRows +=
        [PSCustomObject]@{

            Driver =
                $driver

            PTT =
                $count
        }
}


$totalRows |
    Format-Table -AutoSize


Write-Host "------------------------------------------"
Write-Host "TOTAL PTT : $totalPtt"


# ============================================================
# PTT PAR JOUR
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "              PTT PAR JOUR"
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


    $dailyRows +=
        [PSCustomObject]@{

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


if (
    $dailyRows.Count -gt 0
) {

    $dailyRows |
        Format-Table -AutoSize
}
else {

    Write-Host "Aucun PTT confirme trouve."
}


# ============================================================
# CONSTRUCTION DES PLAGES DE FAIL
#
# Une plage commence au premier FAIL.
# Elle se termine au premier PASS suivant.
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
        $attempt in $driverAttempts
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
        # PREMIER PASS APRES LE FAIL
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
    # PLAGE TOUJOURS OUVERTE A LA FIN
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


    $failSummary +=
        [PSCustomObject]@{

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
Write-Host "             PLAGES DE FAIL"
Write-Host "=========================================="
Write-Host ""


$rangeRows = @()


foreach (
    $range in $failRanges
) {


    if (
        $null -ne $range.Recovery
    ) {

        $rangeEnd =
            $range.Recovery


        $recoveryText =
            $range.Recovery.ToString(
                "yyyy-MM-dd HH:mm:ss"
            )
    }
    elseif (
        $null -ne $lastAttemptTime
    ) {

        $rangeEnd =
            $lastAttemptTime


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


    $rangeRows +=
        [PSCustomObject]@{

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


if (
    $rangeRows.Count -gt 0
) {

    $rangeRows |
        Format-Table -AutoSize
}
else {

    Write-Host "Aucune plage de FAIL trouvee."
}


# ============================================================
# TEMPS PASS / FAIL PAR TELEPHONE
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "       TEMPS PASS / FAIL PAR TELEPHONE"
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


    foreach (
        $range in $driverRanges
    ) {


        if (
            $null -ne $range.Recovery
        ) {

            $rangeEnd =
                $range.Recovery
        }
        elseif (
            $null -ne $lastAttemptTime
        ) {

            $rangeEnd =
                $lastAttemptTime
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
        $totalFailSeconds -gt
        $actualSeconds
    ) {

        $totalFailSeconds =
            $actualSeconds
    }


    $totalPassSeconds =
        $actualSeconds -
        $totalFailSeconds


    if (
        $totalPassSeconds -lt 0
    ) {

        $totalPassSeconds = 0
    }


    if (
        $actualSeconds -gt 0
    ) {

        $failPercent =
            (
                $totalFailSeconds /
                $actualSeconds
            ) * 100


        $passPercent =
            (
                $totalPassSeconds /
                $actualSeconds
            ) * 100
    }
    else {

        $failPercent = 0

        $passPercent = 0
    }


    $availabilityRows +=
        [PSCustomObject]@{

            Driver =
                $driver

            Nb_Plages_FAIL =
                $driverRanges.Count

            Temps_FAIL =
                Format-Duration `
                    -Seconds $totalFailSeconds

            Temps_PASS =
                Format-Duration `
                    -Seconds $totalPassSeconds

            Plus_Long_FAIL =
                Format-Duration `
                    -Seconds $longestFailSeconds

            FAIL_Pct =
                "{0:N2} %" -f $failPercent

            PASS_Pct =
                "{0:N2} %" -f $passPercent
        }
}


$availabilityRows |
    Format-Table -AutoSize


# ============================================================
# KPI ENDURANCE
# ============================================================

$attemptCounts = @()


foreach ($i in 1..6) {

    $driver = "driver$i"

    $attemptCounts +=
        @(
            $attempts[$driver]
        ).Count
}


$totalAttempts =
    (
        $attemptCounts |
        Measure-Object -Sum
    ).Sum


$totalFails = 0


foreach ($i in 1..6) {

    $driver = "driver$i"

    $totalFails +=
        $failTotals[$driver]
}


# Tentatives n'etant ni un PTT confirme,
# ni un status FAIL.
$unknownAttempts =
    $totalAttempts -
    $totalPtt -
    $totalFails


if (
    $unknownAttempts -lt 0
) {

    $unknownAttempts = 0
}


# ------------------------------------------------------------
# ITERATIONS REELLES
# ------------------------------------------------------------

$uniqueAttemptCounts = @(
    $attemptCounts |
    Sort-Object -Unique
)


$actualIterations = $null

$iterationsAreConsistent = $false


if (
    $uniqueAttemptCounts.Count -eq 1
) {

    $actualIterations =
        $uniqueAttemptCounts[0]

    $iterationsAreConsistent =
        $true
}


# ------------------------------------------------------------
# TAUX GLOBAL
# ------------------------------------------------------------

if (
    $totalAttempts -gt 0
) {

    $globalSuccessRate =
        (
            $totalPtt /
            $totalAttempts
        ) * 100


    $globalFailRate =
        (
            $totalFails /
            $totalAttempts
        ) * 100
}
else {

    $globalSuccessRate = 0

    $globalFailRate = 0
}


# ------------------------------------------------------------
# DUREE MOYENNE REELLE D'UNE ITERATION
# ------------------------------------------------------------

$realIterationSeconds = $null


if (
    $iterationsAreConsistent -and
    $actualIterations -gt 0
) {

    $realIterationSeconds =
        (
            $actualSeconds /
            $actualIterations
        )
}


# ------------------------------------------------------------
# PROGRESSION TEMPORELLE
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


$remainingSeconds =
    $plannedSeconds -
    $actualSeconds


if (
    $remainingSeconds -lt 0
) {

    $remainingSeconds = 0
}


# ------------------------------------------------------------
# REFERENCE NOMINALE 120H
# ------------------------------------------------------------

$nominalIterations120h =
    [math]::Floor(
        $plannedSeconds /
        $IterationSeconds
    )


$nominalPtt120h =
    $nominalIterations120h *
    6


# ------------------------------------------------------------
# DEBIT REEL
# ------------------------------------------------------------

$actualHoursDecimal =
    $actualSeconds /
    3600


if (
    $actualHoursDecimal -gt 0
) {

    $actualAttemptsPerHour =
        $totalAttempts /
        $actualHoursDecimal


    $actualSuccessfulPttPerHour =
        $totalPtt /
        $actualHoursDecimal
}
else {

    $actualAttemptsPerHour = 0

    $actualSuccessfulPttPerHour = 0
}


# ------------------------------------------------------------
# PROJECTION 120H
# ------------------------------------------------------------

$projectedAttempts120h =
    [math]::Round(
        $actualAttemptsPerHour *
        $PlannedHours
    )


$projectedSuccessfulPtt120h =
    [math]::Round(
        $actualSuccessfulPttPerHour *
        $PlannedHours
    )


# ============================================================
# AFFICHAGE KPI
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "             KPI ENDURANCE"
Write-Host "=========================================="
Write-Host ""


Write-Host "Duree prevue                     : $PlannedHours h"

Write-Host "Duree executee                   : $ActualDuration"

Write-Host (
    "Temps non execute                 : {0}" -f
    (
        Format-Duration `
            -Seconds $remainingSeconds
    )
)

Write-Host (
    "Progression temporelle            : {0:N2} %" -f
    $timeProgress
)


Write-Host ""


if (
    $iterationsAreConsistent
) {

    Write-Host "Iterations REELLES               : $actualIterations"

    Write-Host (
        "Duree moyenne REELLE / iteration : {0:N2} s" -f
        $realIterationSeconds
    )
}
else {

    Write-Host "Iterations REELLES               : INCOHERENCE ENTRE DRIVERS"

    for (
        $i = 1;
        $i -le 6;
        $i++
    ) {

        Write-Host (
            "driver{0} : {1} tentatives" -f
            $i,
            $attemptCounts[$i - 1]
        )
    }
}


Write-Host "Duree nominale / iteration       : $IterationSeconds s"

Write-Host ""

Write-Host "Tentatives PTT reelles           : $totalAttempts"

Write-Host "PTT confirmes                    : $totalPtt"

Write-Host "PTT en FAIL                      : $totalFails"

Write-Host "Tentatives UNKNOWN               : $unknownAttempts"

Write-Host ""

Write-Host (
    "Taux global de succes             : {0:N2} %" -f
    $globalSuccessRate
)

Write-Host (
    "Taux global de FAIL               : {0:N2} %" -f
    $globalFailRate
)


Write-Host ""
Write-Host "------------------------------------------"
Write-Host "REFERENCE NOMINALE 120H"
Write-Host "------------------------------------------"

Write-Host "Iterations nominales a 120h      : $nominalIterations120h"

Write-Host "PTT nominaux a 120h              : $nominalPtt120h"


Write-Host ""
Write-Host "------------------------------------------"
Write-Host "DEBIT REEL OBSERVE"
Write-Host "------------------------------------------"

Write-Host (
    "Tentatives / heure                : {0:N2}" -f
    $actualAttemptsPerHour
)

Write-Host (
    "PTT confirmes / heure             : {0:N2}" -f
    $actualSuccessfulPttPerHour
)


Write-Host ""
Write-Host "------------------------------------------"
Write-Host "PROJECTION 120H AU RYTHME OBSERVE"
Write-Host "------------------------------------------"

Write-Host "Tentatives projetees a 120h      : $projectedAttempts120h"

Write-Host "PTT confirmes projetes a 120h    : $projectedSuccessfulPtt120h"


# ============================================================
# PREMIER / DERNIER PTT CONFIRME
#
# IMPORTANT :
# ces valeurs viennent directement des timestamps :
#
# <msg time="...">PTT pressed...</msg>
# ============================================================

if (
    $null -ne $firstPttTime -and
    $null -ne $lastPttTime
) {

    $pttObservedDuration =
        (
            $lastPttTime -
            $firstPttTime
        ).TotalSeconds


    Write-Host ""
    Write-Host "------------------------------------------"
    Write-Host "PERIODE DES PTT CONFIRMES"
    Write-Host "------------------------------------------"


    Write-Host (
        "Premier PTT confirme             : {0}" -f
        $firstPttTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )


    Write-Host (
        "Dernier PTT confirme             : {0}" -f
        $lastPttTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )


    Write-Host (
        "Periode entre PTT confirmes      : {0}" -f
        (
            Format-Duration `
                -Seconds $pttObservedDuration
        )
    )
}


# ============================================================
# PREMIERE / DERNIERE TENTATIVE
#
# Ces timestamps utilisent le start du status Robot.
# Ils sont affiches separement pour eviter toute confusion.
# ============================================================

if (
    $null -ne $firstAttemptTime -and
    $null -ne $lastAttemptTime
) {

    $attemptObservedDuration =
        (
            $lastAttemptTime -
            $firstAttemptTime
        ).TotalSeconds


    Write-Host ""
    Write-Host "------------------------------------------"
    Write-Host "PERIODE DES TENTATIVES PTT"
    Write-Host "------------------------------------------"


    Write-Host (
        "Premiere tentative PTT           : {0}" -f
        $firstAttemptTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )


    Write-Host (
        "Derniere tentative PTT           : {0}" -f
        $lastAttemptTime.ToString(
            "yyyy-MM-dd HH:mm:ss"
        )
    )


    Write-Host (
        "Periode des tentatives           : {0}" -f
        (
            Format-Duration `
                -Seconds $attemptObservedDuration
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


    $driverRanges = @(
        $failRanges |
        Where-Object {
            $_.Driver -eq $driver
        }
    )


    $totalFailSeconds = 0
    $longestFailSeconds = 0


    foreach (
        $range in $driverRanges
    ) {

        if (
            $null -ne $range.Recovery
        ) {

            $rangeEnd =
                $range.Recovery
        }
        elseif (
            $null -ne $lastAttemptTime
        ) {

            $rangeEnd =
                $lastAttemptTime
        }
        else {

            continue
        }


        if (
            $rangeEnd -gt $range.Start
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
        $totalFailSeconds -gt
        $actualSeconds
    ) {

        $totalFailSeconds =
            $actualSeconds
    }


    $totalPassSeconds =
        $actualSeconds -
        $totalFailSeconds


    if (
        $totalPassSeconds -lt 0
    ) {

        $totalPassSeconds = 0
    }


    if (
        $actualSeconds -gt 0
    ) {

        $failPercent =
            (
                $totalFailSeconds /
                $actualSeconds
            ) * 100


        $passPercent =
            (
                $totalPassSeconds /
                $actualSeconds
            ) * 100
    }
    else {

        $failPercent = 0

        $passPercent = 0
    }


    $notConfirmed =
        $attemptCount -
        $ptt


    if (
        $notConfirmed -lt 0
    ) {

        $notConfirmed = 0
    }


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

            PTT_Non_Confirmes =
                $notConfirmed

            Plages_FAIL =
                $driverRanges.Count

            Temps_FAIL =
                Format-Duration `
                    -Seconds $totalFailSeconds

            Temps_PASS =
                Format-Duration `
                    -Seconds $totalPassSeconds

            Plus_Long_FAIL =
                Format-Duration `
                    -Seconds $longestFailSeconds

            FAIL_Pct =
                "{0:N2} %" -f $failPercent

            PASS_Pct =
                "{0:N2} %" -f $passPercent

            Taux_PTT =
                "{0:N2} %" -f $pressRate
        }
}


$phoneKpi |
    Format-Table -AutoSize


# ============================================================
# EXPORT CSV
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
            "ptt_pass_fail_temps.csv"


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