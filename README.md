$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PortableBundleRoot = $PSScriptRoot
$PortableRuntimeRoot = Join-Path $PortableBundleRoot "runtime"
$PortablePython = Join-Path $PortableRuntimeRoot "python\python.exe"
$PortableNode = Join-Path $PortableRuntimeRoot "node\node.exe"
$PortableAppiumEntry = Join-Path $PortableRuntimeRoot "node\node_modules\appium\index.js"
$PortableJavaHome = Join-Path $PortableRuntimeRoot "java"
$PortableAndroidHome = Join-Path $PortableRuntimeRoot "android-sdk"
$PortableAdb = Join-Path $PortableAndroidHome "platform-tools\adb.exe"
$PortableAppiumHome = Join-Path $PortableRuntimeRoot "appium-home"
$PortableAppiumExtensionsManifest = Join-Path $PortableAppiumHome "node_modules\.cache\appium\extensions.yaml"
# Le driver est place dans le meme node_modules que le coeur Appium. Cela lui
# permet de resoudre son peerDependency "appium" sans lien symbolique ni chemin
# propre a la machine ayant construit le bundle.
$PortableUiAutomator2Driver = Join-Path $PortableRuntimeRoot "node\node_modules\appium-uiautomator2-driver"
$LegacyUiAutomator2Driver = Join-Path $PortableAppiumHome "node_modules\appium-uiautomator2-driver"
$PortableAndroidUserHome = Join-Path $PortableRuntimeRoot "android-user"

# Migration automatique des premiers bundles deja copies en entreprise : ils
# avaient le driver dans APPIUM_HOME, separe du coeur Appium. Aucun telechargement
# n'est effectue ; le repertoire existant est simplement replace localement.
if (
    -not (Test-Path -LiteralPath $PortableUiAutomator2Driver) -and
    (Test-Path -LiteralPath (Join-Path $LegacyUiAutomator2Driver "package.json"))
) {
    Move-Item -LiteralPath $LegacyUiAutomator2Driver -Destination $PortableUiAutomator2Driver
    Write-Host "[portable] driver UiAutomator2 migre avec le coeur Appium"
}

$requiredPaths = @(
    $PortablePython,
    $PortableNode,
    $PortableAppiumEntry,
    (Join-Path $PortableJavaHome "bin\java.exe"),
    $PortableAdb,
    (Join-Path $PortableAppiumHome "package.json"),
    $PortableAppiumExtensionsManifest,
    (Join-Path $PortableUiAutomator2Driver "package.json")
)

foreach ($requiredPath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Bundle incomplet : fichier requis introuvable : $requiredPath"
    }
}

# Appium memorise installPath comme chemin absolu dans extensions.yaml. Ce
# registre doit donc etre recalcule apres chaque copie/deplacement du bundle.
$manifestLines = [System.IO.File]::ReadAllLines($PortableAppiumExtensionsManifest)
$uiautomatorSectionFound = $false
$installPathIndex = -1
for ($index = 0; $index -lt $manifestLines.Length; $index++) {
    $line = $manifestLines[$index]
    if ($line -eq "  uiautomator2:") {
        $uiautomatorSectionFound = $true
        continue
    }
    if ($uiautomatorSectionFound -and $line -match '^  [^ ].*:$') {
        break
    }
    if ($uiautomatorSectionFound -and $line -match '^    installPath:\s*') {
        $installPathIndex = $index
        break
    }
}
if ($installPathIndex -lt 0) {
    throw "Bundle incomplet : installPath UiAutomator2 introuvable dans $PortableAppiumExtensionsManifest"
}

$yamlDriverPath = $PortableUiAutomator2Driver.Replace("'", "''")
$expectedInstallPath = "    installPath: '$yamlDriverPath'"
if ($manifestLines[$installPathIndex] -ne $expectedInstallPath) {
    $manifestLines[$installPathIndex] = $expectedInstallPath
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines(
        $PortableAppiumExtensionsManifest,
        [string[]]$manifestLines,
        $utf8WithoutBom
    )
    Write-Host "[portable] registre UiAutomator2 relocalise vers $PortableUiAutomator2Driver"
}

# Valide aussi les peerDependencies npm. Un simple "driver list" peut afficher
# le driver comme installe meme si son module ne peut pas charger le coeur
# Appium. Cette importation echoue immediatement avec une cause explicite.
$uiautomator2Entry = Join-Path $PortableUiAutomator2Driver "build\lib\index.js"
if (-not (Test-Path -LiteralPath $uiautomator2Entry)) {
    throw "Bundle incomplet : entree UiAutomator2 introuvable : $uiautomator2Entry"
}
$driverImportOutput = & $PortableNode --input-type=module -e `
    "import {pathToFileURL} from 'node:url'; await import(pathToFileURL(process.argv[1]).href);" `
    $uiautomator2Entry 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "UiAutomator2 ne peut pas charger ses dependances npm :`n$($driverImportOutput -join [Environment]::NewLine)"
}
$PortableUiAutomator2ModuleReady = $true

foreach ($writableDirectory in @(
    $PortableAndroidUserHome,
    (Join-Path $PortableBundleRoot "logs"),
    (Join-Path $PortableBundleRoot "artifacts")
)) {
    if (-not (Test-Path -LiteralPath $writableDirectory)) {
        New-Item -ItemType Directory -Path $writableDirectory | Out-Null
    }
}

# Ces variables ne modifient pas Windows : elles vivent uniquement dans le
# processus PowerShell courant et ses sous-processus.
$env:JAVA_HOME = $PortableJavaHome
$env:ANDROID_HOME = $PortableAndroidHome
$env:ANDROID_SDK_ROOT = $PortableAndroidHome
$env:ANDROID_USER_HOME = $PortableAndroidUserHome
$env:APPIUM_HOME = $PortableAppiumHome
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

$portablePathEntries = @(
    (Join-Path $PortableRuntimeRoot "python"),
    (Join-Path $PortableRuntimeRoot "python\Scripts"),
    (Join-Path $PortableRuntimeRoot "node"),
    (Join-Path $PortableJavaHome "bin"),
    (Join-Path $PortableAndroidHome "platform-tools")
)
$env:Path = ($portablePathEntries -join ";") + ";" + $env:Path
