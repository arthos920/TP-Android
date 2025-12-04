Nous avons activé deux options qui forcent Appium à repartir sur un environnement propre à chaque test.
Cela évite que des fichiers internes se corrompent et bloquent les appareils.
Résultat : plus de stabilité, plus besoin de redémarrer les téléphones, et moins d’échecs non pertinents.






if desired_capabilities is None:
    desired_caps = {
        "platformName": "Android",

        # ✔ ton app garde ses données
        "noReset": True,
        "fullReset": False,

        # ✔ Appium réinstalle ses serveurs UiAutomator2 → stabilité
        "skipServerInstallation": False,
        "skipDeviceInitialization": False,

        # ✔ empêche les logs d'exploser → évite socket hang up
        "clearDeviceLogsOnStart": True,

        # ✔ délais pour éviter les timeouts UiAutomator2 / ADB
        "uiautomator2ServerInstallTimeout": 30000,
        "adbExecTimeout": 60000,

        # ✔ langue & locale
        "appium:language": "en",
        "appium:locale": "en",

        # ✔ pour éviter la déconnexion du driver en long test
        "newCommandTimeout": 3000
    }