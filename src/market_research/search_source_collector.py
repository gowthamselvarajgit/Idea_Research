"""Integration layer connecting search discovery with web source collection.

Coordinates search execution (SearchProvider / SearchClient), extracts discovered
destination URLs, forwards them to WebSourceCollector, and aggregates collected
WebResearchSource records along with individual collection failures.
"""

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Final, Optional, Sequence

from src.market_research.duckduckgo_provider import DuckDuckGoHTMLSearchProvider
from src.market_research.fallback_search_provider import create_default_search_provider
from src.market_research.search_client import (
    DEFAULT_MAX_RESULTS,
    SearchClient,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
)
from src.market_research.search_models import SearchResult
from src.market_research.source_collection import (
    SourceCollectionFailure,
    SourceCollectionResult,
    WebSourceCollector,
)
from src.market_research.source_models import WebResearchSource

logger = logging.getLogger(__name__)


class SearchSourceCollectorError(SearchProviderError):
    """Raised when the search source collection workflow encounters a fatal error."""
    pass


@dataclass(frozen=True)
class SearchSourceCollectionResult:
    """Consolidated result of searching and collecting web sources for a research query.

    Attributes:
        query: The search query executed.
        search_results: Tuple of SearchResult items discovered by the search provider.
        sources: Tuple of successfully retrieved and validated WebResearchSource records.
        failures: Tuple of SourceCollectionFailure records for URLs that could not be retrieved.
    """

    query: str
    search_results: tuple[SearchResult, ...] = field(default_factory=tuple)
    sources: tuple[WebResearchSource, ...] = field(default_factory=tuple)
    failures: tuple[SourceCollectionFailure, ...] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        """Number of successfully collected sources."""
        return len(self.sources)

    @property
    def failure_count(self) -> int:
        """Number of failed URL collections."""
        return len(self.failures)

    @property
    def total_count(self) -> int:
        """Total number of URLs processed for collection."""
        return len(self.sources) + len(self.failures)

    @property
    def collection_result(self) -> SourceCollectionResult:
        """Extract equivalent SourceCollectionResult view."""
        return SourceCollectionResult(sources=self.sources, failures=self.failures)

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a standard dictionary."""
        return {
            "query": self.query,
            "search_results": [r.to_dict() for r in self.search_results],
            "sources": [s.to_dict() for s in self.sources],
            "failures": [f.to_dict() for f in self.failures],
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
        }


class SearchSourceCollector:
    """Orchestrates search discovery and subsequent webpage retrieval for a single query."""

    def __init__(
        self,
        search_provider_or_client: Optional[SearchProvider | SearchClient] = None,
        source_collector: Optional[WebSourceCollector] = None,
        *,
        search_client: Optional[SearchClient] = None,
        search_provider: Optional[SearchProvider] = None,
        provider: Optional[SearchProvider] = None,
        collector: Optional[WebSourceCollector] = None,
    ) -> None:
        """Initialize SearchSourceCollector with injected search and collection components.

        Args:
            search_provider_or_client: SearchClient or SearchProvider instance.
            source_collector: WebSourceCollector instance.
            search_client: Explicit SearchClient instance.
            search_provider: Explicit SearchProvider instance.
            provider: Alias for search_provider.
            collector: Alias for source_collector.
        """
        # Resolve search client
        active_client = search_client
        if active_client is None:
            active_provider = search_provider or provider
            if active_provider is not None:
                active_client = SearchClient(provider=active_provider)
            elif isinstance(search_provider_or_client, SearchClient):
                active_client = search_provider_or_client
            elif search_provider_or_client is not None:
                active_client = SearchClient(provider=search_provider_or_client)
            else:
                active_client = SearchClient(provider=create_default_search_provider())

        self.search_client = active_client
        self.source_collector = source_collector or collector or WebSourceCollector()

    @property
    def provider(self) -> SearchProvider:
        """Return the underlying SearchProvider instance."""
        return self.search_client.provider

    def collect_for_query(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        source_type: str = "other",
    ) -> SearchSourceCollectionResult:
        """Execute a search query and retrieve web sources for the discovered URLs.

        Lifecycle:
            1. Validates query and max_results parameters.
            2. Executes search through search_client (e.g. DuckDuckGoHTMLSearchProvider).
            3. Extracts destination URLs from returned SearchResults, deduplicating while
               strictly preserving order.
            4. Bounds the collection targets to max_results.
            5. Retrieves each URL via WebSourceCollector.
            6. Consolidates SearchResults, successfully collected WebResearchSources, and
               structured failures into SearchSourceCollectionResult.

        Args:
            query: Non-empty search query string.
            max_results: Maximum number of search results/sources to retrieve.
            source_type: Controlled classification for WebSourceClient (default: "other").

        Returns:
            SearchSourceCollectionResult: Aggregated search and collection outcome.

        Raises:
            SearchQueryValidationError: If query or max_results fail validation.
            SearchSourceCollectorError: If search discovery fails fatally.
        """
        if not isinstance(query, str) or not query.strip():
            raise SearchQueryValidationError("Query must be a non-empty string.")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise SearchQueryValidationError("max_results must be an integer >= 1.")

        clean_query = query.strip()

        # 1. Execute search
        try:
            search_results = self.search_client.search(
                query=clean_query,
                max_results=max_results,
            )
        except SearchProviderError as exc:
            logger.error("Search provider error for query '%s': %s", clean_query, exc)
            raise SearchSourceCollectorError(
                f"Search provider failed for query '{clean_query}': {exc}"
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error during search for query '%s': %s", clean_query, exc)
            raise SearchSourceCollectorError(
                f"Search failed unexpectedly for query '{clean_query}': {exc}"
            ) from exc

        if not search_results:
            logger.info("Search returned zero results for query '%s'", clean_query)
            return SearchSourceCollectionResult(
                query=clean_query,
                search_results=(),
                sources=(),
                failures=(),
            )

        # 2. Extract and deduplicate URLs in discovery order
        seen_urls: set[str] = set()
        target_urls: list[str] = []

        for sr in search_results:
            url_str = sr.url.strip()
            if url_str and url_str not in seen_urls:
                seen_urls.add(url_str)
                target_urls.append(url_str)
            if len(target_urls) >= max_results:
                break

        # 3. Retrieve sources via WebSourceCollector
        collection_result = self.source_collector.collect_sources(
            urls=target_urls,
            source_type=source_type,
            deduplicate=True,
        )

        return SearchSourceCollectionResult(
            query=clean_query,
            search_results=tuple(search_results),
            sources=collection_result.sources,
            failures=collection_result.failures,
        )

    # Convenience aliases
    search_and_collect = collect_for_query
    collect_sources_for_query = collect_for_query


def collect_sources_for_search_query(
    query: str,
    search_provider_or_client: Optional[SearchProvider | SearchClient] = None,
    source_collector: Optional[WebSourceCollector] = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    source_type: str = "other",
) -> SearchSourceCollectionResult:
    """Convenience functional wrapper to search and collect sources for a query.

    Args:
        query: Non-empty search query string.
        search_provider_or_client: Optional SearchProvider or SearchClient override.
        source_collector: Optional WebSourceCollector override.
        max_results: Maximum results/sources to retrieve.
        source_type: Controlled classification for WebSourceClient.

    Returns:
        SearchSourceCollectionResult: Consolidated search and collection outcome.
    """
    service = SearchSourceCollector(
        search_provider_or_client=search_provider_or_client,
        source_collector=source_collector,
    )
    return service.collect_for_query(
        query=query,
        max_results=max_results,
        source_type=source_type,
    )
