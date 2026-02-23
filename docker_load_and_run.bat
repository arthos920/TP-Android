@echo off
:: ============================================================
:: docker_load_and_run.bat
:: A lancer sur la machine OFFLINE (apres transfert de l'image)
:: ============================================================
:: Prerequis sur la machine offline :
::   - Docker Desktop installe et demarre
::   - Appium server demarre sur le HOST (port 4723)
::   - Telephones Android branches en USB + ADB autorise
::   - LLM local si besoin (ex: Ollama sur http://localhost:11434)
::
:: Fichiers a copier depuis la machine online :
::   appium-mcp-runner.tar.gz
::   ce dossier entier (scripts + capabilities.json)
:: ============================================================

setlocal EnableDelayedExpansion

:: ── Configuration — ADAPTER ICI ───────────────────────────
:: Recuprer les serials ADB avec : adb devices
set DEVICE_1_ID=REMPLACER_PAR_SERIAL_PHONE1
set DEVICE_2_ID=REMPLACER_PAR_SERIAL_PHONE2

:: URL du LLM local (Ollama sur le host)
set LLM_BASE_URL=http://host.docker.internal:11434/v1
set LLM_MODEL=llama3.2
set LLM_API_KEY=no-key

:: App a tester (si pas de Jira)
set APP_PACKAGE=com.android.settings
set APP_ACTIVITY=.Settings

:: Script Python a executer (defaut : test deterministe)
set SCRIPT=script_test_settings.py
:: Pour le runner complet avec LLM + Jira :
:: set SCRIPT=script_jira_appium_v2.py
:: ──────────────────────────────────────────────────────────

echo ===================================================
echo  1/3  Import de l'image Docker (si pas encore fait)
echo ===================================================
docker image inspect appium-mcp-runner:latest >nul 2>&1
if %ERRORLEVEL% neq 0 (
    if not exist appium-mcp-runner.tar.gz (
        echo [ERREUR] Fichier appium-mcp-runner.tar.gz introuvable.
        echo Copier le fichier tar.gz dans ce dossier et relancer.
        pause
        exit /b 1
    )
    echo Chargement de l'image...
    docker load -i appium-mcp-runner.tar.gz || goto :error
    echo Image chargee avec succes.
) else (
    echo Image deja presente, skip load.
)

echo.
echo ===================================================
echo  2/3  Verification Appium server sur HOST :4723
echo ===================================================
curl -s --max-time 3 http://localhost:4723/status >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARN] Appium server non detecte sur :4723
    echo        Lancer restart_appium.bat sur le HOST avant de continuer.
    pause
)

echo.
echo ===================================================
echo  3/3  Lancement du container
echo ===================================================
echo Device 1 : %DEVICE_1_ID%
echo Device 2 : %DEVICE_2_ID%
echo Script   : %SCRIPT%
echo.

:: Creer le dossier screenshots si absent
if not exist screenshots mkdir screenshots

docker run --rm ^
    --add-host=host.docker.internal:host-gateway ^
    -e DEVICE_1_ID=%DEVICE_1_ID% ^
    -e DEVICE_2_ID=%DEVICE_2_ID% ^
    -e APPIUM_SERVER_URL=http://host.docker.internal:4723 ^
    -e LLM_API_KEY=%LLM_API_KEY% ^
    -e LLM_BASE_URL=%LLM_BASE_URL% ^
    -e LLM_MODEL=%LLM_MODEL% ^
    -e APP_PACKAGE=%APP_PACKAGE% ^
    -e APP_ACTIVITY=%APP_ACTIVITY% ^
    -v "%CD%\screenshots:/app/screenshots" ^
    -v "%CD%\capabilities.json:/app/capabilities.json:ro" ^
    appium-mcp-runner:latest ^
    python3 %SCRIPT%

echo.
echo Logs et screenshots disponibles dans : %CD%\screenshots
goto :end

:error
echo.
echo [ERREUR] Code: %ERRORLEVEL%
pause
exit /b 1

:end
pause
