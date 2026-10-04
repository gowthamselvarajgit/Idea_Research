"""Application service for extracting and persisting problems from patents."""

import logging
from typing import Any, Optional

from src.patents.models import PatentRecord, clean_patent_string
from src.patents.run_reader import ResearchRunPatentReader
from src.problems.extraction_prompt import (
    PROBLEM_EXTRACTION_SYSTEM_PROMPT,
    format_patent_extraction_user_prompt,
)
from src.problems.models import ProblemRecord
from src.problems.output_parser import parse_problem_extraction_output
from src.problems.patent_input import build_patent_extraction_input
from src.problems.repository import ProblemRepository

logger = logging.getLogger(__name__)


class ProblemExtractionServiceError(Exception):
    """Base exception for problem extraction service errors."""
    pass


class PatentNotInRunError(ProblemExtractionServiceError):
    """Raised when the requested patent is not associated with the research run."""
    pass


class ProblemExtractionAIError(ProblemExtractionServiceError):
    """Raised when the AI client fails to generate an extraction."""
    pass


class ProblemExtractionPersistenceError(ProblemExtractionServiceError):
    """Raised when persisting the extracted problem fails."""
    pass


class ProblemExtractionService:
    """Application service coordinating patent extraction via an AI client and repository."""

    def __init__(
        self,
        ai_client: Any,
        repository: Optional[ProblemRepository] = None,
        patent_reader: Optional[ResearchRunPatentReader] = None,
        *,
        problem_repository: Optional[ProblemRepository] = None,
    ) -> None:
        """Initialize the problem extraction service with required dependencies.

        Args:
            ai_client: AI client implementing generate(system_prompt, user_prompt) -> str.
            repository: ProblemRepository for persisting extracted problems.
            patent_reader: ResearchRunPatentReader for querying patents linked to runs.
            problem_repository: Keyword-argument alias for repository.

        Raises:
            ValueError: If any required dependency is missing.
        """
        actual_repo = repository if repository is not None else problem_repository
        if ai_client is None:
            raise ValueError("ai_client is required and must not be None.")
        if actual_repo is None:
            raise ValueError("repository is required and must not be None.")
        if patent_reader is None:
            raise ValueError("patent_reader is required and must not be None.")

        self.ai_client = ai_client
        self.repository = actual_repo
        self.patent_reader = patent_reader

    def extract_problem_for_patent(self, run_id: str, patent_id: str) -> ProblemRecord:
        """Extract a problem from a single persisted patent and save it to the current run.

        Workflow:
            1. Validate run_id and patent_id.
            2. Retrieve the requested patent from the research run using ResearchRunPatentReader.
            3. If the patent is not part of the run, raise PatentNotInRunError.
            4. Convert PatentRecord using build_patent_extraction_input.
            5. Build user prompt using format_patent_extraction_user_prompt.
            6. Use PROBLEM_EXTRACTION_SYSTEM_PROMPT.
            7. Call injected AI client exactly once.
            8. Parse response using parse_problem_extraction_output.
            9. Persist ProblemRecord using ProblemRepository.save_problem.
            10. Return validated ProblemRecord.

        Args:
            run_id: Unique research run identifier.
            patent_id: Target patent number or database identifier.

        Returns:
            ProblemRecord: Validated and persisted problem record.

        Raises:
            ProblemExtractionServiceError: If arguments are invalid, parsing fails, or general service error occurs.
            PatentNotInRunError: If the patent is not part of the specified research run.
            ProblemExtractionAIError: If the AI client invocation fails.
            ProblemExtractionPersistenceError: If saving the problem to the repository fails.
        """
        # a. Validate run_id and patent_id
        if not isinstance(run_id, str) or not run_id.strip():
            raise ProblemExtractionServiceError("run_id must be a non-empty string.")
        if not isinstance(patent_id, str) or not patent_id.strip():
            raise ProblemExtractionServiceError("patent_id must be a non-empty string.")

        clean_run_id = run_id.strip()
        clean_patent_id = patent_id.strip()

        # b. Retrieve the requested patent from the research run using existing ResearchRunPatentReader
        try:
            run_patents = self.patent_reader.get_patents_for_run(clean_run_id)
        except Exception as exc:
            raise ProblemExtractionServiceError(
                f"Failed to retrieve patents for run '{clean_run_id}': {exc}"
            ) from exc

        # c. Find target patent; if not part of the run, raise PatentNotInRunError
        target_patent: Optional[PatentRecord] = None
        for p in run_patents:
            p_num = getattr(p, "patent_number", None)
            p_id = getattr(p, "id", None)
            raw_data = getattr(p, "raw_data", None)
            raw_id = raw_data.get("id") if isinstance(raw_data, dict) else None

            # Exact match on patent_number
            if p_num and p_num == clean_patent_id:
                target_patent = p
                break

            # Punctuation/case-insensitive match on normalized patent number
            try:
                if p_num and clean_patent_string(p_num) == clean_patent_string(clean_patent_id):
                    target_patent = p
                    break
            except Exception:
                pass

            # Primary key match if id attribute or raw_data id is present
            if (p_id and str(p_id) == clean_patent_id) or (raw_id and str(raw_id) == clean_patent_id):
                target_patent = p
                break

        if target_patent is None:
            raise PatentNotInRunError(
                f"Patent '{patent_id}' is not associated with research run '{clean_run_id}'."
            )

        # d. Convert PatentRecord using build_patent_extraction_input
        try:
            extraction_input = build_patent_extraction_input(target_patent)
        except Exception as exc:
            raise ProblemExtractionServiceError(
                f"Failed to build patent extraction input for patent '{target_patent.patent_number}': {exc}"
            ) from exc

        # e. Build the user prompt using format_patent_extraction_user_prompt
        try:
            user_prompt = format_patent_extraction_user_prompt(extraction_input)
        except Exception as exc:
            raise ProblemExtractionServiceError(
                f"Failed to format extraction user prompt for patent '{target_patent.patent_number}': {exc}"
            ) from exc

        # f. Use existing PROBLEM_EXTRACTION_SYSTEM_PROMPT
        system_prompt = PROBLEM_EXTRACTION_SYSTEM_PROMPT

        # g. Call the injected AI client exactly once
        try:
            raw_response = self.ai_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            raise ProblemExtractionAIError(
                f"AI problem extraction failed for patent '{target_patent.patent_number}': {exc}"
            ) from exc

        # h. Parse the response using parse_problem_extraction_output
        try:
            problem_record = parse_problem_extraction_output(
                response_text=raw_response,
                source_patent_numbers=(target_patent.patent_number,),
            )
        except Exception as exc:
            raise ProblemExtractionServiceError(
                f"Failed to parse extraction output for patent '{target_patent.patent_number}': {exc}"
            ) from exc

        # i. Persist the resulting ProblemRecord using ProblemRepository.save_problem
        try:
            self.repository.save_problem(problem=problem_record, run_id=clean_run_id)
        except Exception as exc:
            raise ProblemExtractionPersistenceError(
                f"Failed to persist extracted problem for patent '{target_patent.patent_number}': {exc}"
            ) from exc

        # j. Return the validated ProblemRecord
        return problem_record
