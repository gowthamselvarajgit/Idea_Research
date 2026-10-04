"""Unit tests for ResearchService research-run orchestration."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from src.common.database import get_db, init_db
from src.common.research_runs import ResearchRunService
from src.patents.discovery_strategy import (
    InPassDiscoveryResult,
    InPassDiscoveryStrategy,
)
from src.patents.inpass_client import InPassCaptchaTimeoutError, InPassClient
from src.patents.inpass_ingestion_service import (
    InPassIngestionResult,
    InPassIngestionSearchError,
)
from src.research.research_service import (
    PatentResearchExecutionError,
    PatentResearchResult,
    ResearchService,
)


class TestResearchService(unittest.TestCase):
    """Test suite for ResearchService patent research orchestration."""

    def setUp(self) -> None:
        """Create isolated temporary database and mocked collaborator services."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_research_service.db"
        init_db(self.db_path)

        self.run_service = ResearchRunService(self.db_path)
        self.mock_discovery = MagicMock(spec=InPassDiscoveryStrategy)
        self.mock_client = MagicMock(spec=InPassClient)

        self.service = ResearchService(
            db_path=self.db_path,
            run_service=self.run_service,
            discovery_strategy=self.mock_discovery,
        )

    def tearDown(self) -> None:
        """Clean up temporary resources."""
        self.temp_dir.cleanup()

    def test_successful_research_run(self) -> None:
        """A successful research run transitions from initialized -> running -> completed."""
        # 1. Setup mock responses
        self.mock_discovery.generate_targeted_queries.return_value = [
            "WATER MONITORING",
            "WATER QUALITY",
        ]
        mock_discovery_result = InPassDiscoveryResult(
            run_id="placeholder",
            theme="WATER",
            generated_queries=("WATER MONITORING", "WATER QUALITY"),
            executed_queries=("WATER MONITORING", "WATER QUALITY"),
            total_discovered=10,
            total_ingested=6,
            total_inserted=4,
            total_existing=2,
            total_linked=6,
            ingestion_results=(),
        )
        self.mock_discovery.discover_for_run.return_value = mock_discovery_result

        captcha_cb = MagicMock()

        # 2. Execute
        result = self.service.run_patent_research(
            theme="WATER",
            max_queries=2,
            max_results_per_query=3,
            on_captcha_required=captcha_cb,
            client=self.mock_client,
            run_name="Custom Water Run",
        )

        # 3. Verify returned result
        self.assertIsInstance(result, PatentResearchResult)
        self.assertTrue(result.is_success)
        self.assertEqual(result.final_run_status, "completed")
        self.assertEqual(result.theme, "WATER")
        self.assertIsNone(result.error)
        self.assertEqual(result.discovered_count, 10)
        self.assertEqual(result.ingested_count, 6)
        self.assertEqual(result.inserted_count, 4)
        self.assertEqual(result.existing_count, 2)
        self.assertEqual(result.linked_count, 6)
        self.assertEqual(list(result.generated_queries), ["WATER MONITORING", "WATER QUALITY"])
        self.assertEqual(list(result.executed_queries), ["WATER MONITORING", "WATER QUALITY"])

        # 4. Verify discovery strategy received correct arguments
        self.mock_discovery.discover_for_run.assert_called_once_with(
            run_id=result.run_id,
            theme="WATER",
            max_queries=2,
            max_results_per_query=3,
            on_captcha_required=captcha_cb,
            client=self.mock_client,
            captcha_solver=None,
        )

        # 5. Verify database lifecycle record
        db_run = self.run_service.get_run(result.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["run_name"], "Custom Water Run")
        self.assertEqual(db_run["query"], "WATER")
        self.assertEqual(db_run["status"], "completed")
        self.assertIsNotNone(db_run["created_at"])
        self.assertIsNotNone(db_run["completed_at"])
        self.assertEqual(db_run["metadata"]["strategy"], "InPassDiscoveryStrategy")

    def test_discovery_failure_marks_run_failed(self) -> None:
        """When discovery raises a search error, run must transition to failed and capture error."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]
        self.mock_discovery.discover_for_run.side_effect = InPassIngestionSearchError(
            "InPASS search failed: connection reset"
        )

        result = self.service.run_patent_research(
            theme="WATER",
            max_queries=1,
            max_results_per_query=2,
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.final_run_status, "failed")
        self.assertIn("connection reset", result.error or "")

        # Verify DB state
        db_run = self.run_service.get_run(result.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["status"], "failed")
        self.assertIsNotNone(db_run["completed_at"])
        self.assertIn("connection reset", db_run["metadata"]["error"])

    def test_captcha_timeout_marks_run_failed(self) -> None:
        """When CAPTCHA entry times out, run must transition to failed."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]
        self.mock_discovery.discover_for_run.side_effect = InPassCaptchaTimeoutError(
            "Human CAPTCHA was not entered within 120 seconds."
        )

        result = self.service.run_patent_research(theme="WATER")

        self.assertFalse(result.is_success)
        self.assertEqual(result.final_run_status, "failed")
        self.assertIn("Human CAPTCHA was not entered", result.error or "")

        db_run = self.run_service.get_run(result.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["status"], "failed")
        self.assertIn("Human CAPTCHA", db_run["metadata"]["error"])

    def test_unexpected_exception_marks_run_failed(self) -> None:
        """Unexpected runtime exception marks run as failed."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]
        self.mock_discovery.discover_for_run.side_effect = RuntimeError(
            "Unexpected hardware failure"
        )

        result = self.service.run_patent_research(theme="WATER")

        self.assertFalse(result.is_success)
        self.assertEqual(result.final_run_status, "failed")
        self.assertIn("Unexpected hardware failure", result.error or "")

        db_run = self.run_service.get_run(result.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["status"], "failed")

    def test_raise_on_error_raises_exception_after_marking_failed(self) -> None:
        """When raise_on_error is True, PatentResearchExecutionError is raised with run marked failed."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]
        self.mock_discovery.discover_for_run.side_effect = InPassIngestionSearchError(
            "Portal down for maintenance"
        )

        with self.assertRaises(PatentResearchExecutionError) as ctx:
            self.service.run_patent_research(theme="WATER", raise_on_error=True)

        self.assertIn("Portal down for maintenance", str(ctx.exception))
        self.assertIsNotNone(ctx.exception.result)
        self.assertEqual(ctx.exception.result.final_run_status, "failed")

        # Verify DB run was marked failed
        db_run = self.run_service.get_run(ctx.exception.result.run_id)
        self.assertIsNotNone(db_run)
        self.assertEqual(db_run["status"], "failed")

    def test_invalid_input_validation(self) -> None:
        """Invalid inputs must raise ValueError before any run is created in the database."""
        # Empty theme
        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme="")

        # Whitespace theme
        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme="   \t\n  ")

        # Non-string theme
        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme=None)  # type: ignore[arg-type]

        # max_queries < 1
        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme="WATER", max_queries=0)

        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme="WATER", max_queries=-2)

        # max_results_per_query < 1
        with self.assertRaises(ValueError):
            self.service.run_patent_research(theme="WATER", max_results_per_query=0)

        # Verify no research runs were created in database
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM research_runs;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_telemetry_aggregation_and_accessors(self) -> None:
        """Verify alias properties, to_dict(), and indexing support on PatentResearchResult."""
        result = PatentResearchResult(
            run_id="run-telemetry-1",
            theme="WATER",
            generated_queries=("WATER MONITORING", "WATER QUALITY"),
            executed_queries=("WATER MONITORING",),
            discovered_count=15,
            ingested_count=8,
            inserted_count=5,
            existing_count=3,
            linked_count=8,
            final_run_status="completed",
            error=None,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.total_discovered, 15)
        self.assertEqual(result.total_ingested, 8)
        self.assertEqual(result.total_inserted, 5)
        self.assertEqual(result.total_existing, 3)
        self.assertEqual(result.total_linked, 8)

        data = result.to_dict()
        self.assertEqual(data["run_id"], "run-telemetry-1")
        self.assertEqual(data["final_run_status"], "completed")
        self.assertEqual(result["discovered_count"], 15)
        self.assertEqual(result["inserted_count"], 5)

    def test_partial_persistence_recorded_on_failure(self) -> None:
        """If failure occurs after some junction links were created, partial_linked is reflected."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]

        def mock_discover(run_id, **kwargs):
            # Simulate a patent linked in run_patents table before failing
            with get_db(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO patents (id, patent_number, title) VALUES ('pat-1', 'IN12345A', 'Test Patent');"
                )
                cursor.execute(
                    "INSERT INTO run_patents (run_id, patent_id) VALUES (?, 'pat-1');",
                    (run_id,),
                )
            raise InPassIngestionSearchError("Failure on query 2")

        self.mock_discovery.discover_for_run.side_effect = mock_discover

        result = self.service.run_patent_research(theme="WATER")

        self.assertEqual(result.final_run_status, "failed")
        self.assertEqual(result.linked_count, 1)

    def test_run_patent_research_forwards_captcha_solver(self) -> None:
        """ResearchService should forward captcha_solver callback to discovery strategy."""
        self.mock_discovery.generate_targeted_queries.return_value = ["WATER MONITORING"]
        solver_mock = MagicMock(return_value="SOLVE99")
        self.mock_discovery.discover_for_run.return_value = InPassDiscoveryResult(
            run_id="run-solver-1",
            theme="WATER",
            generated_queries=("WATER MONITORING",),
            executed_queries=("WATER MONITORING",),
            total_discovered=1,
            total_ingested=1,
            total_inserted=1,
            total_existing=0,
            total_linked=1,
            ingestion_results=(),
        )

        result = self.service.run_patent_research(
            theme="WATER",
            max_queries=1,
            captcha_solver=solver_mock,
        )

        self.assertEqual(result.final_run_status, "completed")
        call_kwargs = self.mock_discovery.discover_for_run.call_args.kwargs
        self.assertEqual(call_kwargs["captcha_solver"], solver_mock)


if __name__ == "__main__":
    unittest.main()

