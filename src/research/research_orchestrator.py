"""Generic domain-agnostic research orchestration layer.

Coordinates the end-to-end research pipeline across seven stages:
1. Patent research for the domain
2. Problem extraction from discovered patents
3. Opportunity synthesis from extracted problems
4. Opportunity evaluation for synthesized opportunities
5. Web research query generation from domain config
6. Web source search and collection
7. Market research AI analysis on collected web evidence and opportunities
"""

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any, Optional, Sequence

from config.settings import DATABASE_PATH
from src.evaluation.evaluation_service import OpportunityEvaluationService
from src.evaluation.models import OpportunityEvaluationRecord
from src.market_research.models import MarketResearchRecord
from src.market_research.research_query_generator import ResearchQueryGenerator
from src.market_research.search_client import (
    SearchClient,
    SearchProvider,
    callable_accepts_kwarg,
)
from src.market_research.search_source_collector import SearchSourceCollector
from src.market_research.source_collection import SourceCollectionFailure
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.models import OpportunityRecord
from src.opportunities.synthesis_service import OpportunitySynthesisService
from src.patents.research_config import ResearchDomainConfig
from src.problems.extraction_service import ProblemExtractionService
from src.problems.models import ProblemRecord
from src.research.research_service import PatentResearchResult, ResearchService

logger = logging.getLogger(__name__)


class ResearchOrchestratorError(Exception):
    """Base exception for research orchestration pipeline failures."""
    pass


@dataclass(frozen=True)
class ResearchOrchestrationResult:
    """Immutable consolidated results and telemetry from the end-to-end research pipeline.

    Attributes:
        run_id: Unique identifier of the associated research run.
        domain_config: The ResearchDomainConfig executed.
        patent_research_result: Telemetry from the patent discovery and ingestion stage.
        extracted_problems: Tuple of ProblemRecords extracted from discovered patents.
        synthesized_opportunities: Tuple of OpportunityRecords synthesized from problem leads.
        opportunity_evaluations: Tuple of OpportunityEvaluationRecords scored across venture dimensions.
        generated_search_queries: Tuple of search queries generated for web research.
        collected_web_sources: Tuple of WebResearchSources successfully retrieved from public web.
        web_collection_failures: Tuple of collection failures encountered during web retrieval.
        market_research_findings: Tuple of MarketResearchRecords produced by market AI analysis.
        status: Final execution status ('completed' or 'failed').
        error: Optional failure message if a stage encountered an unrecoverable error.
    """

    run_id: str
    domain_config: ResearchDomainConfig
    patent_research_result: Optional[PatentResearchResult] = None
    extracted_problems: tuple[ProblemRecord, ...] = field(default_factory=tuple)
    synthesized_opportunities: tuple[OpportunityRecord, ...] = field(default_factory=tuple)
    opportunity_evaluations: tuple[OpportunityEvaluationRecord, ...] = field(default_factory=tuple)
    generated_search_queries: tuple[str, ...] = field(default_factory=tuple)
    collected_web_sources: tuple[WebResearchSource, ...] = field(default_factory=tuple)
    web_collection_failures: tuple[SourceCollectionFailure, ...] = field(default_factory=tuple)
    market_research_findings: tuple[MarketResearchRecord, ...] = field(default_factory=tuple)
    status: str = "completed"
    error: Optional[str] = None

    @property
    def problem_count(self) -> int:
        """Total number of problems extracted."""
        return len(self.extracted_problems)

    @property
    def opportunity_count(self) -> int:
        """Total number of opportunities synthesized."""
        return len(self.synthesized_opportunities)

    @property
    def evaluation_count(self) -> int:
        """Total number of evaluations performed."""
        return len(self.opportunity_evaluations)

    @property
    def query_count(self) -> int:
        """Total number of web search queries generated."""
        return len(self.generated_search_queries)

    @property
    def web_source_count(self) -> int:
        """Total number of web sources successfully collected."""
        return len(self.collected_web_sources)

    @property
    def web_failure_count(self) -> int:
        """Total number of web source collection failures."""
        return len(self.web_collection_failures)

    @property
    def market_finding_count(self) -> int:
        """Total number of market research findings generated."""
        return len(self.market_research_findings)

    @property
    def is_success(self) -> bool:
        """True if the orchestrated pipeline completed successfully without fatal error."""
        return self.status == "completed" and self.error is None

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a dictionary."""
        return {
            "run_id": self.run_id,
            "domain_name": self.domain_config.domain_name,
            "status": self.status,
            "error": self.error,
            "problem_count": self.problem_count,
            "opportunity_count": self.opportunity_count,
            "evaluation_count": self.evaluation_count,
            "query_count": self.query_count,
            "web_source_count": self.web_source_count,
            "web_failure_count": self.web_failure_count,
            "market_finding_count": self.market_finding_count,
            "patent_research": self.patent_research_result.to_dict() if self.patent_research_result else None,
            "extracted_problems": [p.to_dict() for p in self.extracted_problems],
            "synthesized_opportunities": [o.to_dict() for o in self.synthesized_opportunities],
            "opportunity_evaluations": [e.to_dict() for e in self.opportunity_evaluations],
            "generated_search_queries": list(self.generated_search_queries),
            "collected_web_sources": [s.to_dict() for s in self.collected_web_sources],
            "web_collection_failures": [f.to_dict() for f in self.web_collection_failures],
            "market_research_findings": [m.to_dict() for m in self.market_research_findings],
        }


class ResearchOrchestrator:
    """Orchestrates the domain-agnostic end-to-end research workflow."""

    def __init__(
        self,
        research_service: Optional[ResearchService] = None,
        problem_extraction_service: Optional[ProblemExtractionService] = None,
        opportunity_synthesis_service: Optional[OpportunitySynthesisService] = None,
        opportunity_evaluation_service: Optional[OpportunityEvaluationService] = None,
        query_generator: Optional[ResearchQueryGenerator] = None,
        search_collector: Optional[SearchSourceCollector] = None,
        web_evidence_analyzer: Optional[WebEvidenceAnalyzer] = None,
        *,
        search_provider: Optional[SearchProvider] = None,
        search_client: Optional[SearchClient] = None,
        db_path: Optional[Path | str] = None,
    ) -> None:
        """Initialize ResearchOrchestrator with explicit dependency injection.

        Args:
            research_service: Service managing patent research runs and InPASS ingestion.
            problem_extraction_service: Service extracting ProblemRecords from patents.
            opportunity_synthesis_service: Service synthesizing OpportunityRecords from problems.
            opportunity_evaluation_service: Service evaluating opportunities across venture dimensions.
            query_generator: Generator for web search queries.
            search_collector: Collector coordinating web searching and page retrieval.
            web_evidence_analyzer: Analyzer connecting web sources to market research AI service.
            search_provider: Optional custom SearchProvider (e.g. FallbackSearchProvider).
            search_client: Optional custom SearchClient.
            db_path: Optional SQLite database path used for default components.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH
        self.research_service = research_service or ResearchService(db_path=self.db_path)
        self.problem_extraction_service = problem_extraction_service
        self.opportunity_synthesis_service = opportunity_synthesis_service
        self.opportunity_evaluation_service = opportunity_evaluation_service
        self.query_generator = query_generator or ResearchQueryGenerator()
        if search_collector is not None:
            self.search_collector = search_collector
        elif search_client is not None or search_provider is not None:
            self.search_collector = SearchSourceCollector(
                search_client=search_client,
                search_provider=search_provider,
            )
        else:
            self.search_collector = SearchSourceCollector()
        self.web_evidence_analyzer = web_evidence_analyzer

    def run_research(
        self,
        domain_config: ResearchDomainConfig,
        *,
        max_patent_queries: int = 4,
        max_patents_per_query: int = 3,
        max_web_queries: int = 3,
        max_web_results_per_query: int = 3,
        raise_on_major_failure: bool = True,
    ) -> ResearchOrchestrationResult:
        """Execute the complete end-to-end research workflow for a domain configuration.

        Execution stages in strict sequence:
        1. Patent research discovery & ingestion.
        2. Problem extraction from discovered patents.
        3. Opportunity synthesis from problem leads.
        4. Opportunity evaluation across venture dimensions.
        5. Web research query generation.
        6. Web search and source collection (with per-source failure isolation).
        7. Market research AI analysis on collected web evidence and opportunities.

        Args:
            domain_config: Configuration defining themes, keywords, and parameters for the domain.
            max_patent_queries: Maximum number of patent queries to execute.
            max_patents_per_query: Maximum patent records to fetch per query.
            max_web_queries: Maximum web search queries to execute.
            max_web_results_per_query: Maximum web search results to fetch per query.
            raise_on_major_failure: If True, major stage exceptions propagate out immediately.

        Returns:
            ResearchOrchestrationResult: Structured result aggregating all stage outputs.

        Raises:
            TypeError: If domain_config is not a ResearchDomainConfig instance.
            Exception: If any major stage fails and raise_on_major_failure is True.
        """
        if not isinstance(domain_config, ResearchDomainConfig):
            raise TypeError(
                f"domain_config must be a ResearchDomainConfig instance, got {type(domain_config).__name__}."
            )

        logger.info("Starting generic research pipeline for domain: '%s'", domain_config.domain_name)

        # ---------------------------------------------------------------------
        # Stage 1: Patent Research
        # ---------------------------------------------------------------------
        logger.info("Stage 1/7: Executing patent research...")
        patent_result = self.research_service.run_patent_research(
            theme=domain_config,
            max_queries=max_patent_queries,
            max_results_per_query=max_patents_per_query,
            raise_on_error=raise_on_major_failure,
        )
        run_id = patent_result.run_id

        # ---------------------------------------------------------------------
        # Stage 2: Problem Extraction
        # ---------------------------------------------------------------------
        extracted_problems: list[ProblemRecord] = []
        if self.problem_extraction_service is not None:
            logger.info("Stage 2/7: Extracting problems from patents for run '%s'...", run_id)
            try:
                extracted_problems = self.problem_extraction_service.extract_problems_for_run(run_id=run_id)
            except Exception as exc:
                logger.error("Stage 2 failed for run '%s': %s", run_id, exc)
                if raise_on_major_failure:
                    raise
        else:
            logger.warning("No ProblemExtractionService provided; skipping Stage 2.")

        # ---------------------------------------------------------------------
        # Stage 3: Opportunity Synthesis
        # ---------------------------------------------------------------------
        synthesized_opportunities: list[OpportunityRecord] = []
        if self.opportunity_synthesis_service is not None and extracted_problems:
            logger.info("Stage 3/7: Synthesizing opportunities from %d problems...", len(extracted_problems))
            try:
                if (
                    len(extracted_problems) > 1
                    and hasattr(self.opportunity_synthesis_service, "synthesize_multiple_opportunities_for_run")
                ):
                    opps = self.opportunity_synthesis_service.synthesize_multiple_opportunities_for_run(run_id=run_id)
                    synthesized_opportunities.extend(opps)
                else:
                    opp = self.opportunity_synthesis_service.synthesize_opportunity_for_run(run_id=run_id)
                    if opp:
                        synthesized_opportunities.append(opp)
            except Exception as exc:
                logger.error("Stage 3 failed for run '%s': %s", run_id, exc)
                if raise_on_major_failure:
                    raise
        else:
            logger.info("Skipping Stage 3 (no problems extracted or service not configured).")

        # ---------------------------------------------------------------------
        # Stage 4: Opportunity Evaluation
        # ---------------------------------------------------------------------
        evaluations: list[OpportunityEvaluationRecord] = []
        if self.opportunity_evaluation_service is not None and synthesized_opportunities:
            logger.info("Stage 4/7: Evaluating %d synthesized opportunities...", len(synthesized_opportunities))
            for opp in synthesized_opportunities:
                if opp.id:
                    try:
                        ev = self.opportunity_evaluation_service.evaluate_opportunity(opp.id)
                        evaluations.append(ev)
                    except Exception as exc:
                        logger.error("Stage 4 evaluation failed for opportunity '%s': %s", opp.id, exc)
                        if raise_on_major_failure:
                            raise
        else:
            logger.info("Skipping Stage 4 (no opportunities synthesized or service not configured).")

        # ---------------------------------------------------------------------
        # Stage 5: Web Research Query Generation
        # ---------------------------------------------------------------------
        logger.info("Stage 5/7: Generating web research queries for domain '%s'...", domain_config.domain_name)
        if callable_accepts_kwarg(self.query_generator.generate_queries, "quote_subject_anchor"):
            queries_result = self.query_generator.generate_queries(
                domain_config,
                max_queries=max_web_queries,
                quote_subject_anchor=True,
            )
        else:
            queries_result = self.query_generator.generate_queries(
                domain_config,
                max_queries=max_web_queries,
            )
        web_queries = list(queries_result.queries)

        # ---------------------------------------------------------------------
        # Stage 6: Web Search and Source Collection (with failure isolation)
        # ---------------------------------------------------------------------
        collected_sources: list[WebResearchSource] = []
        collection_failures: list[SourceCollectionFailure] = []
        seen_urls: set[str] = set()
        domain_subject_terms = tuple(domain_config.themes)
        accepts_subjects = callable_accepts_kwarg(
            self.search_collector.collect_for_query, "subject_terms"
        )

        logger.info("Stage 6/7: Collecting web sources across %d queries...", len(web_queries))
        for q in web_queries[:max_web_queries]:
            try:
                if accepts_subjects and domain_subject_terms is not None:
                    col_res = self.search_collector.collect_for_query(
                        query=q,
                        max_results=max_web_results_per_query,
                        subject_terms=domain_subject_terms,
                    )
                else:
                    col_res = self.search_collector.collect_for_query(
                        query=q,
                        max_results=max_web_results_per_query,
                    )
                for s in col_res.sources:
                    if s.url not in seen_urls:
                        seen_urls.add(s.url)
                        collected_sources.append(s)
                collection_failures.extend(col_res.failures)
            except Exception as exc:
                logger.warning("Web search collection error on query '%s': %s", q, exc)
                collection_failures.append(
                    SourceCollectionFailure(
                        url=q,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )

        # ---------------------------------------------------------------------
        # Stage 7: Market Research AI Analysis
        # ---------------------------------------------------------------------
        market_findings: list[MarketResearchRecord] = []
        if self.web_evidence_analyzer is not None and collected_sources:
            target_opps = synthesized_opportunities
            if not target_opps:
                # Synthesize a fallback opportunity using run_id and domain name so web evidence can still be analyzed
                fallback_opp = OpportunityRecord(
                    opportunity_title=f"{domain_config.domain_name} Innovation Opportunity",
                    solution_concept=f"Venture opportunity synthesized for {domain_config.domain_name} domain.",
                    target_customer="Target enterprise and commercial customers",
                    value_proposition=f"Commercial solutions addressing bottleneck in {domain_config.domain_name}.",
                    source_problem_ids=(f"lead-{run_id}",),
                    id=f"opp-{run_id}",
                )
                target_opps = [fallback_opp]

            logger.info("Stage 7/7: Analyzing web evidence across %d opportunities...", len(target_opps))
            for opp in target_opps:
                opp_id = opp.id or f"opp-{run_id}"
                try:
                    findings = self.web_evidence_analyzer.analyze(
                        opportunity_id=opp_id,
                        sources=collected_sources,
                        opportunity=opp,
                    )
                    market_findings.extend(findings)
                except Exception as exc:
                    logger.error("Stage 7 market research failed for opportunity '%s': %s", opp_id, exc)
                    if raise_on_major_failure:
                        raise
        else:
            logger.info("Skipping Stage 7 (no web sources collected or analyzer not configured).")

        logger.info("Pipeline completed successfully for run '%s'.", run_id)

        # ---------------------------------------------------------------------
        # Stage 8: Structured Result
        # ---------------------------------------------------------------------
        return ResearchOrchestrationResult(
            run_id=run_id,
            domain_config=domain_config,
            patent_research_result=patent_result,
            extracted_problems=tuple(extracted_problems),
            synthesized_opportunities=tuple(synthesized_opportunities),
            opportunity_evaluations=tuple(evaluations),
            generated_search_queries=tuple(web_queries),
            collected_web_sources=tuple(collected_sources),
            web_collection_failures=tuple(collection_failures),
            market_research_findings=tuple(market_findings),
            status="completed",
            error=None,
        )

    # Convenience alias
    orchestrate_research = run_research
