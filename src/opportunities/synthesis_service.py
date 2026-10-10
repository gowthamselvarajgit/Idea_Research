"""Application service coordinating startup opportunity synthesis from problem leads."""

from dataclasses import replace
import logging
from typing import Any, Optional

from src.opportunities.models import OpportunityRecord
from src.opportunities.opportunity_prompt import (
    OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT,
    format_opportunity_synthesis_user_prompt,
)
from src.opportunities.output_parser import parse_opportunity_synthesis_output
from src.opportunities.repository import OpportunityRepository
from src.problems.repository import ProblemRepository

logger = logging.getLogger(__name__)


class OpportunitySynthesisServiceError(Exception):
    """Base exception for opportunity synthesis service errors."""
    pass


class NoProblemsInRunError(OpportunitySynthesisServiceError):
    """Raised when the specified research run has no extracted problems to synthesize from."""
    pass


class OpportunitySynthesisAIError(OpportunitySynthesisServiceError):
    """Raised when the AI client fails to generate an opportunity response."""
    pass


class OpportunitySynthesisParseError(OpportunitySynthesisServiceError):
    """Raised when the AI response text cannot be parsed or validated."""
    pass


class OpportunitySynthesisPersistenceError(OpportunitySynthesisServiceError):
    """Raised when persisting the synthesized opportunity fails."""
    pass


class OpportunitySynthesisService:
    """Application service coordinating startup opportunity synthesis from verified problem leads."""

    def __init__(
        self,
        ai_client: Any,
        problem_repository: Optional[ProblemRepository] = None,
        opportunity_repository: Optional[OpportunityRepository] = None,
        *,
        problem_repo: Optional[ProblemRepository] = None,
        opportunity_repo: Optional[OpportunityRepository] = None,
    ) -> None:
        """Initialize the opportunity synthesis service with required dependencies.

        Args:
            ai_client: AI client implementing generate(system_prompt, user_prompt) -> str.
            problem_repository: ProblemRepository for querying extracted problems for a run.
            opportunity_repository: OpportunityRepository for persisting synthesized opportunities.
            problem_repo: Optional keyword alias for problem_repository.
            opportunity_repo: Optional keyword alias for opportunity_repository.

        Raises:
            ValueError: If any required dependency is None.
        """
        p_repo = problem_repository if problem_repository is not None else problem_repo
        o_repo = opportunity_repository if opportunity_repository is not None else opportunity_repo

        if ai_client is None:
            raise ValueError("ai_client is required and must not be None.")
        if p_repo is None:
            raise ValueError("problem_repository is required and must not be None.")
        if o_repo is None:
            raise ValueError("opportunity_repository is required and must not be None.")

        self.ai_client = ai_client
        self.problem_repository = p_repo
        self.opportunity_repository = o_repo

    def synthesize_opportunity_for_run(self, run_id: str) -> OpportunityRecord:
        """Synthesize and persist a startup opportunity from verified problems in a research run.

        Flow:
            1. Validate run_id input.
            2. Retrieve all ProblemRecord instances belonging to the research run.
            3. Verify the run contains at least one problem lead (raises NoProblemsInRunError if empty).
            4. Build user prompt using format_opportunity_synthesis_user_prompt.
            5. Invoke the injected AI client using OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT.
            6. Parse the raw response using parse_opportunity_synthesis_output.
            7. Persist the OpportunityRecord via OpportunityRepository.save_opportunity.
            8. Return the persisted OpportunityRecord populated with its persistent ID.

        Args:
            run_id: Identifier of the research run.

        Returns:
            OpportunityRecord: Persisted opportunity record with populated ID.

        Raises:
            OpportunitySynthesisServiceError: For validation or unexpected errors.
            NoProblemsInRunError: When no problems are found for the research run.
            OpportunitySynthesisAIError: When the AI client invocation fails.
            OpportunitySynthesisParseError: When response parsing/validation fails.
            OpportunitySynthesisPersistenceError: When repository storage fails.
        """
        if not isinstance(run_id, str) or not run_id.strip():
            raise OpportunitySynthesisServiceError("run_id must be a non-empty string.")

        clean_run_id = run_id.strip()

        # 1. Retrieve all ProblemRecords belonging to that research run
        try:
            problems = self.problem_repository.get_problems_for_run(clean_run_id)
        except Exception as exc:
            raise OpportunitySynthesisServiceError(
                f"Failed to retrieve problems for run '{clean_run_id}': {exc}"
            ) from exc

        # 2. Validate that the run exists and has problems
        if not problems:
            raise NoProblemsInRunError(
                f"No problem records found for research run '{clean_run_id}'. Cannot synthesize opportunity."
            )

        # 3. Build user prompt using format_opportunity_synthesis_user_prompt
        try:
            user_prompt = format_opportunity_synthesis_user_prompt(problems)
        except Exception as exc:
            raise OpportunitySynthesisServiceError(
                f"Failed to format opportunity synthesis user prompt for run '{clean_run_id}': {exc}"
            ) from exc

        system_prompt = OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT

        # 4. Call the existing AI client
        try:
            raw_response = self.ai_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise OpportunitySynthesisAIError(
                f"AI opportunity synthesis failed for run '{clean_run_id}': {exc}"
            ) from exc

        # 5. Parse the response using parse_opportunity_synthesis_output
        try:
            opportunity_record = parse_opportunity_synthesis_output(raw_response)
        except Exception as exc:
            raise OpportunitySynthesisParseError(
                f"Failed to parse opportunity synthesis output for run '{clean_run_id}': {exc}"
            ) from exc

        # 6. Persist the resulting OpportunityRecord using OpportunityRepository.save_opportunity
        try:
            saved_id = self.opportunity_repository.save_opportunity(
                opportunity=opportunity_record,
                run_id=clean_run_id,
            )
        except Exception as exc:
            raise OpportunitySynthesisPersistenceError(
                f"Failed to persist synthesized opportunity for run '{clean_run_id}': {exc}"
            ) from exc

        # 7. Return the validated OpportunityRecord populated with the persisted UUID
        if saved_id:
            return replace(opportunity_record, id=saved_id)
        return opportunity_record

    def synthesize_multiple_opportunities_for_run(
        self,
        run_id: str,
        max_opportunities: int = 3,
    ) -> list[OpportunityRecord]:
        """Synthesize distinct startup opportunities for the problem leads in a research run.

        Args:
            run_id: Identifier of the research run.
            max_opportunities: Maximum number of distinct opportunities to synthesize.

        Returns:
            list[OpportunityRecord]: List of validated, persisted OpportunityRecord instances.
        """
        if not isinstance(run_id, str) or not run_id.strip():
            raise OpportunitySynthesisServiceError("run_id must be a non-empty string.")

        clean_run_id = run_id.strip()
        problems = self.problem_repository.get_problems_for_run(clean_run_id)
        if not problems:
            raise NoProblemsInRunError(
                f"No problem records found for research run '{clean_run_id}'. Cannot synthesize opportunity."
            )

        if len(problems) == 1:
            return [self.synthesize_opportunity_for_run(clean_run_id)]

        opportunities: list[OpportunityRecord] = []
        for prob in problems[:max_opportunities]:
            try:
                user_prompt = format_opportunity_synthesis_user_prompt(prob)
                raw_response = self.ai_client.generate(
                    system_prompt=OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
                opp_record = parse_opportunity_synthesis_output(raw_response)
                saved_id = self.opportunity_repository.save_opportunity(
                    opportunity=opp_record,
                    run_id=clean_run_id,
                )
                if saved_id:
                    opp_record = replace(opp_record, id=saved_id)
                opportunities.append(opp_record)
            except Exception as exc:
                logger.warning(
                    "Failed synthesizing opportunity for problem %s in run %s: %s",
                    prob.id,
                    clean_run_id,
                    exc,
                )

        if not opportunities:
            return [self.synthesize_opportunity_for_run(clean_run_id)]

        return opportunities

    # Aliases for interface compatibility
    synthesize_for_run = synthesize_opportunity_for_run
    synthesize_opportunity = synthesize_opportunity_for_run
    synthesize_opportunities_for_run = synthesize_opportunity_for_run
