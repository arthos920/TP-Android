@echo off
:: ============================================================
:: docker_build.bat — Construit l'image + exporte pour offline
:: A lancer UNE FOIS sur la machine en ligne.
:: ============================================================

echo ===================================================
echo  1/3  Build de l'image appium-mcp-runner
echo ===================================================
docker build -t appium-mcp-runner:latest . || goto :error

echo.
echo ===================================================
echo  2/3  Export de l'image en fichier tar.gz
echo ===================================================
docker save appium-mcp-runner:latest | gzip > appium-mcp-runner.tar.gz
if %ERRORLEVEL% neq 0 goto :error
echo   Fichier cree : appium-mcp-runner.tar.gz
for %%F in (appium-mcp-runner.tar.gz) do echo   Taille : %%~zF octets

echo.
echo ===================================================
echo  3/3  Termine !
echo ===================================================
echo.
echo Pour transferer sur la machine offline :
echo   Copier appium-mcp-runner.tar.gz + ce dossier
echo.
echo Sur la machine offline :
echo   docker_load_and_run.bat
echo.
goto :end

:error
echo.
echo [ERREUR] Build echoue. Code: %ERRORLEVEL%
exit /b 1

:end
