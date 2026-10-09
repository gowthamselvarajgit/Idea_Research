"""Google News RSS search discovery provider for web market research.

Implements the SearchProvider protocol using Python standard-library urllib and
xml.etree.ElementTree, executing queries against the public Google News RSS feed
(https://news.google.com/rss/search).

Provides an unauthenticated, zero-cost, legitimate public discovery source for
industry news, competitor moves, products, market gaps, and emerging trends without
scraping HTML search engine result pages or requiring paid API credentials.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import html
import logging
import re
import socket
from typing import Any, Callable, Final, Optional
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from src.market_research.search_client import (
    DEFAULT_MAX_RESULTS,
    MAX_ALLOWED_RESULTS,
    SearchProvider,
    SearchProviderError,
)
from src.market_research.search_contract import validate_search_result_record
from src.market_research.search_models import SearchResult

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS_ENDPOINT: Final[str] = "https://news.google.com/rss/search"
DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_HL: Final[str] = "en-US"
DEFAULT_GL: Final[str] = "US"
DEFAULT_CEID: Final[str] = "US:en"

DEFAULT_NEGATIVE_TERMS: Final[tuple[str, ...]] = (
    "investment app",
    "investing app",
    "stock trading",
    "trading app",
    "cryptocurrency",
    "crypto trading",
    "wealth management",
    "real estate",
    "mortgage",
)

COMMON_STOP_WORDS: Final[frozenset[str]] = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "for", "with", "at",
    "by", "to", "from", "as", "is", "are", "was", "were", "be", "been",
    "it", "its", "that", "this", "these", "those", "how", "what", "why",
    "apps", "app", "tools", "tool", "features", "news", "top", "best",
    "2024", "2025", "2026", "2027", "guide", "review", "overview",
})


class GoogleNewsSearchError(SearchProviderError):
    """Base exception for Google News RSS search provider failures."""
    pass


class GoogleNewsHTTPError(GoogleNewsSearchError):
    """Raised when Google News RSS returns an HTTP error response."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleNewsNetworkError(GoogleNewsSearchError):
    """Raised when network connectivity or socket errors occur."""
    pass


class GoogleNewsTimeoutError(GoogleNewsNetworkError):
    """Raised when a Google News RSS request exceeds the configured timeout."""
    pass


class GoogleNewsParseError(GoogleNewsSearchError):
    """Raised when the RSS XML response is malformed or unparseable."""
    pass


@dataclass(frozen=True)
class CandidateDecision:
    """Explainable relevance decision for a single Google News RSS item.

    Attributes:
        title: Truncated candidate title.
        url: Candidate destination URL.
        accepted: Boolean flag whether candidate met relevance criteria.
        reason: Explainable human-readable rationale for inclusion/exclusion.
        matched_terms: Matched subject or query terms.
    """

    title: str
    url: str
    accepted: bool
    reason: str
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchDiagnostics:
    """Diagnostic metrics and candidate decisions for the latest Google News RSS query.

    Attributes:
        query: Search query executed.
        feed_items_count: Total raw <item> entries in RSS feed.
        examined_count: Number of candidates parsed and evaluated.
        accepted_count: Number of candidates that passed relevance filtering.
        rejected_count: Number of candidates rejected by relevance filtering.
        feed_was_empty: True if the RSS feed genuinely had 0 items.
        all_filtered_out: True if feed had items but all were filtered out.
        decisions: Bounded tuple of candidate decisions for explainability.
    """

    query: str
    feed_items_count: int
    examined_count: int
    accepted_count: int
    rejected_count: int
    feed_was_empty: bool
    all_filtered_out: bool
    decisions: tuple[CandidateDecision, ...] = ()


def extract_domain_from_url(url: str) -> Optional[str]:
    """Extract normalized publishing domain from a URL, stripping leading www."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parsed = urllib.parse.urlparse(url.strip())
        netloc = parsed.netloc.lower()
        if not netloc:
            return None
        domain = netloc.split(":")[0]
        if domain.startswith("www.") and len(domain) > 4:
            domain = domain[4:]
        return domain or netloc
    except Exception:
        return None


def strip_html_tags(raw_text: str) -> str:
    """Unescape HTML entities and remove tags to yield clean plaintext."""
    if not raw_text or not isinstance(raw_text, str):
        return ""
    unescaped = html.unescape(raw_text)
    cleaned = re.sub(r"<[^>]+>", " ", unescaped)
    return " ".join(cleaned.split())


def evaluate_candidate_relevance(
    title: str,
    snippet: str,
    domain: str,
    publisher: str,
    query: str,
    url: str = "",
    subject_terms: Optional[Sequence[str]] = None,
    negative_terms: Sequence[str] = DEFAULT_NEGATIVE_TERMS,
) -> CandidateDecision:
    """Evaluate candidate article relevance using explainable, conservative rules.

    Args:
        title: Article title.
        snippet: Article snippet or description plaintext.
        domain: Publishing domain.
        publisher: Publisher source name.
        query: Search query executed.
        url: Destination URL.
        subject_terms: Optional configurable subject/domain keywords.
        negative_terms: Sequence of off-topic phrases.

    Returns:
        CandidateDecision: Structured explainable decision.
    """
    full_text = f"{title} {snippet} {domain} {publisher}".lower()
    text_words = set(re.findall(r"\b[a-z0-9_-]+\b", full_text))

    # Identify negative off-topic signals
    found_negatives = [neg for neg in negative_terms if neg.lower() in full_text]

    # 1. Subject terms check (if explicitly configured)
    matched_subjects: list[str] = []
    if subject_terms:
        for st in subject_terms:
            st_clean = st.strip().lower()
            if not st_clean:
                continue
            if st_clean in full_text:
                matched_subjects.append(st_clean)
            elif len(st_clean) >= 4 and any(
                w.startswith(st_clean) or (st_clean.startswith(w) and len(w) >= 4)
                for w in text_words
            ):
                matched_subjects.append(st_clean)

    # 2. Quoted anchors check (e.g. "skincare", "WATER QUALITY")
    quoted_phrases = [q.strip().lower() for q in re.findall(r'"([^"]+)"', query) if q.strip()]
    matched_anchors: list[str] = []
    for qp in quoted_phrases:
        if qp in full_text:
            matched_anchors.append(qp)
        else:
            qp_tokens = [
                tok for tok in re.findall(r"\b[a-z0-9_-]{3,}\b", qp)
                if tok not in COMMON_STOP_WORDS
            ]
            for tok in qp_tokens:
                if tok in full_text or any(
                    w.startswith(tok) or (tok.startswith(w) and len(w) >= 4)
                    for w in text_words
                    if len(tok) >= 4
                ):
                    matched_anchors.append(tok)

    # 3. General query tokens
    query_tokens = [
        tok for tok in re.findall(r"\b[a-z0-9_-]{3,}\b", query.lower())
        if tok not in COMMON_STOP_WORDS
    ]
    matched_query_tokens: list[str] = []
    for tok in query_tokens:
        if tok in full_text or any(
            w.startswith(tok) or (tok.startswith(w) and len(w) >= 4)
            for w in text_words
            if len(tok) >= 4
        ):
            matched_query_tokens.append(tok)

    # 4. Apply explainable decision logic
    # Rule A: Off-topic negative terms found
    if found_negatives:
        if matched_subjects or matched_anchors:
            matched = tuple(dict.fromkeys(matched_subjects or matched_anchors))
            return CandidateDecision(
                title=title[:80],
                url=url,
                accepted=True,
                reason=f"Accepted: Matched subject/anchor {list(matched)} despite negative signal {found_negatives}",
                matched_terms=matched,
            )
        return CandidateDecision(
            title=title[:80],
            url=url,
            accepted=False,
            reason=f"Rejected: Contains off-topic negative term(s) {found_negatives} with no subject match",
        )

    # Rule B: Configured subject terms provided
    if subject_terms:
        if matched_subjects:
            matched = tuple(dict.fromkeys(matched_subjects))
            return CandidateDecision(
                title=title[:80],
                url=url,
                accepted=True,
                reason=f"Accepted: Matched configured subject term(s) {list(matched)}",
                matched_terms=matched,
            )
        if matched_anchors:
            matched = tuple(dict.fromkeys(matched_anchors))
            return CandidateDecision(
                title=title[:80],
                url=url,
                accepted=True,
                reason=f"Accepted: Matched quoted anchor term(s) {list(matched)}",
                matched_terms=matched,
            )
        return CandidateDecision(
            title=title[:80],
            url=url,
            accepted=False,
            reason=f"Rejected: No match with configured subject terms {list(subject_terms)}",
        )

    # Rule C: Quoted anchor was present in query
    if quoted_phrases:
        if matched_anchors:
            matched = tuple(dict.fromkeys(matched_anchors))
            return CandidateDecision(
                title=title[:80],
                url=url,
                accepted=True,
                reason=f"Accepted: Matched quoted subject anchor {list(matched)}",
                matched_terms=matched,
            )
        return CandidateDecision(
            title=title[:80],
            url=url,
            accepted=False,
            reason=f"Rejected: Missing quoted subject anchor {quoted_phrases}",
        )

    # Rule D: General query tokens fallback
    if matched_query_tokens:
        matched = tuple(dict.fromkeys(matched_query_tokens))
        return CandidateDecision(
            title=title[:80],
            url=url,
            accepted=True,
            reason=f"Accepted: Matched query term(s) {list(matched)}",
            matched_terms=matched,
        )

    return CandidateDecision(
        title=title[:80],
        url=url,
        accepted=False,
        reason=f"Rejected: No overlap with significant query terms {query_tokens}",
    )


class GoogleNewsRSSSearchProvider:
    """Pluggable SearchProvider implementation for Google News RSS with relevance filtering.

    Implements the SearchProvider protocol, allowing drop-in use in SearchClient
    and FallbackSearchProvider composites.
    """

    name: str = "GoogleNewsRSSSearchProvider"

    def __init__(
        self,
        endpoint: str = GOOGLE_NEWS_RSS_ENDPOINT,
        hl: str = DEFAULT_HL,
        gl: str = DEFAULT_GL,
        ceid: str = DEFAULT_CEID,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        http_transport: Optional[Callable[[urllib.request.Request, float], str | bytes]] = None,
        subject_terms: Optional[Sequence[str]] = None,
        negative_terms: Optional[Sequence[str]] = None,
        relevance_filter_enabled: bool = True,
    ) -> None:
        """Initialize GoogleNewsRSSSearchProvider.

        Args:
            endpoint: Base Google News RSS search URL.
            hl: Host language code (e.g. 'en-US').
            gl: Geolocation / country code (e.g. 'US').
            ceid: Country-edition ID (e.g. 'US:en').
            timeout: Request timeout in seconds.
            user_agent: Custom User-Agent header string.
            http_transport: Optional callable for injecting HTTP execution (for testing).
            subject_terms: Optional configurable domain/subject terms for candidate filtering.
            negative_terms: Optional sequence of off-topic negative phrases.
            relevance_filter_enabled: Whether to apply candidate relevance filtering (default True).
        """
        if not endpoint or not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")

        self.endpoint = endpoint.strip()
        self.hl = hl.strip() if isinstance(hl, str) and hl.strip() else DEFAULT_HL
        self.gl = gl.strip() if isinstance(gl, str) and gl.strip() else DEFAULT_GL
        self.ceid = ceid.strip() if isinstance(ceid, str) and ceid.strip() else DEFAULT_CEID
        self.timeout = float(timeout)
        self.user_agent = user_agent.strip() if user_agent and user_agent.strip() else DEFAULT_USER_AGENT
        self.http_transport = http_transport
        self.subject_terms = tuple(subject_terms) if subject_terms is not None else None
        self.negative_terms = tuple(negative_terms) if negative_terms is not None else DEFAULT_NEGATIVE_TERMS
        self.relevance_filter_enabled = relevance_filter_enabled
        self.last_diagnostics: Optional[SearchDiagnostics] = None

    @property
    def diagnostics(self) -> Optional[SearchDiagnostics]:
        """Diagnostic metrics and candidate decisions for the latest search execution."""
        return self.last_diagnostics

    def search(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        *,
        subject_terms: Optional[Sequence[str]] = None,
        negative_terms: Optional[Sequence[str]] = None,
    ) -> Sequence[SearchResult]:
        """Execute search query against Google News RSS and return validated SearchResults.

        Args:
            query: Non-empty search query string.
            max_results: Maximum desired search results (must be >= 1).
            subject_terms: Optional per-query override of subject/domain keywords.
            negative_terms: Optional per-query override of off-topic phrases.

        Returns:
            Sequence[SearchResult]: Sequence of discovered and validated SearchResult records.

        Raises:
            ValueError: If query is empty or max_results < 1.
            GoogleNewsHTTPError: If the HTTP request fails with a non-200 status code.
            GoogleNewsTimeoutError: If the request times out.
            GoogleNewsNetworkError: If network connectivity fails.
            GoogleNewsParseError: If the RSS XML response cannot be parsed.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string.")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an integer >= 1.")

        clean_query = query.strip()
        bounded_max_results = min(max_results, MAX_ALLOWED_RESULTS)

        # Build RSS search URL with query parameters
        params = {
            "q": clean_query,
            "hl": self.hl,
            "gl": self.gl,
            "ceid": self.ceid,
        }
        query_string = urllib.parse.urlencode(params)
        request_url = f"{self.endpoint}?{query_string}"

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(
            url=request_url,
            headers=headers,
            method="GET",
        )

        xml_content: str = self._execute_request(req, clean_query)
        effective_subjects = subject_terms if subject_terms is not None else self.subject_terms
        effective_negatives = negative_terms if negative_terms is not None else self.negative_terms

        return self._parse_rss(
            xml_content=xml_content,
            query=clean_query,
            max_results=bounded_max_results,
            subject_terms=effective_subjects,
            negative_terms=effective_negatives,
        )

    def _execute_request(self, req: urllib.request.Request, query: str) -> str:
        """Execute HTTP request either through injected transport or urllib.request."""
        try:
            if self.http_transport is not None:
                raw_response = self.http_transport(req, self.timeout)
                if isinstance(raw_response, bytes):
                    return raw_response.decode("utf-8", errors="replace")
                return str(raw_response)

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                encoding = resp.headers.get_content_charset() or "utf-8"
                content = resp.read()
                return content.decode(encoding, errors="replace")

        except urllib.error.HTTPError as exc:
            logger.error("Google News RSS HTTP error %s for query '%s'", exc.code, query)
            raise GoogleNewsHTTPError(
                f"Google News RSS request failed with status {exc.code}: {exc.reason}",
                status_code=exc.code,
            ) from exc

        except (socket.timeout, TimeoutError) as exc:
            logger.error("Google News RSS request timed out for query '%s'", query)
            raise GoogleNewsTimeoutError(
                f"Google News RSS request timed out after {self.timeout}s: {exc}"
            ) from exc

        except urllib.error.URLError as exc:
            logger.error("Google News RSS URL error for query '%s': %s", query, exc)
            if isinstance(exc.reason, (socket.timeout, TimeoutError)) or "timed out" in str(exc.reason).lower():
                raise GoogleNewsTimeoutError(
                    f"Google News RSS request timed out: {exc}"
                ) from exc
            raise GoogleNewsNetworkError(
                f"Google News RSS network request failed: {exc.reason}"
            ) from exc

        except OSError as exc:
            logger.error("Google News RSS OS error for query '%s': %s", query, exc)
            raise GoogleNewsNetworkError(
                f"Google News RSS request failed unexpectedly: {exc}"
            ) from exc

    def _parse_rss(
        self,
        xml_content: str,
        query: str,
        max_results: int,
        subject_terms: Optional[Sequence[str]] = None,
        negative_terms: Sequence[str] = DEFAULT_NEGATIVE_TERMS,
    ) -> tuple[SearchResult, ...]:
        """Parse RSS XML, evaluate candidate relevance, and return validated SearchResult records."""
        if not xml_content or not xml_content.strip():
            logger.warning("Google News RSS returned empty response for query '%s'.", query)
            self.last_diagnostics = SearchDiagnostics(
                query=query,
                feed_items_count=0,
                examined_count=0,
                accepted_count=0,
                rejected_count=0,
                feed_was_empty=True,
                all_filtered_out=False,
                decisions=(),
            )
            return ()

        try:
            root = ET.fromstring(xml_content.strip())
        except ET.ParseError as exc:
            logger.error("Failed to parse Google News RSS XML for query '%s': %s", query, exc)
            raise GoogleNewsParseError(
                f"Invalid XML returned by Google News RSS for query '{query}': {exc}"
            ) from exc

        items = root.findall(".//item")
        if not items:
            logger.info("Google News RSS returned genuinely empty feed (0 items) for query '%s'.", query)
            self.last_diagnostics = SearchDiagnostics(
                query=query,
                feed_items_count=0,
                examined_count=0,
                accepted_count=0,
                rejected_count=0,
                feed_was_empty=True,
                all_filtered_out=False,
                decisions=(),
            )
            return ()

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        decisions_list: list[CandidateDecision] = []
        examined_count = 0
        rejected_count = 0

        for item in items:
            raw_title = item.findtext("title", "")
            raw_link = item.findtext("link", "")
            raw_desc = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")

            source_elem = item.find("source")
            publisher_name = source_elem.text.strip() if source_elem is not None and source_elem.text else ""
            source_url = source_elem.get("url", "").strip() if source_elem is not None else ""

            # Validate destination link
            if not raw_link or not isinstance(raw_link, str):
                continue
            clean_url = raw_link.strip()
            parsed_url = urllib.parse.urlparse(clean_url)
            if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.netloc:
                continue

            # Deduplicate by URL
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            # Determine title
            clean_title = " ".join(html.unescape(raw_title).split())
            if not clean_title:
                continue

            # Determine publisher / domain
            domain = ""
            if source_url:
                domain = extract_domain_from_url(source_url) or ""
            if not domain and publisher_name:
                domain = extract_domain_from_url(publisher_name) or ""
            if not domain:
                domain = extract_domain_from_url(clean_url) or parsed_url.netloc.lower()

            # Determine snippet
            clean_snippet = strip_html_tags(raw_desc)
            if not clean_snippet:
                clean_snippet = clean_title if not publisher_name else f"{clean_title} ({publisher_name})"

            # Candidate evaluation
            examined_count += 1
            if self.relevance_filter_enabled:
                decision = evaluate_candidate_relevance(
                    title=clean_title,
                    snippet=clean_snippet,
                    domain=domain,
                    publisher=publisher_name,
                    query=query,
                    url=clean_url,
                    subject_terms=subject_terms,
                    negative_terms=negative_terms if negative_terms is not None else DEFAULT_NEGATIVE_TERMS,
                )
                decisions_list.append(decision)
                logger.debug("Google News candidate '%s': %s", clean_title[:80], decision.reason)
                if not decision.accepted:
                    rejected_count += 1
                    continue
            else:
                decision = CandidateDecision(
                    title=clean_title[:80],
                    url=clean_url,
                    accepted=True,
                    reason="Accepted: Relevance filter disabled",
                )
                decisions_list.append(decision)

            raw_metadata: dict[str, Any] = {
                "engine": "google_news_rss",
                "publisher": publisher_name,
                "source_url": source_url,
                "pub_date": pub_date,
                "query": query,
                "relevance_reason": decision.reason,
            }

            try:
                record = SearchResult(
                    url=clean_url,
                    title=clean_title,
                    snippet=clean_snippet,
                    domain=domain,
                    raw_data=raw_metadata,
                )
                validate_search_result_record(record)
                results.append(record)
            except Exception as exc:
                logger.debug("Skipping unvalidatable Google News result '%s': %s", clean_url, exc)
                continue

            if len(results) >= max_results:
                break

        all_filtered = len(results) == 0 and len(items) > 0
        if all_filtered:
            logger.warning(
                "Google News RSS returned %d items for query '%s', but all candidates were filtered out by relevance criteria.",
                len(items),
                query,
            )

        self.last_diagnostics = SearchDiagnostics(
            query=query,
            feed_items_count=len(items),
            examined_count=examined_count,
            accepted_count=len(results),
            rejected_count=rejected_count,
            feed_was_empty=False,
            all_filtered_out=all_filtered,
            decisions=tuple(decisions_list[:25]),
        )

        return tuple(results)
