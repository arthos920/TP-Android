import threading
import robot.api

def start_ptt_long_press(self, duration=8000):
    def task():
        try:
            ptt_button = self.driver.find_element(By.ID, PTT_BTN_ID)
            self.driver.execute_script("mobile: longClickGesture", {
                "elementId": ptt_button.id,
                "duration": int(duration)
            })
            robot.api.logger.info("PTT long press finished")
        except Exception as e:
            robot.api.logger.error("PTT long press failed: " + str(e))
            raise

    self._ptt_thread = threading.Thread(target=task)
    self._ptt_thread.start()