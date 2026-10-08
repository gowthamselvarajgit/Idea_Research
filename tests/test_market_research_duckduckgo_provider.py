"""Unit tests for DuckDuckGoHTMLSearchProvider."""

import socket
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.parse
import urllib.request

from src.market_research.duckduckgo_provider import (
    DUCKDUCKGO_HTML_ENDPOINT,
    DuckDuckGoHTMLSearchProvider,
    DuckDuckGoHTTPError,
    DuckDuckGoNetworkError,
    DuckDuckGoSearchError,
    DuckDuckGoTimeoutError,
    decode_duckduckgo_url,
    extract_domain_from_url,
)
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    SearchProviderError,
)
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult


SAMPLE_DUCKDUCKGO_HTML = """<!DOCTYPE html>
<html>
<head><title>DuckDuckGo</title></head>
<body>
<div class="results">
  <!-- Result 1: Tracking link with uddg parameter, nested tags, HTML entities -->
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.skincarebrand.com%2Fserum&rut=abc">
          <b>Advanced</b> Skincare Serum &amp; Treatment
        </a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.skincarebrand.com%2Fserum&rut=abc">
        Clinically proven <i>skincare formulation</i> for daily skin barrier protection &amp; repair.
      </a>
      <div class="result__extras">
        <a class="result__url" href="...">skincarebrand.com</a>
      </div>
    </div>
  </div>

  <!-- Result 2: Direct HTTPS link, div snippet -->
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a class="result__a" href="https://beautytech.org/ai-analysis">
          AI Skin Analysis &amp; Diagnostic Platform
        </a>
      </h2>
      <div class="result__snippet">
        Personalised recommendation algorithms for modern cosmetics and dermatology.
      </div>
    </div>
  </div>

  <!-- Result 3: Root-relative tracking link with query string in destination -->
  <div class="result results_links results_links_deep web-result">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fcosmetics-lab.io%2Fpeptides%3Fref%3Dddg&rut=xyz">
          Cosmetic Peptide Formulations 2026
        </a>
      </h2>
      <a class="result__snippet" href="/l/?uddg=https%3A%2F%2Fcosmetics-lab.io%2Fpeptides%3Fref%3Dddg&rut=xyz">
        Research summary on anti-aging peptides and botanical extract stabilization.
      </a>
    </div>
  </div>
</div>
</body>
</html>
"""


class TestDuckDuckGoHTMLSearchProvider(unittest.TestCase):
    """Comprehensive test suite for DuckDuckGoHTMLSearchProvider."""

    def test_multiple_realistic_results_parsed(self) -> None:
        """1. Multiple realistic DuckDuckGo results are parsed and returned in order."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        results = provider.search(query="skincare formulation", max_results=10)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].url, "https://www.skincarebrand.com/serum")
        self.assertEqual(results[1].url, "https://beautytech.org/ai-analysis")
        self.assertEqual(results[2].url, "https://cosmetics-lab.io/peptides?ref=ddg")

    def test_title_extraction(self) -> None:
        """2. Title extraction unescapes entities, strips nested tags, and normalizes spaces."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        results = provider.search(query="skincare", max_results=3)

        self.assertEqual(results[0].title, "Advanced Skincare Serum & Treatment")
        self.assertEqual(results[1].title, "AI Skin Analysis & Diagnostic Platform")
        self.assertEqual(results[2].title, "Cosmetic Peptide Formulations 2026")

    def test_snippet_extraction(self) -> None:
        """3. Snippet extraction handles both anchor and div snippets, unescaping entities."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        results = provider.search(query="skincare", max_results=3)

        self.assertEqual(
            results[0].snippet,
            "Clinically proven skincare formulation for daily skin barrier protection & repair.",
        )
        self.assertEqual(
            results[1].snippet,
            "Personalised recommendation algorithms for modern cosmetics and dermatology.",
        )
        self.assertEqual(
            results[2].snippet,
            "Research summary on anti-aging peptides and botanical extract stabilization.",
        )

    def test_destination_url_extraction(self) -> None:
        """4. Destination URL extraction returns full decoded destination address."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        results = provider.search(query="skincare", max_results=3)

        self.assertEqual(results[0].url, "https://www.skincarebrand.com/serum")
        self.assertEqual(results[1].url, "https://beautytech.org/ai-analysis")
        self.assertEqual(results[2].url, "https://cosmetics-lab.io/peptides?ref=ddg")

    def test_domain_extraction(self) -> None:
        """5. Domain extraction strips www and port, yielding clean host domain."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        results = provider.search(query="skincare", max_results=3)

        self.assertEqual(results[0].domain, "skincarebrand.com")
        self.assertEqual(results[1].domain, "beautytech.org")
        self.assertEqual(results[2].domain, "cosmetics-lab.io")

        # Test helper directly
        self.assertEqual(extract_domain_from_url("https://www.example.com/path"), "example.com")
        self.assertEqual(extract_domain_from_url("http://sub.domain.org:8080/foo"), "sub.domain.org")

    def test_tracking_url_decoding(self) -> None:
        """6. DuckDuckGo tracking URL decoding handles protocol-relative, root-relative, and absolute."""
        self.assertEqual(
            decode_duckduckgo_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Ftest.com%2Fdoc%3Fid%3D1&rut=123"),
            "https://test.com/doc?id=1",
        )
        self.assertEqual(
            decode_duckduckgo_url("/l/?uddg=https%3A%2F%2Ftarget.org%2Fpage"),
            "https://target.org/page",
        )
        self.assertEqual(
            decode_duckduckgo_url("https://duckduckgo.com/l/?uddg=http%3A%2F%2Finsecure.org%2Fentry"),
            "http://insecure.org/entry",
        )
        self.assertEqual(
            decode_duckduckgo_url("https://directsite.com/about"),
            "https://directsite.com/about",
        )

    def test_non_http_https_url_filtering(self) -> None:
        """7. Non-HTTP/HTTPS URLs and internal DuckDuckGo site links are discarded."""
        html_with_invalid_urls = """
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=ftp%3A%2F%2Ffiles.org%2Freadme.txt">FTP File</a>
          <div class="result__snippet">FTP download snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="javascript:void(0)">JavaScript Link</a>
          <div class="result__snippet">Script snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="/feedback.html">DuckDuckGo Feedback</a>
          <div class="result__snippet">Leave feedback</div>
        </div>
        <div class="result">
          <a class="result__a" href="https://valid-target.com/page">Valid Destination</a>
          <div class="result__snippet">Valid snippet content</div>
        </div>
        """
        provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: html_with_invalid_urls
        )
        results = provider.search(query="query", max_results=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://valid-target.com/page")

    def test_duplicate_url_removal(self) -> None:
        """8. Duplicate destination URLs are filtered while retaining first occurrence order."""
        html_with_duplicates = """
        <div class="result">
          <a class="result__a" href="https://duplicate.com/page">First Duplicate</a>
          <div class="result__snippet">First snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="https://unique.com/page">Unique Page</a>
          <div class="result__snippet">Unique snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fduplicate.com%2Fpage">Second Duplicate</a>
          <div class="result__snippet">Second snippet</div>
        </div>
        """
        provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: html_with_duplicates
        )
        results = provider.search(query="query", max_results=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://duplicate.com/page")
        self.assertEqual(results[0].title, "First Duplicate")
        self.assertEqual(results[1].url, "https://unique.com/page")

    def test_max_results_enforcement(self) -> None:
        """9. max_results strictly bounds the returned items even when more are available."""
        provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: SAMPLE_DUCKDUCKGO_HTML
        )
        results_1 = provider.search(query="skincare", max_results=1)
        self.assertEqual(len(results_1), 1)
        self.assertEqual(results_1[0].url, "https://www.skincarebrand.com/serum")

        results_2 = provider.search(query="skincare", max_results=2)
        self.assertEqual(len(results_2), 2)

    def test_malformed_result_handling(self) -> None:
        """10. Results missing title or snippet or with invalid href are safely ignored."""
        html_malformed = """
        <div class="result">
          <a class="result__a" href="https://missing-snippet.com">Title Only</a>
        </div>
        <div class="result">
          <div class="result__snippet">Snippet without title</div>
        </div>
        <div class="result">
          <a class="result__a" href="">Empty URL</a>
          <div class="result__snippet">Snippet</div>
        </div>
        <div class="result">
          <a class="result__a" href="https://valid.org/ok">Valid One</a>
          <div class="result__snippet">Valid snippet</div>
        </div>
        """
        provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: html_malformed
        )
        results = provider.search(query="query", max_results=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://valid.org/ok")
        self.assertEqual(results[0].title, "Valid One")

    def test_empty_result_handling(self) -> None:
        """11. Empty HTML, whitespace, or 'no results' pages return empty list."""
        empty_samples = [
            "",
            "   \t\n  ",
            "<html><body><div class='no-results'>No results found for your query.</div></body></html>",
            "<html><body><div>No links here</div></body></html>",
        ]
        for sample in empty_samples:
            with self.subTest(sample=sample[:20]):
                provider = DuckDuckGoHTMLSearchProvider(
                    http_transport=lambda req, to, s=sample: s
                )
                results = provider.search(query="empty query", max_results=5)
                self.assertEqual(results, [])

    def test_http_error_handling(self) -> None:
        """12. HTTP error response raises DuckDuckGoHTTPError with status code."""
        mock_response = MagicMock()
        mock_response.status = 403
        http_err = urllib.error.HTTPError(
            url=DUCKDUCKGO_HTML_ENDPOINT,
            code=403,
            msg="Forbidden",
            hdrs=MagicMock(),
            fp=None,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            provider = DuckDuckGoHTMLSearchProvider()
            with self.assertRaises(DuckDuckGoHTTPError) as ctx:
                provider.search(query="test", max_results=5)

            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("403", str(ctx.exception))
            self.assertIsInstance(ctx.exception, SearchProviderError)

    def test_network_and_timeout_error_handling(self) -> None:
        """13. Network failure and timeouts raise distinct DuckDuckGoNetworkError / TimeoutError."""
        # Socket timeout
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            provider = DuckDuckGoHTMLSearchProvider()
            with self.assertRaises(DuckDuckGoTimeoutError):
                provider.search(query="test", max_results=5)

        # URLError timeout
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection timed out")):
            provider = DuckDuckGoHTMLSearchProvider()
            with self.assertRaises(DuckDuckGoTimeoutError):
                provider.search(query="test", max_results=5)

        # General URLError (DNS / connection refused)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Name or service not known")):
            provider = DuckDuckGoHTMLSearchProvider()
            with self.assertRaises(DuckDuckGoNetworkError):
                provider.search(query="test", max_results=5)

    def test_search_query_is_sent_correctly(self) -> None:
        """14. Search query is encoded into POST body to html.duckduckgo.com/html/."""
        captured_req: list[urllib.request.Request] = []

        def transport(req: urllib.request.Request, timeout: float) -> str:
            captured_req.append(req)
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)
        provider.search(query="personalised skincare AI", max_results=3)

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, DUCKDUCKGO_HTML_ENDPOINT)

        # Verify POST data
        self.assertIsNotNone(req.data)
        parsed_body = urllib.parse.parse_qs(req.data.decode("utf-8"))
        self.assertEqual(parsed_body["q"], ["personalised skincare AI"])

    def test_user_agent_is_sent(self) -> None:
        """15. Configured User-Agent header is sent on the request."""
        captured_req: list[urllib.request.Request] = []

        custom_ua = "CustomResearchAgent/1.0"
        provider = DuckDuckGoHTMLSearchProvider(
            user_agent=custom_ua,
            http_transport=lambda req, to: (captured_req.append(req) or SAMPLE_DUCKDUCKGO_HTML),
        )
        provider.search(query="skincare", max_results=2)

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        self.assertEqual(req.get_header("User-agent"), custom_ua)

    def test_contract_and_protocol_compliance(self) -> None:
        """16. Provider satisfies SearchProvider protocol and results pass SearchResult contract."""
        def transport(req: urllib.request.Request, timeout: float) -> str:
            return SAMPLE_DUCKDUCKGO_HTML

        provider = DuckDuckGoHTMLSearchProvider(http_transport=transport)

        # 1. Check SearchProvider protocol
        self.assertIsInstance(provider, SearchProvider)

        # 2. Check SearchResult contract validation on all items
        results = provider.search(query="beauty tech", max_results=3)
        self.assertEqual(len(results), 3)

        for res in results:
            self.assertIsInstance(res, SearchResult)
            validate_search_result_record(res)
            self.assertEqual(res.raw_data.get("source"), "duckduckgo_html")

        # 3. Seamless integration with SearchClient
        client = SearchClient(provider=provider)
        client_results = client.search(query="beauty tech", max_results=2)
        self.assertEqual(len(client_results), 2)
        self.assertIsInstance(client_results, tuple)
        self.assertEqual(client_results[0].url, "https://www.skincarebrand.com/serum")

    def test_input_validation(self) -> None:
        """Query must be non-empty string and max_results must be integer >= 1."""
        provider = DuckDuckGoHTMLSearchProvider()

        bad_queries = ["", "   ", "\t\n", None, 123]
        for bad_q in bad_queries:
            with self.subTest(bad_q=bad_q):
                with self.assertRaises(ValueError):
                    provider.search(query=bad_q, max_results=5)  # type: ignore[arg-type]

        bad_max = [0, -1, "5", True, None]
        for bad_m in bad_max:
            with self.subTest(bad_m=bad_m):
                with self.assertRaises(ValueError):
                    provider.search(query="skincare", max_results=bad_m)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
