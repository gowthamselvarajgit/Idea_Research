"""Tests for ResearchRunService lifecycle management and SQLite persistence."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db, init_db
from src.common.research_runs import (
    InvalidLifecycleTransitionError,
    ResearchRunService,
    RunNotFoundError,
)


class TestResearchRunService(unittest.TestCase):
    """Test suite for research run creation, state transitions, and retrieval."""

    def setUp(self) -> None:
        """Create an isolated temporary SQLite database for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_research_runs.db"
        init_db(self.db_path)
        self.service = ResearchRunService(self.db_path)

    def tearDown(self) -> None:
        """Clean up temporary resources."""
        self.temp_dir.cleanup()

    def test_create_run_and_generated_unique_id(self) -> None:
        """Creating runs generates unique IDs, defaults to initialized status, and validates names."""
        run_id_1 = self.service.create_run(run_name="First Run")
        run_id_2 = self.service.create_run(run_name="Second Run")

        self.assertIsInstance(run_id_1, str)
        self.assertIsInstance(run_id_2, str)
        self.assertNotEqual(run_id_1, run_id_2)

        # Confirm UUID format
        parsed_uuid = uuid.UUID(run_id_1)
        self.assertEqual(str(parsed_uuid), run_id_1)

        # Check initialized state in database
        run_1 = self.service.get_run(run_id_1)
        self.assertIsNotNone(run_1)
        self.assertEqual(run_1["run_name"], "First Run")
        self.assertEqual(run_1["status"], "initialized")
        self.assertIsNotNone(run_1["created_at"])
        self.assertIsNone(run_1["completed_at"])

        # Blank run names should fail
        with self.assertRaises(ValueError):
            self.service.create_run(run_name="")
        with self.assertRaises(ValueError):
            self.service.create_run(run_name="   ")

    def test_query_persistence(self) -> None:
        """Query strings are persisted when provided and remain None when omitted."""
        run_id_query = self.service.create_run(
            run_name="Query Run",
            query="cql: ta=battery and pd>2022",
        )
        record_query = self.service.get_run(run_id_query)
        self.assertEqual(record_query["query"], "cql: ta=battery and pd>2022")

        run_id_no_query = self.service.create_run(run_name="No Query Run")
        record_no_query = self.service.get_run(run_id_no_query)
        self.assertIsNone(record_no_query["query"])

    def test_metadata_json_round_trip(self) -> None:
        """Metadata dictionaries are serialized to JSON in SQLite and deserialized cleanly."""
        metadata_payload = {
            "tags": ["cleantech", "energy"],
            "max_results": 50,
            "config": {"source": "EPO_OPS", "strict": True},
        }

        run_id = self.service.create_run(
            run_name="Metadata Test Run",
            metadata=metadata_payload,
        )

        record = self.service.get_run(run_id)
        self.assertEqual(record["metadata"], metadata_payload)
        self.assertEqual(record["metadata"]["tags"], ["cleantech", "energy"])
        self.assertEqual(record["metadata"]["config"]["strict"], True)

        # When metadata is None
        empty_meta_run_id = self.service.create_run(run_name="Empty Meta Run")
        empty_record = self.service.get_run(empty_meta_run_id)
        self.assertIsNone(empty_record["metadata"])

    def test_start_transition(self) -> None:
        """A run can transition from initialized to running."""
        run_id = self.service.create_run(run_name="Startable Run")
        self.service.start_run(run_id)

        record = self.service.get_run(run_id)
        self.assertEqual(record["status"], "running")
        self.assertIsNone(record["completed_at"])

    def test_complete_transition_and_timestamp(self) -> None:
        """A running run transitions to completed and records a completion timestamp."""
        run_id = self.service.create_run(run_name="Completable Run")
        self.service.start_run(run_id)
        self.service.complete_run(run_id)

        record = self.service.get_run(run_id)
        self.assertEqual(record["status"], "completed")
        self.assertIsNotNone(record["completed_at"])

    def test_fail_transition_and_timestamp(self) -> None:
        """A running run transitions to failed and records completion timestamp."""
        run_id = self.service.create_run(run_name="Failable Run")
        self.service.start_run(run_id)
        self.service.fail_run(run_id)

        record = self.service.get_run(run_id)
        self.assertEqual(record["status"], "failed")
        self.assertIsNotNone(record["completed_at"])

    def test_failure_metadata(self) -> None:
        """Failing a run records failure error information while preserving existing metadata."""
        initial_metadata = {"source": "EPO", "target_count": 25}
        run_id = self.service.create_run(
            run_name="Failure Meta Run",
            metadata=initial_metadata,
        )
        self.service.start_run(run_id)
        self.service.fail_run(run_id, error_message="EPO OPS rate limit exceeded: HTTP 429")

        record = self.service.get_run(run_id)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["metadata"]["source"], "EPO")
        self.assertEqual(record["metadata"]["target_count"], 25)
        self.assertEqual(record["metadata"]["error"], "EPO OPS rate limit exceeded: HTTP 429")
        self.assertEqual(record["metadata"]["error_message"], "EPO OPS rate limit exceeded: HTTP 429")

    def test_unknown_run_handling(self) -> None:
        """Operations on non-existent run IDs raise RunNotFoundError or return None."""
        missing_id = "non-existent-uuid-1234"

        with self.assertRaises(RunNotFoundError):
            self.service.start_run(missing_id)

        with self.assertRaises(RunNotFoundError):
            self.service.complete_run(missing_id)

        with self.assertRaises(RunNotFoundError):
            self.service.fail_run(missing_id, error_message="Some error")

        self.assertIsNone(self.service.get_run(missing_id))

    def test_invalid_lifecycle_transitions(self) -> None:
        """Invalid state transitions raise InvalidLifecycleTransitionError and prevent restarting."""
        # 1. initialized -> completed (skipping running is forbidden)
        run_1 = self.service.create_run(run_name="Run 1")
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.complete_run(run_1)

        # 2. initialized -> failed (must be started before failing)
        run_2 = self.service.create_run(run_name="Run 2")
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.fail_run(run_2, error_message="Direct fail")

        # 3. running -> running (already running)
        run_3 = self.service.create_run(run_name="Run 3")
        self.service.start_run(run_3)
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.start_run(run_3)

        # 4. completed -> running (completed runs must not restart)
        self.service.complete_run(run_3)
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.start_run(run_3)

        # 5. completed -> completed
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.complete_run(run_3)

        # 6. completed -> failed
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.fail_run(run_3, error_message="Fail completed run")

        # 7. failed -> running (failed runs must not restart)
        run_4 = self.service.create_run(run_name="Run 4")
        self.service.start_run(run_4)
        self.service.fail_run(run_4, error_message="Initial failure")
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.start_run(run_4)

        # 8. failed -> completed
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.complete_run(run_4)

        # 9. failed -> failed
        with self.assertRaises(InvalidLifecycleTransitionError):
            self.service.fail_run(run_4, error_message="Repeat failure")

    def test_production_database_remains_untouched(self) -> None:
        """Ensure testing uses isolated databases and leaves data/research_engine.db empty."""
        if not DATABASE_PATH.exists():
            return

        conn = sqlite3.connect(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM research_runs;")
            run_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM patents;")
            patents_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM run_patents;")
            junction_count = cursor.fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(run_count, 0, "Production research_runs has rows!")
        self.assertEqual(patents_count, 0, "Production patents has rows!")
        self.assertEqual(junction_count, 0, "Production run_patents has rows!")


if __name__ == "__main__":
    unittest.main()
