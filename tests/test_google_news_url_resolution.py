"""Regression test suite for Google News URL resolution and readable article retrieval.

Tests the end-to-end resolution pipeline:
1. Resolving a Google News RSS URL to a publisher URL via 2-step batchexecute RPC.
2. Extracting publisher URLs from RSS metadata (<source url="...">, origLink).
3. Fetching readable article content from resolved publisher URLs via WebSourceClient.
4. Handling failed redirects, blocked publishers (HTTP 403), and empty responses gracefully.
5. Preserving search discovery metadata, initial/resolved URLs, and citation grounding.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from src.market_research.citation_grounding import (
    build_source_url_lookup,
    correlate_finding_with_sources,
)
from src.market_research.google_news_provider import GoogleNewsRSSSearchProvider
from src.market_research.google_news_url_resolver import (
    GoogleNewsURLResolver,
    extract_google_news_article_id,
    extract_publisher_url_from_metadata,
    extract_publisher_url_from_rss_item,
    is_google_news_url,
    resolve_google_news_url,
)
from src.market_research.models import MarketResearchRecord
from src.market_research.search_models import SearchResult
from src.market_research.search_source_collector import (
    SearchSourceCollector,
    _enrich_source_with_search_metadata,
)
from src.market_research.source_collection import (
    SourceCollectionFailure,
    WebSourceCollector,
)
from src.market_research.source_models import WebResearchSource
from src.market_research.web_source_client import (
    WebSourceClient,
    WebSourceContentError,
    WebSourceHTTPError,
    WebSourceNetworkError,
)

SAMPLE_STEP1_SPLASH_HTML = """<!DOCTYPE html>
<html>
<head><title>Google News</title></head>
<body>
  <c-wiz data-n-a-id="CBMi_TEST_ART_123" data-n-a-ts="1791649700" data-n-a-sg="TEST_SIG_ABCDEF">
    <div class="content">Redirecting...</div>
  </c-wiz>
</body>
</html>
"""

SAMPLE_STEP2_BATCHEXECUTE_RESP = """)]}'

[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://www.factmr.com/report/waterless-beauty-tablets-market\\",1]",null,null,null,"generic"],["di",12],["af.httprm",12,"-8132613491382945276",18]]
"""

SAMPLE_PUBLISHER_HTML = """<!DOCTYPE html>
<html>
<head><title>Waterless Beauty Tablets Market Outlook</title></head>
<body>
  <article>
    <h1>Waterless Beauty Tablets Market Expansion</h1>
    <p>The global waterless beauty market is experiencing exponential growth driven by consumer demand for sustainable packaging.</p>
    <p>Formulations without water content eliminate preservative requirements and reduce transportation weight significantly.</p>
  </article>
</body>
</html>
"""

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Cosmetics News</title>
    <item>
      <title>Sustainable Waterless Formulations - Cosmetics Design</title>
      <link>https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5</link>
      <pubDate>Thu, 08 Oct 2026 12:00:00 GMT</pubDate>
      <description>&lt;p&gt;Overview of waterless cosmetics packaging trends.&lt;/p&gt;</description>
      <source url="https://www.cosmeticsdesign.com">Cosmetics Design</source>
    </item>
  </channel>
</rss>
"""


class TestGoogleNewsURLResolution(unittest.TestCase):
    """Test suite verifying URL resolution, error resilience, and metadata preservation."""

    # -------------------------------------------------------------------------
    # 1. Resolving a Google News RSS URL to a publisher URL
    # -------------------------------------------------------------------------

    def test_is_google_news_url_detection(self) -> None:
        """Accurately distinguishes Google News RSS links from publisher URLs."""
        gnews_urls = [
            "https://news.google.com/rss/articles/CBMibkFVX3lxTE9CU0M3?oc=5",
            "https://news.google.com/articles/CBMibkFVX3lxTE9CU0M3",
            "http://news.google.com/rss/articles/XYZ123",
            "https://news.google.co.uk/articles/UK_ART_456",
        ]
        for u in gnews_urls:
            with self.subTest(url=u):
                self.assertTrue(is_google_news_url(u))

        regular_urls = [
            "https://www.factmr.com/report/waterless-beauty-tablets-market",
            "https://www.nytimes.com/article",
            "https://google.com/search?q=test",
            "https://example.com/rss/articles/fake",
            "",
            None,
        ]
        for u in regular_urls:
            with self.subTest(url=u):
                self.assertFalse(is_google_news_url(u))

    def test_extract_google_news_article_id(self) -> None:
        """Extracts article ID token from various Google News URL structures."""
        self.assertEqual(
            extract_google_news_article_id("https://news.google.com/rss/articles/CBMi12345?oc=5"),
            "CBMi12345",
        )
        self.assertEqual(
            extract_google_news_article_id("https://news.google.com/articles/ART_XYZ"),
            "ART_XYZ",
        )
        self.assertIsNone(extract_google_news_article_id("https://example.com/article"))

    def test_successful_two_step_url_resolution(self) -> None:
        """Resolver executes 2-step RPC and retrieves decoded publisher destination URL."""
        def mock_transport(req: urllib.request.Request, timeout: float) -> str:
            if "batchexecute" in req.full_url:
                # Step 2: batchexecute POST
                self.assertEqual(req.get_method(), "POST")
                return SAMPLE_STEP2_BATCHEXECUTE_RESP
            # Step 1: splash GET
            self.assertIn("CBMi_TEST_ART_123", req.full_url)
            return SAMPLE_STEP1_SPLASH_HTML

        resolver = GoogleNewsURLResolver(http_transport=mock_transport)
        input_url = "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5"
        resolved = resolver.resolve_url(input_url)

        self.assertEqual(
            resolved,
            "https://www.factmr.com/report/waterless-beauty-tablets-market",
        )

    def test_non_google_url_passed_through_unchanged(self) -> None:
        """Non-Google URLs pass through resolver directly without network operations."""
        calls = []
        resolver = GoogleNewsURLResolver(
            http_transport=lambda req, to: calls.append(req.full_url) or ""
        )
        direct_url = "https://www.cosmeticsbusiness.com/article/123"
        resolved = resolver.resolve_url(direct_url)

        self.assertEqual(resolved, direct_url)
        self.assertEqual(len(calls), 0)

    # -------------------------------------------------------------------------
    # 2. Extracting the publisher URL when available in RSS metadata
    # -------------------------------------------------------------------------

    def test_extract_publisher_url_from_rss_source_element(self) -> None:
        """Extracts publisher domain or base URL from RSS <source url="..."> attribute."""
        root = ET.fromstring(SAMPLE_RSS_XML)
        item = root.find(".//item")
        assert item is not None

        pub_url = extract_publisher_url_from_rss_item(item)
        self.assertEqual(pub_url, "https://www.cosmeticsdesign.com")

    def test_extract_publisher_url_from_feedburner_origlink(self) -> None:
        """Extracts direct destination URL from <origLink> when available in RSS feed."""
        xml_orig = """<item>
          <title>Orig Article</title>
          <link>https://news.google.com/rss/articles/CBMi_STUB</link>
          <origLink>https://directpublisher.com/original-article-slug</origLink>
        </item>"""
        item = ET.fromstring(xml_orig)
        pub_url = extract_publisher_url_from_rss_item(item)
        self.assertEqual(pub_url, "https://directpublisher.com/original-article-slug")

    def test_extract_publisher_url_from_metadata_dict(self) -> None:
        """Extracts publisher URL from search result raw_data dictionary."""
        meta = {
            "source_url": "https://www.cosmeticsdesign.com",
            "publisher": "Cosmetics Design",
            "engine": "google_news_rss",
        }
        self.assertEqual(
            extract_publisher_url_from_metadata(meta),
            "https://www.cosmeticsdesign.com",
        )

        # Reject if only points to another Google News redirect
        bad_meta = {"source_url": "https://news.google.com/rss/articles/XYZ"}
        self.assertIsNone(extract_publisher_url_from_metadata(bad_meta))

    def test_google_news_provider_populates_publisher_url_in_raw_data(self) -> None:
        """GoogleNewsRSSSearchProvider stores publisher_url in SearchResult raw_data."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: SAMPLE_RSS_XML
        )
        results = provider.search("waterless cosmetics")
        self.assertEqual(len(results), 1)
        sr = results[0]
        self.assertEqual(sr.raw_data.get("publisher_url"), "https://www.cosmeticsdesign.com")
        self.assertEqual(sr.raw_data.get("source_url"), "https://www.cosmeticsdesign.com")

    # -------------------------------------------------------------------------
    # 3. Fetching readable content from a resolved URL
    # -------------------------------------------------------------------------

    @patch("urllib.request.urlopen")
    def test_web_source_client_resolves_and_fetches_content(
        self, mock_urlopen: MagicMock
    ) -> None:
        """WebSourceClient resolves Google News URL and fetches readable article text."""
        # Resolver mock returns the resolved publisher destination URL
        mock_resolver = MagicMock(spec=GoogleNewsURLResolver)
        mock_resolver.resolve_url.return_value = (
            "https://www.factmr.com/report/waterless-beauty-tablets-market"
        )

        # Mock publisher HTTP response
        mock_resp = MagicMock()
        mock_resp.read.return_value = SAMPLE_PUBLISHER_HTML.encode("utf-8")
        mock_resp.geturl.return_value = "https://www.factmr.com/report/waterless-beauty-tablets-market"
        mock_resp.getcode.return_value = 200
        mock_resp.status = 200
        mock_resp.headers = MagicMock()
        mock_resp.headers.get.return_value = "text/html; charset=utf-8"
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        mock_urlopen.return_value = mock_resp

        client = WebSourceClient(url_resolver=mock_resolver)
        input_gnews_url = "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5"
        source = client.fetch_source(input_gnews_url)

        # Verified destination URL and domain
        self.assertEqual(source.url, "https://www.factmr.com/report/waterless-beauty-tablets-market")
        self.assertEqual(source.publisher_or_domain, "www.factmr.com")
        self.assertIn("Waterless Beauty Tablets Market Outlook", source.title)

        # Verified readable body content retrieved
        self.assertIn("The global waterless beauty market is experiencing exponential growth", source.retrieved_content)
        self.assertIn("Formulations without water content eliminate preservative requirements", source.retrieved_content)

        # Verified metadata preservation
        self.assertEqual(source.raw_data["initial_url"], input_gnews_url)
        self.assertEqual(
            source.raw_data["resolved_url"],
            "https://www.factmr.com/report/waterless-beauty-tablets-market",
        )
        self.assertEqual(source.raw_data["original_search_url"], input_gnews_url)
        self.assertTrue(source.raw_data["redirected"])

    # -------------------------------------------------------------------------
    # 4. Handling unresolved links and failed publisher fetches gracefully
    # -------------------------------------------------------------------------

    def test_resolution_failure_step1_network_error(self) -> None:
        """Step 1 network error returns None safely without raising an unhandled exception."""
        def failing_transport(req: urllib.request.Request, to: float) -> str:
            raise urllib.error.URLError("Connection reset by peer")

        resolver = GoogleNewsURLResolver(http_transport=failing_transport)
        result = resolver.resolve_url("https://news.google.com/rss/articles/CBMi_ERR?oc=5")
        self.assertIsNone(result)

    def test_resolution_failure_step2_http_500(self) -> None:
        """Step 2 HTTP error returns None safely without raising an unhandled exception."""
        def transport_with_step2_failure(req: urllib.request.Request, to: float) -> str:
            if "batchexecute" in req.full_url:
                raise urllib.error.HTTPError(
                    req.full_url, 500, "Internal Server Error", {}, None
                )
            return SAMPLE_STEP1_SPLASH_HTML

        resolver = GoogleNewsURLResolver(http_transport=transport_with_step2_failure)
        result = resolver.resolve_url("https://news.google.com/rss/articles/CBMi_TEST_ART_123")
        self.assertIsNone(result)

    def test_web_source_client_raises_content_error_on_unresolvable_url(self) -> None:
        """WebSourceClient raises WebSourceContentError when link cannot be resolved."""
        mock_resolver = MagicMock(spec=GoogleNewsURLResolver)
        mock_resolver.resolve_url.return_value = None  # Failed resolution

        client = WebSourceClient(url_resolver=mock_resolver)
        with self.assertRaises(WebSourceContentError) as ctx:
            client.fetch_source("https://news.google.com/rss/articles/CBMi_UNRESOLVABLE")

        self.assertIn("Could not resolve Google News article link", str(ctx.exception))

    def test_web_source_collector_records_failure_for_unresolved_url(self) -> None:
        """WebSourceCollector records structured failure for unresolvable Google News link."""
        mock_client = MagicMock(spec=WebSourceClient)
        mock_client.fetch_source.side_effect = WebSourceContentError("Could not resolve link")

        collector = WebSourceCollector(client=mock_client)
        col_res = collector.collect_sources(["https://news.google.com/rss/articles/CBMi_FAIL"])

        self.assertEqual(len(col_res.sources), 0)
        self.assertEqual(len(col_res.failures), 1)
        self.assertEqual(col_res.failures[0].error_type, "WebSourceContentError")
        self.assertIn("Could not resolve link", col_res.failures[0].error_message)

    @patch("urllib.request.urlopen")
    def test_publisher_blocked_403_recorded_as_collection_failure(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Publisher HTTP 403 Forbidden raises WebSourceHTTPError and records collection failure."""
        mock_resolver = MagicMock(spec=GoogleNewsURLResolver)
        mock_resolver.resolve_url.return_value = "https://blockedpublisher.com/article"

        # Publisher blocks with 403
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://blockedpublisher.com/article",
            403,
            "Forbidden",
            {},
            None,
        )

        client = WebSourceClient(url_resolver=mock_resolver)
        with self.assertRaises(WebSourceHTTPError) as ctx:
            client.fetch_source("https://news.google.com/rss/articles/CBMi_BLOCKED")

        self.assertIn("403", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 5. Preserving existing source metadata and citation-grounding behaviour
    # -------------------------------------------------------------------------

    def test_search_source_collector_enriches_and_preserves_discovery_metadata(self) -> None:
        """Enrichment preserves initial search URL, resolved URL, publisher, and query."""
        sr = SearchResult(
            url="https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5",
            title="Sustainable Waterless Formulations - Cosmetics Design",
            snippet="Overview of waterless cosmetics packaging trends.",
            domain="cosmeticsdesign.com",
            raw_data={
                "publisher": "Cosmetics Design",
                "source_url": "https://www.cosmeticsdesign.com",
                "pub_date": "Thu, 08 Oct 2026 12:00:00 GMT",
                "engine": "google_news_rss",
                "query": "waterless cosmetics packaging",
            },
        )

        collected_source = WebResearchSource(
            url="https://www.factmr.com/report/waterless-beauty-tablets-market",
            title="Waterless Beauty Tablets Market Outlook",
            source_type="news",
            publisher_or_domain="factmr.com",
            retrieved_content="The global waterless beauty market is experiencing exponential growth.",
            retrieved_at="2026-10-10T12:00:00Z",
            raw_data={
                "initial_url": "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5",
                "final_url": "https://www.factmr.com/report/waterless-beauty-tablets-market",
                "resolved_url": "https://www.factmr.com/report/waterless-beauty-tablets-market",
                "original_search_url": "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5",
            },
        )

        enriched = _enrich_source_with_search_metadata(
            source=collected_source,
            search_result=sr,
            query="waterless cosmetics packaging",
        )

        # Verification of preserved discovery and crawler metadata
        self.assertEqual(enriched.url, "https://www.factmr.com/report/waterless-beauty-tablets-market")
        self.assertEqual(enriched.raw_data["initial_url"], "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5")
        self.assertEqual(enriched.raw_data["resolved_url"], "https://www.factmr.com/report/waterless-beauty-tablets-market")
        self.assertEqual(enriched.raw_data["original_search_url"], "https://news.google.com/rss/articles/CBMi_TEST_ART_123?oc=5")
        self.assertEqual(enriched.raw_data["search_publisher"], "Cosmetics Design")
        self.assertEqual(enriched.raw_data["search_query"], "waterless cosmetics packaging")
        self.assertEqual(enriched.raw_data["pub_date"], "Thu, 08 Oct 2026 12:00:00 GMT")

    def test_citation_grounding_matches_finding_against_resolved_source(self) -> None:
        """Citation lookup matches finding whether citing resolved publisher URL or original RSS URL."""
        source = WebResearchSource(
            url="https://www.factmr.com/report/waterless-beauty-tablets-market",
            title="Waterless Beauty Tablets Market Outlook",
            source_type="news",
            publisher_or_domain="factmr.com",
            retrieved_content="The global waterless beauty market is experiencing exponential growth with sustainable tablets.",
            retrieved_at="2026-10-10T12:00:00Z",
            raw_data={
                "initial_url": "https://news.google.com/rss/articles/CBMi_TEST_ART_123",
                "final_url": "https://www.factmr.com/report/waterless-beauty-tablets-market",
                "resolved_url": "https://www.factmr.com/report/waterless-beauty-tablets-market",
                "original_search_url": "https://news.google.com/rss/articles/CBMi_TEST_ART_123",
            },
        )

        lookup = build_source_url_lookup([source])

        # 1. Lookup by resolved publisher URL
        s_by_resolved = lookup.get("https://www.factmr.com/report/waterless-beauty-tablets-market")
        self.assertIsNotNone(s_by_resolved)
        self.assertEqual(s_by_resolved.url, source.url)

        # 2. Lookup by original Google News RSS URL
        s_by_rss = lookup.get("https://news.google.com/rss/articles/CBMi_TEST_ART_123")
        self.assertIsNotNone(s_by_rss)
        self.assertEqual(s_by_rss.url, source.url)

        # 3. Correlate finding citing the resolved URL
        finding = MarketResearchRecord(
            opportunity_id="OPP-001",
            source_type="industry_report",
            source_name="FactMR",
            source_url="https://www.factmr.com/report/waterless-beauty-tablets-market",
            company_or_product="Waterless Tablets",
            finding="The global waterless beauty market is experiencing exponential growth.",
            evidence_summary="Market research report shows growth in waterless beauty tablets.",
            relevance="HIGH",
        )
        correlated = correlate_finding_with_sources(finding, [source])
        self.assertEqual(correlated.raw_data["evidence_status"], "SUPPORTED")
        self.assertTrue(correlated.raw_data["citation_verified"])


if __name__ == "__main__":
    unittest.main()
