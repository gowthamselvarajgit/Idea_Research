"""Unit tests for Problem extraction contract and controlled vocabulary validation."""

import unittest

from src.problems.extraction_contract import (
    ALLOWED_CONFIDENCE,
    ALLOWED_FREQUENCY,
    ALLOWED_SEVERITY,
    ProblemContractValidationError,
    validate_problem_record,
)
from src.problems.models import ProblemRecord


class TestExtractionContract(unittest.TestCase):
    """Test suite for extraction contract validation."""

    def _sample_record(
        self,
        confidence: str = "high",
        severity: str = "high",
        frequency: str = "daily",
    ) -> ProblemRecord:
        """Helper to create a ProblemRecord with configurable controlled fields."""
        return ProblemRecord(
            problem_title="Solid Electrolyte Delamination at High Cycle Rates",
            problem_description="Interface separation between solid electrolyte and cathode.",
            affected_users="Battery Cell Design Engineers",
            bottleneck_type="Interfacial Degradation",
            technical_domain="Energy Storage",
            current_workaround="Applying excessive external stack pressure",
            problem_frequency=frequency,
            problem_severity=severity,
            evidence_summary="Disclosed in comparative examples of cited patent.",
            evidence_confidence=confidence,
            source_patent_numbers=("US11223344B2",),
            raw_data={"patent_claim_ref": "Claim 1"},
        )

    def test_valid_problem_record_passes_validation(self) -> None:
        """A canonical ProblemRecord with valid controlled values passes validation."""
        record = self._sample_record(confidence="high", severity="high", frequency="daily")
        # Should execute cleanly without raising an exception
        validate_problem_record(record)

    def test_valid_controlled_values_combinations(self) -> None:
        """All defined combinations of allowed confidence, severity, and frequency pass."""
        for conf in ALLOWED_CONFIDENCE:
            for sev in ALLOWED_SEVERITY:
                for freq in ALLOWED_FREQUENCY:
                    record = self._sample_record(confidence=conf, severity=sev, frequency=freq)
                    validate_problem_record(record)

    def test_case_insensitive_handling(self) -> None:
        """Controlled values are validated case-insensitively with leading/trailing spaces tolerated."""
        record = self._sample_record(
            confidence=" HIGH ",
            severity=" Medium ",
            frequency=" OCCASIONAL ",
        )
        validate_problem_record(record)

    def test_invalid_confidence_raises_error(self) -> None:
        """Invalid evidence_confidence values raise ProblemContractValidationError."""
        invalid_values = ["certain", "very high", "unknown", "none", "speculative"]

        for bad_conf in invalid_values:
            record = self._sample_record(confidence=bad_conf)
            with self.assertRaises(ProblemContractValidationError, msg=f"Should reject {bad_conf}"):
                validate_problem_record(record)

    def test_invalid_severity_raises_error(self) -> None:
        """Invalid problem_severity values raise ProblemContractValidationError."""
        invalid_values = ["critical", "catastrophic", "extreme", "negligible"]

        for bad_sev in invalid_values:
            record = self._sample_record(severity=bad_sev)
            with self.assertRaises(ProblemContractValidationError, msg=f"Should reject {bad_sev}"):
                validate_problem_record(record)

    def test_invalid_frequency_raises_error(self) -> None:
        """Invalid problem_frequency values raise ProblemContractValidationError."""
        invalid_values = ["hourly", "yearly", "perpetual", "intermittent", "sporadic"]

        for bad_freq in invalid_values:
            record = self._sample_record(frequency=bad_freq)
            with self.assertRaises(ProblemContractValidationError, msg=f"Should reject {bad_freq}"):
                validate_problem_record(record)

    def test_unknown_handling(self) -> None:
        """Using 'unknown' for severity and frequency is explicitly supported and valid."""
        record = self._sample_record(
            confidence="low",
            severity="unknown",
            frequency="unknown",
        )
        validate_problem_record(record)

    def test_type_error_for_non_record(self) -> None:
        """Passing non-ProblemRecord types raises TypeError."""
        with self.assertRaises(TypeError):
            validate_problem_record({"problem_title": "Dict representation"})  # type: ignore

        with self.assertRaises(TypeError):
            validate_problem_record("string representation")  # type: ignore


if __name__ == "__main__":
    unittest.main()
