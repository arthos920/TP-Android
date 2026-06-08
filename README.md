from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

def ptt_press(self):
    ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

    rect = ptt_button.rect
    x = rect["x"] + rect["width"] // 2
    y = rect["y"] + rect["height"] // 2

    finger = PointerInput(interaction.POINTER_TOUCH, "finger")
    actions = ActionBuilder(self.driver, mouse=finger)

    actions.pointer_action.move_to_location(x, y)
    actions.pointer_action.pointer_down()
    actions.perform()

    robot.api.logger.info("PTT pressed")


def ptt_release(self):
    self.driver.release_actions()
    robot.api.logger.info("PTT released")