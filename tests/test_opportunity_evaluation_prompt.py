"""Unit tests for the Opportunity Evaluation prompt specification and formatting."""

import unittest

from src.evaluation.opportunity_evaluation_contract import REQUIRED_EVALUATION_FIELDS
from src.evaluation.opportunity_evaluation_prompt import (
    EXPECTED_EVALUATION_OUTPUT_FIELDS,
    OPPORTUNITY_EVALUATION_SYSTEM_PROMPT,
    format_opportunity_evaluation_user_prompt,
)
from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord


class TestOpportunityEvaluationPrompt(unittest.TestCase):
    """Test suite verifying evaluation prompt specification rules and user prompt formatting."""

    def _sample_opportunity(self, opp_id: str = "opp-uuid-101") -> OpportunityRecord:
        """Helper providing a valid OpportunityRecord."""
        return OpportunityRecord(
            id=opp_id,
            opportunity_title="AI Autonomous Industrial Drain Inspection Robotics",
            solution_concept="ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
            target_customer="Municipal Water Authorities and Industrial Plant EHS Managers",
            value_proposition="Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
            source_problem_ids=("prob-uuid-001",),
        )

    def _sample_problem(self) -> ProblemRecord:
        """Helper providing a valid ProblemRecord."""
        return ProblemRecord(
            id="prob-uuid-001",
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

    def test_system_prompt_exists_and_is_substantial(self) -> None:
        """System prompt is defined and has substantial instructions."""
        self.assertIsInstance(OPPORTUNITY_EVALUATION_SYSTEM_PROMPT, str)
        self.assertTrue(len(OPPORTUNITY_EVALUATION_SYSTEM_PROMPT.strip()) > 500)

    def test_system_prompt_contains_all_16_fields(self) -> None:
        """System prompt explicitly defines all 16 evaluation contract fields."""
        self.assertEqual(len(EXPECTED_EVALUATION_OUTPUT_FIELDS), 16)
        self.assertEqual(
            set(EXPECTED_EVALUATION_OUTPUT_FIELDS),
            REQUIRED_EVALUATION_FIELDS,
        )

        for field in EXPECTED_EVALUATION_OUTPUT_FIELDS:
            self.assertIn(
                f'"{field}"',
                OPPORTUNITY_EVALUATION_SYSTEM_PROMPT,
                f"Field '{field}' must be explicitly quoted in system prompt schema.",
            )

    def test_system_prompt_contains_critical_evaluation_principles(self) -> None:
        """System prompt contains all required venture evaluation instructions."""
        prompt_lower = OPPORTUNITY_EVALUATION_SYSTEM_PROMPT.lower()

        # 1. Aggressively reject weak opportunities
        self.assertIn("aggressively reject", prompt_lower)
        self.assertIn("skepticism", prompt_lower)

        # 2. Evaluate problem, not patent novelty
        self.assertIn("not the patent novelty", prompt_lower)
        self.assertIn("underlying problem", prompt_lower)

        # 3. All 11 evaluation dimensions
        dimensions = [
            "problem_severity",
            "frequency",
            "user_scale",
            "willingness_to_pay",
            "market_gap",
            "technology_leverage",
            "competition",
            "wow_factor",
            "recurring_potential",
            "social_impact",
            "execution_feasibility",
        ]
        for dim in dimensions:
            self.assertIn(dim, prompt_lower)

        # 4. Avoid fabricated market statistics or validation
        self.assertIn("avoid fabricated", prompt_lower)
        self.assertIn("market statistics", prompt_lower)
        self.assertIn("distinguish", prompt_lower)

        # 5. Recommendation criteria
        self.assertIn("reject", prompt_lower)
        self.assertIn("validate", prompt_lower)
        self.assertIn("pursue", prompt_lower)
        self.assertIn("rejection_reasons", prompt_lower)

        # 6. JSON only requirement
        self.assertIn("only a valid json", prompt_lower)
        self.assertIn("markdown", prompt_lower)

    def test_user_prompt_formatting_opportunity_only(self) -> None:
        """User prompt formatting properly formats OpportunityRecord fields."""
        opp = self._sample_opportunity("opp-uuid-999")
        prompt = format_opportunity_evaluation_user_prompt(opp)

        self.assertIn("opp-uuid-999", prompt)
        self.assertIn("AI Autonomous Industrial Drain Inspection Robotics", prompt)
        self.assertIn("Municipal Water Authorities", prompt)
        self.assertIn("Eliminates human entry", prompt)
        self.assertIn("prob-uuid-001", prompt)
        self.assertNotIn("--- SOURCE PROBLEM CONTEXT ---", prompt)

    def test_user_prompt_formatting_with_problem_context(self) -> None:
        """User prompt formatting includes ProblemRecord context when supplied."""
        opp = self._sample_opportunity("opp-uuid-999")
        prob = self._sample_problem()

        prompt = format_opportunity_evaluation_user_prompt(opp, problems=[prob])

        self.assertIn("opp-uuid-999", prompt)
        self.assertIn("--- SOURCE PROBLEM CONTEXT ---", prompt)
        self.assertIn("Toxic Sewer Gas Exposure in Inspection", prompt)
        self.assertIn("Human Safety Hazard", prompt)

    def test_user_prompt_fallback_id(self) -> None:
        """User prompt assigns a fallback ID if opportunity.id is None."""
        opp = OpportunityRecord(
            opportunity_title="Unpersisted Opportunity Concept",
            solution_concept="Innovative pipeline leak acoustic sensor platform.",
            target_customer="Water pipeline utilities",
            value_proposition="Reduces water utility losses by 40% with continuous monitoring.",
            source_problem_ids=("prob-1",),
            id=None,
        )

        prompt = format_opportunity_evaluation_user_prompt(opp)
        self.assertIn("opportunity-lead-1", prompt)

    def test_user_prompt_rejects_invalid_type(self) -> None:
        """Non-OpportunityRecord input raises TypeError."""
        with self.assertRaises(TypeError):
            format_opportunity_evaluation_user_prompt({"invalid": "dict"})  # type: ignore

        with self.assertRaises(TypeError):
            format_opportunity_evaluation_user_prompt(None)  # type: ignore


if __name__ == "__main__":
    unittest.main()
