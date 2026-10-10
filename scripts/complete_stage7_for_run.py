"""Complete Stage 5, 6, 7 for existing run 3356b1fa-a8ed-4281-bdb8-b924e6b3b11e."""

import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from config.settings import DATABASE_PATH
from src.market_research.fallback_search_provider import create_default_search_provider
from src.market_research.repository import MarketResearchRepository
from src.market_research.research_query_generator import ResearchQueryGenerator
from src.market_research.search_source_collector import SearchSourceCollector
from src.market_research.service import MarketResearchService
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.repository import OpportunityRepository
from src.patents.research_config import COSMETICS_RESEARCH_CONFIG
from src.problems.ai_client import AntigravityAIClient

run_id = "3356b1fa-a8ed-4281-bdb8-b924e6b3b11e"

# Load opportunities from DB
opp_repo = OpportunityRepository(db_path=DATABASE_PATH)
opps = opp_repo.get_opportunities_for_run(run_id)
print(f"Loaded {len(opps)} opportunities for run {run_id}:")
for o in opps:
    print(f"  - {o.id}: {o.opportunity_title}")

# Stage 5: Queries
query_gen = ResearchQueryGenerator()
queries_result = query_gen.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=7, quote_subject_anchor=True)
queries = list(queries_result.queries)
print(f"\nGenerated {len(queries)} web research queries:")
for q in queries:
    print(f"  - {q}")

# Stage 6: Source collection
provider = create_default_search_provider()
collector = SearchSourceCollector(search_provider=provider)

collected_sources = []
seen_urls = set()
for q in queries:
    try:
        res = collector.collect_for_query(query=q, max_results=3)
        for s in res.sources:
            if s.url not in seen_urls:
                seen_urls.add(s.url)
                collected_sources.append(s)
    except Exception as exc:
        print(f"[Warning] Query '{q}' failed: {exc}")

print(f"\nCollected {len(collected_sources)} unique web sources.")

# Stage 7: Market research AI analysis
ai_client = AntigravityAIClient(model="gemini-3.8-flash-low")
mr_repo = MarketResearchRepository(db_path=DATABASE_PATH)
market_service = MarketResearchService(ai_client=ai_client, market_research_repository=mr_repo)
analyzer = WebEvidenceAnalyzer(market_research_service=market_service)

all_findings = []
for opp in opps:
    print(f"\nAnalyzing web evidence for opportunity '{opp.opportunity_title}' ({opp.id})...")
    findings = analyzer.analyze(opportunity_id=opp.id, sources=collected_sources, opportunity=opp)
    print(f"Generated {len(findings)} findings for {opp.id}.")
    all_findings.extend(findings)

print(f"\nTotal market research findings persisted to {DATABASE_PATH}: {len(all_findings)}")
