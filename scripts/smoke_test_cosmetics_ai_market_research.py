"""Controlled real AI market-research analysis smoke test using cosmetics web sources."""

import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.market_research.fallback_search_provider import create_default_search_provider
from src.market_research.models import MarketResearchRecord
from src.market_research.research_query_generator import ResearchQueryGenerator
from src.market_research.search_source_collector import SearchSourceCollector
from src.market_research.service import MarketResearchService
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer
from src.opportunities.models import OpportunityRecord
from src.patents.research_config import COSMETICS_RESEARCH_CONFIG
from src.problems.ai_client import AntigravityAIClient


class InMemoryMarketResearchRepository:
    """Isolated in-memory repository ensuring ZERO writes to production database."""

    def __init__(self) -> None:
        self.records: list[MarketResearchRecord] = []

    def save_market_research(self, record: MarketResearchRecord, conn: Any = None) -> str:
        rec_id = record.id or f"smoke-rec-{len(self.records) + 1}"
        self.records.append(record)
        return rec_id


def run_controlled_ai_market_research_smoke_test() -> None:
    print("=" * 75)
    print("CONTROLLED REAL AI MARKET RESEARCH SMOKE TEST")
    print(f"Domain: {COSMETICS_RESEARCH_CONFIG.domain_name}")
    print("=" * 75)

    # 1. Generate research queries from COSMETICS_RESEARCH_CONFIG
    generator = ResearchQueryGenerator()
    generated = generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=10)

    # 2. Use ONLY the first 2 queries: 'skincare competitors', 'skincare products'
    target_queries = ["skincare competitors", "skincare products"]
    print("\nSelected Research Queries for Web Discovery:")
    for idx, q in enumerate(target_queries, 1):
        print(f"  {idx}. '{q}'")

    # 3. Setup resilient search provider and search collector
    provider = create_default_search_provider()
    collector = SearchSourceCollector(search_provider=provider)

    combined_sources: list[WebResearchSource] = []
    collection_failures: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    print("\n" + "-" * 75)
    print("Phase 1: Web Search & Source Retrieval (max_results=3 per query)...")
    print("-" * 75)

    for q_idx, query_str in enumerate(target_queries, 1):
        print(f"\n[Query {q_idx}/2]: '{query_str}'")
        try:
            res = collector.collect_for_query(query=query_str, max_results=3)
            print(f"  Discovered Search Results: {len(res.search_results)}")
            print(f"  Successfully Fetched Webpages: {len(res.sources)}")
            print(f"  Fetch Failures: {len(res.failures)}")

            for src in res.sources:
                if src.url not in seen_urls:
                    seen_urls.add(src.url)
                    combined_sources.append(src)
                    print(f"    + Added source: '{src.title[:60]}...' ({src.publisher_or_domain})")

            for fail in res.failures:
                collection_failures.append({
                    "query": query_str,
                    "url": fail.url,
                    "error_type": fail.error_type,
                    "error_message": fail.error_message,
                })

        except Exception as exc:
            print(f"  [ERROR] Query '{query_str}' search/collection failed: {exc}")
            collection_failures.append({
                "query": query_str,
                "url": "N/A",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })

    print(f"\nTotal unique web sources collected: {len(combined_sources)}")
    print(f"Total collection failures: {len(collection_failures)}")

    # 4. Setup Real AI Service & Web Evidence Analyzer with isolated in-memory repository
    print("\n" + "-" * 75)
    print("Phase 2: Real AI Market Research Analysis...")
    print("-" * 75)

    smoke_test_opp_id = "smoke-test-cosmetics-ai-opp-001"
    smoke_opportunity = OpportunityRecord(
        opportunity_title="AI-Powered Personalized Skincare Diagnostics",
        solution_concept="Multi-spectral imaging and optical computer vision algorithms analyzing skin health for personalized routines.",
        target_customer="Dermatological practices, prosumers, and clinical aesthetic spas",
        value_proposition="Reduces consultation time by 70% and recommends tailored formulations based on objective optical metrics.",
        source_problem_ids=("smoke-lead-cosmetics-1",),
        id=smoke_test_opp_id,
    )

    ai_client = AntigravityAIClient()
    in_memory_repo = InMemoryMarketResearchRepository()
    service = MarketResearchService(
        ai_client=ai_client,
        market_research_repository=in_memory_repo,
    )
    analyzer = WebEvidenceAnalyzer(
        market_research_service=service,
    )

    ai_findings: list[MarketResearchRecord] = []
    ai_parser_error: str | None = None

    try:
        print(f"Invoking AI inference for opportunity '{smoke_test_opp_id}'...")
        ai_findings = analyzer.analyze(
            opportunity_id=smoke_test_opp_id,
            sources=combined_sources,
            opportunity=smoke_opportunity,
        )
        print(f"AI market research analysis succeeded! Generated {len(ai_findings)} findings.")
    except Exception as exc:
        ai_parser_error = f"{type(exc).__name__}: {exc}"
        print(f"[AI ERROR] Analysis failed: {ai_parser_error}")

    # 5. Print Findings
    print("\n" + "=" * 75)
    print("MARKET RESEARCH FINDINGS REPORT:")
    print("=" * 75)

    if ai_findings:
        for idx, finding in enumerate(ai_findings, 1):
            print(f"\n--- Finding #{idx} ---")
            print(f"  Source Type:        {finding.source_type}")
            print(f"  Source Name:        {finding.source_name}")
            print(f"  Source URL:         {finding.source_url}")
            print(f"  Company / Product:  {finding.company_or_product}")
            print(f"  Finding:            {finding.finding}")
            print(f"  Evidence Summary:   {finding.evidence_summary}")
            print(f"  Relevance:          {finding.relevance}")
    else:
        print("  No AI market research findings generated.")

    # 6. Print Collection Failures if any
    if collection_failures:
        print("\n" + "-" * 75)
        print("COLLECTION FAILURES:")
        for idx, f in enumerate(collection_failures, 1):
            print(f"  [{idx}] URL: {f['url']}")
            print(f"      Query: {f['query']}")
            print(f"      Error: [{f['error_type']}] {f['error_message']}")

    # 7. Print Final Summary Metrics
    print("\n" + "=" * 75)
    print("FINAL SUMMARY TOTALS:")
    print(f"  Web sources collected:     {len(combined_sources)}")
    print(f"  AI findings generated:     {len(ai_findings)}")
    print(f"  Collection failures:       {len(collection_failures)}")
    print(f"  AI / Parser failure:       {ai_parser_error if ai_parser_error else 'None (Success)'}")
    print("=" * 75)


if __name__ == "__main__":
    run_controlled_ai_market_research_smoke_test()
