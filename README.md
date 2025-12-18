@echo off
REM ==========================================
REM Start GitLab Runner at VM boot
REM ==========================================

REM Chemin vers GitLab Runner
set GITLAB_RUNNER_DIR=C:\gitlab-runner
set GITLAB_RUNNER_EXE=%GITLAB_RUNNER_DIR%\gitlab-runner.exe

REM Log de démarrage
set LOG_FILE=%GITLAB_RUNNER_DIR%\runner_startup.log

echo [%DATE% %TIME%] Starting GitLab Runner... >> %LOG_FILE%

REM Se placer dans le bon dossier
cd /d %GITLAB_RUNNER_DIR%

REM Lancer le runner en mode console (non service)
start "" "%GITLAB_RUNNER_EXE%" run

echo [%DATE% %TIME%] GitLab Runner launched. >> %LOG_FILE%