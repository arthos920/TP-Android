def _is_android_terminal(self, terminal) -> bool:
    platform = getattr(terminal, "platform_name", None) or getattr(terminal, "platformName", None)
    automation = getattr(terminal, "automation_name", None) or getattr(terminal, "automationName", None)

    return platform == "Android" and automation == "UiAutomator2"


@keyword
def start_terminal_sessions(self, *terminals: Terminal):
    """
    Keyword to start WebDriver session and terminal.
    NOTE! Appium removes application data by default on start.
    :param terminals: terminals to execute on
    """
    handle_tag_based_suite_skip(self.suite_data, terminals)

    mobile_tasks = []
    browser_tasks = []

    command_executor = AppiumServer.get_appium_url()
    if not command_executor:
        raise ValueError("AppiumServer.get_appium_url() returned empty value.")

    for terminal in terminals:
        if self._is_android_terminal(terminal):
            self.assign_terminal_port(terminal)

            logger.info(
                f"Assigned systemPort {getattr(terminal, 'session_port', None)} "
                f"to terminal {getattr(terminal, 'udid', terminal)}",
                also_to_console=True
            )

            logger.info(
                f"Device {getattr(terminal, 'udid', terminal)} -> Appium URL: {command_executor}",
                also_to_console=True
            )

            mobile_tasks.append(
                lambda terminal=terminal, command_executor=command_executor:
                    terminal.start_session(command_executor)
            )
        else:
            logger.info(
                f"Browser/Desktop terminal {getattr(terminal, 'udid', terminal)} "
                f"-> Appium URL: {command_executor}",
                also_to_console=True
            )

            browser_tasks.append(terminal.start_session)

    sessions = []

    if mobile_tasks:
        sessions.extend(self.run_concurrently(mobile_tasks))

    if browser_tasks:
        sessions.extend(self.run_concurrently(browser_tasks, command_executor))

    self.terminal_sessions.extend(sessions)
    self.test_run_data.write_suite_terminals_metadata(self.terminal_sessions)
    self.test_run_terminals.set_terminal_objects(*terminals)

    self.start_log_and_screen_capture(self.suite_data, setup=True)



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