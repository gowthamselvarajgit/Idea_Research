"""Real, persisted cosmetics research experiment using the Patent -> Problem -> Opportunity Engine.

Executes a complete end-to-end research cycle against data/research_engine.db:
1. Patent research (Stage 1: InPASS Discovery -> InPassIngestionService)
2. Problem extraction (Stage 2: ProblemExtractionService -> AntigravityAIClient)
3. Opportunity synthesis (Stage 3: OpportunitySynthesisService -> AntigravityAIClient)
4. Opportunity evaluation (Stage 4: OpportunityEvaluationService -> AntigravityAIClient)
5. Web query generation (Stage 5: ResearchQueryGenerator)
6. Web search & source collection (Stage 6: SearchSourceCollector -> DDG + Google News RSS + URL Resolver)
7. Market research AI analysis (Stage 7: WebEvidenceAnalyzer -> MarketResearchService -> AntigravityAIClient)

Persists all records to the production database (data/research_engine.db) without overwriting past runs.
"""

from dataclasses import asdict
import json
import logging
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Callable, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Line buffering for immediate console output in background tasks
sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("persisted_cosmetics_experiment")

from config.settings import DATABASE_PATH
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
        time.sleep(0.5)
        res = super().collect_for_query(query=query, max_results=max_results, *args, **kwargs)
        self.query_telemetry.append({
            "query": query,
            "search_results_count": len(res.search_results),
            "sources_count": len(res.sources),
            "failures_count": len(res.failures),
        })
        return res


def run_experiment() -> ResearchOrchestrationResult:
    """Run full persisted research experiment for cosmetics domain."""
    print("=" * 80, flush=True)
    print("PERSISTED STARTUP OPPORTUNITY RESEARCH EXPERIMENT", flush=True)
    print(f"Domain: {COSMETICS_RESEARCH_CONFIG.domain_name}", flush=True)
    print(f"Database: {DATABASE_PATH}", flush=True)
    print("=" * 80, flush=True)

    # 1. Initialize production database schema
    init_db(DATABASE_PATH)

    # 2. Instantiate database services and repositories pointing to production DB
    run_service = ResearchRunService(db_path=DATABASE_PATH)
    patent_repo = PatentRepository(db_path=DATABASE_PATH)
    patent_reader = ResearchRunPatentReader(db_path=DATABASE_PATH)
    problem_repo = ProblemRepository(db_path=DATABASE_PATH)
    opportunity_repo = OpportunityRepository(db_path=DATABASE_PATH)
    evaluation_repo = OpportunityEvaluationRepository(db_path=DATABASE_PATH)
    market_research_repo = MarketResearchRepository(db_path=DATABASE_PATH)

    # 3. Instantiate real AI client
    print("[AI Client] Initializing AntigravityAIClient (gemini-3.8-flash-low)...", flush=True)
    ai_client = AntigravityAIClient(model="gemini-3.8-flash-low")

    # 4. Stage 1: Patent Research
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
        db_path=DATABASE_PATH,
        run_service=run_service,
        discovery_strategy=discovery_strategy,
        research_config=COSMETICS_RESEARCH_CONFIG,
    )

    # 5. Stage 2: Problem Extraction
    print("[Stage 2 Setup] Initializing ProblemExtractionService...", flush=True)
    problem_service = ProblemExtractionService(
        ai_client=ai_client,
        repository=problem_repo,
        patent_reader=patent_reader,
    )

    # 6. Stage 3: Opportunity Synthesis
    print("[Stage 3 Setup] Initializing OpportunitySynthesisService...", flush=True)
    opportunity_service = OpportunitySynthesisService(
        ai_client=ai_client,
        problem_repository=problem_repo,
        opportunity_repository=opportunity_repo,
    )

    # 7. Stage 4: Opportunity Evaluation
    print("[Stage 4 Setup] Initializing OpportunityEvaluationService...", flush=True)
    evaluation_service = OpportunityEvaluationService(
        ai_client=ai_client,
        opportunity_repository=opportunity_repo,
        problem_repository=problem_repo,
        evaluation_repository=evaluation_repo,
    )

    # 8. Stage 5: Web Query Generation
    print("[Stage 5 Setup] Initializing ResearchQueryGenerator...", flush=True)
    query_generator = ResearchQueryGenerator()

    # 9. Stage 6: Search Source Collector with DDG + Google News + URL Resolver
    print("[Stage 6 Setup] Initializing Search Provider & Collector...", flush=True)
    search_provider = create_default_search_provider()
    search_collector = TrackingSearchSourceCollector(search_provider=search_provider)

    # 10. Stage 7: Market Research AI Service & Web Evidence Analyzer
    print("[Stage 7 Setup] Initializing MarketResearchService & WebEvidenceAnalyzer...", flush=True)
    market_service = MarketResearchService(
        ai_client=ai_client,
        market_research_repository=market_research_repo,
    )
    web_evidence_analyzer = WebEvidenceAnalyzer(
        market_research_service=market_service,
    )

    # 11. Assemble ResearchOrchestrator
    orchestrator = ResearchOrchestrator(
        research_service=research_service,
        problem_extraction_service=problem_service,
        opportunity_synthesis_service=opportunity_service,
        opportunity_evaluation_service=evaluation_service,
        query_generator=query_generator,
        search_collector=search_collector,
        web_evidence_analyzer=web_evidence_analyzer,
        db_path=DATABASE_PATH,
    )

    # 12. Execute research pipeline with batch of 2 patents, 7 web queries, 3 results/query
    print("\n" + "-" * 80, flush=True)
    print("Executing Research Pipeline (1 patent query, 2 patents per query batch, 7 web queries, 3 results/query)...", flush=True)
    print("-" * 80 + "\n", flush=True)

    try:
        result = orchestrator.run_research(
            domain_config=COSMETICS_RESEARCH_CONFIG,
            max_patent_queries=1,
            max_patents_per_query=2,
            max_web_queries=7,
            max_web_results_per_query=3,
            raise_on_major_failure=True,
        )

        print("\n" + "=" * 80, flush=True)
        print("EXPERIMENT EXECUTION COMPLETE", flush=True)
        print("=" * 80, flush=True)
        print(f"Run ID: {result.run_id}")
        print(f"Status: {result.status}")
        print(f"Patents Ingested: {result.patent_research_result.ingested_count if result.patent_research_result else 0}")
        print(f"Problems Extracted: {result.problem_count}")
        print(f"Opportunities Synthesized: {result.opportunity_count}")
        print(f"Evaluations Performed: {result.evaluation_count}")
        print(f"Web Queries Generated: {result.query_count}")
        print(f"Web Sources Collected: {result.web_source_count}")
        print(f"Web Collection Failures: {result.web_failure_count}")
        print(f"Market Research Findings: {result.market_finding_count}")

        return result
    finally:
        inpass_client.close_browser()


if __name__ == "__main__":
    try:
        run_experiment()
    except Exception as exc:
        print(f"\n[FATAL EXPERIMENT FAILURE] {type(exc).__name__}: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
