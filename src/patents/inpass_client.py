"""InPASS (Indian Patent Advanced Search System) browser client.

Automates search navigation and patent retrieval against the official Indian Patent Office
public search portal (iprsearch.ipindia.gov.in) using Selenium WebDriver.

Features:
- Clean browser lifecycle with isolated temporary Chrome user profiles
- Fully parameterized search configuration (Title, Abstract, Application Date, Published/Granted)
- Human-in-the-loop CAPTCHA checkpoint with callback hooks and reactive detection
- Search results extraction and multi-page navigation
- Retrieval of full PatentDetails HTML and integration with parse_inpass_patent_details()
"""

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, Optional, Sequence
import uuid

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from src.patents.base_client import BasePatentClient, PatentClientError
from src.patents.inpass_parser import parse_inpass_patent_details
from src.patents.models import InPassPatentRecord

logger = logging.getLogger(__name__)

INPASS_DEFAULT_URL = "https://iprsearch.ipindia.gov.in/publicsearch"


class InPassClientError(PatentClientError):
    """Base exception for all InPASS search client errors."""
    pass


class InPassBrowserError(InPassClientError):
    """Raised when browser initialization, execution, or shutdown fails."""
    pass


class InPassNavigationError(InPassClientError):
    """Raised when navigating or locating elements on InPASS pages fails."""
    pass


class InPassCaptchaTimeoutError(InPassClientError):
    """Raised when the human-in-the-loop CAPTCHA checkpoint exceeds timeout."""
    pass


class InPassSearchError(InPassClientError):
    """Raised when search execution or results retrieval encounters an error."""
    pass


@dataclass(frozen=True)
class InPassSearchConfig:
    """Configuration parameters for configuring an InPASS patent search query."""

    keyword: str
    field_type: str = "TI"  # TI = Title, AB = Abstract, CS = Complete Spec, APN = App Num
    published: bool = True
    granted: bool = False
    date_field: str = "APD"  # APD = Application Date (National), PD = Publication Date
    logic_field: str = "AND"

    def __post_init__(self) -> None:
        if not isinstance(self.keyword, str) or not self.keyword.strip():
            raise ValueError("keyword must be a non-empty string.")


@dataclass(frozen=True)
class InPassSearchResultRow:
    """Summary record parsed from an InPASS search results table row."""

    application_number: str
    title: str = ""
    date: Optional[str] = None
    status: Optional[str] = None
    raw_cells: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialize row to dictionary format."""
        return {
            "application_number": self.application_number,
            "title": self.title,
            "date": self.date,
            "status": self.status,
            "raw_cells": list(self.raw_cells),
        }


class InPassClient(BasePatentClient):
    """Production client for interacting with the official InPASS public search portal.

    Maintains a visible or configured Chrome browser session with an isolated temporary
    profile, provides search form filling, human CAPTCHA checkpoint waiting, pagination,
    and PatentDetails extraction.
    """

    def __init__(
        self,
        base_url: str = INPASS_DEFAULT_URL,
        headless: bool = False,
        timeout: float = 30.0,
        captcha_timeout: float = 600.0,
        user_data_dir: Optional[str] = None,
        driver: Optional[WebDriver] = None,
    ) -> None:
        """Initialize the InPASS client.

        Args:
            base_url: Public search URL. Defaults to the official portal URL.
            headless: Whether to run Chrome headlessly. Defaults to False because
                      CAPTCHA requires human entry in the browser window.
            timeout: Default explicit wait timeout in seconds for DOM elements.
            captcha_timeout: Timeout in seconds to wait for human CAPTCHA submission.
            user_data_dir: Optional existing Chrome profile directory. If None, a dedicated
                           temporary directory is created and cleaned up automatically.
            driver: Optional pre-configured WebDriver (useful for dependency injection/tests).
        """
        self.base_url = base_url
        self.headless = headless
        self.timeout = timeout
        self.captcha_timeout = captcha_timeout
        self.custom_user_data_dir = user_data_dir

        self.driver: Optional[WebDriver] = driver
        self._temp_profile_dir: Optional[str] = None
        self._owns_driver: bool = driver is None

    def start_browser(self) -> WebDriver:
        """Launch the Chrome browser session with dedicated profile and anti-crash options.

        Returns:
            WebDriver: The initialized Selenium Chrome WebDriver instance.

        Raises:
            InPassBrowserError: If Chrome fails to launch.
        """
        if self.driver is not None:
            return self.driver

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

        # Dedicated profile directory prevents locks/crashes from existing user sessions
        if self.custom_user_data_dir:
            profile_path = self.custom_user_data_dir
        else:
            self._temp_profile_dir = tempfile.mkdtemp(prefix="chrome_inpass_profile_")
            profile_path = self._temp_profile_dir

        chrome_options.add_argument(f"--user-data-dir={profile_path}")

        try:
            logger.info("Starting Chrome browser for InPASS (profile: %s)", profile_path)
            self.driver = webdriver.Chrome(options=chrome_options)
            self._owns_driver = True
            return self.driver
        except Exception as err:
            self._cleanup_profile()
            raise InPassBrowserError(f"Failed to start Chrome browser: {err}") from err

    def close_browser(self) -> None:
        """Quit the browser session and cleanly remove temporary profile directories."""
        if self.driver is not None and self._owns_driver:
            try:
                logger.info("Closing Chrome browser session.")
                self.driver.quit()
            except Exception as err:
                logger.warning("Error while closing Chrome driver: %s", err)
            finally:
                self.driver = None

        self._cleanup_profile()

    def _cleanup_profile(self) -> None:
        """Delete temporary profile folder if one was generated."""
        if self._temp_profile_dir and Path(self._temp_profile_dir).exists():
            try:
                shutil.rmtree(self._temp_profile_dir, ignore_errors=True)
            except Exception as err:
                logger.warning("Failed to clean temporary profile dir %s: %s", self._temp_profile_dir, err)
            finally:
                self._temp_profile_dir = None

    def __enter__(self) -> "InPassClient":
        """Context manager entry point."""
        self.start_browser()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit point."""
        self.close_browser()

    def _get_driver(self) -> WebDriver:
        """Ensure browser is running and return driver instance."""
        if self.driver is None:
            return self.start_browser()
        return self.driver

    def open_search_page(self, url: Optional[str] = None) -> None:
        """Navigate browser to the InPASS public search page and wait for form elements.

        Args:
            url: Target URL. Defaults to self.base_url.

        Raises:
            InPassNavigationError: If page cannot be reached or form doesn't load.
        """
        driver = self._get_driver()
        target_url = url or self.base_url
        logger.info("Navigating to InPASS search page: %s", target_url)

        try:
            driver.get(target_url)
            wait = WebDriverWait(driver, self.timeout)
            wait.until(EC.presence_of_element_located((By.NAME, "ItemField1")))
        except (TimeoutException, WebDriverException) as err:
            raise InPassNavigationError(f"Failed to load InPASS search page ({target_url}): {err}") from err

    def configure_search(
        self,
        config_or_query: Optional[InPassSearchConfig | str] = None,
        keyword: Optional[str] = None,
        field_type: str = "TI",
        published: bool = True,
        granted: bool = False,
        date_field: str = "APD",
        logic_field: str = "AND",
    ) -> InPassSearchConfig:
        """Fill in the InPASS search criteria according to configuration.

        Args:
            config_or_query: An InPassSearchConfig object or a string keyword query.
            keyword: Alternate keyword argument for the query string.
            field_type: Field dropdown selection code if config_or_query is string (default 'TI').
            published: Check 'Published' status if config_or_query is string.
            granted: Check 'Granted' status if config_or_query is string.
            date_field: Date select code if config_or_query is string (default 'APD').
            logic_field: Boolean logic code if config_or_query is string (default 'AND').

        Returns:
            InPassSearchConfig: The applied search configuration.

        Raises:
            InPassNavigationError: If form elements are missing or cannot be interacted with.
        """
        if isinstance(config_or_query, InPassSearchConfig):
            cfg = config_or_query
        else:
            target_keyword = keyword or (config_or_query if isinstance(config_or_query, str) else "")
            cfg = InPassSearchConfig(
                keyword=target_keyword,
                field_type=field_type,
                published=published,
                granted=granted,
                date_field=date_field,
                logic_field=logic_field,
            )

        driver = self._get_driver()
        try:
            # 1. Published checkbox
            pub_el = driver.find_element(By.ID, "Published")
            if pub_el.is_selected() != cfg.published:
                pub_el.click()

            # 2. Granted checkbox
            grant_el = driver.find_element(By.ID, "Granted")
            if grant_el.is_selected() != cfg.granted:
                grant_el.click()

            # 3. Date field dropdown (optional on some portal variants)
            try:
                date_select = Select(driver.find_element(By.ID, "DateField"))
                date_select.select_by_value(cfg.date_field)
            except Exception:
                pass

            # 4. Search criteria field dropdown (e.g. Title 'TI')
            item_select = Select(driver.find_element(By.NAME, "ItemField1"))
            item_select.select_by_value(cfg.field_type)

            # 5. Search text input
            text_input = driver.find_element(By.NAME, "TextField1")
            text_input.clear()
            text_input.send_keys(cfg.keyword)

            # 6. Logic field dropdown
            try:
                logic_select = Select(driver.find_element(By.NAME, "LogicField1"))
                logic_select.select_by_value(cfg.logic_field)
            except Exception:
                pass

            logger.info("InPASS search form configured: keyword='%s', field='%s'", cfg.keyword, cfg.field_type)
            return cfg
        except WebDriverException as err:
            raise InPassNavigationError(f"Failed to configure InPASS search fields: {err}") from err

    def capture_captcha_image(self, output_path: Optional[str] = None) -> str:
        """Capture the currently rendered InPASS CAPTCHA element directly from the browser session.

        Uses Selenium element screenshot to capture the rendered pixels without making a separate
        HTTP request, ensuring the captured image matches the active session challenge.

        Args:
            output_path: Optional destination file path. If None, a unique temp PNG is generated.

        Returns:
            str: Resolved absolute path to the saved PNG image.

        Raises:
            InPassNavigationError: If the CAPTCHA element is not found in the DOM or screenshot fails.
        """
        driver = self._get_driver()
        try:
            captcha_elements = driver.find_elements(By.ID, "Captcha")
            if not captcha_elements:
                captcha_elements = driver.find_elements(
                    By.XPATH, "//img[@id='Captcha' or contains(@src, 'GetCaptchaImage')]"
                )

            if not captcha_elements:
                raise InPassNavigationError("CAPTCHA image element '#Captcha' not found on the page.")

            captcha_el = captcha_elements[0]

            if output_path is None:
                target_dir = Path(tempfile.gettempdir())
                resolved_path = target_dir / f"inpass_captcha_{uuid.uuid4().hex[:8]}.png"
            else:
                resolved_path = Path(output_path).resolve()

            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            captcha_el.screenshot(str(resolved_path))
            if not resolved_path.exists() or resolved_path.stat().st_size == 0:
                png_bytes = captcha_el.screenshot_as_png
                with open(resolved_path, "wb") as f:
                    f.write(png_bytes)

            logger.info("Captured InPASS CAPTCHA screenshot to %s", resolved_path)
            return str(resolved_path)
        except WebDriverException as err:
            raise InPassNavigationError(f"Failed to capture CAPTCHA image: {err}") from err

    def submit_captcha(self, captcha_text: str) -> None:
        """Fill the CAPTCHA code input field and submit the search form.

        Args:
            captcha_text: The solved CAPTCHA string.

        Raises:
            ValueError: If captcha_text is empty or not a string.
            InPassNavigationError: If CAPTCHA input or submit button cannot be interacted with.
        """
        if not isinstance(captcha_text, str) or not captcha_text.strip():
            raise ValueError("captcha_text must be a non-empty string.")

        clean_text = captcha_text.strip()
        driver = self._get_driver()

        try:
            input_elements = driver.find_elements(By.ID, "CaptchaText")
            if not input_elements:
                input_elements = driver.find_elements(By.NAME, "CaptchaText")

            if not input_elements:
                raise InPassNavigationError("CAPTCHA input field '#CaptchaText' not found.")

            text_input = input_elements[0]
            text_input.clear()
            text_input.send_keys(clean_text)

            submit_elements = driver.find_elements(
                By.XPATH,
                "//input[@type='submit' and @value='Search'] | //button[@type='submit' and contains(., 'Search')]",
            )
            if not submit_elements:
                submit_elements = driver.find_elements(By.NAME, "submit")

            if not submit_elements:
                raise InPassNavigationError("Search submit button not found.")

            submit_btn = submit_elements[0]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
            time.sleep(0.2)
            try:
                submit_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", submit_btn)

            logger.info("Submitted CAPTCHA text '%s' to InPASS search form.", clean_text)
        except WebDriverException as err:
            raise InPassNavigationError(f"Failed to submit CAPTCHA: {err}") from err

    def wait_for_captcha_and_results(
        self,
        timeout: Optional[float] = None,
        poll_interval: float = 0.5,
        on_captcha_required: Optional[Callable[[str], None]] = None,
        captcha_solver: Optional[Callable[[str], str]] = None,
    ) -> bool:
        """Pause execution for human CAPTCHA entry and wait for results page detection.

        Supports both manual visible browser entry (when captcha_solver is None) and
        two-way in-chat/headless CAPTCHA challenge via captcha_solver callback.

        Args:
            timeout: Seconds to wait before raising InPassCaptchaTimeoutError.
                     Defaults to self.captcha_timeout.
            poll_interval: Seconds between DOM polling checks.
            on_captcha_required: Optional notification callback invoked once when checkpoint begins.
            captcha_solver: Optional callback accepting (image_path: str) and returning (captcha_text: str).

        Returns:
            bool: True once the results page is detected.

        Raises:
            InPassCaptchaTimeoutError: If results page is not detected within the timeout.
            InPassNavigationError: On navigation or element interaction failure.
        """
        driver = self._get_driver()
        wait_limit = timeout if timeout is not None else self.captcha_timeout

        if captcha_solver is not None:
            image_path = self.capture_captcha_image()
            if on_captcha_required:
                try:
                    on_captcha_required(f"CAPTCHA image captured: {image_path}")
                except Exception as cb_err:
                    logger.warning("Error in on_captcha_required callback: %s", cb_err)

            logger.info("Invoking captcha_solver with image: %s", image_path)
            captcha_solution = captcha_solver(image_path)
            if not captcha_solution or not str(captcha_solution).strip():
                raise ValueError("captcha_solver returned an empty CAPTCHA string.")

            self.submit_captcha(str(captcha_solution).strip())
        else:
            instruction_msg = (
                "=================================================================\n"
                ">>> CHECKPOINT: Please enter the CAPTCHA manually and submit. <<<\n"
                "================================================================="
            )
            if on_captcha_required:
                try:
                    on_captcha_required(instruction_msg)
                except Exception as cb_err:
                    logger.warning("Error in on_captcha_required callback: %s", cb_err)
            else:
                logger.info(instruction_msg)

        start_time = time.time()
        initial_url = driver.current_url

        while time.time() - start_time < wait_limit:
            try:
                current_url = driver.current_url
                page_source = driver.page_source

                # Detection criteria for InPASS results table arrival
                has_page_btns = len(driver.find_elements(By.XPATH, "//button[@name='page']")) > 0
                has_app_btns = len(driver.find_elements(By.XPATH, "//*[@name='ApplicationNumber']")) > 0
                has_result_rows = (
                    len(
                        driver.find_elements(
                            By.XPATH,
                            "//table//tr[td[contains(., 'Published') or contains(., '202') or contains(., '199')]]",
                        )
                    )
                    > 0
                )
                url_changed = (current_url != initial_url) and (
                    "/search" in current_url.lower() or "publicationsearch" in current_url.lower()
                )

                if has_page_btns or has_app_btns or has_result_rows or ("total document" in page_source.lower() and url_changed):
                    logger.info("InPASS search results detected successfully.")
                    return True

                if "invalid captcha" in page_source.lower():
                    logger.warning("InPASS indicated 'Invalid captcha'.")
                    if captcha_solver is not None:
                        time.sleep(1.0)
                        image_path = self.capture_captcha_image()
                        logger.info("Re-invoking captcha_solver with new CAPTCHA: %s", image_path)
                        captcha_solution = captcha_solver(image_path)
                        if captcha_solution and str(captcha_solution).strip():
                            self.submit_captcha(str(captcha_solution).strip())
                    else:
                        time.sleep(1.5)
                    continue

            except WebDriverException:
                pass

            time.sleep(poll_interval)

        raise InPassCaptchaTimeoutError(
            f"Timed out waiting for human CAPTCHA submission and search results ({wait_limit}s)."
        )

    def read_current_page_results(self) -> list[InPassSearchResultRow]:
        """Parse patent summary rows from the currently displayed search results page.

        Returns:
            list[InPassSearchResultRow]: Extracted patent rows from the table.

        Raises:
            InPassSearchError: If no results table can be found or parsed.
        """
        driver = self._get_driver()
        rows: list[InPassSearchResultRow] = []

        try:
            # Find all table rows containing data cells
            tr_elements = driver.find_elements(By.XPATH, "//table//tr[td]")
            for tr in tr_elements:
                tds = tr.find_elements(By.TAG_NAME, "td")
                if not tds:
                    continue

                cell_texts = [td.text.strip() for td in tds]
                if not any(cell_texts):
                    continue

                # Ignore header rows that may be rendered using td
                first_text = cell_texts[0].lower()
                if "application" in first_text and "number" in first_text:
                    continue

                # Column 0: Application Number (may be inside a button or text)
                app_num = cell_texts[0]
                btn_matches = tr.find_elements(By.XPATH, ".//*[@name='ApplicationNumber']")
                if btn_matches:
                    val = btn_matches[0].get_attribute("value") or btn_matches[0].text.strip()
                    if val:
                        app_num = val.strip()

                title = cell_texts[1] if len(cell_texts) > 1 else ""
                date_val = cell_texts[2] if len(cell_texts) > 2 else None
                status = cell_texts[3] if len(cell_texts) > 3 else None

                if app_num:
                    rows.append(
                        InPassSearchResultRow(
                            application_number=app_num,
                            title=title,
                            date=date_val,
                            status=status,
                            raw_cells=tuple(cell_texts),
                        )
                    )

            logger.info("Read %d patent result rows from current page.", len(rows))
            return rows
        except WebDriverException as err:
            raise InPassSearchError(f"Failed to read result rows from search page: {err}") from err

    def get_available_pages(self) -> list[int]:
        """Retrieve list of available page numbers from pagination controls.

        Returns:
            list[int]: Sorted list of distinct available page numbers.
        """
        driver = self._get_driver()
        pages: set[int] = set()
        try:
            page_btns = driver.find_elements(By.XPATH, "//button[@name='page']")
            for btn in page_btns:
                val = btn.get_attribute("value") or btn.text.strip()
                if val and val.isdigit():
                    pages.add(int(val))
        except WebDriverException:
            pass
        return sorted(pages)

    def go_to_page(self, page_number: int, timeout: float = 30.0) -> bool:
        """Navigate to a specific result page by clicking its pagination button.

        Args:
            page_number: Target 1-based page number.
            timeout: Seconds to wait for new page content to load.

        Returns:
            bool: True if page navigation succeeded.

        Raises:
            InPassNavigationError: If page button is not found or page fails to load.
        """
        driver = self._get_driver()
        logger.info("Navigating to InPASS results page %d", page_number)

        try:
            p_buttons = driver.find_elements(By.XPATH, f"//button[@name='page' and @value='{page_number}']")
            if not p_buttons:
                p_buttons = driver.find_elements(By.CSS_SELECTOR, f"button[name='page'][value='{page_number}']")

            if not p_buttons:
                raise InPassNavigationError(f"Pagination button for page {page_number} not found.")

            target_btn = p_buttons[0]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
            time.sleep(0.3)

            try:
                target_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", target_btn)

            # Wait for results table to be present and stable
            wait = WebDriverWait(driver, timeout)
            wait.until(EC.presence_of_element_located((By.XPATH, "//table//tr[td]")))
            time.sleep(0.5)
            return True
        except (TimeoutException, WebDriverException) as err:
            raise InPassNavigationError(f"Failed to navigate to page {page_number}: {err}") from err

    def open_patent_details(self, application_number: str, timeout: float = 30.0) -> str:
        """Click the application on the results page, wait for PatentDetails, and capture HTML.

        Args:
            application_number: Target patent application number.
            timeout: Maximum seconds to wait for PatentDetails page to load.

        Returns:
            str: Raw HTML payload of the PatentDetails page.

        Raises:
            InPassNavigationError: If the application cannot be found or details fail to load.
        """
        driver = self._get_driver()
        clean_app = application_number.strip()
        logger.info("Opening PatentDetails for application: %s", clean_app)

        initial_handles = driver.window_handles
        initial_window = driver.current_window_handle

        try:
            app_elements = driver.find_elements(
                By.XPATH,
                f"//button[@name='ApplicationNumber' and (@value='{clean_app}' or contains(text(), '{clean_app}'))] "
                f"| //input[@name='ApplicationNumber' and @value='{clean_app}'] "
                f"| //tr[contains(., '{clean_app}')]//*[@name='ApplicationNumber'] "
                f"| //tr[contains(., '{clean_app}')]//button "
                f"| //tr[contains(., '{clean_app}')]//a",
            )

            if app_elements:
                target_el = app_elements[0]
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_el)
                time.sleep(0.3)
                try:
                    target_el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", target_el)
            else:
                # Direct POST submission fallback if link element is obscured or virtualized
                submit_script = f"""
                    var form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '/PublicSearch/PublicationSearch/PatentDetails';
                    form.target = '_self';
                    var f1 = document.createElement('input'); f1.name = 'ApplicationNumber'; f1.value = '{clean_app}'; form.appendChild(f1);
                    var f2 = document.createElement('input'); f2.name = 'ConnectionName'; f2.value = 'PublicationConnection'; form.appendChild(f2);
                    var f3 = document.createElement('input'); f3.name = 'IP'; f3.value = '163.53.207.117'; form.appendChild(f3);
                    document.body.appendChild(form);
                    form.submit();
                """
                driver.execute_script(submit_script)

            # Wait for PatentDetails DOM content to load
            start_time = time.time()
            pd_loaded = False
            while time.time() - start_time < timeout:
                try:
                    new_handles = driver.window_handles
                    if len(new_handles) > len(initial_handles):
                        for h in new_handles:
                            if h != initial_window:
                                driver.switch_to.window(h)
                                break

                    src_lower = driver.page_source.lower()
                    if (
                        "complete specification" in src_lower
                        or "complete_specification" in src_lower
                        or "patent details" in src_lower
                        or clean_app.lower() in src_lower
                    ):
                        pd_loaded = True
                        break
                except WebDriverException:
                    pass
                time.sleep(0.4)

            if not pd_loaded:
                raise InPassNavigationError(f"PatentDetails page did not load for application {clean_app}.")

            return driver.page_source
        except WebDriverException as err:
            raise InPassNavigationError(f"Error opening PatentDetails for {clean_app}: {err}") from err

    def get_patent_details(
        self,
        application_number: str,
        return_to_search: bool = True,
        timeout: float = 30.0,
    ) -> InPassPatentRecord:
        """Fetch and parse full PatentDetails for an application into canonical InPassPatentRecord.

        Args:
            application_number: Target patent application number.
            return_to_search: If True, closes the details tab or navigates back to preserve search page state.
            timeout: Maximum seconds to wait for PatentDetails page to load.

        Returns:
            InPassPatentRecord: Fully parsed immutable patent record.

        Raises:
            InPassNavigationError: On navigation failure.
            InPassParserError: If captured HTML cannot be parsed.
        """
        driver = self._get_driver()
        clean_app = application_number.strip()
        initial_handles = driver.window_handles
        initial_window = driver.current_window_handle

        html_content = self.open_patent_details(clean_app, timeout=timeout)
        canonical_url = f"https://iprsearch.ipindia.gov.in/publicsearch?app={clean_app}"
        record = parse_inpass_patent_details(html_content, source_url=canonical_url)

        if return_to_search:
            try:
                current_handles = driver.window_handles
                if len(current_handles) > len(initial_handles):
                    # Close the newly opened child window and return to parent
                    driver.close()
                    driver.switch_to.window(initial_window)
                else:
                    # Same window navigation - go back
                    driver.back()
                    time.sleep(0.5)
            except Exception as nav_back_err:
                logger.warning("Error returning to search page: %s", nav_back_err)

        return record

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Execute search conforming to the BasePatentClient contract.

        Opens search page, fills query in Title field, pauses for CAPTCHA submission,
        and retrieves up to max_results summary records from the result pages.

        Args:
            query: Keyword query string.
            max_results: Maximum candidate records to return.

        Returns:
            list[dict]: List of raw search result dictionary records.

        Raises:
            InPassClientError: On search or browser error.
        """
        self.open_search_page()
        self.configure_search(query)
        self.wait_for_captcha_and_results()

        collected: list[dict] = []
        rows = self.read_current_page_results()
        for r in rows:
            collected.append(r.to_dict())
            if len(collected) >= max_results:
                return collected

        # Navigate subsequent pages if more records requested
        page_num = 2
        while len(collected) < max_results:
            available = self.get_available_pages()
            if page_num not in available:
                break
            try:
                self.go_to_page(page_num)
            except InPassNavigationError:
                break

            page_rows = self.read_current_page_results()
            if not page_rows:
                break
            for r in page_rows:
                collected.append(r.to_dict())
                if len(collected) >= max_results:
                    return collected
            page_num += 1

        return collected
