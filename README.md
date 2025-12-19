def log_screenshot_web(driver):
    from robot.libraries.BuiltIn import BuiltIn
    import os, time, robot.api.logger

    output_dir = BuiltIn().get_variable_value("${OUTPUT DIR}")
    screenshots_dir = os.path.join(output_dir, "screenshots_secure_recorder")
    os.makedirs(screenshots_dir, exist_ok=True)

    filename = f"screenshot_{int(time.time()*1000)}.png"
    img_path = os.path.join(screenshots_dir, filename)

    driver.get_screenshot_as_file(img_path)

    rel_path = os.path.join("screenshots_secure_recorder", filename)

    robot.api.logger.info(
        f'<a href="{rel_path}"><img src="{rel_path}" width="400px"></a>',
        html=True
    )