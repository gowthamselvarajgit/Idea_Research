"""Unit tests for WebSourceCollector and collect_sources."""

from unittest.mock import MagicMock
import unittest

from src.market_research.source_collection import (
    SourceCollectionFailure,
    SourceCollectionResult,
    WebSourceCollector,
    collect_sources,
)
from src.market_research.source_models import WebResearchSource
from src.market_research.web_source_client import (
    WebSourceClient,
    WebSourceHTTPError,
    WebSourceNetworkError,
)


class TestWebSourceCollection(unittest.TestCase):
    """Test suite for batch URL collection and failure isolation."""

    def _create_mock_source(
        self,
        url: str,
        title: str = "Test Page",
        source_type: str = "other",
    ) -> WebResearchSource:
        """Helper to create a WebResearchSource for testing."""
        return WebResearchSource(
            url=url,
            title=title,
            source_type=source_type,
            publisher_or_domain="example.com",
            retrieved_content="Sample retrieved body content for testing.",
            retrieved_at="2026-10-06T20:00:00Z",
            id=None,
            raw_data={},
        )

    def test_multiple_successful_urls_and_order_preservation(self) -> None:
        """Batch collection preserves original input order across multiple successful URLs."""
        mock_client = MagicMock(spec=WebSourceClient)
        urls = [
            "https://alpha.example.com",
            "https://beta.example.com",
            "https://gamma.example.com",
        ]

        mock_client.fetch_source.side_effect = [
            self._create_mock_source("https://alpha.example.com", title="Alpha"),
            self._create_mock_source("https://beta.example.com", title="Beta"),
            self._create_mock_source("https://gamma.example.com", title="Gamma"),
        ]

        result = collect_sources(urls=urls, client=mock_client)

        self.assertIsInstance(result, SourceCollectionResult)
        self.assertEqual(result.success_count, 3)
        self.assertEqual(result.failure_count, 0)
        self.assertEqual(result.total_count, 3)

        # Order preservation
        self.assertEqual(result.sources[0].url, "https://alpha.example.com")
        self.assertEqual(result.sources[1].url, "https://beta.example.com")
        self.assertEqual(result.sources[2].url, "https://gamma.example.com")

    def test_one_failed_url_does_not_stop_others(self) -> None:
        """Failure of a single URL does not interrupt collection of remaining URLs."""
        mock_client = MagicMock(spec=WebSourceClient)
        urls = [
            "https://success1.example.com",
            "https://failing.example.com",
            "https://success2.example.com",
        ]

        def fetch_side_effect(url: str, source_type: str = "other"):
            if "failing" in url:
                raise WebSourceHTTPError("HTTP request failed with status 404: Not Found")
            return self._create_mock_source(url)

        mock_client.fetch_source.side_effect = fetch_side_effect

        result = collect_sources(urls=urls, client=mock_client)

        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.total_count, 3)

        # Successful items
        self.assertEqual(result.sources[0].url, "https://success1.example.com")
        self.assertEqual(result.sources[1].url, "https://success2.example.com")

        # Failure diagnostics
        failure = result.failures[0]
        self.assertIsInstance(failure, SourceCollectionFailure)
        self.assertEqual(failure.url, "https://failing.example.com")
        self.assertEqual(failure.error_type, "WebSourceHTTPError")
        self.assertIn("404", failure.error_message)

    def test_source_type_forwarding(self) -> None:
        """source_type is forwarded properly to the client."""
        mock_client = MagicMock(spec=WebSourceClient)
        mock_client.fetch_source.return_value = self._create_mock_source(
            "https://competitor.example.com",
            source_type="competitor",
        )

        result = collect_sources(
            urls=["https://competitor.example.com"],
            source_type="competitor",
            client=mock_client,
        )

        mock_client.fetch_source.assert_called_once_with(
            url="https://competitor.example.com",
            source_type="competitor",
        )
        self.assertEqual(result.sources[0].source_type, "competitor")

    def test_empty_or_none_url_list(self) -> None:
        """Empty or None input sequences return empty SourceCollectionResult."""
        r1 = collect_sources([])
        self.assertEqual(r1.success_count, 0)
        self.assertEqual(r1.failure_count, 0)
        self.assertEqual(r1.sources, ())
        self.assertEqual(r1.failures, ())

        r2 = collect_sources(None)  # type: ignore
        self.assertEqual(r2.success_count, 0)
        self.assertEqual(r2.failure_count, 0)

    def test_duplicate_urls_handled_consistently(self) -> None:
        """Redundant duplicate URLs are fetched only once when deduplication is enabled."""
        mock_client = MagicMock(spec=WebSourceClient)
        mock_client.fetch_source.side_effect = [
            self._create_mock_source("https://unique1.com"),
            self._create_mock_source("https://unique2.com"),
        ]

        urls = [
            "https://unique1.com",
            "https://unique2.com",
            "https://unique1.com",  # Duplicate
            "  https://unique1.com  ",  # Duplicate with whitespace
        ]

        result = collect_sources(urls=urls, client=mock_client, deduplicate=True)

        self.assertEqual(result.success_count, 2)
        self.assertEqual(mock_client.fetch_source.call_count, 2)

    def test_invalid_url_entries_captured_as_failures(self) -> None:
        """Empty strings and non-string inputs are captured cleanly as failures."""
        mock_client = MagicMock(spec=WebSourceClient)
        mock_client.fetch_source.return_value = self._create_mock_source("https://valid.com")

        urls = [
            "https://valid.com",
            "",
            "   ",
            12345,  # type: ignore
        ]

        result = collect_sources(urls=urls, client=mock_client)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.failure_count, 3)
        self.assertEqual(result.failures[0].error_type, "ValueError")
        self.assertEqual(result.failures[1].error_type, "ValueError")
        self.assertEqual(result.failures[2].error_type, "TypeError")

    def test_injected_collector_class_behavior(self) -> None:
        """WebSourceCollector works as a reusable class instance with injected client."""
        mock_client = MagicMock(spec=WebSourceClient)
        mock_client.fetch_source.side_effect = WebSourceNetworkError("DNS failed")

        collector = WebSourceCollector(client=mock_client)
        result = collector.collect_sources(["https://unreachable.org"])

        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.failures[0].error_type, "WebSourceNetworkError")

    def test_to_dict_serialization(self) -> None:
        """SourceCollectionResult and failures serialize to dictionary accurately."""
        source = self._create_mock_source("https://test.com")
        failure = SourceCollectionFailure(
            url="https://fail.com",
            error_type="WebSourceHTTPError",
            error_message="500 Internal Error",
        )
        result = SourceCollectionResult(
            sources=(source,),
            failures=(failure,),
        )

        res_dict = result.to_dict()
        self.assertEqual(res_dict["success_count"], 1)
        self.assertEqual(res_dict["failure_count"], 1)
        self.assertEqual(res_dict["total_count"], 2)
        self.assertEqual(len(res_dict["sources"]), 1)
        self.assertEqual(len(res_dict["failures"]), 1)
        self.assertEqual(res_dict["failures"][0]["url"], "https://fail.com")


if __name__ == "__main__":
    unittest.main()
