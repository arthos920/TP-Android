
import time
from appium.webdriver.applicationstate import ApplicationState


def is_phone_locked(self):
    """Vérifie si le téléphone est verrouillé."""
    return self.driver.execute_script("mobile: isLocked")


def unlock_phone(self, pin="0000"):
    """Déverrouille uniquement si nécessaire."""

    if not self.is_phone_locked():
        return True

    self.driver.execute_script(
        "mobile: unlock",
        {
            "type": "pin",
            "key": pin,
            "timeoutMs": 10000
        }
    )

    if self.is_phone_locked():
        raise RuntimeError("Phone unlock failed")

    return True


def is_app_running(self, package_name):
    """Vérifie si l'application est au premier plan."""

    state = self.driver.query_app_state(package_name)

    return state == ApplicationState.RUNNING_IN_FOREGROUND


def back_up_endurance(self, package_name):
    """
    Récupération conditionnelle après un PTT FAILED.
    """

    # 1. Vérifier et déverrouiller si nécessaire
    was_locked = self.is_phone_locked()

    if was_locked:
        self.unlock_phone()

    # 2. Vérifier si l'application est ouverte
    if self.is_app_running(package_name):
        return "UNLOCKED" if was_locked else "ALREADY_RUNNING"

    # 3. Application absente du premier plan :
    # redémarrage
    self.driver.terminate_app(package_name)
    self.driver.activate_app(package_name)

    # 4. Attendre que l'application soit au premier plan
    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        if self.is_app_running(package_name):
            return "RESTARTED"

        time.sleep(1)

    raise RuntimeError("Application restart failed")





${ptt1}=    Run Keyword And Return Status    driver1.use_ptt_release

IF    not ${ptt1}

    Log To Console    [ENDURANCE] PTT FAILED driver1

    ${status1}    ${action1}=    Run Keyword And Ignore Error    driver1.back_up_endurance    ${APP_PACKAGE}

    IF    '${status1}' == 'PASS'

        Log To Console    [ENDURANCE] driver1: ${action1}

        IF    '${action1}' == 'RESTARTED'
            ${nav1}=    Run Keyword And Return Status    driver1.navigate to talk group view
            IF    ${nav1}
                ${group1}=    Run Keyword And Return Status    driver1.connect Group    ${conversation_name}
                IF    ${group1}
                    ${view1}=    Run Keyword And Return Status    driver1.open ptt view
                END
            END
        END

    ELSE
        Log    [ENDURANCE] Backup driver1 FAILED: ${action1}    WARN
    END
END

Sleep    2s
