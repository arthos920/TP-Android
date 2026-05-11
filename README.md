adb -s R5CWC01H42Y shell am force-stop io.appium.uiautomator2.server
adb -s R5CWC01H42Y shell am force-stop io.appium.uiautomator2.server.test
adb -s R5CWC01H42Y shell am force-stop io.appium.settings


adb -s R5CWC01H42Y uninstall io.appium.uiautomator2.server
adb -s R5CWC01H42Y uninstall io.appium.uiautomator2.server.test
adb -s R5CWC01H42Y uninstall io.appium.settings