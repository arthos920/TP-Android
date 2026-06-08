from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

def ptt_release(self):
    try:
        finger = PointerInput(interaction.POINTER_TOUCH, "finger")
        actions = ActionBuilder(self.driver, mouse=finger)

        actions.pointer_action.pointer_up()
        actions.perform()

        robot.api.logger.info("PTT released")

    except Exception as e:
        robot.api.logger.error("Does not manage to release the PTT: " + str(e))
        raise