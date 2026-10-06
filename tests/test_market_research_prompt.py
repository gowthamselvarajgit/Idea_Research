"""Unit tests for AI market research prompt layer."""

import unittest

from src.market_research.research_prompt import (
    MARKET_RESEARCH_SYSTEM_PROMPT,
    format_market_research_user_prompt,
)
from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord


class TestMarketResearchPrompt(unittest.TestCase):
    """Test suite for Market Research system prompt and user prompt formatter."""

    def _sample_opportunity(self, opp_id: str = "opp-uuid-301") -> OpportunityRecord:
        """Helper to construct a valid OpportunityRecord."""
        return OpportunityRecord(
            opportunity_title="Autonomous Toxic Drain Inspection Robotics",
            solution_concept="ESP-32 microcrawlers equipped with optical and multi-gas sensors for sewer lines.",
            target_customer="Municipal Water Authorities and Industrial Plant EHS Teams",
            value_proposition="Reduces toxic human confined-space entry by 100% and cuts inspection labor cost by 60%.",
            source_problem_ids=("prob-101", "prob-102"),
            id=opp_id,
            raw_data={"domain": "industrial_robotics"},
        )

    def _sample_problem(
        self,
        prob_id: str = "prob-101",
        title: str = "Confined Space Toxic Gas Hazard in Sewer Lines",
    ) -> ProblemRecord:
        """Helper to construct a valid ProblemRecord."""
        return ProblemRecord(
            problem_title=title,
            problem_description="Manual entry into underground pipes exposes workers to toxic H2S and methane gases.",
            affected_users="Municipal Maintenance Personnel",
            bottleneck_type="Atmospheric Hazard",
            technical_domain="Municipal Infrastructure",
            current_workaround="Manual gas detector stick probes and hazardous manned entry",
            problem_frequency="Continuous",
            problem_severity="Critical",
            evidence_summary="Fatalities and OSHA citations documented in multiple sewer inspection incidents.",
            evidence_confidence="High",
            source_patent_numbers=("US8877665B2",),
            id=prob_id,
        )

    def test_system_prompt_structure_and_principles(self) -> None:
        """System prompt is comprehensive and enforces core research principles."""
        self.assertIsInstance(MARKET_RESEARCH_SYSTEM_PROMPT, str)
        self.assertGreater(len(MARKET_RESEARCH_SYSTEM_PROMPT), 500)

        # Check anti-fabrication requirements
        self.assertIn("Do NOT fabricate", MARKET_RESEARCH_SYSTEM_PROMPT)
        self.assertIn("TAM", MARKET_RESEARCH_SYSTEM_PROMPT)

        # Check epistemic tier requirements
        self.assertIn("KNOWN FACTS", MARKET_RESEARCH_SYSTEM_PROMPT)
        self.assertIn("EVIDENCE NEEDED", MARKET_RESEARCH_SYSTEM_PROMPT)
        self.assertIn("HYPOTHESES", MARKET_RESEARCH_SYSTEM_PROMPT)

        # Check competition perspective
        self.assertIn("Competition is NOT automatically bad", MARKET_RESEARCH_SYSTEM_PROMPT)
        self.assertIn("existing competitor", MARKET_RESEARCH_SYSTEM_PROMPT.lower())

        # Check problem vs patent lead principle
        self.assertIn("research lead", MARKET_RESEARCH_SYSTEM_PROMPT.lower())
        self.assertIn("underlying problem", MARKET_RESEARCH_SYSTEM_PROMPT.lower())

    def test_valid_opportunity_prompt_generation_without_problems(self) -> None:
        """User prompt formats cleanly when no source problems are provided."""
        opp = self._sample_opportunity()
        prompt = format_market_research_user_prompt(opp)

        self.assertIsInstance(prompt, str)
        self.assertIn(opp.opportunity_title, prompt)
        self.assertIn(opp.solution_concept, prompt)
        self.assertIn(opp.target_customer, prompt)
        self.assertIn(opp.value_proposition, prompt)
        self.assertIn("opp-uuid-301", prompt)
        self.assertIn("prob-101", prompt)
        self.assertIn("prob-102", prompt)
        self.assertNotIn("--- SOURCE PROBLEM CONTEXT ---", prompt)

    def test_valid_opportunity_prompt_with_none_or_empty_problems(self) -> None:
        """Passing None or empty tuple/list for problems generates valid prompt without problem section."""
        opp = self._sample_opportunity()

        prompt_none = format_market_research_user_prompt(opp, problems=None)
        self.assertNotIn("--- SOURCE PROBLEM CONTEXT ---", prompt_none)

        prompt_empty = format_market_research_user_prompt(opp, problems=[])
        self.assertNotIn("--- SOURCE PROBLEM CONTEXT ---", prompt_empty)

        prompt_tuple = format_market_research_user_prompt(opp, problems=())
        self.assertNotIn("--- SOURCE PROBLEM CONTEXT ---", prompt_tuple)

    def test_prompt_includes_single_source_problem(self) -> None:
        """User prompt includes detailed information for a single supplied problem."""
        opp = self._sample_opportunity()
        prob = self._sample_problem(prob_id="prob-single", title="Extreme Thermal Degradation in Pipe Shells")

        prompt = format_market_research_user_prompt(opp, problems=[prob])
        self.assertIn("--- SOURCE PROBLEM CONTEXT ---", prompt)
        self.assertIn("prob-single", prompt)
        self.assertIn("Extreme Thermal Degradation in Pipe Shells", prompt)
        self.assertIn("Municipal Maintenance Personnel", prompt)
        self.assertIn("US8877665B2", prompt)

    def test_prompt_supports_multiple_problems(self) -> None:
        """User prompt includes multiple source problems when provided."""
        opp = self._sample_opportunity()
        prob1 = self._sample_problem(prob_id="prob-1", title="Toxic Gas Hazard")
        prob2 = self._sample_problem(prob_id="prob-2", title="Pipe Corrosion Acoustic Attenuation")

        prompt = format_market_research_user_prompt(opp, problems=[prob1, prob2])
        self.assertIn("--- SOURCE PROBLEM CONTEXT ---", prompt)
        self.assertIn("Problem Lead 1 (ID: prob-1)", prompt)
        self.assertIn("Toxic Gas Hazard", prompt)
        self.assertIn("Problem Lead 2 (ID: prob-2)", prompt)
        self.assertIn("Pipe Corrosion Acoustic Attenuation", prompt)

    def test_invalid_opportunity_input_rejected(self) -> None:
        """Non-OpportunityRecord input raises TypeError."""
        for invalid_opp in ["not-an-opp", {"title": "Test"}, None, 123]:
            with self.subTest(invalid_opp=invalid_opp):
                with self.assertRaises(TypeError):
                    format_market_research_user_prompt(invalid_opp)  # type: ignore

    def test_invalid_problems_input_rejected(self) -> None:
        """Non-sequence or sequence of non-ProblemRecord objects raises TypeError."""
        opp = self._sample_opportunity()

        with self.assertRaises(TypeError):
            format_market_research_user_prompt(opp, problems="invalid-type")  # type: ignore

        with self.assertRaises(TypeError):
            format_market_research_user_prompt(opp, problems=["not-a-problem-record"])  # type: ignore

        with self.assertRaises(TypeError):
            format_market_research_user_prompt(opp, problems=[self._sample_problem(), 42])  # type: ignore

    def test_prompt_contains_anti_fabrication_requirements(self) -> None:
        """User prompt explicitly includes anti-fabrication and epistemic instructions."""
        opp = self._sample_opportunity()
        prompt = format_market_research_user_prompt(opp)

        self.assertIn("ZERO FABRICATION", prompt)
        self.assertIn("Do NOT invent", prompt)
        self.assertIn("EPISTEMIC CLARITY", prompt)

    def test_prompt_contains_competition_and_gap_analysis_requirements(self) -> None:
        """User prompt contains explicit instructions for competition and gap analysis."""
        opp = self._sample_opportunity()
        prompt = format_market_research_user_prompt(opp)

        self.assertIn("Existing Companies", prompt)
        self.assertIn("Existing Products/Solutions", prompt)
        self.assertIn("Solution Capabilities", prompt)
        self.assertIn("Customer Segments", prompt)
        self.assertIn("Visible Weaknesses", prompt)
        self.assertIn("Category Dynamics", prompt)
        self.assertIn("User Pain & Demand", prompt)
        self.assertIn("Market Gaps", prompt)
        self.assertIn("Meaningful Differentiation", prompt)


if __name__ == "__main__":
    unittest.main()
