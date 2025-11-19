from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.by import By
import time

def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        # Pointeur générique (équivalent souris)
        finger = PointerInput(PointerInput.MOUSE, "finger")
        actions = ActionBuilder(self.driver)
        actions.add_action(finger)

        rect = ptt_button.rect
        x = int(rect["x"] + rect["width"] / 2)
        y = int(rect["y"] + rect["height"] / 2)

        # Pointer appui
        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()

        robot.api.logger.info("PTT pressed")

        time.sleep(1)  # durée d'appui

        # Pointer relâché
        actions.pointer_action.pointer_up()
        actions.perform()

        robot.api.logger.info("PTT released")

    except Exception as e:
        robot.api.logger.error("Error pressing/releasing PTT: " + str(e))
        raise