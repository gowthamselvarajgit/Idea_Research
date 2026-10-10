"""Citation URL grounding and source-metadata correlation for market research findings.

Correlates findings with actually collected WebResearchSource objects, verifies
citations conservatively, preserves discovery metadata, and flags unmatched,
ambiguous, or hallucinated citations.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
import logging
from typing import Any, Optional, Union
import urllib.parse

from src.market_research.evidence_status import classify_finding_evidence_status
from src.market_research.models import MarketResearchRecord
from src.market_research.source_models import WebResearchSource

logger = logging.getLogger(__name__)


def normalize_citation_url(url: Optional[str]) -> str:
    """Normalize a citation URL conservatively for resilient matching.

    Handles harmless differences:
    - Hostname casing (case-insensitive: e.g. EXAMPLE.COM -> example.com)
    - URL fragments (stripped: e.g. #section is client-side only)
    - Trailing slashes on paths (e.g. /path/ -> /path, / -> empty)
    - Default HTTP/HTTPS port (:80 for http, :443 for https)

    Preserves strict host identity:
    - Does NOT strip www. or subdomains: www.example.com and example.com are distinct
      unless explicitly linked by trustworthy crawler redirect metadata.
    - Preserves path casing and path hierarchy exactly.
    - Preserves query parameters exactly.

    Safely handles missing or malformed URLs:
    - Returns empty string for None, non-string, whitespace, missing scheme,
      unsupported scheme (only http/https permitted), or invalid hostnames.
    """
    if not url or not isinstance(url, str):
        return ""
    clean = url.strip()
    if not clean:
        return ""

    try:
        parsed = urllib.parse.urlsplit(clean)
    except Exception:
        return ""

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return ""

    # Validate hostname strictly
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return ""

    # Reject hosts with invalid structure (leading/trailing dots, consecutive dots, whitespace)
    if host.startswith(".") or host.endswith(".") or ".." in host or " " in host:
        return ""

    # Strip default port if present
    try:
        port = parsed.port
    except ValueError:
        return ""

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = host
    elif port is not None:
        netloc = f"{host}:{port}"
    else:
        netloc = host

    # Normalize path: strip trailing slash safely without changing empty or root identity
    path = parsed.path
    if path and path != "/":
        path = path.rstrip("/")
    elif path == "/":
        path = ""

    # Preserve exact query string
    query = f"?{parsed.query}" if parsed.query else ""

    return f"{scheme}://{netloc}{path}{query}"


class CitationSourceLookup(dict):
    """Dictionary mapping normalized URLs to WebResearchSources with ambiguous URL tracking."""

    def __init__(self, *args, ambiguous_urls: Optional[set[str]] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.ambiguous_urls: set[str] = set(ambiguous_urls) if ambiguous_urls else set()

    def is_ambiguous(self, norm_url: str) -> bool:
        """Return True if the URL was claimed by multiple distinct collected sources."""
        return norm_url in self.ambiguous_urls


def _are_same_source(s1: WebResearchSource, s2: WebResearchSource) -> bool:
    """Determine whether two WebResearchSource references represent the exact same collected source."""
    if s1 is s2:
        return True
    if s1.id and s2.id and s1.id.strip() == s2.id.strip():
        return True
    return (
        s1.url.strip() == s2.url.strip()
        and s1.retrieved_content == s2.retrieved_content
    )


def build_source_url_lookup(
    sources: Optional[Iterable[WebResearchSource]],
) -> CitationSourceLookup:
    """Build a lookup mapping normalized URLs to WebResearchSource instances.

    Only maps URLs that genuinely and unambiguously belong to a single collected source.
    If multiple distinct collected sources share a URL (e.g. multiple different
    articles redirect to the same generic login/error page), the URL is marked
    ambiguous and excluded from verification.
    """
    if not sources:
        return CitationSourceLookup()

    url_to_sources: dict[str, list[WebResearchSource]] = {}

    for s in sources:
        if not isinstance(s, WebResearchSource):
            continue

        s_urls: set[str] = set()

        # 1. Primary canonical URL
        if isinstance(s.url, str) and s.url.strip():
            norm_primary = normalize_citation_url(s.url)
            if norm_primary:
                s_urls.add(norm_primary)

        # 2. Legitimate crawler metadata URLs belonging to this specific source
        if isinstance(s.raw_data, dict):
            for k in ("initial_url", "final_url", "search_url", "original_search_url", "resolved_url", "publisher_url"):
                val = s.raw_data.get(k)
                if isinstance(val, str) and val.strip():
                    norm_k = normalize_citation_url(val)
                    if norm_k:
                        s_urls.add(norm_k)

        for u in s_urls:
            url_to_sources.setdefault(u, []).append(s)

    lookup_map: dict[str, WebResearchSource] = {}
    ambiguous_urls: set[str] = set()

    for u, matched_list in url_to_sources.items():
        if len(matched_list) == 1:
            lookup_map[u] = matched_list[0]
        else:
            first = matched_list[0]
            if all(_are_same_source(first, other) for other in matched_list[1:]):
                lookup_map[u] = first
            else:
                ambiguous_urls.add(u)
                logger.info(
                    "URL '%s' is claimed by %d distinct sources; marked ambiguous.",
                    u,
                    len(matched_list),
                )

    return CitationSourceLookup(lookup_map, ambiguous_urls=ambiguous_urls)


def correlate_finding_with_sources(
    finding: MarketResearchRecord,
    sources_or_lookup: Union[Optional[Sequence[WebResearchSource]], CitationSourceLookup, dict[str, WebResearchSource]],
) -> MarketResearchRecord:
    """Correlate a MarketResearchRecord citation with collected web sources.

    - Matches finding.source_url conservatively against the lookup.
    - If matched unambiguously:
      - raw_data["citation_verified"] = True
      - raw_data["unmatched_citation"] = False
      - raw_data["matched_source_url"] = matched_source.url
      - Adds available discovery metadata: search_query, search_engine,
        search_publisher, relevance_reason, http_status.
    - If unmatched or ambiguous:
      - raw_data["citation_verified"] = False
      - raw_data["unmatched_citation"] = True
      - If ambiguous, sets raw_data["ambiguous_citation"] = True
    """
    if not isinstance(finding, MarketResearchRecord):
        return finding

    if isinstance(sources_or_lookup, (CitationSourceLookup, dict)):
        lookup = sources_or_lookup
    else:
        lookup = build_source_url_lookup(sources_or_lookup)

    norm_citation = normalize_citation_url(finding.source_url)
    matched_source: Optional[WebResearchSource] = lookup.get(norm_citation) if norm_citation else None

    is_ambiguous = (
        lookup.is_ambiguous(norm_citation)
        if isinstance(lookup, CitationSourceLookup) and norm_citation
        else False
    )

    new_raw = dict(finding.raw_data) if isinstance(finding.raw_data, dict) else {}

    if matched_source is not None:
        new_raw["citation_verified"] = True
        new_raw["unmatched_citation"] = False
        new_raw["matched_source_url"] = matched_source.url

        if isinstance(matched_source.raw_data, dict):
            src_raw = matched_source.raw_data
            if "search_query" in src_raw and src_raw["search_query"]:
                new_raw["search_query"] = src_raw["search_query"]
            elif "query" in src_raw and src_raw["query"]:
                new_raw["search_query"] = src_raw["query"]

            if "search_engine" in src_raw and src_raw["search_engine"]:
                new_raw["search_engine"] = src_raw["search_engine"]
            elif "engine" in src_raw and src_raw["engine"]:
                new_raw["search_engine"] = src_raw["engine"]

            if "search_publisher" in src_raw and src_raw["search_publisher"]:
                new_raw["search_publisher"] = src_raw["search_publisher"]
            elif "publisher" in src_raw and src_raw["publisher"]:
                new_raw["search_publisher"] = src_raw["publisher"]
            elif matched_source.publisher_or_domain:
                new_raw["search_publisher"] = matched_source.publisher_or_domain

            if "relevance_reason" in src_raw and src_raw["relevance_reason"]:
                new_raw["relevance_reason"] = src_raw["relevance_reason"]
            elif "search_relevance_reason" in src_raw and src_raw["search_relevance_reason"]:
                new_raw["relevance_reason"] = src_raw["search_relevance_reason"]

            if "http_status" in src_raw and src_raw["http_status"] is not None:
                new_raw["http_status"] = src_raw["http_status"]

            if "pub_date" in src_raw and src_raw["pub_date"]:
                new_raw["pub_date"] = src_raw["pub_date"]
                new_raw["publication_date"] = src_raw["pub_date"]
            elif "publication_date" in src_raw and src_raw["publication_date"]:
                new_raw["pub_date"] = src_raw["publication_date"]
                new_raw["publication_date"] = src_raw["publication_date"]
        elif matched_source.publisher_or_domain:
            new_raw["search_publisher"] = matched_source.publisher_or_domain
    else:
        new_raw["citation_verified"] = False
        new_raw["unmatched_citation"] = True
        if is_ambiguous:
            new_raw["ambiguous_citation"] = True

    # Classify evidence status conservatively based on actual source content
    status, supporting_passage = classify_finding_evidence_status(
        finding=finding,
        source=matched_source if (matched_source is not None and not is_ambiguous) else None,
    )
    new_raw["evidence_status"] = status
    if supporting_passage:
        new_raw["supporting_passage"] = supporting_passage

    return replace(finding, raw_data=new_raw)


def correlate_findings_with_sources(
    findings: Sequence[MarketResearchRecord],
    sources: Optional[Sequence[WebResearchSource]],
) -> list[MarketResearchRecord]:
    """Correlate a sequence of MarketResearchRecord objects with collected sources."""
    if not findings:
        return []
    lookup = build_source_url_lookup(sources)
    return [correlate_finding_with_sources(f, lookup) for f in findings]
