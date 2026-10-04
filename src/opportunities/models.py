"""Canonical startup opportunity data models and validation rules.

Defines the immutable OpportunityRecord dataclass representing venture opportunities
synthesized from validated problem statements and bottlenecks.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


REQUIRED_OPPORTUNITY_TEXT_FIELDS = (
    "opportunity_title",
    "solution_concept",
    "target_customer",
    "value_proposition",
)


@dataclass(frozen=True)
class OpportunityRecord:
    """Immutable record of a startup venture opportunity synthesized from problem analysis.

    Attributes:
        opportunity_title: Concise commercial venture or product concept headline.
        solution_concept: Technical and commercial architecture solving the bottleneck.
        target_customer: Precise customer segment or industrial buyer facing the pain point.
        value_proposition: Quantifiable value, ROI, or efficiency improvement delivered.
        source_problem_ids: Tuple of persistent ProblemRecord UUIDs addressed by this opportunity.
        id: Optional persistent UUID primary key assigned upon database storage.
        raw_data: Optional dictionary preserving raw synthesis payload and metadata.
    """

    opportunity_title: str
    solution_concept: str
    target_customer: str
    value_proposition: str
    source_problem_ids: tuple[str, ...]
    id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field constraints and enforce immutability conventions."""
        # 0. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or not self.id.strip():
                raise ValueError("OpportunityRecord id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 1. Validate required text fields
        for field_name in REQUIRED_OPPORTUNITY_TEXT_FIELDS:
            val = getattr(self, field_name)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"OpportunityRecord requires a non-empty string for '{field_name}'."
                )

        # 2. Validate and enforce source_problem_ids as a non-empty tuple
        if isinstance(self.source_problem_ids, (list, tuple)):
            clean_problems = tuple(self.source_problem_ids)
            object.__setattr__(self, "source_problem_ids", clean_problems)
        else:
            raise TypeError("source_problem_ids must be a tuple or sequence of strings.")

        if not self.source_problem_ids:
            raise ValueError("source_problem_ids must contain at least one problem ID.")

        for pid in self.source_problem_ids:
            if not isinstance(pid, str) or not pid.strip():
                raise ValueError("All source problem IDs must be non-empty strings.")

        # 3. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize OpportunityRecord to a standard dictionary."""
        return asdict(self)
