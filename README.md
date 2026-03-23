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
