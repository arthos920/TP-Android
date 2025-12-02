@echo off
echo -------------------------------------------
echo  Lancement du Jenkins Agent en mode GUI
echo -------------------------------------------
echo.

REM Aller dans le dossier de l’agent
cd /d C:\jenkins-agent

REM Vérifier que agent.jar existe
if not exist agent.jar (
    echo ERREUR : agent.jar introuvable dans C:\jenkins-agent
    pause
    exit /b
)

echo Démarrage de l’agent...
echo.

REM Lancer l’agent Jenkins en mode interactif
java -jar agent.jar -jnlpUrl "<URL_JNLP>" -secret "<SECRET>" -workDir "C:\jenkins-agent"

echo.
echo -------------------------------------------
echo     Agent Jenkins arrêté (fenêtre fermée)
echo -------------------------------------------
pause