"""Unit tests for OpportunitySynthesisService using mocked dependencies."""

import json
import unittest
from unittest.mock import MagicMock, call

from src.opportunities.models import OpportunityRecord
from src.opportunities.opportunity_prompt import OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT
from src.opportunities.repository import OpportunityRepository, OpportunityRepositoryError
from src.opportunities.synthesis_service import (
    NoProblemsInRunError,
    OpportunitySynthesisAIError,
    OpportunitySynthesisParseError,
    OpportunitySynthesisPersistenceError,
    OpportunitySynthesisService,
    OpportunitySynthesisServiceError,
)
from src.problems.ai_client import AIClientError
from src.problems.models import ProblemRecord
from src.problems.repository import ProblemRepository


class TestOpportunitySynthesisService(unittest.TestCase):
    """Test suite for OpportunitySynthesisService with mock dependencies."""

    def setUp(self) -> None:
        """Set up test fixtures and mocked dependencies."""
        self.mock_ai_client = MagicMock()
        self.mock_problem_repo = MagicMock(spec=ProblemRepository)
        self.mock_opportunity_repo = MagicMock(spec=OpportunityRepository)

        self.service = OpportunitySynthesisService(
            ai_client=self.mock_ai_client,
            problem_repository=self.mock_problem_repo,
            opportunity_repository=self.mock_opportunity_repo,
        )

        self.sample_problem = ProblemRecord(
            id="prob-001-uuid",
            problem_title="Ceramic Separator Dendrite Penetration",
            problem_description="Lithium metal dendrites breach solid ceramic separators at high current density.",
            affected_users="EV Battery Pack Engineers and Cell Manufacturers",
            bottleneck_type="Material Degradation / Dendrite Formation",
            technical_domain="Energy Storage / Solid-State Batteries",
            current_workaround="Limiting fast-charge current and thick separator layers",
            problem_frequency="high",
            problem_severity="critical",
            evidence_summary="Disclosed in comparative battery cycling failure analysis in patent claims.",
            evidence_confidence="high",
            source_patent_numbers=("US11223344B2",),
            raw_data={"lead_type": "material_science"},
        )

        self.valid_ai_dict = {
            "opportunity_title": "AI Autonomous Battery In-Line Quality Scanner",
            "solution_concept": "High-throughput acoustic microscopy paired with edge ML to detect dendrite seeds during cell assembly.",
            "target_customer": "Solid-state EV battery pack manufacturing plants and quality assurance leads",
            "value_proposition": "Reduces pack failure rate from 2.5% to under 0.01% while increasing production line yield by 18%.",
            "source_problem_ids": ["prob-001-uuid"],
        }
        self.valid_ai_json = json.dumps(self.valid_ai_dict)

    def test_initialization_requires_all_dependencies(self) -> None:
        """Missing any required dependency in __init__ raises ValueError."""
        with self.assertRaises(ValueError):
            OpportunitySynthesisService(
                ai_client=None,
                problem_repository=self.mock_problem_repo,
                opportunity_repository=self.mock_opportunity_repo,
            )

        with self.assertRaises(ValueError):
            OpportunitySynthesisService(
                ai_client=self.mock_ai_client,
                problem_repository=None,
                opportunity_repository=self.mock_opportunity_repo,
            )

        with self.assertRaises(ValueError):
            OpportunitySynthesisService(
                ai_client=self.mock_ai_client,
                problem_repository=self.mock_problem_repo,
                opportunity_repository=None,
            )

    def test_successful_synthesis_and_persistence(self) -> None:
        """Service queries problems, calls AI, parses response, persists, and returns record with ID."""
        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem]
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_opportunity_repo.save_opportunity.return_value = "opp-persisted-uuid-999"

        result = self.service.synthesize_opportunity_for_run("run-001")

        # Verify calls
        self.mock_problem_repo.get_problems_for_run.assert_called_once_with("run-001")
        self.mock_ai_client.generate.assert_called_once()
        call_kwargs = self.mock_ai_client.generate.call_args.kwargs
        self.assertEqual(call_kwargs["system_prompt"], OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT)
        self.assertIn("prob-001-uuid", call_kwargs["user_prompt"])
        self.assertIn("Ceramic Separator Dendrite Penetration", call_kwargs["user_prompt"])

        self.mock_opportunity_repo.save_opportunity.assert_called_once()
        save_kwargs = self.mock_opportunity_repo.save_opportunity.call_args.kwargs
        self.assertEqual(save_kwargs["run_id"], "run-001")
        saved_opp = save_kwargs["opportunity"]
        self.assertIsInstance(saved_opp, OpportunityRecord)
        self.assertIsNone(saved_opp.id)  # Before persistence, record id was None
        self.assertEqual(saved_opp.opportunity_title, self.valid_ai_dict["opportunity_title"])

        # Returned record has populated persisted ID
        self.assertEqual(result.id, "opp-persisted-uuid-999")
        self.assertEqual(result.opportunity_title, self.valid_ai_dict["opportunity_title"])
        self.assertEqual(result.solution_concept, self.valid_ai_dict["solution_concept"])
        self.assertEqual(result.target_customer, self.valid_ai_dict["target_customer"])
        self.assertEqual(result.value_proposition, self.valid_ai_dict["value_proposition"])
        self.assertEqual(result.source_problem_ids, ("prob-001-uuid",))

    def test_multiple_source_problems(self) -> None:
        """Service correctly processes multiple problem leads and preserves all source problem IDs."""
        prob2 = ProblemRecord(
            id="prob-002-uuid",
            problem_title="Thermal Hotspot Propagation",
            problem_description="Thermal gradients induce rapid degradation.",
            affected_users="EV Pack Engineers",
            bottleneck_type="Thermal Instability",
            technical_domain="Energy Storage",
            current_workaround="Derating fast charge",
            problem_frequency="high",
            problem_severity="critical",
            evidence_summary="Patent disclosure example 2.",
            evidence_confidence="high",
            source_patent_numbers=("US9988776B2",),
            raw_data={},
        )

        multi_dict = dict(self.valid_ai_dict)
        multi_dict["source_problem_ids"] = ["prob-001-uuid", "prob-002-uuid"]

        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem, prob2]
        self.mock_ai_client.generate.return_value = json.dumps(multi_dict)
        self.mock_opportunity_repo.save_opportunity.return_value = "opp-multi-uuid"

        result = self.service.synthesize_opportunity_for_run("run-001")

        call_kwargs = self.mock_ai_client.generate.call_args.kwargs
        self.assertIn("PROBLEM LEAD 1", call_kwargs["user_prompt"])
        self.assertIn("prob-001-uuid", call_kwargs["user_prompt"])
        self.assertIn("PROBLEM LEAD 2", call_kwargs["user_prompt"])
        self.assertIn("prob-002-uuid", call_kwargs["user_prompt"])

        self.assertEqual(result.source_problem_ids, ("prob-001-uuid", "prob-002-uuid"))
        self.assertIsInstance(result.source_problem_ids, tuple)

    def test_no_problems_for_run(self) -> None:
        """When research run contains zero problems, NoProblemsInRunError is raised and AI is not called."""
        self.mock_problem_repo.get_problems_for_run.return_value = []

        with self.assertRaises(NoProblemsInRunError) as ctx:
            self.service.synthesize_opportunity_for_run("run-empty")

        self.assertIn("run-empty", str(ctx.exception))
        self.mock_ai_client.generate.assert_not_called()
        self.mock_opportunity_repo.save_opportunity.assert_not_called()

    def test_ai_failure(self) -> None:
        """AI client failure raises OpportunitySynthesisAIError and does not call repository."""
        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem]
        self.mock_ai_client.generate.side_effect = AIClientError("Subprocess timeout after 120s")

        with self.assertRaises(OpportunitySynthesisAIError) as ctx:
            self.service.synthesize_opportunity_for_run("run-001")

        self.assertIn("Subprocess timeout", str(ctx.exception))
        self.mock_opportunity_repo.save_opportunity.assert_not_called()

    def test_parser_failure(self) -> None:
        """Malformed or non-compliant AI response raises OpportunitySynthesisParseError without saving."""
        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem]

        # Case 1: Malformed JSON
        self.mock_ai_client.generate.return_value = "not valid json {broken"
        with self.assertRaises(OpportunitySynthesisParseError) as ctx:
            self.service.synthesize_opportunity_for_run("run-001")
        self.assertIn("failed to parse", str(ctx.exception).lower())
        self.mock_opportunity_repo.save_opportunity.assert_not_called()

        # Case 2: Missing field in JSON
        invalid_dict = dict(self.valid_ai_dict)
        del invalid_dict["opportunity_title"]
        self.mock_ai_client.generate.return_value = json.dumps(invalid_dict)
        with self.assertRaises(OpportunitySynthesisParseError):
            self.service.synthesize_opportunity_for_run("run-001")
        self.mock_opportunity_repo.save_opportunity.assert_not_called()

    def test_repository_failure(self) -> None:
        """Repository persistence failure raises OpportunitySynthesisPersistenceError."""
        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem]
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_opportunity_repo.save_opportunity.side_effect = OpportunityRepositoryError("DB is locked")

        with self.assertRaises(OpportunitySynthesisPersistenceError) as ctx:
            self.service.synthesize_opportunity_for_run("run-001")

        self.assertIn("DB is locked", str(ctx.exception))

    def test_dependencies_called_in_expected_order(self) -> None:
        """Dependencies are strictly called in order: problem repo -> AI client -> opportunity repo."""
        manager = MagicMock()
        manager.attach_mock(self.mock_problem_repo.get_problems_for_run, "get_problems_for_run")
        manager.attach_mock(self.mock_ai_client.generate, "generate")
        manager.attach_mock(self.mock_opportunity_repo.save_opportunity, "save_opportunity")

        self.mock_problem_repo.get_problems_for_run.return_value = [self.sample_problem]
        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_opportunity_repo.save_opportunity.return_value = "persisted-id"

        self.service.synthesize_opportunity_for_run("run-order-test")

        # Verify order of the three main method calls
        mock_calls = [c[0] for c in manager.mock_calls]
        self.assertEqual(
            mock_calls,
            ["get_problems_for_run", "generate", "save_opportunity"],
        )

    def test_run_id_validation(self) -> None:
        """Invalid run_id values raise OpportunitySynthesisServiceError immediately."""
        for invalid_run in ["", "   ", None, 123]:
            with self.subTest(run_id=invalid_run):
                with self.assertRaises(OpportunitySynthesisServiceError):
                    self.service.synthesize_opportunity_for_run(invalid_run)  # type: ignore

        self.mock_problem_repo.get_problems_for_run.assert_not_called()
        self.mock_ai_client.generate.assert_not_called()
        self.mock_opportunity_repo.save_opportunity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
