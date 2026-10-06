"""Unit tests for MarketResearchService application service."""

import json
from unittest.mock import MagicMock
import unittest

from src.market_research.models import MarketResearchRecord
from src.market_research.repository import (
    MarketResearchRepository,
    MarketResearchRepositoryError,
)
from src.market_research.service import (
    InvalidOpportunityError,
    MarketResearchAIError,
    MarketResearchParseError,
    MarketResearchPersistenceError,
    MarketResearchService,
)
from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord


class TestMarketResearchService(unittest.TestCase):
    """Test suite for MarketResearchService orchestration, error handling, and persistence."""

    def setUp(self) -> None:
        """Set up standard fixtures and mocks."""
        self.mock_ai_client = MagicMock()
        self.mock_repo = MagicMock(spec=MarketResearchRepository)
        self.service = MarketResearchService(
            ai_client=self.mock_ai_client,
            market_research_repository=self.mock_repo,
        )

    def _sample_opportunity(self, opp_id: str = "opp-uuid-501") -> OpportunityRecord:
        """Helper to construct a valid OpportunityRecord."""
        return OpportunityRecord(
            opportunity_title="Autonomous Drain Inspection Crawlers",
            solution_concept="ESP-32 microcrawler with optical and multi-gas detection for underground pipes.",
            target_customer="Municipal Water Authorities and Utilities",
            value_proposition="Reduces toxic human confined space entry by 100% and labor by 60%.",
            source_problem_ids=("prob-uuid-1",),
            id=opp_id,
            raw_data={"test": True},
        )

    def _sample_ai_response(self, opp_id: str = "opp-uuid-501") -> str:
        """Helper returning valid AI JSON response text with 2 findings."""
        findings = [
            {
                "opportunity_id": opp_id,
                "source_type": "competitor_site",
                "source_name": "DrainRobo Inc",
                "source_url": "https://drainrobo.example.com/specs",
                "company_or_product": "DrainRobo X",
                "finding": "Competitor provides tethered pipe crawlers but lacks built-in gas sensors.",
                "evidence_summary": "Datasheet confirms 50m tether requirement and no toxic gas detection.",
                "relevance": "HIGH",
            },
            {
                "opportunity_id": opp_id,
                "source_type": "industry_report",
                "source_name": "Water Tech Review",
                "source_url": "https://watertech.example.com/2025-report",
                "company_or_product": "PipeInspect Systems",
                "finding": "PipeInspect holds 35% market share in manual CCTV crawler services.",
                "evidence_summary": "Report notes high service contract fees and lack of real-time telemetry.",
                "relevance": "MEDIUM",
            },
        ]
        return json.dumps(findings)

    def test_dependency_injection_validation(self) -> None:
        """Constructor requires non-None ai_client and repository."""
        with self.assertRaises(ValueError):
            MarketResearchService(ai_client=None, market_research_repository=self.mock_repo)

        with self.assertRaises(ValueError):
            MarketResearchService(ai_client=self.mock_ai_client, market_research_repository=None)

    def test_invalid_opportunity_rejected_before_downstream_calls(self) -> None:
        """Non-OpportunityRecord input is rejected without invoking AI or repository."""
        for invalid_opp in [None, "invalid-opp-str", {"title": "Fake"}, 123]:
            with self.subTest(invalid_opp=invalid_opp):
                with self.assertRaises(InvalidOpportunityError):
                    self.service.conduct_market_research(invalid_opp)  # type: ignore

        self.mock_ai_client.generate.assert_not_called()
        self.mock_repo.save_market_research.assert_not_called()

    def test_successful_service_execution_and_persisted_ids_returned(self) -> None:
        """Service successfully calls AI, parses findings, persists each, and returns records with database IDs."""
        opp = self._sample_opportunity()
        self.mock_ai_client.generate.return_value = self._sample_ai_response(opp_id="opp-uuid-501")
        self.mock_repo.save_market_research.side_effect = ["saved-id-001", "saved-id-002"]

        records = self.service.conduct_market_research(
            opportunity=opp,
            research_evidence="Preliminary web search found DrainRobo and PipeInspect.",
        )

        # Verify AI client called once
        self.mock_ai_client.generate.assert_called_once()
        system_prompt = self.mock_ai_client.generate.call_args[1]["system_prompt"]
        user_prompt = self.mock_ai_client.generate.call_args[1]["user_prompt"]
        self.assertIn("Drain Inspection Crawlers", user_prompt)
        self.assertIn("Preliminary web search found", user_prompt)

        # Verify repository called twice
        self.assertEqual(self.mock_repo.save_market_research.call_count, 2)

        # Verify returned records
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].id, "saved-id-001")
        self.assertEqual(records[0].company_or_product, "DrainRobo X")
        self.assertEqual(records[1].id, "saved-id-002")
        self.assertEqual(records[1].company_or_product, "PipeInspect Systems")

    def test_dependency_call_order(self) -> None:
        """Verify strict call order: AI generation -> Parser -> Repository persistence."""
        call_order: list[str] = []

        def ai_side_effect(*args, **kwargs):
            call_order.append("ai_call")
            return self._sample_ai_response()

        def repo_side_effect(record):
            call_order.append("repo_call")
            return "uuid-123"

        self.mock_ai_client.generate.side_effect = ai_side_effect
        self.mock_repo.save_market_research.side_effect = repo_side_effect

        opp = self._sample_opportunity()
        self.service.conduct_market_research(opp)

        self.assertEqual(call_order, ["ai_call", "repo_call", "repo_call"])

    def test_ai_failure_means_no_persistence(self) -> None:
        """If AI client generation fails, MarketResearchAIError is raised and repository is never called."""
        self.mock_ai_client.generate.side_effect = RuntimeError("AI Gateway timeout")
        opp = self._sample_opportunity()

        with self.assertRaises(MarketResearchAIError):
            self.service.conduct_market_research(opp)

        self.mock_repo.save_market_research.assert_not_called()

    def test_parser_failure_means_no_persistence(self) -> None:
        """If AI output cannot be parsed, MarketResearchParseError is raised and repository is never called."""
        self.mock_ai_client.generate.return_value = "invalid non-json text"
        opp = self._sample_opportunity()

        with self.assertRaises(MarketResearchParseError):
            self.service.conduct_market_research(opp)

        self.mock_repo.save_market_research.assert_not_called()

    def test_parser_mismatch_means_no_persistence(self) -> None:
        """If AI output returns wrong opportunity_id, MarketResearchParseError is raised and nothing is saved."""
        bad_response = json.dumps([
            {
                "opportunity_id": "different-opp-999",
                "source_type": "competitor_site",
                "source_name": "Test",
                "source_url": "https://test.com",
                "company_or_product": "Test",
                "finding": "Test finding",
                "evidence_summary": "Test summary",
                "relevance": "HIGH",
            }
        ])
        self.mock_ai_client.generate.return_value = bad_response
        opp = self._sample_opportunity(opp_id="opp-uuid-501")

        with self.assertRaises(MarketResearchParseError):
            self.service.conduct_market_research(opp)

        self.mock_repo.save_market_research.assert_not_called()

    def test_repository_failure_raises_market_research_persistence_error(self) -> None:
        """If repository save fails, MarketResearchPersistenceError is raised."""
        opp = self._sample_opportunity()
        self.mock_ai_client.generate.return_value = self._sample_ai_response(opp_id="opp-uuid-501")
        self.mock_repo.save_market_research.side_effect = MarketResearchRepositoryError("DB locked")

        with self.assertRaises(MarketResearchPersistenceError):
            self.service.conduct_market_research(opp)


if __name__ == "__main__":
    unittest.main()
