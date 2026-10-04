"""Unit tests for OpportunityRepository persistence and retrieval in SQLite."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db, init_db
from src.opportunities.models import OpportunityRecord
from src.opportunities.repository import (
    OpportunityNotFoundError,
    OpportunityProblemNotFoundError,
    OpportunityRepository,
    OpportunityRepositoryError,
)


class TestOpportunityRepository(unittest.TestCase):
    """Test suite for SQLite OpportunityRepository."""

    def setUp(self) -> None:
        """Create fresh isolated temporary database and repositories."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_opportunities.db"
        init_db(self.db_path)
        self.repo = OpportunityRepository(self.db_path)

        # Seed prerequisite research runs and patent rows
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-001', 'Energy Storage Run');"
            )
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-002', 'Robotics Run');"
            )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _seed_problem(
        self,
        problem_id: str = "prob-001",
        run_id: str = "run-001",
        title: str = "Electrolyte Dendrite Growth at High Current Density",
    ) -> str:
        """Helper to seed an extracted_problems row in the database."""
        with get_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO extracted_problems (
                    id, run_id, problem_title, problem_description,
                    bottleneck_type, technical_domain, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    problem_id,
                    run_id,
                    title,
                    "Lithium dendrites penetrate solid state ceramic separators.",
                    "Material Degradation",
                    "Energy Storage",
                    "{}",
                ),
            )
        return problem_id

    def _sample_opportunity(
        self,
        title: str = "Nanostructured Ceramic Separator Coating",
        concept: str = "Atomic layer deposition of ultra-thin lithiophilic interfacial coatings.",
        customer: str = "Next-Generation Solid-State Battery Manufacturers",
        val_prop: str = "Extends cell cycle life by 400% under 4C fast charging conditions.",
        source_problem_ids: tuple[str, ...] = ("prob-001",),
        opp_id: str | None = None,
        raw_data: dict | None = None,
    ) -> OpportunityRecord:
        """Helper to construct a valid OpportunityRecord."""
        return OpportunityRecord(
            opportunity_title=title,
            solution_concept=concept,
            target_customer=customer,
            value_proposition=val_prop,
            source_problem_ids=source_problem_ids,
            id=opp_id,
            raw_data=raw_data if raw_data is not None else {"tier": "flagship"},
        )

    def test_save_and_retrieve_by_id(self) -> None:
        """OpportunityRecord is saved, assigned a UUID, and retrieved with full attribute parity."""
        prob_id = self._seed_problem("prob-001")
        opportunity = self._sample_opportunity(source_problem_ids=(prob_id,))

        opp_id = self.repo.save_opportunity(opportunity, run_id="run-001")
        self.assertIsInstance(opp_id, str)
        self.assertEqual(len(opp_id), 36)

        retrieved = self.repo.get_opportunity_by_id(opp_id)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, OpportunityRecord)
        self.assertEqual(retrieved.id, opp_id)
        self.assertEqual(retrieved.opportunity_title, opportunity.opportunity_title)
        self.assertEqual(retrieved.solution_concept, opportunity.solution_concept)
        self.assertEqual(retrieved.target_customer, opportunity.target_customer)
        self.assertEqual(retrieved.value_proposition, opportunity.value_proposition)
        self.assertEqual(retrieved.source_problem_ids, (prob_id,))
        self.assertEqual(retrieved.raw_data, {"tier": "flagship"})

    def test_save_and_retrieve_by_run(self) -> None:
        """Opportunities are filtered correctly by run_id in deterministic order."""
        p1 = self._seed_problem("prob-001", run_id="run-001")
        p2 = self._seed_problem("prob-002", run_id="run-002")

        opp1 = self._sample_opportunity(
            title="Solid Electrolyte Coating Venture",
            source_problem_ids=(p1,),
        )
        opp2 = self._sample_opportunity(
            title="Fast-Charging Thermal Management System",
            source_problem_ids=(p1,),
        )
        opp3 = self._sample_opportunity(
            title="Robotics Pipeline Inspection Tool",
            source_problem_ids=(p2,),
        )

        id1 = self.repo.save_opportunity(opp1, run_id="run-001")
        id2 = self.repo.save_opportunity(opp2, run_id="run-001")
        id3 = self.repo.save_opportunity(opp3, run_id="run-002")

        run1_opps = self.repo.get_opportunities_for_run("run-001")
        run2_opps = self.repo.get_opportunities_for_run("run-002")
        empty_opps = self.repo.get_opportunities_for_run("run-nonexistent")

        self.assertEqual(len(run1_opps), 2)
        self.assertEqual(len(run2_opps), 1)
        self.assertEqual(len(empty_opps), 0)

        self.assertEqual([o.id for o in run1_opps], [id1, id2])
        self.assertEqual(run1_opps[0].opportunity_title, "Solid Electrolyte Coating Venture")
        self.assertEqual(run1_opps[1].opportunity_title, "Fast-Charging Thermal Management System")
        self.assertEqual(run2_opps[0].id, id3)
        self.assertEqual(run2_opps[0].opportunity_title, "Robotics Pipeline Inspection Tool")

    def test_generated_uuid(self) -> None:
        """When id is None, save_opportunity generates a new valid UUID4."""
        prob_id = self._seed_problem("prob-001")
        opp = self._sample_opportunity(opp_id=None, source_problem_ids=(prob_id,))

        persisted_id = self.repo.save_opportunity(opp, run_id="run-001")
        self.assertIsNotNone(persisted_id)
        uuid_obj = uuid.UUID(persisted_id)
        self.assertEqual(str(uuid_obj), persisted_id)

        retrieved = self.repo.get_opportunity_by_id(persisted_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, persisted_id)

    def test_provided_uuid_preservation(self) -> None:
        """When id is provided, save_opportunity preserves that exact ID."""
        prob_id = self._seed_problem("prob-001")
        custom_id = "e2c07a3f-14f7-418e-9ea1-9238e8ec438b"
        opp = self._sample_opportunity(opp_id=custom_id, source_problem_ids=(prob_id,))

        persisted_id = self.repo.save_opportunity(opp, run_id="run-001")
        self.assertEqual(persisted_id, custom_id)

        retrieved = self.repo.get_opportunity_by_id(custom_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, custom_id)

    def test_all_opportunity_fields_round_trip(self) -> None:
        """Nested raw_data and all domain fields round-trip with 100% fidelity."""
        prob_id = self._seed_problem("prob-001")
        complex_raw = {
            "ai_metadata": {"model": "gemini-3.8-flash-low", "temperature": 0.2},
            "market_analysis": {
                "tam": "12B",
                "competitors": ["Alpha Corp", "Beta Tech"],
            },
            "confidence_scores": [0.98, 0.94],
        }
        opp = self._sample_opportunity(
            title="AI In-Line Defect Scanner for Solid Electrolytes",
            concept="Hyperspectral vision combined with edge ML inference to reject dendrite-prone separators.",
            customer="Solid-state EV battery pack manufacturing plants",
            val_prop="Reduces pack failure rate from 2.5% to under 0.01% during assembly.",
            source_problem_ids=(prob_id,),
            raw_data=complex_raw,
        )

        persisted_id = self.repo.save_opportunity(opp, run_id="run-001")
        retrieved = self.repo.get_opportunity_by_id(persisted_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.opportunity_title, opp.opportunity_title)
        self.assertEqual(retrieved.solution_concept, opp.solution_concept)
        self.assertEqual(retrieved.target_customer, opp.target_customer)
        self.assertEqual(retrieved.value_proposition, opp.value_proposition)
        self.assertEqual(retrieved.source_problem_ids, (prob_id,))
        self.assertEqual(retrieved.raw_data, complex_raw)
        self.assertEqual(
            retrieved.raw_data["market_analysis"]["competitors"],
            ["Alpha Corp", "Beta Tech"],
        )

    def test_source_problem_links_are_created(self) -> None:
        """Saving an opportunity creates junction rows in opportunity_problems."""
        prob_id = self._seed_problem("prob-001")
        opp = self._sample_opportunity(source_problem_ids=(prob_id,))

        opp_id = self.repo.save_opportunity(opp, run_id="run-001")

        linked_problems = self.repo.get_problems_for_opportunity(opp_id)
        self.assertEqual(linked_problems, [prob_id])

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT opportunity_id, problem_id FROM opportunity_problems WHERE opportunity_id = ?;",
                (opp_id,),
            )
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["opportunity_id"], opp_id)
            self.assertEqual(rows[0]["problem_id"], prob_id)

    def test_one_opportunity_multiple_problems(self) -> None:
        """One opportunity can address and link to multiple extracted problems."""
        p1 = self._seed_problem("prob-001", title="Dendrite Growth Problem")
        p2 = self._seed_problem("prob-002", title="High Interfacial Resistance Problem")

        opp = self._sample_opportunity(
            title="Integrated Electrolyte Interface & Separator",
            source_problem_ids=(p1, p2),
        )

        opp_id = self.repo.save_opportunity(opp, run_id="run-001")

        linked_problems = self.repo.get_problems_for_opportunity(opp_id)
        self.assertEqual(set(linked_problems), {p1, p2})

        retrieved = self.repo.get_opportunity_by_id(opp_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(set(retrieved.source_problem_ids), {p1, p2})

    def test_one_problem_multiple_opportunities(self) -> None:
        """One problem can be addressed by multiple distinct startup opportunities."""
        prob_id = self._seed_problem("prob-001")

        opp1 = self._sample_opportunity(
            title="Approach A: Nanomaterial Separator Additive",
            source_problem_ids=(prob_id,),
        )
        opp2 = self._sample_opportunity(
            title="Approach B: Acoustic Wave Dendrite Disruption",
            source_problem_ids=(prob_id,),
        )

        id1 = self.repo.save_opportunity(opp1, run_id="run-001")
        id2 = self.repo.save_opportunity(opp2, run_id="run-001")
        self.assertNotEqual(id1, id2)

        # Both opportunities link to the same problem
        self.assertEqual(self.repo.get_problems_for_opportunity(id1), [prob_id])
        self.assertEqual(self.repo.get_problems_for_opportunity(id2), [prob_id])

        # Verify junction table has 2 rows pointing to prob-001
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM opportunity_problems WHERE problem_id = ?;",
                (prob_id,),
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_duplicate_saving_idempotency(self) -> None:
        """Saving the exact same opportunity repeatedly returns existing ID without duplicating rows."""
        prob_id = self._seed_problem("prob-001")
        opp = self._sample_opportunity(
            title="Deterministic Idempotent Venture Concept",
            source_problem_ids=(prob_id,),
        )

        id1 = self.repo.save_opportunity(opp, run_id="run-001")
        id2 = self.repo.save_opportunity(opp, run_id="run-001")
        self.assertEqual(id1, id2)

        # Verify exactly 1 row in startup_opportunities and 1 in opportunity_problems
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM startup_opportunities WHERE run_id = 'run-001';")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT COUNT(*) FROM opportunity_problems;")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_missing_source_problem_rejected(self) -> None:
        """Referencing an unpersisted problem raises OpportunityProblemNotFoundError."""
        opp = self._sample_opportunity(source_problem_ids=("non-existent-problem",))

        with self.assertRaises(OpportunityProblemNotFoundError) as ctx:
            self.repo.save_opportunity(opp, run_id="run-001")

        self.assertIn("non-existent-problem", str(ctx.exception))

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM startup_opportunities;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_failed_save_does_not_leave_partial_opportunity(self) -> None:
        """If one problem in a multi-problem list is missing, no opportunity or link rows are created."""
        p1 = self._seed_problem("prob-001")
        # prob-002 does NOT exist

        opp = self._sample_opportunity(
            source_problem_ids=(p1, "prob-002-missing"),
        )

        with self.assertRaises(OpportunityProblemNotFoundError):
            self.repo.save_opportunity(opp, run_id="run-001")

        # Ensure no records or links were committed
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM startup_opportunities;")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM opportunity_problems;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_invalid_input(self) -> None:
        """Invalid inputs to save and retrieval methods raise expected errors or return empty."""
        prob_id = self._seed_problem("prob-001")
        valid_opp = self._sample_opportunity(source_problem_ids=(prob_id,))

        # Non-OpportunityRecord
        with self.assertRaises(OpportunityRepositoryError):
            self.repo.save_opportunity({"title": "Mock"}, run_id="run-001")  # type: ignore

        # Empty run_id
        with self.assertRaises(OpportunityRepositoryError):
            self.repo.save_opportunity(valid_opp, run_id="")

        with self.assertRaises(OpportunityRepositoryError):
            self.repo.save_opportunity(valid_opp, run_id="   ")

        # None or empty opportunity_id query returns None / empty list
        self.assertIsNone(self.repo.get_opportunity_by_id(""))
        self.assertEqual(self.repo.get_opportunities_for_run(""), [])
        self.assertEqual(self.repo.get_problems_for_opportunity(""), [])

    def test_database_isolation(self) -> None:
        """Ensure testing uses isolated databases and leaves production research_engine.db untouched."""
        if not DATABASE_PATH.exists():
            return

        conn = sqlite3.connect(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM startup_opportunities;")
            so_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM opportunity_problems;")
            op_count = cursor.fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(so_count, 0, "Production startup_opportunities has rows!")
        self.assertEqual(op_count, 0, "Production opportunity_problems has rows!")


if __name__ == "__main__":
    unittest.main()
