"""Application service coordinating AI-driven market research and persistence."""

from dataclasses import replace
import logging
from typing import Any, Optional, Sequence, Union

from src.market_research.citation_grounding import correlate_findings_with_sources
from src.market_research.models import MarketResearchRecord
from src.market_research.output_parser import (
    MarketResearchOutputParseError,
    parse_market_research_output,
)
from src.market_research.repository import MarketResearchRepository
from src.market_research.research_prompt import (
    MARKET_RESEARCH_SYSTEM_PROMPT,
    format_market_research_user_prompt,
)
from src.market_research.source_models import WebResearchSource
from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord

logger = logging.getLogger(__name__)


class MarketResearchServiceError(Exception):
    """Base exception for market research service errors."""
    pass


class InvalidOpportunityError(MarketResearchServiceError):
    """Raised when an invalid opportunity is provided to the market research service."""
    pass


class MarketResearchAIError(MarketResearchServiceError):
    """Raised when the AI client fails to generate a market research response."""
    pass


class MarketResearchParseError(MarketResearchServiceError):
    """Raised when AI market research output cannot be safely parsed or validated."""
    pass


class MarketResearchPersistenceError(MarketResearchServiceError):
    """Raised when persisting market research findings to the repository fails."""
    pass


class MarketResearchService:
    """Application service coordinating AI competitive research, evidence analysis, and persistence."""

    def __init__(
        self,
        ai_client: Any,
        market_research_repository: Optional[MarketResearchRepository] = None,
        *,
        repository: Optional[MarketResearchRepository] = None,
        market_research_repo: Optional[MarketResearchRepository] = None,
        repo: Optional[MarketResearchRepository] = None,
    ) -> None:
        """Initialize the market research service with required dependencies.

        Args:
            ai_client: AI client implementing generate(system_prompt, user_prompt) -> str.
            market_research_repository: Repository for persisting validated MarketResearchRecords.
            repository: Keyword alias for market_research_repository.
            market_research_repo: Keyword alias for market_research_repository.
            repo: Keyword alias for market_research_repository.

        Raises:
            ValueError: If ai_client or repository is None.
        """
        r = (
            market_research_repository
            if market_research_repository is not None
            else (repository if repository is not None else (market_research_repo or repo))
        )

        if ai_client is None:
            raise ValueError("ai_client is required and must not be None.")
        if r is None:
            raise ValueError("market_research_repository is required and must not be None.")

        self.ai_client = ai_client
        self.repository = r

    def conduct_market_research(
        self,
        opportunity: OpportunityRecord,
        problems: Optional[Sequence[ProblemRecord]] = None,
        research_evidence: Optional[Union[str, Sequence[str], dict[str, Any]]] = None,
        *,
        evidence: Optional[Union[str, Sequence[str], dict[str, Any]]] = None,
        sources: Optional[Sequence[WebResearchSource]] = None,
    ) -> list[MarketResearchRecord]:
        """Conduct AI-driven market research on a startup opportunity and persist findings.

        Workflow:
            1. Validate opportunity input (rejects before any downstream calls).
            2. Validate optional problem leads.
            3. Build research user prompt using format_market_research_user_prompt.
            4. Invoke injected AI client with MARKET_RESEARCH_SYSTEM_PROMPT.
            5. Parse response into structured MarketResearchRecords.
            6. Persist findings atomically via MarketResearchRepository.save_market_research.
            7. Return persisted records with populated database IDs.

        Args:
            opportunity: OpportunityRecord to research.
            problems: Optional sequence of originating ProblemRecord leads.
            research_evidence: Optional research evidence or context.
            evidence: Keyword alias for research_evidence.

        Returns:
            list[MarketResearchRecord]: List of persisted records with database IDs.

        Raises:
            InvalidOpportunityError: If opportunity is not an OpportunityRecord.
            MarketResearchServiceError: If problems validation fails.
            MarketResearchAIError: If AI generation fails.
            MarketResearchParseError: If output parsing fails.
            MarketResearchPersistenceError: If repository persistence fails.
        """
        # 1. Reject invalid opportunity before downstream calls
        if not isinstance(opportunity, OpportunityRecord):
            raise InvalidOpportunityError(
                f"Expected OpportunityRecord instance, got {type(opportunity).__name__}."
            )

        # 2. Validate optional problems
        if problems is not None:
            if not isinstance(problems, (list, tuple)):
                raise MarketResearchServiceError(
                    f"problems must be a list or tuple of ProblemRecord objects, got {type(problems).__name__}."
                )
            for idx, p in enumerate(problems):
                if not isinstance(p, ProblemRecord):
                    raise MarketResearchServiceError(
                        f"problems[{idx}] must be a ProblemRecord instance, got {type(p).__name__}."
                    )

        # 3. Build user prompt
        ev = research_evidence if research_evidence is not None else evidence
        try:
            user_prompt = format_market_research_user_prompt(
                opportunity=opportunity,
                problems=problems,
                evidence=ev,
            )
        except Exception as exc:
            raise MarketResearchServiceError(
                f"Failed to format market research user prompt: {exc}"
            ) from exc

        system_prompt = MARKET_RESEARCH_SYSTEM_PROMPT

        # 4. Invoke AI client
        try:
            raw_response = self.ai_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise MarketResearchAIError(
                f"AI market research generation failed for opportunity '{opportunity.id}': {exc}"
            ) from exc

        # 5. Parse response into structured MarketResearchRecords
        try:
            parsed_findings = parse_market_research_output(
                raw_output=raw_response,
                expected_opportunity_id=opportunity.id,
            )
        except (MarketResearchOutputParseError, Exception) as exc:
            raise MarketResearchParseError(
                f"Failed to parse market research output for opportunity '{opportunity.id}': {exc}"
            ) from exc

        # 5b. Correlate citations with sources when provided
        if sources is not None:
            parsed_findings = correlate_findings_with_sources(parsed_findings, sources)

        # 6. Persist findings using MarketResearchRepository
        persisted_records: list[MarketResearchRecord] = []
        for finding in parsed_findings:
            try:
                saved_id = self.repository.save_market_research(finding)
                persisted_records.append(replace(finding, id=saved_id))
            except Exception as exc:
                raise MarketResearchPersistenceError(
                    f"Failed to persist market research finding for opportunity '{opportunity.id}': {exc}"
                ) from exc

        return persisted_records

    # Aliases for caller ergonomics
    research_opportunity = conduct_market_research
    conduct_research = conduct_market_research
