# ============================================
# Android logs collector - PowerShell 5.1
# ============================================

$PackageName = "xxxx"

# Dossier racine
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$RootFolder = Join-Path $PSScriptRoot "Android_Logs_$Timestamp"

New-Item -ItemType Directory -Path $RootFolder -Force | Out-Null

Write-Host ""
Write-Host "========================================"
Write-Host " Android Logs Collector"
Write-Host "========================================"
Write-Host "Package : $PackageName"
Write-Host "Output  : $RootFolder"
Write-Host ""

# Récupération des devices ADB connectés
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

foreach ($Device in $Devices) {

    Write-Host "----------------------------------------"
    Write-Host "Device : $Device"
    Write-Host "----------------------------------------"

    # Informations téléphone
    $Manufacturer = (adb -s $Device shell getprop ro.product.manufacturer).Trim()
    $Model        = (adb -s $Device shell getprop ro.product.model).Trim()
    $Android      = (adb -s $Device shell getprop ro.build.version.release).Trim()
    $Sdk          = (adb -s $Device shell getprop ro.build.version.sdk).Trim()

    # Nettoyage du nom pour Windows
    $SafeManufacturer = $Manufacturer -replace '[\\/:*?"<>|]', '_'
    $SafeModel = $Model -replace '[\\/:*?"<>|]', '_'

    # Exemple :
    # user1_R5CX72Q0BHV_Samsung_SM-G736B
    $DeviceFolderName = "${Device}_${SafeManufacturer}_${SafeModel}"
    $DeviceFolder = Join-Path $RootFolder $DeviceFolderName

    New-Item -ItemType Directory -Path $DeviceFolder -Force | Out-Null

    # ----------------------------------------
    # 1. Infos générales du téléphone
    # ----------------------------------------

    $DeviceInfoFile = Join-Path $DeviceFolder "device_info.txt"

    @"
Serial       : $Device
Manufacturer : $Manufacturer
Model        : $Model
Android      : $Android
SDK          : $Sdk
Package      : $PackageName
Date         : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
"@ | Out-File -FilePath $DeviceInfoFile -Encoding UTF8

    # Toutes les propriétés Android
    adb -s $Device shell getprop `
        | Out-File (Join-Path $DeviceFolder "getprop.txt") -Encoding UTF8

    # ----------------------------------------
    # 2. LOGCAT COMPLET
    # ----------------------------------------

    Write-Host " -> Full logcat"

    adb -s $Device logcat -b all -d -v threadtime `
        | Out-File (Join-Path $DeviceFolder "logcat_full.txt") -Encoding UTF8

    # ----------------------------------------
    # 3. LOGCAT filtré sur l'application
    # ----------------------------------------

    Write-Host " -> Application logcat"

    $AppLogFile = Join-Path $DeviceFolder "logcat_app.txt"

    adb -s $Device logcat -b all -d -v threadtime |
        Select-String -SimpleMatch $PackageName |
        Out-File $AppLogFile -Encoding UTF8

    # ----------------------------------------
    # 4. Logs crash / AndroidRuntime
    # ----------------------------------------

    Write-Host " -> Crash logs"

    $CrashPatterns = @(
        "FATAL EXCEPTION",
        "AndroidRuntime",
        "APP CRASH",
        "ANR",
        "SIGSEGV",
        "SIGABRT",
        "SIGKILL",
        "OutOfMemoryError",
        "lowmemory",
        "lmkd",
        "Killing",
        $PackageName
    )

    adb -s $Device logcat -b all -d -v threadtime |
        Select-String -Pattern $CrashPatterns |
        Out-File (Join-Path $DeviceFolder "crash_related_logs.txt") -Encoding UTF8

    # ----------------------------------------
    # 5. ApplicationExitInfo
    # Permet de savoir pourquoi l'app s'est fermée
    # ----------------------------------------

    Write-Host " -> ApplicationExitInfo"

    adb -s $Device shell dumpsys activity exit-info $PackageName `
        | Out-File (Join-Path $DeviceFolder "application_exit_info.txt") -Encoding UTF8

    # ----------------------------------------
    # 6. Mémoire de l'application
    # ----------------------------------------

    Write-Host " -> Memory info"

    adb -s $Device shell dumpsys meminfo $PackageName `
        | Out-File (Join-Path $DeviceFolder "meminfo.txt") -Encoding UTF8

    # ----------------------------------------
    # 7. Etat actuel de l'application
    # ----------------------------------------

    Write-Host " -> Process info"

    adb -s $Device shell pidof $PackageName `
        | Out-File (Join-Path $DeviceFolder "pid.txt") -Encoding UTF8

    adb -s $Device shell dumpsys activity processes `
        | Select-String -SimpleMatch $PackageName `
        | Out-File (Join-Path $DeviceFolder "process_info.txt") -Encoding UTF8

    # ----------------------------------------
    # 8. Dropbox Android
    # Peut contenir crash / ANR / tombstones
    # ----------------------------------------

    Write-Host " -> Android DropBox"

    adb -s $Device shell dumpsys dropbox --print `
        | Out-File (Join-Path $DeviceFolder "dropbox_full.txt") -Encoding UTF8

    adb -s $Device shell dumpsys dropbox --print |
        Select-String -Pattern @(
            $PackageName,
            "data_app_crash",
            "data_app_anr",
            "tombstone",
            "FATAL"
        ) |
        Out-File (Join-Path $DeviceFolder "dropbox_app.txt") -Encoding UTF8

    Write-Host " -> Termine pour $Device"
    Write-Host ""
}

Write-Host "========================================"
Write-Host " Collecte terminee"
Write-Host "========================================"
Write-Host ""
Write-Host "Logs disponibles ici :"
Write-Host $RootFolder
Write-Host ""