param (
    [Parameter(Mandatory=$true)]
    [datetime]$TestStart,

    [Parameter(Mandatory=$true)]
    [datetime]$TestEnd,

    [string]$LogPath = ""
)

Write-Host ""
Write-Host "========================================="
Write-Host "  ANALYSE TELEPHONES ADB / ANYWHEREUSB"
Write-Host "========================================="
Write-Host ""
Write-Host "Debut du test : $TestStart"
Write-Host "Fin du test   : $TestEnd"
Write-Host ""

# ============================================================
# 1. RECUPERATION DES TELEPHONES ACTUELLEMENT VUS PAR ADB
# ============================================================

$devices = adb devices |
    Select-String "\sdevice$" |
    ForEach-Object {
        ($_ -split "\s+")[0]
    }

if (-not $devices) {
    Write-Host "Aucun telephone actuellement detecte par ADB."
}
else {
    Write-Host "$($devices.Count) telephone(s) actuellement detecte(s) par ADB."
}

Write-Host ""

$results = @()

# ============================================================
# 2. ANALYSE DE CHAQUE TELEPHONE
# ============================================================

foreach ($serial in $devices) {

    Write-Host "-----------------------------------------"
    Write-Host "Analyse : $serial"
    Write-Host "-----------------------------------------"

    # Etat ADB
    try {
        $state = (adb -s $serial get-state 2>$null).Trim()
    }
    catch {
        $state = "ERROR"
    }

    # Modele du telephone
    try {
        $model = (adb -s $serial shell getprop ro.product.model 2>$null).Trim()
    }
    catch {
        $model = "UNKNOWN"
    }

    # Recherche du périphérique correspondant dans Windows
    $pnp = Get-PnpDevice -ErrorAction SilentlyContinue |
        Where-Object {
            $_.InstanceId -like "*$serial*"
        } |
        Select-Object -First 1

    $arrival = $null
    $connectedFor = "UNKNOWN"
    $reconnectionDuringTest = "UNKNOWN"

    if ($pnp) {

        try {
            $arrival = (
                Get-PnpDeviceProperty `
                    -InstanceId $pnp.InstanceId `
                    -KeyName "DEVPKEY_Device_LastArrivalDate" `
                    -ErrorAction Stop
            ).Data
        }
        catch {
            $arrival = $null
        }

        if ($arrival) {

            $duration = New-TimeSpan -Start $arrival -End (Get-Date)

            $connectedFor = "{0}j {1}h {2}min {3}s" -f `
                $duration.Days,
                $duration.Hours,
                $duration.Minutes,
                $duration.Seconds

            if (($arrival -ge $TestStart) -and ($arrival -le $TestEnd)) {
                $reconnectionDuringTest = "OUI - reconnexion possible"
            }
            else {
                $reconnectionDuringTest = "NON"
            }
        }
    }
    else {
        Write-Host "Impossible d'associer automatiquement le serial ADB au peripherique Windows."
    }

    Write-Host "ADB ID               : $serial"
    Write-Host "Modele                : $model"
    Write-Host "Etat ADB              : $state"
    Write-Host "Derniere arrivee VM   : $arrival"
    Write-Host "Present depuis        : $connectedFor"
    Write-Host "Arrivee pendant test  : $reconnectionDuringTest"
    Write-Host ""

    $results += [PSCustomObject]@{
        ADB_ID                    = $serial
        Model                     = $model
        ADB_State                 = $state
        LastArrival               = $arrival
        ConnectedFor              = $connectedFor
        ArrivalDuringTest         = $reconnectionDuringTest
    }
}

# ============================================================
# 3. TABLEAU RECAPITULATIF
# ============================================================

Write-Host ""
Write-Host "========================================="
Write-Host "RESUME"
Write-Host "========================================="
Write-Host ""

$results | Format-Table -AutoSize

# ============================================================
# 4. EVENEMENTS WINDOWS PNP / USB PENDANT LE TEST
# ============================================================

Write-Host ""
Write-Host "========================================="
Write-Host "EVENEMENTS WINDOWS PENDANT LE TEST"
Write-Host "========================================="
Write-Host ""

try {

    $windowsEvents = Get-WinEvent -FilterHashtable @{
        LogName   = "System"
        StartTime = $TestStart
        EndTime   = $TestEnd
    } -ErrorAction Stop |
    Where-Object {
        $_.ProviderName -match "Kernel-PnP|UserPnp|USB|DriverFramework"
    } |
    Select-Object TimeCreated, Id, ProviderName, Message

    if ($windowsEvents) {

        foreach ($event in $windowsEvents) {

            Write-Host "-----------------------------------------"
            Write-Host "Date     : $($event.TimeCreated)"
            Write-Host "ID       : $($event.Id)"
            Write-Host "Provider : $($event.ProviderName)"
            Write-Host "Message  : $($event.Message)"
        }

    }
    else {
        Write-Host "Aucun evenement PnP/USB trouve pendant la periode."
    }

}
catch {
    Write-Host "Impossible de lire les evenements Windows :"
    Write-Host $_.Exception.Message
}

# ============================================================
# 5. ANALYSE OPTIONNELLE DES LOGS ROBOT / APPIUM
# ============================================================

if ($LogPath -ne "") {

    Write-Host ""
    Write-Host "========================================="
    Write-Host "RECHERCHE DANS LES LOGS ROBOT / APPIUM"
    Write-Host "========================================="
    Write-Host ""

    if (Test-Path $LogPath) {

        $patterns = @(
            "device offline",
            "device not found",
            "no devices/emulators found",
            "connection reset",
            "socket hang up",
            "ADB.*offline",
            "ADB.*not found",
            "NoSuchElementException"
        )

        $logFiles = Get-ChildItem `
            -Path $LogPath `
            -Recurse `
            -File `
            -Include *.log,*.txt,*.xml `
            -ErrorAction SilentlyContinue

        foreach ($pattern in $patterns) {

            $matches = $logFiles |
                Select-String `
                    -Pattern $pattern `
                    -CaseSensitive:$false `
                    -ErrorAction SilentlyContinue

            if ($matches) {

                Write-Host ""
                Write-Host "ERREUR TROUVEE : $pattern"
                Write-Host ""

                $matches |
                    Select-Object Path, LineNumber, Line |
                    Format-Table -Wrap
            }
        }

    }
    else {
        Write-Host "Le dossier de logs n'existe pas : $LogPath"
    }
}

# ============================================================
# 6. EXPORT CSV
# ============================================================

$csvFile = ".\phone_connection_report.csv"

$results |
    Export-Csv `
        -Path $csvFile `
        -Delimiter ";" `
        -NoTypeInformation `
        -Encoding UTF8

Write-Host ""
Write-Host "========================================="
Write-Host "FIN DE L'ANALYSE"
Write-Host "========================================="
Write-Host ""
Write-Host "Rapport CSV : $csvFile"