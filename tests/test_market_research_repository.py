"""Unit tests for MarketResearchRepository persistence and retrieval in SQLite."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from src.common.database import get_db, init_db
from src.market_research.models import MarketResearchRecord
from src.market_research.repository import (
    MarketResearchRepository,
    MarketResearchRepositoryError,
    OpportunityNotFoundError,
)


class TestMarketResearchRepository(unittest.TestCase):
    """Test suite for SQLite MarketResearchRepository."""

    def setUp(self) -> None:
        """Create fresh isolated temporary database and seed prerequisite opportunities."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_market_research.db"
        init_db(self.db_path)
        self.repo = MarketResearchRepository(self.db_path)

        # Seed prerequisite research run and opportunities
        with get_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_runs (id, run_name) VALUES ('run-001', 'Drain Inspection Run');"
            )
            conn.execute(
                """
                INSERT INTO startup_opportunities (
                    id, run_id, opportunity_title, solution_concept,
                    target_customer, value_proposition, raw_data
                )
                VALUES ('opp-101', 'run-001', 'Autonomous Drain Inspection Robot',
                        'ESP-32 microcrawler with gas detection',
                        'Municipal Utilities', 'Saves human entry costs by 60%', '{}');
                """
            )
            conn.execute(
                """
                INSERT INTO startup_opportunities (
                    id, run_id, opportunity_title, solution_concept,
                    target_customer, value_proposition, raw_data
                )
                VALUES ('opp-102', 'run-001', 'Acoustic Battery Scanner',
                        'Ultrasonic resonance analyzer',
                        'Battery Gigafactories', 'Prevents thermal runaway defects', '{}');
                """
            )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _sample_record(
        self,
        opp_id: str = "opp-101",
        source_type: str = "competitor_site",
        source_name: str = "DrainTech Systems",
        source_url: str = "https://draintech.example.com/crawler",
        company_or_product: str = "DrainTech Pro",
        finding: str = "Competitor lacks multi-gas sensors and requires tethered tether cable.",
        evidence_summary: str = "Datasheet verifies 50m tether limitation and no H2S/methane detection.",
        relevance: str = "HIGH",
        rec_id: str | None = None,
        raw_data: dict | None = None,
    ) -> MarketResearchRecord:
        """Helper constructing a valid MarketResearchRecord."""
        return MarketResearchRecord(
            opportunity_id=opp_id,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            company_or_product=company_or_product,
            finding=finding,
            evidence_summary=evidence_summary,
            relevance=relevance,
            id=rec_id,
            raw_data=raw_data if raw_data is not None else {"source_engine": "duckduckgo_v2"},
        )

    def test_successful_persistence_with_generated_id(self) -> None:
        """Finding is saved, assigned a valid UUID, and retrieved with full attribute parity."""
        record = self._sample_record()
        saved_id = self.repo.save_market_research(record)

        self.assertIsInstance(saved_id, str)
        self.assertEqual(len(saved_id), 36)
        # Verify UUID structure
        uuid.UUID(saved_id)

        retrieved = self.repo.get_by_id(saved_id)
        self.assertIsNotNone(retrieved)
        self.assertIsInstance(retrieved, MarketResearchRecord)
        self.assertEqual(retrieved.id, saved_id)
        self.assertEqual(retrieved.opportunity_id, "opp-101")
        self.assertEqual(retrieved.source_type, "competitor_site")
        self.assertEqual(retrieved.source_name, "DrainTech Systems")
        self.assertEqual(retrieved.source_url, "https://draintech.example.com/crawler")
        self.assertEqual(retrieved.company_or_product, "DrainTech Pro")
        self.assertEqual(retrieved.finding, record.finding)
        self.assertEqual(retrieved.evidence_summary, record.evidence_summary)
        self.assertEqual(retrieved.relevance, "HIGH")
        self.assertEqual(retrieved.raw_data, {"source_engine": "duckduckgo_v2"})

    def test_persistence_preserves_explicit_id(self) -> None:
        """Explicit record id is preserved upon persistence and retrieval."""
        custom_id = "custom-market-finding-777"
        record = self._sample_record(rec_id=custom_id)
        saved_id = self.repo.save_market_research(record)

        self.assertEqual(saved_id, custom_id)
        retrieved = self.repo.get_by_id(custom_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, custom_id)

    def test_retrieval_by_id_nonexistent_or_empty(self) -> None:
        """get_by_id returns None for non-existent IDs and empty strings."""
        self.assertIsNone(self.repo.get_by_id("non-existent-uuid"))
        self.assertIsNone(self.repo.get_by_id(""))
        self.assertIsNone(self.repo.get_by_id("   "))

    def test_round_trip_raw_data_fidelity(self) -> None:
        """Complex nested raw_data dictionary round-trips through JSON storage accurately."""
        complex_payload = {
            "search_query": "confined space pipe crawling robot competitors",
            "page_rank": 1,
            "metadata": {
                "pricing": {"tier": "enterprise", "estimated_usd": 45000},
                "tags": ["confined_space", "sewer", "robotics"],
                "verified": True,
            },
        }
        record = self._sample_record(raw_data=complex_payload)
        saved_id = self.repo.save_market_research(record)

        retrieved = self.repo.get_by_id(saved_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.raw_data, complex_payload)

    def test_missing_opportunity_raises_opportunity_not_found_error(self) -> None:
        """Attempting to save market research for non-existent opportunity raises OpportunityNotFoundError."""
        record = self._sample_record(opp_id="opp-non-existent")
        with self.assertRaises(OpportunityNotFoundError):
            self.repo.save_market_research(record)

    def test_invalid_record_rejected(self) -> None:
        """save_market_research rejects non-records with MarketResearchRepositoryError."""
        with self.assertRaises(MarketResearchRepositoryError):
            self.repo.save_market_research("not-a-record")  # type: ignore

        with self.assertRaises(MarketResearchRepositoryError):
            self.repo.save_market_research(None)  # type: ignore

    def test_duplicate_and_idempotency_behavior(self) -> None:
        """Re-saving identical finding returns existing ID without creating duplicate rows."""
        record = self._sample_record()

        id1 = self.repo.save_market_research(record)
        id2 = self.repo.save_market_research(record)
        self.assertEqual(id1, id2)

        # Confirm only one row was inserted
        findings = self.repo.get_for_opportunity("opp-101")
        self.assertEqual(len(findings), 1)

        # Re-saving with explicit ID also returns existing ID idempotently
        record_with_id = self._sample_record(
            rec_id="explicit-finding-001",
            source_url="https://different.example.com",
            company_or_product="Different Corp",
        )
        id3 = self.repo.save_market_research(record_with_id)
        id4 = self.repo.save_market_research(record_with_id)
        self.assertEqual(id3, "explicit-finding-001")
        self.assertEqual(id4, "explicit-finding-001")

    def test_multiple_findings_for_one_opportunity(self) -> None:
        """Multiple distinct findings for the same opportunity are persisted and returned deterministically."""
        rec1 = self._sample_record(
            opp_id="opp-101",
            company_or_product="Competitor Alpha",
            source_url="https://alpha.example.com/specs",
            finding="Alpha lacks wireless communications in underground pipe networks.",
        )
        rec2 = self._sample_record(
            opp_id="opp-101",
            company_or_product="Competitor Beta",
            source_url="https://beta.example.com/product",
            finding="Beta crawler requires manual steering with no autonomy.",
        )
        rec3 = self._sample_record(
            opp_id="opp-101",
            company_or_product="Gartner Research",
            source_type="industry_report",
            source_url="https://gartner.example.com/infrastructure-2025",
            finding="Global municipal drain maintenance market growing at 12% CAGR.",
        )

        id1 = self.repo.save_market_research(rec1)
        id2 = self.repo.save_market_research(rec2)
        id3 = self.repo.save_market_research(rec3)

        self.assertNotEqual(id1, id2)
        self.assertNotEqual(id2, id3)

        findings_101 = self.repo.get_for_opportunity("opp-101")
        self.assertEqual(len(findings_101), 3)

        # Check retrieval order matches insertion
        self.assertEqual(findings_101[0].company_or_product, "Competitor Alpha")
        self.assertEqual(findings_101[1].company_or_product, "Competitor Beta")
        self.assertEqual(findings_101[2].company_or_product, "Gartner Research")

        # Confirm other opportunity returns empty list
        findings_102 = self.repo.get_for_opportunity("opp-102")
        self.assertEqual(findings_102, [])

    def test_get_for_opportunity_empty_or_whitespace(self) -> None:
        """get_for_opportunity returns empty list for empty or whitespace strings."""
        self.assertEqual(self.repo.get_for_opportunity(""), [])
        self.assertEqual(self.repo.get_for_opportunity("   "), [])

    def test_external_connection_transaction_support(self) -> None:
        """External connection transaction support works seamlessly."""
        record = self._sample_record()
        with get_db(self.db_path) as conn:
            saved_id = self.repo.save_market_research(record, conn=conn)

        retrieved = self.repo.get_by_id(saved_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, saved_id)


if __name__ == "__main__":
    unittest.main()
