from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions.action_builder import ActionBuilder

def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        # Création d'un pointeur tactile
        touch = PointerInput(PointerInput.TOUCH, "finger")
        actions = ActionBuilder(self.driver)
        actions.add_action(touch)

        # Déplacement vers l’élément et appui
        actions.pointer_action.move_to(ptt_button)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pause(1)

        robot.api.logger.info("PTT Pressed")

        # Relâchement
        actions.pointer_action.pointer_up()
        actions.perform()

        robot.api.logger.info("PTT Released OK")

    except Exception as e:
        robot.api.logger.error("Does not manage to take the PTT – " + str(e))
        raise Exception("Does not manage to take the PTT")