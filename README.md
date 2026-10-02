@echo off
setlocal EnableDelayedExpansion

echo ==========================================
echo       APPAREILS ANDROID CONNECTES
echo ==========================================
echo.

for /f "skip=1 tokens=1,2" %%A in ('adb devices') do (
    if "%%B"=="device" (

        set "SERIAL=%%A"
        set "MARKETNAME="
        set "DEVICENAME="
        set "MODEL="
        set "DEVICE="
        set "BRAND="
        set "MANUFACTURER="
        set "ANDROID="
        set "SDK="
        set "NAME="

        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.marketname') do set "MARKETNAME=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell settings get global device_name') do set "DEVICENAME=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.model') do set "MODEL=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.device') do set "DEVICE=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.brand') do set "BRAND=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.product.manufacturer') do set "MANUFACTURER=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.build.version.release') do set "ANDROID=%%I"
        for /f "delims=" %%I in ('adb -s %%A shell getprop ro.build.version.sdk') do set "SDK=%%I"

        rem Fallback nom du telephone
        if defined MARKETNAME (
            set "NAME=!MARKETNAME!"
        ) else (
            if defined DEVICENAME (
                if /I not "!DEVICENAME!"=="null" (
                    set "NAME=!DEVICENAME!"
                )
            )
        )

        if not defined NAME (
            set "NAME=!MODEL!"
        )

        echo ------------------------------------------
        echo NOM          : !NAME!
        echo SERIAL       : !SERIAL!
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