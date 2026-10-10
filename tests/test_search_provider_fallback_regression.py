"""Focused regression tests for search provider fallback in the live research pipeline.

Validates the seven key fallback requirements:
1. DuckDuckGo returns results — they are used.
2. DuckDuckGo raises an exception — Google News RSS is attempted.
3. DuckDuckGo returns an empty list — the fallback is attempted.
4. Both providers fail — failures are reported without crashing unrelated pipeline stages.
5. Both providers return the same URL — duplicates are handled correctly.
6. Search metadata and source relevance filtering remain intact.
7. The live orchestrator actually uses the configured composite provider.
"""

from collections.abc import Sequence
from typing import Any, Optional
import unittest
from unittest.mock import MagicMock, patch

from src.market_research.duckduckgo_provider import (
    DuckDuckGoChallengeError,
    DuckDuckGoHTMLSearchProvider,
)
from src.market_research.fallback_search_provider import (
    FallbackSearchProvider,
    FallbackSearchProviderError,
    create_default_search_provider,
)
from src.market_research.google_news_provider import (
    GoogleNewsHTTPError,
    GoogleNewsRSSSearchProvider,
    evaluate_candidate_relevance,
)
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
)
from src.market_research.search_models import SearchResult
from src.market_research.search_source_collector import (
    SearchSourceCollectionResult,
    SearchSourceCollector,
    SearchSourceCollectorError,
)
from src.market_research.source_collection import (
    SourceCollectionFailure,
    WebSourceCollector,
)
from src.market_research.source_models import WebResearchSource
from src.patents.research_config import ResearchDomainConfig
from src.research.research_orchestrator import (
    ResearchOrchestrationResult,
    ResearchOrchestrator,
)
from src.research.research_service import PatentResearchResult, ResearchService


class MockSearchProvider:
    """Deterministic mock search provider supporting subject_terms kwarg."""

    def __init__(
        self,
        name: str = "MockSearchProvider",
        results: Optional[Sequence[SearchResult]] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        self.name = name
        self.results = list(results) if results is not None else []
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        max_results: int = 10,
        *,
        subject_terms: Optional[Sequence[str]] = None,
    ) -> list[SearchResult]:
        self.calls.append({
            "query": query,
            "max_results": max_results,
            "subject_terms": subject_terms,
        })
        if self.exception is not None:
            raise self.exception
        return self.results


class TestSearchProviderFallbackRegression(unittest.TestCase):
    """Regression suite testing search provider fallback in the live research pipeline."""

    def _make_search_result(
        self,
        url: str,
        title: str = "Test Title",
        snippet: str = "Test snippet content.",
        domain: str = "example.com",
        engine: str = "test_engine",
    ) -> SearchResult:
        return SearchResult(
            url=url,
            title=title,
            snippet=snippet,
            domain=domain,
            raw_data={"engine": engine},
        )

    def _make_patent_result(self, run_id: str = "run-test") -> PatentResearchResult:
        return PatentResearchResult(
            run_id=run_id,
            theme="Cosmetics",
            generated_queries=["skincare"],
            executed_queries=["skincare"],
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )

    def _make_web_source(
        self,
        url: str,
        title: str = "Test Title",
        source_type: str = "news",
        publisher_or_domain: str = "example.com",
        retrieved_content: str = (
            "Comprehensive technical article discussing botanical formulation stability, "
            "chemical standardization methods, and active ingredient shelf-life in clean cosmetic products."
        ),
        raw_data: Optional[dict[str, Any]] = None,
    ) -> WebResearchSource:
        return WebResearchSource(
            url=url,
            title=title,
            source_type=source_type,
            publisher_or_domain=publisher_or_domain,
            retrieved_content=retrieved_content,
            retrieved_at="2026-10-10T12:00:00Z",
            raw_data=raw_data or {},
        )

    # -------------------------------------------------------------------------
    # 1. DuckDuckGo returns results — they are used
    # -------------------------------------------------------------------------
    def test_1_duckduckgo_returns_results_they_are_used(self) -> None:
        """When DuckDuckGo returns valid results, they are returned and fallback is skipped."""
        ddg_results = [
            self._make_search_result("https://ddg.example.com/res1", "DDG 1", engine="duckduckgo_html"),
            self._make_search_result("https://ddg.example.com/res2", "DDG 2", engine="duckduckgo_html"),
        ]
        gnews_results = [
            self._make_search_result("https://gnews.example.com/res1", "GNews 1", engine="google_news_rss"),
        ]

        mock_ddg = MockSearchProvider(name="DuckDuckGoHTMLSearchProvider", results=ddg_results)
        mock_gnews = MockSearchProvider(name="GoogleNewsRSSSearchProvider", results=gnews_results)

        composite = FallbackSearchProvider([mock_ddg, mock_gnews])
        results = composite.search("skincare formulations", max_results=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://ddg.example.com/res1")
        self.assertEqual(results[1].url, "https://ddg.example.com/res2")
        self.assertEqual(len(mock_ddg.calls), 1)
        self.assertEqual(len(mock_gnews.calls), 0, "Google News must not be called when DDG succeeds")

    # -------------------------------------------------------------------------
    # 2. DuckDuckGo raises an exception — Google News RSS is attempted
    # -------------------------------------------------------------------------
    def test_2_duckduckgo_raises_exception_google_news_rss_attempted(self) -> None:
        """When DuckDuckGo raises DuckDuckGoChallengeError, Google News RSS is attempted and succeeds."""
        mock_ddg = MockSearchProvider(
            name="DuckDuckGoHTMLSearchProvider",
            exception=DuckDuckGoChallengeError("anti-bot challenge (status=202)", status_code=202),
        )
        gnews_results = [
            self._make_search_result("https://gnews.example.com/article1", "GNews Hit 1", engine="google_news_rss"),
            self._make_search_result("https://gnews.example.com/article2", "GNews Hit 2", engine="google_news_rss"),
        ]
        mock_gnews = MockSearchProvider(name="GoogleNewsRSSSearchProvider", results=gnews_results)

        composite = FallbackSearchProvider([mock_ddg, mock_gnews])
        results = composite.search(
            '"skincare" technology',
            max_results=5,
            subject_terms=("skincare",),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://gnews.example.com/article1")
        self.assertEqual(results[1].url, "https://gnews.example.com/article2")
        self.assertEqual(len(mock_ddg.calls), 1)
        self.assertEqual(len(mock_gnews.calls), 1)
        self.assertEqual(mock_gnews.calls[0]["subject_terms"], ("skincare",))

    # -------------------------------------------------------------------------
    # 3. DuckDuckGo returns an empty list — the fallback is attempted
    # -------------------------------------------------------------------------
    def test_3_duckduckgo_returns_empty_list_fallback_attempted(self) -> None:
        """When DuckDuckGo returns an empty list, Google News RSS fallback is attempted."""
        mock_ddg = MockSearchProvider(name="DuckDuckGoHTMLSearchProvider", results=[])
        gnews_results = [
            self._make_search_result("https://gnews.example.com/niche", "Niche Botanical", engine="google_news_rss"),
        ]
        mock_gnews = MockSearchProvider(name="GoogleNewsRSSSearchProvider", results=gnews_results)

        composite = FallbackSearchProvider([mock_ddg, mock_gnews])
        results = composite.search('"niche botanical" extraction', max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://gnews.example.com/niche")
        self.assertEqual(len(mock_ddg.calls), 1)
        self.assertEqual(len(mock_gnews.calls), 1)

    # -------------------------------------------------------------------------
    # 4. Both providers fail — failures are reported without crashing pipeline
    # -------------------------------------------------------------------------
    def test_4_both_providers_fail_reported_without_crashing_pipeline(self) -> None:
        """When all search providers fail, collector raises error with attempts, and orchestrator isolates it."""
        mock_ddg = MockSearchProvider(
            name="DuckDuckGoHTMLSearchProvider",
            exception=DuckDuckGoChallengeError("Challenge 202", status_code=202),
        )
        mock_gnews = MockSearchProvider(
            name="GoogleNewsRSSSearchProvider",
            exception=GoogleNewsHTTPError("503 Service Unavailable", status_code=503),
        )
        composite = FallbackSearchProvider([mock_ddg, mock_gnews])

        # A. Verify FallbackSearchProvider raises FallbackSearchProviderError with attempt telemetry
        with self.assertRaises(FallbackSearchProviderError) as ctx:
            composite.search("failing query", max_results=3)
        self.assertEqual(len(ctx.exception.attempts), 2)
        self.assertEqual(ctx.exception.attempts[0]["status"], "error")
        self.assertEqual(ctx.exception.attempts[1]["status"], "error")

        # B. Verify SearchSourceCollector wraps into SearchSourceCollectorError
        collector = SearchSourceCollector(search_provider=composite)
        with self.assertRaises(SearchSourceCollectorError) as collector_ctx:
            collector.collect_for_query("failing query", max_results=3)
        self.assertIn("All 2 search providers failed", str(collector_ctx.exception))

        # C. Verify ResearchOrchestrator Stage 6 captures failure without aborting pipeline
        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = self._make_patent_result("run-test-fallback-fail")
        mock_query_gen = MagicMock()
        mock_query_gen.generate_queries.return_value = MagicMock(queries=["failing query"])

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            search_collector=collector,
            query_generator=mock_query_gen,
        )
        domain_cfg = ResearchDomainConfig(domain_name="Cosmetics", themes=("skincare",), description="Cosmetics")

        # Must execute without raising exception
        orch_result = orch.run_research(domain_cfg, max_web_queries=1)
        self.assertTrue(orch_result.is_success)
        self.assertEqual(orch_result.web_source_count, 0)
        self.assertEqual(orch_result.web_failure_count, 1)
        self.assertIn("failing query", orch_result.web_collection_failures[0].url)

    # -------------------------------------------------------------------------
    # 5. Both providers return the same URL — duplicates are handled correctly
    # -------------------------------------------------------------------------
    def test_5_both_providers_return_same_url_duplicates_handled(self) -> None:
        """When fallback providers or multiple queries return identical URLs, duplicates are stripped."""
        shared_url = "https://industry-news.com/article"

        # Within FallbackSearchProvider result list: duplicate URLs are stripped
        dup_results = [
            self._make_search_result(shared_url, "Article Copy 1"),
            self._make_search_result(shared_url, "Article Copy 2"),
            self._make_search_result("https://unique.com/1", "Unique 1"),
        ]
        mock_provider = MockSearchProvider(results=dup_results)
        composite = FallbackSearchProvider([mock_provider])
        deduped = composite.search("query", max_results=5)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].url, shared_url)
        self.assertEqual(deduped[1].url, "https://unique.com/1")

        # Across orchestrator queries: Query 1 uses DDG, Query 2 uses fallback Google News
        mock_collector = MagicMock(spec=SearchSourceCollector)
        source1 = self._make_web_source(
            url=shared_url,
            publisher_or_domain="industry-news.com",
            retrieved_content="Content 1",
        )
        source2 = self._make_web_source(
            url="https://unique2.com/page",
            publisher_or_domain="unique2.com",
            retrieved_content="Content 2",
        )
        source3_duplicate = self._make_web_source(
            url=shared_url,
            publisher_or_domain="industry-news.com",
            retrieved_content="Content 1 Duplicate from Fallback",
        )

        mock_collector.collect_for_query.side_effect = [
            SearchSourceCollectionResult(
                query="query 1",
                search_results=(),
                sources=(source1, source2),
                failures=(),
            ),
            SearchSourceCollectionResult(
                query="query 2",
                search_results=(),
                sources=(source3_duplicate,),
                failures=(),
            ),
        ]

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = self._make_patent_result("run-dedup")
        mock_query_gen = MagicMock()
        mock_query_gen.generate_queries.return_value = MagicMock(queries=["query 1", "query 2"])

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            search_collector=mock_collector,
            query_generator=mock_query_gen,
        )
        domain_cfg = ResearchDomainConfig(domain_name="Cosmetics", themes=("skincare",), description="Desc")
        res = orch.run_research(domain_cfg, max_web_queries=2)

        # shared_url must only appear ONCE in collected_web_sources
        collected_urls = [s.url for s in res.collected_web_sources]
        self.assertEqual(len(collected_urls), 2)
        self.assertEqual(collected_urls, [shared_url, "https://unique2.com/page"])

    # -------------------------------------------------------------------------
    # 6. Search metadata and source relevance filtering remain intact
    # -------------------------------------------------------------------------
    def test_6_search_metadata_and_source_relevance_filtering_intact(self) -> None:
        """Search metadata is attached by collector, and Google News relevance filtering blocks off-topic results."""
        # A. Metadata preservation
        gnews_item = self._make_search_result(
            "https://cosmetics-daily.com/formula",
            "Botanical Formulations",
            engine="google_news_rss",
        )
        mock_gnews = MockSearchProvider(name="GoogleNewsRSSSearchProvider", results=[gnews_item])
        mock_web_collector = MagicMock(spec=WebSourceCollector)
        mock_web_collector.collect_sources.return_value = MagicMock(
            sources=[
                self._make_web_source(
                    url="https://cosmetics-daily.com/formula",
                    publisher_or_domain="cosmetics-daily.com",
                    source_type="other",
                )
            ],
            failures=[],
        )

        collector = SearchSourceCollector(
            search_provider=mock_gnews,
            source_collector=mock_web_collector,
        )
        res = collector.collect_for_query("formula", max_results=1)
        self.assertEqual(len(res.sources), 1)
        self.assertEqual(res.sources[0].raw_data.get("engine"), "google_news_rss")

        # B. Relevance filtering validation
        # Off-topic crypto/trading article must be rejected
        off_topic_decision = evaluate_candidate_relevance(
            title="Crypto Trading App Launches",
            snippet="Best stock trading and cryptocurrency investment platform for 2026.",
            domain="cryptonews.com",
            publisher="CryptoNews",
            query='"skincare" technology',
            url="https://cryptonews.com/app",
            subject_terms=("skincare", "cosmetics"),
        )
        self.assertFalse(off_topic_decision.accepted)
        self.assertIn("off-topic negative term", off_topic_decision.reason.lower())

        # On-topic skincare article must be accepted
        on_topic_decision = evaluate_candidate_relevance(
            title="AI Formulation Engine Launches for Skincare Brands",
            snippet="New platform simulates cosmetic vehicle stability and active ingredient shelf-life.",
            domain="cosmeticsdesign.com",
            publisher="CosmeticsDesign",
            query='"skincare" technology',
            url="https://cosmeticsdesign.com/ai-skincare",
            subject_terms=("skincare", "cosmetics"),
        )
        self.assertTrue(on_topic_decision.accepted)

    # -------------------------------------------------------------------------
    # 7. The live orchestrator actually uses the configured composite provider
    # -------------------------------------------------------------------------
    def test_7_orchestrator_uses_configured_composite_provider(self) -> None:
        """ResearchOrchestrator uses FallbackSearchProvider with DDG and Google News RSS by default, and supports custom provider injection."""
        # A. Default instantiation wires FallbackSearchProvider with DDG + Google News RSS
        default_orch = ResearchOrchestrator()
        default_provider = default_orch.search_collector.provider
        self.assertIsInstance(default_provider, FallbackSearchProvider)
        self.assertEqual(len(default_provider.providers), 2)
        self.assertIsInstance(default_provider.providers[0], DuckDuckGoHTMLSearchProvider)
        self.assertIsInstance(default_provider.providers[1], GoogleNewsRSSSearchProvider)

        # B. Custom provider injection via ResearchOrchestrator.__init__
        custom_provider = MockSearchProvider(name="CustomSearchComposite")
        custom_orch = ResearchOrchestrator(search_provider=custom_provider)
        self.assertIs(custom_orch.search_collector.provider, custom_provider)

        # C. End-to-end stage verification: DDG fails, Google News succeeds inside live orchestrator
        mock_ddg = MockSearchProvider(
            name="DuckDuckGoHTMLSearchProvider",
            exception=DuckDuckGoChallengeError("anti-bot challenge 202", status_code=202),
        )
        mock_gnews = MockSearchProvider(
            name="GoogleNewsRSSSearchProvider",
            results=[
                self._make_search_result(
                    "https://live-test.com/botanical-ai",
                    "Botanical AI News",
                    engine="google_news_rss",
                )
            ],
        )
        live_composite = FallbackSearchProvider([mock_ddg, mock_gnews])

        mock_web_collector = MagicMock(spec=WebSourceCollector)
        mock_web_collector.collect_sources.return_value = MagicMock(
            sources=[
                self._make_web_source(
                    url="https://live-test.com/botanical-ai",
                    publisher_or_domain="live-test.com",
                    source_type="news",
                )
            ],
            failures=[],
        )

        live_collector = SearchSourceCollector(
            search_provider=live_composite,
            source_collector=mock_web_collector,
        )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = self._make_patent_result("run-live-composite")
        mock_query_gen = MagicMock()
        mock_query_gen.generate_queries.return_value = MagicMock(queries=['"skincare" technology'])

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            search_collector=live_collector,
            query_generator=mock_query_gen,
        )
        domain_cfg = ResearchDomainConfig(domain_name="Cosmetics", themes=("skincare",), description="Desc")
        run_res = orch.run_research(domain_cfg, max_web_queries=1)

        self.assertEqual(len(mock_ddg.calls), 1, "DDG must have been attempted first")
        self.assertEqual(len(mock_gnews.calls), 1, "Google News must have been called as fallback")
        self.assertEqual(run_res.web_source_count, 1)
        self.assertEqual(run_res.collected_web_sources[0].url, "https://live-test.com/botanical-ai")


if __name__ == "__main__":
    unittest.main()
