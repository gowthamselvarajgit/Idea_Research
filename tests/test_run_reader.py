"""Tests for ResearchRunPatentReader read-only patent retrieval service."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db, init_db
from src.patents.models import PatentRecord
from src.patents.repository import PatentRepository
from src.patents.run_reader import ResearchRunPatentReader


class TestResearchRunPatentReader(unittest.TestCase):
    """Test suite for retrieving and reconstructing PatentRecord objects for runs."""

    def setUp(self) -> None:
        """Create isolated temporary database and repository/reader instances."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_run_reader.db"
        init_db(self.db_path)
        self.repo = PatentRepository(self.db_path)
        self.reader = ResearchRunPatentReader(self.db_path)

    def tearDown(self) -> None:
        """Clean up temporary resources."""
        self.temp_dir.cleanup()

    def _create_run(self, run_id: str, name: str = "Test Run") -> str:
        """Helper to create a run record."""
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES (?, ?);",
                (run_id, name),
            )
        return run_id

    def _sample_patent(
        self,
        patent_number: str = "US11223344B2",
        title: str = "Solid Electrolyte",
        pub_date: str = "2022-01-01",
        raw_data: dict | None = None,
    ) -> PatentRecord:
        """Helper to generate a test PatentRecord."""
        return PatentRecord(
            patent_number=patent_number,
            title=title,
            abstract="Electrolyte composition.",
            filing_date="2020-01-01",
            publication_date=pub_date,
            assignee="Quantum Battery Inc",
            source_url=f"https://patents.google.com/patent/{patent_number}/en",
            raw_data=raw_data or {"doc_num": patent_number},
        )

    def test_retrieve_multiple_patents_for_run(self) -> None:
        """Verify multiple patents are retrieved and reconstructed as PatentRecord instances."""
        run_id = self._create_run("run-100")
        patents = [
            self._sample_patent("US10000001B2", "Patent 1", "2021-01-01"),
            self._sample_patent("US10000002B2", "Patent 2", "2021-02-01"),
            self._sample_patent("US10000003B2", "Patent 3", "2021-03-01"),
        ]
        self.repo.save_patents_for_run(run_id, patents)

        retrieved = self.reader.get_patents_for_run(run_id)

        self.assertEqual(len(retrieved), 3)
        for item in retrieved:
            self.assertIsInstance(item, PatentRecord)

    def test_fields_reconstructed_correctly(self) -> None:
        """Verify all individual PatentRecord attributes match the stored data."""
        run_id = self._create_run("run-200")
        original = PatentRecord(
            patent_number="EP3456789A1",
            title="Polymer Solid State Separator",
            abstract="Detailed abstract text describing the separator.",
            filing_date="2019-06-15",
            publication_date="2020-12-20",
            assignee="European Energy SA",
            source_url="https://patents.google.com/patent/EP3456789A1/en",
            raw_data={"ipc": "H01M", "priority": "EP"},
        )
        self.repo.save_patents_for_run(run_id, [original])

        retrieved = self.reader.get_patents_for_run(run_id)
        self.assertEqual(len(retrieved), 1)
        record = retrieved[0]

        self.assertEqual(record.patent_number, "EP3456789A1")
        self.assertEqual(record.title, "Polymer Solid State Separator")
        self.assertEqual(record.abstract, "Detailed abstract text describing the separator.")
        self.assertEqual(record.filing_date, "2019-06-15")
        self.assertEqual(record.publication_date, "2020-12-20")
        self.assertEqual(record.assignee, "European Energy SA")
        self.assertEqual(record.source_url, "https://patents.google.com/patent/EP3456789A1/en")
        self.assertEqual(record.raw_data, {"ipc": "H01M", "priority": "EP"})

    def test_raw_data_round_trip(self) -> None:
        """Verify nested raw_data JSON round-trips cleanly into a Python dictionary."""
        run_id = self._create_run("run-300")
        nested_raw = {
            "origin": "EPO_OPS",
            "metadata": {
                "classifications": ["H01M4/13", "H01M10/052"],
                "citations_count": 14,
            },
            "flags": {"valid": True},
        }
        patent = self._sample_patent("US9988776B2", raw_data=nested_raw)
        self.repo.save_patents_for_run(run_id, [patent])

        retrieved = self.reader.get_patents_for_run(run_id)
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].raw_data, nested_raw)
        self.assertEqual(retrieved[0].raw_data["metadata"]["citations_count"], 14)

    def test_malformed_stored_raw_data_handled_safely(self) -> None:
        """Malformed or unparseable raw_data string is handled without crashing."""
        run_id = self._create_run("run-malformed")
        patent_id = str(uuid.uuid4())

        # Directly insert a row with invalid JSON in raw_data
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO patents (id, patent_number, title, raw_data)
                VALUES (?, 'US8877665B2', 'Corrupted Raw Data Patent', '{corrupted: json');
                """,
                (patent_id,),
            )
            conn.execute(
                "INSERT INTO run_patents (run_id, patent_id) VALUES (?, ?);",
                (run_id, patent_id),
            )

        retrieved = self.reader.get_patents_for_run(run_id)
        self.assertEqual(len(retrieved), 1)
        self.assertIsInstance(retrieved[0], PatentRecord)
        self.assertEqual(retrieved[0].patent_number, "US8877665B2")
        self.assertIn("raw_unparsed", retrieved[0].raw_data)
        self.assertEqual(retrieved[0].raw_data["raw_unparsed"], "{corrupted: json")

    def test_deterministic_ordering(self) -> None:
        """Patents are returned in deterministic order: publication_date ASC, patent_number ASC."""
        run_id = self._create_run("run-ordering")
        patents = [
            self._sample_patent("US10000003B2", "P3", pub_date="2023-05-01"),
            self._sample_patent("US10000001B2", "P1", pub_date="2021-01-01"),
            self._sample_patent("US10000002B2", "P2", pub_date="2021-01-01"),
            self._sample_patent("EP1234567A1", "P4", pub_date="2022-03-15"),
        ]
        # Save in mixed order
        self.repo.save_patents_for_run(run_id, patents)

        retrieved = self.reader.get_patents_for_run(run_id)
        numbers = [p.patent_number for p in retrieved]

        # 2021-01-01: EP... doesn't exist, US10000001B2 < US10000002B2
        # 2022-03-15: EP1234567A1
        # 2023-05-01: US10000003B2
        expected_order = [
            "US10000001B2",
            "US10000002B2",
            "EP1234567A1",
            "US10000003B2",
        ]
        self.assertEqual(numbers, expected_order)

    def test_empty_and_unknown_run(self) -> None:
        """Retrieval and count on empty or unknown runs return empty list and 0 without errors."""
        empty_run_id = self._create_run("run-empty")

        self.assertEqual(self.reader.get_patents_for_run(empty_run_id), [])
        self.assertEqual(self.reader.count_patents_for_run(empty_run_id), 0)

        self.assertEqual(self.reader.get_patents_for_run("unknown-run-id"), [])
        self.assertEqual(self.reader.count_patents_for_run("unknown-run-id"), 0)

        self.assertEqual(self.reader.get_patents_for_run(""), [])
        self.assertEqual(self.reader.count_patents_for_run(""), 0)

    def test_count_method(self) -> None:
        """count_patents_for_run accurately reports linked count."""
        run_id = self._create_run("run-count")
        patents = [
            self._sample_patent(f"US100000{i}0B2", f"Patent {i}", "2022-01-01")
            for i in range(1, 5)
        ]
        self.repo.save_patents_for_run(run_id, patents)

        self.assertEqual(self.reader.count_patents_for_run(run_id), 4)

    def test_same_patent_in_multiple_runs_scoped_properly(self) -> None:
        """Patents linked to different runs are cleanly isolated by run_id."""
        run_a = self._create_run("run-A")
        run_b = self._create_run("run-B")

        patent_only_a = self._sample_patent("US10000001B2", "Only in A")
        patent_shared = self._sample_patent("US10000002B2", "In Both A and B")
        patent_only_b = self._sample_patent("US10000003B2", "Only in B")

        self.repo.save_patents_for_run(run_a, [patent_only_a, patent_shared])
        self.repo.save_patents_for_run(run_b, [patent_shared, patent_only_b])

        patents_a = self.reader.get_patents_for_run(run_a)
        patents_b = self.reader.get_patents_for_run(run_b)

        self.assertEqual([p.patent_number for p in patents_a], ["US10000001B2", "US10000002B2"])
        self.assertEqual([p.patent_number for p in patents_b], ["US10000002B2", "US10000003B2"])
        self.assertEqual(self.reader.count_patents_for_run(run_a), 2)
        self.assertEqual(self.reader.count_patents_for_run(run_b), 2)

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
