"""Unit tests for EPODiscoveryService using mocked EPOClient."""

from unittest import mock
import unittest

from src.patents.discovery_service import (
    DiscoveryStats,
    EPODiscoveryError,
    EPODiscoveryService,
)
from src.patents.epo_client import EPOClient, EPOClientNetworkError
from src.patents.models import PatentRecord

MOCK_SINGLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org">
    <ops:biblio-search total-result-count="1">
        <ops:search-result>
            <exchange-documents>
                <exchange-document country="EP" doc-number="3456789" kind="A1">
                    <bibliographic-data>
                        <invention-title lang="en">Solid State Battery Electrolyte</invention-title>
                    </bibliographic-data>
                    <abstract lang="en">
                        <p>High performance solid electrolyte.</p>
                    </abstract>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""

MOCK_DUPLICATE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org">
    <ops:biblio-search total-result-count="3">
        <ops:search-result>
            <exchange-documents>
                <!-- First occurrence of EP3456789A1 -->
                <exchange-document country="EP" doc-number="3456789" kind="A1">
                    <bibliographic-data>
                        <invention-title lang="en">First Title</invention-title>
                    </bibliographic-data>
                </exchange-document>
                <!-- Duplicate occurrence of EP3456789A1 -->
                <exchange-document country="EP" doc-number="3456789" kind="A1">
                    <bibliographic-data>
                        <invention-title lang="en">Duplicate Title</invention-title>
                    </bibliographic-data>
                </exchange-document>
                <!-- Distinct publication (EP3456789B1: grant stage) -->
                <exchange-document country="EP" doc-number="3456789" kind="B1">
                    <bibliographic-data>
                        <invention-title lang="en">Granted Patent Title</invention-title>
                    </bibliographic-data>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""

MOCK_WITH_MALFORMED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org">
    <ops:biblio-search total-result-count="2">
        <ops:search-result>
            <exchange-documents>
                <!-- Malformed: invalid country -->
                <exchange-document country="INVALID" doc-number="999" kind="A1">
                    <bibliographic-data>
                        <invention-title lang="en">Bad</invention-title>
                    </bibliographic-data>
                </exchange-document>
                <!-- Valid -->
                <exchange-document country="US" doc-number="11456789" kind="B2">
                    <bibliographic-data>
                        <invention-title lang="en">Valid US</invention-title>
                    </bibliographic-data>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""


class TestEPODiscoveryService(unittest.TestCase):
    """Test suite for EPODiscoveryService coordination, deduplication, and stats."""

    def setUp(self):
        self.mock_client = mock.MagicMock(spec=EPOClient)
        self.service = EPODiscoveryService(client=self.mock_client)

    def test_search_parse_return_patent_records(self):
        """Verify the service coordinates search, parsing, and returns PatentRecord instances."""
        self.mock_client.search.return_value = MOCK_SINGLE_XML

        records = self.service.discover(query='ta="battery"', max_results=10)

        self.assertEqual(len(records), 1)
        self.assertIsInstance(records[0], PatentRecord)
        self.assertEqual(records[0].patent_number, "EP3456789A1")
        self.assertEqual(records[0].title, "Solid State Battery Electrolyte")

    def test_query_and_requested_count_passed_correctly(self):
        """Verify query and max_results are forwarded to client.search()."""
        self.mock_client.search.return_value = MOCK_SINGLE_XML

        self.service.discover(query='ta="lithium anode"', max_results=25, start_index=1)

        self.mock_client.search.assert_called_once_with(
            query='ta="lithium anode"',
            max_results=25,
            start_index=1,
        )

    def test_duplicate_publication_records_removed(self):
        """Verify identical publication numbers are deduplicated, preserving first occurrence."""
        self.mock_client.search.return_value = MOCK_DUPLICATE_XML

        records = self.service.discover(query='ta="test"', max_results=10)

        # Total 3 documents in XML: 2 are EP3456789A1, 1 is EP3456789B1
        # Result should contain exactly 2 distinct records
        self.assertEqual(len(records), 2)
        patent_numbers = [r.patent_number for r in records]
        self.assertEqual(patent_numbers, ["EP3456789A1", "EP3456789B1"])

        # Preserved first occurrence title
        self.assertEqual(records[0].title, "First Title")

        # Stats verify 1 duplicate removed
        self.assertIsNotNone(self.service.last_stats)
        self.assertEqual(self.service.last_stats.duplicates_removed, 1)
        self.assertEqual(self.service.last_stats.valid_patents_returned, 2)

    def test_different_publication_numbers_from_same_family_retained(self):
        """Verify application (A1) and grant (B1) are both retained as distinct records."""
        self.mock_client.search.return_value = MOCK_DUPLICATE_XML

        records = self.service.discover(query='ta="test"')
        numbers = {r.patent_number for r in records}

        self.assertIn("EP3456789A1", numbers)
        self.assertIn("EP3456789B1", numbers)

    def test_empty_search_response_returns_empty_list(self):
        """Verify empty client response yields empty record list and clean stats."""
        self.mock_client.search.return_value = ""

        records = self.service.discover(query='ta="unknown"')

        self.assertEqual(records, [])
        self.assertIsNotNone(self.service.last_stats)
        self.assertEqual(self.service.last_stats.valid_patents_returned, 0)
        self.assertEqual(self.service.last_stats.raw_results_parsed, 0)

    def test_blank_query_returns_empty_list_without_calling_client(self):
        """Verify blank or empty query returns immediately without calling search()."""
        self.assertEqual(self.service.discover(""), [])
        self.assertEqual(self.service.discover("   "), [])
        self.mock_client.search.assert_not_called()

    def test_parser_failure_handled_clearly(self):
        """Verify broken XML raises EPODiscoveryError with clear context."""
        self.mock_client.search.return_value = "<broken><unclosed>"

        with self.assertRaises(EPODiscoveryError) as ctx:
            self.service.discover(query='ta="broken"')

        self.assertIn("parsing failed", str(ctx.exception).lower())

    def test_client_error_wrapped_in_discovery_error(self):
        """Verify underlying EPOClientError is wrapped in EPODiscoveryError."""
        self.mock_client.search.side_effect = EPOClientNetworkError("Connection timed out")

        with self.assertRaises(EPODiscoveryError) as ctx:
            self.service.discover(query='ta="timeout"')

        self.assertIn("EPO search request failed", str(ctx.exception))

    def test_statistics_accuracy_including_malformed_records(self):
        """Verify discovery telemetry accurately records counts and skipped records."""
        self.mock_client.search.return_value = MOCK_WITH_MALFORMED_XML

        records = self.service.discover(query='ta="battery"', max_results=15)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].patent_number, "US11456789B2")

        stats = self.service.last_stats
        self.assertIsInstance(stats, DiscoveryStats)
        self.assertEqual(stats.query, 'ta="battery"')
        self.assertEqual(stats.requested_count, 15)
        self.assertEqual(stats.raw_results_parsed, 1)
        self.assertEqual(stats.valid_patents_returned, 1)
        self.assertEqual(stats.duplicates_removed, 0)
        self.assertEqual(stats.malformed_records_skipped, 1)

        stats_dict = stats.to_dict()
        self.assertIsInstance(stats_dict, dict)
        self.assertEqual(stats_dict["malformed_records_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
