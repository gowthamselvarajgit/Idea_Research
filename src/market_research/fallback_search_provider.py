"""Generic fallback and composite search provider for web market research.

Coordinates sequential execution across an ordered sequence of SearchProvider instances,
failing over when a provider raises an exception or returns zero usable results.
"""

from collections.abc import Sequence
import logging
from typing import Any, Final, Optional
import urllib.parse

from src.market_research.search_client import (
    DEFAULT_MAX_RESULTS,
    MAX_ALLOWED_RESULTS,
    SearchProvider,
    SearchProviderError,
    SearchQueryValidationError,
)
from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)


class FallbackSearchProviderError(SearchProviderError):
    """Raised when all configured search providers fail or return zero usable results.

    Attributes:
        attempts: Tuple of dictionaries documenting the outcome of each provider attempt.
        query: The search query that failed across all providers.
    """

    def __init__(
        self,
        message: str,
        attempts: Optional[Sequence[dict[str, Any]]] = None,
        query: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.attempts: tuple[dict[str, Any], ...] = tuple(attempts) if attempts is not None else ()
        self.query: Optional[str] = query


# Convenience alias for caller clarity
AllProvidersFailedError = FallbackSearchProviderError


class FallbackSearchProvider:
    """Composite SearchProvider trying an ordered sequence of providers with fallback.

    Implements the SearchProvider protocol, allowing drop-in substitution wherever
    SearchProvider or SearchClient is used.
    """

    def __init__(self, providers: Sequence[SearchProvider]) -> None:
        """Initialize FallbackSearchProvider with an ordered sequence of providers.

        Args:
            providers: Non-empty sequence of SearchProvider instances.

        Raises:
            ValueError: If providers is None or empty.
            TypeError: If providers is not a sequence or contains invalid elements.
        """
        if providers is None:
            raise ValueError("providers must not be None.")
        if not isinstance(providers, (list, tuple, Sequence)) or isinstance(providers, (str, bytes)):
            raise TypeError("providers must be a sequence of SearchProvider instances.")
        if len(providers) == 0:
            raise ValueError("providers must contain at least one SearchProvider.")

        validated_providers: list[SearchProvider] = []
        for idx, provider in enumerate(providers):
            if provider is None:
                raise TypeError(f"Provider at index {idx} must not be None.")
            if not hasattr(provider, "search") or not callable(getattr(provider, "search")):
                raise TypeError(
                    f"Provider at index {idx} ({type(provider).__name__}) must implement SearchProvider protocol."
                )
            validated_providers.append(provider)

        self._providers: tuple[SearchProvider, ...] = tuple(validated_providers)

    @property
    def providers(self) -> tuple[SearchProvider, ...]:
        """Configured search providers in priority order."""
        return self._providers

    def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> tuple[SearchResult, ...]:
        """Execute search query through providers in configured order until usable results are obtained.

        Workflow:
            1. Validate query string and max_results constraints.
            2. Iterate through configured providers in order.
            3. For each provider:
               a. Call provider.search(query, max_results).
               b. Filter valid SearchResult objects with HTTP/HTTPS URLs.
               c. Deduplicate results by URL while preserving order.
               d. If at least one usable result is found, cap at max_results and return immediately.
               e. If provider returns 0 usable results or raises an exception, record attempt and continue.
            4. If all providers fail or return zero usable results, raise FallbackSearchProviderError.

        Args:
            query: Non-empty search query string.
            max_results: Maximum number of search results requested (default 10, between 1 and 100).

        Returns:
            tuple[SearchResult, ...]: Deduplicated search results from the first successful provider.

        Raises:
            SearchQueryValidationError: If query or max_results fails validation.
            FallbackSearchProviderError: If every provider fails or returns zero usable results.
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

        attempts: list[dict[str, Any]] = []

        for provider in self._providers:
            provider_name = getattr(provider, "name", None) or type(provider).__name__

            try:
                raw_results = provider.search(clean_query, max_results)
            except Exception as exc:
                logger.warning(
                    "Fallback provider '%s' failed for query '%s': %s",
                    provider_name,
                    clean_query,
                    exc,
                )
                attempts.append({
                    "provider": provider_name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "exception": exc,
                })
                continue

            if not raw_results:
                logger.info(
                    "Fallback provider '%s' returned 0 results for query '%s'; trying next provider.",
                    provider_name,
                    clean_query,
                )
                attempts.append({
                    "provider": provider_name,
                    "status": "zero_results",
                    "count": 0,
                })
                continue

            # Filter valid HTTP/HTTPS SearchResult items and deduplicate by URL
            usable_results: list[SearchResult] = []
            seen_urls: set[str] = set()

            for item in raw_results:
                if not isinstance(item, SearchResult):
                    continue

                parsed = urllib.parse.urlparse(item.url)
                if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
                    continue

                if item.url in seen_urls:
                    continue

                seen_urls.add(item.url)
                usable_results.append(item)
                if len(usable_results) >= max_results:
                    break

            if usable_results:
                logger.info(
                    "Fallback provider '%s' successfully returned %d usable results for query '%s'.",
                    provider_name,
                    len(usable_results),
                    clean_query,
                )
                return tuple(usable_results)

            # Raw results contained items but none were usable HTTP/HTTPS results
            logger.info(
                "Fallback provider '%s' returned raw items but 0 usable results for query '%s'.",
                provider_name,
                clean_query,
            )
            attempts.append({
                "provider": provider_name,
                "status": "zero_usable_results",
                "count": 0,
            })

        # All providers failed or returned zero usable results
        attempt_summaries: list[str] = []
        for att in attempts:
            if att["status"] == "error":
                attempt_summaries.append(f"{att['provider']}: error ({att['error_type']}: {att['error_message']})")
            else:
                attempt_summaries.append(f"{att['provider']}: {att['status']} (0 results)")

        summary_str = "; ".join(attempt_summaries)
        msg = (
            f"All {len(self._providers)} search providers failed or returned zero usable results "
            f"for query '{clean_query}'. Attempts: [{summary_str}]"
        )
        logger.error(msg)
        raise FallbackSearchProviderError(msg, attempts=attempts, query=clean_query)


def create_default_search_provider(
    ddg_provider: Optional[SearchProvider] = None,
    tavily_provider: Optional[SearchProvider] = None,
    tavily_api_key: Optional[str] = None,
) -> SearchProvider:
    """Create the default search discovery provider configuration for web market research.

    DuckDuckGo is always configured as the primary search provider.
    Tavily is configured as the secondary fallback provider ONLY when its required
    API credentials are available (either via parameter or TAVILY_API_KEY environment variable).
    If Tavily credentials are not configured, only DuckDuckGo is used.

    Args:
        ddg_provider: Optional custom primary SearchProvider (defaults to DuckDuckGoHTMLSearchProvider).
        tavily_provider: Optional custom fallback SearchProvider.
        tavily_api_key: Optional Tavily API key override.

    Returns:
        SearchProvider: Either a single DuckDuckGo provider or a FallbackSearchProvider composite.
    """
    from src.market_research.duckduckgo_provider import DuckDuckGoHTMLSearchProvider
    from src.market_research.tavily_provider import TavilySearchProvider

    primary = ddg_provider or DuckDuckGoHTMLSearchProvider()

    if tavily_provider is not None:
        return FallbackSearchProvider([primary, tavily_provider])

    resolved_tavily = TavilySearchProvider(api_key=tavily_api_key)
    if resolved_tavily.is_configured:
        logger.info(
            "Tavily API key is configured. Initializing FallbackSearchProvider with "
            "DuckDuckGo (primary) and Tavily (fallback)."
        )
        return FallbackSearchProvider([primary, resolved_tavily])

    logger.info(
        "Tavily API key is not configured (TAVILY_API_KEY not set). "
        "Using DuckDuckGoHTMLSearchProvider as sole provider."
    )
    return primary

