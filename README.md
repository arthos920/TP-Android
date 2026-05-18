def delete_cache(self, device_id, package_app):

    """
    Clear app data if installed,
    otherwise install the application.
    """

    # Vérifie si l'application existe
    check_cmd = f"adb -s {device_id} shell pm path {package_app}"
    result = self.send_command_with_pipes(check_cmd)

    # Application installée
    if result and "package:" in str(result):

        print(f"{package_app} installé -> clear data")

        cmd_clear = f"adb -s {device_id} shell pm clear {package_app}"
        self.send_command_with_pipes(cmd_clear)

    # Application absente
    else:

        print(f"{package_app} absent -> installation")

        cmd_install = (
            f'adb -s {device_id} install '
            f'"C:\\Users\\labadmin\\Documents\\apk\\g.apk"'
        )

        self.send_command_with_pipes(cmd_install)