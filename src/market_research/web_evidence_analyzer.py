"""Integration layer connecting collected WebResearchSources to market-research AI analysis.

Bridges external web evidence (WebResearchSource) to the existing MarketResearchService,
preserving source metadata (URL, title, source_type, domain, retrieved_content)
and returning structured MarketResearchRecords.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from typing import Any, Final, Optional

from src.market_research.citation_grounding import correlate_findings_with_sources
from src.market_research.models import MarketResearchRecord
from src.market_research.repository import MarketResearchRepository
from src.market_research.search_client import callable_accepts_kwarg
from src.market_research.service import (
    MarketResearchAIError,
    MarketResearchParseError,
    MarketResearchPersistenceError,
    MarketResearchService,
    MarketResearchServiceError,
)
from src.market_research.source_models import WebResearchSource
from src.opportunities.models import OpportunityRecord
from src.opportunities.repository import OpportunityRepository
from src.problems.models import ProblemRecord

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONTENT_LENGTH: Final[int] = 100

BOT_CHALLENGE_PHRASES: Final[tuple[str, ...]] = (
    "please verify you are human",
    "verify you are human to continue",
    "verify that you are human to continue",
    "confirm you are human to continue",
    "prove you are human to continue",
    "press & hold to prove you are human",
    "unusual traffic detected from your",
    "our systems have detected unusual traffic",
    "our automated systems detected unusual traffic",
    "checking if the site connection is secure",
    "checking your browser before accessing",
    "please complete the security check",
    "security check to access",
    "enable javascript and cookies to continue",
    "turn on javascript and cookies to continue",
    "please turn cookie on and reload the page",
    "pardon our interruption as you've been browsing",
    "pardon our interruption... as you've been browsing",
    "attention required! | cloudflare",
    "please solve the captcha",
    "please solve this captcha",
)

ACCESS_DENIED_ERROR_PHRASES: Final[tuple[str, ...]] = (
    "403 forbidden",
    "404 not found",
    "page not found",
    "error 404",
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "503 service temporarily unavailable",
    "access denied",
    "you do not have permission to access",
    "you don't have permission to access",
    "requested url was not found on this server",
    "the page you are looking for cannot be found",
    "the page you are looking for doesn't exist",
    "this page does not exist",
    "something went wrong on our end",
)

COOKIE_NOTICE_PHRASES: Final[tuple[str, ...]] = (
    "accept all cookies",
    "accept cookies",
    "cookie preferences",
    "manage cookie preferences",
    "manage cookies",
    "we use cookies to",
    "strictly necessary cookies",
    "by clicking accept",
    "by clicking “accept",
    "by clicking \"accept",
    "reject non-essential",
    "cookie policy",
)


@dataclass(frozen=True)
class SourceQualityDecision:
    """Deterministic assessment result of web research content quality.

    Attributes:
        is_accepted: True if content meets evidence quality criteria; False if rejected.
        reason: Concise descriptive reason explaining the decision.
    """

    is_accepted: bool
    reason: str


def evaluate_source_quality(
    source: WebResearchSource,
    min_content_length: int = DEFAULT_MIN_CONTENT_LENGTH,
) -> SourceQualityDecision:
    """Evaluate whether a WebResearchSource contains acceptable evidence for AI analysis.

    A conservative low-quality content filter that detects:
    1. HTTP error responses (status >= 400 when status code is available).
    2. Empty or whitespace-only content.
    3. Content shorter than min_content_length (default 100 characters).
    4. Obvious bot-protection challenges (e.g. 'verify you are human', 'unusual traffic detected').
    5. Access-denied messages and generic error templates (e.g. '403 Forbidden', 'Page Not Found').
    6. Cookie-consent only notices lacking substantive article content.

    Avoids false positives by ensuring legitimate articles discussing cookies,
    CAPTCHAs, or access restrictions with substantive text are preserved.
    """
    if not isinstance(source, WebResearchSource):
        return SourceQualityDecision(
            is_accepted=False,
            reason=f"Expected WebResearchSource instance, got {type(source).__name__}.",
        )

    # 1. HTTP error response check (when status is available)
    raw_data = source.raw_data if isinstance(source.raw_data, dict) else {}
    http_status = raw_data.get("http_status")
    if http_status is None:
        http_status = raw_data.get("status_code")
    if isinstance(http_status, int) and http_status >= 400:
        return SourceQualityDecision(
            is_accepted=False,
            reason=f"HTTP error response with status code {http_status}.",
        )

    # 2. Empty or whitespace-only content check
    content = source.retrieved_content or ""
    clean_content = content.strip()
    if not clean_content:
        return SourceQualityDecision(
            is_accepted=False,
            reason="Extracted content is empty or whitespace-only.",
        )

    # 3. Minimum length threshold check
    if len(clean_content) < min_content_length:
        return SourceQualityDecision(
            is_accepted=False,
            reason=(
                f"Extracted content length ({len(clean_content)} characters) "
                f"is below minimum threshold ({min_content_length} characters)."
            ),
        )

    lower_content = clean_content.lower()
    lower_title = (source.title or "").strip().lower()

    # 4. Bot-protection challenges
    has_challenge_title = any(
        t in lower_title
        for t in (
            "attention required",
            "security check",
            "just a moment",
            "bot verification",
            "verify you are human",
            "robot or human",
            "captcha",
        )
    )
    matched_bot_phrases = [p for p in BOT_CHALLENGE_PHRASES if p in lower_content]
    if (
        (has_challenge_title and matched_bot_phrases)
        or (len(clean_content) < 600 and matched_bot_phrases)
        or (len(matched_bot_phrases) >= 2 and len(clean_content) < 1200)
    ):
        return SourceQualityDecision(
            is_accepted=False,
            reason="Page appears to be a bot-protection or verification challenge.",
        )

    # 5. Access-denied and generic error templates
    has_error_title = any(
        e in lower_title
        for e in (
            "403 forbidden",
            "404 not found",
            "page not found",
            "access denied",
            "500 internal",
            "502 bad gateway",
            "503 service",
            "error 404",
        )
    )
    matched_error_phrases = [e for e in ACCESS_DENIED_ERROR_PHRASES if e in lower_content]
    if (
        (has_error_title and (matched_error_phrases or len(clean_content) < 800))
        or (len(clean_content) < 600 and matched_error_phrases)
    ):
        return SourceQualityDecision(
            is_accepted=False,
            reason="Page is an access-denied or error template.",
        )

    # 6. Cookie-consent only notices
    matched_cookie_phrases = [c for c in COOKIE_NOTICE_PHRASES if c in lower_content]
    starts_with_cookie = any(
        lower_content.startswith(p)
        for p in (
            "we use cookies",
            "this website uses cookies",
            "this site uses cookies",
            "accept all cookies",
            "by clicking accept",
        )
    )
    if len(clean_content) < 600 and (starts_with_cookie or len(matched_cookie_phrases) >= 2):
        return SourceQualityDecision(
            is_accepted=False,
            reason="Page consists primarily of a cookie-consent notice.",
        )

    return SourceQualityDecision(
        is_accepted=True,
        reason="Content meets quality standards.",
    )


class WebEvidenceAnalyzerError(MarketResearchServiceError):
    """Base exception for web evidence analyzer operations."""
    pass


class InvalidOpportunityIdError(WebEvidenceAnalyzerError, ValueError):
    """Raised when an opportunity_id is empty, whitespace, or invalid type."""
    pass


def extract_publication_date(source: WebResearchSource) -> str:
    """Extract and format publication date string from a WebResearchSource.

    Checks source.raw_data for 'pub_date', 'publication_date', 'published_date', or 'published_at'.
    If missing or empty, returns 'Unknown'.
    If present, preserves the original date value (including malformed dates for debugging).
    """
    if not isinstance(source.raw_data, dict):
        return "Unknown"

    raw_val = (
        source.raw_data.get("pub_date")
        or source.raw_data.get("publication_date")
        or source.raw_data.get("published_date")
        or source.raw_data.get("published_at")
    )

    if raw_val is None:
        return "Unknown"

    if isinstance(raw_val, str):
        clean = raw_val.strip()
        return clean if clean else "Unknown"

    str_val = str(raw_val).strip()
    return str_val if str_val else "Unknown"


def format_web_source_evidence(
    source: WebResearchSource,
    max_content_chars: int = 2500,
) -> str:
    """Format a WebResearchSource into structured evidence text preserving metadata.

    Preserves URL, title, source_type, publisher_or_domain, publication_date, retrieved_at, and retrieved_content.
    Caps extracted content length to prevent operating system process buffer overflows.
    """
    content = source.retrieved_content.strip()
    if max_content_chars > 0 and len(content) > max_content_chars:
        content = content[:max_content_chars] + "... [truncated]"

    pub_date_display = extract_publication_date(source)

    return (
        f"Title: {source.title}\n"
        f"URL: {source.url}\n"
        f"Domain / Publisher: {source.publisher_or_domain}\n"
        f"Source Type: {source.source_type}\n"
        f"Publication Date: {pub_date_display}\n"
        f"Retrieved At: {source.retrieved_at}\n"
        f"Retrieved Content:\n{content}"
    )


def format_web_sources_evidence(
    sources: Sequence[WebResearchSource],
    max_content_chars: int = 2500,
    max_total_chars: int = 10000,
) -> list[str]:
    """Format a sequence of WebResearchSource objects preserving metadata for market research."""
    if not sources:
        return []
    per_source_limit = min(max_content_chars, max(300, max_total_chars // len(sources)))
    return [format_web_source_evidence(s, max_content_chars=per_source_limit) for s in sources]



class WebEvidenceAnalyzer:
    """Connects collected WebResearchSource objects to the existing MarketResearchService."""

    def __init__(
        self,
        market_research_service: Optional[MarketResearchService] = None,
        opportunity_repository: Optional[OpportunityRepository] = None,
        *,
        service: Optional[MarketResearchService] = None,
        ai_client: Optional[Any] = None,
        market_research_repository: Optional[MarketResearchRepository] = None,
        opportunity_repo: Optional[OpportunityRepository] = None,
    ) -> None:
        """Initialize WebEvidenceAnalyzer with required service or dependencies.

        Args:
            market_research_service: Injected MarketResearchService instance.
            opportunity_repository: Optional repository to look up OpportunityRecords.
            service: Alias for market_research_service.
            ai_client: AI client to construct MarketResearchService if service not provided.
            market_research_repository: Repository to construct MarketResearchService.
            opportunity_repo: Alias for opportunity_repository.

        Raises:
            ValueError: If neither a service nor (ai_client + market_research_repository) is provided.
        """
        active_service = market_research_service if market_research_service is not None else service
        if active_service is None:
            if ai_client is not None and market_research_repository is not None:
                active_service = MarketResearchService(
                    ai_client=ai_client,
                    market_research_repository=market_research_repository,
                )
            else:
                raise ValueError(
                    "Either market_research_service or both (ai_client and market_research_repository) must be provided."
                )

        self.service = active_service
        self.opportunity_repository = opportunity_repository or opportunity_repo

    def analyze(
        self,
        opportunity_id: str,
        sources: Sequence[WebResearchSource],
        *,
        opportunity: Optional[OpportunityRecord] = None,
        problems: Optional[Sequence[ProblemRecord]] = None,
    ) -> list[MarketResearchRecord]:
        """Analyze collected web research sources for an opportunity using MarketResearchService.

        Args:
            opportunity_id: Identifier of the opportunity being researched.
            sources: Sequence of collected WebResearchSource objects.
            opportunity: Optional explicit OpportunityRecord instance.
            problems: Optional sequence of originating ProblemRecord leads.

        Returns:
            list[MarketResearchRecord]: Structured market research findings.

        Raises:
            InvalidOpportunityIdError: If opportunity_id is invalid.
            WebEvidenceAnalyzerError: If inputs are invalid or analysis fails.
            MarketResearchServiceError: If downstream service fails.
        """
        # 1. Validate opportunity_id
        if not isinstance(opportunity_id, str) or isinstance(opportunity_id, bool) or not opportunity_id.strip():
            raise InvalidOpportunityIdError("opportunity_id must be a non-empty string.")
        clean_opp_id = opportunity_id.strip()

        # 2. Validate sources sequence
        if sources is None:
            raise WebEvidenceAnalyzerError("sources must not be None.")
        if not isinstance(sources, (list, tuple, Sequence)):
            raise WebEvidenceAnalyzerError(
                f"sources must be a sequence of WebResearchSource objects, got {type(sources).__name__}."
            )
        for idx, src in enumerate(sources):
            if not isinstance(src, WebResearchSource):
                raise WebEvidenceAnalyzerError(
                    f"sources[{idx}] must be a WebResearchSource instance, got {type(src).__name__}."
                )

        # 3. Filter low-quality sources before formatting evidence
        if not sources:
            logger.info("Empty sources sequence provided for opportunity '%s'; returning empty findings.", clean_opp_id)
            return []

        accepted_sources: list[WebResearchSource] = []
        for src in sources:
            decision = evaluate_source_quality(src)
            if decision.is_accepted:
                accepted_sources.append(src)
            else:
                logger.info(
                    "Excluding low-quality source '%s' from evidence: %s",
                    src.url,
                    decision.reason,
                )

        if not accepted_sources:
            logger.info(
                "No usable web sources available after quality filtering for opportunity '%s'; returning empty findings.",
                clean_opp_id,
            )
            return []

        # 4. Resolve OpportunityRecord
        if opportunity is not None:
            if not isinstance(opportunity, OpportunityRecord):
                raise WebEvidenceAnalyzerError(
                    f"Expected OpportunityRecord instance, got {type(opportunity).__name__}."
                )
            if opportunity.id and opportunity.id.strip() != clean_opp_id:
                raise WebEvidenceAnalyzerError(
                    f"Opportunity ID mismatch: provided opportunity has id='{opportunity.id}', expected '{clean_opp_id}'."
                )
            target_opp = opportunity
        elif self.opportunity_repository is not None:
            try:
                looked_up = self.opportunity_repository.get_opportunity_by_id(clean_opp_id)
            except Exception as exc:
                raise WebEvidenceAnalyzerError(
                    f"Failed to retrieve opportunity '{clean_opp_id}' from repository: {exc}"
                ) from exc
            if looked_up is None:
                raise WebEvidenceAnalyzerError(
                    f"Opportunity '{clean_opp_id}' not found in opportunity repository."
                )
            target_opp = looked_up
        else:
            # Standalone / lightweight execution: synthesize valid minimal OpportunityRecord
            target_opp = OpportunityRecord(
                opportunity_title=f"Opportunity {clean_opp_id}",
                solution_concept="Venture opportunity evaluated against collected web evidence.",
                target_customer="Target commercial market segment",
                value_proposition="Venture value proposition evaluated against market evidence.",
                source_problem_ids=(f"problem-{clean_opp_id}",),
                id=clean_opp_id,
            )

        # 5. Format evidence preserving all source metadata
        formatted_evidence = format_web_sources_evidence(accepted_sources)

        # 6. Call existing MarketResearchService
        try:
            if callable_accepts_kwarg(self.service.conduct_market_research, "sources"):
                findings = self.service.conduct_market_research(
                    opportunity=target_opp,
                    problems=problems,
                    research_evidence=formatted_evidence,
                    sources=accepted_sources,
                )
            else:
                findings = self.service.conduct_market_research(
                    opportunity=target_opp,
                    problems=problems,
                    research_evidence=formatted_evidence,
                )
        except MarketResearchServiceError:
            raise
        except Exception as exc:
            raise WebEvidenceAnalyzerError(
                f"Market research analysis failed for opportunity '{clean_opp_id}': {exc}"
            ) from exc

        # 7. Ground and correlate citation URLs against collected sources
        return correlate_findings_with_sources(findings, accepted_sources)

    # Aliases for caller ergonomics
    analyze_sources = analyze
    analyze_evidence = analyze
    analyze_web_evidence = analyze


def analyze_web_sources(
    opportunity_id: str,
    sources: Sequence[WebResearchSource],
    service: MarketResearchService,
    *,
    opportunity: Optional[OpportunityRecord] = None,
    problems: Optional[Sequence[ProblemRecord]] = None,
) -> list[MarketResearchRecord]:
    """Convenience functional helper to analyze web sources for an opportunity.

    Args:
        opportunity_id: Non-empty opportunity identifier string.
        sources: Sequence of WebResearchSource objects.
        service: Injected MarketResearchService instance.
        opportunity: Optional explicit OpportunityRecord.
        problems: Optional sequence of originating ProblemRecord leads.

    Returns:
        list[MarketResearchRecord]: Structured market research findings.
    """
    analyzer = WebEvidenceAnalyzer(market_research_service=service)
    return analyzer.analyze(
        opportunity_id=opportunity_id,
        sources=sources,
        opportunity=opportunity,
        problems=problems,
    )
