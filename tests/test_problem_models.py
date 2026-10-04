"""Unit tests for ProblemRecord data model and validation."""

from dataclasses import FrozenInstanceError
import unittest

from src.problems.models import REQUIRED_TEXT_FIELDS, ProblemRecord


class TestProblemRecord(unittest.TestCase):
    """Test suite for immutable ProblemRecord dataclass."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for ProblemRecord."""
        return {
            "problem_title": "Electrolyte Dendrite Growth at High Current Density",
            "problem_description": "Lithium dendrites penetrate solid state ceramic separators during fast charging.",
            "affected_users": "EV Battery Pack Engineers and Cell Manufacturers",
            "bottleneck_type": "Material Degradation / Dendrite Formation",
            "technical_domain": "Energy Storage / Solid-State Batteries",
            "current_workaround": "Thick lithium layers or reduced charging current densities",
            "problem_frequency": "High under fast-charging conditions",
            "problem_severity": "Critical (Causes internal short circuit and fire hazard)",
            "evidence_summary": "Documented in claims and experimental microstructures across cited patents.",
            "evidence_confidence": "High",
            "source_patent_numbers": ("US11223344B2",),
            "raw_data": {"extracted_entities": ["dendrite", "lithium metal"]},
        }

    def test_valid_construction(self) -> None:
        """ProblemRecord constructs successfully with valid arguments."""
        kwargs = self._sample_kwargs()
        problem = ProblemRecord(**kwargs)

        self.assertEqual(problem.problem_title, kwargs["problem_title"])
        self.assertEqual(problem.problem_description, kwargs["problem_description"])
        self.assertEqual(problem.affected_users, kwargs["affected_users"])
        self.assertEqual(problem.bottleneck_type, kwargs["bottleneck_type"])
        self.assertEqual(problem.technical_domain, kwargs["technical_domain"])
        self.assertEqual(problem.current_workaround, kwargs["current_workaround"])
        self.assertEqual(problem.problem_frequency, kwargs["problem_frequency"])
        self.assertEqual(problem.problem_severity, kwargs["problem_severity"])
        self.assertEqual(problem.evidence_summary, kwargs["evidence_summary"])
        self.assertEqual(problem.evidence_confidence, kwargs["evidence_confidence"])
        self.assertEqual(problem.source_patent_numbers, ("US11223344B2",))
        self.assertEqual(problem.raw_data, {"extracted_entities": ["dendrite", "lithium metal"]})

    def test_immutability(self) -> None:
        """ProblemRecord is frozen and prohibits modifying fields."""
        problem = ProblemRecord(**self._sample_kwargs())

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            problem.problem_title = "Modified Title"  # type: ignore

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            problem.source_patent_numbers = ("EP9999999A1",)  # type: ignore

    def test_required_text_field_validation(self) -> None:
        """Every required text field rejects empty strings, whitespace-only, and None."""
        base_kwargs = self._sample_kwargs()

        for field_name in REQUIRED_TEXT_FIELDS:
            # Test empty string
            bad_kwargs_empty = dict(base_kwargs)
            bad_kwargs_empty[field_name] = ""
            with self.assertRaises(ValueError, msg=f"Field {field_name} should reject empty string"):
                ProblemRecord(**bad_kwargs_empty)

            # Test whitespace-only string
            bad_kwargs_ws = dict(base_kwargs)
            bad_kwargs_ws[field_name] = "   \t\n  "
            with self.assertRaises(ValueError, msg=f"Field {field_name} should reject whitespace-only"):
                ProblemRecord(**bad_kwargs_ws)

            # Test None or non-string
            bad_kwargs_none = dict(base_kwargs)
            bad_kwargs_none[field_name] = None  # type: ignore
            with self.assertRaises(ValueError, msg=f"Field {field_name} should reject None"):
                ProblemRecord(**bad_kwargs_none)

    def test_tuple_handling(self) -> None:
        """source_patent_numbers is guaranteed to be a tuple regardless of input list/tuple."""
        kwargs = self._sample_kwargs()

        # Passed as tuple
        kwargs["source_patent_numbers"] = ("US11223344B2", "EP3456789A1")
        problem_tuple = ProblemRecord(**kwargs)
        self.assertIsInstance(problem_tuple.source_patent_numbers, tuple)
        self.assertEqual(problem_tuple.source_patent_numbers, ("US11223344B2", "EP3456789A1"))

        # Passed as list -> safely converted to tuple
        kwargs["source_patent_numbers"] = ["US11223344B2", "EP3456789A1"]
        problem_list = ProblemRecord(**kwargs)
        self.assertIsInstance(problem_list.source_patent_numbers, tuple)
        self.assertEqual(problem_list.source_patent_numbers, ("US11223344B2", "EP3456789A1"))

        # Non-sequence raises TypeError
        kwargs["source_patent_numbers"] = 12345  # type: ignore
        with self.assertRaises(TypeError):
            ProblemRecord(**kwargs)

    def test_raw_data_preservation_and_default(self) -> None:
        """raw_data defaults safely to empty dict and preserves arbitrary nested dictionaries."""
        kwargs = self._sample_kwargs()
        del kwargs["raw_data"]

        # Default value
        problem_default = ProblemRecord(**kwargs)
        self.assertEqual(problem_default.raw_data, {})

        # Preserves nested structure
        nested_data = {
            "source_model": "gemini-1.5-pro",
            "scores": {"relevance": 0.95, "bottleneck_depth": 0.88},
            "citations": ["claim 1", "fig 3"],
        }
        kwargs["raw_data"] = nested_data
        problem_nested = ProblemRecord(**kwargs)
        self.assertEqual(problem_nested.raw_data, nested_data)

        # Invalid raw_data type
        kwargs["raw_data"] = ["not", "a", "dict"]  # type: ignore
        with self.assertRaises(TypeError):
            ProblemRecord(**kwargs)

    def test_multiple_source_patents(self) -> None:
        """Problems can synthesize findings across multiple canonical patent numbers."""
        kwargs = self._sample_kwargs()
        kwargs["source_patent_numbers"] = (
            "US11223344B2",
            "EP3456789A1",
            "WO2022123456A1",
        )
        problem = ProblemRecord(**kwargs)

        self.assertEqual(len(problem.source_patent_numbers), 3)
        self.assertEqual(
            problem.source_patent_numbers,
            ("US11223344B2", "EP3456789A1", "WO2022123456A1"),
        )

    def test_empty_or_invalid_source_patent_numbers(self) -> None:
        """Empty tuple/list or invalid patent entries raise appropriate errors."""
        kwargs = self._sample_kwargs()

        # Empty tuple
        kwargs["source_patent_numbers"] = ()
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)

        # Empty list
        kwargs["source_patent_numbers"] = []
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)

        # Sequence containing empty string or whitespace
        kwargs["source_patent_numbers"] = ("US11223344B2", "")
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)

        kwargs["source_patent_numbers"] = ("US11223344B2", "   ")
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)

    def test_to_dict_method(self) -> None:
        """to_dict serializes all ProblemRecord fields into a standard dictionary."""
        problem = ProblemRecord(**self._sample_kwargs())
        as_dict = problem.to_dict()

        self.assertIsInstance(as_dict, dict)
        self.assertEqual(as_dict["problem_title"], problem.problem_title)
        self.assertEqual(as_dict["source_patent_numbers"], ("US11223344B2",))
        self.assertEqual(as_dict["raw_data"], problem.raw_data)
        self.assertIsNone(as_dict["id"])

    def test_optional_id_attribute(self) -> None:
        """Optional id field defaults to None, accepts valid UUID, and rejects empty strings."""
        kwargs = self._sample_kwargs()
        p_no_id = ProblemRecord(**kwargs)
        self.assertIsNone(p_no_id.id)

        kwargs["id"] = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        p_with_id = ProblemRecord(**kwargs)
        self.assertEqual(p_with_id.id, "f47ac10b-58cc-4372-a567-0e02b2c3d479")

        # Empty string / whitespace rejects
        kwargs["id"] = ""
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)

        kwargs["id"] = "   "
        with self.assertRaises(ValueError):
            ProblemRecord(**kwargs)


if __name__ == "__main__":
    unittest.main()
