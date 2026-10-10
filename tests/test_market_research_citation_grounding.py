"""Focused unit tests for hardened citation URL grounding and source metadata correlation."""

import unittest
from unittest.mock import MagicMock

from src.market_research.citation_grounding import (
    build_source_url_lookup,
    correlate_finding_with_sources,
    correlate_findings_with_sources,
    normalize_citation_url,
)
from src.market_research.models import MarketResearchRecord
from src.market_research.output_parser import parse_market_research_output
from src.market_research.service import MarketResearchService
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.models import OpportunityRecord


class TestCitationGrounding(unittest.TestCase):
    """Test suite covering hardened URL normalization, citation verification, and metadata correlation."""

    def _sample_source(
        self,
        url: str = "https://aquamembrane.example.com/spec",
        search_query: str = '"membrane biofouling" competitors',
        search_engine: str = "google_news_rss",
        search_publisher: str = "AquaMembrane Press",
        relevance_reason: str = "Matched configured subject term: 'membrane biofouling'",
        http_status: int = 200,
        initial_url: str = "https://aquamembrane.example.com/spec",
        content: str = "Technical specifications for reverse osmosis filtration units with detailed membrane permeability and contaminant rejection metrics.",
        source_id: str = None,
    ) -> WebResearchSource:
        """Helper to create a WebResearchSource populated with discovery metadata."""
        return WebResearchSource(
            url=url,
            title="AquaMembrane Official Specification",
            source_type="competitor",
            publisher_or_domain="aquamembrane.example.com",
            retrieved_content=content,
            retrieved_at="2026-10-10T10:00:00Z",
            id=source_id,
            raw_data={
                "search_query": search_query,
                "search_engine": search_engine,
                "search_publisher": search_publisher,
                "relevance_reason": relevance_reason,
                "http_status": http_status,
                "initial_url": initial_url,
                "final_url": url,
            },
        )

    def _sample_finding(
        self,
        source_url: str = "https://aquamembrane.example.com/spec",
        finding: str = "Competitor provides standard RO membranes with quarterly chemical washes.",
        opp_id: str = "opp-101",
        raw_data: dict = None,
    ) -> MarketResearchRecord:
        """Helper to create a MarketResearchRecord."""
        return MarketResearchRecord(
            opportunity_id=opp_id,
            source_type="competitor_site",
            source_name="AquaMembrane Press",
            source_url=source_url,
            company_or_product="AquaMembrane X",
            finding=finding,
            evidence_summary="Public specs confirm quarterly chemical wash requirement.",
            relevance="HIGH",
            raw_data=raw_data if raw_data is not None else {"ai_raw_output": {"finding": finding}},
        )

    # 1. Valid citation matching a collected source
    def test_valid_citation_matches_collected_source(self) -> None:
        """A valid citation URL matching a collected source is verified and enriched."""
        source = self._sample_source(url="https://aquamembrane.example.com/spec")
        finding = self._sample_finding(source_url="https://aquamembrane.example.com/spec")

        correlated = correlate_finding_with_sources(finding, [source])

        # Assert verification flags
        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertFalse(correlated.raw_data.get("unmatched_citation"))
        self.assertEqual(
            correlated.raw_data.get("matched_source_url"),
            "https://aquamembrane.example.com/spec",
        )

        # Assert discovery metadata copied from matching source
        self.assertEqual(
            correlated.raw_data.get("search_query"),
            '"membrane biofouling" competitors',
        )
        self.assertEqual(correlated.raw_data.get("search_engine"), "google_news_rss")
        self.assertEqual(correlated.raw_data.get("search_publisher"), "AquaMembrane Press")
        self.assertEqual(
            correlated.raw_data.get("relevance_reason"),
            "Matched configured subject term: 'membrane biofouling'",
        )
        self.assertEqual(correlated.raw_data.get("http_status"), 200)

    # 2. Fabricated citation URL flagged as unverified
    def test_fabricated_citation_flagged_as_unverified(self) -> None:
        """A fabricated or uncrawled citation URL is flagged as unverified and unmatched."""
        source = self._sample_source(url="https://aquamembrane.example.com/spec")
        finding = self._sample_finding(source_url="https://fake-incumbent-hallucinated.com/product")

        correlated = correlate_finding_with_sources(finding, [source])

        self.assertFalse(correlated.raw_data.get("citation_verified"))
        self.assertTrue(correlated.raw_data.get("unmatched_citation"))
        self.assertNotIn("matched_source_url", correlated.raw_data)
        self.assertNotIn("search_query", correlated.raw_data)
        self.assertNotIn("search_engine", correlated.raw_data)

    # 3. Missing and malformed citation URLs handled safely
    def test_missing_and_malformed_citation_urls_handled_safely(self) -> None:
        """Missing or malformed URLs do not crash and are safely flagged as unverified."""
        source = self._sample_source()

        malformed_urls = [
            "not a url",
            "http://",
            "   ",
            "javascript:void(0)",
            "ftp://files.example.com/doc",
            "http:///no-netloc",
            "https://..",
            "https://example..com",
            "https://example.com:abc/path",
            "example.com/no-scheme",
        ]

        for bad_url in malformed_urls:
            with self.subTest(bad_url=bad_url):
                norm = normalize_citation_url(bad_url)
                self.assertEqual(norm, "", f"Expected empty string for malformed '{bad_url}'")

                dummy_record = MarketResearchRecord(
                    opportunity_id="opp-1",
                    source_type="other",
                    source_name="Unknown",
                    source_url=bad_url if bad_url.strip() else "https://placeholder.org",
                    company_or_product="Test",
                    finding="Test finding",
                    evidence_summary="Test evidence",
                    relevance="LOW",
                )
                correlated = correlate_finding_with_sources(dummy_record, [source])
                self.assertFalse(correlated.raw_data.get("citation_verified"))
                self.assertTrue(correlated.raw_data.get("unmatched_citation"))

    # 4. URL normalization for genuine harmless differences
    def test_url_normalization_harmless_differences(self) -> None:
        """Harmless differences (host casing, fragments, trailing slash, default port) match."""
        canonical = "https://example.com/product"
        source = self._sample_source(url=canonical)

        variations = [
            "https://EXAMPLE.COM/product",               # Host casing
            "https://example.com/product#specifications",# URL fragment
            "https://example.com/product/",              # Trailing slash on path
            "https://EXAMPLE.COM/product/#specs",        # casing + trailing slash + fragment
            "https://example.com:443/product",           # Default HTTPS port
            "https://example.com:443/product/",          # Default HTTPS port + trailing slash
        ]

        for variant in variations:
            with self.subTest(variant=variant):
                finding = self._sample_finding(source_url=variant)
                correlated = correlate_finding_with_sources(finding, [source])
                self.assertTrue(
                    correlated.raw_data.get("citation_verified"),
                    f"Variant '{variant}' failed to match canonical '{canonical}'",
                )
                self.assertFalse(correlated.raw_data.get("unmatched_citation"))

    # 5. www. host variants do NOT automatically match without explicit crawler link
    def test_www_host_variants_do_not_automatically_match(self) -> None:
        """www.example.com and example.com are NOT assumed equivalent without explicit crawler metadata."""
        # Source has non-www URL and no www link in raw_data
        source_non_www = self._sample_source(url="https://example.com/article")
        finding_www = self._sample_finding(source_url="https://www.example.com/article")

        correlated = correlate_finding_with_sources(finding_www, [source_non_www])
        self.assertFalse(
            correlated.raw_data.get("citation_verified"),
            "www.example.com should not automatically match example.com without crawler link",
        )
        self.assertTrue(correlated.raw_data.get("unmatched_citation"))

        # Reverse check: Source has www URL, finding cites non-www
        source_www = self._sample_source(url="https://www.example.com/article")
        finding_non_www = self._sample_finding(source_url="https://example.com/article")

        correlated_rev = correlate_finding_with_sources(finding_non_www, [source_www])
        self.assertFalse(
            correlated_rev.raw_data.get("citation_verified"),
            "example.com should not automatically match www.example.com without crawler link",
        )
        self.assertTrue(correlated_rev.raw_data.get("unmatched_citation"))

    # 6. Explicit redirect linking www and non-www DOES match
    def test_explicit_redirect_linking_www_and_non_www_matches(self) -> None:
        """When crawler metadata explicitly records a redirect between www and non-www, it legitimately matches."""
        source_redirected = WebResearchSource(
            url="https://www.example.com/article",
            title="Article",
            source_type="news",
            publisher_or_domain="example.com",
            retrieved_content="Content",
            retrieved_at="2026-10-10T10:00:00Z",
            raw_data={
                "initial_url": "https://example.com/article",
                "final_url": "https://www.example.com/article",
                "search_url": "https://example.com/article",
                "search_engine": "google_news_rss",
            },
        )

        # Finding citing pre-redirect non-www URL matches the source
        finding = self._sample_finding(source_url="https://example.com/article")
        correlated = correlate_finding_with_sources(finding, [source_redirected])
        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertEqual(
            correlated.raw_data.get("matched_source_url"),
            "https://www.example.com/article",
        )

    # 7. Different subdomains do NOT match
    def test_different_subdomains_do_not_match(self) -> None:
        """Subdomains (app, api, blog, docs) are preserved strictly and do not cross-match."""
        source = self._sample_source(url="https://app.example.com/dashboard")

        unrelated_subdomains = [
            "https://api.example.com/dashboard",
            "https://blog.example.com/dashboard",
            "https://example.com/dashboard",
            "https://docs.example.com/dashboard",
        ]

        for other_url in unrelated_subdomains:
            with self.subTest(other_url=other_url):
                finding = self._sample_finding(source_url=other_url)
                correlated = correlate_finding_with_sources(finding, [source])
                self.assertFalse(
                    correlated.raw_data.get("citation_verified"),
                    f"Subdomain '{other_url}' incorrectly matched 'https://app.example.com/dashboard'",
                )

    # 8. Different paths or query parameters do NOT match
    def test_different_paths_and_query_params_do_not_match(self) -> None:
        """Materially different paths, query parameters, or domains are not treated as matches."""
        source = self._sample_source(url="https://example.com/product/alpha?lang=en")

        non_matching_urls = [
            "https://example.com/product/beta?lang=en",      # Different subpath
            "https://example.com/product?lang=en",           # Truncated path
            "https://example.com/product/alpha?lang=es",      # Different query parameter
            "https://example.com/product/alpha",             # Missing query parameter
            "https://otherexample.com/product/alpha?lang=en",# Different domain
            "http://example.com/product/alpha?lang=en",       # Different scheme
        ]

        for non_match in non_matching_urls:
            with self.subTest(non_match=non_match):
                finding = self._sample_finding(source_url=non_match)
                correlated = correlate_finding_with_sources(finding, [source])
                self.assertFalse(
                    correlated.raw_data.get("citation_verified"),
                    f"URL '{non_match}' incorrectly matched 'https://example.com/product/alpha?lang=en'",
                )
                self.assertTrue(correlated.raw_data.get("unmatched_citation"))

    # 9. Search-result URLs that are not the actual cited page do NOT match
    def test_search_result_url_for_different_page_does_not_match(self) -> None:
        """A finding citing a different article on the same domain does not match a collected source."""
        source = self._sample_source(
            url="https://techcrunch.com/2026/10/water-startup-launch",
            initial_url="https://techcrunch.com/2026/10/water-startup-launch",
        )

        # Finding cites an uncrawled article on the same publisher
        finding = self._sample_finding(source_url="https://techcrunch.com/2026/10/unrelated-ai-app")
        correlated = correlate_finding_with_sources(finding, [source])

        self.assertFalse(correlated.raw_data.get("citation_verified"))
        self.assertTrue(correlated.raw_data.get("unmatched_citation"))

    # 10. Ambiguous URLs across multiple distinct sources are NOT verified
    def test_ambiguous_url_across_multiple_sources_is_not_verified(self) -> None:
        """When multiple distinct collected sources share a URL (e.g. redirect collision), it is excluded as ambiguous."""
        common_error_url = "https://example.com/auth-error"

        # Source 1: Article A that redirected to common_error_url
        src1 = self._sample_source(
            url=common_error_url,
            content="Error page text for source 1",
            initial_url="https://example.com/article-1",
            source_id="src-1",
        )
        # Source 2: Article B that ALSO redirected to common_error_url
        src2 = self._sample_source(
            url=common_error_url,
            content="Error page text for source 2 (different body)",
            initial_url="https://example.com/article-2",
            source_id="src-2",
        )

        lookup = build_source_url_lookup([src1, src2])

        # The shared redirect destination is ambiguous
        self.assertTrue(lookup.is_ambiguous(common_error_url))
        self.assertIsNone(lookup.get(common_error_url))

        # A finding citing the ambiguous common URL must NOT be verified
        finding_ambiguous = self._sample_finding(source_url=common_error_url)
        correlated_ambiguous = correlate_finding_with_sources(finding_ambiguous, lookup)

        self.assertFalse(correlated_ambiguous.raw_data.get("citation_verified"))
        self.assertTrue(correlated_ambiguous.raw_data.get("unmatched_citation"))
        self.assertTrue(correlated_ambiguous.raw_data.get("ambiguous_citation"))

        # However, a finding citing Source 1's unique initial URL is unambiguously verified
        finding_src1 = self._sample_finding(source_url="https://example.com/article-1")
        correlated_src1 = correlate_finding_with_sources(finding_src1, lookup)
        self.assertTrue(correlated_src1.raw_data.get("citation_verified"))
        self.assertEqual(correlated_src1.raw_data.get("matched_source_url"), common_error_url)

    # 11. Existing raw_data preserved while discovery metadata is added
    def test_existing_raw_data_preserved_while_metadata_added(self) -> None:
        """Existing raw_data keys (e.g. ai_raw_output) remain intact alongside verification data."""
        source = self._sample_source(url="https://aquamembrane.example.com/spec")
        initial_raw = {
            "ai_raw_output": {"finding": "original ai text", "score": 95},
            "custom_pipeline_tag": "run-phase-7",
        }
        finding = self._sample_finding(
            source_url="https://aquamembrane.example.com/spec",
            raw_data=initial_raw,
        )

        correlated = correlate_finding_with_sources(finding, [source])

        # Assert prior keys retained
        self.assertEqual(
            correlated.raw_data.get("ai_raw_output"),
            {"finding": "original ai text", "score": 95},
        )
        self.assertEqual(correlated.raw_data.get("custom_pipeline_tag"), "run-phase-7")

        # Assert new keys added
        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertEqual(correlated.raw_data.get("search_engine"), "google_news_rss")

    # 12. Multiple sources and multiple findings correlated correctly
    def test_multiple_sources_and_multiple_findings_correlated_correctly(self) -> None:
        """Multiple sources correlate to their respective findings without cross-contamination."""
        src_a = self._sample_source(
            url="https://source-a.com/page",
            search_query="query A",
            search_engine="ddg",
            search_publisher="Publisher A",
        )
        src_b = self._sample_source(
            url="https://source-b.com/item/",
            search_query="query B",
            search_engine="google_news_rss",
            search_publisher="Publisher B",
        )
        src_c = self._sample_source(
            url="https://source-c.com/spec",
            search_query="query C",
            search_engine="tavily",
            search_publisher="Publisher C",
        )

        f1 = self._sample_finding(source_url="https://source-a.com/page", finding="Finding 1")
        f2 = self._sample_finding(source_url="https://source-b.com/item#section", finding="Finding 2")
        f3 = self._sample_finding(source_url="https://source-c.com/spec/", finding="Finding 3")
        f4 = self._sample_finding(source_url="https://unrelated-fake.com/blog", finding="Finding 4")

        correlated = correlate_findings_with_sources([f1, f2, f3, f4], [src_a, src_b, src_c])

        self.assertEqual(len(correlated), 4)

        # F1 matched to src_a
        self.assertTrue(correlated[0].raw_data["citation_verified"])
        self.assertEqual(correlated[0].raw_data["search_publisher"], "Publisher A")
        self.assertEqual(correlated[0].raw_data["search_engine"], "ddg")

        # F2 matched to src_b
        self.assertTrue(correlated[1].raw_data["citation_verified"])
        self.assertEqual(correlated[1].raw_data["search_publisher"], "Publisher B")
        self.assertEqual(correlated[1].raw_data["search_engine"], "google_news_rss")

        # F3 matched to src_c
        self.assertTrue(correlated[2].raw_data["citation_verified"])
        self.assertEqual(correlated[2].raw_data["search_publisher"], "Publisher C")
        self.assertEqual(correlated[2].raw_data["search_engine"], "tavily")

        # F4 unmatched
        self.assertFalse(correlated[3].raw_data["citation_verified"])
        self.assertTrue(correlated[3].raw_data["unmatched_citation"])
        self.assertNotIn("search_publisher", correlated[3].raw_data)

    # 13. WebEvidenceAnalyzer integration returns correlated findings
    def test_web_evidence_analyzer_returns_correlated_findings(self) -> None:
        """WebEvidenceAnalyzer.analyze returns records with citation_verified properly set."""
        source = self._sample_source(url="https://competitor.com/product")
        raw_finding = self._sample_finding(source_url="https://competitor.com/product")

        mock_service = MagicMock(spec=MarketResearchService)
        mock_service.conduct_market_research.return_value = [raw_finding]

        analyzer = WebEvidenceAnalyzer(market_research_service=mock_service)
        results = analyzer.analyze("opp-101", sources=[source])

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].raw_data.get("citation_verified"))
        self.assertFalse(results[0].raw_data.get("unmatched_citation"))
        self.assertEqual(results[0].raw_data.get("search_engine"), "google_news_rss")

    # 14. parse_market_research_output supports optional sources kwarg
    def test_parse_market_research_output_with_sources(self) -> None:
        """parse_market_research_output correlates findings when sources parameter is supplied."""
        raw_json = """[
            {
                "opportunity_id": "opp-101",
                "source_type": "competitor_site",
                "source_name": "Test Press",
                "source_url": "https://matched.com/spec",
                "company_or_product": "Product X",
                "finding": "Key finding",
                "evidence_summary": "Evidence summary",
                "relevance": "HIGH"
            },
            {
                "opportunity_id": "opp-101",
                "source_type": "news",
                "source_name": "Fake News",
                "source_url": "https://unmatched.com/fake",
                "company_or_product": "Product Y",
                "finding": "Unverified finding",
                "evidence_summary": "Unverified summary",
                "relevance": "LOW"
            }
        ]"""
        source = self._sample_source(url="https://matched.com/spec")
        findings = parse_market_research_output(raw_json, "opp-101", sources=[source])

        self.assertEqual(len(findings), 2)
        self.assertTrue(findings[0].raw_data["citation_verified"])
        self.assertFalse(findings[1].raw_data["citation_verified"])
        self.assertTrue(findings[1].raw_data["unmatched_citation"])


if __name__ == "__main__":
    unittest.main()
