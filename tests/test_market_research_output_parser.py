"""Unit tests for Market Research output parser."""

import json
import unittest

from src.market_research.models import MarketResearchRecord
from src.market_research.output_parser import (
    MarketResearchOutputParseError,
    OpportunityIdMismatchError,
    parse_market_research_output,
)


class TestMarketResearchOutputParser(unittest.TestCase):
    """Test suite for parsing and validating AI market research JSON output."""

    def _sample_finding_dict(self, opp_id: str = "opp-uuid-401") -> dict:
        """Helper returning a valid finding dictionary."""
        return {
            "opportunity_id": opp_id,
            "source_type": "competitor_site",
            "source_name": "DrainRobo Inc",
            "source_url": "https://drainrobo.example.com/crawler",
            "company_or_product": "DrainRobo X",
            "finding": "Competitor provides tethered pipe crawler without multi-gas sensors.",
            "evidence_summary": "Public product datasheet confirms tethered operation and lack of gas sensors.",
            "relevance": "HIGH",
        }

    def test_valid_json_parsing_as_list(self) -> None:
        """Parser successfully parses a valid top-level JSON list of findings."""
        finding1 = self._sample_finding_dict()
        raw_json = json.dumps([finding1])

        records = parse_market_research_output(raw_json)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertIsInstance(rec, MarketResearchRecord)
        self.assertEqual(rec.opportunity_id, "opp-uuid-401")
        self.assertEqual(rec.company_or_product, "DrainRobo X")
        self.assertEqual(rec.relevance, "HIGH")
        self.assertIsNone(rec.id)
        self.assertEqual(rec.raw_data, {"ai_raw_output": finding1})

    def test_valid_json_parsing_as_findings_object(self) -> None:
        """Parser successfully parses a JSON object with 'findings' key."""
        finding1 = self._sample_finding_dict()
        raw_json = json.dumps({"findings": [finding1]})

        records = parse_market_research_output(raw_json)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].opportunity_id, "opp-uuid-401")

    def test_multiple_findings_parsed(self) -> None:
        """Parser correctly parses multiple distinct findings in a single response."""
        f1 = self._sample_finding_dict()
        f2 = {
            "opportunity_id": "opp-uuid-401",
            "source_type": "industry_report",
            "source_name": "Gartner Infra",
            "source_url": "https://gartner.example.com/drain-inspection-2025",
            "company_or_product": "SewerScan Solutions",
            "finding": "SewerScan dominates North America with 40% market share.",
            "evidence_summary": "Report notes high subscription pricing and vendor lock-in.",
            "relevance": "MEDIUM",
        }
        raw_json = json.dumps([f1, f2])

        records = parse_market_research_output(raw_json)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].company_or_product, "DrainRobo X")
        self.assertEqual(records[0].relevance, "HIGH")
        self.assertEqual(records[1].company_or_product, "SewerScan Solutions")
        self.assertEqual(records[1].relevance, "MEDIUM")

    def test_invalid_json_rejected(self) -> None:
        """Malformed JSON strings raise MarketResearchOutputParseError."""
        malformed_inputs = [
            "",
            "   ",
            "not json at all",
            "{ incomplete json",
            "[ {'unquoted': single_quotes} ]",
        ]
        for bad_input in malformed_inputs:
            with self.subTest(bad_input=bad_input):
                with self.assertRaises(MarketResearchOutputParseError):
                    parse_market_research_output(bad_input)

    def test_non_string_input_raises_type_error(self) -> None:
        """Non-string inputs raise TypeError."""
        for invalid_type in [123, None, [self._sample_finding_dict()], {"findings": []}]:
            with self.subTest(invalid_type=invalid_type):
                with self.assertRaises(TypeError):
                    parse_market_research_output(invalid_type)  # type: ignore

    def test_empty_findings_list_rejected(self) -> None:
        """Empty list or empty findings object raises MarketResearchOutputParseError."""
        with self.assertRaises(MarketResearchOutputParseError):
            parse_market_research_output("[]")

        with self.assertRaises(MarketResearchOutputParseError):
            parse_market_research_output(json.dumps({"findings": []}))

    def test_missing_required_fields_rejected(self) -> None:
        """Any finding missing a required field raises MarketResearchOutputParseError."""
        for key in [
            "opportunity_id",
            "source_type",
            "source_name",
            "source_url",
            "company_or_product",
            "finding",
            "evidence_summary",
            "relevance",
        ]:
            with self.subTest(missing_key=key):
                bad_finding = self._sample_finding_dict()
                del bad_finding[key]
                raw_json = json.dumps([bad_finding])
                with self.assertRaises(MarketResearchOutputParseError):
                    parse_market_research_output(raw_json)

    def test_unsupported_extra_fields_rejected(self) -> None:
        """Findings containing extra unexpected fields raise MarketResearchOutputParseError."""
        bad_finding = self._sample_finding_dict()
        bad_finding["extra_unsupported_field"] = "hallucinated_data"
        raw_json = json.dumps([bad_finding])

        with self.assertRaises(MarketResearchOutputParseError):
            parse_market_research_output(raw_json)

    def test_empty_or_whitespace_values_rejected(self) -> None:
        """Empty string or whitespace values in finding fields raise MarketResearchOutputParseError."""
        for key in self._sample_finding_dict().keys():
            with self.subTest(empty_key=key):
                bad_finding = self._sample_finding_dict()
                bad_finding[key] = "   "
                raw_json = json.dumps([bad_finding])
                with self.assertRaises(MarketResearchOutputParseError):
                    parse_market_research_output(raw_json)

    def test_invalid_relevance_values_rejected(self) -> None:
        """Invalid relevance ratings raise MarketResearchOutputParseError."""
        for bad_rel in ["EXTREME", "NONE", "VERY_HIGH", ""]:
            with self.subTest(bad_rel=bad_rel):
                bad_finding = self._sample_finding_dict()
                bad_finding["relevance"] = bad_rel
                raw_json = json.dumps([bad_finding])
                with self.assertRaises(MarketResearchOutputParseError):
                    parse_market_research_output(raw_json)

    def test_opportunity_id_mismatch_rejected(self) -> None:
        """When expected_opportunity_id is passed, mismatch raises OpportunityIdMismatchError."""
        finding = self._sample_finding_dict(opp_id="opp-uuid-999")
        raw_json = json.dumps([finding])

        with self.assertRaises(OpportunityIdMismatchError):
            parse_market_research_output(raw_json, expected_opportunity_id="opp-uuid-401")

    def test_opportunity_id_match_accepted(self) -> None:
        """Matching expected_opportunity_id is accepted cleanly."""
        finding = self._sample_finding_dict(opp_id="opp-uuid-401")
        raw_json = json.dumps([finding])

        records = parse_market_research_output(raw_json, expected_opportunity_id="opp-uuid-401")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].opportunity_id, "opp-uuid-401")


if __name__ == "__main__":
    unittest.main()
