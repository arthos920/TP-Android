@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo       APPAREILS ANDROID CONNECTES
echo ==========================================
echo.

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" (
        set "SERIAL=%%A"

        echo ------------------------------------------
        echo SERIAL       : %%A

        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.manufacturer') do set "MANUFACTURER=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.brand') do set "BRAND=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.model') do set "MODEL=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.device') do set "DEVICE=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.build.version.release') do set "ANDROID=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.build.version.sdk') do set "SDK=%%I"

        echo FABRICANT    : !MANUFACTURER!
        echo MARQUE       : !BRAND!
        echo MODELE       : !MODEL!
        echo DEVICE       : !DEVICE!
        echo ANDROID      : !ANDROID!
        echo SDK          : !SDK!
        echo.
    )
)

echo ==========================================
pause