# ============================================================
# Android Memory Monitor - PowerShell 5.1
# Multi-devices ADB
# ============================================================

$PackageName = "xxxx"

# Intervalle entre deux mesures
$IntervalSeconds = 120

# Dossier de sortie
$StartTime = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$RootFolder = Join-Path $PSScriptRoot "Memory_Monitor_$StartTime"

New-Item -ItemType Directory -Path $RootFolder -Force | Out-Null

Write-Host ""
Write-Host "=============================================================="
Write-Host " Android Memory Monitor"
Write-Host "=============================================================="
Write-Host "Package  : $PackageName"
Write-Host "Interval : $IntervalSeconds secondes"
Write-Host "Output   : $RootFolder"
Write-Host ""
Write-Host "CTRL+C pour arreter."
Write-Host ""

# ------------------------------------------------------------
# Récupération des téléphones connectés
# ------------------------------------------------------------

$Devices = adb devices |
    Select-Object -Skip 1 |
    ForEach-Object {
        if ($_ -match "^(\S+)\s+device$") {
            $matches[1]
        }
    }

if (-not $Devices) {
    Write-Host "Aucun telephone ADB connecte."
    exit 1
}

Write-Host "$($Devices.Count) telephone(s) detecte(s)."
Write-Host ""

# ------------------------------------------------------------
# Création des dossiers et CSV
# ------------------------------------------------------------

$DeviceData = @{}

foreach ($Device in $Devices) {

    $Manufacturer = (adb -s $Device shell getprop ro.product.manufacturer).Trim()
    $Model = (adb -s $Device shell getprop ro.product.model).Trim()

    $SafeManufacturer = $Manufacturer -replace '[\\/:*?"<>|]', '_'
    $SafeModel = $Model -replace '[\\/:*?"<>|]', '_'

    $FolderName = "${Device}_${SafeManufacturer}_${SafeModel}"
    $DeviceFolder = Join-Path $RootFolder $FolderName

    New-Item -ItemType Directory -Path $DeviceFolder -Force | Out-Null

    $CsvFile = Join-Path $DeviceFolder "memory.csv"

    # CSV en MB
    "Timestamp,Serial,Status,PID,Total_PSS_MB,Total_RSS_MB,Java_Heap_MB,Native_Heap_MB" |
        Out-File -FilePath $CsvFile -Encoding UTF8

    $DeviceData[$Device] = @{
        Folder = $DeviceFolder
        Csv    = $CsvFile
    }

    Write-Host "Device : $Device | $Manufacturer $Model"
}

Write-Host ""
Write-Host "=============================================================="
Write-Host " Monitoring lance"
Write-Host "=============================================================="
Write-Host ""

# ------------------------------------------------------------
# Monitoring
# ------------------------------------------------------------

while ($true) {

    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    foreach ($Device in $Devices) {

        try {

            # ------------------------------------------------
            # PID application
            # ------------------------------------------------

            $PidOutput = adb -s $Device shell pidof $PackageName 2>$null

            if ($PidOutput) {

                $AppPid = $PidOutput.Trim()
                $Status = "RUNNING"

                # --------------------------------------------
                # dumpsys meminfo
                # --------------------------------------------

                $MemInfo = adb -s $Device shell dumpsys meminfo $PackageName 2>$null

                $TotalPssKB = 0
                $TotalRssKB = 0
                $JavaHeapKB = 0
                $NativeHeapKB = 0

                foreach ($Line in $MemInfo) {

                    if ($Line -match "Java Heap:\s+(\d+)") {
                        $JavaHeapKB = [double]$matches[1]
                    }

                    if ($Line -match "Native Heap:\s+(\d+)") {
                        $NativeHeapKB = [double]$matches[1]
                    }

                    if ($Line -match "TOTAL PSS:\s+(\d+)") {
                        $TotalPssKB = [double]$matches[1]
                    }

                    if ($Line -match "TOTAL RSS:\s+(\d+)") {
                        $TotalRssKB = [double]$matches[1]
                    }
                }

                # --------------------------------------------
                # Conversion KB -> MB
                # --------------------------------------------

                $TotalPssMB = [math]::Round($TotalPssKB / 1024, 1)
                $TotalRssMB = [math]::Round($TotalRssKB / 1024, 1)
                $JavaHeapMB = [math]::Round($JavaHeapKB / 1024, 1)
                $NativeHeapMB = [math]::Round($NativeHeapKB / 1024, 1)

                # --------------------------------------------
                # CSV
                # --------------------------------------------

                $LineOutput = "$Timestamp,$Device,$Status,$AppPid,$TotalPssMB,$TotalRssMB,$JavaHeapMB,$NativeHeapMB"

                Add-Content `
                    -Path $DeviceData[$Device].Csv `
                    -Value $LineOutput

                # --------------------------------------------
                # Affichage terminal
                # --------------------------------------------

                Write-Host (
                    "{0} | {1} | PID={2} | PSS={3} MB | RSS={4} MB | Java={5} MB | Native={6} MB" -f `
                    $Timestamp,
                    $Device,
                    $AppPid,
                    $TotalPssMB,
                    $TotalRssMB,
                    $JavaHeapMB,
                    $NativeHeapMB
                )
            }
            else {

                # ------------------------------------------------
                # Application arrêtée
                # ------------------------------------------------

                $Status = "NOT_RUNNING"

                $LineOutput = "$Timestamp,$Device,$Status,,,,,"

                Add-Content `
                    -Path $DeviceData[$Device].Csv `
                    -Value $LineOutput

                Write-Host "$Timestamp | $Device | APPLICATION NOT RUNNING"

                # --------------------------------------------
                # Sauvegarde automatique de l'ExitInfo
                # --------------------------------------------

                $ExitTimestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

                $ExitInfoFile = Join-Path `
                    $DeviceData[$Device].Folder `
                    "exit_info_$ExitTimestamp.txt"

                adb -s $Device shell dumpsys activity exit-info $PackageName |
                    Out-File $ExitInfoFile -Encoding UTF8

                # --------------------------------------------
                # Sauvegarde d'un logcat au moment de la détection
                # --------------------------------------------

                $LogcatFile = Join-Path `
                    $DeviceData[$Device].Folder `
                    "logcat_after_stop_$ExitTimestamp.txt"

                adb -s $Device logcat -b all -d -v threadtime |
                    Out-File $LogcatFile -Encoding UTF8
            }

        }
        catch {

            Write-Host "$Timestamp | $Device | ERROR : $($_.Exception.Message)"
        }
    }

    Write-Host ""

    Start-Sleep -Seconds $IntervalSeconds
}