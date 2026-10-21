def close_notifications(self):
    """
    Close the Android notification panel using ADB shell.
    """
    self.driver.execute_script(
        "mobile: shell",
        {
            "command": "cmd",
            "args": ["statusbar", "collapse"]
        }
    )