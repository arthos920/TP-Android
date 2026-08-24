Une fois le dossier copié sur le PC entreprise, aucune installation Python, Appium, Java ou npm n’est nécessaire.
1. Ouvrir PowerShell dans le dossier
Par exemple :
cd C:\QA\alumnium-multidevice-portable
Évitez de l’exécuter depuis un lecteur réseau : le dossier doit être local et accessible en écriture.
2. Configurer l’IA et Jira
Modifiez qa_config.py :
OPENAI_API_KEY = "votre-cle-entreprise"
OPENAI_BASE_URL = "https://votre-endpoint/v1"
OPENAI_MODEL = "magistral-2509"
PROXY_URL = ""  # ou votre proxy

JIRA_MCP_URL = "https://votre-serveur-mcp-jira/..."
JIRA_KEY = "PROJET-123"
ALUMNIUM_MODEL et OPENAI_CUSTOM_URL sont dérivés automatiquement.
Le fichier contenant la clé en clair, conservez le dossier dans un emplacement protégé.
3. Tester Jira et le planner uniquement
Aucun téléphone ni serveur Appium n’est utilisé à cette étape :
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -JiraPlanOnly
Le résultat attendu est :
Jira MCP
→ lecture du ticket
→ résumé
→ classification
→ plan JSON multi-device
Le plan sera sauvegardé dans :
artifacts\multidevice\<date>\generated-jira-plan.json
4. Connecter les téléphones
Sur chaque téléphone :
- activer les options développeur ;
- activer le débogage USB ;
- déverrouiller l’écran ;
- accepter la clé de débogage ADB ;
- vérifier que l’application entreprise est installée.
Lancez ensuite :
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\diagnostic.ps1
Vous devez obtenir :
List of devices attached
R58M123456A    device
R58M789012B    device
L’avertissement indiquant que l’émulateur est absent est normal pour ce bundle.
Si un téléphone affiche :
unauthorized
déverrouillez-le et acceptez la demande USB. S’il n’apparaît pas, il faut probablement installer son pilote USB constructeur sur Windows.
5. Reporter les UDID dans la configuration
Dans qa_config.py :
DEVICES = {
    "phone_1": {
        "enabled": True,
        "udid": "R58M123456A",
        # ...
    },
    "phone_2": {
        "enabled": True,
        "udid": "R58M789012B",
        # ...
    },
}
Pour trois téléphones :
"phone_3": {
    "enabled": True,
    "udid": "R58M345678C",
    # ...
}
Puis ajoutez un rôle :
MULTI_DEVICE_ROLES = {
    "caller": "phone_1",
    "callee": "phone_2",
    "observer": "phone_3",
}
6. Tester ADB et Appium sans IA
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -PreflightOnly
Ce test doit confirmer :
ADB OK
APPIUM OK
PREFLIGHT MULTI-DEVICE : SUCCES
Appium est démarré et arrêté automatiquement.
7. Tester Alumnium sur Settings
Laissez temporairement :
MULTI_DEVICE_START = "intent:android.settings.SETTINGS"
Puis lancez :
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -PlanSource fixed
Cette étape valide :
endpoint IA
→ Alumnium
→ Appium
→ deux téléphones
→ Android Settings
8. Configurer l’application entreprise
Lorsque Settings fonctionne, remplacez le point de départ :
MULTI_DEVICE_START = "com.entreprise.application"
Ou avec une activité explicite :
MULTI_DEVICE_START = "com.entreprise.application/.MainActivity"
9. Lancer le scénario Jira complet
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
Le pipeline complet sera alors :
Jira MCP
→ modèle entreprise
→ plan multi-device
→ Alumnium
→ Appium
→ UiAutomator2
→ téléphones physiques
En cas d’échec, récupérez :
logs\
artifacts\multidevice\<date>\
et la sortie PowerShell complète.


15 août, 15:35








je dois lancer un server appium ?







15 août, 15:36






Non, pas manuellement.
Cette commande démarre automatiquement l’Appium inclus dans le bundle, exécute le test, puis l’arrête :
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
C’est également valable pour :
.\run.ps1 -PreflightOnly
.\run.ps1 -PlanSource fixed
En mode suivant, Appium n’est pas démarré car aucun téléphone n’est utilisé :
.\run.ps1 -JiraPlanOnly
Si vous préférez voir Appium dans une console séparée, lancez d’abord :
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-appium.ps1
Puis, dans un second PowerShell :
.\run.ps1 -NoStartAppium
Mais pour l’utilisation normale, une seule commande run.ps1 suffit.
