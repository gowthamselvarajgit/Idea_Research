"""Unit tests for the InPASS Selenium browser search client."""

import unittest
from unittest.mock import MagicMock, call, patch

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

from src.patents.base_client import BasePatentClient, PatentClientError
from src.patents.inpass_client import (
    INPASS_DEFAULT_URL,
    InPassBrowserError,
    InPassCaptchaTimeoutError,
    InPassClient,
    InPassClientError,
    InPassNavigationError,
    InPassSearchConfig,
    InPassSearchError,
    InPassSearchResultRow,
)
from src.patents.models import InPassPatentRecord


class TestInPassSearchConfig(unittest.TestCase):
    """Test InPassSearchConfig dataclass validation and defaults."""

    def test_default_config(self):
        cfg = InPassSearchConfig(keyword="WATER")
        self.assertEqual(cfg.keyword, "WATER")
        self.assertEqual(cfg.field_type, "TI")
        self.assertTrue(cfg.published)
        self.assertFalse(cfg.granted)
        self.assertEqual(cfg.date_field, "APD")
        self.assertEqual(cfg.logic_field, "AND")

    def test_custom_config(self):
        cfg = InPassSearchConfig(
            keyword="SOLAR",
            field_type="AB",
            published=False,
            granted=True,
            date_field="PD",
            logic_field="OR",
        )
        self.assertEqual(cfg.keyword, "SOLAR")
        self.assertEqual(cfg.field_type, "AB")
        self.assertFalse(cfg.published)
        self.assertTrue(cfg.granted)
        self.assertEqual(cfg.date_field, "PD")
        self.assertEqual(cfg.logic_field, "OR")

    def test_empty_keyword_raises_error(self):
        with self.assertRaises(ValueError):
            InPassSearchConfig(keyword="")

        with self.assertRaises(ValueError):
            InPassSearchConfig(keyword="   ")


class TestInPassSearchResultRow(unittest.TestCase):
    """Test InPassSearchResultRow serialization and attributes."""

    def test_search_result_row_to_dict(self):
        row = InPassSearchResultRow(
            application_number="202641109752",
            title="DUAL-WAVELENGTH OPTICAL DETECTION",
            date="12/09/2026",
            status="Published",
            raw_cells=("202641109752", "DUAL-WAVELENGTH OPTICAL DETECTION", "12/09/2026", "Published"),
        )
        data = row.to_dict()
        self.assertEqual(data["application_number"], "202641109752")
        self.assertEqual(data["title"], "DUAL-WAVELENGTH OPTICAL DETECTION")
        self.assertEqual(data["date"], "12/09/2026")
        self.assertEqual(data["status"], "Published")
        self.assertEqual(len(data["raw_cells"]), 4)


class TestInPassExceptions(unittest.TestCase):
    """Verify exception hierarchy compatibility with PatentClientError."""

    def test_exception_inheritance(self):
        self.assertTrue(issubclass(InPassClientError, PatentClientError))
        self.assertTrue(issubclass(InPassBrowserError, InPassClientError))
        self.assertTrue(issubclass(InPassNavigationError, InPassClientError))
        self.assertTrue(issubclass(InPassCaptchaTimeoutError, InPassClientError))
        self.assertTrue(issubclass(InPassSearchError, InPassClientError))


class TestInPassClient(unittest.TestCase):
    """Unit tests for InPassClient with mocked Selenium WebDriver."""

    def setUp(self):
        self.mock_driver = MagicMock()
        self.client = InPassClient(driver=self.mock_driver, timeout=2.0, captcha_timeout=2.0)

    def test_is_base_patent_client(self):
        """InPassClient must implement BasePatentClient."""
        self.assertIsInstance(self.client, BasePatentClient)

    def test_initialization_defaults(self):
        client = InPassClient()
        self.assertEqual(client.base_url, INPASS_DEFAULT_URL)
        self.assertFalse(client.headless)
        self.assertEqual(client.timeout, 30.0)
        self.assertEqual(client.captcha_timeout, 600.0)
        self.assertIsNone(client.driver)

    @patch("src.patents.inpass_client.webdriver.Chrome")
    @patch("src.patents.inpass_client.tempfile.mkdtemp", return_value="C:/fake_profile")
    def test_start_browser_creates_chrome_with_profile(self, mock_mkdtemp, mock_chrome):
        client = InPassClient(headless=True)
        created_driver = MagicMock()
        mock_chrome.return_value = created_driver

        driver = client.start_browser()
        self.assertEqual(driver, created_driver)
        self.assertEqual(client.driver, created_driver)
        mock_mkdtemp.assert_called_once()
        mock_chrome.assert_called_once()

    @patch("src.patents.inpass_client.shutil.rmtree")
    def test_close_browser_cleans_up_profile(self, mock_rmtree):
        client = InPassClient()
        client._owns_driver = True
        client.driver = self.mock_driver
        client._temp_profile_dir = "C:/fake_profile"

        with patch("src.patents.inpass_client.Path.exists", return_value=True):
            client.close_browser()

        self.mock_driver.quit.assert_called_once()
        self.assertIsNone(client.driver)
        mock_rmtree.assert_called_once_with("C:/fake_profile", ignore_errors=True)

    @patch("src.patents.inpass_client.webdriver.Chrome")
    @patch("src.patents.inpass_client.tempfile.mkdtemp", return_value="C:/fake_profile")
    def test_context_manager_lifecycle(self, mock_mkdtemp, mock_chrome):
        fake_driver = MagicMock()
        mock_chrome.return_value = fake_driver

        client = InPassClient()
        with client as c:
            self.assertEqual(c.driver, fake_driver)

        fake_driver.quit.assert_called_once()

    def test_open_search_page_success(self):
        with patch("src.patents.inpass_client.WebDriverWait") as mock_wait_cls:
            mock_wait = MagicMock()
            mock_wait_cls.return_value = mock_wait

            self.client.open_search_page("https://test.url")

            self.mock_driver.get.assert_called_once_with("https://test.url")
            mock_wait.until.assert_called_once()

    def test_open_search_page_failure_raises_navigation_error(self):
        self.mock_driver.get.side_effect = WebDriverException("Connection refused")
        with self.assertRaises(InPassNavigationError):
            self.client.open_search_page()

    def test_configure_search_sets_form_elements(self):
        mock_published = MagicMock()
        mock_published.is_selected.return_value = False

        mock_granted = MagicMock()
        mock_granted.is_selected.return_value = True

        mock_date_select_el = MagicMock()
        mock_item_select_el = MagicMock()
        mock_text_input = MagicMock()
        mock_logic_select_el = MagicMock()

        def find_element_side_effect(by, value):
            if value == "Published":
                return mock_published
            elif value == "Granted":
                return mock_granted
            elif value == "DateField":
                return mock_date_select_el
            elif value == "ItemField1":
                return mock_item_select_el
            elif value == "TextField1":
                return mock_text_input
            elif value == "LogicField1":
                return mock_logic_select_el
            raise NoSuchElementException(f"Unknown: {value}")

        self.mock_driver.find_element.side_effect = find_element_side_effect

        with patch("src.patents.inpass_client.Select") as mock_select_cls:
            mock_select_inst = MagicMock()
            mock_select_cls.return_value = mock_select_inst

            cfg = self.client.configure_search(keyword="WATER", field_type="TI", published=True, granted=False)

            self.assertEqual(cfg.keyword, "WATER")
            mock_published.click.assert_called_once()
            mock_granted.click.assert_called_once()
            mock_text_input.clear.assert_called_once()
            mock_text_input.send_keys.assert_called_once_with("WATER")

    def test_wait_for_captcha_and_results_success(self):
        self.mock_driver.current_url = "https://iprsearch.ipindia.gov.in/publicsearch/Search"
        self.mock_driver.page_source = "Total documents: 25"
        self.mock_driver.find_elements.return_value = [MagicMock()]  # Page buttons found

        callback_mock = MagicMock()
        result = self.client.wait_for_captcha_and_results(
            timeout=1.0, poll_interval=0.01, on_captcha_required=callback_mock
        )

        self.assertTrue(result)
        callback_mock.assert_called_once()
        self.assertIn("CHECKPOINT", callback_mock.call_args[0][0])

    def test_wait_for_captcha_timeout_raises_error(self):
        self.mock_driver.current_url = "https://iprsearch.ipindia.gov.in/publicsearch"
        self.mock_driver.page_source = "Enter captcha..."
        self.mock_driver.find_elements.return_value = []

        with self.assertRaises(InPassCaptchaTimeoutError):
            self.client.wait_for_captcha_and_results(timeout=0.05, poll_interval=0.01)

    def test_read_current_page_results(self):
        mock_tr1 = MagicMock()
        mock_td_app = MagicMock(text="202641109752")
        mock_td_title = MagicMock(text="Optical microplastic detection")
        mock_td_date = MagicMock(text="18/09/2026")
        mock_td_status = MagicMock(text="Published")
        mock_tr1.find_elements.side_effect = lambda by, val: (
            [mock_td_app, mock_td_title, mock_td_date, mock_td_status] if val == "td" else []
        )

        self.mock_driver.find_elements.return_value = [mock_tr1]

        rows = self.client.read_current_page_results()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].application_number, "202641109752")
        self.assertEqual(rows[0].title, "Optical microplastic detection")
        self.assertEqual(rows[0].date, "18/09/2026")
        self.assertEqual(rows[0].status, "Published")

    def test_get_available_pages(self):
        btn1 = MagicMock()
        btn1.get_attribute.return_value = "1"
        btn2 = MagicMock()
        btn2.get_attribute.return_value = "2"
        btn3 = MagicMock()
        btn3.get_attribute.return_value = "3"

        self.mock_driver.find_elements.return_value = [btn1, btn2, btn3]

        pages = self.client.get_available_pages()
        self.assertEqual(pages, [1, 2, 3])

    def test_go_to_page_success(self):
        btn2 = MagicMock()
        self.mock_driver.find_elements.return_value = [btn2]

        with patch("src.patents.inpass_client.WebDriverWait") as mock_wait_cls:
            mock_wait = MagicMock()
            mock_wait_cls.return_value = mock_wait

            success = self.client.go_to_page(2, timeout=2.0)
            self.assertTrue(success)
            btn2.click.assert_called_once()
            mock_wait.until.assert_called_once()

    def test_go_to_page_missing_button_raises_navigation_error(self):
        self.mock_driver.find_elements.return_value = []
        with self.assertRaises(InPassNavigationError):
            self.client.go_to_page(99)

    def test_open_and_get_patent_details(self):
        app_btn = MagicMock()
        self.mock_driver.find_elements.return_value = [app_btn]
        self.mock_driver.window_handles = ["win_main"]
        self.mock_driver.current_window_handle = "win_main"

        fake_html = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr><td>Publication Number</td><td>38/2026</td></tr>
          <tr><td>Publication Date</td><td>18/09/2026</td></tr>
          <tr><td>Application Filing Date</td><td>12/09/2026</td></tr>
          <tr><td>Invention Title</td><td>DUAL-WAVELENGTH OPTICAL SENSOR</td></tr>
          <tr><td>Classification (IPC)</td><td>G01N 21/47</td></tr>
          <tr><td colspan="2"><strong>Abstract:</strong><br><br>Sample abstract.</td></tr>
          <tr><td colspan="2"><textarea id="COMPLETE_SPECIFICATION">Detailed spec. , Claims:1. A sensor.</textarea></td></tr>
        </table>
        """
        self.mock_driver.page_source = fake_html

        record = self.client.get_patent_details("202641109752", return_to_search=True)

        self.assertIsInstance(record, InPassPatentRecord)
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.publication_number, "38/2026")
        self.assertEqual(record.filing_date, "12/09/2026")
        self.assertEqual(record.title, "DUAL-WAVELENGTH OPTICAL SENSOR")
        self.assertEqual(record.ipc, "G01N 21/47")
        self.assertEqual(record.abstract, "Sample abstract.")
        self.assertEqual(record.specification, "Detailed spec.")
        self.assertEqual(record.claims, "1. A sensor.")

    def test_search_base_client_contract(self):
        """search() method should coordinate open, configure, wait, and return dicts."""
        self.client.open_search_page = MagicMock()
        self.client.configure_search = MagicMock()
        self.client.wait_for_captcha_and_results = MagicMock()
        self.client.read_current_page_results = MagicMock(
            return_value=[
                InPassSearchResultRow(application_number="202641109752", title="Patent A"),
                InPassSearchResultRow(application_number="202641109913", title="Patent B"),
            ]
        )

        results = self.client.search(query="WATER", max_results=2)

        self.client.open_search_page.assert_called_once()
        self.client.configure_search.assert_called_once_with("WATER")
        self.client.wait_for_captcha_and_results.assert_called_once()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["application_number"], "202641109752")
        self.assertEqual(results[1]["application_number"], "202641109913")

    def test_capture_captcha_image_saves_png(self):
        """capture_captcha_image should locate #Captcha, save screenshot, and return file path."""
        mock_captcha_el = MagicMock()
        mock_captcha_el.screenshot.side_effect = lambda path: Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")
        self.mock_driver.find_elements.return_value = [mock_captcha_el]

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            out_file = str(Path(td) / "custom_captcha.png")
            res_path = self.client.capture_captcha_image(output_path=out_file)

            self.assertEqual(res_path, str(Path(out_file).resolve()))
            self.assertTrue(Path(res_path).exists())
            self.assertEqual(Path(res_path).read_bytes(), b"\x89PNG\r\n\x1a\n")

    def test_capture_captcha_image_missing_element_raises_navigation_error(self):
        """Missing #Captcha element should raise InPassNavigationError."""
        self.mock_driver.find_elements.return_value = []
        with self.assertRaises(InPassNavigationError):
            self.client.capture_captcha_image()

    def test_submit_captcha_enters_text_and_clicks_search(self):
        """submit_captcha should find #CaptchaText, enter text, and click the search button."""
        mock_text_input = MagicMock()
        mock_submit_btn = MagicMock()

        def mock_find_elements(by, val):
            if "CaptchaText" in val:
                return [mock_text_input]
            if "submit" in val or "Search" in val:
                return [mock_submit_btn]
            return []

        self.mock_driver.find_elements.side_effect = mock_find_elements

        self.client.submit_captcha("K7M9P")

        mock_text_input.clear.assert_called_once()
        mock_text_input.send_keys.assert_called_once_with("K7M9P")
        self.mock_driver.execute_script.assert_called()

    def test_submit_captcha_invalid_string_raises_value_error(self):
        """Empty or whitespace-only captcha_text raises ValueError."""
        with self.assertRaises(ValueError):
            self.client.submit_captcha("")
        with self.assertRaises(ValueError):
            self.client.submit_captcha("   ")

    def test_wait_for_captcha_and_results_with_solver_callback(self):
        """wait_for_captcha_and_results with captcha_solver captures image, invokes solver, and submits."""
        self.client.capture_captcha_image = MagicMock(return_value="/tmp/mock_captcha.png")
        self.client.submit_captcha = MagicMock()

        solver_mock = MagicMock(return_value="X4R8Q")
        on_captcha_mock = MagicMock()

        # Simulate results arrival immediately in the polling loop
        page_btn = MagicMock()
        self.mock_driver.find_elements.side_effect = lambda by, val: [page_btn] if "page" in val else []

        success = self.client.wait_for_captcha_and_results(
            timeout=5.0,
            on_captcha_required=on_captcha_mock,
            captcha_solver=solver_mock,
        )

        self.assertTrue(success)
        self.client.capture_captcha_image.assert_called_once()
        solver_mock.assert_called_once_with("/tmp/mock_captcha.png")
        self.client.submit_captcha.assert_called_once_with("X4R8Q")
        on_captcha_mock.assert_called_once()

    def test_wait_for_captcha_and_results_backward_compatibility_without_solver(self):
        """When captcha_solver is None, capture and submit are NOT called."""
        self.client.capture_captcha_image = MagicMock()
        self.client.submit_captcha = MagicMock()

        page_btn = MagicMock()
        self.mock_driver.find_elements.side_effect = lambda by, val: [page_btn] if "page" in val else []
        on_captcha_mock = MagicMock()

        success = self.client.wait_for_captcha_and_results(
            timeout=5.0,
            on_captcha_required=on_captcha_mock,
            captcha_solver=None,
        )

        self.assertTrue(success)
        self.client.capture_captcha_image.assert_not_called()
        self.client.submit_captcha.assert_not_called()
        on_captcha_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

