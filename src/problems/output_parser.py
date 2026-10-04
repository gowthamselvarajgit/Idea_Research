"""Safe parser for AI-generated problem extraction JSON outputs."""

import json
from typing import Final

from src.problems.extraction_contract import (
    ProblemContractValidationError,
    validate_problem_record,
)
from src.problems.models import ProblemRecord

REQUIRED_FIELDS: Final[frozenset[str]] = frozenset({
    "problem_title",
    "problem_description",
    "affected_users",
    "bottleneck_type",
    "technical_domain",
    "current_workaround",
    "problem_frequency",
    "problem_severity",
    "evidence_summary",
    "evidence_confidence",
})


class ProblemOutputParseError(ValueError):
    """Raised when an AI problem extraction response cannot be safely parsed or validated."""
    pass


def parse_problem_extraction_output(
    response_text: str,
    source_patent_numbers: tuple[str, ...],
) -> ProblemRecord:
    """Parse and validate raw AI extraction text into an immutable ProblemRecord.

    Strictly validates JSON structure, requires exactly the 10 defined fields,
    verifies controlled vocabularies, and associates the given source patent numbers.

    Args:
        response_text: Raw string response returned by the AI extractor.
        source_patent_numbers: Tuple of canonical patent numbers identifying origin patents.

    Returns:
        ProblemRecord: Validated immutable problem record.

    Raises:
        TypeError: If response_text is not a string.
        ProblemOutputParseError: If JSON is invalid, schema does not match exactly,
                                 values are non-strings, or contract validation fails.
    """
    if not isinstance(response_text, str):
        raise TypeError(f"response_text must be a str, got {type(response_text).__name__}.")

    clean_text = response_text.strip()
    if not clean_text:
        raise ProblemOutputParseError("AI extraction response text is empty.")

    # 1. Parse JSON
    try:
        data = json.loads(clean_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ProblemOutputParseError(f"Malformed JSON in AI extraction response: {err}") from err

    # 2. Require a JSON object/dictionary
    if not isinstance(data, dict):
        raise ProblemOutputParseError(
            f"Expected a JSON object/dictionary, got {type(data).__name__}."
        )

    # 3. Enforce exact 10 fields (no missing, no extra)
    data_keys = set(data.keys())
    missing_fields = REQUIRED_FIELDS - data_keys
    if missing_fields:
        raise ProblemOutputParseError(
            f"Extraction output missing required field(s): {sorted(list(missing_fields))}."
        )

    extra_fields = data_keys - REQUIRED_FIELDS
    if extra_fields:
        raise ProblemOutputParseError(
            f"Extraction output contains unexpected extra field(s): {sorted(list(extra_fields))}."
        )

    # 4. Require non-empty string values for all 10 fields
    for field_name in REQUIRED_FIELDS:
        val = data[field_name]
        if not isinstance(val, str):
            raise ProblemOutputParseError(
                f"Field '{field_name}' must be a string, got {type(val).__name__}."
            )
        if not val.strip():
            raise ProblemOutputParseError(
                f"Field '{field_name}' must not be empty or whitespace."
            )

    # 5. Instantiate ProblemRecord
    try:
        record = ProblemRecord(
            problem_title=data["problem_title"],
            problem_description=data["problem_description"],
            affected_users=data["affected_users"],
            bottleneck_type=data["bottleneck_type"],
            technical_domain=data["technical_domain"],
            current_workaround=data["current_workaround"],
            problem_frequency=data["problem_frequency"],
            problem_severity=data["problem_severity"],
            evidence_summary=data["evidence_summary"],
            evidence_confidence=data["evidence_confidence"],
            source_patent_numbers=source_patent_numbers,
            raw_data={"ai_raw_output": data},
        )
    except (ValueError, TypeError) as err:
        raise ProblemOutputParseError(f"Failed to construct ProblemRecord: {err}") from err

    # 6. Validate contract rules (controlled values)
    try:
        validate_problem_record(record)
    except (ProblemContractValidationError, ValueError) as err:
        raise ProblemOutputParseError(f"Extraction contract validation failed: {err}") from err

    return record
