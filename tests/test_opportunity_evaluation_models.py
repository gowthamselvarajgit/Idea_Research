"""Unit tests for OpportunityEvaluationRecord data model and validation."""

from dataclasses import FrozenInstanceError
import unittest

from src.evaluation.models import (
    ALLOWED_RECOMMENDATIONS,
    DIMENSION_SCORE_FIELDS,
    OpportunityEvaluationRecord,
)


class TestOpportunityEvaluationModels(unittest.TestCase):
    """Test suite for immutable OpportunityEvaluationRecord dataclass."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for OpportunityEvaluationRecord."""
        return {
            "opportunity_id": "opp-uuid-001",
            "overall_score": 85,
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
            "rejection_reasons": (),
            "recommendation": "PURSUE",
            "rationale": "High-urgency industrial pain with strong willingness to pay and defensible edge AI IP.",
            "raw_data": {"evaluator": "gemini-3.8-flash-low"},
        }

    def test_valid_construction(self) -> None:
        """OpportunityEvaluationRecord constructs successfully with valid attributes."""
        kwargs = self._sample_kwargs()
        record = OpportunityEvaluationRecord(**kwargs)

        self.assertEqual(record.opportunity_id, kwargs["opportunity_id"])
        self.assertEqual(record.overall_score, 85)
        self.assertEqual(record.problem_severity_score, 9)
        self.assertEqual(record.frequency_score, 8)
        self.assertEqual(record.user_scale_score, 8)
        self.assertEqual(record.willingness_to_pay_score, 9)
        self.assertEqual(record.market_gap_score, 7)
        self.assertEqual(record.technology_leverage_score, 9)
        self.assertEqual(record.competition_score, 8)
        self.assertEqual(record.wow_factor_score, 8)
        self.assertEqual(record.recurring_potential_score, 7)
        self.assertEqual(record.social_impact_score, 8)
        self.assertEqual(record.execution_feasibility_score, 8)
        self.assertEqual(record.rejection_reasons, ())
        self.assertEqual(record.recommendation, "PURSUE")
        self.assertEqual(record.rationale, kwargs["rationale"])
        self.assertIsNone(record.id)
        self.assertEqual(record.raw_data, {"evaluator": "gemini-3.8-flash-low"})

    def test_boundary_scores(self) -> None:
        """Records construct cleanly at min/max boundary scores (0 and 10, 0 and 100)."""
        kwargs = self._sample_kwargs()

        # Minimum boundaries
        kwargs_min = dict(kwargs)
        kwargs_min["overall_score"] = 0
        for dim in DIMENSION_SCORE_FIELDS:
            kwargs_min[dim] = 0
        rec_min = OpportunityEvaluationRecord(**kwargs_min)
        self.assertEqual(rec_min.overall_score, 0)
        for dim in DIMENSION_SCORE_FIELDS:
            self.assertEqual(getattr(rec_min, dim), 0)

        # Maximum boundaries
        kwargs_max = dict(kwargs)
        kwargs_max["overall_score"] = 100
        for dim in DIMENSION_SCORE_FIELDS:
            kwargs_max[dim] = 10
        rec_max = OpportunityEvaluationRecord(**kwargs_max)
        self.assertEqual(rec_max.overall_score, 100)
        for dim in DIMENSION_SCORE_FIELDS:
            self.assertEqual(getattr(rec_max, dim), 10)

    def test_invalid_overall_scores(self) -> None:
        """overall_score rejects negative values, >100, floats, booleans, and strings."""
        invalid_overall = [-1, 101, 150, 75.5, True, False, "85", None]
        for bad_score in invalid_overall:
            with self.subTest(bad_overall=bad_score):
                kwargs = self._sample_kwargs()
                kwargs["overall_score"] = bad_score
                with self.assertRaises((ValueError, TypeError)):
                    OpportunityEvaluationRecord(**kwargs)

    def test_invalid_dimension_scores(self) -> None:
        """Dimension scores reject <0, >10, floats, booleans, and non-ints."""
        bad_dimension_values = [-1, 11, 20, 5.5, True, False, "9", None]
        for dim in DIMENSION_SCORE_FIELDS:
            for bad_val in bad_dimension_values:
                with self.subTest(dimension=dim, bad_val=bad_val):
                    kwargs = self._sample_kwargs()
                    kwargs[dim] = bad_val
                    with self.assertRaises((ValueError, TypeError)):
                        OpportunityEvaluationRecord(**kwargs)

    def test_valid_recommendations(self) -> None:
        """recommendation accepts PURSUE, VALIDATE, REJECT and normalizes casing."""
        for rec in ["PURSUE", "VALIDATE", "REJECT", "pursue", "Validate", "reject"]:
            with self.subTest(rec=rec):
                kwargs = self._sample_kwargs()
                kwargs["recommendation"] = rec
                record = OpportunityEvaluationRecord(**kwargs)
                self.assertEqual(record.recommendation, rec.upper())

    def test_invalid_recommendation(self) -> None:
        """Invalid recommendation strings raise ValueError or TypeError."""
        for invalid_rec in ["MAYBE", "INVEST", "SKIP", "APPROVE", "", 123, None]:
            with self.subTest(invalid_rec=invalid_rec):
                kwargs = self._sample_kwargs()
                kwargs["recommendation"] = invalid_rec
                with self.assertRaises((ValueError, TypeError)):
                    OpportunityEvaluationRecord(**kwargs)

    def test_invalid_opportunity_id(self) -> None:
        """Empty, whitespace-only, or non-string opportunity_id raises ValueError."""
        for bad_id in ["", "   ", "\t\n", None, 123]:
            with self.subTest(bad_id=bad_id):
                kwargs = self._sample_kwargs()
                kwargs["opportunity_id"] = bad_id
                with self.assertRaises((ValueError, TypeError)):
                    OpportunityEvaluationRecord(**kwargs)

    def test_invalid_rationale(self) -> None:
        """Empty, whitespace-only, or non-string rationale raises ValueError."""
        for bad_rat in ["", "   ", "\t\n", None, 123]:
            with self.subTest(bad_rat=bad_rat):
                kwargs = self._sample_kwargs()
                kwargs["rationale"] = bad_rat
                with self.assertRaises((ValueError, TypeError)):
                    OpportunityEvaluationRecord(**kwargs)

    def test_rejection_reasons_coercion_and_validation(self) -> None:
        """rejection_reasons is coerced to tuple, rejects non-sequences, empty strings, non-strings."""
        kwargs = self._sample_kwargs()

        # Coerced from list to tuple
        kwargs["rejection_reasons"] = ["Market is saturated", "High capex required"]
        record = OpportunityEvaluationRecord(**kwargs)
        self.assertIsInstance(record.rejection_reasons, tuple)
        self.assertEqual(
            record.rejection_reasons,
            ("Market is saturated", "High capex required"),
        )

        # Non-sequence raises TypeError
        kwargs["rejection_reasons"] = "single string reason"
        with self.assertRaises(TypeError):
            OpportunityEvaluationRecord(**kwargs)

        # Sequence containing empty string or whitespace raises ValueError
        kwargs["rejection_reasons"] = ["valid", ""]
        with self.assertRaises(ValueError):
            OpportunityEvaluationRecord(**kwargs)

        kwargs["rejection_reasons"] = ["valid", "   "]
        with self.assertRaises(ValueError):
            OpportunityEvaluationRecord(**kwargs)

        kwargs["rejection_reasons"] = ["valid", 123]
        with self.assertRaises(ValueError):
            OpportunityEvaluationRecord(**kwargs)

    def test_immutability(self) -> None:
        """OpportunityEvaluationRecord is frozen and prohibits field reassignment."""
        record = OpportunityEvaluationRecord(**self._sample_kwargs())

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.overall_score = 90  # type: ignore

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.recommendation = "REJECT"  # type: ignore

    def test_to_dict_method(self) -> None:
        """to_dict serializes all fields into a standard dictionary."""
        record = OpportunityEvaluationRecord(**self._sample_kwargs())
        as_dict = record.to_dict()

        self.assertIsInstance(as_dict, dict)
        self.assertEqual(as_dict["opportunity_id"], "opp-uuid-001")
        self.assertEqual(as_dict["overall_score"], 85)
        self.assertEqual(as_dict["recommendation"], "PURSUE")
        self.assertEqual(as_dict["rejection_reasons"], ())
        self.assertIsNone(as_dict["id"])

    def test_optional_persisted_id(self) -> None:
        """Optional persisted id is None by default, accepts non-empty string, rejects empty string."""
        kwargs = self._sample_kwargs()
        r1 = OpportunityEvaluationRecord(**kwargs)
        self.assertIsNone(r1.id)

        kwargs["id"] = "eval-uuid-123"
        r2 = OpportunityEvaluationRecord(**kwargs)
        self.assertEqual(r2.id, "eval-uuid-123")

        kwargs["id"] = "   "
        with self.assertRaises(ValueError):
            OpportunityEvaluationRecord(**kwargs)


if __name__ == "__main__":
    unittest.main()
