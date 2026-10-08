"""Real web-research collection smoke test using COSMETICS_RESEARCH_CONFIG."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.market_research.duckduckgo_provider import DuckDuckGoHTMLSearchProvider
from src.market_research.research_query_generator import ResearchQueryGenerator
from src.market_research.search_source_collector import SearchSourceCollector
from src.patents.research_config import COSMETICS_RESEARCH_CONFIG


def run_cosmetics_web_research_smoke_test() -> None:
    print("=" * 70)
    print("SMOKE TEST: Cosmetics Web Research Collection Pipeline")
    print(f"Domain: {COSMETICS_RESEARCH_CONFIG.domain_name}")
    print("=" * 70)

    # 1. Generate queries from COSMETICS_RESEARCH_CONFIG
    generator = ResearchQueryGenerator()
    generated = generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=10)

    # 2. Pick only the first 3 queries
    target_queries = generated.queries[:3]
    print(f"\nGenerated research queries (top 3 selected for smoke test):")
    for i, q in enumerate(target_queries, start=1):
        print(f"  {i}. {q}")

    # 3. Setup provider and collector
    provider = DuckDuckGoHTMLSearchProvider()
    collector = SearchSourceCollector(search_provider=provider)

    total_queries_executed = 0
    total_search_results = 0
    total_successful_webpages = 0
    total_failed_webpages = 0
    query_reports = []

    print("\n" + "-" * 70)
    print("Executing searches & webpage collections (max_results=3 per query)...")
    print("-" * 70)

    for idx, query_str in enumerate(target_queries, start=1):
        print(f"\n[Query {idx}/{len(target_queries)}]: '{query_str}'")
        total_queries_executed += 1

        try:
            result = collector.collect_for_query(query=query_str, max_results=3)
            num_sr = len(result.search_results)
            num_succ = result.success_count
            num_fail = result.failure_count

            total_search_results += num_sr
            total_successful_webpages += num_succ
            total_failed_webpages += num_fail

            print(f"  Search Results Discovered: {num_sr}")
            print(f"  Webpages Fetched Successfully: {num_succ}")
            print(f"  Webpage Fetch Failures: {num_fail}")

            if result.sources:
                print("  Successful Web Sources:")
                for s_idx, source in enumerate(result.sources, start=1):
                    content_len = len(source.retrieved_content)
                    print(f"    [{s_idx}] Title: {source.title}")
                    print(f"        URL:    {source.url}")
                    print(f"        Domain: {source.publisher_or_domain}")
                    print(f"        Length: {content_len} chars")

            if result.failures:
                print("  Failures:")
                for f_idx, failure in enumerate(result.failures, start=1):
                    print(f"    [{f_idx}] URL: {failure.url}")
                    print(f"        Error: [{failure.error_type}] {failure.error_message}")

            query_reports.append({
                "query": query_str,
                "search_results": num_sr,
                "successful_pages": num_succ,
                "failed_pages": num_fail,
                "error": None,
            })

        except Exception as exc:
            print(f"  [ERROR] Query '{query_str}' failed: {type(exc).__name__}: {exc}")
            query_reports.append({
                "query": query_str,
                "search_results": 0,
                "successful_pages": 0,
                "failed_pages": 0,
                "error": f"{type(exc).__name__}: {exc}",
            })

    # Print final totals
    print("\n" + "=" * 70)
    print("FINAL SUMMARY TOTALS:")
    print(f"  Total queries executed:           {total_queries_executed}")
    print(f"  Total search results discovered:  {total_search_results}")
    print(f"  Total successful webpages:        {total_successful_webpages}")
    print(f"  Total failed webpage fetches:     {total_failed_webpages}")
    print("=" * 70)


if __name__ == "__main__":
    run_cosmetics_web_research_smoke_test()
