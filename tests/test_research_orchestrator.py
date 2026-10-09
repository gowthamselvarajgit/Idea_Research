"""Focused unit tests for the generic domain-agnostic ResearchOrchestrator."""

from collections.abc import Sequence
from unittest.mock import MagicMock
import unittest

from src.evaluation.evaluation_service import OpportunityEvaluationService
from src.evaluation.models import OpportunityEvaluationRecord
from src.market_research.fallback_search_provider import FallbackSearchProvider
from src.market_research.google_news_provider import GoogleNewsRSSSearchProvider
from src.market_research.models import MarketResearchRecord
from src.market_research.research_query_generator import (
    GeneratedResearchQueries,
    ResearchQueryGenerator,
    ResearchQueryItem,
)
from src.market_research.search_client import SearchClient, SearchProvider
from src.market_research.search_models import SearchResult
from src.market_research.search_source_collector import (
    SearchSourceCollectionResult,
    SearchSourceCollector,
)
from src.market_research.source_collection import (
    SourceCollectionFailure,
    WebSourceCollector,
)
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.models import OpportunityRecord
from src.opportunities.synthesis_service import OpportunitySynthesisService
from src.patents.research_config import ResearchDomainConfig
from src.problems.extraction_service import ProblemExtractionService
from src.problems.models import ProblemRecord
from src.research.research_orchestrator import (
    ResearchOrchestrationResult,
    ResearchOrchestrator,
    ResearchOrchestratorError,
)
from src.research.research_service import (
    PatentResearchExecutionError,
    PatentResearchResult,
    ResearchService,
)


class TestResearchOrchestrator(unittest.TestCase):
    """Test suite for ResearchOrchestrator end-to-end stage execution and failure handling."""

    def setUp(self) -> None:
        """Create standard mock dependencies and fixtures."""
        self.mock_research_service = MagicMock(spec=ResearchService)
        self.mock_problem_extraction_service = MagicMock(spec=ProblemExtractionService)
        self.mock_opportunity_synthesis_service = MagicMock(spec=OpportunitySynthesisService)
        self.mock_opportunity_evaluation_service = MagicMock(spec=OpportunityEvaluationService)
        self.mock_query_generator = MagicMock(spec=ResearchQueryGenerator)
        self.mock_search_collector = MagicMock(spec=SearchSourceCollector)
        self.mock_web_evidence_analyzer = MagicMock(spec=WebEvidenceAnalyzer)

        self.orchestrator = ResearchOrchestrator(
            research_service=self.mock_research_service,
            problem_extraction_service=self.mock_problem_extraction_service,
            opportunity_synthesis_service=self.mock_opportunity_synthesis_service,
            opportunity_evaluation_service=self.mock_opportunity_evaluation_service,
            query_generator=self.mock_query_generator,
            search_collector=self.mock_search_collector,
            web_evidence_analyzer=self.mock_web_evidence_analyzer,
        )

        self.sample_config = ResearchDomainConfig(
            domain_name="Water Treatment",
            themes=("water purification", "desalination", "water contamination"),
            description="Industrial and municipal water treatment research",
        )


        self.sample_patent_result = PatentResearchResult(
            run_id="run-uuid-101",
            theme="Water Treatment",
            generated_queries=("WATER",),
            executed_queries=("WATER",),
            discovered_count=5,
            ingested_count=5,
            inserted_count=5,
            existing_count=0,
            linked_count=5,
            final_run_status="completed",
        )

        self.sample_problem = ProblemRecord(
            problem_title="Membrane Biofouling",
            problem_description="Biofilm accumulation degrades reverse osmosis membrane flux.",
            affected_users="Desalination Plant Operators",
            bottleneck_type="Fouling",
            technical_domain="Membrane Separation",
            current_workaround="Frequent chemical flushing",
            problem_frequency="Continuous",
            problem_severity="High",
            evidence_summary="Extracted from patent disclosure.",
            evidence_confidence="High",
            source_patent_numbers=("US9999999B2",),
            id="prob-101",
        )

        self.sample_opportunity = OpportunityRecord(
            opportunity_title="Nanocoated Anti-Biofouling Membrane Modules",
            solution_concept="Zwitterionic surface functionalization preventing bacterial adhesion.",
            target_customer="Industrial Desalination Facilities",
            value_proposition="Reduces downtime by 40% and triples membrane lifespan.",
            source_problem_ids=("prob-101",),
            id="opp-101",
        )

        self.sample_evaluation = OpportunityEvaluationRecord(
            opportunity_id="opp-101",
            overall_score=85,
            problem_severity_score=9,
            frequency_score=8,
            user_scale_score=8,
            willingness_to_pay_score=9,
            market_gap_score=8,
            technology_leverage_score=9,
            competition_score=8,
            wow_factor_score=7,
            recurring_potential_score=8,
            social_impact_score=9,
            execution_feasibility_score=8,
            rejection_reasons=(),
            recommendation="PURSUE",
            rationale="Exceptional commercial viability addressing a severe operational bottleneck.",
            id="eval-101",
        )


        self.sample_web_source = WebResearchSource(
            url="https://watertech.example.com/membranes",
            title="State of Desalination Membranes 2026",
            source_type="industry",
            publisher_or_domain="watertech.example.com",
            retrieved_content="Industrial market review of reverse osmosis membranes.",
            retrieved_at="2026-10-08T12:00:00Z",
            id="src-101",
        )

        self.sample_finding = MarketResearchRecord(
            opportunity_id="opp-101",
            source_type="competitor_site",
            source_name="AquaMembrane Corp",
            source_url="https://aquamembrane.example.com",
            company_or_product="AquaMembrane X",
            finding="Incumbent manufactures standard RO membranes but lacks biofouling resistance.",
            evidence_summary="Public specs confirm quarterly chemical wash requirement.",
            relevance="HIGH",
            id="find-101",
        )

    def test_stages_execute_in_correct_order_and_return_consolidated_result(self) -> None:
        """Pipeline stages execute in strict order (1 to 7) and return complete telemetry."""
        call_sequence: list[str] = []

        def trace_patent_research(*args, **kwargs):
            call_sequence.append("patent_research")
            return self.sample_patent_result

        def trace_problem_extraction(*args, **kwargs):
            call_sequence.append("problem_extraction")
            return [self.sample_problem]

        def trace_opportunity_synthesis(*args, **kwargs):
            call_sequence.append("opportunity_synthesis")
            return self.sample_opportunity

        def trace_opportunity_evaluation(*args, **kwargs):
            call_sequence.append("opportunity_evaluation")
            return self.sample_evaluation

        def trace_query_generation(*args, **kwargs):
            call_sequence.append("query_generation")
            q_str = "water purification competitors"
            return GeneratedResearchQueries(
                domain_name=self.sample_config.domain_name,
                queries=(q_str,),
                items=(ResearchQueryItem(q_str, "competitor", "water purification"),),
            )


        def trace_search_collection(*args, **kwargs):
            call_sequence.append("search_collection")
            return SearchSourceCollectionResult(
                query="water purification competitors",
                sources=(self.sample_web_source,),
                failures=(),
            )

        def trace_market_analysis(*args, **kwargs):
            call_sequence.append("market_analysis")
            return [self.sample_finding]

        self.mock_research_service.run_patent_research.side_effect = trace_patent_research
        self.mock_problem_extraction_service.extract_problems_for_run.side_effect = trace_problem_extraction
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.side_effect = trace_opportunity_synthesis
        self.mock_opportunity_evaluation_service.evaluate_opportunity.side_effect = trace_opportunity_evaluation
        self.mock_query_generator.generate_queries.side_effect = trace_query_generation
        self.mock_search_collector.collect_for_query.side_effect = trace_search_collection
        self.mock_web_evidence_analyzer.analyze.side_effect = trace_market_analysis

        result = self.orchestrator.run_research(self.sample_config)

        # 1. Assert exact execution order
        expected_sequence = [
            "patent_research",
            "problem_extraction",
            "opportunity_synthesis",
            "opportunity_evaluation",
            "query_generation",
            "search_collection",
            "market_analysis",
        ]
        self.assertEqual(call_sequence, expected_sequence)

        # 2. Assert result structure and counts
        self.assertIsInstance(result, ResearchOrchestrationResult)
        self.assertEqual(result.run_id, "run-uuid-101")
        self.assertEqual(result.domain_config, self.sample_config)
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.error)
        self.assertTrue(result.is_success)

        self.assertEqual(result.problem_count, 1)
        self.assertEqual(result.opportunity_count, 1)
        self.assertEqual(result.evaluation_count, 1)
        self.assertEqual(result.query_count, 1)
        self.assertEqual(result.web_source_count, 1)
        self.assertEqual(result.web_failure_count, 0)
        self.assertEqual(result.market_finding_count, 1)

        # Check references
        self.assertEqual(result.extracted_problems[0], self.sample_problem)
        self.assertEqual(result.synthesized_opportunities[0], self.sample_opportunity)
        self.assertEqual(result.opportunity_evaluations[0], self.sample_evaluation)
        self.assertEqual(result.collected_web_sources[0], self.sample_web_source)
        self.assertEqual(result.market_research_findings[0], self.sample_finding)

    def test_domain_config_passed_through_correctly(self) -> None:
        """The ResearchDomainConfig is passed directly to patent research and query generator."""
        self.mock_research_service.run_patent_research.return_value = self.sample_patent_result
        self.mock_problem_extraction_service.extract_problems_for_run.return_value = [self.sample_problem]
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = self.sample_opportunity
        self.mock_opportunity_evaluation_service.evaluate_opportunity.return_value = self.sample_evaluation
        self.mock_query_generator.generate_queries.return_value = GeneratedResearchQueries(
            domain_name=self.sample_config.domain_name,
            queries=("q1",),
            items=(ResearchQueryItem("q1", "other", "water"),),
        )
        self.mock_search_collector.collect_for_query.return_value = SearchSourceCollectionResult(
            query="q1", sources=(), failures=()
        )

        result = self.orchestrator.run_research(self.sample_config)

        # Verify research_service received domain_config
        call_kwargs = self.mock_research_service.run_patent_research.call_args.kwargs
        self.assertEqual(call_kwargs["theme"], self.sample_config)

        # Verify query_generator received domain_config
        gen_args = self.mock_query_generator.generate_queries.call_args[0]
        self.assertEqual(gen_args[0], self.sample_config)

        self.assertEqual(result.domain_config.domain_name, "Water Treatment")

    def test_invalid_domain_config_rejected(self) -> None:
        """Non-ResearchDomainConfig input raises TypeError."""
        for invalid in [None, "water", 123, {"domain": "Water"}]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    self.orchestrator.run_research(invalid)  # type: ignore

    def test_major_stage_failure_propagates_immediately(self) -> None:
        """Fatal error in any major stage (1, 2, 3, 4, 7) propagates out without being swallowed."""
        # Stage 1 failure
        self.mock_research_service.run_patent_research.side_effect = PatentResearchExecutionError("Stage 1 failed")
        with self.assertRaises(PatentResearchExecutionError):
            self.orchestrator.run_research(self.sample_config)

        # Reset Stage 1, fail Stage 2
        self.mock_research_service.run_patent_research.side_effect = None
        self.mock_research_service.run_patent_research.return_value = self.sample_patent_result
        self.mock_problem_extraction_service.extract_problems_for_run.side_effect = RuntimeError("Stage 2 DB crashed")
        with self.assertRaises(RuntimeError):
            self.orchestrator.run_research(self.sample_config)

        # Reset Stage 2, fail Stage 3
        self.mock_problem_extraction_service.extract_problems_for_run.side_effect = None
        self.mock_problem_extraction_service.extract_problems_for_run.return_value = [self.sample_problem]
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.side_effect = RuntimeError("Stage 3 AI failed")
        with self.assertRaises(RuntimeError):
            self.orchestrator.run_research(self.sample_config)

        # Reset Stage 3, fail Stage 4
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.side_effect = None
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = self.sample_opportunity
        self.mock_opportunity_evaluation_service.evaluate_opportunity.side_effect = RuntimeError("Stage 4 failed")
        with self.assertRaises(RuntimeError):
            self.orchestrator.run_research(self.sample_config)

    def test_web_source_failures_remain_isolated(self) -> None:
        """Web search retrieval failures remain isolated without terminating pipeline."""
        self.mock_research_service.run_patent_research.return_value = self.sample_patent_result
        self.mock_problem_extraction_service.extract_problems_for_run.return_value = [self.sample_problem]
        self.mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = self.sample_opportunity
        self.mock_opportunity_evaluation_service.evaluate_opportunity.return_value = self.sample_evaluation

        self.mock_query_generator.generate_queries.return_value = GeneratedResearchQueries(
            domain_name=self.sample_config.domain_name,
            queries=("q1_success", "q2_failing_url", "q3_query_exception"),
            items=(
                ResearchQueryItem("q1_success", "other", "water"),
                ResearchQueryItem("q2_failing_url", "other", "water"),
                ResearchQueryItem("q3_query_exception", "other", "water"),
            ),
        )

        def mock_collect(query, max_results):
            if query == "q1_success":
                return SearchSourceCollectionResult(
                    query=query,
                    sources=(self.sample_web_source,),
                    failures=(),
                )
            elif query == "q2_failing_url":
                return SearchSourceCollectionResult(
                    query=query,
                    sources=(),
                    failures=(
                        SourceCollectionFailure(
                            url="https://failed.example.com",
                            error_type="HTTP403",
                            error_message="Forbidden",
                        ),
                    ),
                )
            else:
                raise ConnectionError("DNS resolution failed for DDG query")

        self.mock_search_collector.collect_for_query.side_effect = mock_collect
        self.mock_web_evidence_analyzer.analyze.return_value = [self.sample_finding]

        result = self.orchestrator.run_research(self.sample_config, max_web_queries=3)

        # Pipeline completed despite web failures
        self.assertTrue(result.is_success)
        self.assertEqual(result.web_source_count, 1)
        self.assertEqual(result.web_failure_count, 2)
        self.assertEqual(result.market_finding_count, 1)
        self.mock_web_evidence_analyzer.analyze.assert_called_once()

    def test_to_dict_serialization(self) -> None:
        """ResearchOrchestrationResult serializes to dictionary cleanly."""
        result = ResearchOrchestrationResult(
            run_id="run-1",
            domain_config=self.sample_config,
            extracted_problems=(self.sample_problem,),
            synthesized_opportunities=(self.sample_opportunity,),
        )
        d = result.to_dict()
        self.assertEqual(d["run_id"], "run-1")
        self.assertEqual(d["domain_name"], "Water Treatment")
        self.assertEqual(d["problem_count"], 1)
        self.assertEqual(d["opportunity_count"], 1)
        self.assertEqual(len(d["extracted_problems"]), 1)


class TestProductionQueryAnchoringAndDomainVocabulary(unittest.TestCase):
    """Focused offline unit tests for production query anchoring and domain vocabulary propagation."""

    def test_production_generated_queries_use_subject_anchoring(self) -> None:
        """Production query generation enables quote_subject_anchor=True and passes anchored queries."""
        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-anchor-1",
            theme="Water",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )
        mock_problem_extraction_service = MagicMock(spec=ProblemExtractionService)
        mock_problem_extraction_service.extract_problems_for_run.return_value = []
        mock_opportunity_synthesis_service = MagicMock(spec=OpportunitySynthesisService)
        mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = None
        mock_opportunity_evaluation_service = MagicMock(spec=OpportunityEvaluationService)
        mock_opportunity_evaluation_service.evaluate_opportunity.return_value = None
        mock_search_collector = MagicMock(spec=SearchSourceCollector)
        mock_search_collector.collect_for_query.return_value = SearchSourceCollectionResult(
            query="test", sources=(), failures=()
        )
        mock_web_evidence_analyzer = MagicMock(spec=WebEvidenceAnalyzer)
        mock_web_evidence_analyzer.analyze.return_value = []

        # 1. Use real ResearchQueryGenerator to verify actual queries executed by the search collector
        real_query_generator = ResearchQueryGenerator()

        orchestrator = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=mock_problem_extraction_service,
            opportunity_synthesis_service=mock_opportunity_synthesis_service,
            opportunity_evaluation_service=mock_opportunity_evaluation_service,
            query_generator=real_query_generator,
            search_collector=mock_search_collector,
            web_evidence_analyzer=mock_web_evidence_analyzer,
        )

        domain_config = ResearchDomainConfig(
            domain_name="Industrial Desalination",
            themes=("membrane biofouling", "reverse osmosis flux"),
            description="Desalination filtration research",
        )

        result = orchestrator.run_research(domain_config, max_web_queries=4)

        self.assertTrue(result.is_success)
        self.assertGreater(mock_search_collector.collect_for_query.call_count, 0)
        executed_queries = [
            call.kwargs.get("query") if "query" in call.kwargs else call.args[0]
            for call in mock_search_collector.collect_for_query.call_args_list
        ]
        for q in executed_queries:
            self.assertTrue(
                q.startswith('"membrane biofouling"') or q.startswith('"reverse osmosis flux"'),
                f"Query '{q}' is missing quoted subject anchor.",
            )

        # 2. Verify quote_subject_anchor=True keyword is explicitly passed to query_generator
        mock_q_gen = MagicMock(spec=ResearchQueryGenerator)
        mock_q_gen.generate_queries.return_value = GeneratedResearchQueries(
            domain_name="Industrial Desalination",
            queries=('"membrane biofouling" competitors',),
            items=(ResearchQueryItem('"membrane biofouling" competitors', "competitor", "membrane biofouling"),),
        )
        orchestrator.query_generator = mock_q_gen
        orchestrator.run_research(domain_config, max_web_queries=2)
        mock_q_gen.generate_queries.assert_called_once_with(
            domain_config,
            max_queries=2,
            quote_subject_anchor=True,
        )

    def test_google_news_provider_receives_vocabulary_from_active_domain(self) -> None:
        """The active domain's subject terms are propagated to the Google News RSS provider."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
          <title>Google News</title>
          <item>
            <title>Advanced Desalination: Solving Membrane Biofouling in Reverse Osmosis</title>
            <link>https://waternews.example.com/biofouling-breakthrough</link>
            <pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate>
            <description>&lt;a href="https://waternews.example.com/biofouling-breakthrough"&gt;Breakthrough in membrane biofouling filtration.&lt;/a&gt;</description>
            <source url="https://waternews.example.com">Water News Daily</source>
          </item>
        </channel>
        </rss>"""

        gnews_provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: rss_xml,
            subject_terms=None,
        )
        search_collector = SearchSourceCollector(
            search_provider=gnews_provider,
            source_collector=MagicMock(spec=WebSourceCollector),
        )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-vocab-1",
            theme="Water",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )
        mock_problem_extraction_service = MagicMock(spec=ProblemExtractionService)
        mock_problem_extraction_service.extract_problems_for_run.return_value = []
        mock_opportunity_synthesis_service = MagicMock(spec=OpportunitySynthesisService)
        mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = None
        mock_opportunity_evaluation_service = MagicMock(spec=OpportunityEvaluationService)
        mock_opportunity_evaluation_service.evaluate_opportunity.return_value = None
        mock_web_evidence_analyzer = MagicMock(spec=WebEvidenceAnalyzer)
        mock_web_evidence_analyzer.analyze.return_value = []

        domain_config = ResearchDomainConfig(
            domain_name="Industrial Desalination",
            themes=("membrane biofouling", "reverse osmosis flux"),
            description="Desalination filtration research",
        )

        orchestrator = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=mock_problem_extraction_service,
            opportunity_synthesis_service=mock_opportunity_synthesis_service,
            opportunity_evaluation_service=mock_opportunity_evaluation_service,
            query_generator=ResearchQueryGenerator(),
            search_collector=search_collector,
            web_evidence_analyzer=mock_web_evidence_analyzer,
        )

        orchestrator.run_research(domain_config, max_web_queries=1)

        diag = gnews_provider.diagnostics
        self.assertIsNotNone(diag)
        self.assertEqual(diag.accepted_count, 1)
        self.assertIn("membrane biofouling", diag.decisions[0].matched_terms)
        self.assertIn("Matched configured subject term", diag.decisions[0].reason)

    def test_different_domain_configurations_do_not_contaminate_one_another(self) -> None:
        """Sequential runs with different domains do not leak vocabulary or state across runs."""
        water_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
          <title>Google News</title>
          <item>
            <title>Industrial Desalination Plant Expands Reverse Osmosis Capacity</title>
            <link>https://water.example.com/ro-plant</link>
            <pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate>
            <description>&lt;a href="https://water.example.com/ro-plant"&gt;Desalination capacity expands.&lt;/a&gt;</description>
            <source url="https://water.example.com">Water World</source>
          </item>
        </channel>
        </rss>"""

        cosmetics_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
          <title>Google News</title>
          <item>
            <title>New AI Skincare Diagnostic Startup Launches Retinol Formulation</title>
            <link>https://cosmetics.example.com/ai-skincare</link>
            <pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate>
            <description>&lt;a href="https://cosmetics.example.com/ai-skincare"&gt;AI skincare with retinol.&lt;/a&gt;</description>
            <source url="https://cosmetics.example.com">Beauty Tech</source>
          </item>
        </channel>
        </rss>"""

        current_xml = [water_rss_xml]

        shared_gnews_provider = GoogleNewsRSSSearchProvider(
            http_transport=lambda req, to: current_xml[0],
            subject_terms=None,
        )
        shared_collector = SearchSourceCollector(
            search_provider=shared_gnews_provider,
            source_collector=MagicMock(spec=WebSourceCollector),
        )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-isolation",
            theme="Test",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )
        mock_problem_extraction_service = MagicMock(spec=ProblemExtractionService)
        mock_problem_extraction_service.extract_problems_for_run.return_value = []
        mock_opportunity_synthesis_service = MagicMock(spec=OpportunitySynthesisService)
        mock_opportunity_synthesis_service.synthesize_opportunity_for_run.return_value = None
        mock_opportunity_evaluation_service = MagicMock(spec=OpportunityEvaluationService)
        mock_opportunity_evaluation_service.evaluate_opportunity.return_value = None
        mock_web_evidence_analyzer = MagicMock(spec=WebEvidenceAnalyzer)
        mock_web_evidence_analyzer.analyze.return_value = []

        orchestrator = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=mock_problem_extraction_service,
            opportunity_synthesis_service=mock_opportunity_synthesis_service,
            opportunity_evaluation_service=mock_opportunity_evaluation_service,
            query_generator=ResearchQueryGenerator(),
            search_collector=shared_collector,
            web_evidence_analyzer=mock_web_evidence_analyzer,
        )

        water_config = ResearchDomainConfig(
            domain_name="Water Treatment",
            themes=("desalination", "water purification"),
            description="Water research",
        )
        cosmetics_config = ResearchDomainConfig(
            domain_name="Cosmetics",
            themes=("skincare", "retinol"),
            description="Cosmetics research",
        )

        # Run 1: Water domain
        orchestrator.run_research(water_config, max_web_queries=1)
        water_diag = shared_gnews_provider.diagnostics
        self.assertIsNotNone(water_diag)
        self.assertEqual(water_diag.accepted_count, 1)
        self.assertIn("desalination", water_diag.decisions[0].matched_terms)

        # Assert shared provider state was not permanently modified
        self.assertIsNone(shared_gnews_provider.subject_terms)

        # Switch transport XML to cosmetics XML
        current_xml[0] = cosmetics_rss_xml

        # Run 2: Cosmetics domain on the SAME orchestrator and search stack
        orchestrator.run_research(cosmetics_config, max_web_queries=1)
        cosmetics_diag = shared_gnews_provider.diagnostics
        self.assertIsNotNone(cosmetics_diag)
        self.assertEqual(cosmetics_diag.accepted_count, 1)
        self.assertIn("skincare", cosmetics_diag.decisions[0].matched_terms)

        # Ensure NO residual water terms in cosmetics decision
        self.assertNotIn("desalination", cosmetics_diag.decisions[0].matched_terms)
        self.assertNotIn("water purification", cosmetics_diag.decisions[0].matched_terms)

        # Assert base provider attribute is still None
        self.assertIsNone(shared_gnews_provider.subject_terms)

    def test_existing_custom_provider_and_fallback_behaviour_remains_compatible(self) -> None:
        """Custom 2-arg providers, fallback composites, and legacy query generators work without error."""
        class LegacyCustomSearchProvider:
            """Provider implementing only traditional search(query, max_results)."""
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def search(self, query: str, max_results: int = 5) -> Sequence[SearchResult]:
                self.calls.append((query, max_results))
                return [
                    SearchResult(
                        url="https://legacy.example.com/article",
                        title="Legacy Result Title",
                        snippet="Legacy snippet text.",
                        domain="legacy.example.com",
                    )
                ]

        legacy_provider = LegacyCustomSearchProvider()
        fallback_composite = FallbackSearchProvider([legacy_provider])
        client = SearchClient(provider=fallback_composite)

        # 1. Calling search directly with subject_terms gracefully degrades for legacy provider
        results = client.search(
            query="test query",
            max_results=3,
            subject_terms=("water purification", "desalination"),
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://legacy.example.com/article")
        self.assertEqual(legacy_provider.calls, [("test query", 3)])

        # 2. SearchSourceCollector works with legacy provider
        collector = SearchSourceCollector(
            search_provider=legacy_provider,
            source_collector=MagicMock(spec=WebSourceCollector),
        )
        res = collector.collect_for_query(
            "test query",
            max_results=2,
            subject_terms=("water purification",),
        )
        self.assertEqual(len(res.search_results), 1)

        # 3. Legacy query generator without quote_subject_anchor arg handled gracefully in orchestrator
        class LegacyQueryGenerator:
            def generate_queries(self, domain_config, max_queries=10):
                return GeneratedResearchQueries(
                    domain_name=domain_config.domain_name,
                    queries=("legacy unquoted query",),
                    items=(ResearchQueryItem("legacy unquoted query", "other", "legacy"),),
                )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-legacy",
            theme="Test",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )
        mock_collector = MagicMock(spec=SearchSourceCollector)
        mock_collector.collect_for_query.return_value = SearchSourceCollectionResult(
            query="legacy unquoted query", sources=(), failures=()
        )

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=MagicMock(spec=ProblemExtractionService),
            opportunity_synthesis_service=MagicMock(spec=OpportunitySynthesisService),
            opportunity_evaluation_service=MagicMock(spec=OpportunityEvaluationService),
            query_generator=LegacyQueryGenerator(),
            search_collector=mock_collector,
            web_evidence_analyzer=MagicMock(spec=WebEvidenceAnalyzer),
        )
        orch_res = orch.run_research(
            ResearchDomainConfig(domain_name="D", themes=("T",), description="Desc")
        )
        self.assertTrue(orch_res.is_success)
        self.assertEqual(orch_res.query_count, 1)

        # 4. Caller not specifying quote_subject_anchor gets unquoted queries by default
        default_gen = ResearchQueryGenerator()
        default_queries = default_gen.generate_queries(
            ResearchDomainConfig(domain_name="D", themes=("purification",), description="Desc"),
            max_queries=2,
        )
        self.assertFalse(default_queries[0].startswith('"'))

    def test_internal_type_error_from_query_generator_propagates(self) -> None:
        """Internal TypeError from keyword-capable query generator propagates and is NOT swallowed."""
        class DefectiveQueryGenerator:
            def generate_queries(self, domain_config, max_queries=10, quote_subject_anchor=False):
                if quote_subject_anchor:
                    raise TypeError("Internal bug in query template: format string mismatch")
                return GeneratedResearchQueries(
                    domain_name=domain_config.domain_name,
                    queries=("unquoted fallback",),
                    items=(ResearchQueryItem("unquoted fallback", "other", "term"),),
                )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-type-err",
            theme="Test",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=MagicMock(spec=ProblemExtractionService),
            opportunity_synthesis_service=MagicMock(spec=OpportunitySynthesisService),
            opportunity_evaluation_service=MagicMock(spec=OpportunityEvaluationService),
            query_generator=DefectiveQueryGenerator(),
            search_collector=MagicMock(spec=SearchSourceCollector),
            web_evidence_analyzer=MagicMock(spec=WebEvidenceAnalyzer),
        )

        domain_config = ResearchDomainConfig(domain_name="D", themes=("T",), description="Desc")
        with self.assertRaises(TypeError) as ctx:
            orch.run_research(domain_config)

        self.assertIn("Internal bug in query template", str(ctx.exception))

    def test_internal_type_error_from_provider_in_fallback_composite_propagates(self) -> None:
        """Internal TypeError from keyword-capable provider inside FallbackSearchProvider propagates."""
        class DefectiveSearchProvider:
            name = "DefectiveSearchProvider"

            def search(self, query: str, max_results: int = 5, *, subject_terms=None):
                if subject_terms is not None:
                    raise TypeError("Internal scoring bug: 'NoneType' object is not subscriptable")
                return [
                    SearchResult(
                        url="https://defect.example.com",
                        title="Swallowed Result",
                        snippet="Snippet",
                        domain="defect.example.com",
                    )
                ]

        fallback = FallbackSearchProvider([DefectiveSearchProvider()])
        with self.assertRaises(TypeError) as ctx:
            fallback.search("test query", subject_terms=("water",))

        self.assertIn("Internal scoring bug", str(ctx.exception))

    def test_kwargs_query_generator_handled_correctly(self) -> None:
        """Query generator accepting **kwargs receives quote_subject_anchor=True."""
        received_kwargs = {}

        class KwargsQueryGenerator:
            def generate_queries(self, domain_config, max_queries=10, **kwargs):
                received_kwargs.update(kwargs)
                return GeneratedResearchQueries(
                    domain_name=domain_config.domain_name,
                    queries=('"theme" query',),
                    items=(ResearchQueryItem('"theme" query', "competitor", "theme"),),
                )

        mock_research_service = MagicMock(spec=ResearchService)
        mock_research_service.run_patent_research.return_value = PatentResearchResult(
            run_id="run-kwargs",
            theme="Test",
            generated_queries=(),
            executed_queries=(),
            discovered_count=1,
            ingested_count=1,
            inserted_count=1,
            existing_count=0,
            linked_count=1,
            final_run_status="completed",
        )
        mock_collector = MagicMock(spec=SearchSourceCollector)
        mock_collector.collect_for_query.return_value = SearchSourceCollectionResult(
            query="test", sources=(), failures=()
        )

        orch = ResearchOrchestrator(
            research_service=mock_research_service,
            problem_extraction_service=MagicMock(spec=ProblemExtractionService),
            opportunity_synthesis_service=MagicMock(spec=OpportunitySynthesisService),
            opportunity_evaluation_service=MagicMock(spec=OpportunityEvaluationService),
            query_generator=KwargsQueryGenerator(),
            search_collector=mock_collector,
            web_evidence_analyzer=MagicMock(spec=WebEvidenceAnalyzer),
        )

        orch.run_research(
            ResearchDomainConfig(domain_name="D", themes=("theme",), description="Desc")
        )
        self.assertTrue(received_kwargs.get("quote_subject_anchor"))


if __name__ == "__main__":
    unittest.main()


