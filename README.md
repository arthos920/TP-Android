from appium.webdriver.common.touch_action import TouchAction

def use_ptt_release(self, screenshots=True):
    try:
        ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)

        action = TouchAction(self.driver)
        action.press(ptt_button).wait(1000).perform()   # Appuie sur le bouton
        robot.api.logger.info("Press on PTT OK")

        time.sleep(1)

        action.release().perform()                     # Relâche le bouton
        robot.api.logger.info("Release PTT button")

    except Exception as e:
        robot.api.logger.info("Does not manage to take the PTT")
        raise Exception("Does not manage to take the PTT")