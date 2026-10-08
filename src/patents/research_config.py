"""Reusable research domain and theme configuration for patent discovery."""

from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class ResearchDomainConfig:
    """Configuration defining a research domain and its targeted discovery themes/queries.

    Attributes:
        domain_name: Non-empty string naming the research domain (e.g., 'Cosmetics & Skincare').
        themes: Non-empty tuple of query strings representing targeted innovation themes.
        description: Optional explanatory summary of the research domain scope.
    """

    domain_name: str
    themes: tuple[str, ...]
    description: Optional[str] = None

    def __init__(
        self,
        domain_name: str,
        themes: Optional[Sequence[str]] = None,
        description: Optional[str] = None,
        *,
        queries: Optional[Sequence[str]] = None,
    ) -> None:
        """Initialize and validate a ResearchDomainConfig instance."""
        if domain_name is None or not isinstance(domain_name, str) or not domain_name.strip():
            raise ValueError("domain_name must be a non-empty string.")

        raw_themes = themes if themes is not None else queries
        if raw_themes is None:
            raise ValueError("themes (or queries) must be provided as a non-empty sequence.")

        if isinstance(raw_themes, str) or not hasattr(raw_themes, "__iter__"):
            raise ValueError("themes must be a non-empty sequence of strings.")

        cleaned_themes: list[str] = []
        for item in raw_themes:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Each theme/query in themes must be a non-empty string.")
            cleaned_themes.append(item.strip())

        if not cleaned_themes:
            raise ValueError("themes cannot be empty.")

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string or None.")

        object.__setattr__(self, "domain_name", domain_name.strip())
        object.__setattr__(self, "themes", tuple(cleaned_themes))
        object.__setattr__(self, "description", description.strip() if description else None)

    @property
    def queries(self) -> tuple[str, ...]:
        """Convenience alias for themes."""
        return self.themes

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary."""
        return {
            "domain_name": self.domain_name,
            "description": self.description,
            "themes": list(self.themes),
            "queries": list(self.themes),
        }


# Convenience alias for domain configuration
PatentResearchConfig = ResearchDomainConfig


# Predefined Research Domain Configurations

COSMETICS_RESEARCH_CONFIG = ResearchDomainConfig(
    domain_name="Cosmetics & Skincare",
    description="Cosmetics, skincare formulations, cosmetic ingredients, and beauty technology innovation.",
    themes=(
        "skincare",
        "cosmetics",
        "skincare products",
        "cosmetic ingredients",
        "skin care technology",
        "personalised skincare",
        "AI skin analysis",
        "beauty technology",
        "cosmetic formulation",
        "skincare recommendation",
    ),
)

WATER_RESEARCH_CONFIG = ResearchDomainConfig(
    domain_name="Water Quality & Infrastructure",
    description="Water monitoring, quality detection, contamination treatment, and purification infrastructure.",
    themes=(
        "WATER MONITORING",
        "WATER QUALITY",
        "WATER CONTAMINATION",
        "WATER PURIFICATION",
        "WATER LEAKAGE",
        "WATER CONSERVATION",
        "WATER INFRASTRUCTURE",
        "WATER SAFETY",
        "WATER TREATMENT",
        "WATER DETECTION",
        "WATER MANAGEMENT",
        "WATER RECOVERY",
    ),
)

DEFAULT_RESEARCH_CONFIG = COSMETICS_RESEARCH_CONFIG


def get_default_research_config() -> ResearchDomainConfig:
    """Return the default/current active research domain configuration."""
    return DEFAULT_RESEARCH_CONFIG
