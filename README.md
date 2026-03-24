def auditor_verify_group_call(
    self,
    started_owner,
    joined_owners,
    took_the_floor_owners,
    ended_owner,
    timeout=120,
    poll_interval=2,
):

    if isinstance(joined_owners, str):
        joined_owners = [x.strip() for x in joined_owners.split("|") if x.strip()]

    if isinstance(took_the_floor_owners, str):
        took_the_floor_owners = [x.strip() for x in took_the_floor_owners.split("|") if x.strip()]

    def _norm(value):
        return (value or "").strip()

    def _etype_key(event_type_text):
        t = _norm(event_type_text).lower()
        if t == "started call":
            return "started"
        if t == "joined call":
            return "joined"
        if t == "took the floor":
            return "took_floor"
        if t == "ended call":
            return "ended"
        return "other"

    try:
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, GROUP_CALL_TABLE_XPATH))
        )

        end_time = time.monotonic() + timeout
        valid_rows = []

        while time.monotonic() < end_time:
            rows = self.driver.find_elements(By.XPATH, GROUP_CALL_ROWS_XPATH)
            valid_rows = []

            for row in rows:
                try:
                    uuid = _norm(row.find_element(By.XPATH, GROUP_CALL_CALL_UUID_XPATH).text)
                    if uuid:
                        valid_rows.append(row)
                except:
                    continue

            if valid_rows:
                break

            time.sleep(poll_interval)

        if not valid_rows:
            log_screenshot_web_global(self.driver, title="group_call FAILED - no rows")
            raise Exception("No populated rows")

        parsed = []
        call_uuids = set()

        for row in valid_rows:
            owner = _norm(row.find_element(By.XPATH, GROUP_CALL_OWNER_XPATH).text)
            etype = _norm(row.find_element(By.XPATH, GROUP_CALL_TYPE_XPATH).text)
            uuid = _norm(row.find_element(By.XPATH, GROUP_CALL_CALL_UUID_XPATH).text)

            if uuid:
                call_uuids.add(uuid)

            parsed.append({
                "owner": owner,
                "etype_key": _etype_key(etype)
            })

        if len(call_uuids) != 1:
            raise Exception(f"Multiple CallUuid found: {call_uuids}")

        call_uuid = list(call_uuids)[0]

        # UI = reverse chrono
        chrono = list(reversed(parsed))

        # 🔥 Filtrer UNIQUEMENT les events utiles
        filtered = [
            (e["etype_key"], e["owner"])
            for e in chrono
            if e["etype_key"] in ("started", "joined", "took_floor", "ended")
        ]

        # Expected
        expected = [("started", started_owner)]

        for o in joined_owners:
            expected.append(("joined", o))

        for o in took_the_floor_owners:
            expected.append(("took_floor", o))

        expected.append(("ended", ended_owner))

        errors = []

        if len(filtered) != len(expected):
            errors.append(f"Length mismatch: expected {len(expected)}, got {len(filtered)}")

        for i, (exp, obs) in enumerate(zip(expected, filtered), start=1):
            if exp != obs:
                errors.append(f"Mismatch pos {i}: expected {exp}, got {obs}")

        if errors:
            html = self.driver.find_element(By.XPATH, GROUP_CALL_TABLE_XPATH).get_attribute("outerHTML")
            robot.api.logger.info(f"[group_call] HTML: {html}")
            robot.api.logger.info(f"[group_call] expected={expected}")
            robot.api.logger.info(f"[group_call] observed={filtered}")
            log_screenshot_web_global(self.driver, title="group_call FAILED")
            raise Exception(" | ".join(errors))

        robot.api.logger.info("[group_call] SUCCESS")
        return call_uuid

    except Exception as e:
        log_screenshot_web_global(self.driver, title=f"group_call FAILED - {str(e)}")
        raise



${STARTED_OWNER}=             Set Variable    Dispatcher_Christ Dispatcher_Christ
${JOINED_OWNERS}=             Set Variable    Christ1 Christ1|Christ2 Christ2|Christ3 Christ3
${TOOK_THE_FLOOR_OWNERS}=     Set Variable    Christ1 Christ1|Christ2 Christ2|Christ3 Christ3|Dispatcher_Christ Dispatcher_Christ
${ENDED_OWNER}=               Set Variable    Dispatcher_Christ Dispatcher_Christ
${TIMEOUT}=                   Set Variable    120
${POLL_INTERVAL}=             Set Variable    2

auditor_verify_group_call
...    started_owner=${STARTED_OWNER}
...    joined_owners=${JOINED_OWNERS}
...    took_the_floor_owners=${TOOK_THE_FLOOR_OWNERS}
...    ended_owner=${ENDED_OWNER}
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