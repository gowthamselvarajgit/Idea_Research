"""Unit tests for Market Research contract and validation rules."""

import unittest

from src.market_research.contract import (
    ALLOWED_RELEVANCE,
    MARKET_RESEARCH_CONTRACT_PRINCIPLES,
    REQUIRED_MARKET_RESEARCH_FIELDS,
    MarketResearchContractValidationError,
    validate_market_research_contract,
    validate_market_research_payload,
    validate_market_research_record,
)
from src.market_research.models import MarketResearchRecord


class TestMarketResearchContract(unittest.TestCase):
    """Test suite for market research contract validation."""

    def _sample_payload(self) -> dict:
        """Helper providing a valid market research dictionary payload."""
        return {
            "opportunity_id": "opp-uuid-201",
            "source_type": "industry_report",
            "source_name": "Gartner Emerging Tech Analysis",
            "source_url": "https://gartner.example.com/reports/edge-drain-robotics-2025",
            "company_or_product": "SewerBot Systems",
            "finding": "SewerBot dominates North American commercial drain inspection with 35% market share.",
            "evidence_summary": "Report notes SewerBot has high vendor lock-in but suffers from high maintenance costs.",
            "relevance": "HIGH",
        }

    def test_principles_and_constants_defined(self) -> None:
        """Contract principles and required fields constants are properly defined."""
        self.assertIsInstance(MARKET_RESEARCH_CONTRACT_PRINCIPLES, str)
        self.assertTrue(len(MARKET_RESEARCH_CONTRACT_PRINCIPLES.strip()) > 100)
        self.assertEqual(len(REQUIRED_MARKET_RESEARCH_FIELDS), 8)
        self.assertIn("opportunity_id", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("source_type", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("source_url", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("company_or_product", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("finding", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("evidence_summary", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertIn("relevance", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertNotIn("id", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertNotIn("raw_data", REQUIRED_MARKET_RESEARCH_FIELDS)
        self.assertEqual(ALLOWED_RELEVANCE, frozenset({"HIGH", "MEDIUM", "LOW"}))

    def test_valid_payload_passes_validation(self) -> None:
        """Valid dictionary payload passes contract validation cleanly."""
        payload = self._sample_payload()
        validate_market_research_payload(payload)
        validate_market_research_contract(payload)

    def test_valid_payload_with_optional_fields(self) -> None:
        """Payload containing optional id and raw_data passes validation."""
        payload = self._sample_payload()
        payload["id"] = "res-uuid-555"
        payload["raw_data"] = {"collected_by": "gemini-researcher"}
        validate_market_research_payload(payload)
        validate_market_research_contract(payload)

    def test_valid_record_passes_validation(self) -> None:
        """Valid MarketResearchRecord instance passes contract validation."""
        payload = self._sample_payload()
        record = MarketResearchRecord(**payload)
        validate_market_research_record(record)
        validate_market_research_contract(record)

    def test_payload_missing_required_fields(self) -> None:
        """Missing any required field raises MarketResearchContractValidationError."""
        for required_field in REQUIRED_MARKET_RESEARCH_FIELDS:
            with self.subTest(missing_field=required_field):
                payload = self._sample_payload()
                del payload[required_field]
                with self.assertRaises(MarketResearchContractValidationError):
                    validate_market_research_payload(payload)

    def test_payload_unexpected_extra_fields(self) -> None:
        """Payload containing unexpected extra keys raises MarketResearchContractValidationError."""
        payload = self._sample_payload()
        payload["unexpected_extra_key"] = "unauthorized_data"
        with self.assertRaises(MarketResearchContractValidationError):
            validate_market_research_payload(payload)

    def test_payload_non_dict_rejected(self) -> None:
        """Non-dictionary payload raises MarketResearchContractValidationError."""
        for invalid_payload in ["string_payload", [1, 2, 3], None, 123]:
            with self.subTest(payload=invalid_payload):
                with self.assertRaises(MarketResearchContractValidationError):
                    validate_market_research_payload(invalid_payload)

    def test_empty_or_whitespace_fields_in_payload(self) -> None:
        """Empty or whitespace values for text fields raise MarketResearchContractValidationError."""
        for field_name in REQUIRED_MARKET_RESEARCH_FIELDS - {"relevance"}:
            for bad_val in ["", "   "]:
                with self.subTest(field=field_name, bad_val=bad_val):
                    payload = self._sample_payload()
                    payload[field_name] = bad_val
                    with self.assertRaises(MarketResearchContractValidationError):
                        validate_market_research_payload(payload)

    def test_invalid_relevance_in_payload(self) -> None:
        """Relevance with invalid value or type raises MarketResearchContractValidationError."""
        for bad_rel in ["INVALID", "CRITICAL", "", 123, None, True]:
            with self.subTest(bad_rel=bad_rel):
                payload = self._sample_payload()
                payload["relevance"] = bad_rel
                with self.assertRaises(MarketResearchContractValidationError):
                    validate_market_research_payload(payload)

    def test_invalid_record_type(self) -> None:
        """validate_market_research_record raises TypeError for non-record instances."""
        with self.assertRaises(TypeError):
            validate_market_research_record("not_a_record")  # type: ignore

    def test_unified_contract_dispatcher_invalid_type(self) -> None:
        """validate_market_research_contract raises MarketResearchContractValidationError on unsupported types."""
        with self.assertRaises(MarketResearchContractValidationError):
            validate_market_research_contract(["invalid", "type"])


if __name__ == "__main__":
    unittest.main()
