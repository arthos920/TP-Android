from selenium.webdriver.support.ui import WebDriverWait

WebDriverWait(self.driver, 20).until(
    lambda d: d.execute_script(
        "return document.querySelectorAll('.tokens-list strong').length > 0"
    )
)

options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-gpu")
options.add_argument("--force-device-scale-factor=1")