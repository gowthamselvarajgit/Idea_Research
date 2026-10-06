"""Data models and validation rules for external web research sources.

Defines the immutable WebResearchSource dataclass representing information
retrieved from external web sources (e.g., competitor sites, reviews, news, industry reports).
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Final, Optional


ALLOWED_SOURCE_TYPES: Final[frozenset[str]] = frozenset({
    "competitor",
    "product",
    "review",
    "news",
    "industry",
    "community",
    "official",
    "other",
})

REQUIRED_SOURCE_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "url",
    "title",
    "publisher_or_domain",
    "retrieved_content",
    "retrieved_at",
)


@dataclass(frozen=True)
class WebResearchSource:
    """Immutable record of an externally retrieved web research source.

    Attributes:
        url: Canonical web URL of the discovered evidence.
        title: Page, document, or article title.
        source_type: Controlled classification of the source (e.g., competitor, review).
        publisher_or_domain: Domain name, publisher, or platform identity.
        retrieved_content: Extracted text, excerpt, or evidence body.
        retrieved_at: ISO timestamp or retrieval date string.
        id: Optional persistent UUID or record identifier.
        raw_data: Optional dictionary preserving raw scraping, crawler, or search metadata.
    """

    url: str
    title: str
    source_type: str
    publisher_or_domain: str
    retrieved_content: str
    retrieved_at: str
    id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field constraints and enforce immutability conventions."""
        # 0. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or isinstance(self.id, bool) or not self.id.strip():
                raise ValueError("WebResearchSource id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 1. Validate required text fields
        for field_name in REQUIRED_SOURCE_TEXT_FIELDS:
            val = getattr(self, field_name)
            if not isinstance(val, str) or isinstance(val, bool):
                raise ValueError(
                    f"WebResearchSource requires a non-empty string for '{field_name}'."
                )
            clean_val = val.strip()
            if not clean_val:
                raise ValueError(
                    f"WebResearchSource requires a non-empty string for '{field_name}'."
                )
            object.__setattr__(self, field_name, clean_val)

        # 2. Validate source_type
        if not isinstance(self.source_type, str) or isinstance(self.source_type, bool):
            raise TypeError("source_type must be a string.")
        clean_st = self.source_type.strip().lower()
        if clean_st not in ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type: '{self.source_type}'. "
                f"Allowed values are: {sorted(list(ALLOWED_SOURCE_TYPES))}."
            )
        object.__setattr__(self, "source_type", clean_st)

        # 3. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize WebResearchSource to a standard dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebResearchSource":
        """Construct a WebResearchSource from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}.")
        return cls(
            url=data["url"],
            title=data["title"],
            source_type=data["source_type"],
            publisher_or_domain=data["publisher_or_domain"],
            retrieved_content=data["retrieved_content"],
            retrieved_at=data["retrieved_at"],
            id=data.get("id"),
            raw_data=data.get("raw_data", {}),
        )
