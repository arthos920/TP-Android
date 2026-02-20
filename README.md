from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

if not fail_attachment:

    # Wait que l’attachment soit présent
    element = WebDriverWait(self.driver, 5).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, '[data-id="attached-file"]')
        )
    )

    # Récupère les infos fichier
    file_type = element.get_attribute("type")
    url = element.get_attribute("href") or element.get_attribute("src")

    is_mp4 = False
    is_jpeg = False

    # Vérification via type MIME
    if file_type:
        if "mp4" in file_type:
            is_mp4 = True
        if "jpeg" in file_type or "jpg" in file_type:
            is_jpeg = True

    # Vérification via URL (backup)
    if url:
        url = url.lower()
        if url.endswith(".mp4"):
            is_mp4 = True
        if url.endswith(".jpg") or url.endswith(".jpeg"):
            is_jpeg = True

    # Condition finale
    if not (is_mp4 or is_jpeg):
        log_screenshot_web_global(
            self.driver,
            title="The media is not MP4 or JPEG"
        )

        raise Exception("The media is not a video or an image")