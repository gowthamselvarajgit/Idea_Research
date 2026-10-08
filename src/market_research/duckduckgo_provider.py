"""DuckDuckGo HTML search discovery provider for market research.

Implements the SearchProvider protocol using standard-library urllib and html.parser,
executing queries against the DuckDuckGo HTML endpoint and extracting structured SearchResults.
"""

from html.parser import HTMLParser
import html
import logging
import socket
from typing import Any, Callable, Optional, Sequence
import urllib.error
import urllib.parse
import urllib.request

from src.market_research.search_client import SearchProvider, SearchProviderError
from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_ENDPOINT: str = "https://html.duckduckgo.com/html/"
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_SECONDS: float = 10.0


class DuckDuckGoSearchError(SearchProviderError):
    """Base exception for DuckDuckGo HTML search provider failures."""
    pass


class DuckDuckGoHTTPError(DuckDuckGoSearchError):
    """Raised when DuckDuckGo returns an HTTP error response."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DuckDuckGoNetworkError(DuckDuckGoSearchError):
    """Raised when network connectivity or socket errors occur."""
    pass


class DuckDuckGoTimeoutError(DuckDuckGoNetworkError):
    """Raised when a search request exceeds the configured timeout."""
    pass


def decode_duckduckgo_url(raw_url: str) -> Optional[str]:
    """Extract and decode target destination URL from DuckDuckGo redirect or direct URL.

    Handles:
    - Protocol-relative URLs ('//duckduckgo.com/l/?uddg=...')
    - Root-relative URLs ('/l/?uddg=...')
    - Absolute DuckDuckGo redirect URLs ('https://duckduckgo.com/l/?uddg=...')
    - Direct destination HTTP/HTTPS URLs ('https://example.com/...')
    - Rejection of non-HTTP/HTTPS URLs ('ftp://', 'javascript:', etc.)
    - Rejection of DuckDuckGo internal site navigation links

    Args:
        raw_url: Raw href attribute extracted from HTML.

    Returns:
        Optional[str]: Decoded destination HTTP/HTTPS URL, or None if invalid.
    """
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None

    url_str = raw_url.strip()

    if url_str.startswith("//"):
        url_str = "https:" + url_str
    elif url_str.startswith("/"):
        url_str = "https://duckduckgo.com" + url_str

    try:
        parsed = urllib.parse.urlparse(url_str)
    except Exception:
        return None

    target_url = url_str

    # Check for DuckDuckGo redirect link with 'uddg' parameter
    if "duckduckgo.com" in parsed.netloc.lower() or parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            candidate = qs["uddg"][0].strip()
            target_url = urllib.parse.unquote(candidate)
        else:
            # Internal DuckDuckGo link without uddg is not an external search result
            return None

    try:
        target_parsed = urllib.parse.urlparse(target_url)
        if target_parsed.scheme.lower() not in ("http", "https"):
            return None
        if not target_parsed.netloc:
            return None
        # Reject if still pointing to duckduckgo.com internal
        if "duckduckgo.com" in target_parsed.netloc.lower():
            return None
        return target_url
    except Exception:
        return None


def extract_domain_from_url(url: str) -> Optional[str]:
    """Extract publishing domain name from a URL, stripping port and leading 'www.'."""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc:
            return None
        domain = netloc.split(":")[0]
        if domain.startswith("www.") and len(domain) > 4:
            domain = domain[4:]
        return domain or netloc
    except Exception:
        return None


class _DuckDuckGoHTMLParser(HTMLParser):
    """HTML parser extracting structured SearchResults from DuckDuckGo HTML output."""

    def __init__(self, max_results: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_results = max_results
        self.results: list[SearchResult] = []
        self.seen_urls: set[str] = set()

        self._current_url: Optional[str] = None
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

        self._in_title = False
        self._title_depth = 0
        self._in_snippet = False
        self._snippet_depth = 0

    def _commit_current(self) -> None:
        """Validate and commit current candidate result if complete."""
        if not self._current_url:
            self._reset_current()
            return

        raw_title = "".join(self._current_title_parts)
        raw_snippet = "".join(self._current_snippet_parts)

        clean_title = " ".join(html.unescape(raw_title).split())
        clean_snippet = " ".join(html.unescape(raw_snippet).split())

        if not clean_title or not clean_snippet:
            self._reset_current()
            return

        dest_url = decode_duckduckgo_url(self._current_url)
        if not dest_url:
            self._reset_current()
            return

        url_key = dest_url.strip().lower()
        if url_key in self.seen_urls:
            self._reset_current()
            return

        domain = extract_domain_from_url(dest_url)
        if not domain:
            self._reset_current()
            return

        try:
            result = SearchResult(
                url=dest_url,
                title=clean_title,
                snippet=clean_snippet,
                domain=domain,
                raw_data={"source": "duckduckgo_html"},
            )
            self.results.append(result)
            self.seen_urls.add(url_key)
        except Exception as exc:
            logger.debug("Skipping malformed search result: %s", exc)

        self._reset_current()

    def _reset_current(self) -> None:
        self._current_url = None
        self._current_title_parts = []
        self._current_snippet_parts = []
        self._in_title = False
        self._title_depth = 0
        self._in_snippet = False
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if len(self.results) >= self.max_results:
            return

        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        class_str = attr_dict.get("class", "").lower()
        class_list = class_str.split()

        # Check for title anchor link: <a class="result__a" href="...">
        is_title_anchor = tag == "a" and any("result__a" in c for c in class_list)

        if is_title_anchor:
            self._commit_current()
            self._current_url = attr_dict.get("href", "")
            self._in_title = True
            self._title_depth = 1
            return

        if self._in_title:
            self._title_depth += 1

        # Check for snippet container: <a class="result__snippet" ...> or <div class="result__snippet">
        is_snippet = any("result__snippet" in c for c in class_list)
        if is_snippet:
            self._in_snippet = True
            self._snippet_depth = 1
            return

        if self._in_snippet:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._in_title:
            self._title_depth -= 1
            if self._title_depth <= 0:
                self._in_title = False
                self._title_depth = 0

        if self._in_snippet:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._in_snippet = False
                self._snippet_depth = 0
                if self._current_url and self._current_title_parts and self._current_snippet_parts:
                    self._commit_current()

    def handle_data(self, data: str) -> None:
        if len(self.results) >= self.max_results:
            return
        if self._in_title:
            self._current_title_parts.append(data)
        elif self._in_snippet:
            self._current_snippet_parts.append(data)

    def close(self) -> None:
        super().close()
        self._commit_current()


class DuckDuckGoHTMLSearchProvider:
    """Real search discovery provider executing queries against DuckDuckGo HTML endpoint."""

    def __init__(
        self,
        endpoint: str = DUCKDUCKGO_HTML_ENDPOINT,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_transport: Optional[Callable[[urllib.request.Request, float], str | bytes]] = None,
    ) -> None:
        """Initialize DuckDuckGoHTMLSearchProvider.

        Args:
            endpoint: DuckDuckGo HTML endpoint URL.
            user_agent: User-Agent header string.
            timeout: Request timeout in seconds.
            http_transport: Optional callable for injecting HTTP execution (useful for testing).
        """
        if not endpoint or not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string.")
        if not user_agent or not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a non-empty string.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")

        self.endpoint = endpoint.strip()
        self.user_agent = user_agent.strip()
        self.timeout = float(timeout)
        self.http_transport = http_transport

    def search(self, query: str, max_results: int) -> Sequence[SearchResult]:
        """Execute a search query against DuckDuckGo HTML and return parsed SearchResult objects.

        Args:
            query: Non-empty search query string.
            max_results: Maximum number of search results requested (must be >= 1).

        Returns:
            Sequence[SearchResult]: Sequence of discovered and validated SearchResult objects.

        Raises:
            ValueError: If query is empty or max_results < 1.
            DuckDuckGoHTTPError: If HTTP request fails with status code.
            DuckDuckGoTimeoutError: If request times out.
            DuckDuckGoNetworkError: If network connectivity fails.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an integer >= 1.")

        clean_query = query.strip()
        post_data = urllib.parse.urlencode({"q": clean_query}).encode("utf-8")
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        req = urllib.request.Request(
            url=self.endpoint,
            data=post_data,
            headers=headers,
            method="POST",
        )

        try:
            if self.http_transport is not None:
                raw_response = self.http_transport(req, self.timeout)
                if isinstance(raw_response, bytes):
                    html_content = raw_response.decode("utf-8", errors="replace")
                else:
                    html_content = raw_response
            else:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    encoding = resp.headers.get_content_charset() or "utf-8"
                    html_content = resp.read().decode(encoding, errors="replace")
        except urllib.error.HTTPError as exc:
            logger.error("DuckDuckGo HTTP error %s for query '%s'", exc.code, clean_query)
            raise DuckDuckGoHTTPError(
                f"DuckDuckGo HTTP request failed with status {exc.code}: {exc.reason}",
                status_code=exc.code,
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            logger.error("DuckDuckGo request timed out for query '%s'", clean_query)
            raise DuckDuckGoTimeoutError(
                f"DuckDuckGo search request timed out after {self.timeout}s: {exc}"
            ) from exc
        except urllib.error.URLError as exc:
            logger.error("DuckDuckGo URL error for query '%s': %s", clean_query, exc)
            if isinstance(exc.reason, (socket.timeout, TimeoutError)) or "timed out" in str(exc.reason).lower():
                raise DuckDuckGoTimeoutError(
                    f"DuckDuckGo search request timed out: {exc}"
                ) from exc
            raise DuckDuckGoNetworkError(
                f"DuckDuckGo network request failed: {exc.reason}"
            ) from exc
        except Exception as exc:
            logger.error("DuckDuckGo unexpected error for query '%s': %s", clean_query, exc)
            raise DuckDuckGoNetworkError(
                f"DuckDuckGo search failed unexpectedly: {exc}"
            ) from exc

        parser = _DuckDuckGoHTMLParser(max_results=max_results)
        parser.feed(html_content)
        parser.close()

        return parser.results[:max_results]
