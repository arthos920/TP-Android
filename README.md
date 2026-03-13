from typing import Callable
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as expected_conditions
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    JavascriptException,
)

def get_component(
    self,
    find_by,
    value: str,
    expected_condition: Callable = expected_conditions.visibility_of_element_located,
    timeout: float = None,
    throw: bool = True,
    exception_class=ComponentNotFoundException,
) -> WebElement:
    """
    Return first visible element located by using specified search locator.
    Compatible headless / non-headless without changing call sites.
    """
    timeout = self.get_timeout(timeout)

    wait = WebDriverWait(
        self.driver,
        timeout,
        poll_frequency=self.POLL_FREQUENCY,
        ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
    )

    locator = (find_by, value)
    component = None
    last_exception = None

    def _is_headless() -> bool:
        caps = self.driver.capabilities or {}
        browser_name = str(caps.get("browserName", "")).lower()
        args = []

        goog = caps.get("goog:chromeOptions", {})
        if isinstance(goog, dict):
            args.extend(goog.get("args", []))

        moz = caps.get("moz:firefoxOptions", {})
        if isinstance(moz, dict):
            args.extend(moz.get("args", []))

        args_str = " ".join(args).lower()
        return "headless" in args_str or caps.get("headless", False) is True or browser_name == "headlesschrome"

    def _scroll_into_view(element: WebElement) -> None:
        try:
            self.driver.execute_script(
                """
                arguments[0].scrollIntoView({
                    block: 'center',
                    inline: 'center'
                });
                """,
                element,
            )
        except JavascriptException:
            pass

    def _has_real_visibility(element: WebElement) -> bool:
        try:
            return bool(self.driver.execute_script(
                """
                const el = arguments[0];
                if (!el) return false;

                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none') return false;
                if (style.visibility === 'hidden') return false;
                if (style.opacity === '0') return false;

                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
                """,
                element
            ))
        except Exception:
            try:
                return element.is_displayed()
            except Exception:
                return False

    def _wait_default_condition():
        condition = expected_condition(locator)
        return wait.until(condition)

    def _wait_headless_fallback():
        # 1) attendre la présence
        element = wait.until(expected_conditions.presence_of_element_located(locator))

        # 2) scroller
        _scroll_into_view(element)

        # 3) attendre qu'il ait une vraie visibilité exploitable
        def _element_ready(_driver):
            try:
                refreshed = _driver.find_element(*locator)
                _scroll_into_view(refreshed)
                if _has_real_visibility(refreshed):
                    return refreshed
                return False
            except (NoSuchElementException, StaleElementReferenceException):
                return False

        return wait.until(_element_ready)

    try:
        component = _wait_default_condition()
        return component

    except TimeoutException as e:
        last_exception = e

        # Fallback intelligent uniquement si la condition demandée est la visibilité
        if expected_condition == expected_conditions.visibility_of_element_located:
            try:
                component = _wait_headless_fallback()
                return component
            except TimeoutException as fallback_error:
                last_exception = fallback_error

        if throw:
            raise exception_class(
                find_by=find_by,
                locator=value,
                expected_condition=expected_condition(locator),
                timeout=timeout,
                terminal=self
            ) from last_exception

        return None