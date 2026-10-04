"""Defensive parser for AI-generated startup opportunity synthesis JSON outputs."""

import json
from typing import Any

from src.opportunities.models import OpportunityRecord
from src.opportunities.opportunity_contract import (
    OpportunityContractValidationError,
    validate_opportunity_ai_output,
)


class OpportunityOutputParseError(ValueError):
    """Raised when an AI opportunity synthesis response cannot be safely parsed or validated."""
    pass


def parse_opportunity_synthesis_output(raw_output: str) -> OpportunityRecord:
    """Parse and validate raw AI synthesis text into an immutable OpportunityRecord.

    Strictly validates JSON structure, requires exactly the 5 defined AI fields,
    verifies contract constraints, and creates an OpportunityRecord with id=None.

    Args:
        raw_output: Raw string response returned by the AI synthesis engine.

    Returns:
        OpportunityRecord: Validated immutable opportunity record with id=None.

    Raises:
        TypeError: If raw_output is not a string.
        OpportunityOutputParseError: If output is empty, malformed JSON, a JSON array/primitive,
                                     missing/extra fields, fails contract validation,
                                     or fails model construction.
    """
    if not isinstance(raw_output, str):
        raise TypeError(f"raw_output must be a str, got {type(raw_output).__name__}.")

    clean_text = raw_output.strip()
    if not clean_text:
        raise OpportunityOutputParseError(
            "JSON parsing failure: AI synthesis output is empty or whitespace."
        )

    # 1. Parse JSON safely without repairing malformed text or stripping markdown fences
    try:
        data = json.loads(clean_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise OpportunityOutputParseError(
            f"JSON parsing failure: malformed JSON in AI synthesis response: {err}"
        ) from err

    # 2. Require a JSON object/dictionary (rejecting arrays and primitives)
    if not isinstance(data, dict):
        if isinstance(data, list):
            raise OpportunityOutputParseError(
                "JSON parsing failure: expected JSON object/dictionary, got JSON array (list)."
            )
        raise OpportunityOutputParseError(
            f"JSON parsing failure: expected JSON object/dictionary, got JSON primitive ({type(data).__name__})."
        )

    # 3. Validate the parsed dictionary using the existing contract validator
    try:
        validate_opportunity_ai_output(data)
    except OpportunityContractValidationError as err:
        raise OpportunityOutputParseError(
            f"Contract validation failure: {err}"
        ) from err

    # 4. Construct immutable OpportunityRecord with id=None and immutable tuple for source_problem_ids
    try:
        record = OpportunityRecord(
            opportunity_title=data["opportunity_title"],
            solution_concept=data["solution_concept"],
            target_customer=data["target_customer"],
            value_proposition=data["value_proposition"],
            source_problem_ids=tuple(data["source_problem_ids"]),
            id=None,
            raw_data={"ai_raw_output": data},
        )
    except (ValueError, TypeError) as err:
        raise OpportunityOutputParseError(
            f"Model construction failure: {err}"
        ) from err

    return record
