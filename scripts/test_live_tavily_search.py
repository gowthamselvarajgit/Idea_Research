"""Safe, controlled single-query live test for TavilySearchProvider.

Requirements:
- Never prints or exposes TAVILY_API_KEY or request headers.
- If TAVILY_API_KEY is missing, aborts without making any network requests.
- If configured, runs exactly one query with max_results=3.
- Prints only title, domain, and URL for each discovered result.
- Does not modify database or production data.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.market_research.tavily_provider import (
    TavilyAuthenticationError,
    TavilyHTTPError,
    TavilyNetworkError,
    TavilyRateLimitError,
    TavilySearchError,
    TavilySearchProvider,
    TavilyTimeoutError,
)

QUERY = "AI skincare product recommendation apps competitors"
MAX_RESULTS = 3


def main() -> int:
    # 1. Inspect configuration without exposing the secret
    has_key = bool(os.getenv("TAVILY_API_KEY") and os.getenv("TAVILY_API_KEY").strip())

    if not has_key:
        print("[STATUS] TAVILY_API_KEY is not configured in the environment.")
        print("[ACTION REQUIRED] Set TAVILY_API_KEY before running live search:")
        print("  Windows PowerShell:")
        print('    $env:TAVILY_API_KEY="tvly-your-actual-api-key"')
        print("  Windows Command Prompt:")
        print("    set TAVILY_API_KEY=tvly-your-actual-api-key")
        print("  Bash / Zsh:")
        print('    export TAVILY_API_KEY="tvly-your-actual-api-key"')
        print("No network requests were made.")
        return 1

    print("[STATUS] TAVILY_API_KEY is configured. Executing 1 controlled search query...")
    print(f"Query: '{QUERY}' | max_results: {MAX_RESULTS}\n")

    provider = TavilySearchProvider()

    try:
        results = provider.search(query=QUERY, max_results=MAX_RESULTS)
    except TavilyAuthenticationError as exc:
        print(f"[AUTH ERROR] Authentication failed: {exc}")
        return 2
    except TavilyRateLimitError as exc:
        print(f"[QUOTA ERROR] Rate limit or quota exceeded: {exc}")
        return 3
    except TavilyTimeoutError as exc:
        print(f"[TIMEOUT ERROR] Request timed out: {exc}")
        return 4
    except (TavilyHTTPError, TavilyNetworkError, TavilySearchError) as exc:
        print(f"[API ERROR] Request failed: {exc}")
        return 5
    except Exception as exc:
        print(f"[UNEXPECTED ERROR] {type(exc).__name__}: {exc}")
        return 6

    print(f"[SUCCESS] Received {len(results)} search results:\n")
    for idx, item in enumerate(results, start=1):
        print(f"Result {idx}:")
        print(f"  Title:  {item.title}")
        print(f"  Domain: {item.domain}")
        print(f"  URL:    {item.url}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
