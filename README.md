org_xpath = (
    "//*[@id='organisationTree']"
    "//span[normalize-space()='%s']"
    "/ancestor::vaadin-grid-cell-content[1]"
    "/following-sibling::vaadin-grid-cell-content"
    "[.//span[normalize-space()='%s']][1]"
) % (f"{int(self.rnid):03d}", f"{int(org_id):02d}")
