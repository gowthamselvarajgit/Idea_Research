"""Unit tests for EPOIngestionService orchestration."""

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from config.settings import DATABASE_PATH
from src.patents.discovery_service import DiscoveryStats, EPODiscoveryError, EPODiscoveryService
from src.patents.ingestion_service import (
    EPOIngestionDiscoveryError,
    EPOIngestionError,
    EPOIngestionRepositoryError,
    EPOIngestionService,
    IngestionResult,
)
from src.patents.models import PatentRecord
from src.patents.repository import PatentRepository


class TestEPOIngestionService(unittest.TestCase):
    """Test suite for EPO patent ingestion pipeline."""

    def setUp(self) -> None:
        """Create mock dependencies for isolation."""
        self.mock_discovery = MagicMock(spec=EPODiscoveryService)
        self.mock_repo = MagicMock(spec=PatentRepository)
        self.service = EPOIngestionService(
            discovery_service=self.mock_discovery,
            repository=self.mock_repo,
        )

        self.sample_patents = [
            PatentRecord(
                patent_number="US11223344B2",
                title="Solid State Electrolyte Formulation",
                abstract="Novel ceramic composite for lithium batteries.",
                filing_date="2021-01-15",
                publication_date="2022-06-30",
                assignee="Solid Energy Inc",
                source_url="https://patents.google.com/patent/US11223344B2/en",
            ),
            PatentRecord(
                patent_number="EP3456789A1",
                title="Sulfonated Separator Matrix",
                abstract="High temperature battery separator.",
                filing_date="2020-03-10",
                publication_date="2021-09-15",
                assignee="Euro Power SAS",
                source_url="https://patents.google.com/patent/EP3456789A1/en",
            ),
        ]

        self.sample_stats = DiscoveryStats(
            query="solid state electrolyte",
            requested_count=25,
            raw_results_parsed=2,
            valid_patents_returned=2,
            duplicates_removed=0,
            malformed_records_skipped=0,
        )

    def test_successful_end_to_end_flow(self) -> None:
        """Verify discover -> parse -> persist flow returns accurate combined telemetry."""
        self.mock_discovery.discover.return_value = self.sample_patents
        self.mock_discovery.last_stats = self.sample_stats
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 2,
            "inserted": 1,
            "existing": 1,
            "linked": 2,
        }

        result = self.service.ingest_run(
            run_id="run-001",
            query="solid state electrolyte",
            max_results=25,
        )

        self.assertIsInstance(result, IngestionResult)
        self.assertEqual(result.query, "solid state electrolyte")
        self.assertEqual(result.run_id, "run-001")
        self.assertEqual(result.discovered, 2)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.existing, 1)
        self.assertEqual(result.linked, 2)
        self.assertEqual(result.discovery_stats, self.sample_stats)

    def test_correct_run_id_passed_to_repository(self) -> None:
        """Verify the exact run_id and discovered patents are passed to repository."""
        self.mock_discovery.discover.return_value = self.sample_patents
        self.mock_discovery.last_stats = self.sample_stats
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 2,
            "inserted": 2,
            "existing": 0,
            "linked": 2,
        }

        self.service.ingest_run(
            run_id="run-target-999",
            query="battery separator",
            max_results=10,
        )

        self.mock_repo.save_patents_for_run.assert_called_once_with(
            run_id="run-target-999",
            patents=self.sample_patents,
        )

    def test_correct_query_and_max_results_passed_to_discovery(self) -> None:
        """Verify query and max_results are forwarded to EPODiscoveryService."""
        self.mock_discovery.discover.return_value = []
        self.mock_discovery.last_stats = None
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 0,
            "inserted": 0,
            "existing": 0,
            "linked": 0,
        }

        self.service.ingest_run(
            run_id="run-123",
            query="cql: ta=silicon and pd>2020",
            max_results=50,
        )

        self.mock_discovery.discover.assert_called_once_with(
            query="cql: ta=silicon and pd>2020",
            max_results=50,
        )

    def test_persistence_statistics_are_returned(self) -> None:
        """Verify all stats properties, dictionary access, and .to_dict() outputs."""
        self.mock_discovery.discover.return_value = self.sample_patents
        self.mock_discovery.last_stats = self.sample_stats
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 2,
            "inserted": 2,
            "existing": 0,
            "linked": 2,
        }

        result = self.service.ingest_run(
            run_id="run-stats",
            query="solid electrolyte",
            max_results=25,
        )

        # Dataclass property access
        self.assertEqual(result.number_discovered, 2)
        self.assertEqual(result.number_inserted, 2)
        self.assertEqual(result.number_existing, 0)
        self.assertEqual(result.number_linked, 2)
        self.assertIsNotNone(result.discovery_statistics)

        # Dictionary access
        self.assertEqual(result["discovered"], 2)
        self.assertEqual(result["number_inserted"], 2)
        self.assertEqual(result["linked"], 2)

        # to_dict conversion
        as_dict = result.to_dict()
        self.assertEqual(as_dict["query"], "solid electrolyte")
        self.assertEqual(as_dict["run_id"], "run-stats")
        self.assertEqual(as_dict["inserted"], 2)
        self.assertEqual(as_dict["discovery_stats"]["valid_patents_returned"], 2)

    def test_discovery_failure_handled_clearly(self) -> None:
        """Verify discovery failures raise EPOIngestionDiscoveryError and abort persistence."""
        self.mock_discovery.discover.side_effect = EPODiscoveryError("EPO gateway rate limit 429")

        with self.assertRaises(EPOIngestionDiscoveryError) as ctx:
            self.service.ingest_run(
                run_id="run-error",
                query="failing query",
            )

        self.assertIn("Patent discovery failed", str(ctx.exception))
        self.mock_repo.save_patents_for_run.assert_not_called()

    def test_repository_failure_handled_clearly(self) -> None:
        """Verify repository failures raise EPOIngestionRepositoryError."""
        self.mock_discovery.discover.return_value = self.sample_patents
        self.mock_discovery.last_stats = self.sample_stats
        self.mock_repo.save_patents_for_run.side_effect = sqlite3.OperationalError("database is locked")

        with self.assertRaises(EPOIngestionRepositoryError) as ctx:
            self.service.ingest_run(
                run_id="run-repo-error",
                query="query",
            )

        self.assertIn("Patent persistence failed", str(ctx.exception))

    def test_zero_result_discovery(self) -> None:
        """Zero discovery results are safely passed to repository and return zeroed metrics."""
        self.mock_discovery.discover.return_value = []
        zero_stats = DiscoveryStats(
            query="unmatched term",
            requested_count=25,
            raw_results_parsed=0,
            valid_patents_returned=0,
            duplicates_removed=0,
            malformed_records_skipped=0,
        )
        self.mock_discovery.last_stats = zero_stats
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 0,
            "inserted": 0,
            "existing": 0,
            "linked": 0,
        }

        result = self.service.ingest_run(
            run_id="run-zero",
            query="unmatched term",
        )

        self.assertEqual(result.discovered, 0)
        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.existing, 0)
        self.assertEqual(result.linked, 0)
        self.mock_repo.save_patents_for_run.assert_called_once_with(
            run_id="run-zero",
            patents=[],
        )

    def test_invalid_run_id_raises_value_error(self) -> None:
        """Empty or whitespace run_id raises ValueError before running discovery."""
        with self.assertRaises(ValueError):
            self.service.ingest_run(run_id="", query="valid query")

        with self.assertRaises(ValueError):
            self.service.ingest_run(run_id="   ", query="valid query")

        self.mock_discovery.discover.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_no_real_network_calls(self, mock_urlopen: MagicMock) -> None:
        """Verify no socket or HTTP network calls occur during ingestion execution."""
        self.mock_discovery.discover.return_value = self.sample_patents
        self.mock_discovery.last_stats = self.sample_stats
        self.mock_repo.save_patents_for_run.return_value = {
            "total": 2,
            "inserted": 2,
            "existing": 0,
            "linked": 2,
        }

        self.service.ingest_run(
            run_id="run-network-guard",
            query="solid state electrolyte",
        )

        mock_urlopen.assert_not_called()

    def test_no_real_production_database_writes(self) -> None:
        """Verify that testing the ingestion service never writes to data/research_engine.db."""
        if not DATABASE_PATH.exists():
            return

        conn = sqlite3.connect(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patents;")
            patents_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM run_patents;")
            runs_count = cursor.fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(patents_count, 0, "Production patents table has unexpected records!")
        self.assertEqual(runs_count, 0, "Production run_patents table has unexpected records!")


if __name__ == "__main__":
    unittest.main()
