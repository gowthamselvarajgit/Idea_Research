"""Unit tests for ProblemRepository persistence in SQLite."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db, init_db
from src.patents.models import PatentRecord
from src.patents.repository import PatentRepository
from src.problems.models import ProblemRecord
from src.problems.repository import (
    ProblemNotFoundError,
    ProblemPatentNotFoundError,
    ProblemRepository,
    ProblemRepositoryError,
)


class TestProblemRepository(unittest.TestCase):
    """Test suite for SQLite ProblemRepository."""

    def setUp(self) -> None:
        """Create fresh isolated temporary database and repositories."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_problems.db"
        init_db(self.db_path)
        self.repo = ProblemRepository(self.db_path)
        self.patent_repo = PatentRepository(self.db_path)

        # Seed prerequisite research run
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-001', 'Energy Storage Run');"
            )
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-002', 'Utility Run');"
            )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _seed_patent(
        self,
        patent_number: str = "US11223344B2",
        title: str = "Solid Electrolyte",
    ) -> str:
        """Helper to seed a patent row in the database."""
        record = PatentRecord(
            patent_number=patent_number,
            title=title,
            abstract="Solid state cell separator.",
            filing_date="2020-01-01",
            publication_date="2021-01-01",
            assignee="Quantum Battery Corp",
            source_url=f"https://patents.google.com/patent/{patent_number}/en",
            raw_data={"doc": patent_number},
        )
        return self.patent_repo.upsert_patent(record)

    def _sample_problem(
        self,
        title: str = "Electrolyte Dendrite Growth at High Current Density",
        source_patents: tuple[str, ...] = ("US11223344B2",),
        raw_data: dict | None = None,
    ) -> ProblemRecord:
        """Helper to construct a valid ProblemRecord."""
        return ProblemRecord(
            problem_title=title,
            problem_description="Lithium dendrites penetrate solid state ceramic separators.",
            affected_users="EV Battery Pack Engineers",
            bottleneck_type="Material Degradation",
            technical_domain="Energy Storage",
            current_workaround="Reducing charging speed",
            problem_frequency="occasional",
            problem_severity="high",
            evidence_summary="Shown in comparative cycling experiments.",
            evidence_confidence="high",
            source_patent_numbers=source_patents,
            raw_data=raw_data if raw_data is not None else {"internal_key": "val"},
        )

    def test_save_and_retrieve_by_id(self) -> None:
        """ProblemRecord is saved, assigned a UUID, and retrieved with full attribute parity."""
        self._seed_patent("US11223344B2")
        problem = self._sample_problem()

        problem_id = self.repo.save_problem(problem, run_id="run-001")
        self.assertIsInstance(problem_id, str)
        self.assertEqual(len(problem_id), 36)

        retrieved = self.repo.get_problem_by_id(problem_id)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, ProblemRecord)
        self.assertEqual(retrieved.problem_title, problem.problem_title)
        self.assertEqual(retrieved.problem_description, problem.problem_description)
        self.assertEqual(retrieved.affected_users, problem.affected_users)
        self.assertEqual(retrieved.bottleneck_type, problem.bottleneck_type)
        self.assertEqual(retrieved.technical_domain, problem.technical_domain)
        self.assertEqual(retrieved.current_workaround, problem.current_workaround)
        self.assertEqual(retrieved.problem_frequency, problem.problem_frequency)
        self.assertEqual(retrieved.problem_severity, problem.problem_severity)
        self.assertEqual(retrieved.evidence_summary, problem.evidence_summary)
        self.assertEqual(retrieved.evidence_confidence, problem.evidence_confidence)
        self.assertEqual(retrieved.source_patent_numbers, ("US11223344B2",))
        self.assertEqual(retrieved.id, problem_id)

    def test_uuid_creation(self) -> None:
        """Each save generates a unique, valid UUID4."""
        self._seed_patent("US11223344B2")
        p1 = self._sample_problem(title="Problem One")
        p2 = self._sample_problem(title="Problem Two")

        id1 = self.repo.save_problem(p1, run_id="run-001")
        id2 = self.repo.save_problem(p2, run_id="run-001")

        self.assertNotEqual(id1, id2)
        uuid_obj1 = uuid.UUID(id1)
        uuid_obj2 = uuid.UUID(id2)
        self.assertEqual(str(uuid_obj1), id1)
        self.assertEqual(str(uuid_obj2), id2)

    def test_complete_raw_data_round_trip(self) -> None:
        """Nested raw_data dictionaries round-trip without data loss."""
        self._seed_patent("US11223344B2")
        nested_raw = {
            "ai_metadata": {"tokens": 250, "model": "gemini-3.8-flash-low"},
            "confidence_scores": [0.95, 0.88],
            "tags": ["critical", "dendrite"],
        }
        problem = self._sample_problem(raw_data=nested_raw)
        problem_id = self.repo.save_problem(problem, run_id="run-001")

        retrieved = self.repo.get_problem_by_id(problem_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.raw_data, nested_raw)
        self.assertEqual(retrieved.raw_data["ai_metadata"]["model"], "gemini-3.8-flash-low")

    def test_source_patent_linkage(self) -> None:
        """Saving a problem creates links in the problem_patents junction table."""
        patent_id = self._seed_patent("US11223344B2")
        problem = self._sample_problem(source_patents=("US11223344B2",))

        problem_id = self.repo.save_problem(problem, run_id="run-001")

        linked_patents = self.repo.get_patents_for_problem(problem_id)
        self.assertEqual(linked_patents, [patent_id])

        # Verify direct junction table content
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT problem_id, patent_id FROM problem_patents WHERE problem_id = ?;",
                (problem_id,),
            )
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["patent_id"], patent_id)

    def test_multiple_source_patents(self) -> None:
        """Problems synthesizing multiple source patents correctly link to all patents."""
        id1 = self._seed_patent("US11223344B2")
        id2 = self._seed_patent("EP3456789A1")
        id3 = self._seed_patent("WO2022012345A1")

        patents_tuple = ("US11223344B2", "EP3456789A1", "WO2022012345A1")
        problem = self._sample_problem(source_patents=patents_tuple)

        problem_id = self.repo.save_problem(problem, run_id="run-001")

        linked_patents = self.repo.get_patents_for_problem(problem_id)
        self.assertEqual(set(linked_patents), {id1, id2, id3})

        retrieved = self.repo.get_problem_by_id(problem_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.source_patent_numbers, patents_tuple)

    def test_duplicate_idempotent_linking(self) -> None:
        """link_problem_to_patent is idempotent and handles repeated calls safely."""
        patent_id = self._seed_patent("US11223344B2")
        problem = self._sample_problem(source_patents=("US11223344B2",))
        problem_id = self.repo.save_problem(problem, run_id="run-001")

        # Explicitly repeat link
        self.repo.link_problem_to_patent(problem_id, patent_id)
        self.repo.link_problem_to_patent(problem_id, patent_id)

        linked_patents = self.repo.get_patents_for_problem(problem_id)
        self.assertEqual(len(linked_patents), 1)

    def test_missing_patent_rejection(self) -> None:
        """Referencing an unpersisted patent raises ProblemPatentNotFoundError without creating rows."""
        problem = self._sample_problem(source_patents=("US9999999B2",))

        with self.assertRaises(ProblemPatentNotFoundError) as ctx:
            self.repo.save_problem(problem, run_id="run-001")

        self.assertIn("US9999999B2", str(ctx.exception))

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM extracted_problems;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_transaction_rollback_on_partial_failure(self) -> None:
        """If one patent in a multi-patent list is missing, the entire transaction rolls back."""
        self._seed_patent("US11223344B2")  # Exists
        # EP9999999A1 does NOT exist

        problem = self._sample_problem(
            source_patents=("US11223344B2", "EP9999999A1")
        )

        with self.assertRaises(ProblemPatentNotFoundError):
            self.repo.save_problem(problem, run_id="run-001")

        # Ensure no records or links were committed
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM extracted_problems;")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM problem_patents;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_run_retrieval(self) -> None:
        """Problems associated with a run are correctly isolated and queried."""
        self._seed_patent("US11223344B2")
        p1 = self._sample_problem(title="Run 1 Problem A")
        p2 = self._sample_problem(title="Run 1 Problem B")
        p3 = self._sample_problem(title="Run 2 Problem C")

        self.repo.save_problem(p1, run_id="run-001")
        self.repo.save_problem(p2, run_id="run-001")
        self.repo.save_problem(p3, run_id="run-002")

        run1_problems = self.repo.get_problems_for_run("run-001")
        run2_problems = self.repo.get_problems_for_run("run-002")
        empty_run_problems = self.repo.get_problems_for_run("run-unknown")

        self.assertEqual(len(run1_problems), 2)
        self.assertEqual(len(run2_problems), 1)
        self.assertEqual(len(empty_run_problems), 0)
        self.assertEqual(run1_problems[0].problem_title, "Run 1 Problem A")
        self.assertEqual(run1_problems[1].problem_title, "Run 1 Problem B")
        self.assertEqual(run2_problems[0].problem_title, "Run 2 Problem C")

    def test_deterministic_ordering(self) -> None:
        """Problems for a run are returned in stable created_at ASC, id ASC order."""
        self._seed_patent("US11223344B2")
        problems = [
            self._sample_problem(title=f"Sequential Problem {i}")
            for i in range(1, 5)
        ]
        for p in problems:
            self.repo.save_problem(p, run_id="run-001")

        retrieved = self.repo.get_problems_for_run("run-001")
        titles = [p.problem_title for p in retrieved]
        expected_titles = [f"Sequential Problem {i}" for i in range(1, 5)]
        self.assertEqual(titles, expected_titles)

    def test_invalid_input(self) -> None:
        """Invalid inputs to save and retrieval methods raise expected errors or return empty."""
        self._seed_patent("US11223344B2")
        valid_problem = self._sample_problem()

        # Non-ProblemRecord
        with self.assertRaises(ProblemRepositoryError):
            self.repo.save_problem({"title": "Mock"}, run_id="run-001")  # type: ignore

        # Empty run_id
        with self.assertRaises(ProblemRepositoryError):
            self.repo.save_problem(valid_problem, run_id="")

        with self.assertRaises(ProblemRepositoryError):
            self.repo.save_problem(valid_problem, run_id="   ")

    def test_save_problem_idempotency(self) -> None:
        """Verify saving the same problem for the same run and patent returns the existing ID without duplicating."""
        self._seed_patent("US11223344B2")
        problem = self._sample_problem(title="Original Problem")

        id1 = self.repo.save_problem(problem, run_id="run-001")
        # Attempt duplicate save
        id2 = self.repo.save_problem(problem, run_id="run-001")

        self.assertEqual(id1, id2)

        # Verify only 1 problem row and 1 problem_patents row exists
        problems = self.repo.get_problems_for_run("run-001")
        self.assertEqual(len(problems), 1)

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM extracted_problems WHERE run_id = 'run-001';")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM problem_patents;")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_get_problem_for_run_and_patent(self) -> None:
        """Verify lookup of problem by run_id and patent number or ID."""
        pat_id = self._seed_patent("US11223344B2")
        self._seed_patent("US9988776B2")

        prob1 = self._sample_problem(title="Problem 1", source_patents=("US11223344B2",))
        prob2 = self._sample_problem(title="Problem 2", source_patents=("US9988776B2",))

        self.repo.save_problem(prob1, run_id="run-001")
        self.repo.save_problem(prob2, run_id="run-001")

        # Lookup by patent_number
        found_by_num = self.repo.get_problem_for_run_and_patent("run-001", "US11223344B2")
        self.assertIsNotNone(found_by_num)
        self.assertEqual(found_by_num.problem_title, "Problem 1")

        # Lookup by patent UUID
        found_by_id = self.repo.get_problem_for_run_and_patent("run-001", pat_id)
        self.assertIsNotNone(found_by_id)
        self.assertEqual(found_by_id.problem_title, "Problem 1")

        # Lookup non-existent
        self.assertIsNone(self.repo.get_problem_for_run_and_patent("run-002", "US11223344B2"))
        self.assertIsNone(self.repo.get_problem_for_run_and_patent("run-001", "NONEXISTENT"))

    def test_production_database_remains_untouched(self) -> None:
        """Ensure testing uses isolated databases and leaves data/research_engine.db empty."""
        if not DATABASE_PATH.exists():
            return

        conn = sqlite3.connect(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM extracted_problems WHERE id LIKE 'prob-%' OR problem_title LIKE 'Test%' OR problem_title LIKE 'Ceramic Separator%';")
            ep_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM problem_patents WHERE problem_id LIKE 'prob-%';")
            pp_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM research_runs WHERE id LIKE 'run-%';")
            rr_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM patents WHERE patent_number IN ('US9999999A', 'US1234567A', 'US7654321A') OR id LIKE 'test%' OR id LIKE 'pat-%';")
            p_count = cursor.fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(ep_count, 0, "Test extracted_problems leaked into production!")
        self.assertEqual(pp_count, 0, "Test problem_patents leaked into production!")
        self.assertEqual(rr_count, 0, "Test research_runs leaked into production!")
        self.assertEqual(p_count, 0, "Test patents leaked into production!")


if __name__ == "__main__":
    unittest.main()
