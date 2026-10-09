"""Unit tests for TavilySearchProvider and fallback search integration."""

import json
import socket
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from src.market_research.duckduckgo_provider import DuckDuckGoHTMLSearchProvider
from src.market_research.fallback_search_provider import (
    FallbackSearchProvider,
    FallbackSearchProviderError,
    create_default_search_provider,
)
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
)
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult
from src.market_research.tavily_provider import (
    TavilyAuthenticationError,
    TavilyHTTPError,
    TavilyNetworkError,
    TavilyRateLimitError,
    TavilySearchError,
    TavilySearchProvider,
    TavilyTimeoutError,
    extract_domain_from_url,
)

SAMPLE_TAVILY_RESPONSE = {
    "query": "skincare competitors",
    "follow_up_questions": None,
    "answer": None,
    "images": [],
    "results": [
        {
            "title": "Top Skincare Competitors and Brands 2024",
            "url": "https://www.cosmetics-analysis.com/market-leaders",
            "content": "Comprehensive competitive analysis of top cosmetic and skincare manufacturers.",
            "score": 0.96,
            "raw_content": None,
        },
        {
            "title": "Innovative Dermatology Brands",
            "url": "https://dermtech.org/innovations",
            "content": "Clinical overview of high-growth dermatology and beauty startups.",
            "score": 0.88,
            "raw_content": None,
        },
        {
            "title": "Duplicate URL result",
            "url": "https://dermtech.org/innovations",
            "content": "This duplicate URL should be ignored.",
            "score": 0.80,
            "raw_content": None,
        },
    ],
    "response_time": 0.35,
}


class FakeSearchProvider:
    """Fake search provider for deterministic composite testing."""

    def __init__(
        self,
        name: str = "FakePrimary",
        results: list[SearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.results = results if results is not None else []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if self.error is not None:
            raise self.error
        return self.results


class TestTavilySearchProvider(unittest.TestCase):
    """Comprehensive test suite for TavilySearchProvider."""

    def test_extract_domain_from_url(self) -> None:
        """extract_domain_from_url strips www and normalizes hostnames."""
        self.assertEqual(extract_domain_from_url("https://www.example.com/path"), "example.com")
        self.assertEqual(extract_domain_from_url("http://sub.domain.org/test?q=1"), "sub.domain.org")
        self.assertEqual(extract_domain_from_url(""), "")
        self.assertEqual(extract_domain_from_url("not-a-valid-url"), "")

    def test_initialization_with_explicit_key(self) -> None:
        """Provider initializes with explicitly provided API key."""
        provider = TavilySearchProvider(
            api_key="tvly-test-12345",
            endpoint="https://custom.tavily.com/search",
            search_depth="advanced",
            timeout=15.0,
        )
        self.assertEqual(provider.api_key, "tvly-test-12345")
        self.assertEqual(provider.endpoint, "https://custom.tavily.com/search")
        self.assertEqual(provider.search_depth, "advanced")
        self.assertEqual(provider.timeout, 15.0)
        self.assertTrue(provider.is_configured)

    def test_initialization_from_environment(self) -> None:
        """Provider reads TAVILY_API_KEY from environment if not passed explicitly."""
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-env-67890"}):
            provider = TavilySearchProvider()
            self.assertEqual(provider.api_key, "tvly-env-67890")
            self.assertTrue(provider.is_configured)

    def test_is_configured_false_when_unconfigured(self) -> None:
        """is_configured returns False when no API key is provided or present in environment."""
        with patch.dict("os.environ", {}, clear=True):
            provider = TavilySearchProvider(api_key=None)
            self.assertFalse(provider.is_configured)

    def test_search_raises_authentication_error_when_unconfigured(self) -> None:
        """search raises TavilyAuthenticationError when API key is missing."""
        provider = TavilySearchProvider(api_key=None)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(TavilyAuthenticationError) as ctx:
                provider.search("skincare formulations")
            self.assertIn("Tavily API key is not configured", str(ctx.exception))

    def test_query_validation(self) -> None:
        """search validates that query is non-empty and max_results is >= 1."""
        provider = TavilySearchProvider(api_key="tvly-dummy")
        with self.assertRaises(ValueError):
            provider.search("")
        with self.assertRaises(ValueError):
            provider.search("   ")
        with self.assertRaises(ValueError):
            provider.search("valid query", max_results=0)
        with self.assertRaises(ValueError):
            provider.search("valid query", max_results=-5)

    def test_successful_search_parsing(self) -> None:
        """Successful JSON response is parsed into validated SearchResult objects."""
        transport = lambda req, timeout: json.dumps(SAMPLE_TAVILY_RESPONSE).encode("utf-8")
        provider = TavilySearchProvider(
            api_key="tvly-dummy-key",
            http_transport=transport,
        )

        results = provider.search("skincare competitors", max_results=5)

        # 3 items in sample, 1 is duplicate URL -> 2 unique valid results expected
        self.assertEqual(len(results), 2)

        res1 = results[0]
        self.assertEqual(res1.url, "https://www.cosmetics-analysis.com/market-leaders")
        self.assertEqual(res1.title, "Top Skincare Competitors and Brands 2024")
        self.assertEqual(
            res1.snippet,
            "Comprehensive competitive analysis of top cosmetic and skincare manufacturers.",
        )
        self.assertEqual(res1.domain, "cosmetics-analysis.com")
        self.assertEqual(res1.raw_data.get("engine"), "tavily")
        self.assertEqual(res1.raw_data.get("score"), 0.96)
        validate_search_result_record(res1)

        res2 = results[1]
        self.assertEqual(res2.url, "https://dermtech.org/innovations")
        self.assertEqual(res2.title, "Innovative Dermatology Brands")
        self.assertEqual(res2.domain, "dermtech.org")
        validate_search_result_record(res2)

    def test_max_results_bounding(self) -> None:
        """search respects max_results constraint."""
        transport = lambda req, timeout: json.dumps(SAMPLE_TAVILY_RESPONSE)
        provider = TavilySearchProvider(
            api_key="tvly-dummy-key",
            http_transport=transport,
        )

        results = provider.search("skincare competitors", max_results=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://www.cosmetics-analysis.com/market-leaders")

    def test_fallback_title_and_snippet_when_empty(self) -> None:
        """When title or content are empty, provider falls back gracefully."""
        payload = {
            "results": [
                {
                    "url": "https://example.org/raw",
                    "title": "",
                    "content": "",
                }
            ]
        }
        provider = TavilySearchProvider(
            api_key="tvly-dummy",
            http_transport=lambda req, to: json.dumps(payload),
        )
        results = provider.search("query", max_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].domain, "example.org")
        self.assertEqual(results[0].title, "example.org")
        self.assertEqual(results[0].snippet, "example.org")

    def test_skips_invalid_urls(self) -> None:
        """Provider ignores non-HTTP/HTTPS URLs."""
        payload = {
            "results": [
                {"url": "ftp://files.example.org/doc", "title": "FTP Doc", "content": "File"},
                {"url": "javascript:void(0)", "title": "JS link", "content": "Script"},
                {"url": "https://valid.org/page", "title": "Valid", "content": "Content"},
            ]
        }
        provider = TavilySearchProvider(
            api_key="tvly-dummy",
            http_transport=lambda req, to: json.dumps(payload),
        )
        results = provider.search("query", max_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://valid.org/page")

    def test_http_401_authentication_error(self) -> None:
        """HTTP 401 raises TavilyAuthenticationError."""
        def transport_401(req, timeout):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=401,
                msg="Unauthorized",
                hdrs={},  # type: ignore[arg-type]
                fp=io_bytes(b'{"detail": {"error": "Invalid API key provided"}}'),
            )

        provider = TavilySearchProvider(api_key="tvly-invalid", http_transport=transport_401)
        with self.assertRaises(TavilyAuthenticationError) as ctx:
            provider.search("query")
        self.assertIn("Invalid API key provided", str(ctx.exception))

    def test_http_429_rate_limit_error(self) -> None:
        """HTTP 429 raises TavilyRateLimitError."""
        def transport_429(req, timeout):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=429,
                msg="Too Many Requests",
                hdrs={},  # type: ignore[arg-type]
                fp=io_bytes(b'{"detail": "Rate limit exceeded"}'),
            )

        provider = TavilySearchProvider(api_key="tvly-valid", http_transport=transport_429)
        with self.assertRaises(TavilyRateLimitError) as ctx:
            provider.search("query")
        self.assertIn("Rate limit exceeded", str(ctx.exception))

    def test_http_500_server_error(self) -> None:
        """HTTP 500 raises TavilyHTTPError with status code."""
        def transport_500(req, timeout):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=500,
                msg="Internal Server Error",
                hdrs={},  # type: ignore[arg-type]
                fp=io_bytes(b'{"detail": "Database unavailable"}'),
            )

        provider = TavilySearchProvider(api_key="tvly-valid", http_transport=transport_500)
        with self.assertRaises(TavilyHTTPError) as ctx:
            provider.search("query")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Database unavailable", str(ctx.exception))

    def test_timeout_error(self) -> None:
        """Socket timeout raises TavilyTimeoutError."""
        def transport_timeout(req, timeout):
            raise socket.timeout("timed out")

        provider = TavilySearchProvider(api_key="tvly-valid", http_transport=transport_timeout)
        with self.assertRaises(TavilyTimeoutError):
            provider.search("query")

    def test_network_url_error(self) -> None:
        """URLError raises TavilyNetworkError."""
        def transport_network_err(req, timeout):
            raise urllib.error.URLError("DNS resolution failed")

        provider = TavilySearchProvider(api_key="tvly-valid", http_transport=transport_network_err)
        with self.assertRaises(TavilyNetworkError):
            provider.search("query")

    def test_malformed_json_raises_search_error(self) -> None:
        """Malformed JSON response raises TavilySearchError."""
        provider = TavilySearchProvider(
            api_key="tvly-valid",
            http_transport=lambda req, to: "NOT JSON",
        )
        with self.assertRaises(TavilySearchError):
            provider.search("query")

    def test_unexpected_payload_structure(self) -> None:
        """Unexpected payload type raises TavilySearchError."""
        provider = TavilySearchProvider(
            api_key="tvly-valid",
            http_transport=lambda req, to: json.dumps(["not", "a", "dict"]),
        )
        with self.assertRaises(TavilySearchError):
            provider.search("query")


class TestTavilyIntegration(unittest.TestCase):
    """Tests verifying Tavily provider compatibility with SearchClient and FallbackSearchProvider."""

    def test_works_with_search_client(self) -> None:
        """TavilySearchProvider implements SearchProvider protocol and works in SearchClient."""
        transport = lambda req, to: json.dumps(SAMPLE_TAVILY_RESPONSE)
        provider = TavilySearchProvider(api_key="tvly-test", http_transport=transport)

        self.assertIsInstance(provider, SearchProvider)

        client = SearchClient(provider=provider)
        results = client.search("skincare competitors", max_results=3)

        self.assertIsInstance(results, tuple)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://www.cosmetics-analysis.com/market-leaders")

    def test_search_client_wraps_tavily_provider_error(self) -> None:
        """SearchClient wraps TavilySearchError as SearchProviderError."""
        def failing_transport(req, to):
            raise urllib.error.URLError("Connection refused")

        provider = TavilySearchProvider(api_key="tvly-test", http_transport=failing_transport)
        client = SearchClient(provider=provider)

        with self.assertRaises(SearchProviderError):
            client.search("skincare")

    def test_fallback_search_provider_fails_over_to_tavily(self) -> None:
        """FallbackSearchProvider invokes Tavily provider when primary provider fails."""
        primary = FakeSearchProvider("DuckDuckGoFake", error=RuntimeError("Bot challenge 403"))
        tavily = TavilySearchProvider(
            api_key="tvly-test",
            http_transport=lambda req, to: json.dumps(SAMPLE_TAVILY_RESPONSE),
        )

        composite = FallbackSearchProvider([primary, tavily])
        results = composite.search("skincare competitors", max_results=5)

        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://www.cosmetics-analysis.com/market-leaders")

    def test_fallback_search_provider_skips_tavily_when_primary_succeeds(self) -> None:
        """When primary provider succeeds, Tavily is not invoked."""
        primary_result = SearchResult(
            url="https://ddg.example.com/item",
            title="DDG Title",
            snippet="DDG Snippet",
            domain="ddg.example.com",
        )
        primary = FakeSearchProvider("Primary", results=[primary_result])
        mock_tavily = MagicMock(spec=SearchProvider)

        composite = FallbackSearchProvider([primary, mock_tavily])
        results = composite.search("query", max_results=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://ddg.example.com/item")
        mock_tavily.search.assert_not_called()

    def test_create_default_search_provider_unconfigured(self) -> None:
        """When TAVILY_API_KEY is not set, create_default_search_provider returns only DuckDuckGo."""
        with patch.dict("os.environ", {}, clear=True):
            provider = create_default_search_provider()
            self.assertIsInstance(provider, DuckDuckGoHTMLSearchProvider)

    def test_create_default_search_provider_configured(self) -> None:
        """When TAVILY_API_KEY is set, create_default_search_provider returns FallbackSearchProvider."""
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-active-key"}):
            provider = create_default_search_provider()
            self.assertIsInstance(provider, FallbackSearchProvider)
            self.assertEqual(len(provider.providers), 2)
            self.assertIsInstance(provider.providers[0], DuckDuckGoHTMLSearchProvider)
            self.assertIsInstance(provider.providers[1], TavilySearchProvider)
            self.assertEqual(provider.providers[1].api_key, "tvly-active-key")


def io_bytes(data: bytes):
    """Helper to simulate urllib.error.HTTPError read stream."""
    import io
    return io.BytesIO(data)


if __name__ == "__main__":
    unittest.main()
