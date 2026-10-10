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
    DEFAULT_MIN_CONTENT_LENGTH,
    InvalidOpportunityIdError,
    SourceQualityDecision,
    WebEvidenceAnalyzer,
    WebEvidenceAnalyzerError,
    analyze_web_sources,
    evaluate_source_quality,
    extract_publication_date,
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
        content: str = "Real-time automated diagnostic tool with 94% accuracy and multi-spectral optical dermatological imaging verification.",
        retrieved_at: str = "2026-10-08T12:00:00Z",
        raw_data: object = None,
    ) -> WebResearchSource:
        """Helper to construct a valid WebResearchSource."""
        return WebResearchSource(
            url=url,
            title=title,
            source_type=source_type,
            publisher_or_domain=publisher,
            retrieved_content=content,
            retrieved_at=retrieved_at,
            raw_data={} if raw_data is None else raw_data,  # type: ignore
        )

    def _sample_record(
        self,
        opp_id: str = "opp-101",
        record_id: str = "rec-uuid-1",
        source_url: str = "https://competitor.example.com/product",
    ) -> MarketResearchRecord:
        """Helper to construct a valid MarketResearchRecord."""
        return MarketResearchRecord(
            opportunity_id=opp_id,
            source_type="competitor",
            source_name="Competitor Platform",
            source_url=source_url,
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
            content="Breakthrough optical imaging algorithms evaluated by clinic trials with multi-center dermatological study validation.",
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

    def test_extract_publication_date_valid_keys(self) -> None:
        """Valid publication dates under pub_date, publication_date, published_date, or published_at are extracted."""
        for key in ("pub_date", "publication_date", "published_date", "published_at"):
            with self.subTest(key=key):
                src = self._sample_source(raw_data={key: "Fri, 09 Oct 2026 14:30:00 GMT"})
                self.assertEqual(extract_publication_date(src), "Fri, 09 Oct 2026 14:30:00 GMT")

    def test_extract_publication_date_missing_or_empty_returns_unknown(self) -> None:
        """Missing or empty publication date explicitly returns 'Unknown'."""
        src_empty_dict = self._sample_source(raw_data={})
        self.assertEqual(extract_publication_date(src_empty_dict), "Unknown")

        # Object with raw_data is None or missing
        mock_no_raw = MagicMock()
        mock_no_raw.raw_data = None
        self.assertEqual(extract_publication_date(mock_no_raw), "Unknown")

        for empty_val in ("", "   ", None):
            with self.subTest(empty_val=empty_val):
                src = self._sample_source(raw_data={"pub_date": empty_val})
                self.assertEqual(extract_publication_date(src), "Unknown")

    def test_extract_publication_date_malformed_string_preserved_safely(self) -> None:
        """Malformed or irregular date strings are preserved safely without crashing or fabricating dates."""
        src = self._sample_source(raw_data={"pub_date": "not-a-valid-date-string-2026-99-99"})
        self.assertEqual(extract_publication_date(src), "not-a-valid-date-string-2026-99-99")

    def test_format_web_source_evidence_includes_publication_and_retrieval_dates(self) -> None:
        """Formatted evidence contains separate Publication Date and Retrieved At fields."""
        src = self._sample_source(
            retrieved_at="2026-10-09T18:00:00Z",
            raw_data={"pub_date": "Fri, 09 Oct 2026 14:30:00 GMT"},
        )

        formatted = format_web_source_evidence(src)
        self.assertIn("Publication Date: Fri, 09 Oct 2026 14:30:00 GMT", formatted)
        self.assertIn("Retrieved At: 2026-10-09T18:00:00Z", formatted)
        # Ensure retrieval date is NOT labeled as publication date
        self.assertNotIn("Publication Date: 2026-10-09T18:00:00Z", formatted)

    def test_format_web_source_evidence_missing_publication_date_shows_unknown(self) -> None:
        """Formatted evidence explicitly displays Publication Date: Unknown when no publication date exists."""
        src = self._sample_source(
            retrieved_at="2026-10-09T18:00:00Z",
            raw_data={},
        )

        formatted = format_web_source_evidence(src)
        self.assertIn("Publication Date: Unknown", formatted)
        self.assertIn("Retrieved At: 2026-10-09T18:00:00Z", formatted)

    def test_format_web_source_evidence_malformed_date_safely_rendered(self) -> None:
        """Formatted evidence safely renders a malformed date for debugging without crashing."""
        src = self._sample_source(
            retrieved_at="2026-10-09T18:00:00Z",
            raw_data={"pub_date": "invalid-date-format-XYZ"},
        )

        formatted = format_web_source_evidence(src)
        self.assertIn("Publication Date: invalid-date-format-XYZ", formatted)
        self.assertIn("Retrieved At: 2026-10-09T18:00:00Z", formatted)

    def test_format_web_source_evidence_compatibility_with_existing_fields(self) -> None:
        """Formatted evidence preserves all required fields: Title, URL, Domain / Publisher, Source Type, Content."""
        src = self._sample_source(
            url="https://example.com/item",
            title="Item Title",
            source_type="industry",
            publisher="example.com",
            content="Sample report text.",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"pub_date": "2026-10-01"},
        )

        formatted = format_web_source_evidence(src)
        self.assertIn("Title: Item Title", formatted)
        self.assertIn("URL: https://example.com/item", formatted)
        self.assertIn("Domain / Publisher: example.com", formatted)
        self.assertIn("Source Type: industry", formatted)
        self.assertIn("Publication Date: 2026-10-01", formatted)
        self.assertIn("Retrieved At: 2026-10-09T12:00:00Z", formatted)
        self.assertIn("Retrieved Content:\nSample report text.", formatted)

    def test_evaluate_source_quality_empty_and_very_short_content(self) -> None:
        """Empty, whitespace-only, and excessively short content (< 100 chars) are rejected."""
        # Empty string
        src_empty = MagicMock(spec=WebResearchSource)
        src_empty.retrieved_content = ""
        src_empty.title = "Empty"
        src_empty.raw_data = {}
        dec_empty = evaluate_source_quality(src_empty)
        self.assertFalse(dec_empty.is_accepted)
        self.assertIn("empty", dec_empty.reason.lower())

        # Whitespace-only
        src_ws = MagicMock(spec=WebResearchSource)
        src_ws.retrieved_content = "   \n\t  "
        src_ws.title = "Whitespace"
        src_ws.raw_data = {}
        dec_ws = evaluate_source_quality(src_ws)
        self.assertFalse(dec_ws.is_accepted)
        self.assertIn("empty", dec_ws.reason.lower())

        # Below 100 characters
        short_text = "Brief note on product specs."  # 28 chars
        src_short = self._sample_source(content=short_text)
        dec_short = evaluate_source_quality(src_short)
        self.assertFalse(dec_short.is_accepted)
        self.assertIn("below minimum threshold", dec_short.reason.lower())
        self.assertIn("100", dec_short.reason)

        # Adjustable threshold allows lower limit when explicitly requested
        dec_short_custom = evaluate_source_quality(src_short, min_content_length=20)
        self.assertTrue(dec_short_custom.is_accepted)

    def test_evaluate_source_quality_bot_challenge_with_http_200(self) -> None:
        """Obvious bot verification and CAPTCHA challenge pages are rejected even on HTTP 200."""
        challenge_content = (
            "Please verify you are human to continue. "
            "Our automated systems detected unusual traffic from your computer network. "
            "Please complete the security check to access the website."
        )  # 193 chars
        src = self._sample_source(
            title="Just a moment... | Security Check",
            content=challenge_content,
            raw_data={"http_status": 200},
        )
        decision = evaluate_source_quality(src)
        self.assertFalse(decision.is_accepted)
        self.assertIn("bot-protection", decision.reason.lower())

    def test_evaluate_source_quality_access_denied_or_error_page_with_http_200(self) -> None:
        """Access-denied messages and generic error templates are rejected even on HTTP 200."""
        # Access Denied
        src_denied = self._sample_source(
            title="403 Forbidden",
            content="Access Denied. You do not have permission to access /enterprise/api on this server. Contact administrator.",
            raw_data={"http_status": 200},
        )
        dec_denied = evaluate_source_quality(src_denied)
        self.assertFalse(dec_denied.is_accepted)
        self.assertIn("access-denied or error template", dec_denied.reason.lower())

        # 404 Not Found template
        src_404 = self._sample_source(
            title="Page Not Found",
            content="The page you are looking for cannot be found. The requested URL was not found on this server. Return to home.",
            raw_data={"http_status": 200},
        )
        dec_404 = evaluate_source_quality(src_404)
        self.assertFalse(dec_404.is_accepted)
        self.assertIn("access-denied or error template", dec_404.reason.lower())

    def test_evaluate_source_quality_http_error_status_with_readable_content(self) -> None:
        """HTTP error statuses (>= 400) are rejected even when the response has readable body content."""
        readable_404 = (
            "We are sorry, but the clinical report page has been archived or moved. "
            "Browse our documentation index to find related dermatology papers and case studies."
        )  # 180 chars
        src_404 = self._sample_source(
            title="Clinical Report Archive",
            content=readable_404,
            raw_data={"http_status": 404},
        )
        dec_404 = evaluate_source_quality(src_404)
        self.assertFalse(dec_404.is_accepted)
        self.assertIn("404", dec_404.reason)

        readable_500 = (
            "Internal Server Error occurred while generating market intelligence visualization. "
            "Please try your request again in a few minutes or notify tech support."
        )  # 175 chars
        src_500 = self._sample_source(
            title="Internal Server Error",
            content=readable_500,
            raw_data={"http_status": 500},
        )
        dec_500 = evaluate_source_quality(src_500)
        self.assertFalse(dec_500.is_accepted)
        self.assertIn("500", dec_500.reason)

    def test_evaluate_source_quality_legitimate_article_mentioning_cookies_or_captcha(self) -> None:
        """Legitimate articles mentioning cookies, CAPTCHA, or access restrictions are accepted."""
        article_text = (
            "Next-generation enterprise authentication services are rapidly replacing legacy "
            "CAPTCHA puzzles where users were forced to verify you are human. Market research across "
            "120 enterprise IT leaders indicates automated behavioral biometrics reduced customer onboarding "
            "drop-off by 43%. Concurrently, as web browsers deprecate third-party tracking cookies, privacy-compliant "
            "first-party data architectures are projected to capture $3.4B in annual vendor spend by 2028."
        )  # 462 chars
        src = self._sample_source(
            title="Enterprise Identity and Access Management Trends 2026",
            content=article_text,
            raw_data={"http_status": 200},
        )
        decision = evaluate_source_quality(src)
        self.assertTrue(decision.is_accepted)
        self.assertEqual(decision.reason, "Content meets quality standards.")

    def test_evaluate_source_quality_legitimate_short_snippet(self) -> None:
        """Legitimate short snippets meeting the minimum length policy (>= 100 chars) are preserved."""
        snippet = (
            "Dermalyze closed a $4.2M seed round to commercialize computer vision lesion analysis hardware at $199 per device."
        )  # 115 chars
        src = self._sample_source(
            title="Dermalyze Seed Financing Announcement",
            content=snippet,
            raw_data={"http_status": 200},
        )
        decision = evaluate_source_quality(src)
        self.assertTrue(decision.is_accepted)
        self.assertEqual(decision.reason, "Content meets quality standards.")

    def test_evaluate_source_quality_cookie_consent_only_rejected(self) -> None:
        """Pages consisting primarily of cookie consent notices are rejected."""
        cookie_text = (
            "We use cookies to ensure you get the best experience on our website. "
            "Accept All Cookies. Manage Cookie Preferences. Reject Non-Essential. "
            "By clicking accept, you agree to our Cookie Policy and terms."
        )  # 217 chars
        src = self._sample_source(
            title="Cookie Consent Notice",
            content=cookie_text,
            raw_data={"http_status": 200},
        )
        decision = evaluate_source_quality(src)
        self.assertFalse(decision.is_accepted)
        self.assertIn("cookie-consent", decision.reason.lower())

    def test_analyzer_filters_rejected_sources_and_retains_accepted_metadata(self) -> None:
        """WebEvidenceAnalyzer excludes rejected sources from AI evidence while preserving accepted source metadata."""
        good_src = self._sample_source(
            url="https://valid.example.com/report",
            title="High Quality Market Report",
            content="Enterprise diagnostics platform launched clinical trials demonstrating 95% specificity in skin screening with multi-center dermatological study validation.",
            retrieved_at="2026-10-09T12:00:00Z",
            raw_data={"pub_date": "2026-10-01", "http_status": 200},
        )
        bot_src = self._sample_source(
            url="https://blocked.example.com/bot",
            title="Attention Required! | Cloudflare",
            content="Please verify you are human to continue. Our systems detected unusual traffic from your computer network.",
            raw_data={"http_status": 200},
        )
        err_src = self._sample_source(
            url="https://broken.example.com/404",
            title="404 Not Found",
            content="The page you are looking for cannot be found on this server.",
            raw_data={"http_status": 404},
        )
        short_src = self._sample_source(
            url="https://empty.example.com/short",
            title="Empty",
            content="Too short.",
            raw_data={"http_status": 200},
        )

        mock_record = self._sample_record(
            opp_id="opp-101",
            source_url="https://valid.example.com/report",
        )
        self.mock_service.conduct_market_research.return_value = [mock_record]

        results = self.analyzer.analyze(
            opportunity_id="opp-101",
            sources=[good_src, bot_src, err_src, short_src],
        )

        # AI service received ONLY the 1 valid source in evidence
        self.mock_service.conduct_market_research.assert_called_once()
        passed_evidence = self.mock_service.conduct_market_research.call_args.kwargs["research_evidence"]
        self.assertEqual(len(passed_evidence), 1)
        ev_text = passed_evidence[0]
        self.assertIn("High Quality Market Report", ev_text)
        self.assertIn("Publication Date: 2026-10-01", ev_text)
        self.assertIn("Retrieved At: 2026-10-09T12:00:00Z", ev_text)
        self.assertNotIn("blocked.example.com", ev_text)
        self.assertNotIn("broken.example.com", ev_text)
        self.assertNotIn("empty.example.com", ev_text)

        # Finding citation grounding succeeded for the accepted source
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].raw_data.get("citation_verified"))

    def test_analyzer_returns_empty_when_all_sources_rejected(self) -> None:
        """When all provided sources fail the quality filter, empty findings are returned without calling AI."""
        bot_src = self._sample_source(
            url="https://blocked.example.com/bot",
            title="Security Check",
            content="Please verify you are human to continue. Unusual traffic detected from your network.",
            raw_data={"http_status": 200},
        )
        short_src = self._sample_source(
            url="https://empty.example.com/short",
            title="Short",
            content="Too short.",
            raw_data={"http_status": 200},
        )

        results = self.analyzer.analyze(
            opportunity_id="opp-101",
            sources=[bot_src, short_src],
        )

        self.assertEqual(results, [])
        self.mock_service.conduct_market_research.assert_not_called()


if __name__ == "__main__":
    unittest.main()
