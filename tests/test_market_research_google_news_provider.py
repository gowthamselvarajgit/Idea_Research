"""Unit tests for GoogleNewsRSSSearchProvider."""

import socket
import unittest
from unittest.mock import MagicMock
import urllib.error
import urllib.parse
import urllib.request

from src.market_research.duckduckgo_provider import DuckDuckGoHTMLSearchProvider
from src.market_research.fallback_search_provider import FallbackSearchProvider
from src.market_research.google_news_provider import (
    GOOGLE_NEWS_RSS_ENDPOINT,
    GoogleNewsHTTPError,
    GoogleNewsNetworkError,
    GoogleNewsParseError,
    GoogleNewsRSSSearchProvider,
    GoogleNewsSearchError,
    GoogleNewsTimeoutError,
    extract_domain_from_url,
    strip_html_tags,
)
from src.market_research.search_client import SearchClient, SearchProvider
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult

SAMPLE_GOOGLE_NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>"AI skincare" - Google News</title>
    <link>https://news.google.com/search?q=AI+skincare&amp;hl=en-US&amp;gl=US&amp;ceid=US:en</link>
    <description>Google News</description>
    <item>
      <title>From selfie to shelf: how AI skin analysis is changing beauty retail - Cosmetics Business</title>
      <link>https://news.google.com/rss/articles/CBMie0FVX3lxTE9lMjlYSW8w</link>
      <guid isPermaLink="false">CBMie0FVX3lxTE9lMjlYSW8w</guid>
      <pubDate>Wed, 07 Oct 2026 10:15:00 GMT</pubDate>
      <description>&lt;a href="https://news.google.com/rss/articles/CBMie0FVX3lx"&gt;From selfie to shelf&lt;/a&gt; Detailed report on computer vision in cosmetics.</description>
      <source url="https://www.cosmeticsbusiness.com">Cosmetics Business</source>
    </item>
    <item>
      <title>Best AI skin analysis tools in 2026 - Personal Care Insights</title>
      <link>https://news.google.com/rss/articles/CBMi-wFBVV95cUxPZzJrTWZ</link>
      <guid isPermaLink="false">CBMi-wFBVV95cUxPZzJrTWZ</guid>
      <pubDate>Mon, 21 Sep 2026 08:30:00 GMT</pubDate>
      <description>&lt;p&gt;Overview of emerging dermatology applications and routine generators.&lt;/p&gt;</description>
      <source url="https://personalcareinsights.com">Personal Care Insights</source>
    </item>
    <item>
      <title>Duplicate Link Article - Duplicate News</title>
      <link>https://news.google.com/rss/articles/CBMie0FVX3lxTE9lMjlYSW8w</link>
      <description>This duplicate link should be ignored.</description>
      <source url="https://duplicate.com">Duplicate</source>
    </item>
  </channel>
</rss>
"""


class TestGoogleNewsRSSSearchProvider(unittest.TestCase):
    """Test suite for GoogleNewsRSSSearchProvider."""

    def test_strip_html_tags(self) -> None:
        """strip_html_tags unescapes HTML entities and strips tags."""
        raw = '<a href="https://example.com">AI &amp; Skincare</a> <font color="#666">News</font>'
        self.assertEqual(strip_html_tags(raw), "AI & Skincare News")
        self.assertEqual(strip_html_tags(""), "")
        self.assertEqual(strip_html_tags("   "), "")

    def test_extract_domain_from_url(self) -> None:
        """extract_domain_from_url normalizes hostnames and strips www."""
        self.assertEqual(extract_domain_from_url("https://www.cosmeticsbusiness.com/article"), "cosmeticsbusiness.com")
        self.assertEqual(extract_domain_from_url("http://sub.domain.org:8080/path"), "sub.domain.org")
        self.assertIsNone(extract_domain_from_url(""))
        self.assertIsNone(extract_domain_from_url("invalid"))

    def test_successful_rss_parsing(self) -> None:
        """Provider parses valid Google News RSS XML into validated SearchResult records."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: SAMPLE_GOOGLE_NEWS_XML
        )
        results = provider.search("AI skincare", max_results=5)

        # 3 items in sample, 1 is duplicate URL -> exactly 2 unique items
        self.assertEqual(len(results), 2)

        res1 = results[0]
        self.assertEqual(res1.url, "https://news.google.com/rss/articles/CBMie0FVX3lxTE9lMjlYSW8w")
        self.assertEqual(
            res1.title,
            "From selfie to shelf: how AI skin analysis is changing beauty retail - Cosmetics Business",
        )
        self.assertEqual(res1.domain, "cosmeticsbusiness.com")
        self.assertIn("Detailed report on computer vision in cosmetics.", res1.snippet)
        self.assertEqual(res1.raw_data.get("engine"), "google_news_rss")
        self.assertEqual(res1.raw_data.get("publisher"), "Cosmetics Business")
        validate_search_result_record(res1)

        res2 = results[1]
        self.assertEqual(res2.url, "https://news.google.com/rss/articles/CBMi-wFBVV95cUxPZzJrTWZ")
        self.assertEqual(res2.domain, "personalcareinsights.com")
        validate_search_result_record(res2)

    def test_result_limits(self) -> None:
        """max_results parameter bounds the returned results."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: SAMPLE_GOOGLE_NEWS_XML
        )
        results = provider.search("AI skincare", max_results=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/CBMie0FVX3lxTE9lMjlYSW8w")

    def test_missing_fields_safe_fallbacks(self) -> None:
        """Provider safely handles missing snippet, source, and invalid URLs."""
        xml_with_gaps = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <!-- Missing description -> uses title as snippet -->
              <title>Breakthrough in Barrier Repair</title>
              <link>https://news.google.com/rss/articles/123</link>
              <source url="https://dermtimes.com">Derm Times</source>
            </item>
            <item>
              <!-- Missing source -> uses link domain -->
              <title>Clinical Study on Retinoids and Barrier Repair</title>
              <link>https://news.google.com/rss/articles/456</link>
              <description>Results of double-blind study.</description>
            </item>
            <item>
              <!-- Invalid non-HTTP link -> skipped -->
              <title>FTP Link</title>
              <link>ftp://files.org/paper.pdf</link>
              <description>FTP file</description>
            </item>
            <item>
              <!-- Missing title -> skipped -->
              <title>   </title>
              <link>https://news.google.com/rss/articles/789</link>
              <description>Missing title</description>
            </item>
          </channel>
        </rss>
        """
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: xml_with_gaps
        )
        results = provider.search("barrier repair", max_results=5)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].snippet, "Breakthrough in Barrier Repair (Derm Times)")
        self.assertEqual(results[0].domain, "dermtimes.com")
        validate_search_result_record(results[0])

        self.assertEqual(results[1].snippet, "Results of double-blind study.")
        self.assertEqual(results[1].domain, "news.google.com")
        validate_search_result_record(results[1])

    def test_malformed_xml_raises_parse_error(self) -> None:
        """Malformed XML raises GoogleNewsParseError."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: "NOT XML <unclosed tag"
        )
        with self.assertRaises(GoogleNewsParseError):
            provider.search("skincare")

    def test_empty_xml_returns_empty_tuple(self) -> None:
        """Empty XML response returns empty tuple."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: "<rss><channel></channel></rss>"
        )
        results = provider.search("empty query", max_results=3)
        self.assertEqual(results, ())

    def test_http_error(self) -> None:
        """HTTP error raises GoogleNewsHTTPError with status code."""
        def failing_transport(req, to):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=503,
                msg="Service Unavailable",
                hdrs={},  # type: ignore[arg-type]
                fp=None,
            )

        provider = GoogleNewsRSSSearchProvider(http_transport=failing_transport)
        with self.assertRaises(GoogleNewsHTTPError) as ctx:
            provider.search("query")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_timeout_error(self) -> None:
        """Socket timeout raises GoogleNewsTimeoutError."""
        def timeout_transport(req, to):
            raise socket.timeout("timed out")

        provider = GoogleNewsRSSSearchProvider(http_transport=timeout_transport)
        with self.assertRaises(GoogleNewsTimeoutError):
            provider.search("query")

    def test_network_error(self) -> None:
        """URLError raises GoogleNewsNetworkError."""
        def url_err_transport(req, to):
            raise urllib.error.URLError("DNS resolution failure")

        provider = GoogleNewsRSSSearchProvider(http_transport=url_err_transport)
        with self.assertRaises(GoogleNewsNetworkError):
            provider.search("query")

    def test_input_validation(self) -> None:
        """search validates non-empty query and max_results >= 1."""
        provider = GoogleNewsRSSSearchProvider()
        with self.assertRaises(ValueError):
            provider.search("")
        with self.assertRaises(ValueError):
            provider.search("   ")
        with self.assertRaises(ValueError):
            provider.search("query", max_results=0)
        with self.assertRaises(ValueError):
            provider.search("query", max_results=-3)

    def test_url_encoding_and_headers(self) -> None:
        """Query is safely URL encoded into GET request with expected headers."""
        captured_req: list[urllib.request.Request] = []

        def transport(req: urllib.request.Request, to: float) -> str:
            captured_req.append(req)
            return SAMPLE_GOOGLE_NEWS_XML

        provider = GoogleNewsRSSSearchProvider(http_transport=transport)
        provider.search("AI & Skincare: Personalization in 2026", max_results=3)

        self.assertEqual(len(captured_req), 1)
        req = captured_req[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertIn("news.google.com/rss/search", req.full_url)
        self.assertIn("q=AI+%26+Skincare%3A+Personalization+in+2026", req.full_url)

    def test_integration_with_search_client(self) -> None:
        """GoogleNewsRSSSearchProvider conforms to SearchProvider and works in SearchClient."""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: SAMPLE_GOOGLE_NEWS_XML
        )
        self.assertIsInstance(provider, SearchProvider)

        client = SearchClient(provider=provider)
        results = client.search("skincare", max_results=2)
        self.assertEqual(len(results), 2)
        self.assertIsInstance(results, tuple)

    def test_fallback_after_duckduckgo_challenge(self) -> None:
        """FallbackSearchProvider fails over from DuckDuckGo challenge to Google News RSS."""
        challenge_html = """<!DOCTYPE html>
        <html>
        <head><title>DuckDuckGo — Anomaly Detected</title></head>
        <body><div id="challenge-form">Automated traffic detected.</div></body>
        </html>"""

        ddg_provider = DuckDuckGoHTMLSearchProvider(
            http_transport=lambda req, to: challenge_html
        )
        google_news_provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: SAMPLE_GOOGLE_NEWS_XML
        )

        composite = FallbackSearchProvider([ddg_provider, google_news_provider])
        results = composite.search("skincare competitors", max_results=3)

        # DDG raises DuckDuckGoChallengeError, FallbackSearchProvider catches it and queries Google News
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/CBMie0FVX3lxTE9lMjlYSW8w")
        self.assertEqual(results[0].domain, "cosmeticsbusiness.com")

    def test_relevant_results_after_irrelevant_results(self) -> None:
        """Relevant results appearing after irrelevant results are selected until max_results."""
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <!-- Item 1: Off-topic financial result -->
              <title>Best Investment Apps Of 2026 - Forbes</title>
              <link>https://news.google.com/rss/articles/item1</link>
              <description>Comprehensive guide to investment and trading apps.</description>
              <source url="https://forbes.com">Forbes</source>
            </item>
            <item>
              <!-- Item 2: Highly relevant AI skincare result -->
              <title>Best AI skin analysis tools in 2026 - Cosmetics Business</title>
              <link>https://news.google.com/rss/articles/item2</link>
              <description>Review of top dermatology and skin analysis AI applications.</description>
              <source url="https://cosmeticsbusiness.com">Cosmetics Business</source>
            </item>
            <item>
              <!-- Item 3: Off-topic financial result matching only 'competitors' -->
              <title>The Best Trading 212 Alternatives &amp; Competitors - Forbes</title>
              <link>https://news.google.com/rss/articles/item3</link>
              <description>Stock trading and brokerage competitors.</description>
              <source url="https://forbes.com">Forbes</source>
            </item>
            <item>
              <!-- Item 4: Highly relevant skincare brand recommendation result -->
              <title>How AI Is Reshaping Beauty Brand Discovery - BeautyMatter</title>
              <link>https://news.google.com/rss/articles/item4</link>
              <description>Consumer recommendation algorithms in cosmetics and skincare.</description>
              <source url="https://beautymatter.com">BeautyMatter</source>
            </item>
          </channel>
        </rss>"""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("skincare", "skin", "cosmetics", "beauty"),
        )
        results = provider.search('"skincare" competitors', max_results=2)

        # Provider skips item 1 and item 3, returning item 2 and item 4
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/item2")
        self.assertEqual(results[1].url, "https://news.google.com/rss/articles/item4")

        # Diagnostics check
        diag = provider.diagnostics
        self.assertIsNotNone(diag)
        self.assertEqual(diag.feed_items_count, 4)
        self.assertEqual(diag.accepted_count, 2)
        self.assertTrue(diag.rejected_count >= 2)
        self.assertFalse(diag.feed_was_empty)
        self.assertFalse(diag.all_filtered_out)

    def test_missing_snippet_handled_safely(self) -> None:
        """Candidates with missing snippets fall back to title and are evaluated safely."""
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Breakthrough in Skin Barrier Repair Formulations</title>
              <link>https://news.google.com/rss/articles/item_nosnip</link>
              <!-- Empty description -->
              <description></description>
              <source url="https://dermtimes.com">Derm Times</source>
            </item>
          </channel>
        </rss>"""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("skin", "skincare", "cosmetics"),
        )
        results = provider.search('"skin" formulation', max_results=2)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/item_nosnip")
        self.assertIn("Breakthrough in Skin Barrier Repair Formulations", results[0].snippet)
        self.assertIn("relevance_reason", results[0].raw_data)

    def test_adjacent_industry_evidence_preserved(self) -> None:
        """Industry articles are preserved even if they do not mention 'AI skincare' verbatim."""
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Prestige Beauty Outpaces High-End Bags as China's Luxury Spending Evolves</title>
              <link>https://news.google.com/rss/articles/item_adj</link>
              <description>Beauty category trends, cosmetic retail, and premium skincare shift.</description>
              <source url="https://businessoffashion.com">The Business of Fashion</source>
            </item>
          </channel>
        </rss>"""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("skincare", "cosmetics", "beauty"),
        )
        results = provider.search('"skincare" market gaps', max_results=3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].domain, "businessoffashion.com")
        self.assertIn("beauty", results[0].raw_data["relevance_reason"].lower())

    def test_unrelated_financial_results_rejected(self) -> None:
        """Unrelated financial results are rejected with explainable reasons in diagnostics."""
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Best Investment Apps Of 2026 - Forbes</title>
              <link>https://news.google.com/rss/articles/item_fin</link>
              <description>Guide to top stock trading and crypto investing apps.</description>
              <source url="https://forbes.com">Forbes</source>
            </item>
          </channel>
        </rss>"""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("skincare", "cosmetics"),
        )
        results = provider.search("AI skincare recommendation apps competitors", max_results=3)

        self.assertEqual(len(results), 0)
        diag = provider.diagnostics
        self.assertIsNotNone(diag)
        self.assertEqual(diag.accepted_count, 0)
        self.assertEqual(diag.rejected_count, 1)
        self.assertTrue(diag.all_filtered_out)
        self.assertIn("off-topic negative term", diag.decisions[0].reason)

    def test_max_results_bounds_examination(self) -> None:
        """Candidate selection stops once max_results relevant items are found."""
        items_xml = "".join(
            f"""<item>
              <title>Skincare Innovation Update {i} - Beauty Daily</title>
              <link>https://news.google.com/rss/articles/item_{i}</link>
              <description>Dermatology and skincare routine tech.</description>
              <source url="https://beautydaily.com">Beauty Daily</source>
            </item>"""
            for i in range(1, 10)
        )
        feed_xml = f"<rss version='2.0'><channel>{items_xml}</channel></rss>"
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("skincare",),
        )
        results = provider.search('"skincare" products', max_results=3)

        self.assertEqual(len(results), 3)
        self.assertEqual(provider.diagnostics.accepted_count, 3)
        # Should have stopped after finding 3 candidates rather than processing all 9
        self.assertEqual(provider.diagnostics.examined_count, 3)

    def test_empty_feed_vs_filtered_feed_diagnostics(self) -> None:
        """Diagnostics correctly distinguishes genuinely empty feeds from feeds where all were filtered out."""
        # Case A: Genuinely empty feed
        empty_provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: "<rss version='2.0'><channel></channel></rss>"
        )
        empty_res = empty_provider.search("skincare", max_results=3)
        self.assertEqual(empty_res, ())
        self.assertTrue(empty_provider.diagnostics.feed_was_empty)
        self.assertFalse(empty_provider.diagnostics.all_filtered_out)

        # Case B: Feed with candidates but all rejected
        off_topic_feed = """<rss version='2.0'><channel>
            <item>
              <title>Mortgage Rates Rise in 2026 - Real Estate News</title>
              <link>https://news.google.com/rss/articles/re1</link>
              <description>Mortgage rate analysis.</description>
              <source url="https://realestate.com">Real Estate</source>
            </item>
        </channel></rss>"""
        filtered_provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: off_topic_feed,
            subject_terms=("water quality", "purification"),
        )
        filtered_res = filtered_provider.search('"water quality" technology', max_results=3)
        self.assertEqual(filtered_res, ())
        self.assertFalse(filtered_provider.diagnostics.feed_was_empty)
        self.assertTrue(filtered_provider.diagnostics.all_filtered_out)
        self.assertEqual(filtered_provider.diagnostics.rejected_count, 1)

    def test_generic_non_skincare_research_themes(self) -> None:
        """Provider works seamlessly on non-skincare research themes (e.g. Water Quality)."""
        feed_xml = """<rss version='2.0'><channel>
            <item>
              <title>Best Investment Apps Of 2026 - Forbes</title>
              <link>https://news.google.com/rss/articles/inv1</link>
              <description>Stock trading app comparison.</description>
              <source url="https://forbes.com">Forbes</source>
            </item>
            <item>
              <title>Smart Hydrology and Water Quality Monitoring in Municipal Infrastructure</title>
              <link>https://news.google.com/rss/articles/water1</link>
              <description>Sensors for real-time contaminant and leakage detection.</description>
              <source url="https://watertech.org">WaterTech</source>
            </item>
            <item>
              <title>Advanced Filtration Systems for Wastewater Recovery</title>
              <link>https://news.google.com/rss/articles/water2</link>
              <description>Industrial water treatment and purification.</description>
              <source url="https://enviroreview.com">EnviroReview</source>
            </item>
        </channel></rss>"""
        provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: feed_xml,
            subject_terms=("water", "hydrology", "filtration", "purification"),
        )
        results = provider.search('"WATER QUALITY" technology', max_results=3)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://news.google.com/rss/articles/water1")
        self.assertEqual(results[1].url, "https://news.google.com/rss/articles/water2")
        self.assertEqual(provider.diagnostics.accepted_count, 2)
        self.assertEqual(provider.diagnostics.rejected_count, 1)


if __name__ == "__main__":
    unittest.main()
