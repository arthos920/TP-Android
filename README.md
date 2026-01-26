import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =========================
# LOCATORS
# =========================

VIDEO_STREAM_TABLE_XPATH = "//table[contains(@class,'reports-table') and @data-report-type='video-calls-video-streaming']"
VIDEO_STREAM_ROWS_XPATH = VIDEO_STREAM_TABLE_XPATH + "//tbody/tr"

STREAM_OWNER_XPATH = ".//td[@data-role='EventOwner']"
STREAM_EVENT_TYPE_XPATH = ".//td[@data-role='EventType']"
STREAM_CALL_UUID_XPATH = ".//td[@data-role='CallUuid']"
STREAM_ADDITIONAL_INFO_XPATH = ".//td[@data-role='AdditionalInfo']"
STREAM_DOWNLOAD_LINK_XPATH = ".//td[@data-role='SessionRecording']//span[contains(@class,'download-link')]"


# =========================
# FUNCTION
# =========================

def auditor_verify_streaming_video_strict_order(
    self,
    started_owner,
    ended_owner,
    joined_owners,
    left_owners,
    timeout=120,
    poll_interval=2,
    require_download_link_on_end=True,
):

    joined_owners = joined_owners or []
    left_owners = left_owners or []

    def _norm(s):
        return (s or "").strip()

    def _etype_key(event_type):
        t = _norm(event_type).lower()
        if "started video streaming" in t:
            return "started"
        if "joined in video streaming" in t:
            return "joined"
        if "left video streaming" in t:
            return "left"
        if "ended video streaming" in t:
            return "ended"
        return "other"

    # =========================
    # WAIT FOR TABLE
    # =========================
    WebDriverWait(self.driver, 20).until(
        EC.presence_of_element_located((By.XPATH, VIDEO_STREAM_TABLE_XPATH))
    )

    # =========================
    # WAIT FOR POPULATED ROWS
    # =========================
    end_time = time.monotonic() + timeout
    valid_rows = []

    while time.monotonic() < end_time:
        rows = self.driver.find_elements(By.XPATH, VIDEO_STREAM_ROWS_XPATH)
        valid_rows.clear()

        for r in rows:
            try:
                uuid = _norm(r.find_element(By.XPATH, STREAM_CALL_UUID_XPATH).text)
                if uuid:
                    valid_rows.append(r)
            except Exception:
                continue

        if valid_rows:
            break

        time.sleep(poll_interval)

    if not valid_rows:
        html = self.driver.find_element(By.XPATH, VIDEO_STREAM_TABLE_XPATH).get_attribute("outerHTML")
        robot.api.logger.info(f"[auditor_verify_streaming_video_strict_order] table html:\n{html}")
        log_screenshot_web_global(self.driver, title="auditor_verify_streaming_video_strict_order FAILED - no populated rows")
        raise Exception("No populated rows found (UI async not finished)")

    # =========================
    # PARSE ROWS
    # =========================
    parsed = []
    call_uuids = set()

    for r in valid_rows:
        owner = _norm(r.find_element(By.XPATH, STREAM_OWNER_XPATH).text)
        etype = _norm(r.find_element(By.XPATH, STREAM_EVENT_TYPE_XPATH).text)
        call_uuid = _norm(r.find_element(By.XPATH, STREAM_CALL_UUID_XPATH).text)

        try:
            add_info = _norm(r.find_element(By.XPATH, STREAM_ADDITIONAL_INFO_XPATH).text)
        except Exception:
            add_info = ""

        try:
            dl = r.find_elements(By.XPATH, STREAM_DOWNLOAD_LINK_XPATH)
            dl_uuid = _norm(dl[0].get_attribute("data-call-uuid")) if dl else ""
        except Exception:
            dl_uuid = ""

        call_uuids.add(call_uuid)

        parsed.append({
            "row": r,
            "owner": owner,
            "etype": etype,
            "key": _etype_key(etype),
            "call_uuid": call_uuid,
            "download_uuid": dl_uuid,
            "additional": add_info
        })

    if len(call_uuids) != 1:
        raise Exception(f"Expected 1 CallUUID, got {len(call_uuids)} → {call_uuids}")

    call_uuid = next(iter(call_uuids))
    robot.api.logger.info(f"[auditor_verify_streaming_video_strict_order] call_uuid = {call_uuid}")

    # =========================
    # CHRONO ORDER (reverse)
    # =========================
    chrono = list(reversed(parsed))

    # =========================
    # EXPECTED SEQUENCE
    # =========================
    expected = []
    expected.append(("started", started_owner))
    expected.extend([("joined", o) for o in joined_owners])
    expected.extend([("left", o) for o in left_owners])
    expected.append(("ended", ended_owner))

    # =========================
    # OBSERVED SEQUENCE
    # =========================
    observed = [(e["key"], e["owner"]) for e in chrono if e["key"] in ("started", "joined", "left", "ended")]

    robot.api.logger.info(f"[auditor_verify_streaming_video_strict_order] expected={expected}")
    robot.api.logger.info(f"[auditor_verify_streaming_video_strict_order] observed={observed}")

    # =========================
    # STRICT ORDER CHECK
    # =========================
    errors = []

    if len(observed) != len(expected):
        errors.append(f"Sequence length mismatch: expected {len(expected)}, got {len(observed)}")

    else:
        for i, (exp, obs) in enumerate(zip(expected, observed), start=1):
            if exp != obs:
                errors.append(f"Mismatch at pos {i}: expected {exp}, got {obs}")

    # =========================
    # DOWNLOAD LINK CHECK
    # =========================
    if require_download_link_on_end:
        ended_event = next((e for e in chrono if e["key"] == "ended"), None)
        if not ended_event:
            errors.append("Missing ended event")
        elif not ended_event["download_uuid"]:
            errors.append("Ended event has no download link uuid")

    if errors:
        html = self.driver.find_element(By.XPATH, VIDEO_STREAM_TABLE_XPATH).get_attribute("outerHTML")
        robot.api.logger.info(f"[auditor_verify_streaming_video_strict_order] table html:\n{html}")
        log_screenshot_web_global(self.driver, title="auditor_verify_streaming_video_strict_order FAILED")
        raise Exception(" | ".join(errors))

    robot.api.logger.info("[auditor_verify_streaming_video_strict_order] SUCCESS")
    return call_uuid