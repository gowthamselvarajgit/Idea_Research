"""Unit tests for FallbackSearchProvider generic fallback / composite search provider."""

from unittest.mock import MagicMock, call
import unittest

from src.market_research.fallback_search_provider import (
    AllProvidersFailedError,
    FallbackSearchProvider,
    FallbackSearchProviderError,
)
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
)
from src.market_research.search_models import SearchResult


class FakeSearchProvider:
    """Fake search provider for deterministic unit testing."""

    def __init__(
        self,
        name: str = "FakeProvider",
        results: list[SearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.results = results if results is not None else []
        self.error = error
        self.call_history: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.call_history.append((query, max_results))
        if self.error is not None:
            raise self.error
        return self.results


class TestFallbackSearchProvider(unittest.TestCase):
    """Test suite for FallbackSearchProvider."""

    def _sample_result(
        self,
        url: str = "https://example.com/page",
        title: str = "Example Page",
        snippet: str = "Summary of example page.",
        domain: str = "example.com",
    ) -> SearchResult:
        """Helper to create a valid SearchResult."""
        return SearchResult(
            url=url,
            title=title,
            snippet=snippet,
            domain=domain,
        )

    # -------------------------------------------------------------------------
    # 1. First provider succeeds
    # -------------------------------------------------------------------------
    def test_first_provider_succeeds(self) -> None:
        """When the first provider succeeds, its results are returned immediately."""
        res1 = self._sample_result("https://p1.com/1", "Title 1")
        res2 = self._sample_result("https://p1.com/2", "Title 2")

        p1 = FakeSearchProvider("Provider1", results=[res1, res2])
        p2 = FakeSearchProvider("Provider2", results=[self._sample_result("https://p2.com/1")])

        fallback = FallbackSearchProvider([p1, p2])
        results = fallback.search("skincare competitors", max_results=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://p1.com/1")
        self.assertEqual(results[1].url, "https://p1.com/2")
        self.assertEqual(len(p1.call_history), 1)
        self.assertEqual(len(p2.call_history), 0)

    # -------------------------------------------------------------------------
    # 2. First provider fails; second succeeds
    # -------------------------------------------------------------------------
    def test_first_provider_fails_second_succeeds(self) -> None:
        """When the first provider raises an exception, the second provider is invoked and succeeds."""
        res = self._sample_result("https://p2.com/item", "P2 Item")
        p1 = FakeSearchProvider("Provider1", error=RuntimeError("Connection reset by peer"))
        p2 = FakeSearchProvider("Provider2", results=[res])

        fallback = FallbackSearchProvider([p1, p2])
        results = fallback.search("cosmetic formulation", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://p2.com/item")
        self.assertEqual(len(p1.call_history), 1)
        self.assertEqual(len(p2.call_history), 1)

    # -------------------------------------------------------------------------
    # 3. First provider returns zero results; second succeeds
    # -------------------------------------------------------------------------
    def test_first_provider_zero_results_second_succeeds(self) -> None:
        """When the first provider returns zero results, the second provider is invoked and succeeds."""
        res = self._sample_result("https://p2.com/result", "P2 Result")
        p1 = FakeSearchProvider("Provider1", results=[])
        p2 = FakeSearchProvider("Provider2", results=[res])

        fallback = FallbackSearchProvider([p1, p2])
        results = fallback.search("botanical extracts", max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://p2.com/result")
        self.assertEqual(len(p1.call_history), 1)
        self.assertEqual(len(p2.call_history), 1)

    # -------------------------------------------------------------------------
    # 4. All providers fail
    # -------------------------------------------------------------------------
    def test_all_providers_fail_raises_clear_error(self) -> None:
        """When all providers raise exceptions, FallbackSearchProviderError is raised with attempt telemetry."""
        p1 = FakeSearchProvider("Provider1", error=TimeoutError("Request timed out"))
        p2 = FakeSearchProvider("Provider2", error=ConnectionError("Failed to reach host"))

        fallback = FallbackSearchProvider([p1, p2])
        with self.assertRaises(FallbackSearchProviderError) as ctx:
            fallback.search("skincare technology")

        err = ctx.exception
        self.assertEqual(err.query, "skincare technology")
        self.assertEqual(len(err.attempts), 2)
        self.assertEqual(err.attempts[0]["provider"], "Provider1")
        self.assertEqual(err.attempts[0]["status"], "error")
        self.assertIn("timed out", err.attempts[0]["error_message"])
        self.assertEqual(err.attempts[1]["provider"], "Provider2")
        self.assertEqual(err.attempts[1]["status"], "error")
        self.assertIn("All 2 search providers failed", str(err))

    # -------------------------------------------------------------------------
    # 5. All providers return zero results
    # -------------------------------------------------------------------------
    def test_all_providers_return_zero_results_raises_error(self) -> None:
        """When all providers return zero results, FallbackSearchProviderError is raised with attempt telemetry."""
        p1 = FakeSearchProvider("Provider1", results=[])
        p2 = FakeSearchProvider("Provider2", results=[])

        fallback = FallbackSearchProvider([p1, p2])
        with self.assertRaises(FallbackSearchProviderError) as ctx:
            fallback.search("uncommon niche term")

        err = ctx.exception
        self.assertEqual(err.query, "uncommon niche term")
        self.assertEqual(len(err.attempts), 2)
        self.assertEqual(err.attempts[0]["status"], "zero_results")
        self.assertEqual(err.attempts[1]["status"], "zero_results")
        self.assertIn("zero usable results", str(err))

    # -------------------------------------------------------------------------
    # 6. Duplicate URLs are removed while preserving order
    # -------------------------------------------------------------------------
    def test_duplicate_urls_removed_preserving_order(self) -> None:
        """Duplicate URLs returned by a provider are deduplicated while preserving first-seen order."""
        res_a1 = self._sample_result("https://site.com/a", "Site A1")
        res_b = self._sample_result("https://site.com/b", "Site B")
        res_a2 = self._sample_result("https://site.com/a", "Site A2 duplicate")
        res_c = self._sample_result("https://site.com/c", "Site C")

        p = FakeSearchProvider("Provider", results=[res_a1, res_b, res_a2, res_c])
        fallback = FallbackSearchProvider([p])

        results = fallback.search("skincare brands", max_results=10)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].url, "https://site.com/a")
        self.assertEqual(results[0].title, "Site A1")
        self.assertEqual(results[1].url, "https://site.com/b")
        self.assertEqual(results[2].url, "https://site.com/c")

    # -------------------------------------------------------------------------
    # 7. max_results is respected
    # -------------------------------------------------------------------------
    def test_max_results_is_respected(self) -> None:
        """Returned results are capped at max_results and provider is called with max_results."""
        results_pool = [self._sample_result(f"https://site.com/{i}", f"Title {i}") for i in range(10)]
        p = FakeSearchProvider("Provider", results=results_pool)
        fallback = FallbackSearchProvider([p])

        results = fallback.search("query", max_results=4)
        self.assertEqual(len(results), 4)
        self.assertEqual(p.call_history[0], ("query", 4))

    # -------------------------------------------------------------------------
    # 8. Providers are tried in configured order
    # -------------------------------------------------------------------------
    def test_providers_tried_in_configured_order(self) -> None:
        """Providers are evaluated in the strict sequential order specified during initialization."""
        call_sequence: list[str] = []

        class OrderedFakeProvider:
            def __init__(self, name: str, should_succeed: bool = False) -> None:
                self.name = name
                self.should_succeed = should_succeed

            def search(self, query: str, max_results: int) -> list[SearchResult]:
                call_sequence.append(self.name)
                if not self.should_succeed:
                    raise RuntimeError(f"{self.name} failed")
                return [SearchResult(url="https://win.com", title="Win", snippet="S", domain="win.com")]

        p1 = OrderedFakeProvider("First")
        p2 = OrderedFakeProvider("Second")
        p3 = OrderedFakeProvider("Third", should_succeed=True)
        p4 = OrderedFakeProvider("Fourth")

        fallback = FallbackSearchProvider([p1, p2, p3, p4])
        results = fallback.search("test query")

        self.assertEqual(call_sequence, ["First", "Second", "Third"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://win.com")

    # -------------------------------------------------------------------------
    # 9. No unnecessary fallback occurs after a successful provider
    # -------------------------------------------------------------------------
    def test_no_unnecessary_fallback_after_successful_provider(self) -> None:
        """Once a provider returns usable results, subsequent providers must never be called."""
        res = self._sample_result("https://success.com")
        p1 = FakeSearchProvider("P1", results=[res])
        p2 = FakeSearchProvider("P2", results=[self._sample_result("https://unused.com")])
        p3 = FakeSearchProvider("P3", error=RuntimeError("Must not be called"))

        fallback = FallbackSearchProvider([p1, p2, p3])
        results = fallback.search("query")

        self.assertEqual(len(results), 1)
        self.assertEqual(len(p1.call_history), 1)
        self.assertEqual(len(p2.call_history), 0)
        self.assertEqual(len(p3.call_history), 0)

    # -------------------------------------------------------------------------
    # 10. Multi-provider mixed failure and zero-result chain
    # -------------------------------------------------------------------------
    def test_mixed_failure_and_zero_results_chain(self) -> None:
        """Provider 1 raises error, Provider 2 returns zero results, Provider 3 succeeds."""
        p1 = FakeSearchProvider("P1", error=RuntimeError("Network offline"))
        p2 = FakeSearchProvider("P2", results=[])
        p3 = FakeSearchProvider("P3", results=[self._sample_result("https://p3.com/win")])

        fallback = FallbackSearchProvider([p1, p2, p3])
        results = fallback.search("query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://p3.com/win")
        self.assertEqual(len(p1.call_history), 1)
        self.assertEqual(len(p2.call_history), 1)
        self.assertEqual(len(p3.call_history), 1)

    # -------------------------------------------------------------------------
    # 11. Filtering of non-HTTP / invalid URL results
    # -------------------------------------------------------------------------
    def test_filters_invalid_urls_and_falls_back_if_none_usable(self) -> None:
        """If a provider returns only non-HTTP or malformed URLs, it counts as 0 usable results."""
        mock_bad = MagicMock(spec=SearchResult)
        mock_bad.url = "ftp://ftp.example.com/file"

        mock_mocked = MagicMock(spec=SearchResult)
        mock_mocked.url = "not-a-valid-url"

        p1 = FakeSearchProvider("P1", results=[mock_bad, mock_mocked])  # type: ignore
        p2 = FakeSearchProvider("P2", results=[self._sample_result("https://valid.com")])

        fallback = FallbackSearchProvider([p1, p2])
        results = fallback.search("query")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://valid.com")

    # -------------------------------------------------------------------------
    # 12. Constructor validation
    # -------------------------------------------------------------------------
    def test_constructor_validation(self) -> None:
        """Empty, None, non-sequence, or invalid provider types are rejected."""
        with self.assertRaises(ValueError):
            FallbackSearchProvider(None)  # type: ignore

        with self.assertRaises(ValueError):
            FallbackSearchProvider([])

        with self.assertRaises(TypeError):
            FallbackSearchProvider("not a sequence")  # type: ignore

        with self.assertRaises(TypeError):
            FallbackSearchProvider(123)  # type: ignore

        with self.assertRaises(TypeError):
            FallbackSearchProvider([None])  # type: ignore

        with self.assertRaises(TypeError):
            FallbackSearchProvider(["not a provider"])  # type: ignore

        class ObjectWithoutSearch:
            pass

        with self.assertRaises(TypeError):
            FallbackSearchProvider([ObjectWithoutSearch()])  # type: ignore

    # -------------------------------------------------------------------------
    # 13. Query validation
    # -------------------------------------------------------------------------
    def test_query_validation(self) -> None:
        """Empty, whitespace, or non-string query raises SearchQueryValidationError."""
        p = FakeSearchProvider("P", results=[self._sample_result()])
        fallback = FallbackSearchProvider([p])

        invalid_queries = ["", "   ", "\t\n", None, 123, True]
        for bad_query in invalid_queries:
            with self.subTest(bad_query=bad_query):
                with self.assertRaises(SearchQueryValidationError):
                    fallback.search(bad_query)  # type: ignore

        self.assertEqual(len(p.call_history), 0)

    # -------------------------------------------------------------------------
    # 14. max_results validation
    # -------------------------------------------------------------------------
    def test_max_results_validation(self) -> None:
        """max_results must be an integer between 1 and 100."""
        p = FakeSearchProvider("P", results=[self._sample_result()])
        fallback = FallbackSearchProvider([p])

        invalid_max = [0, -1, 101, 200, 5.5, True, False, "5", None]
        for bad_max in invalid_max:
            with self.subTest(bad_max=bad_max):
                with self.assertRaises(SearchQueryValidationError):
                    fallback.search("valid query", max_results=bad_max)  # type: ignore

        self.assertEqual(len(p.call_history), 0)

    # -------------------------------------------------------------------------
    # 15. SearchProvider protocol compatibility & SearchClient integration
    # -------------------------------------------------------------------------
    def test_search_provider_protocol_and_search_client_integration(self) -> None:
        """FallbackSearchProvider satisfies SearchProvider protocol and integrates into SearchClient."""
        res = self._sample_result("https://client.com/item")
        p = FakeSearchProvider("Underlying", results=[res])
        fallback = FallbackSearchProvider([p])

        # Protocol check
        self.assertIsInstance(fallback, SearchProvider)

        # SearchClient integration
        client = SearchClient(provider=fallback)
        client_results = client.search(query="pipe crawler", max_results=2)

        self.assertEqual(len(client_results), 1)
        self.assertEqual(client_results[0].url, "https://client.com/item")

    # -------------------------------------------------------------------------
    # 16. Providers property immutability
    # -------------------------------------------------------------------------
    def test_providers_property_returns_tuple(self) -> None:
        """providers property returns an immutable tuple of configured providers."""
        p1 = FakeSearchProvider("P1")
        p2 = FakeSearchProvider("P2")
        fallback = FallbackSearchProvider([p1, p2])

        self.assertIsInstance(fallback.providers, tuple)
        self.assertEqual(len(fallback.providers), 2)
        self.assertIs(fallback.providers[0], p1)
        self.assertIs(fallback.providers[1], p2)

    # -------------------------------------------------------------------------
    # 17. Exception alias and inheritance
    # -------------------------------------------------------------------------
    def test_exception_inheritance_and_alias(self) -> None:
        """FallbackSearchProviderError subclasses SearchProviderError and aliases AllProvidersFailedError."""
        self.assertTrue(issubclass(FallbackSearchProviderError, SearchProviderError))
        self.assertIs(AllProvidersFailedError, FallbackSearchProviderError)


if __name__ == "__main__":
    unittest.main()
