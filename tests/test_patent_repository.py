"""Tests for PatentRepository persistence, deduplication, and run linking."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.common.database import get_db, init_db
from src.patents.models import PatentRecord
from src.patents.repository import PatentRepository


class TestPatentRepository(unittest.TestCase):
    """Unit tests for SQLite PatentRepository."""

    def setUp(self) -> None:
        """Create a fresh temporary database for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_patents.db"
        init_db(self.db_path)
        self.repo = PatentRepository(self.db_path)

    def tearDown(self) -> None:
        """Clean up the temporary directory."""
        self.temp_dir.cleanup()

    def _create_research_run(
        self,
        run_id: str = "run-001",
        run_name: str = "Solid State Batteries",
        query: str = "solid state electrolyte",
    ) -> str:
        """Helper to create a prerequisite research_runs entry."""
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO research_runs (id, run_name, query, status)
                VALUES (?, ?, ?, 'initialized');
                """,
                (run_id, run_name, query),
            )
        return run_id

    def _sample_patent(
        self,
        patent_number: str = "US11223344B2",
        title: str = "Solid State Lithium Battery",
        abstract: str = "An electrolyte formulation for solid state cells.",
        assignee: str = "QuantumScape Battery Corp",
    ) -> PatentRecord:
        """Helper to generate a test PatentRecord."""
        return PatentRecord(
            patent_number=patent_number,
            title=title,
            abstract=abstract,
            filing_date="2020-05-15",
            publication_date="2021-11-20",
            assignee=assignee,
            source_url=f"https://patents.google.com/patent/{patent_number}/en",
            raw_data={"doc_id": patent_number, "origin": "EPO_OPS"},
        )

    def test_insert_new_patent(self) -> None:
        """Inserting a new patent persists all attributes and returns a UUID."""
        patent = self._sample_patent()
        patent_id = self.repo.upsert_patent(patent)

        self.assertIsInstance(patent_id, str)
        self.assertTrue(len(patent_id) > 0)

        record = self.repo.get_patent_by_id(patent_id)
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], patent_id)
        self.assertEqual(record["patent_number"], "US11223344B2")
        self.assertEqual(record["title"], "Solid State Lithium Battery")
        self.assertEqual(record["abstract"], "An electrolyte formulation for solid state cells.")
        self.assertEqual(record["filing_date"], "2020-05-15")
        self.assertEqual(record["publication_date"], "2021-11-20")
        self.assertEqual(record["assignee"], "QuantumScape Battery Corp")
        self.assertEqual(record["source_url"], "https://patents.google.com/patent/US11223344B2/en")

        parsed_raw = json.loads(record["raw_data"])
        self.assertEqual(parsed_raw["doc_id"], "US11223344B2")

    def test_get_existing_patent(self) -> None:
        """Retrieving by patent_number and by ID returns the correct record."""
        patent = self._sample_patent(patent_number="EP3456789A1", title="European Patent Title")
        patent_id = self.repo.upsert_patent(patent)

        by_number = self.repo.get_patent_by_number("EP3456789A1")
        self.assertIsNotNone(by_number)
        self.assertEqual(by_number["id"], patent_id)
        self.assertEqual(by_number["title"], "European Patent Title")

        by_id = self.repo.get_patent_by_id(patent_id)
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id["patent_number"], "EP3456789A1")

        non_existent = self.repo.get_patent_by_number("WO99999999A1")
        self.assertIsNone(non_existent)

        non_existent_id = self.repo.get_patent_by_id("non-existent-uuid")
        self.assertIsNone(non_existent_id)

    def test_repeated_upsert_does_not_create_duplicates(self) -> None:
        """Repeated upsert for the same patent_number returns the same ID and creates no duplicate rows."""
        patent = self._sample_patent(patent_number="US10000001B2")

        id_1 = self.repo.upsert_patent(patent)
        id_2 = self.repo.upsert_patent(patent)
        id_3 = self.repo.upsert_patent(patent)

        self.assertEqual(id_1, id_2)
        self.assertEqual(id_2, id_3)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patents WHERE patent_number = 'US10000001B2';")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)

    def test_metadata_update_works(self) -> None:
        """Upserting an existing patent with better metadata updates the row and preserves good data."""
        initial_patent = PatentRecord(
            patent_number="US10500000B2",
            title="Untitled",
            abstract=None,
            filing_date="2020-01-01",
            publication_date="2021-01-01",
            assignee=None,
            source_url="https://patents.google.com/patent/US10500000B2/en",
        )
        patent_id = self.repo.upsert_patent(initial_patent)

        updated_patent = PatentRecord(
            patent_number="US10500000B2",
            title="Silicon Anode Fast-Charging Architecture",
            abstract="Novel conductive binder matrix.",
            filing_date="2020-01-01",
            publication_date="2021-01-01",
            assignee="Sila Nanotechnologies Inc",
            source_url="https://patents.google.com/patent/US10500000B2/en",
            raw_data={"source": "OPS", "enriched": True},
        )
        returned_id = self.repo.upsert_patent(updated_patent)
        self.assertEqual(returned_id, patent_id)

        record = self.repo.get_patent_by_id(patent_id)
        self.assertEqual(record["title"], "Silicon Anode Fast-Charging Architecture")
        self.assertEqual(record["abstract"], "Novel conductive binder matrix.")
        self.assertEqual(record["assignee"], "Sila Nanotechnologies Inc")
        self.assertIsNotNone(record["raw_data"])

        # Another update with "Untitled" and None fields should not overwrite the good data
        minimal_patent = PatentRecord(
            patent_number="US10500000B2",
            title="Untitled",
            abstract=None,
            filing_date=None,
            publication_date=None,
            assignee=None,
            source_url="https://patents.google.com/patent/US10500000B2/en",
        )
        self.repo.upsert_patent(minimal_patent)
        preserved_record = self.repo.get_patent_by_id(patent_id)
        self.assertEqual(preserved_record["title"], "Silicon Anode Fast-Charging Architecture")
        self.assertEqual(preserved_record["abstract"], "Novel conductive binder matrix.")
        self.assertEqual(preserved_record["assignee"], "Sila Nanotechnologies Inc")

    def test_link_patent_to_run(self) -> None:
        """Linking a patent to a run inserts a row in the run_patents junction table."""
        run_id = self._create_research_run(run_id="run-101")
        patent = self._sample_patent(patent_number="US9988776B2")
        patent_id = self.repo.upsert_patent(patent)

        linked = self.repo.link_patent_to_run(run_id, patent_id)
        self.assertTrue(linked)

        run_patents = self.repo.get_patents_for_run(run_id)
        self.assertEqual(len(run_patents), 1)
        self.assertEqual(run_patents[0]["id"], patent_id)
        self.assertEqual(run_patents[0]["patent_number"], "US9988776B2")

    def test_repeated_linking_is_idempotent(self) -> None:
        """Repeatedly linking the same patent to the same run does not produce duplicates."""
        run_id = self._create_research_run(run_id="run-102")
        patent = self._sample_patent(patent_number="US7766554B2")
        patent_id = self.repo.upsert_patent(patent)

        first_link = self.repo.link_patent_to_run(run_id, patent_id)
        second_link = self.repo.link_patent_to_run(run_id, patent_id)
        third_link = self.repo.link_patent_to_run(run_id, patent_id)

        self.assertTrue(first_link)
        self.assertFalse(second_link)
        self.assertFalse(third_link)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM run_patents WHERE run_id = ? AND patent_id = ?;",
                (run_id, patent_id),
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)

    def test_saving_multiple_patents_for_run(self) -> None:
        """save_patents_for_run batch upserts and links patents, returning accurate counts."""
        run_id = self._create_research_run(run_id="run-103")
        patents = [
            self._sample_patent(patent_number=f"US1000000{i}B2", title=f"Battery Concept {i}")
            for i in range(1, 4)
        ]

        stats = self.repo.save_patents_for_run(run_id, patents)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["inserted"], 3)
        self.assertEqual(stats["existing"], 0)
        self.assertEqual(stats["linked"], 3)

        run_patents = self.repo.get_patents_for_run(run_id)
        self.assertEqual(len(run_patents), 3)

        # Re-saving same 3 patents + 1 new patent
        patents_expanded = patents + [
            self._sample_patent(patent_number="US10000004B2", title="Battery Concept 4")
        ]
        stats_second = self.repo.save_patents_for_run(run_id, patents_expanded)
        self.assertEqual(stats_second["total"], 4)
        self.assertEqual(stats_second["inserted"], 1)
        self.assertEqual(stats_second["existing"], 3)
        self.assertEqual(stats_second["linked"], 1)

        run_patents_updated = self.repo.get_patents_for_run(run_id)
        self.assertEqual(len(run_patents_updated), 4)

    def test_same_patent_in_multiple_runs(self) -> None:
        """The same patent appearing in multiple runs creates only one patent row but links to both runs."""
        run_a = self._create_research_run(run_id="run-A", run_name="Run A")
        run_b = self._create_research_run(run_id="run-B", run_name="Run B")

        shared_patent = self._sample_patent(
            patent_number="US12345678B2",
            title="Shared Energy Storage Patent",
        )

        stats_a = self.repo.save_patents_for_run(run_a, [shared_patent])
        self.assertEqual(stats_a["inserted"], 1)
        self.assertEqual(stats_a["linked"], 1)

        stats_b = self.repo.save_patents_for_run(run_b, [shared_patent])
        self.assertEqual(stats_b["inserted"], 0)
        self.assertEqual(stats_b["existing"], 1)
        self.assertEqual(stats_b["linked"], 1)

        # Only one row in patents table
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patents WHERE patent_number = 'US12345678B2';")
            self.assertEqual(cursor.fetchone()[0], 1)

            cursor.execute("SELECT COUNT(*) FROM run_patents;")
            self.assertEqual(cursor.fetchone()[0], 2)

        # Both runs can access the patent
        patents_in_a = self.repo.get_patents_for_run(run_a)
        patents_in_b = self.repo.get_patents_for_run(run_b)
        self.assertEqual(len(patents_in_a), 1)
        self.assertEqual(len(patents_in_b), 1)
        self.assertEqual(patents_in_a[0]["id"], patents_in_b[0]["id"])

    def test_transaction_rollback_on_foreign_key_error(self) -> None:
        """When an operation fails inside save_patents_for_run, the transaction rolls back."""
        # Use a non-existent run_id so foreign key enforcement on run_patents triggers IntegrityError
        invalid_run_id = "non-existent-run-id"
        patent = self._sample_patent(patent_number="US88889999B2")

        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save_patents_for_run(invalid_run_id, [patent])

        # Verify that the patent was NOT persisted due to transaction rollback
        record = self.repo.get_patent_by_number("US88889999B2")
        self.assertIsNone(record)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patents;")
            self.assertEqual(cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
