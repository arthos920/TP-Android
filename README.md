import time
from typing import Callable

from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    JavascriptException,
    WebDriverException,
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def get_component(
    self,
    find_by,
    value: str,
    expected_condition: Callable = EC.visibility_of_element_located,
    timeout: float = None,
    throw: bool = True,
    exception_class=ComponentNotFoundException,
) -> WebElement:
    """
    Retourne le premier élément trouvé de manière robuste,
    compatible headless / non-headless sans changer les appels existants.
    """
    timeout = self.get_timeout(timeout)
    locator = (find_by, value)

    wait = WebDriverWait(
        self.driver,
        timeout,
        poll_frequency=self.POLL_FREQUENCY,
        ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
    )

    start_time = time.time()
    last_exception = None

    def _remaining_time() -> float:
        return max(0.2, timeout - (time.time() - start_time))

    def _wait_document_ready(max_wait: float = 2.0) -> None:
        """
        Attend un minimum que le DOM soit chargé.
        On ne bloque pas trop longtemps pour ne pas casser le comportement global.
        """
        end = time.time() + max_wait
        while time.time() < end:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.1)

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
        except Exception:
            pass

    def _is_really_visible(element: WebElement) -> bool:
        try:
            return bool(
                self.driver.execute_script(
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
                    element,
                )
            )
        except Exception:
            try:
                return element.is_displayed()
            except Exception:
                return False

    def _find_present_element():
        local_wait = WebDriverWait(
            self.driver,
            _remaining_time(),
            poll_frequency=self.POLL_FREQUENCY,
            ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
        )
        return local_wait.until(EC.presence_of_element_located(locator))

    def _find_with_requested_condition():
        local_wait = WebDriverWait(
            self.driver,
            _remaining_time(),
            poll_frequency=self.POLL_FREQUENCY,
            ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
        )
        return local_wait.until(expected_condition(locator))

    while (time.time() - start_time) < timeout:
        try:
            _wait_document_ready(max_wait=1.0)

            # 1) tentative normale avec la condition demandée
            element = _find_with_requested_condition()

            try:
                _scroll_into_view(element)
            except Exception:
                pass

            return element

        except TimeoutException as e:
            last_exception = e

            # 2) fallback : si la condition demandée est trop stricte,
            #    on tente au moins de récupérer l'élément présent
            try:
                element = _find_present_element()
                _scroll_into_view(element)

                if expected_condition == EC.visibility_of_element_located:
                    if _is_really_visible(element):
                        return element
                else:
                    return element

            except Exception as fallback_error:
                last_exception = fallback_error

        except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
            last_exception = e

        time.sleep(0.2)

    # debug utile en cas d'échec
    try:
        current_url = self.driver.current_url
    except Exception:
        current_url = "<unavailable>"

    try:
        page_state = self.driver.execute_script("return document.readyState")
    except Exception:
        page_state = "<unavailable>"

    if throw:
        raise exception_class(
            find_by=find_by,
            locator=value,
            expected_condition=expected_condition(locator),
            timeout=timeout,
            terminal=self,
            message=(
                f"Unable to locate element {locator} after {timeout} seconds. "
                f"current_url={current_url}, document.readyState={page_state}"
            )
        ) from last_exception

    return None