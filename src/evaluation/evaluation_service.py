"""Application service coordinating startup opportunity evaluation via AI and persistent storage."""

from dataclasses import replace
import logging
from typing import Any, Optional

from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.opportunity_evaluation_prompt import (
    OPPORTUNITY_EVALUATION_SYSTEM_PROMPT,
    format_opportunity_evaluation_user_prompt,
)
from src.evaluation.output_parser import (
    OpportunityEvaluationOutputParseError,
    parse_opportunity_evaluation_output,
)
from src.evaluation.repository import OpportunityEvaluationRepository
from src.opportunities.models import OpportunityRecord
from src.opportunities.repository import OpportunityRepository
from src.problems.models import ProblemRecord
from src.problems.repository import ProblemRepository

logger = logging.getLogger(__name__)


class OpportunityEvaluationServiceError(Exception):
    """Base exception for opportunity evaluation service errors."""
    pass


class OpportunityNotFoundError(OpportunityEvaluationServiceError):
    """Raised when the requested opportunity is not found in the repository."""
    pass


class OpportunityEvaluationAIError(OpportunityEvaluationServiceError):
    """Raised when the AI client fails to generate an evaluation."""
    pass


class OpportunityEvaluationParseError(OpportunityEvaluationServiceError):
    """Raised when the AI response text cannot be safely parsed or validated."""
    pass


class OpportunityIdMismatchError(OpportunityEvaluationServiceError):
    """Raised when the opportunity ID in the AI evaluation output does not match the requested opportunity."""
    pass


class OpportunityEvaluationPersistenceError(OpportunityEvaluationServiceError):
    """Raised when persisting the opportunity evaluation fails."""
    pass


class OpportunityEvaluationService:
    """Application service coordinating the AI-driven evaluation, scoring, and persistence of startup opportunities."""

    def __init__(
        self,
        ai_client: Any,
        opportunity_repository: Optional[OpportunityRepository] = None,
        problem_repository: Optional[ProblemRepository] = None,
        evaluation_repository: Optional[OpportunityEvaluationRepository] = None,
        *,
        opportunity_repo: Optional[OpportunityRepository] = None,
        problem_repo: Optional[ProblemRepository] = None,
        evaluation_repo: Optional[OpportunityEvaluationRepository] = None,
    ) -> None:
        """Initialize the opportunity evaluation service with required dependencies.

        Args:
            ai_client: AI client implementing generate(system_prompt, user_prompt) -> str.
            opportunity_repository: Repository for retrieving synthesized opportunities.
            problem_repository: Optional repository for retrieving originating problem context.
            evaluation_repository: Repository for persisting evaluated opportunity records.
            opportunity_repo: Keyword alias for opportunity_repository.
            problem_repo: Keyword alias for problem_repository.
            evaluation_repo: Keyword alias for evaluation_repository.

        Raises:
            ValueError: If ai_client, opportunity_repository, or evaluation_repository is None.
        """
        o_repo = opportunity_repository if opportunity_repository is not None else opportunity_repo
        p_repo = problem_repository if problem_repository is not None else problem_repo
        e_repo = evaluation_repository if evaluation_repository is not None else evaluation_repo

        if ai_client is None:
            raise ValueError("ai_client is required and must not be None.")
        if o_repo is None:
            raise ValueError("opportunity_repository is required and must not be None.")
        if e_repo is None:
            raise ValueError("evaluation_repository is required and must not be None.")

        self.ai_client = ai_client
        self.opportunity_repository = o_repo
        self.problem_repository = p_repo
        self.evaluation_repository = e_repo

    def evaluate_opportunity(self, opportunity_id: str) -> OpportunityEvaluationRecord:
        """Evaluate a startup opportunity using AI reasoning across 11 venture dimensions and persist the result.

        Workflow:
            1. Validate opportunity_id input.
            2. Retrieve OpportunityRecord from OpportunityRepository (raises OpportunityNotFoundError if missing).
            3. Retrieve originating ProblemRecord instances from ProblemRepository if available.
            4. Format evaluation user prompt using format_opportunity_evaluation_user_prompt.
            5. Invoke the AI client using OPPORTUNITY_EVALUATION_SYSTEM_PROMPT.
            6. Parse and validate the response using parse_opportunity_evaluation_output.
            7. Verify the returned opportunity_id matches the evaluated opportunity.
            8. Persist the OpportunityEvaluationRecord via OpportunityEvaluationRepository.save_evaluation.
            9. Return the persisted OpportunityEvaluationRecord populated with its database ID.

        Args:
            opportunity_id: Identifier of the opportunity to evaluate.

        Returns:
            OpportunityEvaluationRecord: Persisted evaluation record with database ID.

        Raises:
            OpportunityEvaluationServiceError: If input is invalid.
            OpportunityNotFoundError: If opportunity_id does not exist.
            OpportunityEvaluationAIError: If AI generation fails.
            OpportunityEvaluationParseError: If output parsing fails.
            OpportunityIdMismatchError: If returned opportunity_id does not match requested.
            OpportunityEvaluationPersistenceError: If repository persistence fails.
        """
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            raise OpportunityEvaluationServiceError("opportunity_id must be a non-empty string.")

        clean_opp_id = opportunity_id.strip()

        # 1. Retrieve the opportunity from OpportunityRepository
        try:
            opportunity = self.opportunity_repository.get_opportunity_by_id(clean_opp_id)
        except Exception as exc:
            raise OpportunityEvaluationServiceError(
                f"Failed to query opportunity '{clean_opp_id}': {exc}"
            ) from exc

        if opportunity is None:
            raise OpportunityNotFoundError(
                f"Opportunity '{clean_opp_id}' was not found in the repository."
            )

        # 2. Retrieve source problems when available
        source_problems: list[ProblemRecord] = []
        if self.problem_repository and opportunity.source_problem_ids:
            for prob_id in opportunity.source_problem_ids:
                try:
                    prob = self.problem_repository.get_problem_by_id(prob_id)
                    if prob:
                        source_problems.append(prob)
                except Exception as exc:
                    logger.warning(
                        "Failed to query source problem '%s' for opportunity '%s': %s",
                        prob_id,
                        clean_opp_id,
                        exc,
                    )

        # 3. Build the evaluation user prompt
        try:
            user_prompt = format_opportunity_evaluation_user_prompt(
                opportunity=opportunity,
                problems=source_problems if source_problems else None,
            )
        except Exception as exc:
            raise OpportunityEvaluationServiceError(
                f"Failed to format evaluation user prompt for opportunity '{clean_opp_id}': {exc}"
            ) from exc

        system_prompt = OPPORTUNITY_EVALUATION_SYSTEM_PROMPT

        # 4. Call the existing AI client
        try:
            raw_response = self.ai_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise OpportunityEvaluationAIError(
                f"AI opportunity evaluation failed for opportunity '{clean_opp_id}': {exc}"
            ) from exc

        # 5. Parse the AI response and verify opportunity_id
        try:
            evaluation_record = parse_opportunity_evaluation_output(
                raw_output=raw_response,
                expected_opportunity_id=clean_opp_id,
            )
        except OpportunityEvaluationOutputParseError as exc:
            if "mismatch" in str(exc).lower():
                raise OpportunityIdMismatchError(
                    f"Opportunity ID mismatch for opportunity '{clean_opp_id}': {exc}"
                ) from exc
            raise OpportunityEvaluationParseError(
                f"Failed to parse evaluation output for opportunity '{clean_opp_id}': {exc}"
            ) from exc
        except Exception as exc:
            raise OpportunityEvaluationParseError(
                f"Unexpected error parsing evaluation output for opportunity '{clean_opp_id}': {exc}"
            ) from exc

        # 6. Safety check: ensure opportunity_id matches
        if evaluation_record.opportunity_id.strip() != clean_opp_id:
            raise OpportunityIdMismatchError(
                f"Returned opportunity_id '{evaluation_record.opportunity_id}' does not match requested '{clean_opp_id}'."
            )

        # 7. Persist the evaluation record using evaluation_repository
        try:
            saved_id = self.evaluation_repository.save_evaluation(evaluation_record)
        except Exception as exc:
            raise OpportunityEvaluationPersistenceError(
                f"Failed to persist evaluation for opportunity '{clean_opp_id}': {exc}"
            ) from exc

        # 8. Return the persisted record with its database ID
        if saved_id:
            return replace(evaluation_record, id=saved_id)
        return evaluation_record

    # Aliases for interface compatibility
    evaluate = evaluate_opportunity
    evaluate_opportunity_by_id = evaluate_opportunity
