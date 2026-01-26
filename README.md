def _get_video_call_uuid_from_row(row):
    # 1) tentative via td[data-role='CallUuid']
    uuid_candidates = row.find_elements(By.XPATH, ".//td[@data-role='CallUuid' or @data-role='VideoCallID' or @data-role='VideoCallId']")
    if uuid_candidates:
        txt = (uuid_candidates[0].text or "").strip()
        if txt:
            return txt

    # 2) fallback via attribut data-call-uuid sur le lien download
    dl = row.find_elements(By.XPATH, ".//td[@data-role='SessionRecording']//span[contains(@class,'download-link') and @data-call-uuid]")
    if dl:
        attr = (dl[0].get_attribute("data-call-uuid") or "").strip()
        if attr:
            return attr

    return ""



call_uuid = _get_video_call_uuid_from_row(row0)
if not call_uuid:
    # debug utile : on log ce qu'on voit dans la row
    html = row0.get_attribute("outerHTML")
    log_screenshot_web_global(self.driver, title="verify_video_call FAILED - empty uuid (row html logged)")
    robot.api.logger.info(f"[verify_video_call] row outerHTML: {html}")
    raise Exception("Empty CallUuid in first row (td and data-call-uuid both empty)")
