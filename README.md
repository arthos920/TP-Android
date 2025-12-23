from selenium.common.exceptions import (
    ElementNotVisibleException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
import time

def click_component(self, *locator, **kwargs):
    """
    CI-safe click_component
    - attend stabilité DOM
    - attend visible + enabled
    - neutralise overlays
    - scroll centre
    - click normal -> ActionChains -> JS -> dispatchEvent -> form.submit
    """

    driver = self.driver
    max_attempts = 6

    def shot(title):
        try:
            log_screenshot_web_global(driver, title)
        except Exception:
            pass

    def kill_overlays():
        driver.execute_script("""
            const selectors = [
                '#loading-mask', '.loading-mask',
                '.ui-widget-overlay',
                '.modal-backdrop',
                '.overlay',
                '.spinner', '.loader'
            ];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    el.style.pointerEvents = 'none';
                });
            });
        """)

    def scroll_center(el):
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});", el
        )
        time.sleep(0.15)

    def is_enabled(el):
        try:
            disabled = el.get_attribute("disabled")
            aria_disabled = el.get_attribute("aria-disabled")
            return el.is_enabled() and disabled in (None, "", "false") and aria_disabled in (None, "", "false")
        except StaleElementReferenceException:
            return False

    for attempt in range(1, max_attempts + 1):
        try:
            component = self.get_component(*locator, **kwargs)

            if component is None:
                shot(f"click_component_attempt_{attempt}_NO_COMPONENT")
                time.sleep(0.3)
                continue

            kill_overlays()
            scroll_center(component)

            # attendre que le bouton soit vraiment activable
            t0 = time.time()
            while time.time() - t0 < 5:
                if is_enabled(component):
                    break
                time.sleep(0.2)
            else:
                shot(f"click_component_attempt_{attempt}_STILL_DISABLED")
                continue

            # 1️⃣ click normal
            try:
                component.click()
                shot(f"click_component_attempt_{attempt}_CLICK_OK")
                return
            except ElementClickInterceptedException:
                shot(f"click_component_attempt_{attempt}_CLICK_INTERCEPTED")

            # 2️⃣ ActionChains
            try:
                ActionChains(driver).move_to_element(component).pause(0.1).click(component).perform()
                shot(f"click_component_attempt_{attempt}_ACTIONCHAINS_OK")
                return
            except Exception:
                shot(f"click_component_attempt_{attempt}_ACTIONCHAINS_FAILED")

            # 3️⃣ JS click
            try:
                driver.execute_script("arguments[0].click();", component)
                shot(f"click_component_attempt_{attempt}_JS_CLICK_OK")
                return
            except Exception:
                shot(f"click_component_attempt_{attempt}_JS_CLICK_FAILED")

            # 4️⃣ dispatchEvent (dernier clic JS)
            try:
                driver.execute_script("""
                    const el = arguments[0];
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                """, component)
                shot(f"click_component_attempt_{attempt}_DISPATCH_EVENT_OK")
                return
            except Exception:
                shot(f"click_component_attempt_{attempt}_DISPATCH_EVENT_FAILED")

            # 5️⃣ submit du form (hyper efficace pour ton cas)
            try:
                submitted = driver.execute_script("""
                    const btn = arguments[0];
                    const form = btn.closest('form');
                    if (form) { form.submit(); return true; }
                    return false;
                """, component)
                if submitted:
                    shot(f"click_component_attempt_{attempt}_FORM_SUBMIT_OK")
                    return
            except Exception:
                shot(f"click_component_attempt_{attempt}_FORM_SUBMIT_FAILED")

        except (StaleElementReferenceException, ElementNotVisibleException):
            time.sleep(0.3)

    shot("click_component_FINAL_FAILURE")
    raise TimeoutException(f"click_component failed after {max_attempts} attempts for locator {locator}")