"""Market research data models and validation rules.

Defines the immutable MarketResearchRecord dataclass representing structured
market evidence, competitive intelligence, and validation findings connected
to startup opportunities.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Final, Optional


ALLOWED_RELEVANCE: Final[frozenset[str]] = frozenset({"HIGH", "MEDIUM", "LOW"})

REQUIRED_MARKET_RESEARCH_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "opportunity_id",
    "source_type",
    "source_name",
    "source_url",
    "company_or_product",
    "finding",
    "evidence_summary",
)


@dataclass(frozen=True)
class MarketResearchRecord:
    """Immutable record of market evidence or competitive intelligence for an opportunity.

    Attributes:
        opportunity_id: Identifier of the related startup opportunity.
        source_type: Category of research source (e.g., competitor_site, industry_report, news, review_forum).
        source_name: Name of publication, platform, or source organization.
        source_url: Canonical web URL or direct citation reference.
        company_or_product: Name of existing company, product, or solution discovered.
        finding: Concrete finding or key market insight.
        evidence_summary: Factual summary of the collected market evidence.
        relevance: Evaluated relevance level (HIGH, MEDIUM, LOW).
        id: Optional persistent UUID primary key assigned upon database storage.
        raw_data: Optional dictionary preserving raw payload and scraping/search metadata.
    """

    opportunity_id: str
    source_type: str
    source_name: str
    source_url: str
    company_or_product: str
    finding: str
    evidence_summary: str
    relevance: str
    id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field constraints and enforce immutability conventions."""
        # 0. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or not self.id.strip():
                raise ValueError("MarketResearchRecord id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 1. Validate required text fields
        for field_name in REQUIRED_MARKET_RESEARCH_TEXT_FIELDS:
            val = getattr(self, field_name)
            if not isinstance(val, str) or isinstance(val, bool):
                raise ValueError(
                    f"MarketResearchRecord requires a non-empty string for '{field_name}'."
                )
            clean_val = val.strip()
            if not clean_val:
                raise ValueError(
                    f"MarketResearchRecord requires a non-empty string for '{field_name}'."
                )
            object.__setattr__(self, field_name, clean_val)

        # 2. Validate relevance
        if not isinstance(self.relevance, str) or isinstance(self.relevance, bool):
            raise TypeError("relevance must be a string.")
        clean_rel = self.relevance.strip().upper()
        if clean_rel not in ALLOWED_RELEVANCE:
            raise ValueError(
                f"Invalid relevance: '{self.relevance}'. "
                f"Allowed values are: {sorted(list(ALLOWED_RELEVANCE))}."
            )
        object.__setattr__(self, "relevance", clean_rel)

        # 3. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize MarketResearchRecord to a standard dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketResearchRecord":
        """Construct a MarketResearchRecord from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}.")
        return cls(
            opportunity_id=data["opportunity_id"],
            source_type=data["source_type"],
            source_name=data["source_name"],
            source_url=data["source_url"],
            company_or_product=data["company_or_product"],
            finding=data["finding"],
            evidence_summary=data["evidence_summary"],
            relevance=data["relevance"],
            id=data.get("id"),
            raw_data=data.get("raw_data", {}),
        )
