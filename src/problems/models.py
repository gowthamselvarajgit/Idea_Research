"""Canonical problem data models and validation rules.

Defines the immutable ProblemRecord dataclass representing verified technical
problems and bottlenecks extracted from patent literature.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


REQUIRED_TEXT_FIELDS = (
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
)


@dataclass(frozen=True)
class ProblemRecord:
    """Immutable record of a technical problem discovered from patent analysis.

    Attributes:
        problem_title: Concise headline summarizing the bottleneck.
        problem_description: Comprehensive technical description of the failure or limitation.
        affected_users: Industry stakeholders, engineers, or operators impacted.
        bottleneck_type: Category of bottleneck (e.g., material degradation, thermal runaway).
        technical_domain: Broader domain classification (e.g., Energy Storage, Semiconductor).
        current_workaround: State-of-the-art compromise or partial solution currently used.
        problem_frequency: Recurrence indicator (e.g., high, periodic, rare).
        problem_severity: Impact level (e.g., critical, high, moderate).
        evidence_summary: Synthesis of findings and patent claims proving problem existence.
        evidence_confidence: Confidence evaluation (e.g., high, medium, low).
        source_patent_numbers: Tuple of canonical normalized patent publication numbers.
        raw_data: Optional dictionary preserving raw extraction payload and metadata.
        id: Optional persistent UUID primary key assigned upon database storage.
    """

    problem_title: str
    problem_description: str
    affected_users: str
    bottleneck_type: str
    technical_domain: str
    current_workaround: str
    problem_frequency: str
    problem_severity: str
    evidence_summary: str
    evidence_confidence: str
    source_patent_numbers: tuple[str, ...]
    raw_data: dict = field(default_factory=dict)
    id: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate field constraints and ensure immutability conventions."""
        # 0. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or not self.id.strip():
                raise ValueError("ProblemRecord id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 1. Validate required text fields
        for field_name in REQUIRED_TEXT_FIELDS:
            val = getattr(self, field_name)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"ProblemRecord requires a non-empty string for '{field_name}'."
                )

        # 2. Validate and enforce source_patent_numbers as a non-empty tuple
        if isinstance(self.source_patent_numbers, (list, tuple)):
            clean_patents = tuple(self.source_patent_numbers)
            object.__setattr__(self, "source_patent_numbers", clean_patents)
        else:
            raise TypeError("source_patent_numbers must be a tuple or sequence of strings.")

        if not self.source_patent_numbers:
            raise ValueError("source_patent_numbers must contain at least one patent number.")

        for pat in self.source_patent_numbers:
            if not isinstance(pat, str) or not pat.strip():
                raise ValueError("All source patent numbers must be non-empty strings.")

        # 3. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize ProblemRecord to a standard dictionary."""
        return asdict(self)
