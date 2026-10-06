"""Unit tests for SearchClient and SearchProvider abstraction."""

from unittest.mock import MagicMock
import unittest

from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
    search,
)
from src.market_research.search_models import SearchResult


class TestSearchClient(unittest.TestCase):
    """Test suite for web search discovery client and provider abstraction."""

    def _sample_result(
        self,
        url: str = "https://example.com/item",
        title: str = "Example Item",
        domain: str = "example.com",
    ) -> SearchResult:
        """Helper to create a valid SearchResult."""
        return SearchResult(
            url=url,
            title=title,
            snippet="Relevant excerpt describing the product or solution.",
            domain=domain,
            raw_data={"rank": 1},
        )

    def test_constructor_requires_provider(self) -> None:
        """SearchClient raises ValueError if provider is None."""
        with self.assertRaises(ValueError):
            SearchClient(provider=None)  # type: ignore

    def test_invalid_or_empty_query_rejected(self) -> None:
        """Empty or non-string search query raises SearchQueryValidationError."""
        mock_provider = MagicMock(spec=SearchProvider)
        client = SearchClient(provider=mock_provider)

        invalid_queries = ["", "   ", None, 123, True]
        for bad_query in invalid_queries:
            with self.subTest(bad_query=bad_query):
                with self.assertRaises(SearchQueryValidationError):
                    client.search(query=bad_query)  # type: ignore

        mock_provider.search.assert_not_called()

    def test_max_results_validation(self) -> None:
        """max_results must be an integer between 1 and 100."""
        mock_provider = MagicMock(spec=SearchProvider)
        client = SearchClient(provider=mock_provider)

        # Invalid types or bounds
        invalid_max = [0, -5, 101, 200, 5.5, True, False, "10", None]
        for bad_max in invalid_max:
            with self.subTest(bad_max=bad_max):
                with self.assertRaises(SearchQueryValidationError):
                    client.search(query="autonomous pipe robot", max_results=bad_max)  # type: ignore

        mock_provider.search.assert_not_called()

    def test_successful_search_and_result_ordering(self) -> None:
        """Search client passes query to provider and preserves result order."""
        mock_provider = MagicMock(spec=SearchProvider)
        res1 = self._sample_result("https://a.com", "Result A", "a.com")
        res2 = self._sample_result("https://b.com", "Result B", "b.com")
        res3 = self._sample_result("https://c.com", "Result C", "c.com")

        mock_provider.search.return_value = [res1, res2, res3]

        client = SearchClient(provider=mock_provider)
        results = client.search(query="pipe crawler", max_results=3)

        mock_provider.search.assert_called_once_with("pipe crawler", 3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].url, "https://a.com")
        self.assertEqual(results[1].url, "https://b.com")
        self.assertEqual(results[2].url, "https://c.com")

    def test_http_https_url_filtering(self) -> None:
        """Results with non-HTTP/HTTPS URLs or malformed URLs are filtered out."""
        mock_provider = MagicMock(spec=SearchProvider)

        # Construct raw mock items where one has an unsupported scheme
        valid_res = self._sample_result("https://valid.com", "Valid", "valid.com")
        invalid_url_res = MagicMock(spec=SearchResult)
        invalid_url_res.url = "ftp://files.com/doc"

        mock_provider.search.return_value = [valid_res, invalid_url_res]

        client = SearchClient(provider=mock_provider)
        results = client.search(query="test query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://valid.com")

    def test_empty_provider_result_handling(self) -> None:
        """Provider returning an empty list returns an empty tuple cleanly."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_provider.search.return_value = []

        client = SearchClient(provider=mock_provider)
        results = client.search(query="nonexistent term")

        self.assertEqual(results, ())

    def test_provider_failure_propagation(self) -> None:
        """Provider exceptions are caught and wrapped into SearchProviderError."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_provider.search.side_effect = RuntimeError("Provider API rate limit exceeded")

        client = SearchClient(provider=mock_provider)
        with self.assertRaises(SearchProviderError) as ctx:
            client.search(query="drain robotics")

        self.assertIn("rate limit", str(ctx.exception).lower())

    def test_functional_search_wrapper(self) -> None:
        """Functional search() helper executes properly with injected provider."""
        mock_provider = MagicMock(spec=SearchProvider)
        res = self._sample_result()
        mock_provider.search.return_value = [res]

        results = search(query="crawler", max_results=5, provider=mock_provider)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, res.url)

        with self.assertRaises(ValueError):
            search(query="crawler", provider=None)


if __name__ == "__main__":
    unittest.main()
