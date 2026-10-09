"""Search discovery client and provider abstraction for web market research.

Defines the pluggable SearchProvider protocol and deterministic SearchClient,
supporting future search engines without tight coupling.
"""

import inspect
import logging
from typing import Any, Final, Optional, Protocol, Sequence, runtime_checkable
import urllib.parse

from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS: Final[int] = 10
MAX_ALLOWED_RESULTS: Final[int] = 100


def callable_accepts_kwarg(target: Any, kwarg_name: str) -> bool:
    """Check whether a callable accepts a specific keyword argument or **kwargs.

    Uses inspect.signature() to inspect the parameters of the given callable.
    Returns True if the callable defines a parameter with matching name (that can
    be passed as a keyword) or accepts variable keyword arguments (**kwargs).

    If the callable cannot be inspected (e.g. certain builtins or C extensions
    raising ValueError/TypeError), returns True so that domain-specific parameters
    are attempted rather than silently discarded, and any errors propagate cleanly.

    Args:
        target: Callable object to inspect (function, method, class, mock, etc.).
        kwarg_name: Name of the keyword argument to check for.

    Returns:
        bool: True if target accepts kwarg_name or **kwargs (or cannot be inspected),
              False if target clearly does not accept the keyword argument.
    """
    if not callable(target):
        return False

    # If target is a mock with a callable side_effect, inspect the underlying side_effect
    side_effect = getattr(target, "side_effect", None)
    if callable(side_effect) and not (
        isinstance(side_effect, type) and issubclass(side_effect, BaseException)
    ):
        inspect_target = side_effect
    else:
        inspect_target = target

    try:
        sig = inspect.signature(inspect_target)
    except (ValueError, TypeError):
        # Cannot inspect signature; prefer attempting kwarg rather than silently dropping
        return True

    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == kwarg_name and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True

    return False



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
        *,
        subject_terms: Optional[Sequence[str]] = None,
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
            subject_terms: Optional domain subject vocabulary for relevance filtering.

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
            if subject_terms is not None and callable_accepts_kwarg(
                self.provider.search, "subject_terms"
            ):
                raw_results = self.provider.search(
                    clean_query,
                    max_results,
                    subject_terms=subject_terms,
                )
            else:
                raw_results = self.provider.search(clean_query, max_results)
        except TypeError:
            raise
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
    *,
    subject_terms: Optional[Sequence[str]] = None,
) -> tuple[SearchResult, ...]:
    """Convenience functional wrapper for executing a search query with an injected provider.

    Args:
        query: Non-empty search query string.
        max_results: Maximum desired results.
        provider: Pluggable search discovery provider.
        subject_terms: Optional domain subject vocabulary for relevance filtering.

    Returns:
        tuple[SearchResult, ...]: Discovered search results.
    """
    if provider is None:
        raise ValueError("provider is required and must not be None.")
    client = SearchClient(provider=provider)
    return client.search(query=query, max_results=max_results, subject_terms=subject_terms)
