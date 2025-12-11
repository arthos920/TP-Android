# Check for blocked systemPort and try to free it
if "free port in range" in str(e) or "systemPort" in str(e):
    print(f"[WARN] Port {desired_caps.get('systemPort')} appears to be blocked. Attempting to free it...")

    def free_port(port):
        cmd = f'netstat -ano | findstr {port}'
        result = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).communicate()[0].decode()

        if result.strip() == "":
            print(f"[INFO] No process found on port {port}")
            return False

        for line in result.splitlines():
            parts = line.split()
            pid = parts[-1]  # PID is last column
            print(f"[INFO] Killing PID {pid} using port {port}")
            os.system(f"taskkill /PID {pid} /F")

        return True

    port = desired_caps.get("systemPort")
    if port:
        freed = free_port(port)
        if freed:
            print("[INFO] Port freed successfully. Retrying setup_device...")
            # Retry immediately after freeing the port
            return self.setup_device(appium_server_address, desired_capabilities,
                                     recording, window_name_to_capture, cache,
                                     system_port=port)















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