"""Unit tests for OpportunityEvaluationService using mocked dependencies."""

import json
import unittest
from unittest.mock import MagicMock

from src.evaluation.evaluation_service import (
    OpportunityEvaluationAIError,
    OpportunityEvaluationParseError,
    OpportunityEvaluationPersistenceError,
    OpportunityEvaluationService,
    OpportunityEvaluationServiceError,
    OpportunityIdMismatchError,
    OpportunityNotFoundError,
)
from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.opportunity_evaluation_prompt import OPPORTUNITY_EVALUATION_SYSTEM_PROMPT
from src.evaluation.repository import (
    OpportunityEvaluationRepository,
    OpportunityEvaluationRepositoryError,
)
from src.opportunities.models import OpportunityRecord
from src.opportunities.repository import OpportunityRepository
from src.problems.ai_client import AIClientError
from src.problems.models import ProblemRecord
from src.problems.repository import ProblemRepository


class TestOpportunityEvaluationService(unittest.TestCase):
    """Test suite for OpportunityEvaluationService."""

    def setUp(self) -> None:
        """Set up test fixtures and mocks."""
        self.mock_ai_client = MagicMock()
        self.mock_opportunity_repo = MagicMock(spec=OpportunityRepository)
        self.mock_problem_repo = MagicMock(spec=ProblemRepository)
        self.mock_evaluation_repo = MagicMock(spec=OpportunityEvaluationRepository)

        self.service = OpportunityEvaluationService(
            ai_client=self.mock_ai_client,
            opportunity_repository=self.mock_opportunity_repo,
            problem_repository=self.mock_problem_repo,
            evaluation_repository=self.mock_evaluation_repo,
        )

        self.sample_opportunity = OpportunityRecord(
            id="opp-101",
            opportunity_title="AI Autonomous Industrial Drain Inspection Robotics",
            solution_concept="ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
            target_customer="Municipal Water Authorities and Industrial Plant EHS Managers",
            value_proposition="Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
            source_problem_ids=("prob-001-uuid",),
        )

        self.sample_problem = ProblemRecord(
            id="prob-001-uuid",
            problem_title="Toxic Sewer Gas Exposure in Inspection",
            problem_description="Municipal operators suffer toxic gas poisoning in unmapped sewer junctions.",
            affected_users="Sewer maintenance workers",
            bottleneck_type="Human Safety Hazard",
            technical_domain="Municipal Infrastructure",
            current_workaround="Manual gas detector on a pole",
            problem_frequency="daily",
            problem_severity="critical",
            evidence_summary="Documented in municipal safety report cited in patent.",
            evidence_confidence="high",
            source_patent_numbers=("US11223344B2",),
            raw_data={},
        )

        self.valid_ai_dict = {
            "opportunity_id": "opp-101",
            "overall_score": 88,
            "problem_severity_score": 9,
            "frequency_score": 8,
            "user_scale_score": 8,
            "willingness_to_pay_score": 9,
            "market_gap_score": 7,
            "technology_leverage_score": 9,
            "competition_score": 8,
            "wow_factor_score": 8,
            "recurring_potential_score": 7,
            "social_impact_score": 8,
            "execution_feasibility_score": 8,
            "rejection_reasons": [],
            "recommendation": "PURSUE",
            "rationale": "High-urgency industrial pain with strong willingness to pay and defensible edge AI IP.",
        }
        self.valid_ai_json = json.dumps(self.valid_ai_dict)

    def test_initialization_validation(self) -> None:
        """Service requires ai_client, opportunity_repository, and evaluation_repository."""
        with self.assertRaises(ValueError):
            OpportunityEvaluationService(
                ai_client=None,
                opportunity_repository=self.mock_opportunity_repo,
                evaluation_repository=self.mock_evaluation_repo,
            )

        with self.assertRaises(ValueError):
            OpportunityEvaluationService(
                ai_client=self.mock_ai_client,
                opportunity_repository=None,
                evaluation_repository=self.mock_evaluation_repo,
            )

        with self.assertRaises(ValueError):
            OpportunityEvaluationService(
                ai_client=self.mock_ai_client,
                opportunity_repository=self.mock_opportunity_repo,
                evaluation_repository=None,
            )

    def test_successful_evaluation_and_persistence(self) -> None:
        """Service retrieves opportunity, calls AI, parses response, persists, and returns record with database ID."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity
        self.mock_problem_repo.get_problem_by_id.return_value = self.sample_problem
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_evaluation_repo.save_evaluation.return_value = "eval-persisted-uuid-999"

        result = self.service.evaluate_opportunity("opp-101")

        self.assertIsInstance(result, OpportunityEvaluationRecord)
        self.assertEqual(result.opportunity_id, "opp-101")
        self.assertEqual(result.overall_score, 88)
        self.assertEqual(result.recommendation, "PURSUE")
        self.assertEqual(result.id, "eval-persisted-uuid-999")  # Database ID populated

        # Verify calls
        self.mock_opportunity_repo.get_opportunity_by_id.assert_called_once_with("opp-101")
        self.mock_problem_repo.get_problem_by_id.assert_called_once_with("prob-001-uuid")
        self.mock_ai_client.generate.assert_called_once()
        self.mock_evaluation_repo.save_evaluation.assert_called_once()
        saved_record = self.mock_evaluation_repo.save_evaluation.call_args[0][0]
        self.assertEqual(saved_record.opportunity_id, "opp-101")
        self.assertEqual(saved_record.overall_score, 88)

    def test_opportunity_not_found(self) -> None:
        """When opportunity does not exist in repository, OpportunityNotFoundError is raised and nothing is saved."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = None

        with self.assertRaises(OpportunityNotFoundError) as ctx:
            self.service.evaluate_opportunity("opp-missing")

        self.assertIn("opp-missing", str(ctx.exception))
        self.mock_problem_repo.get_problem_by_id.assert_not_called()
        self.mock_ai_client.generate.assert_not_called()
        self.mock_evaluation_repo.save_evaluation.assert_not_called()

    def test_ai_failure_means_no_persistence(self) -> None:
        """AI client execution failure raises OpportunityEvaluationAIError and never persists."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity
        self.mock_ai_client.generate.side_effect = AIClientError("Process timed out after 120s")

        with self.assertRaises(OpportunityEvaluationAIError) as ctx:
            self.service.evaluate_opportunity("opp-101")

        self.assertIn("Process timed out", str(ctx.exception))
        self.mock_evaluation_repo.save_evaluation.assert_not_called()

    def test_parser_failure_means_no_persistence(self) -> None:
        """Malformed JSON or contract violation in AI output raises OpportunityEvaluationParseError and never persists."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity

        # Case 1: Malformed JSON
        self.mock_ai_client.generate.return_value = "not valid json"
        with self.assertRaises(OpportunityEvaluationParseError):
            self.service.evaluate_opportunity("opp-101")
        self.mock_evaluation_repo.save_evaluation.assert_not_called()

        # Case 2: Missing required field
        bad_dict = dict(self.valid_ai_dict)
        del bad_dict["overall_score"]
        self.mock_ai_client.generate.return_value = json.dumps(bad_dict)
        with self.assertRaises(OpportunityEvaluationParseError):
            self.service.evaluate_opportunity("opp-101")
        self.mock_evaluation_repo.save_evaluation.assert_not_called()

    def test_id_mismatch_means_no_persistence(self) -> None:
        """When AI returns a mismatched opportunity_id, OpportunityIdMismatchError is raised and never persists."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity

        mismatched_dict = dict(self.valid_ai_dict)
        mismatched_dict["opportunity_id"] = "opp-completely-different-999"
        self.mock_ai_client.generate.return_value = json.dumps(mismatched_dict)

        with self.assertRaises(OpportunityIdMismatchError) as ctx:
            self.service.evaluate_opportunity("opp-101")

        self.assertIn("mismatch", str(ctx.exception).lower())
        self.mock_evaluation_repo.save_evaluation.assert_not_called()

    def test_repository_failure(self) -> None:
        """Evaluation repository failure raises OpportunityEvaluationPersistenceError."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity
        self.mock_problem_repo.get_problem_by_id.return_value = self.sample_problem
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_evaluation_repo.save_evaluation.side_effect = OpportunityEvaluationRepositoryError("DB locked")

        with self.assertRaises(OpportunityEvaluationPersistenceError) as ctx:
            self.service.evaluate_opportunity("opp-101")

        self.assertIn("DB locked", str(ctx.exception))

    def test_source_problems_passed_to_prompt(self) -> None:
        """Originating ProblemRecords are queried and formatted into the evaluation prompt."""
        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity
        self.mock_problem_repo.get_problem_by_id.return_value = self.sample_problem
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_evaluation_repo.save_evaluation.return_value = "eval-uuid-1"

        self.service.evaluate_opportunity("opp-101")

        call_kwargs = self.mock_ai_client.generate.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("--- SOURCE PROBLEM CONTEXT ---", user_prompt)
        self.assertIn("Toxic Sewer Gas Exposure in Inspection", user_prompt)
        self.assertIn("Human Safety Hazard", user_prompt)

    def test_dependency_call_order(self) -> None:
        """Dependencies are strictly called in order: opportunity repo -> problem repo -> AI client -> eval repo."""
        manager = MagicMock()
        manager.attach_mock(self.mock_opportunity_repo.get_opportunity_by_id, "get_opportunity_by_id")
        manager.attach_mock(self.mock_problem_repo.get_problem_by_id, "get_problem_by_id")
        manager.attach_mock(self.mock_ai_client.generate, "generate")
        manager.attach_mock(self.mock_evaluation_repo.save_evaluation, "save_evaluation")

        self.mock_opportunity_repo.get_opportunity_by_id.return_value = self.sample_opportunity
        self.mock_problem_repo.get_problem_by_id.return_value = self.sample_problem
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_evaluation_repo.save_evaluation.return_value = "eval-id-123"

        self.service.evaluate_opportunity("opp-101")

        mock_calls = [c[0] for c in manager.mock_calls]
        self.assertEqual(
            mock_calls,
            ["get_opportunity_by_id", "get_problem_by_id", "generate", "save_evaluation"],
        )

    def test_invalid_opportunity_id_input(self) -> None:
        """Invalid opportunity_id values raise OpportunityEvaluationServiceError without calling dependencies."""
        for invalid_id in ["", "   ", None, 123]:
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(OpportunityEvaluationServiceError):
                    self.service.evaluate_opportunity(invalid_id)  # type: ignore

        self.mock_opportunity_repo.get_opportunity_by_id.assert_not_called()
        self.mock_ai_client.generate.assert_not_called()
        self.mock_evaluation_repo.save_evaluation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
