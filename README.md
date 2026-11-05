
import subprocess
import time

from appium.webdriver.applicationstate import ApplicationState


def is_phone_locked(self):
    """Vérifie si le téléphone est verrouillé."""
    return self.driver.is_locked()


def unlock_phone(self, pin="0000"):
    """Déverrouille le téléphone avec ADB si nécessaire."""

    if not self.is_phone_locked():
        return True

    # Identifier le bon téléphone parmi les 6
    udid = (
        self.driver.capabilities.get("udid")
        or self.driver.capabilities.get("appium:udid")
    )

    if not udid:
        raise RuntimeError("Android UDID missing")

    def adb_shell(*args):
        subprocess.run(
            ["adb", "-s", udid, "shell", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15
        )

    # Réveiller le téléphone
    adb_shell("input", "keyevent", "224")
    time.sleep(1)

    # Afficher la saisie du PIN
    adb_shell("input", "keyevent", "82")
    time.sleep(1)

    # Saisir le PIN et valider
    adb_shell("input", "text", pin)
    adb_shell("input", "keyevent", "66")
    time.sleep(2)

    if self.is_phone_locked():
        raise RuntimeError("Phone unlock failed")

    return True


def is_app_running(self, package_name):
    """Vérifie si l'application est au premier plan."""
    state = self.driver.query_app_state(package_name)

    return state == ApplicationState.RUNNING_IN_FOREGROUND


def back_up_endurance(self, package_name):
    """Récupération après échec du PTT."""

    was_locked = self.is_phone_locked()

    # Déverrouiller uniquement si nécessaire
    if was_locked:
        self.unlock_phone()

    # Ne pas redémarrer si l'app est déjà ouverte
    if self.is_app_running(package_name):
        return "UNLOCKED" if was_locked else "ALREADY_RUNNING"

    # Redémarrer l'application
    self.driver.terminate_app(package_name)
    self.driver.activate_app(package_name)

    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        if self.is_app_running(package_name):
            return "RESTARTED"

        time.sleep(1)

    raise RuntimeError("Application restart failed")
