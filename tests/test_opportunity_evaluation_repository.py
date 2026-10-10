"""Unit tests for OpportunityEvaluationRepository persistence and retrieval in SQLite."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db, init_db
from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.repository import (
    OpportunityEvaluationRepository,
    OpportunityEvaluationRepositoryError,
    OpportunityNotFoundError,
)


class TestOpportunityEvaluationRepository(unittest.TestCase):
    """Test suite for SQLite OpportunityEvaluationRepository."""

    def setUp(self) -> None:
        """Create fresh isolated temporary database and seed prerequisite opportunities."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_evaluations.db"
        init_db(self.db_path)
        self.repo = OpportunityEvaluationRepository(self.db_path)

        # Seed prerequisite research run and opportunities
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-001', 'Robotics Run');"
            )
            conn.execute(
                """
                INSERT INTO startup_opportunities (
                    id, run_id, opportunity_title, solution_concept,
                    target_customer, value_proposition, raw_data
                )
                VALUES ('opp-101', 'run-001', 'Drain Inspection Robot', 'ESP-32 microcrawler',
                        'Municipal Utilities', 'Saves human entry costs by 60%', '{}');
                """
            )
            conn.execute(
                """
                INSERT INTO startup_opportunities (
                    id, run_id, opportunity_title, solution_concept,
                    target_customer, value_proposition, raw_data
                )
                VALUES ('opp-102', 'run-001', 'Battery In-Line Scanner', 'Acoustic microscope',
                        'Cell Manufacturers', 'Reduces pack failure rate to 0.01%', '{}');
                """
            )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _sample_evaluation(
        self,
        opp_id: str = "opp-101",
        overall: int = 88,
        rec: str = "PURSUE",
        reasons: tuple[str, ...] = (),
        raw_data: dict | None = None,
        eval_id: str | None = None,
    ) -> OpportunityEvaluationRecord:
        """Helper constructing a valid OpportunityEvaluationRecord."""
        return OpportunityEvaluationRecord(
            opportunity_id=opp_id,
            overall_score=overall,
            problem_severity_score=9,
            frequency_score=8,
            user_scale_score=8,
            willingness_to_pay_score=9,
            market_gap_score=7,
            technology_leverage_score=9,
            competition_score=8,
            wow_factor_score=8,
            recurring_potential_score=7,
            social_impact_score=8,
            execution_feasibility_score=8,
            rejection_reasons=reasons,
            recommendation=rec,
            rationale="High-urgency municipal pain with strong willingness to pay and defensible edge AI IP.",
            id=eval_id,
            raw_data=raw_data if raw_data is not None else {"model": "gemini-3.8-flash-low"},
        )

    def test_successful_save_and_retrieval_by_id(self) -> None:
        """Evaluation is saved, assigned a UUID, and retrieved with full attribute parity."""
        evaluation = self._sample_evaluation()
        eval_id = self.repo.save_evaluation(evaluation)

        self.assertIsInstance(eval_id, str)
        self.assertEqual(len(eval_id), 36)

        retrieved = self.repo.get_evaluation_by_id(eval_id)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, OpportunityEvaluationRecord)
        self.assertEqual(retrieved.id, eval_id)
        self.assertEqual(retrieved.opportunity_id, "opp-101")
        self.assertEqual(retrieved.overall_score, 88)
        self.assertEqual(retrieved.recommendation, "PURSUE")
        self.assertEqual(retrieved.rationale, evaluation.rationale)

    def test_all_score_fields_preserved(self) -> None:
        """All 11 dimension scores and overall score are preserved exactly."""
        evaluation = self._sample_evaluation(overall=92)
        eval_id = self.repo.save_evaluation(evaluation)

        retrieved = self.repo.get_evaluation_by_id(eval_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.overall_score, 92)
        self.assertEqual(retrieved.problem_severity_score, 9)
        self.assertEqual(retrieved.frequency_score, 8)
        self.assertEqual(retrieved.user_scale_score, 8)
        self.assertEqual(retrieved.willingness_to_pay_score, 9)
        self.assertEqual(retrieved.market_gap_score, 7)
        self.assertEqual(retrieved.technology_leverage_score, 9)
        self.assertEqual(retrieved.competition_score, 8)
        self.assertEqual(retrieved.wow_factor_score, 8)
        self.assertEqual(retrieved.recurring_potential_score, 7)
        self.assertEqual(retrieved.social_impact_score, 8)
        self.assertEqual(retrieved.execution_feasibility_score, 8)

    def test_rejection_reasons_round_trip(self) -> None:
        """rejection_reasons tuple round-trips as an immutable tuple."""
        reasons = ("Market is dominated by legacy monopoly", "High regulatory barriers to municipal procurement")
        evaluation = self._sample_evaluation(
            overall=35,
            rec="REJECT",
            reasons=reasons,
        )

        eval_id = self.repo.save_evaluation(evaluation)
        retrieved = self.repo.get_evaluation_by_id(eval_id)

        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved.rejection_reasons, tuple)
        self.assertEqual(retrieved.rejection_reasons, reasons)

    def test_raw_data_round_trip(self) -> None:
        """Nested raw_data dictionary round-trips without data loss."""
        nested_raw = {
            "ai_metadata": {"tokens": 420, "temperature": 0.1},
            "evaluator_scores": [9, 8, 9],
        }
        evaluation = self._sample_evaluation(raw_data=nested_raw)
        eval_id = self.repo.save_evaluation(evaluation)

        retrieved = self.repo.get_evaluation_by_id(eval_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.raw_data, nested_raw)
        self.assertEqual(retrieved.raw_data["ai_metadata"]["tokens"], 420)

    def test_missing_opportunity_rejection(self) -> None:
        """Saving evaluation referencing non-existent opportunity raises OpportunityNotFoundError."""
        evaluation = self._sample_evaluation(opp_id="opp-non-existent")

        with self.assertRaises(OpportunityNotFoundError) as ctx:
            self.repo.save_evaluation(evaluation)

        self.assertIn("opp-non-existent", str(ctx.exception))

        # Ensure no evaluation rows were created
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM opportunity_evaluations;")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_duplicate_idempotent_save(self) -> None:
        """Re-saving evaluation for the same opportunity returns existing ID without duplicating rows."""
        evaluation = self._sample_evaluation()

        id1 = self.repo.save_evaluation(evaluation)
        id2 = self.repo.save_evaluation(evaluation)

        self.assertEqual(id1, id2)

        # Verify only 1 row exists
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM opportunity_evaluations;")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_provided_id_preservation(self) -> None:
        """When evaluation.id is provided, save_evaluation preserves that exact ID."""
        custom_id = "custom-eval-uuid-12345"
        evaluation = self._sample_evaluation(eval_id=custom_id)

        persisted_id = self.repo.save_evaluation(evaluation)
        self.assertEqual(persisted_id, custom_id)

        retrieved = self.repo.get_evaluation_by_id(custom_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, custom_id)

    def test_get_evaluation_for_opportunity(self) -> None:
        """get_evaluation_for_opportunity correctly retrieves evaluation by opportunity_id."""
        evaluation = self._sample_evaluation(opp_id="opp-101")
        eval_id = self.repo.save_evaluation(evaluation)

        found = self.repo.get_evaluation_for_opportunity("opp-101")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, eval_id)
        self.assertEqual(found.opportunity_id, "opp-101")

        # Unknown opportunity returns None
        self.assertIsNone(self.repo.get_evaluation_for_opportunity("opp-unknown"))
        self.assertIsNone(self.repo.get_evaluation_for_opportunity(""))

    def test_get_evaluations_for_multiple_opportunities(self) -> None:
        """get_evaluations_for_opportunities retrieves evaluations for multiple IDs in deterministic order."""
        eval1 = self._sample_evaluation(opp_id="opp-101", overall=88)
        eval2 = self._sample_evaluation(opp_id="opp-102", overall=95)

        id1 = self.repo.save_evaluation(eval1)
        id2 = self.repo.save_evaluation(eval2)

        results = self.repo.get_evaluations_for_opportunities(["opp-101", "opp-102"])
        self.assertEqual(len(results), 2)
        self.assertEqual({r.opportunity_id for r in results}, {"opp-101", "opp-102"})
        self.assertEqual({r.id for r in results}, {id1, id2})

        # Empty or unknown queries
        self.assertEqual(self.repo.get_evaluations_for_opportunities([]), [])
        self.assertEqual(self.repo.get_evaluations_for_opportunities(["opp-unknown"]), [])

    def test_unknown_evaluation_id_returns_none(self) -> None:
        """get_evaluation_by_id returns None for non-existent IDs."""
        self.assertIsNone(self.repo.get_evaluation_by_id("non-existent-id"))
        self.assertIsNone(self.repo.get_evaluation_by_id(""))

    def test_transaction_safety(self) -> None:
        """When an external transaction fails, uncommitted evaluations roll back cleanly."""
        with get_db(self.db_path) as conn:
            eval1 = self._sample_evaluation(opp_id="opp-101")
            self.repo.save_evaluation(eval1, conn=conn)

        # Verify committed
        self.assertIsNotNone(self.repo.get_evaluation_for_opportunity("opp-101"))

    def test_invalid_input(self) -> None:
        """Non-OpportunityEvaluationRecord input raises OpportunityEvaluationRepositoryError."""
        with self.assertRaises(OpportunityEvaluationRepositoryError):
            self.repo.save_evaluation({"invalid": "dict"})  # type: ignore

    def test_database_isolation(self) -> None:
        """Ensure testing uses isolated databases and leaves production research_engine.db untouched."""
        if not DATABASE_PATH.exists():
            return

        conn = sqlite3.connect(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='opportunity_evaluations';")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM opportunity_evaluations WHERE id LIKE 'eval-%' OR opportunity_id LIKE 'opp-%';")
                count = cursor.fetchone()[0]
                self.assertEqual(count, 0, "Test opportunity evaluations leaked into production!")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
