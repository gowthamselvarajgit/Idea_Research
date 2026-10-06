"""Data models for web search discovery results.

Defines the immutable SearchResult dataclass representing a single discovered
web page URL and its basic snippet metadata returned by a search provider.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Final, Optional
import urllib.parse

REQUIRED_SEARCH_RESULT_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "url",
    "title",
    "snippet",
    "domain",
)


@dataclass(frozen=True)
class SearchResult:
    """Immutable record of an externally discovered search result item.

    Attributes:
        url: Discovered HTTP/HTTPS web page URL.
        title: Title headline of the discovered page.
        snippet: Text excerpt or summary snippet returned by the search provider.
        domain: Hostname or publishing domain of the discovered result.
        id: Optional persistent UUID or record identifier.
        raw_data: Optional dictionary preserving raw provider metadata (e.g. rank, engine).
    """

    url: str
    title: str
    snippet: str
    domain: str
    id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field constraints and ensure immutability."""
        # 0. Validate optional id
        if self.id is not None:
            if not isinstance(self.id, str) or isinstance(self.id, bool) or not self.id.strip():
                raise ValueError("SearchResult id must be a non-empty string if provided.")
            object.__setattr__(self, "id", self.id.strip())

        # 1. Validate required text fields
        for field_name in REQUIRED_SEARCH_RESULT_TEXT_FIELDS:
            val = getattr(self, field_name)
            if not isinstance(val, str) or isinstance(val, bool):
                raise ValueError(
                    f"SearchResult requires a non-empty string for '{field_name}'."
                )
            clean_val = val.strip()
            if not clean_val:
                raise ValueError(
                    f"SearchResult requires a non-empty string for '{field_name}'."
                )
            object.__setattr__(self, field_name, clean_val)

        # 2. Validate URL scheme
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"SearchResult URL must be a valid HTTP or HTTPS URL, got '{self.url}'."
            )

        # 3. Validate raw_data
        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    @property
    def source(self) -> str:
        """Alias property for domain/source identity."""
        return self.domain

    def to_dict(self) -> dict[str, Any]:
        """Serialize SearchResult to a standard dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """Construct a SearchResult instance from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}.")
        return cls(
            url=data["url"],
            title=data["title"],
            snippet=data["snippet"],
            domain=data.get("domain") or data.get("source", ""),
            id=data.get("id"),
            raw_data=data.get("raw_data", {}),
        )
