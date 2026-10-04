"""Unit tests for AI opportunity evaluation output parser."""

from dataclasses import FrozenInstanceError
import json
import unittest

from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.output_parser import (
    OpportunityEvaluationOutputParseError,
    parse_opportunity_evaluation_output,
)


class TestOpportunityEvaluationOutputParser(unittest.TestCase):
    """Test suite for parse_opportunity_evaluation_output."""

    def _sample_dict(self) -> dict:
        """Helper providing a valid 16-field evaluation dictionary."""
        return {
            "opportunity_id": "opp-uuid-101",
            "overall_score": 86,
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
            "rationale": "High-urgency municipal pain with strong willingness to pay and defensible edge AI IP.",
        }

    def _sample_json_text(self) -> str:
        """Helper returning valid JSON string."""
        return json.dumps(self._sample_dict())

    def test_valid_json_parses_correctly(self) -> None:
        """Valid JSON string parses into a canonical OpportunityEvaluationRecord."""
        record = parse_opportunity_evaluation_output(self._sample_json_text())

        self.assertIsInstance(record, OpportunityEvaluationRecord)
        self.assertEqual(record.opportunity_id, "opp-uuid-101")
        self.assertEqual(record.overall_score, 86)
        self.assertEqual(record.problem_severity_score, 9)
        self.assertEqual(record.frequency_score, 8)
        self.assertEqual(record.rejection_reasons, ())
        self.assertEqual(record.recommendation, "PURSUE")
        self.assertIsNone(record.id)
        self.assertEqual(record.raw_data, {"ai_raw_output": self._sample_dict()})

    def test_returned_record_has_id_none(self) -> None:
        """Returned OpportunityEvaluationRecord explicitly has id=None."""
        record = parse_opportunity_evaluation_output(self._sample_json_text())
        self.assertIsNone(record.id)

    def test_rejection_reasons_is_immutable_tuple(self) -> None:
        """rejection_reasons is stored as an immutable tuple."""
        data = self._sample_dict()
        data["recommendation"] = "REJECT"
        data["rejection_reasons"] = ["Market monopoly by incumbent", "Negative unit economics"]

        record = parse_opportunity_evaluation_output(json.dumps(data))
        self.assertIsInstance(record.rejection_reasons, tuple)
        self.assertEqual(
            record.rejection_reasons,
            ("Market monopoly by incumbent", "Negative unit economics"),
        )

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.rejection_reasons = ("new-reason",)  # type: ignore

    def test_expected_opportunity_id_enforcement(self) -> None:
        """Matching expected_opportunity_id succeeds; mismatch raises parse error."""
        json_text = self._sample_json_text()

        # Matching ID passes
        rec = parse_opportunity_evaluation_output(json_text, expected_opportunity_id="opp-uuid-101")
        self.assertEqual(rec.opportunity_id, "opp-uuid-101")

        # Mismatched ID fails
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json_text, expected_opportunity_id="opp-different-999")
        self.assertIn("contract validation failure", str(ctx.exception).lower())
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_invalid_json(self) -> None:
        """Malformed JSON strings raise parse error with JSON parsing failure message."""
        bad_jsons = [
            "{invalid: json}",
            "not a json object",
            "{'single_quotes': 'invalid'}",
            '{"unclosed": "string}',
        ]
        for bad in bad_jsons:
            with self.subTest(bad=bad):
                with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
                    parse_opportunity_evaluation_output(bad)
                self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_empty_output(self) -> None:
        """Empty or whitespace-only response raises JSON parsing failure."""
        for empty in ["", "   ", "\t\n  "]:
            with self.subTest(empty=repr(empty)):
                with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
                    parse_opportunity_evaluation_output(empty)
                self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_json_array(self) -> None:
        """JSON array raises JSON parsing failure with array mention."""
        array_json = json.dumps([self._sample_dict()])
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(array_json)
        self.assertIn("json parsing failure", str(ctx.exception).lower())
        self.assertIn("array", str(ctx.exception).lower())

    def test_json_primitive(self) -> None:
        """JSON primitives raise JSON parsing failure with primitive mention."""
        for prim in [json.dumps("string"), json.dumps(123), json.dumps(True), json.dumps(None)]:
            with self.subTest(prim=prim):
                with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
                    parse_opportunity_evaluation_output(prim)
                self.assertIn("json parsing failure", str(ctx.exception).lower())
                self.assertIn("primitive", str(ctx.exception).lower())

    def test_missing_field(self) -> None:
        """Missing any required field raises Contract validation failure."""
        base_dict = self._sample_dict()
        for field_name in base_dict.keys():
            with self.subTest(missing_field=field_name):
                truncated = dict(base_dict)
                del truncated[field_name]
                with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
                    parse_opportunity_evaluation_output(json.dumps(truncated))
                self.assertIn("contract validation failure", str(ctx.exception).lower())
                self.assertIn("missing", str(ctx.exception).lower())

    def test_extra_field(self) -> None:
        """Unexpected extra fields in payload raise Contract validation failure."""
        extra_dict = self._sample_dict()
        extra_dict["tam_estimate"] = "$5B"
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(extra_dict))
        self.assertIn("contract validation failure", str(ctx.exception).lower())
        self.assertIn("unexpected", str(ctx.exception).lower())

    def test_score_out_of_range(self) -> None:
        """Score out of allowed range raises Contract validation failure."""
        bad_overall = self._sample_dict()
        bad_overall["overall_score"] = 105
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(bad_overall))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

        bad_dim = self._sample_dict()
        bad_dim["market_gap_score"] = -2
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(bad_dim))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

    def test_boolean_score_rejected(self) -> None:
        """Boolean scores raise Contract validation failure."""
        bad_bool = self._sample_dict()
        bad_bool["overall_score"] = True
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(bad_bool))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

    def test_reject_requires_reasons(self) -> None:
        """Recommendation REJECT without rejection_reasons raises Contract validation failure."""
        data = self._sample_dict()
        data["recommendation"] = "REJECT"
        data["rejection_reasons"] = []
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(data))
        self.assertIn("contract validation failure", str(ctx.exception).lower())
        self.assertIn("reject", str(ctx.exception).lower())

    def test_short_rationale_rejected(self) -> None:
        """Rationale under 15 characters raises Contract validation failure."""
        data = self._sample_dict()
        data["rationale"] = "Too short"
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(json.dumps(data))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

    def test_no_malformed_output_repair(self) -> None:
        """Markdown code blocks and extra text are rejected without repair."""
        valid_json = self._sample_json_text()

        # Markdown wrapped
        markdown_wrapped = f"```json\n{valid_json}\n```"
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(markdown_wrapped)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

        # Preamble text
        preamble = f"Here is the evaluation result:\n{valid_json}"
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(preamble)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

        # Postscript text
        postscript = f"{valid_json}\nHope this helps evaluate!"
        with self.assertRaises(OpportunityEvaluationOutputParseError) as ctx:
            parse_opportunity_evaluation_output(postscript)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_non_string_raw_output_raises_type_error(self) -> None:
        """Non-string raw_output raises TypeError."""
        with self.assertRaises(TypeError):
            parse_opportunity_evaluation_output(None)  # type: ignore

        with self.assertRaises(TypeError):
            parse_opportunity_evaluation_output(self._sample_dict())  # type: ignore


if __name__ == "__main__":
    unittest.main()
