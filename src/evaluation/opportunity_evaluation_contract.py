"""Strict evaluation contract and validation rules for startup opportunity evaluations.

Defines the required fields, controlled recommendations, scoring ranges,
and contract enforcement functions for AI-driven opportunity evaluation outputs.
"""

from typing import Any, Final
from src.evaluation.models import (
    ALLOWED_RECOMMENDATIONS,
    DIMENSION_SCORE_FIELDS,
    OpportunityEvaluationRecord,
)


class OpportunityEvaluationContractValidationError(ValueError, TypeError):
    """Raised when an opportunity evaluation record or payload violates evaluation contract rules."""
    pass


REQUIRED_EVALUATION_FIELDS: Final[frozenset[str]] = frozenset({
    "opportunity_id",
    "overall_score",
    "problem_severity_score",
    "frequency_score",
    "user_scale_score",
    "willingness_to_pay_score",
    "market_gap_score",
    "technology_leverage_score",
    "competition_score",
    "wow_factor_score",
    "recurring_potential_score",
    "social_impact_score",
    "execution_feasibility_score",
    "rejection_reasons",
    "recommendation",
    "rationale",
})

OPPORTUNITY_EVALUATION_CONTRACT_PRINCIPLES: Final[str] = """
Opportunity Evaluation Core Principles:

1. Objective Multi-Dimensional Scoring:
   - Each of the 11 dimension scores must be an integer from 0 to 10.
   - The overall_score must be an integer from 0 to 100 representing composite venture viability.

2. Controlled Recommendations:
   - Must be strictly one of: PURSUE, VALIDATE, REJECT.
   - PURSUE: Strong venture potential across market size, pain depth, defensibility, and tech advantage.
   - VALIDATE: Promising but critical uncertainties exist (e.g. willingness to pay or competition).
   - REJECT: Fundamental flaws (e.g. commodity business, no clear payer, minor feature, high risk).

3. Accountability & Rejection Reasoning:
   - When recommendation is REJECT, non-empty rejection_reasons must be explicitly stated.
   - When recommendation is PURSUE or VALIDATE, rejection_reasons may be empty.

4. Rigorous Justification:
   - The rationale must provide substantive, meaningful justification (minimum 15 characters).
   - Avoid generic phrases like "looks good" or "standard idea".
"""


def validate_opportunity_evaluation_payload(data: Any) -> None:
    """Validate a raw evaluation dictionary against strict contract constraints.

    Args:
        data: Parsed dictionary from evaluation output.

    Raises:
        OpportunityEvaluationContractValidationError: If data is invalid.
    """
    if not isinstance(data, dict):
        raise OpportunityEvaluationContractValidationError(
            f"Expected a dictionary for evaluation payload, got {type(data).__name__}."
        )

    # 1. Enforce exact required fields (no missing, no extra)
    data_keys = set(data.keys())
    missing = REQUIRED_EVALUATION_FIELDS - data_keys
    if missing:
        raise OpportunityEvaluationContractValidationError(
            f"Evaluation payload missing required field(s): {sorted(list(missing))}."
        )

    extra = data_keys - REQUIRED_EVALUATION_FIELDS
    if extra:
        raise OpportunityEvaluationContractValidationError(
            f"Evaluation payload contains unexpected extra field(s): {sorted(list(extra))}."
        )

    # 2. Validate opportunity_id
    opp_id = data["opportunity_id"]
    if not isinstance(opp_id, str) or not opp_id.strip():
        raise OpportunityEvaluationContractValidationError(
            "Field 'opportunity_id' must be a non-empty string."
        )

    # 3. Validate overall_score
    overall = data["overall_score"]
    if isinstance(overall, bool) or not isinstance(overall, int):
        raise OpportunityEvaluationContractValidationError(
            f"Field 'overall_score' must be an integer, got {type(overall).__name__}."
        )
    if not (0 <= overall <= 100):
        raise OpportunityEvaluationContractValidationError(
            f"Field 'overall_score' must be between 0 and 100, got {overall}."
        )

    # 4. Validate dimension scores (0-10)
    for dim_field in DIMENSION_SCORE_FIELDS:
        val = data[dim_field]
        if isinstance(val, bool) or not isinstance(val, int):
            raise OpportunityEvaluationContractValidationError(
                f"Field '{dim_field}' must be an integer, got {type(val).__name__}."
            )
        if not (0 <= val <= 10):
            raise OpportunityEvaluationContractValidationError(
                f"Field '{dim_field}' must be an integer between 0 and 10, got {val}."
            )

    # 5. Validate recommendation
    rec = data["recommendation"]
    if not isinstance(rec, str):
        raise OpportunityEvaluationContractValidationError(
            f"Field 'recommendation' must be a string, got {type(rec).__name__}."
        )
    clean_rec = rec.strip().upper()
    if clean_rec not in ALLOWED_RECOMMENDATIONS:
        raise OpportunityEvaluationContractValidationError(
            f"Invalid recommendation: '{rec}'. Allowed values: {sorted(list(ALLOWED_RECOMMENDATIONS))}."
        )

    # 6. Validate rejection_reasons
    reasons = data["rejection_reasons"]
    if not isinstance(reasons, (list, tuple)) or isinstance(reasons, (str, bytes)):
        raise OpportunityEvaluationContractValidationError(
            f"Field 'rejection_reasons' must be a list or tuple of strings, got {type(reasons).__name__}."
        )

    for i, reason in enumerate(reasons):
        if not isinstance(reason, str) or not reason.strip():
            raise OpportunityEvaluationContractValidationError(
                f"rejection_reasons[{i}] must be a non-empty string."
            )

    # If recommendation is REJECT, require at least one rejection reason
    if clean_rec == "REJECT" and len(reasons) == 0:
        raise OpportunityEvaluationContractValidationError(
            "Evaluation with recommendation 'REJECT' must specify at least one rejection reason."
        )

    # 7. Validate rationale
    rationale = data["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise OpportunityEvaluationContractValidationError(
            "Field 'rationale' must be a non-empty string."
        )
    if len(rationale.strip()) < 15:
        raise OpportunityEvaluationContractValidationError(
            f"Field 'rationale' must provide substantive justification (at least 15 characters, got {len(rationale.strip())})."
        )


def validate_opportunity_evaluation_record(record: OpportunityEvaluationRecord) -> None:
    """Validate that an OpportunityEvaluationRecord strictly adheres to the evaluation contract.

    Args:
        record: OpportunityEvaluationRecord instance.

    Raises:
        OpportunityEvaluationContractValidationError: If record violates contract.
        TypeError: If record is not an OpportunityEvaluationRecord.
    """
    if not isinstance(record, OpportunityEvaluationRecord):
        raise TypeError(
            f"Expected OpportunityEvaluationRecord instance, got {type(record).__name__}."
        )

    if record.recommendation == "REJECT" and len(record.rejection_reasons) == 0:
        raise OpportunityEvaluationContractValidationError(
            "OpportunityEvaluationRecord with recommendation 'REJECT' must specify at least one rejection reason."
        )

    if len(record.rationale.strip()) < 15:
        raise OpportunityEvaluationContractValidationError(
            f"rationale must provide substantive justification (at least 15 characters, got {len(record.rationale.strip())})."
        )


def validate_opportunity_evaluation_contract(target: Any) -> None:
    """Unified validation entry point for either evaluation dictionary payload or OpportunityEvaluationRecord."""
    if isinstance(target, OpportunityEvaluationRecord):
        validate_opportunity_evaluation_record(target)
    elif isinstance(target, dict):
        validate_opportunity_evaluation_payload(target)
    else:
        raise OpportunityEvaluationContractValidationError(
            f"Expected OpportunityEvaluationRecord or dict, got {type(target).__name__}."
        )
