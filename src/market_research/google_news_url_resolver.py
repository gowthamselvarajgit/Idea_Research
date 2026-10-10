"""Google News RSS article link resolver.

Resolves intermediate Google News RSS article URLs (e.g.
https://news.google.com/rss/articles/CBMi...) to their actual publisher destination
URLs using Python standard library tools (urllib.request, json, re).

Also extracts publisher URLs when available in RSS metadata (e.g. <source url="...">).
"""

from collections.abc import Callable
import json
import logging
import re
from typing import Any, Final, Optional
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

DEFAULT_RESOLVER_TIMEOUT: Final[float] = 10.0
DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

BATCHEXECUTE_URL: Final[str] = "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
GOOGLE_NEWS_DOMAINS: Final[frozenset[str]] = frozenset({
    "news.google.com",
    "news.google.co.uk",
    "news.google.ca",
    "news.google.com.au",
    "news.google.co.in",
})

SG_PATTERN: Final[re.Pattern[str]] = re.compile(r'data-n-a-sg="([^"]+)"')
TS_PATTERN: Final[re.Pattern[str]] = re.compile(r'data-n-a-ts="([^"]+)"')
ID_PATTERN: Final[re.Pattern[str]] = re.compile(r'data-n-a-id="([^"]+)"')


def is_google_news_url(url: Optional[str]) -> bool:
    """Return True if the URL is an intermediate Google News article redirect link."""
    if not url or not isinstance(url, str):
        return False
    clean = url.strip()
    try:
        parsed = urllib.parse.urlparse(clean)
        host = (parsed.hostname or "").lower()
        if host not in GOOGLE_NEWS_DOMAINS and not host.endswith(".news.google.com"):
            return False
        path = parsed.path.lower()
        return (
            "/rss/articles/" in path
            or "/articles/" in path
            or path.startswith("/read/")
        )
    except Exception:
        return False


def extract_google_news_article_id(url: str) -> Optional[str]:
    """Extract the article token identifier from a Google News article URL."""
    if not is_google_news_url(url):
        return None
    try:
        parsed = urllib.parse.urlparse(url.strip())
        path = parsed.path.rstrip("/")
        if "/articles/" in path:
            return path.split("/articles/")[-1].strip("/")
        if path.startswith("/read/"):
            return path[len("/read/"):].strip("/")
        return None
    except Exception:
        return None


def extract_publisher_url_from_metadata(metadata: Optional[dict[str, Any]]) -> Optional[str]:
    """Extract publisher destination URL from search result or crawler metadata.

    Inspects standard fields: publisher_url, source_url, article_url, and original_url.
    Validates that the candidate is a valid HTTP/HTTPS URL and not a Google News redirect.
    """
    if not metadata or not isinstance(metadata, dict):
        return None

    candidates = (
        metadata.get("publisher_url"),
        metadata.get("source_url"),
        metadata.get("article_url"),
        metadata.get("original_url"),
    )

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            clean = cand.strip()
            try:
                parsed = urllib.parse.urlparse(clean)
                if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
                    if not is_google_news_url(clean):
                        return clean
            except Exception:
                continue

    return None


def extract_publisher_url_from_rss_item(item_elem: ET.Element) -> Optional[str]:
    """Extract publisher URL from a Google News or syndicated RSS <item> element.

    Checks:
    1. <source url="..."> attribute
    2. <feedburner:origLink> or <origLink> element
    3. <guid isPermaLink="true">
    """
    if item_elem is None or not isinstance(item_elem, ET.Element):
        return None

    # 1. <source url="...">
    source_elem = item_elem.find("source")
    if source_elem is not None:
        url_attr = source_elem.get("url", "").strip()
        if url_attr:
            try:
                parsed = urllib.parse.urlparse(url_attr)
                if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
                    if not is_google_news_url(url_attr):
                        return url_attr
            except Exception:
                pass

    # 2. <origLink> or FeedBurner equivalent
    for tag in ("origLink", "{http://rssnamespace.org/feedburner/ext/1.0}origLink"):
        orig_elem = item_elem.find(tag)
        if orig_elem is not None and orig_elem.text:
            orig_url = orig_elem.text.strip()
            if orig_url and not is_google_news_url(orig_url):
                try:
                    parsed = urllib.parse.urlparse(orig_url)
                    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
                        return orig_url
                except Exception:
                    pass

    # 3. <guid isPermaLink="true">
    guid_elem = item_elem.find("guid")
    if guid_elem is not None and guid_elem.get("isPermaLink", "").lower() == "true":
        guid_text = (guid_elem.text or "").strip()
        if guid_text and not is_google_news_url(guid_text):
            try:
                parsed = urllib.parse.urlparse(guid_text)
                if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
                    return guid_text
            except Exception:
                pass

    return None


class GoogleNewsURLResolver:
    """Standard-library resolver for converting Google News RSS links to publisher URLs."""

    def __init__(
        self,
        timeout: float = DEFAULT_RESOLVER_TIMEOUT,
        user_agent: Optional[str] = None,
        http_transport: Optional[Callable[[urllib.request.Request, float], str | bytes]] = None,
    ) -> None:
        """Initialize GoogleNewsURLResolver.

        Args:
            timeout: Network timeout in seconds for resolution requests.
            user_agent: Custom User-Agent header string.
            http_transport: Optional injected callable for testing network interactions.
        """
        self.timeout = float(timeout) if timeout > 0 else DEFAULT_RESOLVER_TIMEOUT
        self.user_agent = user_agent.strip() if user_agent and user_agent.strip() else DEFAULT_USER_AGENT
        self.http_transport = http_transport

    def _execute_http(self, req: urllib.request.Request, timeout: float) -> str:
        """Execute HTTP request either through injected transport or urllib.request."""
        if self.http_transport is not None:
            raw = self.http_transport(req, timeout)
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
            return str(raw)

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw_bytes.decode(charset, errors="replace")

    def resolve_url(
        self,
        url: str,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Resolve a Google News RSS article URL to its actual publisher destination URL.

        If the URL is not a Google News URL, it is returned unchanged.
        If resolution fails due to network error, unexpected format, or missing signature,
        None is returned safely without raising unhandled exceptions.

        Args:
            url: Google News article URL or direct publisher URL.
            timeout: Optional per-request timeout override.

        Returns:
            str: Resolved publisher destination URL, or None if resolution failed.
        """
        if not isinstance(url, str) or not url.strip():
            return None

        clean_url = url.strip()

        # If already a direct publisher URL, return as-is
        if not is_google_news_url(clean_url):
            return clean_url

        art_id = extract_google_news_article_id(clean_url)
        if not art_id:
            logger.debug("Could not extract article ID from Google News URL: %s", clean_url)
            return None

        req_timeout = timeout if timeout is not None and timeout > 0 else self.timeout

        # ---------------------------------------------------------------------
        # Step 1: GET intermediate splash page to obtain signature and timestamp
        # ---------------------------------------------------------------------
        step1_url = f"https://news.google.com/rss/articles/{art_id}?hl=en-US&gl=US&ceid=US:en"
        step1_req = urllib.request.Request(
            step1_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            method="GET",
        )

        try:
            body = self._execute_http(step1_req, req_timeout)
        except Exception as exc:
            logger.warning("Google News URL resolution step 1 failed for %s: %s", art_id, exc)
            return None

        # Check for direct anchor tag or direct URL in body (legacy format)
        direct_anchor_match = re.search(
            r'<c-wiz[^>]*>.*?<a\s+[^>]*href=["\'](https?://(?!news\.google\.)[^"\']+)["\']',
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if direct_anchor_match:
            dest = direct_anchor_match.group(1).strip()
            if dest and not is_google_news_url(dest):
                return dest

        sg_match = SG_PATTERN.search(body)
        ts_match = TS_PATTERN.search(body)
        id_match = ID_PATTERN.search(body)

        sg = sg_match.group(1) if sg_match else None
        ts = ts_match.group(1) if ts_match else None
        effective_id = id_match.group(1) if id_match else art_id

        if not sg or not ts:
            logger.debug(
                "Google News page did not contain expected signature/timestamp for %s",
                art_id,
            )
            return None

        try:
            ts_int = int(ts)
        except (ValueError, TypeError):
            ts_int = 0

        # ---------------------------------------------------------------------
        # Step 2: POST to DotsSplashUi batchexecute RPC endpoint
        # ---------------------------------------------------------------------
        req_obj = [
            "garturlreq",
            [
                ["en-US", "US", ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"], None, None, 1, 1, "US:en", None, None, None, None, None, None, None, 0, 5],
                "en-US",
                "US",
                True,
                [2, 4, 8],
                1,
                True,
                "661099999",
                0,
                0,
                None,
                0,
            ],
            effective_id,
            ts_int,
            sg,
        ]

        payload = urllib.parse.urlencode({
            "f.req": json.dumps([[["Fbv4je", json.dumps(req_obj), None, "generic"]]])
        }).encode("utf-8")

        step2_req = urllib.request.Request(
            BATCHEXECUTE_URL,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        try:
            resp_text = self._execute_http(step2_req, req_timeout)
        except Exception as exc:
            logger.warning("Google News URL resolution step 2 failed for %s: %s", art_id, exc)
            return None

        # ---------------------------------------------------------------------
        # Step 3: Parse batchexecute response
        # ---------------------------------------------------------------------
        try:
            clean_text = resp_text.lstrip(")]}' \n\r")
            data = json.loads(clean_text)
            if not isinstance(data, list) or not data:
                return None
            first_entry = data[0]
            if not isinstance(first_entry, list) or len(first_entry) < 3:
                return None
            array_string = first_entry[2]
            if not array_string or not isinstance(array_string, str):
                return None
            decoded_array = json.loads(array_string)
            if not isinstance(decoded_array, list) or len(decoded_array) < 2:
                return None
            dest_url = decoded_array[1]
            if isinstance(dest_url, str) and dest_url.strip():
                dest_clean = dest_url.strip()
                parsed_dest = urllib.parse.urlparse(dest_clean)
                if parsed_dest.scheme.lower() in ("http", "https") and parsed_dest.netloc:
                    if not is_google_news_url(dest_clean):
                        return dest_clean
        except Exception as exc:
            logger.debug("Failed to parse batchexecute response for %s: %s", art_id, exc)
            return None

        return None


def resolve_google_news_url(
    url: str,
    timeout: float = DEFAULT_RESOLVER_TIMEOUT,
    user_agent: Optional[str] = None,
    http_transport: Optional[Callable[[urllib.request.Request, float], str | bytes]] = None,
) -> Optional[str]:
    """Convenience functional wrapper to resolve a Google News article URL."""
    resolver = GoogleNewsURLResolver(
        timeout=timeout,
        user_agent=user_agent,
        http_transport=http_transport,
    )
    return resolver.resolve_url(url)
