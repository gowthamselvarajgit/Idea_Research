"""Unit tests for WebResearchSource contract validation."""

import unittest

from src.market_research.source_contract import (
    ALLOWED_SOURCE_TYPES,
    REQUIRED_SOURCE_FIELDS,
    WebResearchSourceContractValidationError,
    validate_web_research_source_contract,
    validate_web_research_source_payload,
    validate_web_research_source_record,
)
from src.market_research.source_models import WebResearchSource


class TestWebResearchSourceContract(unittest.TestCase):
    """Test suite for WebResearchSource contract enforcement."""

    def _sample_payload(self) -> dict:
        """Helper returning a valid web research source dictionary payload."""
        return {
            "url": "https://industry-review.example.com/crawlers-2025",
            "title": "State of Sewer Inspection Robotics in 2025",
            "source_type": "industry",
            "publisher_or_domain": "industry-review.example.com",
            "retrieved_content": "Extensive overview of robotic crawl platforms and market adoption rates.",
            "retrieved_at": "2026-10-06T19:30:00Z",
        }

    def test_constants_defined(self) -> None:
        """Contract constants are properly defined."""
        self.assertEqual(len(REQUIRED_SOURCE_FIELDS), 6)
        self.assertIn("url", REQUIRED_SOURCE_FIELDS)
        self.assertIn("title", REQUIRED_SOURCE_FIELDS)
        self.assertIn("source_type", REQUIRED_SOURCE_FIELDS)
        self.assertIn("publisher_or_domain", REQUIRED_SOURCE_FIELDS)
        self.assertIn("retrieved_content", REQUIRED_SOURCE_FIELDS)
        self.assertIn("retrieved_at", REQUIRED_SOURCE_FIELDS)
        self.assertNotIn("id", REQUIRED_SOURCE_FIELDS)
        self.assertNotIn("raw_data", REQUIRED_SOURCE_FIELDS)
        self.assertEqual(len(ALLOWED_SOURCE_TYPES), 8)

    def test_valid_payload_passes_validation(self) -> None:
        """Valid payload passes contract validation cleanly."""
        payload = self._sample_payload()
        validate_web_research_source_payload(payload)
        validate_web_research_source_contract(payload)

    def test_valid_payload_with_optional_fields(self) -> None:
        """Payload with valid optional id and raw_data passes validation."""
        payload = self._sample_payload()
        payload["id"] = "src-uuid-101"
        payload["raw_data"] = {"scraper": "custom_extractor"}
        validate_web_research_source_payload(payload)
        validate_web_research_source_contract(payload)

    def test_valid_record_passes_validation(self) -> None:
        """Valid WebResearchSource instance passes contract validation."""
        payload = self._sample_payload()
        source = WebResearchSource(**payload)
        validate_web_research_source_record(source)
        validate_web_research_source_contract(source)

    def test_missing_required_fields_rejected(self) -> None:
        """Missing any required field raises WebResearchSourceContractValidationError."""
        for required_key in REQUIRED_SOURCE_FIELDS:
            with self.subTest(missing_key=required_key):
                payload = self._sample_payload()
                del payload[required_key]
                with self.assertRaises(WebResearchSourceContractValidationError):
                    validate_web_research_source_payload(payload)

    def test_unexpected_extra_fields_rejected(self) -> None:
        """Payload containing unexpected extra fields raises WebResearchSourceContractValidationError."""
        payload = self._sample_payload()
        payload["unexpected_extra_field"] = "unexpected_data"
        with self.assertRaises(WebResearchSourceContractValidationError):
            validate_web_research_source_payload(payload)

    def test_empty_or_whitespace_fields_rejected(self) -> None:
        """Empty or whitespace-only field values raise WebResearchSourceContractValidationError."""
        for field_name in REQUIRED_SOURCE_FIELDS:
            for bad_val in ["", "   "]:
                with self.subTest(field=field_name, bad_val=bad_val):
                    payload = self._sample_payload()
                    payload[field_name] = bad_val
                    with self.assertRaises(WebResearchSourceContractValidationError):
                        validate_web_research_source_payload(payload)

    def test_invalid_source_type_rejected(self) -> None:
        """Disallowed source_type values raise WebResearchSourceContractValidationError."""
        for bad_st in ["invalid", "forum", "wiki", 123, None]:
            with self.subTest(bad_st=bad_st):
                payload = self._sample_payload()
                payload["source_type"] = bad_st
                with self.assertRaises(WebResearchSourceContractValidationError):
                    validate_web_research_source_payload(payload)

    def test_non_dict_payload_rejected(self) -> None:
        """Non-dictionary payload raises WebResearchSourceContractValidationError."""
        for invalid_payload in ["string", [1, 2], None, 123]:
            with self.subTest(payload=invalid_payload):
                with self.assertRaises(WebResearchSourceContractValidationError):
                    validate_web_research_source_payload(invalid_payload)

    def test_invalid_record_type_rejected(self) -> None:
        """validate_web_research_source_record raises TypeError on non-record input."""
        with self.assertRaises(TypeError):
            validate_web_research_source_record("not-a-source")  # type: ignore

    def test_contract_dispatcher_invalid_type(self) -> None:
        """validate_web_research_source_contract raises error on unsupported type."""
        with self.assertRaises(WebResearchSourceContractValidationError):
            validate_web_research_source_contract(["unsupported", "list"])


if __name__ == "__main__":
    unittest.main()
