
def clean_appium_apks(self, device_id):
    """
    Désinstalle les APK internes Appium uniquement s'ils sont présents.
    - UiAutomator2 server
    - UiAutomator2 server test
    - Appium Settings
    """

    print(f"[CLEAN] Nettoyage des APK Appium sur le device {device_id}...")

    packages = [
        "io.appium.uiautomator2.server",
        "io.appium.uiautomator2.server.test",
        "io.appium.settings"
    ]

    # 1️⃣ On récupère la liste des packages installés sur le téléphone
    list_cmd = f"adb -s {device_id} shell pm list packages"
    installed_packages = self.send_command_with_pipes(list_cmd)

    # 2️⃣ Vérification + désinstallation
    for pkg in packages:
        if pkg in installed_packages:
            print(f"[CLEAN] → {pkg} trouvé, désinstallation en cours...")
            uninstall_cmd = f"adb -s {device_id} uninstall {pkg}"
            self.send_command_with_pipes(uninstall_cmd)
        else:
            print(f"[CLEAN] → {pkg} absent, rien à désinstaller.")

    print("[CLEAN] Fin du nettoyage Appium APKs.")















"C:\Program Files\Java\jdk-20\bin\java.exe" ^
  -Dhttp.nonProxyHosts="10.*|localhost|127.0.0.1" ^
  -Dhttps.nonProxyHosts="10.*|localhost|127.0.0.1" ^
  -jar agent.jar ^
  -url "http://url:port" ^
  <TON_TOKEN> ^
  -name "SduLeL6nSY5O8" ^
  -webSocket ^
  -workDir "C:\Jenkins"

set NO_PROXY=10.,localhost,127.0.0.1
set no_proxy=10.,localhost,127.0.0.1











def clean_appium_apks(self, device_id):
    """
    Désinstalle les APK internes Appium uniquement s'ils sont présents :
    - UiAutomator2 server
    - UiAutomator2 server test
    - Appium Settings

    Cela permet d'éviter les blocages Appium (socket hang up, proxy errors).
    Appium les réinstallera automatiquement au lancement de la session.
    """

    print(f"[CLEAN] Nettoyage des APK Appium sur le device {device_id}...")

    packages = [
        "io.appium.uiautomator2.server",
        "io.appium.uiautomator2.server.test",
        "io.appium.settings"
    ]

    for pkg in packages:
        # Vérifier si le package est installé
        check_cmd = f"adb -s {device_id} shell pm list packages | grep {pkg}"
        result = self.send_command_with_pipes(check_cmd)

        if pkg in result:
            print(f"[CLEAN] → {pkg} trouvé, désinstallation en cours...")
            uninstall_cmd = f"adb -s {device_id} uninstall {pkg}"
            self.send_command_with_pipes(uninstall_cmd)
        else:
            print(f"[CLEAN] → {pkg} absent, rien à désinstaller.")

    print(f"[CLEAN] Fin du nettoyage Appium APKs.")




from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def clear_close_call(self, timeout=5):
    """
    Ferme proprement un appel en cours si nécessaire.

    Logique :
    1. Si un bouton raccrocher est visible → on clique.
    2. Sinon, on va sur la vue messages.
    3. Si un bouton Join est visible → on clique, puis on raccroche.
    4. Si un item avec texte 'Ongoing' est visible → on clique, puis on raccroche.
    """

    try:
        wait = WebDriverWait(self.driver, timeout)

        # 1) Essayer de raccrocher directement si le bouton est déjà là
        try:
            element = wait.until(
                EC.element_to_be_clickable((By.ID, HANGUP_BUTTON_ID))
            )
            element.click()
            # Si tu as une fonction qui termine vraiment l'appel (PTT par ex.)
            if hasattr(self, "stop_ptt_call"):
                self.stop_ptt_call()
            return
        except Exception:
            # Pas de bouton raccrocher visible tout de suite -> on continue
            pass

        # 2) Tenter d'aller vers la vue message (si tu as cette méthode)
        try:
            if hasattr(self, "navigation_to_message_view"):
                self.navigation_to_message_view()
        except Exception:
            # Si ça plante, on ne bloque pas le nettoyage
            pass

        # 3) Si un bouton Join est présent, on rejoint l'appel puis on raccroche
        try:
            join_btn = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.ID, JOIN_BUTTON_ID))
            )
            join_btn.click()

            hangup_btn = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.ID, HANGUP_BUTTON_ID))
            )
            hangup_btn.click()

            if hasattr(self, "stop_ptt_call"):
                self.stop_ptt_call()
            return
        except Exception:
            # Pas de Join visible -> on essaye la liste "Ongoing"
            pass

        # 4) Chercher un item "Ongoing" et le fermer
        try:
            ongoing_cell = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.ID, PRIMARY_TEXT_ID))
            )

            if ongoing_cell.text == "Ongoing":
                ongoing_cell.click()

                hangup_btn = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.ID, HANGUP_BUTTON_ID))
                )
                hangup_btn.click()

                if hasattr(self, "stop_ptt_call"):
                    self.stop_ptt_call()
                return
        except Exception:
            # Rien trouvé, on considère qu'il n'y a pas d'appel à fermer
            pass

    except Exception as e:
        print(f"[clear_close_call] Error while cleaning call: {e}")