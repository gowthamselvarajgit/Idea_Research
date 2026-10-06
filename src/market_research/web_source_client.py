"""Standard-library HTTP client for retrieving and parsing web research sources.

Fetches public web pages over HTTP/HTTPS, strips scripts/styles, extracts clean text
and title metadata, and converts raw page contents into validated WebResearchSource instances.
"""

from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import logging
from typing import Final, Optional
import urllib.error
import urllib.parse
import urllib.request

from src.market_research.source_contract import validate_web_research_source_record
from src.market_research.source_models import ALLOWED_SOURCE_TYPES, WebResearchSource

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_USER_AGENT: Final[str] = "StartupResearchAgent/1.0 (WebResearchSourceClient; +https://example.com/bot)"

FORBIDDEN_HOSTS: Final[frozenset[str]] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
})


class WebSourceClientError(Exception):
    """Base exception for web source client operations."""
    pass


class WebSourceInvalidURLError(WebSourceClientError):
    """Raised when a URL is invalid, uses an unsupported scheme, or violates security constraints."""
    pass


class WebSourceHTTPError(WebSourceClientError):
    """Raised when an HTTP error status code (4xx, 5xx) is encountered."""
    pass


class WebSourceNetworkError(WebSourceClientError):
    """Raised when network connectivity, DNS resolution, or request timeout fails."""
    pass


class WebSourceContentError(WebSourceClientError):
    """Raised when page content is empty, non-text, or unusable."""
    pass


class HTMLContentExtractor(HTMLParser):
    """Clean HTML parser that extracts title and readable text while removing scripts/styles."""

    def __init__(self) -> None:
        super().__init__()
        self._title_parts: list[str] = []
        self._in_title = False
        self._ignored_tags: Final[set[str]] = {"script", "style", "noscript", "svg", "header", "footer"}
        self._ignored_depth = 0
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._ignored_depth += 1
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower in {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "section", "article"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "section", "article"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._ignored_depth == 0:
            stripped = data.strip()
            if stripped:
                self._text_parts.append(data)

    def get_title(self) -> str:
        """Return normalized title text."""
        raw_title = " ".join("".join(self._title_parts).split())
        return raw_title.strip()

    def get_text(self) -> str:
        """Return cleaned and collapsed readable body text."""
        raw = "".join(self._text_parts)
        lines = [line.strip() for line in raw.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return cleaned.strip()


def validate_target_url(url: str, allow_localhost: bool = False) -> urllib.parse.ParseResult:
    """Validate URL syntax, protocol scheme, and target host security rules.

    Args:
        url: URL string to validate.
        allow_localhost: If False, prohibits localhost and loopback targets.

    Returns:
        urllib.parse.ParseResult: Parsed URL structure.

    Raises:
        WebSourceInvalidURLError: If URL is empty, invalid, uses unsupported scheme, or targets forbidden hosts.
    """
    if not isinstance(url, str) or not url.strip():
        raise WebSourceInvalidURLError("URL must be a non-empty string.")

    clean_url = url.strip()

    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception as exc:
        raise WebSourceInvalidURLError(f"Malformed URL '{clean_url}': {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise WebSourceInvalidURLError(
            f"Unsupported URL scheme '{parsed.scheme}'. Only http:// and https:// are permitted."
        )

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise WebSourceInvalidURLError(f"URL '{clean_url}' lacks a valid hostname.")

    if not allow_localhost:
        if host in FORBIDDEN_HOSTS or host.startswith("127.") or host.endswith(".local"):
            raise WebSourceInvalidURLError(
                f"Access to local or loopback host '{host}' is prohibited for security."
            )

    return parsed


class WebSourceClient:
    """Standard-library HTTP client that retrieves web pages and constructs WebResearchSources."""

    def __init__(
        self,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: Optional[str] = None,
        allow_localhost: bool = False,
    ) -> None:
        """Initialize the client.

        Args:
            default_timeout: Network timeout in seconds.
            user_agent: Custom User-Agent header string.
            allow_localhost: If True, allows local loopback addresses (for test setups).
        """
        self.default_timeout = default_timeout
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.allow_localhost = allow_localhost

    def fetch_source(
        self,
        url: str,
        source_type: str = "other",
        timeout: Optional[float] = None,
    ) -> WebResearchSource:
        """Retrieve web page content and return a validated WebResearchSource.

        Workflow:
            1. Validate URL and security constraints.
            2. Validate requested source_type.
            3. Perform HTTP GET using urllib.request.
            4. Follow standard HTTP redirects and capture final URL.
            5. Extract clean title and readable body text, removing scripts/styles.
            6. Derive publisher/domain from final URL.
            7. Package response metadata into raw_data.
            8. Construct and validate immutable WebResearchSource.

        Args:
            url: Target HTTP/HTTPS URL.
            source_type: Controlled classification of source (default: "other").
            timeout: Optional override for request timeout.

        Returns:
            WebResearchSource: Validated immutable source record.

        Raises:
            WebSourceInvalidURLError: For invalid URLs or prohibited schemes/hosts.
            WebSourceHTTPError: For HTTP 4xx or 5xx status codes.
            WebSourceNetworkError: For network connection or timeout errors.
            WebSourceContentError: When page body is empty or unusable.
        """
        parsed_url = validate_target_url(url, allow_localhost=self.allow_localhost)

        clean_st = source_type.strip().lower()
        if clean_st not in ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type: '{source_type}'. Allowed values: {sorted(list(ALLOWED_SOURCE_TYPES))}."
            )

        req_timeout = timeout if timeout is not None else self.default_timeout

        req = urllib.request.Request(
            url=url.strip(),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as response:
                final_url = response.geturl()
                status_code = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type", "")

                # Decode raw bytes using detected or fallback encoding
                raw_bytes = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    html_text = raw_bytes.decode(charset, errors="replace")
                except Exception:
                    html_text = raw_bytes.decode("utf-8", errors="replace")

        except urllib.error.HTTPError as exc:
            raise WebSourceHTTPError(
                f"HTTP request failed with status {exc.code} for '{url}': {exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WebSourceNetworkError(
                f"Network error while retrieving '{url}': {exc}"
            ) from exc

        # Parse HTML text and extract readable body and title
        extractor = HTMLContentExtractor()
        try:
            extractor.feed(html_text)
        except Exception as exc:
            logger.warning("HTML parsing warning for '%s': %s", final_url, exc)

        extracted_text = extractor.get_text()
        if not extracted_text:
            raise WebSourceContentError(
                f"Extracted content from '{final_url}' is empty or contains no readable text."
            )

        # Determine title (fallback to domain if title missing)
        final_parsed = urllib.parse.urlparse(final_url)
        domain = final_parsed.netloc.lower()

        extracted_title = extractor.get_title()
        title = extracted_title if extracted_title else f"{domain} - {final_parsed.path or '/'}"

        retrieval_timestamp = datetime.now(timezone.utc).isoformat()

        raw_data = {
            "initial_url": url.strip(),
            "final_url": final_url,
            "http_status": status_code,
            "content_type": content_type,
            "content_length": len(raw_bytes),
            "redirected": (url.strip() != final_url),
        }

        source = WebResearchSource(
            url=final_url,
            title=title,
            source_type=clean_st,
            publisher_or_domain=domain,
            retrieved_content=extracted_text,
            retrieved_at=retrieval_timestamp,
            id=None,
            raw_data=raw_data,
        )

        validate_web_research_source_record(source)
        return source


def fetch_source(
    url: str,
    source_type: str = "other",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    allow_localhost: bool = False,
) -> WebResearchSource:
    """Functional convenience wrapper for retrieving a web research source.

    Args:
        url: Target HTTP/HTTPS URL.
        source_type: Source category classification.
        timeout: Request timeout in seconds.
        allow_localhost: Whether to permit localhost targets.

    Returns:
        WebResearchSource: Validated immutable source record.
    """
    client = WebSourceClient(default_timeout=timeout, allow_localhost=allow_localhost)
    return client.fetch_source(url=url, source_type=source_type)
