"""Search discovery client and provider abstraction for web market research.

Defines the pluggable SearchProvider protocol and deterministic SearchClient,
supporting future search engines without tight coupling.
"""

import logging
from typing import Final, Optional, Protocol, Sequence, runtime_checkable
import urllib.parse

from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS: Final[int] = 10
MAX_ALLOWED_RESULTS: Final[int] = 100


class SearchClientError(Exception):
    """Base exception for search discovery client errors."""
    pass


class SearchQueryValidationError(SearchClientError, ValueError):
    """Raised when search query or query parameters fail validation."""
    pass


class SearchProviderError(SearchClientError):
    """Raised when the underlying search discovery provider fails."""
    pass


@runtime_checkable
class SearchProvider(Protocol):
    """Protocol for pluggable web search discovery providers."""

    def search(self, query: str, max_results: int) -> Sequence[SearchResult]:
        """Execute a search query against a search provider and return results.

        Args:
            query: Non-empty search query string.
            max_results: Maximum number of search results requested.

        Returns:
            Sequence[SearchResult]: Sequence of discovered search result items.
        """
        ...


class SearchClient:
    """Client coordinating web search discovery across pluggable providers."""

    def __init__(self, provider: SearchProvider) -> None:
        """Initialize SearchClient with a pluggable SearchProvider.

        Args:
            provider: SearchProvider instance implementing the search protocol.

        Raises:
            ValueError: If provider is None.
        """
        if provider is None:
            raise ValueError("provider is required and must not be None.")
        self.provider = provider

    def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> tuple[SearchResult, ...]:
        """Execute search query through the configured provider and return filtered HTTP/HTTPS results.

        Workflow:
            1. Validate query string (must be non-empty string).
            2. Validate and bound max_results parameter.
            3. Call injected SearchProvider.
            4. Filter out any non-HTTP/HTTPS URLs and retain result order.
            5. Return immutable tuple of SearchResult objects capped at max_results.

        Args:
            query: Search query text.
            max_results: Maximum desired results (default 10, between 1 and 100).

        Returns:
            tuple[SearchResult, ...]: Discovered and validated search results.

        Raises:
            SearchQueryValidationError: If query or max_results are invalid.
            SearchProviderError: If the underlying search provider encounters an error.
        """
        # 1. Validate query
        if not isinstance(query, str) or not query.strip():
            raise SearchQueryValidationError("Query must be a non-empty string.")

        clean_query = query.strip()

        # 2. Validate max_results
        if isinstance(max_results, bool) or not isinstance(max_results, int):
            raise SearchQueryValidationError("max_results must be an integer.")

        if max_results < 1:
            raise SearchQueryValidationError(
                f"max_results must be at least 1, got {max_results}."
            )
        if max_results > MAX_ALLOWED_RESULTS:
            raise SearchQueryValidationError(
                f"max_results cannot exceed {MAX_ALLOWED_RESULTS}, got {max_results}."
            )

        # 3. Call search provider
        try:
            raw_results = self.provider.search(clean_query, max_results)
        except Exception as exc:
            logger.error("Search provider failed for query '%s': %s", clean_query, exc)
            raise SearchProviderError(
                f"Search provider failed for query '{clean_query}': {exc}"
            ) from exc

        if not raw_results:
            return ()

        # 4. Filter only valid SearchResult objects with HTTP/HTTPS URLs
        valid_results: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, SearchResult):
                continue

            parsed = urllib.parse.urlparse(item.url)
            if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
                continue

            valid_results.append(item)
            if len(valid_results) >= max_results:
                break

        return tuple(valid_results)


def search(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    provider: Optional[SearchProvider] = None,
) -> tuple[SearchResult, ...]:
    """Convenience functional wrapper for executing a search query with an injected provider.

    Args:
        query: Non-empty search query string.
        max_results: Maximum desired results.
        provider: Pluggable search discovery provider.

    Returns:
        tuple[SearchResult, ...]: Discovered search results.
    """
    if provider is None:
        raise ValueError("provider is required and must not be None.")
    client = SearchClient(provider=provider)
    return client.search(query=query, max_results=max_results)
