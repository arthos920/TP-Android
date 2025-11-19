from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput

def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        actions = ActionBuilder(self.driver)
        finger = PointerInput(PointerInput.TOUCH, "finger")
        actions.add_action(finger)

        # Appuyer
        actions.pointer_action.move_to(ptt_button)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pause(1)
        robot.api.logger.info("Press on PTT OK")

        # Relâcher
        actions.pointer_action.pointer_up()
        actions.perform()
        robot.api.logger.info("Release PTT button")

    except Exception as e:
        robot.api.logger.info("Does not manage to take the PTT")
        raise Exception("Does not manage to take the PTT")