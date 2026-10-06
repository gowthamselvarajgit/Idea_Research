"""Unit tests for WebSourceClient and fetch_source."""

import io
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import unittest

from src.market_research.source_models import WebResearchSource
from src.market_research.web_source_client import (
    WebSourceClient,
    WebSourceClientError,
    WebSourceContentError,
    WebSourceHTTPError,
    WebSourceInvalidURLError,
    WebSourceNetworkError,
    fetch_source,
)


class TestWebSourceClient(unittest.TestCase):
    """Test suite for HTTP web page retrieval client."""

    def _mock_http_response(
        self,
        html_content: str,
        final_url: str = "https://drainrobo.example.com/products",
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
    ) -> MagicMock:
        """Helper to create a mocked urllib response context manager."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_content.encode("utf-8")
        mock_resp.geturl.return_value = final_url
        mock_resp.getcode.return_value = status_code
        mock_resp.status = status_code
        mock_resp.headers = MagicMock()
        mock_resp.headers.get.return_value = content_type
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_successful_html_retrieval(self, mock_urlopen: MagicMock) -> None:
        """Successful HTTP GET retrieves page, extracts content, and returns WebResearchSource."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>DrainRobo Systems - NextGen Crawlers</title></head>
        <body>
            <h1>Robotic Pipe Inspection</h1>
            <p>We build specialized inspection crawlers for industrial pipelines.</p>
        </body>
        </html>
        """
        mock_urlopen.return_value = self._mock_http_response(html)

        source = fetch_source("https://drainrobo.example.com/products", source_type="competitor")

        self.assertIsInstance(source, WebResearchSource)
        self.assertEqual(source.url, "https://drainrobo.example.com/products")
        self.assertEqual(source.title, "DrainRobo Systems - NextGen Crawlers")
        self.assertEqual(source.source_type, "competitor")
        self.assertEqual(source.publisher_or_domain, "drainrobo.example.com")
        self.assertIn("Robotic Pipe Inspection", source.retrieved_content)
        self.assertIn("We build specialized inspection crawlers", source.retrieved_content)
        self.assertIsNotNone(source.retrieved_at)
        self.assertEqual(source.raw_data["http_status"], 200)

    @patch("urllib.request.urlopen")
    def test_title_extraction_and_fallback(self, mock_urlopen: MagicMock) -> None:
        """Page title is extracted cleanly, or derived from URL when tag is missing."""
        # 1. Title present
        mock_urlopen.return_value = self._mock_http_response(
            "<html><head><title>   Clean Title   </title></head><body><p>Text</p></body></html>"
        )
        s1 = fetch_source("https://example.com/page")
        self.assertEqual(s1.title, "Clean Title")

        # 2. Title absent
        mock_urlopen.return_value = self._mock_http_response(
            "<html><body><p>Content without title tag</p></body></html>",
            final_url="https://example.com/docs/api",
        )
        s2 = fetch_source("https://example.com/docs/api")
        self.assertIn("example.com", s2.title)

    @patch("urllib.request.urlopen")
    def test_script_and_style_removal(self, mock_urlopen: MagicMock) -> None:
        """Scripts, stylesheets, and noscript elements are stripped from retrieved content."""
        html = """
        <html>
        <head>
            <title>Competitor Specs</title>
            <style>body { background: blue; } h1 { font-size: 20px; }</style>
            <script>window.analytics.track("pageview");</script>
        </head>
        <body>
            <h1>DrainBot Specifications</h1>
            <script>function maliciousCode() { return true; }</script>
            <noscript>You must enable javascript to view full page.</noscript>
            <p>Operates in pipes from 6 to 36 inches in diameter.</p>
        </body>
        </html>
        """
        mock_urlopen.return_value = self._mock_http_response(html)

        source = fetch_source("https://specs.example.com/drainbot")

        self.assertIn("DrainBot Specifications", source.retrieved_content)
        self.assertIn("Operates in pipes from 6 to 36 inches", source.retrieved_content)
        self.assertNotIn("analytics", source.retrieved_content)
        self.assertNotIn("maliciousCode", source.retrieved_content)
        self.assertNotIn("background: blue", source.retrieved_content)

    @patch("urllib.request.urlopen")
    def test_redirect_handling(self, mock_urlopen: MagicMock) -> None:
        """Client records final URL after redirection and updates publisher/domain."""
        html = "<html><head><title>Final Page</title></head><body><p>Target content</p></body></html>"
        mock_urlopen.return_value = self._mock_http_response(
            html,
            final_url="https://final-domain.example.com/new-path",
        )

        source = fetch_source("https://old-domain.example.com/old-path")

        self.assertEqual(source.url, "https://final-domain.example.com/new-path")
        self.assertEqual(source.publisher_or_domain, "final-domain.example.com")
        self.assertTrue(source.raw_data["redirected"])

    def test_invalid_urls_and_unsupported_schemes(self) -> None:
        """Client rejects invalid URLs, non-HTTP schemes, and prohibited localhost targets."""
        client = WebSourceClient()

        # Empty or non-string
        with self.assertRaises(WebSourceInvalidURLError):
            client.fetch_source("")
        with self.assertRaises(WebSourceInvalidURLError):
            client.fetch_source("   ")
        with self.assertRaises(WebSourceInvalidURLError):
            client.fetch_source(123)  # type: ignore

        # Unsupported schemes
        unsupported = [
            "ftp://ftp.example.com/file.txt",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,Hello",
        ]
        for bad_url in unsupported:
            with self.subTest(scheme_url=bad_url):
                with self.assertRaises(WebSourceInvalidURLError):
                    client.fetch_source(bad_url)

        # Prohibited local targets
        local_targets = [
            "http://localhost:8080/admin",
            "http://127.0.0.1/status",
            "http://0.0.0.0:3000",
        ]
        for local_url in local_targets:
            with self.subTest(local_url=local_url):
                with self.assertRaises(WebSourceInvalidURLError):
                    client.fetch_source(local_url)

    @patch("urllib.request.urlopen")
    def test_http_error_handling(self, mock_urlopen: MagicMock) -> None:
        """HTTP error responses raise WebSourceHTTPError with status code."""
        # 404 Not Found
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.com/missing",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b"Not Found"),
        )
        with self.assertRaises(WebSourceHTTPError) as ctx:
            fetch_source("https://example.com/missing")
        self.assertIn("404", str(ctx.exception))

        # 500 Internal Server Error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.com/error",
            code=500,
            msg="Internal Error",
            hdrs={},
            fp=io.BytesIO(b"Internal Error"),
        )
        with self.assertRaises(WebSourceHTTPError) as ctx:
            fetch_source("https://example.com/error")
        self.assertIn("500", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_network_error_handling(self, mock_urlopen: MagicMock) -> None:
        """Network and timeout errors raise WebSourceNetworkError."""
        # URLError (e.g. DNS failure or connection reset)
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with self.assertRaises(WebSourceNetworkError):
            fetch_source("https://unreachable.example.com")

        # TimeoutError
        mock_urlopen.side_effect = TimeoutError("Timed out")
        with self.assertRaises(WebSourceNetworkError):
            fetch_source("https://timeout.example.com")

    @patch("urllib.request.urlopen")
    def test_empty_or_unusable_response(self, mock_urlopen: MagicMock) -> None:
        """Pages with no extractable text raise WebSourceContentError."""
        empty_pages = [
            "",
            "<html><head><script>code();</script></head><body></body></html>",
            "<html><body>   \n\t   </body></html>",
        ]
        for empty_html in empty_pages:
            with self.subTest(empty_html=empty_html):
                mock_urlopen.return_value = self._mock_http_response(empty_html)
                with self.assertRaises(WebSourceContentError):
                    fetch_source("https://empty.example.com")

    @patch("urllib.request.urlopen")
    def test_source_type_forwarding_and_validation(self, mock_urlopen: MagicMock) -> None:
        """Controlled source_type is forwarded and validated."""
        html = "<html><head><title>Title</title></head><body><p>Content</p></body></html>"
        mock_urlopen.return_value = self._mock_http_response(html)

        # Valid source_type
        source = fetch_source("https://example.com", source_type="review")
        self.assertEqual(source.source_type, "review")

        # Invalid source_type
        with self.assertRaises(ValueError):
            fetch_source("https://example.com", source_type="unauthorized_type")


if __name__ == "__main__":
    unittest.main()
