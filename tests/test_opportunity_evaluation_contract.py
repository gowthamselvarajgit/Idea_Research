"""Unit tests for Opportunity Evaluation contract and validation rules."""

import unittest

from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.opportunity_evaluation_contract import (
    OPPORTUNITY_EVALUATION_CONTRACT_PRINCIPLES,
    REQUIRED_EVALUATION_FIELDS,
    OpportunityEvaluationContractValidationError,
    validate_opportunity_evaluation_contract,
    validate_opportunity_evaluation_payload,
    validate_opportunity_evaluation_record,
)


class TestOpportunityEvaluationContract(unittest.TestCase):
    """Test suite for opportunity evaluation contract validation."""

    def _sample_payload(self) -> dict:
        """Helper providing a valid evaluation output dictionary."""
        return {
            "opportunity_id": "opp-uuid-001",
            "overall_score": 88,
            "problem_severity_score": 9,
            "frequency_score": 9,
            "user_scale_score": 8,
            "willingness_to_pay_score": 9,
            "market_gap_score": 8,
            "technology_leverage_score": 9,
            "competition_score": 7,
            "wow_factor_score": 8,
            "recurring_potential_score": 8,
            "social_impact_score": 8,
            "execution_feasibility_score": 8,
            "rejection_reasons": [],
            "recommendation": "PURSUE",
            "rationale": "High-urgency industrial pain point with substantial willingness to pay and defensible edge AI IP.",
        }

    def test_principles_and_constants_defined(self) -> None:
        """Contract principles and required fields constants are properly defined."""
        self.assertIsInstance(OPPORTUNITY_EVALUATION_CONTRACT_PRINCIPLES, str)
        self.assertTrue(len(OPPORTUNITY_EVALUATION_CONTRACT_PRINCIPLES.strip()) > 100)
        self.assertEqual(len(REQUIRED_EVALUATION_FIELDS), 16)
        self.assertIn("overall_score", REQUIRED_EVALUATION_FIELDS)
        self.assertIn("recommendation", REQUIRED_EVALUATION_FIELDS)
        self.assertIn("rejection_reasons", REQUIRED_EVALUATION_FIELDS)
        self.assertNotIn("id", REQUIRED_EVALUATION_FIELDS)

    def test_valid_payload_passes_validation(self) -> None:
        """Valid dictionary payload passes contract validation cleanly."""
        payload = self._sample_payload()
        # Should not raise
        validate_opportunity_evaluation_payload(payload)
        validate_opportunity_evaluation_contract(payload)

    def test_valid_record_passes_validation(self) -> None:
        """Valid OpportunityEvaluationRecord instance passes contract validation."""
        payload = self._sample_payload()
        record = OpportunityEvaluationRecord(**payload)
        validate_opportunity_evaluation_record(record)
        validate_opportunity_evaluation_contract(record)

    def test_missing_field_fails_validation(self) -> None:
        """Missing any required field raises OpportunityEvaluationContractValidationError."""
        for field_name in REQUIRED_EVALUATION_FIELDS:
            with self.subTest(missing_field=field_name):
                payload = self._sample_payload()
                del payload[field_name]
                with self.assertRaises(OpportunityEvaluationContractValidationError):
                    validate_opportunity_evaluation_payload(payload)

    def test_unexpected_extra_field_fails_validation(self) -> None:
        """Unexpected extra fields raise OpportunityEvaluationContractValidationError."""
        payload = self._sample_payload()
        payload["unsupported_field"] = "unexpected"
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload)

        # Persistence id in raw payload should also be rejected
        payload2 = self._sample_payload()
        payload2["id"] = "some-id"
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload2)

    def test_score_out_of_range(self) -> None:
        """Dimension scores outside 0-10 or overall_score outside 0-100 raise error."""
        # overall_score < 0
        p1 = self._sample_payload()
        p1["overall_score"] = -1
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(p1)

        # overall_score > 100
        p2 = self._sample_payload()
        p2["overall_score"] = 101
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(p2)

        # dimension score < 0
        p3 = self._sample_payload()
        p3["problem_severity_score"] = -1
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(p3)

        # dimension score > 10
        p4 = self._sample_payload()
        p4["technology_leverage_score"] = 11
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(p4)

    def test_boolean_score_rejected(self) -> None:
        """Booleans masquerading as integers are strictly rejected."""
        payload = self._sample_payload()
        payload["overall_score"] = True
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload)

        payload2 = self._sample_payload()
        payload2["problem_severity_score"] = False
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload2)

    def test_invalid_recommendation(self) -> None:
        """Non-controlled recommendation raises OpportunityEvaluationContractValidationError."""
        for bad_rec in ["MAYBE", "INVEST", "SKIP", 123, None]:
            with self.subTest(bad_rec=bad_rec):
                payload = self._sample_payload()
                payload["recommendation"] = bad_rec
                with self.assertRaises(OpportunityEvaluationContractValidationError):
                    validate_opportunity_evaluation_payload(payload)

    def test_reject_recommendation_requires_reasons(self) -> None:
        """When recommendation is REJECT, empty rejection_reasons raises error."""
        payload = self._sample_payload()
        payload["recommendation"] = "REJECT"
        payload["rejection_reasons"] = []
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload)

        # With reasons, it passes
        payload["rejection_reasons"] = ["Incumbent monopoly prevents go-to-market"]
        validate_opportunity_evaluation_payload(payload)

    def test_record_reject_requires_reasons(self) -> None:
        """OpportunityEvaluationRecord with REJECT and empty rejection_reasons fails contract validation."""
        payload = self._sample_payload()
        payload["recommendation"] = "REJECT"
        payload["rejection_reasons"] = ()
        record = OpportunityEvaluationRecord(**payload)
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_record(record)

    def test_short_rationale_fails_validation(self) -> None:
        """Rationale shorter than 15 characters fails contract validation."""
        payload = self._sample_payload()
        payload["rationale"] = "Looks decent"  # 12 chars
        with self.assertRaises(OpportunityEvaluationContractValidationError):
            validate_opportunity_evaluation_payload(payload)


if __name__ == "__main__":
    unittest.main()
