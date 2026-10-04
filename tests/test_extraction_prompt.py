"""Unit tests for the AI problem extraction prompt specification."""

import unittest

from src.problems.extraction_contract import (
    ALLOWED_CONFIDENCE,
    ALLOWED_FREQUENCY,
    ALLOWED_SEVERITY,
)
from src.problems.extraction_prompt import (
    EXPECTED_OUTPUT_FIELDS,
    PROBLEM_EXTRACTION_SYSTEM_PROMPT,
    format_patent_extraction_user_prompt,
)


class TestProblemExtractionPrompt(unittest.TestCase):
    """Test suite verifying prompt specification rules and requirements."""

    def test_prompt_exists_and_is_non_empty_string(self) -> None:
        """The system prompt is defined as a substantial non-empty string."""
        self.assertIsInstance(PROBLEM_EXTRACTION_SYSTEM_PROMPT, str)
        self.assertTrue(len(PROBLEM_EXTRACTION_SYSTEM_PROMPT.strip()) > 200)

    def test_contains_required_output_field_names(self) -> None:
        """The prompt explicitly defines all 10 expected output fields."""
        self.assertEqual(len(EXPECTED_OUTPUT_FIELDS), 10)

        for field in EXPECTED_OUTPUT_FIELDS:
            self.assertIn(
                f'"{field}"',
                PROBLEM_EXTRACTION_SYSTEM_PROMPT,
                f"Prompt must explicitly specify expected field: '{field}'",
            )

    def test_contains_controlled_vocabulary(self) -> None:
        """The prompt enumerates all controlled values for frequency, severity, and confidence."""
        # Frequency values
        for freq in ALLOWED_FREQUENCY:
            self.assertIn(
                freq,
                PROBLEM_EXTRACTION_SYSTEM_PROMPT,
                f"Controlled frequency '{freq}' missing from system prompt",
            )

        # Severity values
        for sev in ALLOWED_SEVERITY:
            self.assertIn(
                sev,
                PROBLEM_EXTRACTION_SYSTEM_PROMPT,
                f"Controlled severity '{sev}' missing from system prompt",
            )

        # Confidence values
        for conf in ALLOWED_CONFIDENCE:
            self.assertIn(
                conf,
                PROBLEM_EXTRACTION_SYSTEM_PROMPT,
                f"Controlled confidence '{conf}' missing from system prompt",
            )

    def test_distinguishes_invention_from_problem(self) -> None:
        """The prompt explicitly instructs separating the technical solution from the problem."""
        prompt_lower = PROBLEM_EXTRACTION_SYSTEM_PROMPT.lower()

        self.assertIn("separate invention from problem", prompt_lower)
        self.assertIn("solution", prompt_lower)
        self.assertIn("bottleneck", prompt_lower)
        # Verify the concrete example distinguishing solution from problem
        self.assertIn("sensor system", prompt_lower)
        self.assertIn("struggle to detect", prompt_lower)

    def test_prohibits_fabricated_market_and_commercial_claims(self) -> None:
        """The prompt prohibits fabricating market metrics and enforces commercialization neutrality."""
        prompt_lower = PROBLEM_EXTRACTION_SYSTEM_PROMPT.lower()

        # Evidence discipline prohibitions
        self.assertIn("market size", prompt_lower)
        self.assertIn("willingness to pay", prompt_lower)
        self.assertIn("revenue", prompt_lower)
        self.assertIn("customer demand", prompt_lower)

        # Commercial neutrality
        self.assertIn("startup", prompt_lower)
        self.assertIn("commercialization neutrality", prompt_lower)

    def test_requires_json_only_output(self) -> None:
        """The prompt requires pure JSON output without Markdown formatting or extra text."""
        prompt_upper = PROBLEM_EXTRACTION_SYSTEM_PROMPT.upper()

        self.assertIn("ONLY A VALID JSON", prompt_upper)
        self.assertIn("NO MARKDOWN", prompt_upper)

    def test_user_prompt_formatting(self) -> None:
        """User prompt formatting properly incorporates all adapter context fields."""
        sample_input = {
            "patent_number": "US11223344B2",
            "title": "Solid Electrolyte",
            "assignee": "Quantum Corp",
            "filing_date": "2020-01-01",
            "publication_date": "2021-01-01",
            "source_url": "https://patents.google.com/patent/US11223344B2/en",
            "abstract": "Solid state battery separator.",
        }

        user_prompt = format_patent_extraction_user_prompt(sample_input)

        self.assertIn("US11223344B2", user_prompt)
        self.assertIn("Solid Electrolyte", user_prompt)
        self.assertIn("Quantum Corp", user_prompt)
        self.assertIn("Solid state battery separator.", user_prompt)


if __name__ == "__main__":
    unittest.main()
