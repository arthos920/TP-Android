@keyword("Stop Appium Server And Kill ADB")
def stop_appium_server_and_kill_adb(self):
    print("[INFO] Stopping Appium server and killing ADB...")

    # 1. Kill Appium process if it was started by this script
    if self.process:
        try:
            if os.name == 'nt':
                self.process.terminate()
            else:
                os.kill(self.process.pid, signal.SIGTERM)
            self.process.wait()
            print("[INFO] Appium server (started via script) terminated.")
        except Exception as e:
            print(f"[WARN] Could not terminate Appium from script: {e}")
    else:
        print("[INFO] No Appium process started via script.")

    # 2. Manually kill any process using port 4723 (Appium)
    if os.name == 'nt':
        try:
            result = subprocess.check_output("netstat -ano | findstr :4723", shell=True).decode()
            lines = result.strip().split("\n")
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/PID", pid, "/F"], check=True)
                    print(f"[INFO] Killed process with PID {pid} on port 4723.")
        except subprocess.CalledProcessError:
            print("[INFO] No process on port 4723 found to kill.")
    else:
        try:
            result = subprocess.check_output(["lsof", "-i", ":4723"]).decode()
            for line in result.splitlines()[1:]:
                parts = line.split()
                pid = parts[1]
                subprocess.run(["kill", "-9", pid])
                print(f"[INFO] Killed process with PID {pid} on port 4723.")
        except Exception:
            print("[INFO] No process on port 4723 found to kill (or lsof not installed).")

    # 3. Kill adb server
    try:
        subprocess.run(["adb", "kill-server"], check=True)
        print("[INFO] ADB server killed.")
    except Exception as e:
        print(f"[WARN] Failed to kill ADB server: {e}")