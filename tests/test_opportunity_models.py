"""Unit tests for OpportunityRecord data model and AI synthesis contract validation."""

from dataclasses import FrozenInstanceError
import unittest

from src.opportunities.models import (
    REQUIRED_OPPORTUNITY_TEXT_FIELDS,
    OpportunityRecord,
)
from src.opportunities.opportunity_contract import (
    BANNED_GENERIC_CUSTOMERS,
    REQUIRED_AI_FIELDS,
    REQUIRED_OPPORTUNITY_AI_FIELDS,
    OpportunityContractValidationError,
    validate_opportunity_ai_output,
    validate_opportunity_contract,
    validate_opportunity_record,
)


class TestOpportunityRecord(unittest.TestCase):
    """Test suite for immutable OpportunityRecord dataclass and its domain rules."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for OpportunityRecord."""
        return {
            "opportunity_title": "Autonomous Industrial Drain Inspection Robotics",
            "solution_concept": "ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
            "target_customer": "Municipal Water Authorities and Industrial Plant EHS Managers",
            "value_proposition": "Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
            "source_problem_ids": ("08bc07f5-3a40-409b-a592-7c95b2012c78",),
            "raw_data": {"market_segment": "industrial_safety"},
        }

    def test_valid_construction(self) -> None:
        """OpportunityRecord constructs successfully with valid arguments."""
        kwargs = self._sample_kwargs()
        record = OpportunityRecord(**kwargs)

        self.assertEqual(record.opportunity_title, kwargs["opportunity_title"])
        self.assertEqual(record.solution_concept, kwargs["solution_concept"])
        self.assertEqual(record.target_customer, kwargs["target_customer"])
        self.assertEqual(record.value_proposition, kwargs["value_proposition"])
        self.assertEqual(record.source_problem_ids, kwargs["source_problem_ids"])
        self.assertIsNone(record.id)
        self.assertEqual(record.raw_data, kwargs["raw_data"])

    def test_default_id_none(self) -> None:
        """id defaults to None when not provided."""
        record = OpportunityRecord(**self._sample_kwargs())
        self.assertIsNone(record.id)

    def test_valid_persisted_id(self) -> None:
        """Persisted UUID is accepted and accessible on OpportunityRecord."""
        kwargs = self._sample_kwargs()
        kwargs["id"] = "e2c07a3f-14f7-418e-9ea1-9238e8ec438b"
        record = OpportunityRecord(**kwargs)

        self.assertEqual(record.id, "e2c07a3f-14f7-418e-9ea1-9238e8ec438b")

    def test_invalid_or_empty_id(self) -> None:
        """Empty string or non-string id raises ValueError."""
        kwargs = self._sample_kwargs()

        kwargs["id"] = ""
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["id"] = "   "
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["id"] = 12345
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

    def test_invalid_text_fields(self) -> None:
        """Every required text field rejects empty strings, whitespace, and None."""
        for field_name in REQUIRED_OPPORTUNITY_TEXT_FIELDS:
            for invalid in ["", "   ", None, 123]:
                with self.subTest(field=field_name, invalid_val=invalid):
                    kwargs = self._sample_kwargs()
                    kwargs[field_name] = invalid
                    with self.assertRaises(ValueError):
                        OpportunityRecord(**kwargs)

    def test_empty_source_problem_ids(self) -> None:
        """Empty tuple or list for source_problem_ids raises ValueError."""
        kwargs = self._sample_kwargs()

        kwargs["source_problem_ids"] = ()
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["source_problem_ids"] = []
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["source_problem_ids"] = None
        with self.assertRaises(TypeError):
            OpportunityRecord(**kwargs)

    def test_invalid_source_problem_ids(self) -> None:
        """Sequences containing empty strings or whitespace entries raise ValueError."""
        kwargs = self._sample_kwargs()

        kwargs["source_problem_ids"] = ("valid-id-1", "")
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["source_problem_ids"] = ("valid-id-1", "   ")
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

        kwargs["source_problem_ids"] = ("valid-id-1", 123)
        with self.assertRaises(ValueError):
            OpportunityRecord(**kwargs)

    def test_source_problem_ids_coerced_to_tuple(self) -> None:
        """List passed to source_problem_ids is safely coerced to an immutable tuple."""
        kwargs = self._sample_kwargs()
        kwargs["source_problem_ids"] = ["id-1", "id-2"]
        record = OpportunityRecord(**kwargs)

        self.assertIsInstance(record.source_problem_ids, tuple)
        self.assertEqual(record.source_problem_ids, ("id-1", "id-2"))

    def test_immutability(self) -> None:
        """OpportunityRecord is frozen and raises FrozenInstanceError on modification."""
        record = OpportunityRecord(**self._sample_kwargs())

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.opportunity_title = "New Title"  # type: ignore

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            record.id = "new-id"  # type: ignore

    def test_to_dict_method(self) -> None:
        """to_dict serializes all fields properly."""
        record = OpportunityRecord(**self._sample_kwargs())
        as_dict = record.to_dict()

        self.assertIsInstance(as_dict, dict)
        self.assertEqual(as_dict["opportunity_title"], record.opportunity_title)
        self.assertEqual(as_dict["solution_concept"], record.solution_concept)
        self.assertEqual(as_dict["target_customer"], record.target_customer)
        self.assertEqual(as_dict["value_proposition"], record.value_proposition)
        self.assertEqual(as_dict["source_problem_ids"], record.source_problem_ids)
        self.assertIsNone(as_dict["id"])

    def test_contract_validation(self) -> None:
        """validate_opportunity_record validates contract rules."""
        valid_record = OpportunityRecord(**self._sample_kwargs())
        validate_opportunity_record(valid_record)

        # Non-record raises TypeError
        with self.assertRaises(TypeError):
            validate_opportunity_record({"not": "a record"})  # type: ignore


class TestOpportunitySynthesisContract(unittest.TestCase):
    """Test suite strictly validating the AI synthesis contract for opportunities."""

    def _sample_ai_payload(self) -> dict:
        """Helper providing a valid AI synthesis output dictionary."""
        return {
            "opportunity_title": "AI Autonomous Industrial Drain Inspection Robotics",
            "solution_concept": "ESP-32 equipped micro-crawlers with multi-gas detection for hazardous sewer lines.",
            "target_customer": "Municipal Water Authorities and Industrial Plant EHS Managers",
            "value_proposition": "Eliminates human entry into toxic confined spaces while cutting inspection labor costs by 60%.",
            "source_problem_ids": ["08bc07f5-3a40-409b-a592-7c95b2012c78"],
        }

    def test_constants_defined(self) -> None:
        """Required AI output fields constant is properly defined."""
        expected = {
            "opportunity_title",
            "solution_concept",
            "target_customer",
            "value_proposition",
            "source_problem_ids",
        }
        self.assertEqual(REQUIRED_OPPORTUNITY_AI_FIELDS, expected)
        self.assertEqual(REQUIRED_AI_FIELDS, expected)
        self.assertNotIn("id", REQUIRED_OPPORTUNITY_AI_FIELDS)
        self.assertNotIn("raw_data", REQUIRED_OPPORTUNITY_AI_FIELDS)

    def test_valid_contract_output(self) -> None:
        """Valid AI output payload passes contract validation cleanly."""
        payload = self._sample_ai_payload()
        # Should not raise
        validate_opportunity_ai_output(payload)
        validate_opportunity_contract(payload)

    def test_missing_field(self) -> None:
        """Missing any required field raises OpportunityContractValidationError."""
        for field_name in REQUIRED_OPPORTUNITY_AI_FIELDS:
            with self.subTest(missing_field=field_name):
                payload = self._sample_ai_payload()
                del payload[field_name]
                with self.assertRaises(OpportunityContractValidationError):
                    validate_opportunity_ai_output(payload)

    def test_extra_field(self) -> None:
        """Presence of unexpected fields (including id or raw_data) raises OpportunityContractValidationError."""
        unexpected_candidates = ["id", "raw_data", "market_tam", "unsupported_field"]
        for extra in unexpected_candidates:
            with self.subTest(extra_field=extra):
                payload = self._sample_ai_payload()
                payload[extra] = "unexpected_value"
                with self.assertRaises(OpportunityContractValidationError):
                    validate_opportunity_ai_output(payload)

    def test_wrong_field_type(self) -> None:
        """Fields with incorrect types raise OpportunityContractValidationError."""
        # Text fields given non-string types
        text_fields = ["opportunity_title", "solution_concept", "target_customer", "value_proposition"]
        for field_name in text_fields:
            for bad_val in [12345, True, False, ["list"], {"key": "val"}, None]:
                with self.subTest(field=field_name, bad_type=type(bad_val)):
                    payload = self._sample_ai_payload()
                    payload[field_name] = bad_val
                    with self.assertRaises(OpportunityContractValidationError):
                        validate_opportunity_ai_output(payload)

        # source_problem_ids given string instead of list/tuple
        payload = self._sample_ai_payload()
        payload["source_problem_ids"] = "08bc07f5-3a40-409b-a592-7c95b2012c78"
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

    def test_empty_strings(self) -> None:
        """Empty or whitespace-only text fields raise OpportunityContractValidationError."""
        text_fields = ["opportunity_title", "solution_concept", "target_customer", "value_proposition"]
        for field_name in text_fields:
            for empty_val in ["", "   ", "\t\n  "]:
                with self.subTest(field=field_name, val=repr(empty_val)):
                    payload = self._sample_ai_payload()
                    payload[field_name] = empty_val
                    with self.assertRaises(OpportunityContractValidationError):
                        validate_opportunity_ai_output(payload)

    def test_invalid_source_problem_ids(self) -> None:
        """Empty sequence, non-string items, or whitespace IDs raise OpportunityContractValidationError."""
        payload = self._sample_ai_payload()

        # Empty list
        payload["source_problem_ids"] = []
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # Empty tuple
        payload["source_problem_ids"] = ()
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # List containing empty string or whitespace
        payload["source_problem_ids"] = ["valid-id", ""]
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        payload["source_problem_ids"] = ["valid-id", "   "]
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # List containing non-string items
        payload["source_problem_ids"] = ["valid-id", 123]
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

    def test_valid_multiple_source_problem_ids(self) -> None:
        """Multiple valid source problem IDs are accepted in list or tuple form."""
        payload = self._sample_ai_payload()
        payload["source_problem_ids"] = [
            "prob-uuid-001",
            "prob-uuid-002",
            "prob-uuid-003",
        ]
        validate_opportunity_ai_output(payload)

        # Also accepts tuple
        payload["source_problem_ids"] = ("prob-uuid-001", "prob-uuid-002")
        validate_opportunity_ai_output(payload)

    def test_semantic_minimum_content_failures(self) -> None:
        """Semantic minimum-content and generic customer catch-alls fail contract validation."""
        payload = self._sample_ai_payload()

        # Title too short (< 5 chars)
        payload["opportunity_title"] = "AI"
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # Solution concept too short (< 10 chars)
        payload = self._sample_ai_payload()
        payload["solution_concept"] = "Robots."
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # Value proposition too short (< 10 chars)
        payload = self._sample_ai_payload()
        payload["value_proposition"] = "Saves $$"
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # Target customer too short (< 3 chars)
        payload = self._sample_ai_payload()
        payload["target_customer"] = "EV"
        with self.assertRaises(OpportunityContractValidationError):
            validate_opportunity_ai_output(payload)

        # Target customer vague / catch-all
        for vague in ["everyone", "businesses", "consumers", "users", "anyone", "all businesses"]:
            with self.subTest(vague_customer=vague):
                payload = self._sample_ai_payload()
                payload["target_customer"] = vague
                with self.assertRaises(OpportunityContractValidationError):
                    validate_opportunity_ai_output(payload)


if __name__ == "__main__":
    unittest.main()
