"""Unit tests for MarketResearchRecord data model and validation."""

from dataclasses import FrozenInstanceError
import unittest

from src.market_research.models import (
    ALLOWED_RELEVANCE,
    REQUIRED_MARKET_RESEARCH_TEXT_FIELDS,
    MarketResearchRecord,
)


class TestMarketResearchModels(unittest.TestCase):
    """Test suite for immutable MarketResearchRecord dataclass."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for MarketResearchRecord."""
        return {
            "opportunity_id": "opp-uuid-101",
            "source_type": "competitor_site",
            "source_name": "DrainRobo Inc.",
            "source_url": "https://drainrobo.example.com/products/crawlers",
            "company_or_product": "DrainRobo Model X",
            "finding": "Competitor offers tethered crawlers but lacks autonomous multi-gas sensing.",
            "evidence_summary": "Product specs confirm tether requirement up to 50m and no built-in toxic gas detection.",
            "relevance": "HIGH",
            "raw_data": {"scraper": "serp_api_v1"},
        }

    def test_valid_construction(self) -> None:
        """MarketResearchRecord constructs successfully with valid attributes."""
        kwargs = self._sample_kwargs()
        record = MarketResearchRecord(**kwargs)

        self.assertEqual(record.opportunity_id, kwargs["opportunity_id"])
        self.assertEqual(record.source_type, kwargs["source_type"])
        self.assertEqual(record.source_name, kwargs["source_name"])
        self.assertEqual(record.source_url, kwargs["source_url"])
        self.assertEqual(record.company_or_product, kwargs["company_or_product"])
        self.assertEqual(record.finding, kwargs["finding"])
        self.assertEqual(record.evidence_summary, kwargs["evidence_summary"])
        self.assertEqual(record.relevance, "HIGH")
        self.assertIsNone(record.id)
        self.assertEqual(record.raw_data, {"scraper": "serp_api_v1"})

    def test_default_id_none(self) -> None:
        """id defaults to None when not provided."""
        record = MarketResearchRecord(**self._sample_kwargs())
        self.assertIsNone(record.id)

    def test_valid_persisted_id(self) -> None:
        """Persisted string id is accepted and accessible on MarketResearchRecord."""
        kwargs = self._sample_kwargs()
        kwargs["id"] = "res-uuid-999"
        record = MarketResearchRecord(**kwargs)

        self.assertEqual(record.id, "res-uuid-999")

    def test_invalid_or_empty_id(self) -> None:
        """Empty string, whitespace, or non-string id raises ValueError."""
        for invalid_id in ["", "   ", 12345, True]:
            with self.subTest(invalid_id=invalid_id):
                kwargs = self._sample_kwargs()
                kwargs["id"] = invalid_id
                with self.assertRaises(ValueError):
                    MarketResearchRecord(**kwargs)

    def test_immutability(self) -> None:
        """MarketResearchRecord is frozen and raises FrozenInstanceError on mutation."""
        record = MarketResearchRecord(**self._sample_kwargs())

        with self.assertRaises(FrozenInstanceError):
            record.finding = "Altered finding"  # type: ignore

        with self.assertRaises(FrozenInstanceError):
            record.id = "new-id"  # type: ignore

        with self.assertRaises(FrozenInstanceError):
            record.relevance = "LOW"  # type: ignore

    def test_required_text_fields_non_empty(self) -> None:
        """Every required text field rejects empty strings, whitespace, None, and non-strings."""
        for field_name in REQUIRED_MARKET_RESEARCH_TEXT_FIELDS:
            for invalid_val in ["", "   ", None, 123, False]:
                with self.subTest(field=field_name, val=invalid_val):
                    kwargs = self._sample_kwargs()
                    kwargs[field_name] = invalid_val
                    with self.assertRaises(ValueError):
                        MarketResearchRecord(**kwargs)

    def test_whitespace_stripping_on_text_fields(self) -> None:
        """Surrounding whitespace on required text fields is cleanly stripped."""
        kwargs = self._sample_kwargs()
        kwargs["opportunity_id"] = "  opp-uuid-padded  "
        kwargs["source_type"] = "  industry_report  "
        kwargs["company_or_product"] = "  Acme Corp  "

        record = MarketResearchRecord(**kwargs)
        self.assertEqual(record.opportunity_id, "opp-uuid-padded")
        self.assertEqual(record.source_type, "industry_report")
        self.assertEqual(record.company_or_product, "Acme Corp")

    def test_relevance_validation_and_normalization(self) -> None:
        """Relevance accepts case-insensitive valid values and normalizes to uppercase."""
        for rel in ["high", "HIGH", "medium", "MEDIUM", "low", "LOW", "  high  "]:
            with self.subTest(relevance=rel):
                kwargs = self._sample_kwargs()
                kwargs["relevance"] = rel
                record = MarketResearchRecord(**kwargs)
                self.assertIn(record.relevance, ALLOWED_RELEVANCE)
                self.assertEqual(record.relevance, rel.strip().upper())

    def test_invalid_relevance(self) -> None:
        """Invalid relevance values or types raise ValueError or TypeError."""
        for bad_rel in ["CRITICAL", "UNKNOWN", "NONE", "", "   "]:
            with self.subTest(bad_rel=bad_rel):
                kwargs = self._sample_kwargs()
                kwargs["relevance"] = bad_rel
                with self.assertRaises(ValueError):
                    MarketResearchRecord(**kwargs)

        for bad_type in [123, None, True, False]:
            with self.subTest(bad_type=bad_type):
                kwargs = self._sample_kwargs()
                kwargs["relevance"] = bad_type
                with self.assertRaises(TypeError):
                    MarketResearchRecord(**kwargs)

    def test_raw_data_validation(self) -> None:
        """raw_data must be a dictionary; non-dict raises TypeError."""
        for bad_raw in ["not_a_dict", [1, 2, 3], 123, None]:
            with self.subTest(bad_raw=bad_raw):
                kwargs = self._sample_kwargs()
                kwargs["raw_data"] = bad_raw
                with self.assertRaises(TypeError):
                    MarketResearchRecord(**kwargs)

    def test_to_dict(self) -> None:
        """to_dict serializes MarketResearchRecord to standard dictionary."""
        kwargs = self._sample_kwargs()
        record = MarketResearchRecord(**kwargs)
        data = record.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["opportunity_id"], kwargs["opportunity_id"])
        self.assertEqual(data["source_type"], kwargs["source_type"])
        self.assertEqual(data["source_name"], kwargs["source_name"])
        self.assertEqual(data["source_url"], kwargs["source_url"])
        self.assertEqual(data["company_or_product"], kwargs["company_or_product"])
        self.assertEqual(data["finding"], kwargs["finding"])
        self.assertEqual(data["evidence_summary"], kwargs["evidence_summary"])
        self.assertEqual(data["relevance"], "HIGH")
        self.assertIsNone(data["id"])
        self.assertEqual(data["raw_data"], kwargs["raw_data"])

    def test_from_dict(self) -> None:
        """from_dict reconstructs valid MarketResearchRecord."""
        kwargs = self._sample_kwargs()
        kwargs["id"] = "res-uuid-123"
        record = MarketResearchRecord.from_dict(kwargs)

        self.assertEqual(record.id, "res-uuid-123")
        self.assertEqual(record.opportunity_id, kwargs["opportunity_id"])
        self.assertEqual(record.finding, kwargs["finding"])

        # Non-dict raises TypeError
        with self.assertRaises(TypeError):
            MarketResearchRecord.from_dict("invalid")  # type: ignore


if __name__ == "__main__":
    unittest.main()
