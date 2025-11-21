from robot.api.deco import keyword, library
import requests
import subprocess
import time
import os
import signal
import socket

@library
class AppiumServerManager:
    def __init__(self, host='127.0.0.1', port=4723, appium_command='appium'):
        self.host = host
        self.port = port
        self.command = appium_command
        self.process = None
        self.status_urls = [
            f"http://{self.host}:{self.port}/wd/hub/status",
            f"http://{self.host}:{self.port}/status"
        ]

    @keyword("Start Appium Server If Not Running")
    def start_appium_server_if_not_running(self):
        if not self.is_port_in_use(self.port):
            print("[INFO] Starting Appium server...")
            self.process = subprocess.Popen(
                [self.command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=os.name == 'nt'
            )
            self._wait_for_appium()
        else:
            print(f"[INFO] Port {self.port} already in use — assuming Appium is running.")

    def _wait_for_appium(self, timeout=15):
        print("[INFO] Waiting for Appium server to become responsive...")
        for i in range(timeout):
            if self.is_appium_running():
                print(f"[INFO] Appium server is ready (after {i+1}s).")
                return
            time.sleep(1)
        raise RuntimeError("Appium server failed to respond within timeout.")

    @keyword("Is Appium Running")
    def is_appium_running(self):
        for url in self.status_urls:
            try:
                res = requests.get(url, timeout=2)
                if res.status_code == 200:
                    print(f"[INFO] Appium server is up at {url}")
                    return True
            except Exception:
                pass
        return False

    def is_port_in_use(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((self.host, port)) == 0

    @keyword("Stop Appium Server And Kill ADB")
    def stop_appium_server_and_kill_adb(self):
        print("[INFO] Stopping Appium server and ADB...")
        if self.process:
            try:
                if os.name == 'nt':
                    self.process.terminate()
                else:
                    os.kill(self.process.pid, signal.SIGTERM)
                self.process.wait()
                print("[INFO] Appium server terminated.")
            except Exception as e:
                print(f"[WARN] Failed to terminate Appium: {e}")
        else:
            print("[INFO] No Appium process to terminate.")

        try:
            subprocess.run(["adb", "kill-server"], check=True)
            print("[INFO] ADB server killed.")
        except Exception as e:
            print(f"[WARN] Failed to kill ADB server: {e}")