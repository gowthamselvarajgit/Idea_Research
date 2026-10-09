"""Domain-agnostic web research query generator for market research.

Transforms a generic ResearchDomainConfig into a deterministic, bounded sequence
of focused web-search queries covering key commercial and innovation intents
(competitors, products, technology, customer problems, reviews, gaps, trends).
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Final, Optional, Sequence

from src.patents.research_config import ResearchDomainConfig

logger = logging.getLogger(__name__)

# Standard domain-agnostic market research categories and their search intent phrases
DEFAULT_RESEARCH_CATEGORIES: Final[tuple[tuple[str, str], ...]] = (
    ("competitors", "competitors"),
    ("products", "products"),
    ("technology", "technology"),
    ("customer_problems", "customer problems"),
    ("complaints_reviews", "complaints reviews"),
    ("market_gaps", "market gaps"),
    ("emerging_trends", "emerging trends"),
)

DEFAULT_MAX_RESEARCH_QUERIES: Final[int] = 20


@dataclass(frozen=True)
class ResearchQueryItem:
    """Structured representation of an individual generated market research query.

    Attributes:
        query: Full search query text.
        category: Research intent category (e.g. 'competitors', 'market_gaps').
        theme: Originating domain theme keyword from configuration.
    """

    query: str
    category: str
    theme: str

    def to_dict(self) -> dict[str, str]:
        """Serialize query item to a standard dictionary."""
        return {
            "query": self.query,
            "category": self.category,
            "theme": self.theme,
        }


@dataclass(frozen=True)
class GeneratedResearchQueries:
    """Immutable collection of market research queries derived from a ResearchDomainConfig.

    Attributes:
        domain_name: Name of the research domain.
        queries: Tuple of unique search query strings in deterministic order.
        items: Tuple of structured ResearchQueryItem records preserving intent metadata.
    """

    domain_name: str
    queries: tuple[str, ...]
    items: tuple[ResearchQueryItem, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.queries)

    def __iter__(self):
        return iter(self.queries)

    def __getitem__(self, index: int) -> str:
        return self.queries[index]

    def to_dict(self) -> dict[str, Any]:
        """Serialize generated queries collection to a dictionary."""
        return {
            "domain_name": self.domain_name,
            "query_count": len(self.queries),
            "queries": list(self.queries),
            "items": [item.to_dict() for item in self.items],
        }


def build_research_query(
    theme: str,
    intent_phrase: str,
    *,
    quote_subject_anchor: bool = False,
) -> str:
    """Combine a research theme with an intent modifier without duplicating tokens.

    Args:
        theme: Theme or topic string (e.g. 'skincare', 'precision agriculture').
        intent_phrase: Intent modifier phrase (e.g. 'competitors', 'customer problems').
        quote_subject_anchor: If True, wraps the theme in quotes as a primary anchor
            for providers like Google News that benefit from subject anchoring.

    Returns:
        str: Clean combined query string.
    """
    clean_theme = " ".join(theme.strip().split())
    clean_intent = " ".join(intent_phrase.strip().split())

    theme_tokens = set(clean_theme.lower().split())
    intent_tokens = [w for w in clean_intent.split() if w.lower() not in theme_tokens]

    anchor = clean_theme
    if quote_subject_anchor and clean_theme:
        if not (clean_theme.startswith('"') and clean_theme.endswith('"')):
            anchor = f'"{clean_theme}"'

    if not intent_tokens:
        return anchor

    return f"{anchor} {' '.join(intent_tokens)}"


class ResearchQueryGenerator:
    """Generates deterministic, domain-agnostic web market research queries from domain configurations."""

    def __init__(
        self,
        categories: Optional[Sequence[tuple[str, str]]] = None,
        quote_subject_anchor: bool = False,
    ) -> None:
        """Initialize ResearchQueryGenerator with optional custom categories and quote anchor option.

        Args:
            categories: Optional sequence of (category_id, intent_phrase) pairs.
                        Defaults to DEFAULT_RESEARCH_CATEGORIES.
            quote_subject_anchor: Default whether to quote the subject theme in generated queries.
        """
        raw_cats = DEFAULT_RESEARCH_CATEGORIES if categories is None else categories
        self.categories = tuple(raw_cats)
        self.quote_subject_anchor = quote_subject_anchor

    def generate_queries(
        self,
        config: ResearchDomainConfig,
        max_queries: int = DEFAULT_MAX_RESEARCH_QUERIES,
        *,
        quote_subject_anchor: Optional[bool] = None,
    ) -> GeneratedResearchQueries:
        """Decompose a ResearchDomainConfig into a bounded, deduplicated list of research queries.

        Workflow:
            1. Validates that config is an instance of ResearchDomainConfig and max_queries >= 1.
            2. Iterates over configured domain themes and generic research intent categories.
            3. Synthesizes natural search queries without repeating tokens.
            4. Deduplicates queries in a case-insensitive, order-preserving manner.
            5. Bounds the result to max_queries.

        Args:
            config: ResearchDomainConfig instance defining domain name and innovation themes.
            max_queries: Maximum number of search queries to generate (must be >= 1).
            quote_subject_anchor: Optional override to quote the theme anchor in queries.

        Returns:
            GeneratedResearchQueries: Structured immutable collection of queries and metadata.

        Raises:
            ValueError: If config is invalid or max_queries < 1.
        """
        if not isinstance(config, ResearchDomainConfig):
            raise ValueError("config must be an instance of ResearchDomainConfig.")
        if isinstance(max_queries, bool) or not isinstance(max_queries, int) or max_queries < 1:
            raise ValueError("max_queries must be an integer >= 1.")

        should_quote = (
            self.quote_subject_anchor
            if quote_subject_anchor is None
            else bool(quote_subject_anchor)
        )

        generated_queries: list[str] = []
        query_items: list[ResearchQueryItem] = []
        seen_keys: set[str] = set()

        for theme in config.themes:
            for category_id, intent_phrase in self.categories:
                if len(generated_queries) >= max_queries:
                    break

                cand_query = build_research_query(
                    theme=theme,
                    intent_phrase=intent_phrase,
                    quote_subject_anchor=should_quote,
                )
                key = cand_query.strip().lower()

                if not key or key in seen_keys:
                    continue

                seen_keys.add(key)
                generated_queries.append(cand_query)
                query_items.append(
                    ResearchQueryItem(
                        query=cand_query,
                        category=category_id,
                        theme=theme,
                    )
                )

            if len(generated_queries) >= max_queries:
                break

        return GeneratedResearchQueries(
            domain_name=config.domain_name,
            queries=tuple(generated_queries),
            items=tuple(query_items),
        )

    def generate_google_news_queries(
        self,
        config: ResearchDomainConfig,
        max_queries: int = DEFAULT_MAX_RESEARCH_QUERIES,
    ) -> GeneratedResearchQueries:
        """Generate market research queries with quoted subject anchors for Google News RSS."""
        return self.generate_queries(
            config=config,
            max_queries=max_queries,
            quote_subject_anchor=True,
        )


def generate_research_queries(
    config: ResearchDomainConfig,
    max_queries: int = DEFAULT_MAX_RESEARCH_QUERIES,
    categories: Optional[Sequence[tuple[str, str]]] = None,
) -> GeneratedResearchQueries:
    """Convenience function to generate market research queries from a ResearchDomainConfig.

    Args:
        config: ResearchDomainConfig instance.
        max_queries: Maximum number of search queries to return.
        categories: Optional custom category pairs override.

    Returns:
        GeneratedResearchQueries: Structured collection of queries.
    """
    generator = ResearchQueryGenerator(categories=categories)
    return generator.generate_queries(config=config, max_queries=max_queries)


def generate_google_news_queries(
    config: ResearchDomainConfig,
    max_queries: int = DEFAULT_MAX_RESEARCH_QUERIES,
    categories: Optional[Sequence[tuple[str, str]]] = None,
) -> GeneratedResearchQueries:
    """Convenience function to generate Google News anchored queries from a ResearchDomainConfig.

    Args:
        config: ResearchDomainConfig instance.
        max_queries: Maximum number of search queries to return.
        categories: Optional custom category pairs override.

    Returns:
        GeneratedResearchQueries: Structured collection of queries with quoted theme anchors.
    """
    generator = ResearchQueryGenerator(categories=categories, quote_subject_anchor=True)
    return generator.generate_queries(config=config, max_queries=max_queries)
