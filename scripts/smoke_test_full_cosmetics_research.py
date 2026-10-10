"""Controlled end-to-end smoke test for the full generic research pipeline using COSMETICS_RESEARCH_CONFIG.

Exercises the real ResearchOrchestrator coordinating:
1. Patent research (ResearchService -> InPassDiscoveryStrategy -> InPassIngestionService)
2. Problem extraction (ProblemExtractionService -> AntigravityAIClient)
3. Opportunity synthesis (OpportunitySynthesisService -> AntigravityAIClient)
4. Opportunity evaluation (OpportunityEvaluationService -> AntigravityAIClient)
5. Web query generation (ResearchQueryGenerator)
6. Web search & source collection (SearchSourceCollector -> DuckDuckGoHTMLSearchProvider)
7. Market research AI analysis (WebEvidenceAnalyzer -> MarketResearchService -> AntigravityAIClient)

Preserves human-in-the-loop CAPTCHA interaction for InPASS and uses an isolated SQLite
database to prevent polluting the production database.
"""

from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, Optional
import uuid

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Line buffering for immediate console output in background tasks
sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("smoke_test_full_cosmetics_research")

from src.common.database import init_db
from src.common.research_runs import ResearchRunService
from src.evaluation.evaluation_service import OpportunityEvaluationService
from src.evaluation.repository import OpportunityEvaluationRepository
from src.market_research.fallback_search_provider import create_default_search_provider
from src.market_research.repository import MarketResearchRepository
from src.market_research.research_query_generator import ResearchQueryGenerator
from src.market_research.search_source_collector import SearchSourceCollector
from src.market_research.service import MarketResearchService
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.repository import OpportunityRepository
from src.opportunities.synthesis_service import OpportunitySynthesisService
from src.patents.discovery_strategy import InPassDiscoveryResult, InPassDiscoveryStrategy
from src.patents.inpass_client import InPassClient
from src.patents.inpass_ingestion_service import InPassIngestionService
from src.patents.repository import PatentRepository
from src.patents.research_config import COSMETICS_RESEARCH_CONFIG
from src.patents.run_reader import ResearchRunPatentReader
from src.problems.ai_client import AntigravityAIClient
from src.problems.extraction_service import ProblemExtractionService
from src.problems.repository import ProblemRepository
from src.research.research_orchestrator import (
    ResearchOrchestrationResult,
    ResearchOrchestrator,
)
from src.research.research_service import ResearchService

ARTIFACT_DIR = Path(r"C:\Users\gowth\.gemini\antigravity-ide\brain\a9ffa234-818f-4260-a870-f0bf1ac3b53e")


def solve_captcha_interactive(image_path: str) -> str:
    """Human-in-the-loop CAPTCHA solver exposing the image to artifacts and prompting stdin."""
    print(f"\n[CAPTCHA CAPTURED] Raw Image: {image_path}", flush=True)
    artifact_captcha = ARTIFACT_DIR / "inpass_captcha.png"
    try:
        shutil.copyfile(image_path, artifact_captcha)
        print(f"[CAPTCHA EXPOSED] Artifact Image: {artifact_captcha}", flush=True)
    except Exception as exc:
        print(f"[Warning] Failed to copy artifact image: {exc}", flush=True)

    print("\n=================================================================", flush=True)
    print(">>> HUMAN-IN-THE-LOOP CHECKPOINT: InPASS CAPTCHA REQUIRED <<<", flush=True)
    print(f"Please inspect {artifact_captcha} and provide the code.", flush=True)
    print(">>> WAITING_FOR_CAPTCHA_INPUT <<<", flush=True)
    print("=================================================================\n", flush=True)
    sys.stdout.flush()

    try:
        user_code = input("Please enter the CAPTCHA text: ").strip()
    except EOFError:
        print("[Warning] EOF encountered reading CAPTCHA input.", flush=True)
        user_code = ""

    print(f"[CAPTCHA ENTERED] Code submitted: '{user_code}'", flush=True)
    return user_code


class HumanInTheLoopInPassDiscoveryStrategy(InPassDiscoveryStrategy):
    """Preserves human-in-the-loop CAPTCHA interaction through dependency injection."""

    def __init__(
        self,
        captcha_solver: Optional[Callable[[str], str]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.active_captcha_solver = captcha_solver

    def discover_for_run(self, *args: Any, **kwargs: Any) -> InPassDiscoveryResult:
        if kwargs.get("captcha_solver") is None and self.active_captcha_solver is not None:
            kwargs["captcha_solver"] = self.active_captcha_solver
        return super().discover_for_run(*args, **kwargs)


class TrackingSearchSourceCollector(SearchSourceCollector):
    """SearchSourceCollector recording per-query search and retrieval metrics."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.query_telemetry: list[dict[str, Any]] = []

    def collect_for_query(self, query: str, max_results: int = 5, *args: Any, **kwargs: Any) -> Any:
        time.sleep(1.0)
        res = super().collect_for_query(query=query, max_results=max_results, *args, **kwargs)
        self.query_telemetry.append({
            "query": query,
            "search_results_count": len(res.search_results),
            "sources_count": len(res.sources),
            "failures_count": len(res.failures),
        })
        return res


def run_full_cosmetics_research_smoke_test() -> ResearchOrchestrationResult:
    """Execute the end-to-end generic research pipeline for COSMETICS_RESEARCH_CONFIG."""
    print("=" * 80, flush=True)
    print("END-TO-END RESEARCH PIPELINE SMOKE TEST", flush=True)
    print(f"Domain: {COSMETICS_RESEARCH_CONFIG.domain_name}", flush=True)
    print(f"Description: {COSMETICS_RESEARCH_CONFIG.description}", flush=True)
    print("=" * 80, flush=True)

    # 1. Setup isolated SQLite database
    temp_dir = Path(tempfile.gettempdir())
    isolated_db_path = temp_dir / f"smoke_test_full_cosmetics_{uuid.uuid4().hex[:8]}.db"
    print(f"\n[Isolation] Initializing isolated database at: {isolated_db_path}", flush=True)
    init_db(isolated_db_path)

    # 2. Instantiate isolated repositories and database services
    run_service = ResearchRunService(db_path=isolated_db_path)
    patent_repo = PatentRepository(db_path=isolated_db_path)
    patent_reader = ResearchRunPatentReader(db_path=isolated_db_path)
    problem_repo = ProblemRepository(db_path=isolated_db_path)
    opportunity_repo = OpportunityRepository(db_path=isolated_db_path)
    evaluation_repo = OpportunityEvaluationRepository(db_path=isolated_db_path)
    market_research_repo = MarketResearchRepository(db_path=isolated_db_path)

    # 3. Instantiate real AI client
    print("[AI Client] Initializing AntigravityAIClient (gemini-3.8-flash-low)...", flush=True)
    ai_client = AntigravityAIClient(model="gemini-3.8-flash-low")

    # 4. Instantiate Stage 1: Patent Research Service with human-in-the-loop InPASS strategy
    print("[Stage 1 Setup] Initializing InPass Discovery Strategy & ResearchService...", flush=True)
    inpass_client = InPassClient()
    ingestion_service = InPassIngestionService(client=inpass_client, repository=patent_repo)
    discovery_strategy = HumanInTheLoopInPassDiscoveryStrategy(
        captcha_solver=solve_captcha_interactive,
        ingestion_service=ingestion_service,
        client=inpass_client,
        research_config=COSMETICS_RESEARCH_CONFIG,
    )
    research_service = ResearchService(
        db_path=isolated_db_path,
        run_service=run_service,
        discovery_strategy=discovery_strategy,
        research_config=COSMETICS_RESEARCH_CONFIG,
    )

    # 5. Instantiate Stage 2: Problem Extraction Service
    print("[Stage 2 Setup] Initializing ProblemExtractionService...", flush=True)
    problem_service = ProblemExtractionService(
        ai_client=ai_client,
        repository=problem_repo,
        patent_reader=patent_reader,
    )

    # 6. Instantiate Stage 3: Opportunity Synthesis Service
    print("[Stage 3 Setup] Initializing OpportunitySynthesisService...", flush=True)
    opportunity_service = OpportunitySynthesisService(
        ai_client=ai_client,
        problem_repository=problem_repo,
        opportunity_repository=opportunity_repo,
    )

    # 7. Instantiate Stage 4: Opportunity Evaluation Service
    print("[Stage 4 Setup] Initializing OpportunityEvaluationService...", flush=True)
    evaluation_service = OpportunityEvaluationService(
        ai_client=ai_client,
        opportunity_repository=opportunity_repo,
        problem_repository=problem_repo,
        evaluation_repository=evaluation_repo,
    )

    # 8. Instantiate Stage 5: Web Query Generator
    print("[Stage 5 Setup] Initializing ResearchQueryGenerator...", flush=True)
    query_generator = ResearchQueryGenerator()

    # 9. Instantiate Stage 6: Resilient Fallback Search Source Collector with telemetry tracking
    print("[Stage 6 Setup] Initializing Fallback Search Provider (DDG + Google News RSS) & TrackingSearchSourceCollector...", flush=True)
    search_provider = create_default_search_provider()
    search_collector = TrackingSearchSourceCollector(search_provider=search_provider)

    # 10. Instantiate Stage 7: Market Research AI Service & Web Evidence Analyzer
    print("[Stage 7 Setup] Initializing MarketResearchService & WebEvidenceAnalyzer...", flush=True)
    market_service = MarketResearchService(
        ai_client=ai_client,
        market_research_repository=market_research_repo,
    )
    web_evidence_analyzer = WebEvidenceAnalyzer(
        market_research_service=market_service,
    )

    # 11. Assemble ResearchOrchestrator
    print("\n[Orchestrator Setup] Initializing ResearchOrchestrator...", flush=True)
    orchestrator = ResearchOrchestrator(
        research_service=research_service,
        problem_extraction_service=problem_service,
        opportunity_synthesis_service=opportunity_service,
        opportunity_evaluation_service=evaluation_service,
        query_generator=query_generator,
        search_collector=search_collector,
        web_evidence_analyzer=web_evidence_analyzer,
        db_path=isolated_db_path,
    )

    # 12. Execute controlled research pipeline (depth: 7 queries across all categories, 3 results per query)
    print("\n" + "-" * 80, flush=True)
    print("Executing Research Pipeline (Depth: 1 patent query, 1 patent result, 7 web queries across all categories, 3 results/query)...", flush=True)
    print("-" * 80 + "\n", flush=True)

    try:
        result = orchestrator.run_research(
            domain_config=COSMETICS_RESEARCH_CONFIG,
            max_patent_queries=1,
            max_patents_per_query=1,
            max_web_queries=7,
            max_web_results_per_query=3,
            raise_on_major_failure=True,
        )

        # 13. Verify internal consistency of ResearchOrchestrationResult
        print("\n" + "-" * 80, flush=True)
        print("Validating Result Consistency...", flush=True)
        print("-" * 80, flush=True)

        assert isinstance(result, ResearchOrchestrationResult), "Result must be a ResearchOrchestrationResult instance."
        assert result.status == "completed", f"Status must be 'completed', got {result.status}"
        assert result.error is None, f"Expected no error, got: {result.error}"
        assert result.is_success, "Result is_success must be True."
        assert result.domain_config == COSMETICS_RESEARCH_CONFIG, "Domain config must match."
        assert result.problem_count == len(result.extracted_problems), "problem_count mismatch."
        assert result.opportunity_count == len(result.synthesized_opportunities), "opportunity_count mismatch."
        assert result.evaluation_count == len(result.opportunity_evaluations), "evaluation_count mismatch."
        assert result.query_count == len(result.generated_search_queries), "query_count mismatch."
        assert result.web_source_count == len(result.collected_web_sources), "web_source_count mismatch."
        assert result.web_failure_count == len(result.web_collection_failures), "web_failure_count mismatch."
        assert result.market_finding_count == len(result.market_research_findings), "market_finding_count mismatch."
        print("All internal consistency checks PASSED!", flush=True)

        # 14. Print detailed per-query search telemetry
        print("\n" + "=" * 80, flush=True)
        print("WEB MARKET RESEARCH QUERY TELEMETRY (7 CATEGORIES)", flush=True)
        print("=" * 80, flush=True)
        for idx, item in enumerate(search_collector.query_telemetry, 1):
            print(f"[{idx}] Query: '{item['query']}'")
            print(f"    - Search results discovered: {item['search_results_count']}")
            print(f"    - Successfully fetched sources: {item['sources_count']}")
            print(f"    - Failed sources: {item['failures_count']}")

        # 15. Print concise structured summary
        print("\n" + "=" * 80, flush=True)
        print("RESEARCH PIPELINE EXECUTION SUMMARY", flush=True)
        print("=" * 80, flush=True)
        print(f"1. Research run ID: {result.run_id}")
        discovered_count = result.patent_research_result.discovered_count if result.patent_research_result else 0
        print(f"2. Number of patents discovered: {discovered_count}")
        print(f"3. Number of problems extracted: {result.problem_count}")
        print(f"4. Number of opportunities synthesized: {result.opportunity_count}")
        print(f"5. Number of opportunities evaluated: {result.evaluation_count}")
        print(f"6. Number of web queries generated: {result.query_count}")
        print(f"7. Total unique web sources collected: {result.web_source_count}")
        print(f"8. Total collection failures: {result.web_failure_count}")
        print(f"9. Number of AI market research findings: {result.market_finding_count}")

        print("\n10. Titles of generated opportunities:")
        if result.synthesized_opportunities:
            for idx, opp in enumerate(result.synthesized_opportunities, 1):
                print(f"    [{idx}] {opp.opportunity_title}")
        else:
            print("    (None)")

        print("\n11. Evaluation recommendation/score for each opportunity:")
        if result.opportunity_evaluations:
            for idx, ev in enumerate(result.opportunity_evaluations, 1):
                print(f"    [{idx}] Opportunity ID: {ev.opportunity_id}")
                print(f"        Overall Score: {ev.overall_score} / 100")
                print(f"        Recommendation: {ev.recommendation.upper()}")
                if ev.rationale:
                    print(f"        Rationale: {ev.rationale[:140]}...")
        else:
            print("    (None)")

        print("\n12. AI Market Research Findings (Source / Company / Product & Relevance):")
        if result.market_research_findings:
            for idx, finding in enumerate(result.market_research_findings, 1):
                print(f"    [{idx}] Company / Product: {finding.company_or_product}")
                print(f"        Source: {finding.source_name} ({finding.source_type})")
                print(f"        URL: {finding.source_url}")
                print(f"        Relevance: {finding.relevance}")
                print(f"        Key Insight: {finding.finding}")
                if finding.evidence_summary:
                    print(f"        Evidence Summary: {finding.evidence_summary[:140]}...")
        else:
            print("    (None)")

        print("=" * 80, flush=True)
        return result
    finally:
        inpass_client.close_browser()


if __name__ == "__main__":
    try:
        run_full_cosmetics_research_smoke_test()
    except Exception as exc:
        print(f"\n[FATAL SMOKE TEST FAILURE] {type(exc).__name__}: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
