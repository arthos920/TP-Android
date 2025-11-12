￼from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def handle_turn_on_location_tags(self):

    try:
        wait = WebDriverWait(self.driver, 5)  # attend jusqu’à 5 secondes

        # Attend que le titre de la pop-up soit visible
        alert = wait.until(
            EC.presence_of_element_located(
                (AppiumBy.ID, "com.sec.android.app.camera:id/alertTitle")
            )
        )

        # Vérifie que c’est bien la bonne pop-up
        if alert and "Turn on Location tags" in alert.text:
            # Attend que le bouton 'Turn on' soit cliquable
            turn_on_btn = wait.until(
                EC.element_to_be_clickable((AppiumBy.ID, "android:id/button1"))
            )
            turn_on_btn.click()
            print("Bouton 'Turn on' cliqué avec succès.")
        else:
            print("La pop-up détectée n’est pas celle attendue.")

    except TimeoutException:
        # Si la pop-up n’apparaît pas dans le délai, on ignore
        print("Aucune pop-up 'Turn on Location tags?' détectée.")