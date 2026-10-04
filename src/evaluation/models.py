"""Opportunity evaluation data model and validation rules.

Defines the immutable OpportunityEvaluationRecord dataclass representing
multi-dimensional venture feasibility and defensibility scoring for startup opportunities.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Final, Optional

ALLOWED_RECOMMENDATIONS: Final[frozenset[str]] = frozenset({"PURSUE", "VALIDATE", "REJECT"})

DIMENSION_SCORE_FIELDS: Final[tuple[str, ...]] = (
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
)


@dataclass(frozen=True)
class OpportunityEvaluationRecord:
    """Immutable evaluation record for a startup venture opportunity.

    Attributes:
        opportunity_id: Identifier of the evaluated OpportunityRecord.
        overall_score: Composite venture score (0–100).
        problem_severity_score: Severity/pain depth score (0–10).
        frequency_score: Occurrence frequency score (0–10).
        user_scale_score: Addressable user population reach score (0–10).
        willingness_to_pay_score: Payer urgency and budget score (0–10).
        market_gap_score: Unmet need and white space score (0–10).
        technology_leverage_score: 10x technical advantage score (0–10).
        competition_score: Market structure and defensibility score (0–10).
        wow_factor_score: Category-defining appeal / differentiation score (0–10).
        recurring_potential_score: Subscription/retention business model score (0–10).
        social_impact_score: Societal and ESG improvement score (0–10).
        execution_feasibility_score: Technical and operational buildability score (0–10).
        rejection_reasons: Tuple of reasons if rejected or cautioned against.
        recommendation: PURSUE, VALIDATE, or REJECT.
        rationale: Explanatory synthesis justifying the evaluation.
        id: Optional persistent UUID primary key assigned upon database storage.
        raw_data: Optional dictionary preserving raw evaluation payload and metadata.
    """

    opportunity_id: str
    overall_score: int
    problem_severity_score: int
    frequency_score: int
    user_scale_score: int
    willingness_to_pay_score: int
    market_gap_score: int
    technology_leverage_score: int
    competition_score: int
    wow_factor_score: int
    recurring_potential_score: int
    social_impact_score: int
    execution_feasibility_score: int
    rejection_reasons: tuple[str, ...]
    recommendation: str
    rationale: str
    id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field constraints, ranges, and enforce immutability conventions."""
        # 1. Validate opportunity_id
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            raise ValueError(
                "OpportunityEvaluationRecord requires a non-empty string for 'opportunity_id'."
            )
        object.__setattr__(self, "opportunity_id", self.opportunity_id.strip())

        # 2. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or not self.id.strip():
                raise ValueError("OpportunityEvaluationRecord id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 3. Validate overall_score (0-100)
        if isinstance(self.overall_score, bool) or not isinstance(self.overall_score, int):
            raise TypeError("overall_score must be an integer.")
        if not (0 <= self.overall_score <= 100):
            raise ValueError(f"overall_score must be between 0 and 100, got {self.overall_score}.")

        # 4. Validate dimension scores (0-10)
        for field_name in DIMENSION_SCORE_FIELDS:
            val = getattr(self, field_name)
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"'{field_name}' must be an integer.")
            if not (0 <= val <= 10):
                raise ValueError(f"'{field_name}' must be an integer between 0 and 10, got {val}.")

        # 5. Validate and enforce rejection_reasons as immutable tuple of non-empty strings
        if isinstance(self.rejection_reasons, (list, tuple)):
            clean_reasons = tuple(self.rejection_reasons)
            object.__setattr__(self, "rejection_reasons", clean_reasons)
        else:
            raise TypeError("rejection_reasons must be a tuple or list of strings.")

        for i, reason in enumerate(self.rejection_reasons):
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"rejection_reasons[{i}] must be a non-empty string.")

        # 6. Validate recommendation
        if not isinstance(self.recommendation, str):
            raise TypeError("recommendation must be a string.")
        clean_rec = self.recommendation.strip().upper()
        if clean_rec not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(
                f"Invalid recommendation: '{self.recommendation}'. "
                f"Allowed values are: {sorted(list(ALLOWED_RECOMMENDATIONS))}."
            )
        object.__setattr__(self, "recommendation", clean_rec)

        # 7. Validate rationale
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError(
                "OpportunityEvaluationRecord requires a non-empty string for 'rationale'."
            )
        object.__setattr__(self, "rationale", self.rationale.strip())

        # 8. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize OpportunityEvaluationRecord to a standard dictionary."""
        return asdict(self)
