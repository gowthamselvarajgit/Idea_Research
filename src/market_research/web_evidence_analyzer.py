"""Integration layer connecting collected WebResearchSources to market-research AI analysis.

Bridges external web evidence (WebResearchSource) to the existing MarketResearchService,
preserving source metadata (URL, title, source_type, domain, retrieved_content)
and returning structured MarketResearchRecords.
"""

from collections.abc import Sequence
import logging
from typing import Any, Optional

from src.market_research.models import MarketResearchRecord
from src.market_research.repository import MarketResearchRepository
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


class WebEvidenceAnalyzerError(MarketResearchServiceError):
    """Base exception for web evidence analyzer operations."""
    pass


class InvalidOpportunityIdError(WebEvidenceAnalyzerError, ValueError):
    """Raised when an opportunity_id is empty, whitespace, or invalid type."""
    pass


def format_web_source_evidence(
    source: WebResearchSource,
    max_content_chars: int = 2500,
) -> str:
    """Format a WebResearchSource into structured evidence text preserving metadata.

    Preserves URL, title, source_type, publisher_or_domain, retrieved_at, and retrieved_content.
    Caps extracted content length to prevent operating system process buffer overflows.
    """
    content = source.retrieved_content.strip()
    if max_content_chars > 0 and len(content) > max_content_chars:
        content = content[:max_content_chars] + "... [truncated]"

    return (
        f"Title: {source.title}\n"
        f"URL: {source.url}\n"
        f"Domain / Publisher: {source.publisher_or_domain}\n"
        f"Source Type: {source.source_type}\n"
        f"Retrieved At: {source.retrieved_at}\n"
        f"Retrieved Content:\n{content}"
    )


def format_web_sources_evidence(
    sources: Sequence[WebResearchSource],
    max_content_chars: int = 2500,
) -> list[str]:
    """Format a sequence of WebResearchSource objects preserving metadata for market research."""
    if not sources:
        return []
    per_source_limit = min(max_content_chars, max(400, 20000 // len(sources)))
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

        # 3. Cleanly handle empty sources
        if not sources:
            logger.info("Empty sources sequence provided for opportunity '%s'; returning empty findings.", clean_opp_id)
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
        formatted_evidence = format_web_sources_evidence(sources)

        # 6. Call existing MarketResearchService
        try:
            return self.service.conduct_market_research(
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
