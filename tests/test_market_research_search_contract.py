"""Unit tests for SearchResult contract validation."""

import unittest

from src.market_research.search_contract import (
    ALL_SEARCH_RESULT_FIELDS,
    REQUIRED_SEARCH_RESULT_FIELDS,
    SearchResultContractValidationError,
    validate_search_result_contract,
    validate_search_result_payload,
    validate_search_result_record,
)
from src.market_research.search_models import SearchResult


class TestSearchResultContract(unittest.TestCase):
    """Test suite for SearchResult contract enforcement."""

    def _sample_payload(self) -> dict:
        """Helper providing a valid search result payload dictionary."""
        return {
            "url": "https://drainrobo.example.com/products/crawler",
            "title": "DrainRobo Inspection Crawler Specifications",
            "snippet": "Leading autonomous microcrawler designed for commercial pipe lines.",
            "domain": "drainrobo.example.com",
        }

    def test_constants_defined(self) -> None:
        """Contract constants are properly defined."""
        self.assertEqual(len(REQUIRED_SEARCH_RESULT_FIELDS), 4)
        self.assertIn("url", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertIn("title", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertIn("snippet", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertIn("domain", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertNotIn("id", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertNotIn("raw_data", REQUIRED_SEARCH_RESULT_FIELDS)
        self.assertEqual(len(ALL_SEARCH_RESULT_FIELDS), 6)

    def test_valid_payload_passes_validation(self) -> None:
        """Valid search result payload passes validation cleanly."""
        payload = self._sample_payload()
        validate_search_result_payload(payload)
        validate_search_result_contract(payload)

    def test_valid_payload_with_optional_fields(self) -> None:
        """Payload with valid optional id and raw_data passes validation."""
        payload = self._sample_payload()
        payload["id"] = "sr-uuid-001"
        payload["raw_data"] = {"rank": 1}
        validate_search_result_payload(payload)
        validate_search_result_contract(payload)

    def test_valid_record_passes_validation(self) -> None:
        """Valid SearchResult record instance passes contract validation."""
        payload = self._sample_payload()
        record = SearchResult(**payload)
        validate_search_result_record(record)
        validate_search_result_contract(record)

    def test_missing_required_fields_rejected(self) -> None:
        """Missing any required field raises SearchResultContractValidationError."""
        for required_key in REQUIRED_SEARCH_RESULT_FIELDS:
            with self.subTest(missing_key=required_key):
                payload = self._sample_payload()
                del payload[required_key]
                with self.assertRaises(SearchResultContractValidationError):
                    validate_search_result_payload(payload)

    def test_unexpected_extra_fields_rejected(self) -> None:
        """Payload containing extra unknown fields raises SearchResultContractValidationError."""
        payload = self._sample_payload()
        payload["unknown_extra_key"] = "extra_value"
        with self.assertRaises(SearchResultContractValidationError):
            validate_search_result_payload(payload)

    def test_empty_or_whitespace_fields_rejected(self) -> None:
        """Empty or whitespace values raise SearchResultContractValidationError."""
        for field_name in REQUIRED_SEARCH_RESULT_FIELDS:
            for bad_val in ["", "   "]:
                with self.subTest(field=field_name, val=bad_val):
                    payload = self._sample_payload()
                    payload[field_name] = bad_val
                    with self.assertRaises(SearchResultContractValidationError):
                        validate_search_result_payload(payload)

    def test_invalid_url_scheme_rejected(self) -> None:
        """Non-HTTP/HTTPS URLs raise SearchResultContractValidationError."""
        for bad_url in ["ftp://example.com", "file:///path", "not-a-url"]:
            with self.subTest(bad_url=bad_url):
                payload = self._sample_payload()
                payload["url"] = bad_url
                with self.assertRaises(SearchResultContractValidationError):
                    validate_search_result_payload(payload)

    def test_non_dict_payload_rejected(self) -> None:
        """Non-dictionary payloads raise SearchResultContractValidationError."""
        for bad_payload in ["string", [1, 2], None, 123]:
            with self.subTest(payload=bad_payload):
                with self.assertRaises(SearchResultContractValidationError):
                    validate_search_result_payload(bad_payload)

    def test_invalid_record_type_rejected(self) -> None:
        """validate_search_result_record raises TypeError for non-record input."""
        with self.assertRaises(TypeError):
            validate_search_result_record("not-a-search-result")  # type: ignore

    def test_contract_dispatcher_invalid_type(self) -> None:
        """validate_search_result_contract raises error on unsupported type."""
        with self.assertRaises(SearchResultContractValidationError):
            validate_search_result_contract(["unsupported", "list"])


if __name__ == "__main__":
    unittest.main()
