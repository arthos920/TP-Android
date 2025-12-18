$RESULTS_DIR = "results"

if (!(Test-Path $RESULTS_DIR)) {
    New-Item -ItemType Directory -Path $RESULTS_DIR | Out-Null
}

$robotCommand = @"
robot `
  --outputdir $RESULTS_DIR `
  --output output.xml `
  --log log.html `
  --report report.html `
  .
"@

Invoke-Expression $robotCommand




script:
  - set ROBOT_OUTPUT_DIR=results
  - powershell -ExecutionPolicy Bypass -File ./scripts/check_actors_launch.ps1








def log_screenshot(driver):
    import os, time
    from robot.api import logger

    base_dir = os.environ.get("ROBOT_OUTPUT_DIR", "results")
    screenshots_dir = os.path.join(base_dir, "screenshots")

    os.makedirs(screenshots_dir, exist_ok=True)

    filename = f"screenshot_{int(time.time()*1000)}.png"
    img_path = os.path.join(screenshots_dir, filename)

    driver.get_screenshot_as_file(img_path)

    # 🔥 CHEMIN RELATIF
    rel_path = os.path.join("screenshots", filename)

    logger.info(
        f'<a href="{rel_path}"><img src="{rel_path}" width="400px"></a>',
        html=True
    )