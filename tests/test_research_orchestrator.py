"""Focused unit tests for the generic domain-agnostic ResearchOrchestrator."""

from unittest.mock import MagicMock
import unittest

from src.evaluation.evaluation_service import OpportunityEvaluationService
from src.evaluation.models import OpportunityEvaluationRecord
from src.market_research.models import MarketResearchRecord
from src.market_research.research_query_generator import (
    GeneratedResearchQueries,
    ResearchQueryGenerator,
    ResearchQueryItem,
)
from src.market_research.search_source_collector import (
    SearchSourceCollectionResult,
    SearchSourceCollector,
)
from src.market_research.source_collection import SourceCollectionFailure
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


if __name__ == "__main__":
    unittest.main()
