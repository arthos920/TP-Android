import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =========================
# LOCATORS
# =========================

LATE_ENTRY_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='audio-calls-ptt']"
LATE_ENTRY_ROWS_XPATH = LATE_ENTRY_TABLE_XPATH + "//tbody//tr[@data-role='row-template']"

LATE_ENTRY_OWNER_XPATH = ".//td[@data-role='EventOwner']"
LATE_ENTRY_TYPE_XPATH = ".//td[@data-role='EventType']"
LATE_ENTRY_DATE_XPATH = ".//td[@data-role='EventDate']"
LATE_ENTRY_ADDITIONAL_INFO_XPATH = ".//td[@data-role='AdditionalInfo']"
LATE_ENTRY_CALL_UUID_XPATH = ".//td[@data-role='CallUuid']"


def auditor_verify_late_entry(
    self,
    started_owner,
    first_joined_owner,
    rejected_owner,
    second_joined_owner,
    ended_owner,
    rejected_info="Declined",
    timeout=120,
    poll_interval=2,
):
    """
    Vérifie un scénario late entry dans la table PTT avec ordre STRICT.

    Ordre chronologique attendu :
      1) Started call          -> started_owner
      2) Joined call           -> first_joined_owner
      3) Call rejected         -> rejected_owner + AdditionalInfo == rejected_info
      4) Joined call           -> second_joined_owner
      5) Left call             -> owner ignoré
      6) Left call             -> owner ignoré
      7) Ended call            -> ended_owner

    Screenshot + dump HTML en cas d'échec.
    Retourne le call_uuid.
    """

    def _norm(value):
        return (value or "").strip()

    def _etype_key(event_type_text):
        t = _norm(event_type_text).lower()
        if t == "started call":
            return "started"
        if t == "joined call":
            return "joined"
        if t == "left call":
            return "left"
        if t == "ended call":
            return "ended"
        if t == "call rejected":
            return "rejected"
        return "other"

    try:
        # 1) Attendre la table
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, LATE_ENTRY_TABLE_XPATH))
        )

        # 2) Attendre des lignes peuplées
        end_time = time.monotonic() + timeout
        valid_rows = []
        last_table_html = None

        while time.monotonic() < end_time:
            rows = self.driver.find_elements(By.XPATH, LATE_ENTRY_ROWS_XPATH)
            valid_rows = []

            for row in rows:
                try:
                    call_uuid = _norm(row.find_element(By.XPATH, LATE_ENTRY_CALL_UUID_XPATH).text)
                    if call_uuid:
                        valid_rows.append(row)
                except Exception:
                    continue

            if valid_rows:
                break

            try:
                last_table_html = self.driver.find_element(By.XPATH, LATE_ENTRY_TABLE_XPATH).get_attribute("outerHTML")
            except Exception:
                last_table_html = None

            time.sleep(poll_interval)

        if not valid_rows:
            if last_table_html:
                robot.api.logger.info(f"[auditor_verify_late_entry] table html: {last_table_html}")
            log_screenshot_web_global(self.driver, title="auditor_verify_late_entry FAILED - no populated rows")
            raise Exception("No populated rows found (UI async not finished)")

        # 3) Parser les rows
        parsed = []
        call_uuids = set()

        for row in valid_rows:
            owner = _norm(row.find_element(By.XPATH, LATE_ENTRY_OWNER_XPATH).text)
            etype = _norm(row.find_element(By.XPATH, LATE_ENTRY_TYPE_XPATH).text)
            edate = _norm(row.find_element(By.XPATH, LATE_ENTRY_DATE_XPATH).text)
            call_uuid = _norm(row.find_element(By.XPATH, LATE_ENTRY_CALL_UUID_XPATH).text)

            try:
                additional_info = _norm(row.find_element(By.XPATH, LATE_ENTRY_ADDITIONAL_INFO_XPATH).text)
            except Exception:
                additional_info = ""

            if call_uuid:
                call_uuids.add(call_uuid)

            parsed.append({
                "row": row,
                "owner": owner,
                "etype": etype,
                "etype_key": _etype_key(etype),
                "event_date": edate,
                "call_uuid": call_uuid,
                "additional_info": additional_info,
            })

        if len(call_uuids) != 1:
            raise Exception(f"Expected exactly 1 CallUuid across rows, got {len(call_uuids)}: {call_uuids}")

        call_uuid = next(iter(call_uuids))
        robot.api.logger.info(f"[auditor_verify_late_entry] detected call_uuid={call_uuid}")

        # 4) La table UI est du plus récent au plus ancien, donc on inverse
        chrono = list(reversed(parsed))

        # 5) Séquence attendue
        expected_sequence = [
            ("started", started_owner),
            ("joined", first_joined_owner),
            ("rejected", rejected_owner),
            ("joined", second_joined_owner),
            ("left", None),
            ("left", None),
            ("ended", ended_owner),
        ]

        # 6) Séquence observée
        observed_sequence = [
            (event["etype_key"], event["owner"])
            for event in chrono
            if event["etype_key"] in ("started", "joined", "rejected", "left", "ended")
        ]

        errors = []

        # 7) Vérif stricte de longueur
        if len(observed_sequence) != len(expected_sequence):
            errors.append(
                f"Sequence length mismatch: expected {len(expected_sequence)}, got {len(observed_sequence)}"
            )

        # 8) Vérif stricte position par position
        for index, (expected_item, observed_item) in enumerate(zip(expected_sequence, observed_sequence), start=1):
            exp_type, exp_owner = expected_item
            obs_type, obs_owner = observed_item

            if exp_type != obs_type:
                errors.append(f"Mismatch at pos {index}: expected type '{exp_type}', got '{obs_type}'")

            if exp_owner is not None and exp_owner != obs_owner:
                errors.append(f"Mismatch at pos {index}: expected owner '{exp_owner}', got '{obs_owner}'")

        # 9) Vérif spécifique du Call rejected
        rejected_event = next((event for event in chrono if event["etype_key"] == "rejected"), None)
        if not rejected_event:
            errors.append("Missing rejected event")
        else:
            if rejected_event["owner"] != rejected_owner:
                errors.append(
                    f"Rejected owner mismatch: expected '{rejected_owner}', got '{rejected_event['owner']}'"
                )

            if rejected_info is not None and rejected_event["additional_info"] != rejected_info:
                errors.append(
                    f"Rejected additional info mismatch: expected '{rejected_info}', got '{rejected_event['additional_info']}'"
                )

        if errors:
            html = self.driver.find_element(By.XPATH, LATE_ENTRY_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[auditor_verify_late_entry] table html: {html}")
            robot.api.logger.info(f"[auditor_verify_late_entry] expected={expected_sequence}")
            robot.api.logger.info(f"[auditor_verify_late_entry] observed={observed_sequence}")
            log_screenshot_web_global(self.driver, title="auditor_verify_late_entry FAILED")
            raise Exception(" | ".join(errors))

        robot.api.logger.info("[auditor_verify_late_entry] SUCCESS")
        return call_uuid

    except Exception as e:
        log_screenshot_web_global(self.driver, title=f"auditor_verify_late_entry FAILED - {str(e)}")
        try:
            html = self.driver.find_element(By.XPATH, LATE_ENTRY_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[auditor_verify_late_entry] table html: {html}")
        except Exception:
            pass
        raise




${STARTED_OWNER}=         Set Variable    Christ1 Christ1
${FIRST_JOINED_OWNER}=    Set Variable    Christ2 Christ2
${REJECTED_OWNER}=        Set Variable    Christ3 Christ3
${SECOND_JOINED_OWNER}=   Set Variable    Christ3 Christ3
${ENDED_OWNER}=           Set Variable    Christ1 Christ1
${REJECTED_INFO}=         Set Variable    Declined
${TIMEOUT}=               Set Variable    120
${POLL_INTERVAL}=         Set Variable    2

auditor_verify_late_entry
...    started_owner=${STARTED_OWNER}
...    first_joined_owner=${FIRST_JOINED_OWNER}
...    rejected_owner=${REJECTED_OWNER}
...    second_joined_owner=${SECOND_JOINED_OWNER}
...    ended_owner=${ENDED_OWNER}
...    rejected_info=${REJECTED_INFO}
...    timeout=${TIMEOUT}
...    poll_interval=${POLL_INTERVAL}







--------------------------------111-1111111

def stop_adb_screenrecord(self) -> None:
    """
    Stops adb screenrecord.
    """
    try:
        for session in self.recording_sessions:
            try:
                session.terminate()
                session.wait(timeout=5)
            except Exception:
                try:
                    session.kill()
                except Exception:
                    pass
    finally:
        del self.recording_sessions[:]


def restart_session(self, terminal):
    """
    Restart WebDriver session.
    :param terminal: terminal where executed
    """
    try:
        if getattr(terminal, "driver", None):
            terminal.stop_session()
    except Exception as e:
        logger.warn(f"Failed to stop previous session for {terminal}: {e}")

    if self._is_android_terminal(terminal):
        force_stop(terminal.udid, "io.appium.uiautomator2.server")
        force_stop(terminal.udid, "io.appium.uiautomator2.server.test")

        self.terminal_assigned_ports.pop(terminal.udid, None)
        self.assign_terminal_port(terminal)

        logger.info(
            f"Restarting Android session for {terminal.udid} with systemPort="
            f"{getattr(terminal, 'session_port', None)}",
            also_to_console=True
        )

        terminal.start_session(AppiumServer.get_appium_url())
    else:
        logger.info(
            f"Restarting browser/desktop session for {terminal}",
            also_to_console=True
        )
        terminal.start_session(AppiumServer.get_appium_url())

















@property
def serial(self):
    """
    Return terminal serial (Android: UDID).
    Tries multiple fallbacks to ensure a usable value.
    """
    # 1. Priorité: udid
    value = getattr(self, "udid", None)

    # 2. Fallback: serial direct
    if not value:
        value = getattr(self, "_serial", None)

    # 3. Fallback: capabilities (si présent)
    if not value and hasattr(self, "capabilities"):
        value = self.capabilities.get("udid") or self.capabilities.get("serial")

    # 4. Fallback: data / metadata éventuelle
    if not value and hasattr(self, "data"):
        value = self.data.get("serial") or self.data.get("udid")

    # 5. Nettoyage
    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return None


@property
def serial_short(self):
    """
    Return last 7 characters of terminal serial.
    Always safe, never crashes.
    """
    serial = self.serial

    # Cas 1: None / vide
    if not serial:
        return "unknown"

    # Cas 2: pas une string (sécurité max)
    if not isinstance(serial, str):
        serial = str(serial)

    serial = serial.strip()

    # Cas 3: string vide après nettoyage
    if not serial:
        return "unknown"

    # Cas 4: longueur < 7
    if len(serial) <= 7:
        return serial

    # Cas normal
    return serial[-7:]




def start_session(self, command_executor) -> TerminalAppium:
    """
    Start WebDriver session
    :param command_executor: Either a string representing URL of the Appium remote server
        or a custom remote_connection.RemoteConnection object.
    """
    if not command_executor:
        raise ValueError(
            f"command_executor is empty for device {self.udid}. "
            f"Cannot create Appium session."
        )

    try:
        logger.info(
            f"Creating Appium driver for device: {self.udid} "
            f"with command_executor: {command_executor} "
            f"and capabilities: {self.data}",
            also_to_console=True
        )

        self.driver = webdriver.Remote(
            command_executor,
            options=UiAutomator2Options().load_capabilities(self.data)
        )

        logger.info(
            f"Driver successfully created for device: {self.udid}",
            also_to_console=True
        )

    except Exception as e:
        logger.info(
            f"Failed to instantiate driver for device: {self.udid}. "
            f"Exception type: {type(e).__name__}. "
            f"Exception message: {e}",
            also_to_console=True
        )
        raise

    return self







@staticmethod
def get_appium_url(port=None):
    """
    Get Appium server URL.
    """
    data = AppiumServerData()

    if port is not None:
        return f"http://127.0.0.1:{port}"

    return data.appium_url




@keyword
def start_terminal_sessions(self, *terminals: Terminal):
    """
    Keyword to start WebDriver session and terminal.
    NOTE! Appium removes application data by default on start.
    :param terminals: terminals to execute on
    """
    handle_tag_based_suite_skip(self.suite_data, terminals)

    tasks = []
    for terminal in terminals:
        self.assign_terminal_port(terminal)

        command_executor = AppiumServer.get_appium_url(terminal.session_port)
        if not command_executor:
            raise ValueError(
                f"No Appium URL for device {terminal.udid} "
                f"(session_port={getattr(terminal, 'session_port', None)})"
            )

        logger.info(
            f"Device {terminal.udid} -> Appium URL: {command_executor}",
            also_to_console=True
        )

        tasks.append(
            lambda terminal=terminal, command_executor=command_executor:
                terminal.start_session(command_executor)
        )

    sessions = self.run_concurrently(tasks)

    self.terminal_sessions.extend(sessions)
    self.test_run_data.write_suite_terminals_metadata(self.terminal_sessions)
    self.test_run_terminals.set_terminal_objects(*terminals)

    self.start_log_and_screen_capture(self.suite_data, setup=True)



def __init__(self, **capabilities):
    # this device port is used to establish reverse port forwarding between host & device
    self.reversePort = 35540

    added_capabilities = {
        "autoGrantPermissions": True,
        "noReset": True,
        "fullReset": False,
        "noSign": True,
        "skipServerInstallation": False,
        "skipDeviceInitialization": False,
        "clearDeviceLogsOnStart": True,
        "androidInstallTimeout": 120000,
        "appWaitForLaunch": False,
        "skipLogcatCapture": False
    }

    capabilities.update(added_capabilities)

    base_capabilities = {
        "autoLaunch": False,
        "platformName": self.platform_name,
        "automationName": self.automation_name,
        "adbExecTimeout": self.adb_exec_timeout,
        "appWaitDuration": self.app_wait_duration,
        "newCommandTimeout": self.new_command_timeout,
        "uiautomator2ServerInstallTimeout": self.uiautomator_server_install_timeout,
        "uiautomator2ServerLaunchTimeout": self.uiautomator_server_launch_timeout,
        "androidInstallTimeout": 120000,
        "clearSystemFiles": True,
        "enforceAppInstall": True,
        "unlockType": "pin",
        "unlockKey": "1234",
        "unlockStrategy": "uiautomator",
        **capabilities
    }

    session_port = self.__dict__.get("session_port")
    if session_port is not None:
        base_capabilities["systemPort"] = session_port

    super().__init__(**base_capabilities)

    self.adb_screenrecord_logger = AdbScreenRecordLogger(
        self.scr_rec_dim["width"],
        self.scr_rec_dim["height"]
    )


def assign_terminal_port(self, terminal: Terminal):
    port = find_free_port()
    self.terminal_assigned_ports[terminal.udid] = port
    terminal.assign_session_port(port)
    logger.info(f"Assigned systemPort {port} to terminal {terminal.udid}")




def restart_session(self, terminal):
    """
    Restart WebDriver session.
    :param terminal: terminal where executed
    """
    for _ in range(10):
        if terminal.udid in get_all_connected_device_serials()[0]:
            break
        time.sleep(2)
    else:
        logger.warn(
            f"{terminal.udid} was not in connected devices when trying to restart session"
        )

    # Ferme proprement l'ancienne session si elle existe
    try:
        if getattr(terminal, "driver", None):
            terminal.stop_session()
    except Exception as e:
        logger.warn(f"Failed to stop previous session for {terminal.udid}: {e}")

    # Tue les restes côté device
    force_stop(terminal.udid, "io.appium.uiautomator2.server")
    force_stop(terminal.udid, "io.appium.uiautomator2.server.test")

    # Libère l'ancien port mémorisé
    self.terminal_assigned_ports.pop(terminal.udid, None)

    # Réassigne un nouveau systemPort
    self.assign_terminal_port(terminal)

    logger.info(
        f"Restarting session for {terminal.udid} with systemPort="
        f"{getattr(terminal, 'session_port', None)}",
        also_to_console=True
    )

    terminal.start_session(AppiumServer.get_appium_url())


def assign_terminal_port(self, terminal: Terminal):
    """
    Assign port number for Appium UiAutomator2 systemPort.
    :param terminal: Terminal getting port number assigned
    """
    port = find_free_port()
    self.terminal_assigned_ports[terminal.udid] = port
    terminal.assign_session_port(port)

    logger.info(
        f"Assigned systemPort {port} to terminal {terminal.udid}",
        also_to_console=True
    )



@keyword
def close_terminal_sessions(self):
    """
    Keyword to close all started WebDriver sessions.
    """
    try:
        for terminal in self.terminal_sessions:
            try:
                terminal.stop_session()
            finally:
                self.terminal_assigned_ports.pop(terminal.udid, None)
    finally:
        self.terminal_sessions.clear()



logger.info(
    f"Creating Appium driver for {self.udid} "
    f"with systemPort={self.data.get('systemPort')} "
    f"and command_executor={command_executor}",
    also_to_console=True
)