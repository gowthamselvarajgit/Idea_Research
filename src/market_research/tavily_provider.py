"""Tavily search discovery provider for web market research.

Implements the SearchProvider protocol using standard-library urllib and json,
executing queries against the official Tavily Search REST API (https://api.tavily.com/search).

Tavily is an AI-optimized search engine that returns clean, structured JSON results
with relevance-ranked content snippets without scraping HTML search result pages.
"""

import json
import logging
import os
import socket
from typing import Any, Callable, Optional, Sequence
import urllib.error
import urllib.parse
import urllib.request

from config.settings import TAVILY_DEFAULT_API_URL, get_tavily_config
from src.market_research.search_client import (
    DEFAULT_MAX_RESULTS,
    MAX_ALLOWED_RESULTS,
    SearchProvider,
    SearchProviderError,
)
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_SEARCH_DEPTH: str = "basic"
DEFAULT_USER_AGENT: str = "StartupResearchAgent/1.0"


class TavilySearchError(SearchProviderError):
    """Base exception for Tavily search provider failures."""
    pass


class TavilyAuthenticationError(TavilySearchError):
    """Raised when Tavily API key is missing, unauthorized, or invalid."""
    pass


class TavilyRateLimitError(TavilySearchError):
    """Raised when Tavily rate limit or monthly query quota is exceeded."""
    pass


class TavilyHTTPError(TavilySearchError):
    """Raised when Tavily API returns a non-200 HTTP status code."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TavilyNetworkError(TavilySearchError):
    """Raised when network connectivity or socket errors occur during a Tavily API call."""
    pass


class TavilyTimeoutError(TavilyNetworkError):
    """Raised when a Tavily API request exceeds the configured timeout."""
    pass


def extract_domain_from_url(url: str) -> str:
    """Extract and normalize publishing domain name from a URL string."""
    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


class TavilySearchProvider:
    """Real search discovery provider executing queries against the Tavily Search API.

    Implements the SearchProvider protocol, allowing seamless use in SearchClient
    and FallbackSearchProvider composites.
    """

    name: str = "TavilySearchProvider"

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        search_depth: str = DEFAULT_SEARCH_DEPTH,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        http_transport: Optional[Callable[[urllib.request.Request, float], str | bytes]] = None,
    ) -> None:
        """Initialize TavilySearchProvider.

        Args:
            api_key: Tavily API key (e.g. 'tvly-...'). If omitted, read from TAVILY_API_KEY environment variable.
            endpoint: Custom API endpoint URL. Defaults to https://api.tavily.com/search.
            search_depth: Tavily search depth ('basic' or 'advanced').
            timeout: Request timeout in seconds.
            user_agent: User-Agent header for the request.
            http_transport: Optional callable for injecting HTTP execution (useful for unit testing).
        """
        # Resolve API key from argument or environment
        if api_key is not None:
            resolved_key = api_key.strip() if isinstance(api_key, str) else ""
        else:
            cfg = get_tavily_config()
            resolved_key = (cfg.get("api_key") or "").strip()

        self.api_key: Optional[str] = resolved_key if resolved_key else None

        # Resolve endpoint
        resolved_endpoint = endpoint.strip() if endpoint and isinstance(endpoint, str) else None
        if not resolved_endpoint:
            cfg = get_tavily_config()
            resolved_endpoint = cfg.get("base_url") or TAVILY_DEFAULT_API_URL

        self.endpoint: str = resolved_endpoint
        self.search_depth: str = search_depth.strip() if isinstance(search_depth, str) else DEFAULT_SEARCH_DEPTH
        self.timeout: float = float(timeout) if timeout > 0 else DEFAULT_TIMEOUT_SECONDS
        self.user_agent: str = user_agent.strip() if user_agent else DEFAULT_USER_AGENT
        self.http_transport = http_transport

    @property
    def is_configured(self) -> bool:
        """Return True if Tavily API credentials are configured and non-empty."""
        return bool(self.api_key and self.api_key.strip())

    def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> Sequence[SearchResult]:
        """Execute search query against Tavily Search API and return SearchResult objects.

        Args:
            query: Non-empty search query string.
            max_results: Maximum desired results (must be >= 1).

        Returns:
            Sequence[SearchResult]: Sequence of discovered and validated SearchResult objects.

        Raises:
            ValueError: If query is empty or max_results < 1.
            TavilyAuthenticationError: If API key is missing or invalid (HTTP 401/403).
            TavilyRateLimitError: If rate limit or quota is exceeded (HTTP 429).
            TavilyHTTPError: If Tavily returns other HTTP error status.
            TavilyTimeoutError: If the request times out.
            TavilyNetworkError: If network connectivity fails.
            TavilySearchError: If response format is invalid.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")

        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an integer >= 1.")

        clean_query = query.strip()
        bounded_max_results = min(max_results, MAX_ALLOWED_RESULTS)

        # Check authentication configuration before making network requests
        if not self.is_configured:
            raise TavilyAuthenticationError(
                "Tavily API key is not configured. Set the TAVILY_API_KEY environment variable "
                "or pass api_key to TavilySearchProvider."
            )

        # Build JSON request payload
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": clean_query,
            "max_results": bounded_max_results,
            "search_depth": self.search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        encoded_data = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(
            url=self.endpoint,
            data=encoded_data,
            headers=headers,
            method="POST",
        )

        response_body: str = self._execute_request(req, clean_query)
        return self._parse_response(response_body, clean_query, bounded_max_results)

    def _execute_request(self, req: urllib.request.Request, query: str) -> str:
        """Execute HTTP request either through injected transport or urllib.request."""
        try:
            if self.http_transport is not None:
                raw_response = self.http_transport(req, self.timeout)
                if isinstance(raw_response, bytes):
                    return raw_response.decode("utf-8", errors="replace")
                return str(raw_response)

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return content.decode(charset, errors="replace")

        except urllib.error.HTTPError as exc:
            status = exc.code
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            error_detail = self._extract_error_detail(error_body) or str(exc)
            logger.warning(
                "Tavily API HTTP %d for query '%s': %s",
                status,
                query,
                error_detail,
            )

            if status in (401, 403):
                raise TavilyAuthenticationError(
                    f"Tavily authentication failed (HTTP {status}): {error_detail}"
                ) from exc
            elif status == 429:
                raise TavilyRateLimitError(
                    f"Tavily rate limit exceeded (HTTP 429): {error_detail}"
                ) from exc
            else:
                raise TavilyHTTPError(
                    f"Tavily HTTP error {status} for query '{query}': {error_detail}",
                    status_code=status,
                ) from exc

        except (socket.timeout, TimeoutError) as exc:
            logger.warning("Tavily request timed out for query '%s': %s", query, exc)
            raise TavilyTimeoutError(
                f"Tavily request timed out after {self.timeout}s for query '{query}'."
            ) from exc

        except urllib.error.URLError as exc:
            reason_str = str(exc.reason)
            if isinstance(exc.reason, socket.timeout) or "timed out" in reason_str.lower():
                logger.warning("Tavily request timed out for query '%s': %s", query, exc)
                raise TavilyTimeoutError(
                    f"Tavily request timed out after {self.timeout}s for query '{query}'."
                ) from exc

            logger.warning("Tavily network error for query '%s': %s", query, exc)
            raise TavilyNetworkError(
                f"Tavily network error for query '{query}': {exc.reason}"
            ) from exc

        except OSError as exc:
            logger.warning("Tavily OS socket error for query '%s': %s", query, exc)
            raise TavilyNetworkError(
                f"Tavily socket/network error for query '{query}': {exc}"
            ) from exc

    def _extract_error_detail(self, error_body: str) -> Optional[str]:
        """Try to extract a descriptive error message from Tavily JSON response."""
        if not error_body or not error_body.strip():
            return None
        try:
            parsed = json.loads(error_body)
            if isinstance(parsed, dict):
                if "detail" in parsed:
                    detail = parsed["detail"]
                    if isinstance(detail, dict) and "error" in detail:
                        return str(detail["error"])
                    return str(detail)
                if "error" in parsed:
                    return str(parsed["error"])
                if "message" in parsed:
                    return str(parsed["message"])
        except Exception:
            pass
        return error_body[:200]

    def _parse_response(
        self,
        response_text: str,
        query: str,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """Parse Tavily JSON search response into validated SearchResult instances."""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            logger.error("Failed to decode Tavily JSON response for query '%s': %s", query, exc)
            raise TavilySearchError(
                f"Invalid JSON returned by Tavily for query '{query}': {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise TavilySearchError(
                f"Expected JSON object from Tavily response, got {type(data).__name__}."
            )

        raw_items = data.get("results")
        if raw_items is None:
            # Check if there is an error message in root
            if "error" in data or "detail" in data:
                detail = data.get("error") or data.get("detail")
                raise TavilySearchError(f"Tavily returned error: {detail}")
            return ()

        if not isinstance(raw_items, list):
            raise TavilySearchError(
                f"Expected 'results' to be a list, got {type(raw_items).__name__}."
            )

        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            raw_url = item.get("url")
            if not raw_url or not isinstance(raw_url, str):
                continue
            clean_url = raw_url.strip()

            # Ensure valid HTTP/HTTPS scheme and hostname
            parsed_url = urllib.parse.urlparse(clean_url)
            if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.netloc:
                continue

            # Deduplicate by URL
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            domain = extract_domain_from_url(clean_url) or parsed_url.netloc.lower()

            # Title
            raw_title = item.get("title")
            title = (raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else domain)

            # Snippet / content
            raw_content = item.get("content")
            if isinstance(raw_content, str) and raw_content.strip():
                snippet = raw_content.strip()
            else:
                snippet = title

            # Preserve provider metadata
            raw_metadata: dict[str, Any] = {
                "engine": "tavily",
                "score": item.get("score"),
                "query": query,
            }

            try:
                record = SearchResult(
                    url=clean_url,
                    title=title,
                    snippet=snippet,
                    domain=domain,
                    raw_data=raw_metadata,
                )
                validate_search_result_record(record)
                results.append(record)
            except Exception as exc:
                logger.debug("Skipping unvalidatable search result '%s': %s", clean_url, exc)
                continue

            if len(results) >= max_results:
                break

        return tuple(results)
