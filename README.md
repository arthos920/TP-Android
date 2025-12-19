def log_screenshot_web_global(driver, title="Web Screenshot"):
    from robot.libraries.BuiltIn import BuiltIn
    import os, time, robot.api.logger

    output_dir = BuiltIn().get_variable_value("${OUTPUT DIR}")
    screenshots_dir = os.path.join(output_dir, "screenshots_web")
    os.makedirs(screenshots_dir, exist_ok=True)

    filename = f"web_{int(time.time()*1000)}.png"
    img_path = os.path.join(screenshots_dir, filename)

    driver.get_screenshot_as_file(img_path)

    rel_path = os.path.join("screenshots_web", filename)

    html_block = f"""
    <div style="border:2px solid #d9534f; padding:10px; margin:10px 0;">
        <h3>📸 {title}</h3>
        <a href="{rel_path}">
            <img src="{rel_path}" style="max-width:600px; border:1px solid #333;">
        </a>
    </div>
    """

    BuiltIn().log(html_block, level="WARN", html=True)