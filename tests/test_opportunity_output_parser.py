"""Unit tests for AI opportunity synthesis output parser."""

from dataclasses import FrozenInstanceError
import json
import unittest

from src.opportunities.models import OpportunityRecord
from src.opportunities.output_parser import (
    OpportunityOutputParseError,
    parse_opportunity_synthesis_output,
)


class TestOpportunityOutputParser(unittest.TestCase):
    """Test suite for parse_opportunity_synthesis_output."""

    def _sample_dict(self) -> dict:
        """Helper providing a valid 5-field dictionary matching synthesis schema."""
        return {
            "opportunity_title": "AI Autonomous Industrial Drain Inspection Robotics",
            "solution_concept": "ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
            "target_customer": "Municipal Water Authorities and Industrial Plant EHS Managers",
            "value_proposition": "Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
            "source_problem_ids": ["08bc07f5-3a40-409b-a592-7c95b2012c78"],
        }

    def _sample_json_text(self) -> str:
        """Helper returning valid JSON string."""
        return json.dumps(self._sample_dict())

    def test_valid_json_parses_correctly(self) -> None:
        """Valid JSON string parses into a canonical OpportunityRecord instance."""
        json_text = self._sample_json_text()
        record = parse_opportunity_synthesis_output(json_text)

        self.assertIsInstance(record, OpportunityRecord)
        self.assertEqual(record.opportunity_title, "AI Autonomous Industrial Drain Inspection Robotics")
        self.assertEqual(
            record.solution_concept,
            "ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
        )
        self.assertEqual(
            record.target_customer,
            "Municipal Water Authorities and Industrial Plant EHS Managers",
        )
        self.assertEqual(
            record.value_proposition,
            "Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
        )
        self.assertEqual(
            record.source_problem_ids,
            ("08bc07f5-3a40-409b-a592-7c95b2012c78",),
        )
        self.assertIsNone(record.id)
        self.assertEqual(record.raw_data, {"ai_raw_output": self._sample_dict()})

    def test_valid_multiple_source_problem_ids(self) -> None:
        """Multiple source problem IDs are parsed and preserved as an immutable tuple."""
        data = self._sample_dict()
        data["source_problem_ids"] = [
            "prob-uuid-001",
            "prob-uuid-002",
            "prob-uuid-003",
        ]
        record = parse_opportunity_synthesis_output(json.dumps(data))

        self.assertEqual(
            record.source_problem_ids,
            ("prob-uuid-001", "prob-uuid-002", "prob-uuid-003"),
        )
        self.assertIsInstance(record.source_problem_ids, tuple)

    def test_returned_record_has_id_none(self) -> None:
        """Returned OpportunityRecord explicitly has id=None."""
        record = parse_opportunity_synthesis_output(self._sample_json_text())
        self.assertIsNone(record.id)

    def test_returned_source_problem_ids_is_immutable(self) -> None:
        """Returned source_problem_ids is an immutable tuple and cannot be modified."""
        record = parse_opportunity_synthesis_output(self._sample_json_text())
        self.assertIsInstance(record.source_problem_ids, tuple)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.source_problem_ids = ("another-id",)  # type: ignore

    def test_invalid_json(self) -> None:
        """Malformed JSON strings raise OpportunityOutputParseError with JSON parsing failure message."""
        bad_jsons = [
            "{invalid: json}",
            "not a json object",
            "{'single_quotes': 'not_valid_json'}",
            '{"unclosed": "string}',
        ]
        for bad in bad_jsons:
            with self.subTest(bad_json=bad):
                with self.assertRaises(OpportunityOutputParseError) as ctx:
                    parse_opportunity_synthesis_output(bad)
                self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_empty_output(self) -> None:
        """Empty or whitespace-only output raises OpportunityOutputParseError."""
        for empty_text in ["", "   ", "\t\n  "]:
            with self.subTest(empty_output=repr(empty_text)):
                with self.assertRaises(OpportunityOutputParseError) as ctx:
                    parse_opportunity_synthesis_output(empty_text)
                self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_json_array(self) -> None:
        """JSON arrays raise OpportunityOutputParseError with JSON parsing failure."""
        array_json = json.dumps([self._sample_dict()])
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(array_json)
        self.assertIn("json parsing failure", str(ctx.exception).lower())
        self.assertIn("array", str(ctx.exception).lower())

    def test_json_primitive(self) -> None:
        """JSON primitives raise OpportunityOutputParseError with JSON parsing failure."""
        primitives = [
            json.dumps("just a string"),
            json.dumps(12345),
            json.dumps(True),
            json.dumps(None),
        ]
        for prim in primitives:
            with self.subTest(primitive=prim):
                with self.assertRaises(OpportunityOutputParseError) as ctx:
                    parse_opportunity_synthesis_output(prim)
                self.assertIn("json parsing failure", str(ctx.exception).lower())
                self.assertIn("primitive", str(ctx.exception).lower())

    def test_missing_field(self) -> None:
        """Missing any required field raises OpportunityOutputParseError with contract validation failure."""
        base_dict = self._sample_dict()
        for field_name in base_dict.keys():
            with self.subTest(missing_field=field_name):
                truncated = dict(base_dict)
                del truncated[field_name]
                with self.assertRaises(OpportunityOutputParseError) as ctx:
                    parse_opportunity_synthesis_output(json.dumps(truncated))
                self.assertIn("contract validation failure", str(ctx.exception).lower())
                self.assertIn("missing", str(ctx.exception).lower())

    def test_extra_field(self) -> None:
        """Unexpected extra fields in JSON raise OpportunityOutputParseError with contract validation failure."""
        extra_dict = self._sample_dict()
        extra_dict["market_size"] = "$10 Billion TAM"
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(extra_dict))
        self.assertIn("contract validation failure", str(ctx.exception).lower())
        self.assertIn("unexpected", str(ctx.exception).lower())

    def test_persistence_fields_rejected_as_ai_output(self) -> None:
        """Persistence fields 'id' and 'raw_data' are rejected as unexpected AI output fields."""
        for persistence_field in ["id", "raw_data"]:
            with self.subTest(persistence_field=persistence_field):
                data = self._sample_dict()
                data[persistence_field] = "persisted-val"
                with self.assertRaises(OpportunityOutputParseError) as ctx:
                    parse_opportunity_synthesis_output(json.dumps(data))
                self.assertIn("contract validation failure", str(ctx.exception).lower())
                self.assertIn("unexpected", str(ctx.exception).lower())

    def test_wrong_field_type(self) -> None:
        """Fields with incorrect basic types raise OpportunityOutputParseError."""
        # Non-string text field
        bad_num = self._sample_dict()
        bad_num["opportunity_title"] = 12345
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(bad_num))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

        # Non-list source_problem_ids
        bad_pids = self._sample_dict()
        bad_pids["source_problem_ids"] = "08bc07f5-3a40-409b-a592-7c95b2012c78"
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(bad_pids))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

    def test_invalid_source_problem_ids(self) -> None:
        """Empty sequence, non-string entries, or whitespace problem IDs raise OpportunityOutputParseError."""
        # Empty list
        bad_empty = self._sample_dict()
        bad_empty["source_problem_ids"] = []
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(bad_empty))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

        # Whitespace / empty string entry
        bad_ws = self._sample_dict()
        bad_ws["source_problem_ids"] = ["valid-id", "   "]
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(bad_ws))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

        # Non-string entry
        bad_int = self._sample_dict()
        bad_int["source_problem_ids"] = ["valid-id", 999]
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(json.dumps(bad_int))
        self.assertIn("contract validation failure", str(ctx.exception).lower())

    def test_no_malformed_output_repair(self) -> None:
        """Markdown code blocks or text before/after JSON are rejected and NOT repaired."""
        valid_json = self._sample_json_text()

        # Markdown wrapped
        markdown_wrapped = f"```json\n{valid_json}\n```"
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(markdown_wrapped)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

        # Commentary before JSON
        preamble_text = f"Here is the synthesized opportunity:\n{valid_json}"
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(preamble_text)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

        # Postscript after JSON
        postscript_text = f"{valid_json}\nHope this helps!"
        with self.assertRaises(OpportunityOutputParseError) as ctx:
            parse_opportunity_synthesis_output(postscript_text)
        self.assertIn("json parsing failure", str(ctx.exception).lower())

    def test_non_string_raw_output_raises_type_error(self) -> None:
        """Passing non-string to parse_opportunity_synthesis_output raises TypeError."""
        with self.assertRaises(TypeError):
            parse_opportunity_synthesis_output(None)  # type: ignore

        with self.assertRaises(TypeError):
            parse_opportunity_synthesis_output(self._sample_dict())  # type: ignore


if __name__ == "__main__":
    unittest.main()
