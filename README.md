from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

def use_ptt_release(self, screenshots=True):
    try:
        # 1. Récupérer le bouton
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        # 2. Appui long (60s max, on arrêtera après)
        self.driver.execute_script("mobile: longClickGesture", {
            "elementId": ptt_button.id,
            "duration": 60000      # peut rester appuyé jusqu'à 60 secondes
        })
        robot.api.logger.info("PTT pressed (long hold started)")

        # 3. Attendre que le terminal passe en 'Transm'
        WebDriverWait(self.driver, 5).until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(@text,'Transm')]"))
        )
        robot.api.logger.info("PTT in transmission mode")

        # 4. Maintien du PTT le temps voulu
        time.sleep(5)  # <--- ajuste si besoin (durée de maintien)

        # 5. RELÂCHEMENT avec un tap hors du bouton
        self.driver.execute_script("mobile: clickGesture", {
            "x": 10,
            "y": 10
        })
        robot.api.logger.info("PTT released")

    except Exception as e:
        robot.api.logger.error("Does not manage to take or release the PTT: " + str(e))
        raise

    # 6. Screenshot si demandé
    if screenshots:
        log_screenshot(self.driver)