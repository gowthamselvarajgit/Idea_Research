"""Unit tests for SearchSourceCollector integration layer."""

import unittest
from unittest.mock import MagicMock

from src.market_research.duckduckgo_provider import (
    DuckDuckGoHTMLSearchProvider,
    DuckDuckGoHTTPError,
)
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
)
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult
from src.market_research.search_source_collector import (
    SearchSourceCollectionResult,
    SearchSourceCollector,
    SearchSourceCollectorError,
    collect_sources_for_search_query,
)
from src.market_research.source_collection import (
    SourceCollectionFailure,
    SourceCollectionResult,
    WebSourceCollector,
)
from src.market_research.source_contract import validate_web_research_source_record
from src.market_research.source_models import WebResearchSource
from src.market_research.web_source_client import WebSourceClient


class TestSearchSourceCollector(unittest.TestCase):
    """Test suite for SearchSourceCollector integration layer."""

    def _sample_search_result(
        self,
        url: str = "https://example.com/product",
        title: str = "Example Product",
        domain: str = "example.com",
    ) -> SearchResult:
        return SearchResult(
            url=url,
            title=title,
            snippet="High-efficacy skincare cosmetic formulation.",
            domain=domain,
            raw_data={"source": "test"},
        )

    def _sample_web_source(
        self,
        url: str = "https://example.com/product",
        title: str = "Example Product",
        domain: str = "example.com",
    ) -> WebResearchSource:
        return WebResearchSource(
            url=url,
            title=title,
            source_type="competitor",
            publisher_or_domain=domain,
            retrieved_content="Full page article on clinical skincare trial results.",
            retrieved_at="2026-10-08T12:00:00Z",
        )

    def test_search_results_passed_and_urls_forwarded_correctly(self) -> None:
        """1. Search results are passed to WebSourceCollector and URLs are forwarded correctly."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        sr1 = self._sample_search_result("https://a.com/page", "Result A", "a.com")
        sr2 = self._sample_search_result("https://b.com/page", "Result B", "b.com")
        sr3 = self._sample_search_result("https://c.com/page", "Result C", "c.com")
        mock_provider.search.return_value = [sr1, sr2, sr3]

        ws1 = self._sample_web_source("https://a.com/page", "Result A")
        ws2 = self._sample_web_source("https://b.com/page", "Result B")
        ws3 = self._sample_web_source("https://c.com/page", "Result C")
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws1, ws2, ws3),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("skincare innovation", max_results=3)

        # Verify search call
        mock_provider.search.assert_called_once_with("skincare innovation", 3)

        # Verify collector call
        mock_collector.collect_sources.assert_called_once_with(
            urls=["https://a.com/page", "https://b.com/page", "https://c.com/page"],
            source_type="other",
            deduplicate=True,
        )

        self.assertEqual(result.query, "skincare innovation")
        self.assertEqual(len(result.search_results), 3)
        self.assertEqual(len(result.sources), 3)
        self.assertEqual(result.failures, ())
        self.assertEqual(result.success_count, 3)
        self.assertEqual(result.failure_count, 0)

    def test_max_results_respected(self) -> None:
        """2. max_results strictly limits the number of forwarded and collected URLs."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.return_value = [
            self._sample_search_result("https://1.com", "R1", "1.com"),
            self._sample_search_result("https://2.com", "R2", "2.com"),
        ]
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(self._sample_web_source("https://1.com", "R1"),),
            failures=(),
        )

        service = SearchSourceCollector(
            provider=mock_provider,
            collector=mock_collector,
        )
        service.collect_for_query("skincare", max_results=2)

        mock_provider.search.assert_called_once_with("skincare", 2)
        mock_collector.collect_sources.assert_called_once_with(
            urls=["https://1.com", "https://2.com"],
            source_type="other",
            deduplicate=True,
        )

    def test_result_ordering_preserved(self) -> None:
        """3. Result ordering from search discovery is strictly preserved into collection."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        urls = ["https://first.com/x", "https://second.com/y", "https://third.com/z"]
        mock_provider.search.return_value = [
            self._sample_search_result(urls[0], "First", "first.com"),
            self._sample_search_result(urls[1], "Second", "second.com"),
            self._sample_search_result(urls[2], "Third", "third.com"),
        ]
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(
                self._sample_web_source(urls[0], "First"),
                self._sample_web_source(urls[1], "Second"),
                self._sample_web_source(urls[2], "Third"),
            ),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("query", max_results=3)

        self.assertEqual([s.url for s in result.search_results], urls)
        self.assertEqual([s.url for s in result.sources], urls)

    def test_duplicate_urls_not_fetched_twice(self) -> None:
        """4. Duplicate URLs returned by search are deduplicated before source collection."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        # Search returned a duplicate URL
        mock_provider.search.return_value = [
            self._sample_search_result("https://duplicate.com/item", "Dup 1", "duplicate.com"),
            self._sample_search_result("https://unique.com/item", "Unique", "unique.com"),
            self._sample_search_result("https://duplicate.com/item", "Dup 2", "duplicate.com"),
        ]
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(
                self._sample_web_source("https://duplicate.com/item", "Dup 1"),
                self._sample_web_source("https://unique.com/item", "Unique"),
            ),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        service.collect_for_query("query", max_results=3)

        # Forwarded list should only contain unique URLs in order
        mock_collector.collect_sources.assert_called_once_with(
            urls=["https://duplicate.com/item", "https://unique.com/item"],
            source_type="other",
            deduplicate=True,
        )

    def test_successful_sources_returned(self) -> None:
        """5. Successful sources returned by collector are preserved on the result."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.return_value = [
            self._sample_search_result("https://target.com/page", "Target", "target.com")
        ]
        ws = self._sample_web_source("https://target.com/page", "Target")
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws,),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("query")

        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].url, "https://target.com/page")
        self.assertEqual(result.success_count, 1)

    def test_individual_source_fetch_failures_preserved(self) -> None:
        """6. Individual source collection failures are preserved alongside successful sources."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.return_value = [
            self._sample_search_result("https://good.com", "Good", "good.com"),
            self._sample_search_result("https://broken.com", "Broken", "broken.com"),
        ]

        good_source = self._sample_web_source("https://good.com", "Good")
        failure = SourceCollectionFailure(
            url="https://broken.com",
            error_type="WebSourceHTTPError",
            error_message="HTTP request failed with status 404: Not Found",
        )

        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(good_source,),
            failures=(failure,),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("query")

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.total_count, 2)
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].url, "https://broken.com")
        self.assertEqual(result.failures[0].error_type, "WebSourceHTTPError")

    def test_search_provider_failure_handled_clearly(self) -> None:
        """7. Search provider failure raises SearchSourceCollectorError and skips collection."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.side_effect = DuckDuckGoHTTPError("Rate limited 429", status_code=429)

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )

        with self.assertRaises(SearchSourceCollectorError) as ctx:
            service.collect_for_query("cosmetics ingredients")

        self.assertIn("Rate limited 429", str(ctx.exception))
        self.assertIsInstance(ctx.exception, SearchProviderError)
        mock_collector.collect_sources.assert_not_called()

    def test_empty_search_results_handled_correctly(self) -> None:
        """8. Empty search results return an empty result without invoking collector."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.return_value = []

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("nonexistent phrase")

        self.assertEqual(result.query, "nonexistent phrase")
        self.assertEqual(result.search_results, ())
        self.assertEqual(result.sources, ())
        self.assertEqual(result.failures, ())
        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.failure_count, 0)
        mock_collector.collect_sources.assert_not_called()

    def test_existing_contracts_remain_compatible(self) -> None:
        """9. Integration with real provider/collector components adheres to all strict contracts."""
        sample_ddg_html = """
        <div class="result">
          <a class="result__a" href="https://example.com/skincare-ai">AI Skin Diagnostics</a>
          <div class="result__snippet">Machine learning analysis for custom cosmetics.</div>
        </div>
        """
        fake_page_html = """
        <!DOCTYPE html>
        <html><head><title>AI Skin Diagnostics</title></head>
        <body><article><p>Detailed dermatology study on automated skin classification.</p></article></body>
        </html>
        """

        provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: sample_ddg_html
        )
        mock_web_client = MagicMock(spec=WebSourceClient)
        mock_web_client.fetch_source.return_value = WebResearchSource(
            url="https://example.com/skincare-ai",
            title="AI Skin Diagnostics",
            source_type="competitor",
            publisher_or_domain="example.com",
            retrieved_content="Detailed dermatology study on automated skin classification.",
            retrieved_at="2026-10-08T12:00:00Z",
        )

        collector = WebSourceCollector(client=mock_web_client)
        service = SearchSourceCollector(
            search_provider=provider,
            source_collector=collector,
        )

        result = service.collect_for_query("AI skin analysis", max_results=1, source_type="competitor")

        # Verify contracts
        self.assertEqual(len(result.search_results), 1)
        validate_search_result_record(result.search_results[0])

        self.assertEqual(len(result.sources), 1)
        validate_web_research_source_record(result.sources[0])

        # Verify dictionary representation
        data = result.to_dict()
        self.assertEqual(data["query"], "AI skin analysis")
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 0)
        self.assertEqual(len(data["sources"]), 1)
        self.assertEqual(len(data["search_results"]), 1)

    def test_input_validation(self) -> None:
        """10. Rejects invalid query and invalid max_results parameters."""
        service = SearchSourceCollector(search_provider=MagicMock(spec=SearchProvider))

        # Invalid query
        for bad_q in ["", "   ", None, 123]:
            with self.subTest(bad_q=bad_q):
                with self.assertRaises(SearchQueryValidationError):
                    service.collect_for_query(bad_q)  # type: ignore[arg-type]

        # Invalid max_results
        for bad_m in [0, -1, "5", True, None]:
            with self.subTest(bad_m=bad_m):
                with self.assertRaises(SearchQueryValidationError):
                    service.collect_for_query("skincare", max_results=bad_m)  # type: ignore[arg-type]

    def test_convenience_aliases_and_functional_helper(self) -> None:
        """11. Aliases search_and_collect, collect_sources_for_query, and functional helper work."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        mock_provider.search.return_value = [
            self._sample_search_result("https://test.com", "Test", "test.com")
        ]
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(self._sample_web_source("https://test.com", "Test"),),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )

        # Test search_and_collect alias
        res1 = service.search_and_collect("test query")
        self.assertEqual(res1.success_count, 1)

        # Test collect_sources_for_query alias
        res2 = service.collect_sources_for_query("test query")
        self.assertEqual(res2.success_count, 1)

        # Test functional helper
        res3 = collect_sources_for_search_query(
            query="test query",
            search_provider_or_client=mock_provider,
            source_collector=mock_collector,
        )
        self.assertEqual(res3.success_count, 1)

    def test_search_metadata_preserved_on_collected_sources(self) -> None:
        """12. Search discovery metadata (query, snippet, publisher, engine, relevance) is preserved in source raw_data."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        sr = SearchResult(
            url="https://innovate.example.com/skincare-tech",
            title="AI Skin Diagnostics",
            snippet="Breakthrough computer vision model for dermal analysis.",
            domain="innovate.example.com",
            raw_data={
                "engine": "google_news_rss",
                "publisher": "Tech Daily",
                "relevance_reason": "Accepted: Matched configured subject term",
                "pub_date": "Fri, 09 Oct 2026 12:00:00 GMT",
            },
        )
        mock_provider.search.return_value = [sr]

        crawler_meta = {
            "initial_url": "https://innovate.example.com/skincare-tech",
            "final_url": "https://innovate.example.com/skincare-tech",
            "http_status": 200,
            "content_type": "text/html",
        }
        ws = WebResearchSource(
            url="https://innovate.example.com/skincare-tech",
            title="AI Skin Diagnostics",
            source_type="industry",
            publisher_or_domain="innovate.example.com",
            retrieved_content="Clinical review text.",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data=crawler_meta,
        )
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws,),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("AI dermal diagnostics", max_results=1)

        self.assertEqual(len(result.sources), 1)
        enriched = result.sources[0]

        # Verify discovery metadata is preserved
        self.assertEqual(enriched.raw_data["search_query"], "AI dermal diagnostics")
        self.assertEqual(enriched.raw_data["search_snippet"], "Breakthrough computer vision model for dermal analysis.")
        self.assertEqual(enriched.raw_data["search_publisher"], "Tech Daily")
        self.assertEqual(enriched.raw_data["search_engine"], "google_news_rss")
        self.assertEqual(enriched.raw_data["relevance_reason"], "Accepted: Matched configured subject term")
        self.assertEqual(enriched.raw_data["search_url"], "https://innovate.example.com/skincare-tech")
        self.assertEqual(enriched.raw_data["original_search_url"], "https://innovate.example.com/skincare-tech")
        self.assertEqual(enriched.raw_data["pub_date"], "Fri, 09 Oct 2026 12:00:00 GMT")

        # Verify original source object was not mutated (immutability)
        self.assertNotIn("search_query", ws.raw_data)

    def test_existing_crawler_metadata_remains_intact(self) -> None:
        """13. Existing crawler metadata (initial_url, final_url, http_status, etc.) is preserved."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        sr = SearchResult(
            url="https://crawler.example.com/item",
            title="Title",
            snippet="Snippet",
            domain="crawler.example.com",
            raw_data={"engine": "duckduckgo_html"},
        )
        mock_provider.search.return_value = [sr]

        crawler_meta = {
            "initial_url": "https://crawler.example.com/item",
            "final_url": "https://crawler.example.com/item/redirected",
            "http_status": 200,
            "content_type": "text/html; charset=utf-8",
            "content_length": 8192,
            "redirected": True,
        }
        ws = WebResearchSource(
            url="https://crawler.example.com/item/redirected",
            title="Title",
            source_type="industry",
            publisher_or_domain="crawler.example.com",
            retrieved_content="Content text.",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data=crawler_meta,
        )
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws,),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("crawler query", max_results=1)

        enriched = result.sources[0]
        # Crawler fields are completely intact
        self.assertEqual(enriched.raw_data["initial_url"], "https://crawler.example.com/item")
        self.assertEqual(enriched.raw_data["final_url"], "https://crawler.example.com/item/redirected")
        self.assertEqual(enriched.raw_data["http_status"], 200)
        self.assertEqual(enriched.raw_data["content_type"], "text/html; charset=utf-8")
        self.assertEqual(enriched.raw_data["content_length"], 8192)
        self.assertTrue(enriched.raw_data["redirected"])

        # And search metadata is also present
        self.assertEqual(enriched.raw_data["search_query"], "crawler query")
        self.assertEqual(enriched.raw_data["search_engine"], "duckduckgo_html")

    def test_multiple_results_matched_to_correct_sources(self) -> None:
        """14. Multiple distinct search results correlate to their exact matching sources."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        sr1 = SearchResult(
            url="https://site1.com/a",
            title="Title 1",
            snippet="Snippet 1",
            domain="site1.com",
            raw_data={"engine": "e1", "publisher": "Pub1", "relevance_reason": "r1"},
        )
        sr2 = SearchResult(
            url="https://site2.com/b",
            title="Title 2",
            snippet="Snippet 2",
            domain="site2.com",
            raw_data={"engine": "e2", "publisher": "Pub2", "relevance_reason": "r2"},
        )
        sr3 = SearchResult(
            url="https://site3.com/c",
            title="Title 3",
            snippet="Snippet 3",
            domain="site3.com",
            raw_data={"engine": "e3", "publisher": "Pub3", "relevance_reason": "r3"},
        )
        mock_provider.search.return_value = [sr1, sr2, sr3]

        ws1 = WebResearchSource(
            url="https://site1.com/a",
            title="Title 1",
            source_type="news",
            publisher_or_domain="site1.com",
            retrieved_content="Content 1",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"initial_url": "https://site1.com/a", "http_status": 200},
        )
        ws2 = WebResearchSource(
            url="https://site2.com/b",
            title="Title 2",
            source_type="news",
            publisher_or_domain="site2.com",
            retrieved_content="Content 2",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"initial_url": "https://site2.com/b", "http_status": 200},
        )
        ws3 = WebResearchSource(
            url="https://site3.com/c",
            title="Title 3",
            source_type="news",
            publisher_or_domain="site3.com",
            retrieved_content="Content 3",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"initial_url": "https://site3.com/c", "http_status": 200},
        )
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws1, ws2, ws3),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("multi query", max_results=3)

        self.assertEqual(len(result.sources), 3)
        res_ws1, res_ws2, res_ws3 = result.sources

        self.assertEqual(res_ws1.raw_data["search_snippet"], "Snippet 1")
        self.assertEqual(res_ws1.raw_data["search_publisher"], "Pub1")
        self.assertEqual(res_ws1.raw_data["relevance_reason"], "r1")

        self.assertEqual(res_ws2.raw_data["search_snippet"], "Snippet 2")
        self.assertEqual(res_ws2.raw_data["search_publisher"], "Pub2")
        self.assertEqual(res_ws2.raw_data["relevance_reason"], "r2")

        self.assertEqual(res_ws3.raw_data["search_snippet"], "Snippet 3")
        self.assertEqual(res_ws3.raw_data["search_publisher"], "Pub3")
        self.assertEqual(res_ws3.raw_data["relevance_reason"], "r3")

    def test_unmatched_sources_retained_without_fabricated_metadata(self) -> None:
        """15. Sources without matching search results are retained as-is without fabricated metadata."""
        mock_provider = MagicMock(spec=SearchProvider)
        mock_collector = MagicMock(spec=WebSourceCollector)

        sr = SearchResult(
            url="https://matched.com/page",
            title="Matched",
            snippet="Matched snippet",
            domain="matched.com",
            raw_data={"engine": "google_news_rss"},
        )
        mock_provider.search.return_value = [sr]

        ws_matched = WebResearchSource(
            url="https://matched.com/page",
            title="Matched",
            source_type="news",
            publisher_or_domain="matched.com",
            retrieved_content="Matched content",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"initial_url": "https://matched.com/page", "http_status": 200},
        )
        ws_unmatched = WebResearchSource(
            url="https://unmatched.com/unrelated",
            title="Unmatched",
            source_type="news",
            publisher_or_domain="unmatched.com",
            retrieved_content="Unmatched content",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"initial_url": "https://unmatched.com/unrelated", "http_status": 200},
        )
        mock_collector.collect_sources.return_value = SourceCollectionResult(
            sources=(ws_matched, ws_unmatched),
            failures=(),
        )

        service = SearchSourceCollector(
            search_provider=mock_provider,
            source_collector=mock_collector,
        )
        result = service.collect_for_query("partial query", max_results=2)

        self.assertEqual(len(result.sources), 2)
        res_matched, res_unmatched = result.sources

        # Matched source has search metadata
        self.assertEqual(res_matched.raw_data["search_snippet"], "Matched snippet")
        self.assertEqual(res_matched.raw_data["search_url"], "https://matched.com/page")

        # Unmatched source retains its original raw_data without fabricated search keys
        self.assertNotIn("search_query", res_unmatched.raw_data)
        self.assertNotIn("search_snippet", res_unmatched.raw_data)
        self.assertNotIn("search_engine", res_unmatched.raw_data)
        self.assertEqual(res_unmatched.raw_data["http_status"], 200)
        self.assertEqual(res_unmatched.raw_data["initial_url"], "https://unmatched.com/unrelated")


if __name__ == "__main__":
    unittest.main()

