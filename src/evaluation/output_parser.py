"""Defensive parser for AI-generated opportunity evaluation JSON outputs."""

import json
from typing import Any, Optional

from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.opportunity_evaluation_contract import (
    OpportunityEvaluationContractValidationError,
    validate_opportunity_evaluation_payload,
)


class OpportunityEvaluationOutputParseError(ValueError):
    """Raised when an AI opportunity evaluation response cannot be safely parsed or validated."""
    pass


def parse_opportunity_evaluation_output(
    raw_output: str,
    expected_opportunity_id: Optional[str] = None,
) -> OpportunityEvaluationRecord:
    """Parse and validate raw AI evaluation output text into an immutable OpportunityEvaluationRecord.

    Strictly validates JSON structure, requires exactly the 16 defined evaluation fields,
    enforces contract validation, and instantiates an OpportunityEvaluationRecord with id=None.

    Args:
        raw_output: Raw string response returned by the AI evaluation engine.
        expected_opportunity_id: Optional opportunity ID to enforce matching.

    Returns:
        OpportunityEvaluationRecord: Validated immutable evaluation record with id=None.

    Raises:
        TypeError: If raw_output is not a string.
        OpportunityEvaluationOutputParseError: If output is empty, malformed JSON, a JSON array/primitive,
                                              missing/extra fields, fails contract validation,
                                              or fails model construction.
    """
    if not isinstance(raw_output, str):
        raise TypeError(f"raw_output must be a str, got {type(raw_output).__name__}.")

    clean_text = raw_output.strip()
    if not clean_text:
        raise OpportunityEvaluationOutputParseError(
            "JSON parsing failure: AI evaluation output is empty or whitespace."
        )

    # 1. Parse JSON safely without repairing malformed text or stripping markdown fences
    try:
        data = json.loads(clean_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise OpportunityEvaluationOutputParseError(
            f"JSON parsing failure: malformed JSON in AI evaluation response: {err}"
        ) from err

    # 2. Require a JSON object/dictionary (rejecting arrays and primitives)
    if not isinstance(data, dict):
        if isinstance(data, list):
            raise OpportunityEvaluationOutputParseError(
                "JSON parsing failure: expected JSON object/dictionary, got JSON array (list)."
            )
        raise OpportunityEvaluationOutputParseError(
            f"JSON parsing failure: expected JSON object/dictionary, got JSON primitive ({type(data).__name__})."
        )

    # 3. Validate the parsed dictionary using the strict evaluation contract validator
    try:
        validate_opportunity_evaluation_payload(data)
    except OpportunityEvaluationContractValidationError as err:
        raise OpportunityEvaluationOutputParseError(
            f"Contract validation failure: {err}"
        ) from err

    # 4. Enforce expected_opportunity_id if provided
    if expected_opportunity_id and expected_opportunity_id.strip():
        clean_expected = expected_opportunity_id.strip()
        if data["opportunity_id"].strip() != clean_expected:
            raise OpportunityEvaluationOutputParseError(
                f"Contract validation failure: opportunity_id mismatch (expected '{clean_expected}', got '{data['opportunity_id']}')."
            )

    # 5. Construct immutable OpportunityEvaluationRecord with id=None and immutable tuple for rejection_reasons
    try:
        record = OpportunityEvaluationRecord(
            opportunity_id=data["opportunity_id"],
            overall_score=data["overall_score"],
            problem_severity_score=data["problem_severity_score"],
            frequency_score=data["frequency_score"],
            user_scale_score=data["user_scale_score"],
            willingness_to_pay_score=data["willingness_to_pay_score"],
            market_gap_score=data["market_gap_score"],
            technology_leverage_score=data["technology_leverage_score"],
            competition_score=data["competition_score"],
            wow_factor_score=data["wow_factor_score"],
            recurring_potential_score=data["recurring_potential_score"],
            social_impact_score=data["social_impact_score"],
            execution_feasibility_score=data["execution_feasibility_score"],
            rejection_reasons=tuple(data["rejection_reasons"]),
            recommendation=data["recommendation"],
            rationale=data["rationale"],
            id=None,
            raw_data={"ai_raw_output": data},
        )
    except (ValueError, TypeError) as err:
        raise OpportunityEvaluationOutputParseError(
            f"Model construction failure: {err}"
        ) from err

    return record
