"""Unit tests for the AI opportunity synthesis prompt specification."""

import unittest

from src.opportunities.opportunity_contract import REQUIRED_OPPORTUNITY_AI_FIELDS
from src.opportunities.opportunity_prompt import (
    EXPECTED_OPPORTUNITY_OUTPUT_FIELDS,
    OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT,
    format_opportunity_synthesis_user_prompt,
)
from src.problems.models import ProblemRecord


class TestOpportunitySynthesisPrompt(unittest.TestCase):
    """Test suite verifying opportunity synthesis prompt rules and user prompt formatting."""

    def _sample_problem(
        self,
        prob_id: str = "prob-001-uuid",
        title: str = "Ceramic Separator Dendrite Penetration",
    ) -> ProblemRecord:
        """Helper returning a valid ProblemRecord instance."""
        return ProblemRecord(
            id=prob_id,
            problem_title=title,
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

    def test_system_prompt_exists_and_is_substantial(self) -> None:
        """System prompt is defined as a non-empty string with substantial instructions."""
        self.assertIsInstance(OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT, str)
        self.assertTrue(len(OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT.strip()) > 500)

    def test_system_prompt_contains_exact_json_field_requirements(self) -> None:
        """The system prompt specifies all 5 required AI output fields and prohibits persistence fields."""
        self.assertEqual(len(EXPECTED_OPPORTUNITY_OUTPUT_FIELDS), 5)
        self.assertEqual(
            set(EXPECTED_OPPORTUNITY_OUTPUT_FIELDS),
            REQUIRED_OPPORTUNITY_AI_FIELDS,
        )

        for field in EXPECTED_OPPORTUNITY_OUTPUT_FIELDS:
            self.assertIn(
                f'"{field}"',
                OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT,
                f"Expected field '{field}' must be explicitly quoted in system prompt schema.",
            )

        # Prohibited fields must be explicitly banned
        prompt_lower = OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT.lower()
        self.assertIn("raw_data", prompt_lower)
        self.assertIn("market_size", prompt_lower)
        self.assertIn("competitors", prompt_lower)

    def test_system_prompt_contains_critical_research_principles(self) -> None:
        """The system prompt explicitly details all key venture reasoning and research principles."""
        prompt_lower = OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT.lower()

        # 1. Lead, not startup
        self.assertIn("research lead", prompt_lower)

        # 2. Don't copy or commercialize patent claims
        self.assertIn("do not simply commercialize or wrap the patent claims", prompt_lower)
        self.assertIn("not assume the patented implementation is the only way", prompt_lower)

        # 3. Bottleneck and clear payer
        self.assertIn("bottleneck", prompt_lower)
        self.assertIn("actually pay", prompt_lower)

        # 4. Recurring / high-frequency pain
        self.assertIn("high-frequency", prompt_lower)

        # 5. Large numbers of users / scale
        self.assertIn("large numbers of users", prompt_lower)

        # 6. B2C / B2B2C / B2B
        self.assertIn("b2c", prompt_lower)
        self.assertIn("b2b2c", prompt_lower)
        self.assertIn("b2b", prompt_lower)

        # 7. Modern technology leverage
        self.assertIn("modern technology", prompt_lower)
        for tech in ["ai", "smartphones", "cloud", "sensors", "iot", "computer vision", "automation"]:
            self.assertIn(tech, prompt_lower)

        # 8. Clones & competitive dynamics
        self.assertIn("clones", prompt_lower)
        self.assertIn("fragmented", prompt_lower)
        self.assertIn("generic apps", prompt_lower)
        self.assertIn("minor feature", prompt_lower)

        # 9. Simple value proposition and why now
        self.assertIn("value proposition", prompt_lower)
        self.assertIn("why now", prompt_lower)

        # 10. Zero fabrication & evidence discipline
        self.assertIn("zero fabrication", prompt_lower)

        # 11. No legal conclusions
        self.assertIn("no legal conclusions", prompt_lower)
        self.assertIn("infringement", prompt_lower)
        self.assertIn("freedom-to-operate", prompt_lower)

        # 12. Multiple problems guidance
        self.assertIn("multiple problems", prompt_lower)

    def test_system_prompt_pure_json_only(self) -> None:
        """The system prompt strictly requires pure JSON output with no markdown fences."""
        self.assertIn("ONLY a valid JSON", OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT)
        self.assertIn("Do NOT wrap in Markdown code blocks", OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT)

    def test_user_prompt_formatting_single_problem(self) -> None:
        """User prompt formatting properly incorporates a single ProblemRecord's fields and ID."""
        prob = self._sample_problem(prob_id="prob-uuid-1234")
        prompt = format_opportunity_synthesis_user_prompt(prob)

        self.assertIn("prob-uuid-1234", prompt)
        self.assertIn("Ceramic Separator Dendrite Penetration", prompt)
        self.assertIn("Lithium metal dendrites breach", prompt)
        self.assertIn("EV Battery Pack Engineers", prompt)
        self.assertIn("Material Degradation", prompt)
        self.assertIn("Energy Storage", prompt)
        self.assertIn("US11223344B2", prompt)

        # Asserts instruction and schema reminder present
        self.assertIn("opportunity_title", prompt)
        self.assertIn("solution_concept", prompt)
        self.assertIn("target_customer", prompt)
        self.assertIn("value_proposition", prompt)
        self.assertIn("source_problem_ids", prompt)
        self.assertIn("Do not commercialize patent claims", prompt)

    def test_user_prompt_formatting_multiple_problems(self) -> None:
        """User prompt correctly formats multiple ProblemRecords with sequential headers."""
        p1 = self._sample_problem(prob_id="prob-1", title="Dendrite Growth")
        p2 = self._sample_problem(prob_id="prob-2", title="Thermal Runaway at Cathode")

        prompt = format_opportunity_synthesis_user_prompt([p1, p2])

        self.assertIn("PROBLEM LEAD 1", prompt)
        self.assertIn("prob-1", prompt)
        self.assertIn("Dendrite Growth", prompt)

        self.assertIn("PROBLEM LEAD 2", prompt)
        self.assertIn("prob-2", prompt)
        self.assertIn("Thermal Runaway at Cathode", prompt)

    def test_user_prompt_validation_empty_or_invalid_inputs(self) -> None:
        """User prompt formatter rejects empty sequences, wrong types, or non-ProblemRecord entries."""
        with self.assertRaises(ValueError):
            format_opportunity_synthesis_user_prompt([])

        with self.assertRaises(ValueError):
            format_opportunity_synthesis_user_prompt(())

        with self.assertRaises(TypeError):
            format_opportunity_synthesis_user_prompt(None)  # type: ignore

        with self.assertRaises(TypeError):
            format_opportunity_synthesis_user_prompt("not a problem record")  # type: ignore

        with self.assertRaises(TypeError):
            format_opportunity_synthesis_user_prompt([self._sample_problem(), {"invalid": "dict"}])  # type: ignore


if __name__ == "__main__":
    unittest.main()
