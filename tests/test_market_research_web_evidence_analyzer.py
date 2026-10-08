"""Unit tests for WebEvidenceAnalyzer integration layer."""

from unittest.mock import MagicMock
import unittest

from src.market_research.models import MarketResearchRecord
from src.market_research.repository import MarketResearchRepository
from src.market_research.service import (
    MarketResearchAIError,
    MarketResearchParseError,
    MarketResearchPersistenceError,
    MarketResearchService,
    MarketResearchServiceError,
)
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import (
    InvalidOpportunityIdError,
    WebEvidenceAnalyzer,
    WebEvidenceAnalyzerError,
    analyze_web_sources,
    format_web_source_evidence,
    format_web_sources_evidence,
)
from src.opportunities.models import OpportunityRecord
from src.opportunities.repository import OpportunityRepository


class TestWebEvidenceAnalyzer(unittest.TestCase):
    """Test suite for WebEvidenceAnalyzer connecting WebResearchSources to MarketResearchService."""

    def setUp(self) -> None:
        """Set up standard fixtures and mocked service dependencies."""
        self.mock_service = MagicMock(spec=MarketResearchService)
        self.analyzer = WebEvidenceAnalyzer(market_research_service=self.mock_service)

    def _sample_source(
        self,
        url: str = "https://competitor.example.com/product",
        title: str = "Competitor AI Analysis Platform",
        source_type: str = "competitor",
        publisher: str = "competitor.example.com",
        content: str = "Real-time automated diagnostic tool with 94% accuracy.",
    ) -> WebResearchSource:
        """Helper to construct a valid WebResearchSource."""
        return WebResearchSource(
            url=url,
            title=title,
            source_type=source_type,
            publisher_or_domain=publisher,
            retrieved_content=content,
            retrieved_at="2026-10-08T12:00:00Z",
        )

    def _sample_record(
        self,
        opp_id: str = "opp-101",
        record_id: str = "rec-uuid-1",
    ) -> MarketResearchRecord:
        """Helper to construct a valid MarketResearchRecord."""
        return MarketResearchRecord(
            opportunity_id=opp_id,
            source_type="competitor",
            source_name="Competitor Platform",
            source_url="https://competitor.example.com/product",
            company_or_product="Competitor Diagnostic",
            finding="Competitor offers automated skin diagnosis with enterprise subscription model.",
            evidence_summary="Public specs indicate $500/month tier targeting dermatological clinics.",
            relevance="HIGH",
            id=record_id,
        )

    def test_initialization_validation(self) -> None:
        """Requires either a service or both (ai_client and market_research_repository)."""
        # Neither provided
        with self.assertRaises(ValueError):
            WebEvidenceAnalyzer(market_research_service=None)

        # Incomplete AI client / repo pair
        mock_ai = MagicMock()
        mock_repo = MagicMock(spec=MarketResearchRepository)
        with self.assertRaises(ValueError):
            WebEvidenceAnalyzer(ai_client=mock_ai, market_research_repository=None)
        with self.assertRaises(ValueError):
            WebEvidenceAnalyzer(ai_client=None, market_research_repository=mock_repo)

        # Successful construction with ai_client and repo
        analyzer2 = WebEvidenceAnalyzer(ai_client=mock_ai, market_research_repository=mock_repo)
        self.assertIsInstance(analyzer2.service, MarketResearchService)

    def test_valid_web_sources_accepted_and_returns_market_research_records(self) -> None:
        """Valid WebResearchSource objects are accepted and return structured MarketResearchRecords."""
        src = self._sample_source()
        rec = self._sample_record(opp_id="opp-101")
        self.mock_service.conduct_market_research.return_value = [rec]

        results = self.analyzer.analyze(opportunity_id="opp-101", sources=[src])

        self.mock_service.conduct_market_research.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], MarketResearchRecord)
        self.assertEqual(results[0].opportunity_id, "opp-101")
        self.assertEqual(results[0].finding, rec.finding)

    def test_source_metadata_passed_to_analysis_layer(self) -> None:
        """Preserves source metadata: URL, title, source_type, publisher/domain, retrieved_content."""
        src = self._sample_source(
            url="https://healthnews.example.com/ai-skincare-2026",
            title="Next Gen Skincare Diagnostics",
            source_type="news",
            publisher="healthnews.example.com",
            content="Breakthrough optical imaging algorithms evaluated by clinic trials.",
        )
        self.mock_service.conduct_market_research.return_value = [self._sample_record()]

        self.analyzer.analyze(opportunity_id="opp-101", sources=[src])

        call_kwargs = self.mock_service.conduct_market_research.call_args.kwargs
        evidence = call_kwargs.get("research_evidence")
        self.assertIsNotNone(evidence)
        self.assertIsInstance(evidence, list)
        self.assertEqual(len(evidence), 1)

        ev_str = evidence[0]
        self.assertIn("https://healthnews.example.com/ai-skincare-2026", ev_str)
        self.assertIn("Next Gen Skincare Diagnostics", ev_str)
        self.assertIn("news", ev_str)
        self.assertIn("healthnews.example.com", ev_str)
        self.assertIn("Breakthrough optical imaging algorithms", ev_str)

    def test_multiple_sources_handled(self) -> None:
        """Multiple WebResearchSource objects are formatted and forwarded into evidence."""
        src1 = self._sample_source(url="https://src1.example.com", title="Source One")
        src2 = self._sample_source(url="https://src2.example.com", title="Source Two")
        src3 = self._sample_source(url="https://src3.example.com", title="Source Three")

        self.mock_service.conduct_market_research.return_value = [
            self._sample_record(record_id="r1"),
            self._sample_record(record_id="r2"),
        ]

        results = self.analyzer.analyze(opportunity_id="opp-101", sources=[src1, src2, src3])

        self.assertEqual(len(results), 2)
        call_kwargs = self.mock_service.conduct_market_research.call_args.kwargs
        evidence = call_kwargs.get("research_evidence")
        self.assertEqual(len(evidence), 3)
        self.assertIn("Source One", evidence[0])
        self.assertIn("Source Two", evidence[1])
        self.assertIn("Source Three", evidence[2])

    def test_empty_source_collection_handled_cleanly(self) -> None:
        """Empty source collection returns empty list without calling downstream service."""
        for empty_sources in [[], (), tuple()]:
            with self.subTest(empty_sources=empty_sources):
                self.mock_service.reset_mock()
                results = self.analyzer.analyze(opportunity_id="opp-101", sources=empty_sources)
                self.assertEqual(results, [])
                self.mock_service.conduct_market_research.assert_not_called()

    def test_invalid_opportunity_id_rejected(self) -> None:
        """Non-string, empty, or whitespace opportunity_id is rejected."""
        src = self._sample_source()
        for invalid_id in ["", "   ", None, 123, True, False, []]:
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(InvalidOpportunityIdError):
                    self.analyzer.analyze(opportunity_id=invalid_id, sources=[src])  # type: ignore

        self.mock_service.conduct_market_research.assert_not_called()

    def test_invalid_sources_input_rejected(self) -> None:
        """Non-sequence sources or sequence containing non-WebResearchSource items is rejected."""
        # Non-sequence
        with self.assertRaises(WebEvidenceAnalyzerError):
            self.analyzer.analyze(opportunity_id="opp-101", sources=None)  # type: ignore
        with self.assertRaises(WebEvidenceAnalyzerError):
            self.analyzer.analyze(opportunity_id="opp-101", sources="not-a-sequence")  # type: ignore

        # Sequence with invalid items
        with self.assertRaises(WebEvidenceAnalyzerError):
            self.analyzer.analyze(opportunity_id="opp-101", sources=[self._sample_source(), "bad-item"])  # type: ignore

        self.mock_service.conduct_market_research.assert_not_called()

    def test_ai_and_service_failures_propagate_clearly(self) -> None:
        """Downstream AI, parsing, or persistence failures propagate without suppression."""
        src = self._sample_source()

        # 1. AI generation error
        self.mock_service.conduct_market_research.side_effect = MarketResearchAIError("Rate limited")
        with self.assertRaises(MarketResearchAIError):
            self.analyzer.analyze("opp-101", [src])

        # 2. Parse error
        self.mock_service.conduct_market_research.side_effect = MarketResearchParseError("JSON broken")
        with self.assertRaises(MarketResearchParseError):
            self.analyzer.analyze("opp-101", [src])

        # 3. Persistence error
        self.mock_service.conduct_market_research.side_effect = MarketResearchPersistenceError("DB locked")
        with self.assertRaises(MarketResearchPersistenceError):
            self.analyzer.analyze("opp-101", [src])

        # 4. Generic MarketResearchServiceError
        self.mock_service.conduct_market_research.side_effect = MarketResearchServiceError("Internal error")
        with self.assertRaises(MarketResearchServiceError):
            self.analyzer.analyze("opp-101", [src])

    def test_explicit_opportunity_and_id_mismatch(self) -> None:
        """Explicit OpportunityRecord is forwarded; ID mismatch is rejected."""
        src = self._sample_source()
        opp_matching = OpportunityRecord(
            opportunity_title="Autonomous Skincare Analyzer",
            solution_concept="Multi-spectral imaging on edge microcontroller.",
            target_customer="Cosmetic clinics",
            value_proposition="Reduces consultation time by 75%.",
            source_problem_ids=("prob-1",),
            id="opp-101",
        )
        self.mock_service.conduct_market_research.return_value = [self._sample_record(opp_id="opp-101")]

        # Matching opportunity succeeds
        res = self.analyzer.analyze("opp-101", [src], opportunity=opp_matching)
        self.assertEqual(len(res), 1)
        passed_opp = self.mock_service.conduct_market_research.call_args.kwargs["opportunity"]
        self.assertEqual(passed_opp.id, "opp-101")
        self.assertEqual(passed_opp.opportunity_title, "Autonomous Skincare Analyzer")

        # Mismatching opportunity raises error
        opp_mismatch = OpportunityRecord(
            opportunity_title="Other Venture",
            solution_concept="Other concept.",
            target_customer="Other customer",
            value_proposition="Other proposition.",
            source_problem_ids=("prob-2",),
            id="opp-999",
        )
        with self.assertRaises(WebEvidenceAnalyzerError):
            self.analyzer.analyze("opp-101", [src], opportunity=opp_mismatch)

    def test_opportunity_repository_lookup(self) -> None:
        """Uses OpportunityRepository if provided; raises if opportunity is not found."""
        mock_opp_repo = MagicMock(spec=OpportunityRepository)
        analyzer = WebEvidenceAnalyzer(
            market_research_service=self.mock_service,
            opportunity_repository=mock_opp_repo,
        )
        src = self._sample_source()

        # Opportunity found in repository
        found_opp = OpportunityRecord(
            opportunity_title="Repo Found Opp",
            solution_concept="Repo concept",
            target_customer="Repo customer",
            value_proposition="Repo ROI",
            source_problem_ids=("prob-1",),
            id="opp-202",
        )
        mock_opp_repo.get_opportunity_by_id.return_value = found_opp
        self.mock_service.conduct_market_research.return_value = [self._sample_record(opp_id="opp-202")]

        res = analyzer.analyze("opp-202", [src])
        self.assertEqual(len(res), 1)
        mock_opp_repo.get_opportunity_by_id.assert_called_with("opp-202")

        # Opportunity not found in repository raises
        mock_opp_repo.get_opportunity_by_id.return_value = None
        with self.assertRaises(WebEvidenceAnalyzerError):
            analyzer.analyze("opp-404", [src])

    def test_convenience_function_analyze_web_sources(self) -> None:
        """Top-level analyze_web_sources functional helper invokes analyzer correctly."""
        src = self._sample_source()
        self.mock_service.conduct_market_research.return_value = [self._sample_record(opp_id="opp-303")]

        results = analyze_web_sources(
            opportunity_id="opp-303",
            sources=[src],
            service=self.mock_service,
        )
        self.assertEqual(len(results), 1)
        self.mock_service.conduct_market_research.assert_called_once()


if __name__ == "__main__":
    unittest.main()
