"""Unit tests for AI problem extraction output parser."""

import json
import unittest

from src.problems.models import ProblemRecord
from src.problems.output_parser import (
    ProblemOutputParseError,
    parse_problem_extraction_output,
)


class TestOutputParser(unittest.TestCase):
    """Test suite for parse_problem_extraction_output."""

    def _sample_json_dict(self) -> dict[str, str]:
        """Helper providing a valid 10-field dictionary matching extraction schema."""
        return {
            "problem_title": "Ceramic Electrolyte Microcracking Under Thermal Shock",
            "problem_description": "LLZO solid-state electrolyte undergoes grain boundary fracture during rapid cycling.",
            "affected_users": "Solid-State Battery R&D Engineers",
            "bottleneck_type": "Mechanical Fracture / Thermal Degradation",
            "technical_domain": "Energy Storage / Solid-State Batteries",
            "current_workaround": "Pre-heating battery cells and dampening charge ramp rate",
            "problem_frequency": "occasional",
            "problem_severity": "high",
            "evidence_summary": "Disclosed in comparative fracture toughness charts in Patent Example 4.",
            "evidence_confidence": "high",
        }

    def _sample_json_text(self) -> str:
        """Helper returning valid JSON string."""
        return json.dumps(self._sample_json_dict())

    def test_valid_json_parses_correctly(self) -> None:
        """Valid JSON string parses into a canonical ProblemRecord instance."""
        json_text = self._sample_json_text()
        record = parse_problem_extraction_output(
            response_text=json_text,
            source_patent_numbers=("US11223344B2",),
        )

        self.assertIsInstance(record, ProblemRecord)
        self.assertEqual(record.problem_title, "Ceramic Electrolyte Microcracking Under Thermal Shock")
        self.assertEqual(record.problem_frequency, "occasional")
        self.assertEqual(record.problem_severity, "high")
        self.assertEqual(record.evidence_confidence, "high")

    def test_all_10_fields_are_preserved(self) -> None:
        """All 10 required fields from the JSON payload are preserved in the model."""
        source_data = self._sample_json_dict()
        record = parse_problem_extraction_output(
            response_text=json.dumps(source_data),
            source_patent_numbers=("US11223344B2",),
        )

        self.assertEqual(record.problem_title, source_data["problem_title"])
        self.assertEqual(record.problem_description, source_data["problem_description"])
        self.assertEqual(record.affected_users, source_data["affected_users"])
        self.assertEqual(record.bottleneck_type, source_data["bottleneck_type"])
        self.assertEqual(record.technical_domain, source_data["technical_domain"])
        self.assertEqual(record.current_workaround, source_data["current_workaround"])
        self.assertEqual(record.problem_frequency, source_data["problem_frequency"])
        self.assertEqual(record.problem_severity, source_data["problem_severity"])
        self.assertEqual(record.evidence_summary, source_data["evidence_summary"])
        self.assertEqual(record.evidence_confidence, source_data["evidence_confidence"])

    def test_source_patent_numbers_are_attached(self) -> None:
        """Source patent numbers passed to the parser are attached to the ProblemRecord."""
        record = parse_problem_extraction_output(
            response_text=self._sample_json_text(),
            source_patent_numbers=("US11223344B2",),
        )
        self.assertEqual(record.source_patent_numbers, ("US11223344B2",))

    def test_multiple_source_patents(self) -> None:
        """Multiple source patent numbers are preserved in exact order."""
        patents = ("US11223344B2", "EP3456789A1", "WO2022012345A1")
        record = parse_problem_extraction_output(
            response_text=self._sample_json_text(),
            source_patent_numbers=patents,
        )
        self.assertEqual(record.source_patent_numbers, patents)

    def test_malformed_json(self) -> None:
        """Malformed JSON strings raise ProblemOutputParseError."""
        bad_jsons = [
            "{invalid: json}",
            "not a json object",
            "{'single_quotes': 'not_valid_json'}",
            "",
            "    ",
        ]

        for bad in bad_jsons:
            with self.assertRaises(ProblemOutputParseError, msg=f"Should reject: {bad}"):
                parse_problem_extraction_output(bad, ("US11223344B2",))

    def test_json_array(self) -> None:
        """JSON arrays raise ProblemOutputParseError."""
        array_json = json.dumps([self._sample_json_dict()])
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(array_json, ("US11223344B2",))

    def test_json_primitive(self) -> None:
        """JSON primitives (strings, numbers, booleans, null) raise ProblemOutputParseError."""
        primitives = [
            json.dumps("just a string"),
            json.dumps(12345),
            json.dumps(True),
            json.dumps(None),
        ]

        for prim in primitives:
            with self.assertRaises(ProblemOutputParseError, msg=f"Should reject primitive: {prim}"):
                parse_problem_extraction_output(prim, ("US11223344B2",))

    def test_missing_field(self) -> None:
        """Missing any of the 10 required fields raises ProblemOutputParseError."""
        base_dict = self._sample_json_dict()

        for key in base_dict.keys():
            truncated = dict(base_dict)
            del truncated[key]
            with self.assertRaises(ProblemOutputParseError, msg=f"Should reject missing: {key}"):
                parse_problem_extraction_output(json.dumps(truncated), ("US11223344B2",))

    def test_extra_field(self) -> None:
        """Unexpected extra fields in JSON raise ProblemOutputParseError."""
        with_extra = self._sample_json_dict()
        with_extra["market_size"] = "$10 Billion TAM"

        with self.assertRaises(ProblemOutputParseError) as ctx:
            parse_problem_extraction_output(json.dumps(with_extra), ("US11223344B2",))

        self.assertIn("unexpected extra field", str(ctx.exception).lower())

    def test_non_string_field(self) -> None:
        """Fields with non-string values (numbers, booleans, lists, objects) raise ProblemOutputParseError."""
        base_dict = self._sample_json_dict()

        # Non-string number
        bad_num = dict(base_dict)
        bad_num["problem_severity"] = 1  # type: ignore
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_num), ("US11223344B2",))

        # Non-string list
        bad_list = dict(base_dict)
        bad_list["affected_users"] = ["Battery Engineers", "Pack Designers"]  # type: ignore
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_list), ("US11223344B2",))

    def test_invalid_controlled_value(self) -> None:
        """Invalid controlled values raise ProblemOutputParseError via contract validation."""
        bad_sev = self._sample_json_dict()
        bad_sev["problem_severity"] = "catastrophic"
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_sev), ("US11223344B2",))

        bad_freq = self._sample_json_dict()
        bad_freq["problem_frequency"] = "constantly"
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_freq), ("US11223344B2",))

        bad_conf = self._sample_json_dict()
        bad_conf["evidence_confidence"] = "absolute"
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_conf), ("US11223344B2",))

    def test_empty_required_field(self) -> None:
        """Empty or whitespace-only string values in required fields raise ProblemOutputParseError."""
        bad_title = self._sample_json_dict()
        bad_title["problem_title"] = ""
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_title), ("US11223344B2",))

        bad_desc = self._sample_json_dict()
        bad_desc["problem_description"] = "    \t \n "
        with self.assertRaises(ProblemOutputParseError):
            parse_problem_extraction_output(json.dumps(bad_desc), ("US11223344B2",))

    def test_non_string_response_text_raises_type_error(self) -> None:
        """Non-string response_text input raises TypeError."""
        with self.assertRaises(TypeError):
            parse_problem_extraction_output(None, ("US11223344B2",))  # type: ignore

        with self.assertRaises(TypeError):
            parse_problem_extraction_output({"dict": "input"}, ("US11223344B2",))  # type: ignore

    def test_deterministic_repeated_parsing(self) -> None:
        """Parsing identical inputs returns equal ProblemRecord outputs deterministically."""
        text = self._sample_json_text()
        patents = ("US11223344B2",)

        rec1 = parse_problem_extraction_output(text, patents)
        rec2 = parse_problem_extraction_output(text, patents)

        self.assertEqual(rec1, rec2)
        self.assertEqual(rec1.to_dict(), rec2.to_dict())


if __name__ == "__main__":
    unittest.main()
