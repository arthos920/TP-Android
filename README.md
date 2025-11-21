from robot.api.deco import keyword, library
import requests
import subprocess
import time
import os
import signal

@library
class AppiumServerManager:
    def __init__(self, host='localhost', port=4723, appium_command='appium'):
        self.host = host
        self.port = port
        self.url = f'http://{host}:{port}/status'
        self.appium_command = appium_command
        self.process = None  # Référence au process Appium démarré ici

    @keyword("Start Appium Server If Not Running")
    def start_appium_server_if_not_running(self, wait_time=5):
        if not self.is_appium_running():
            print("[INFO] Appium server not running, starting it...")
            self.process = subprocess.Popen(
                [self.appium_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=os.name == 'nt'
            )
            time.sleep(wait_time)
            if not self.is_appium_running():
                raise RuntimeError("Failed to start Appium server.")
        else:
            print("[INFO] Appium server already running.")

    @keyword("Is Appium Running")
    def is_appium_running(self):
        try:
            response = requests.get(self.url, timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    @keyword("Stop Appium Server And Kill ADB")
    def stop_appium_server_and_kill_adb(self):
        print("[INFO] Stopping Appium server and killing ADB...")
        if self.process:
            if os.name == 'nt':
                self.process.terminate()
            else:
                os.kill(self.process.pid, signal.SIGTERM)
            self.process.wait()
            print("[INFO] Appium server terminated.")
        else:
            print("[INFO] No Appium process was started by this script.")

        # Tuer adb proprement
        try:
            subprocess.run(["adb", "kill-server"], check=True)
            print("[INFO] ADB server killed.")
        except FileNotFoundError:
            print("[WARN] ADB not found in PATH.")
        except subprocess.CalledProcessError:
            print("[WARN] Failed to kill ADB server.")