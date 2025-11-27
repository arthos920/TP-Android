def verify_PTT_call(self, alias_initiator, alias_participant, call_type=None, floor_time=None, datafile="FROM_SETTINGS_FILE"):

    # -----------------------------------------------
    # 1. Load expected Initiator / Participant from Excel
    # -----------------------------------------------
    excelDict_initiator = SecureRecorderModule().initialize(alias_initiator, datafile)
    expected_initiator = f"{excelDict_initiator['FirstName']} {excelDict_initiator['LastName']}"

    excelDict_participant = SecureRecorderModule().initialize(alias_participant, datafile)
    expected_participant = f"{excelDict_participant['FirstName']} {excelDict_participant['LastName']}"

    # -----------------------------------------------
    # 2. Set call type defaults if missing
    # -----------------------------------------------
    if call_type is None:
        call_type = "PTT Call"

    expected_floor_time = floor_time

    # -----------------------------------------------
    # 3. Open the toggle menu
    # -----------------------------------------------
    try:
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-id='toggle-menu-button']"))
        ).click()

    except:
        log_screenshot(self.driver)
        robot.api.logger.info("There is no item for your research")
        for i in range(7):
            time.sleep(5)
            try:
                self.driver.find_element(By.XPATH, AUDITOR_BUTTON_SWAP_ORDER).click()
                WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-id='toggle-menu-button']"))
                ).click()
                break
            except:
                log_screenshot(self.driver)
        else:
            raise Exception("No item found after multiple attempts")

    # ----------------------------------------------------
    # 4. VERIFY INITIATOR — REACT-FIBER SAFE VERSION
    # ----------------------------------------------------
    initiator_xpath = (
        "//div[@data-id='title' and contains(normalize-space(), 'Initiator')]"
        "/following-sibling::div[@data-id='value'][1]"
        "//span[@data-id='usergroup-user']"
    )

    # Wait for the element to be PRESENT (React Fiber safe)
    initiator_element = WebDriverWait(self.driver, 20).until(
        EC.presence_of_element_located((By.XPATH, initiator_xpath))
    )

    # Wait for React to hydrate text
    actual_initiator = ""
    for _ in range(15):
        txt = initiator_element.text.strip()
        if txt:
            actual_initiator = txt
            break
        time.sleep(0.2)

    if not actual_initiator:
        raise Exception("Initiator text did not load (React hydration delay).")

    # Compare expected vs actual
    if expected_initiator not in actual_initiator:
        raise Exception(
            f"Initiator mismatch. Expected: {expected_initiator}, Actual: {actual_initiator}"
        )

    robot.api.logger.info(f"Initiator OK: {actual_initiator}")

    # ----------------------------------------------------
    # 5. (Optionnel) Tu peux ajouter ici les autres checks :
    #    - participant
    #    - call type
    #    - floor time
    # ----------------------------------------------------