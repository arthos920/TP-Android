import threading
import time
import robot.api

def ptt_press(self):
    try:
        self._ptt_stop = False

        def hold_ptt():
            while not self._ptt_stop:
                self.driver.execute_script("mobile: longClickGesture", {
                    "elementId": self.driver.find_element(By.ID, PTT_BTN_ID).id,
                    "duration": 1000
                })

        self._ptt_thread = threading.Thread(target=hold_ptt)
        self._ptt_thread.start()

        robot.api.logger.info("PTT hold started")

    except Exception as e:
        robot.api.logger.error("Does not manage to press PTT: " + str(e))
        raise


def ptt_release(self):
    try:
        self._ptt_stop = True

        if hasattr(self, "_ptt_thread"):
            self._ptt_thread.join(timeout=2)

        robot.api.logger.info("PTT released")

    except Exception as e:
        robot.api.logger.error("Does not manage to release PTT: " + str(e))
        raise