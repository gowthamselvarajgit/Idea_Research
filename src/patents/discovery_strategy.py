"""Intelligent patent discovery strategy for targeted InPASS search generation and execution.

Provides modular, deterministic query generation to decompose broad research themes
into bounded, high-relevance technical search concepts, coordinating execution through
InPassIngestionService while keeping CAPTCHA human-in-the-loop.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
import re
from typing import Any, Callable, Optional, Sequence

from src.patents.inpass_client import InPassClient, InPassSearchConfig
from src.patents.inpass_ingestion_service import InPassIngestionResult, InPassIngestionService

logger = logging.getLogger(__name__)

# Standard technical dimensions commonly associated with industrial innovation and patent claims
DEFAULT_TECHNICAL_FACETS: tuple[str, ...] = (
    "MONITORING",
    "QUALITY",
    "CONTAMINATION",
    "PURIFICATION",
    "LEAKAGE",
    "CONSERVATION",
    "INFRASTRUCTURE",
    "SAFETY",
    "TREATMENT",
    "DETECTION",
    "MANAGEMENT",
    "RECOVERY",
)


class BasePatentQueryGenerator(ABC):
    """Abstract contract for decomposing research themes into targeted patent search queries."""

    @abstractmethod
    def generate_queries(self, theme: str, max_queries: int = 5) -> list[str]:
        """Generate a bounded, deduplicated list of search queries for a research theme.

        Args:
            theme: Broad research theme or topic.
            max_queries: Maximum number of search queries to generate.

        Returns:
            list[str]: Bounded list of targeted search query strings.

        Raises:
            ValueError: If theme is empty, whitespace, or invalid.
        """
        pass


class DeterministicPatentQueryGenerator(BasePatentQueryGenerator):
    """Deterministic rule-based query generator using domain-agnostic technical facets.

    Splits and analyzes the input theme, prevents near-duplicate terms, and combines the
    theme with targeted industrial facets in a deterministic, repeatable order.
    """

    def __init__(self, facets: Optional[Sequence[str]] = None) -> None:
        """Initialize the query generator.

        Args:
            facets: Optional sequence of technical facet keywords to use for expansion.
                    Defaults to DEFAULT_TECHNICAL_FACETS.
        """
        raw_facets = DEFAULT_TECHNICAL_FACETS if facets is None else facets
        self.facets = tuple(f.strip().upper() for f in raw_facets if f.strip())

    def generate_queries(self, theme: str, max_queries: int = 5) -> list[str]:
        """Decompose a research theme into a bounded set of targeted patent search queries.

        Rules:
        1. Validates that theme is a non-empty string.
        2. Normalizes whitespace and uppercase characters.
        3. If theme contains multiple words, includes the theme itself as the primary query.
        4. Expands the theme with technical facets, skipping facets already present in the theme.
        5. Performs case-insensitive and token-set deduplication.
        6. Limits the result to max_queries in deterministic order.

        Args:
            theme: Broad research theme (e.g. "WATER", "solar energy", "battery storage").
            max_queries: Maximum queries to return (must be >= 1).

        Returns:
            list[str]: Bounded list of targeted search query strings.

        Raises:
            ValueError: If theme is empty or max_queries < 1.
        """
        if not isinstance(theme, str) or not theme.strip():
            raise ValueError("Research theme must be a non-empty string.")
        if max_queries < 1:
            raise ValueError("max_queries must be at least 1.")

        clean_theme = " ".join(theme.strip().upper().split())
        theme_tokens = set(clean_theme.split())

        generated: list[str] = []
        seen_token_sets: list[set[str]] = []

        def add_query(cand: str) -> None:
            norm_cand = " ".join(cand.strip().upper().split())
            cand_tokens = set(norm_cand.split())
            if not norm_cand or cand_tokens in seen_token_sets:
                return
            seen_token_sets.append(cand_tokens)
            generated.append(norm_cand)

        # For multi-word specific themes, preserve the raw theme as query #1
        if len(theme_tokens) > 1:
            add_query(clean_theme)

        # Generate targeted technical facets
        for facet in self.facets:
            if len(generated) >= max_queries:
                break

            # Skip facet if it's already an exact word in the theme
            if facet in theme_tokens:
                continue

            candidate = f"{clean_theme} {facet}"
            add_query(candidate)

        # Fallback: if single-word theme and no facets added (e.g. facet list empty), use theme
        if not generated:
            add_query(clean_theme)

        return generated[:max_queries]


@dataclass(frozen=True)
class InPassDiscoveryResult:
    """Consolidated telemetry and summary for an InPASS multi-query discovery execution."""

    run_id: str
    theme: str
    generated_queries: Sequence[str]
    executed_queries: Sequence[str]
    total_discovered: int
    total_ingested: int
    total_inserted: int
    total_existing: int
    total_linked: int
    ingestion_results: Sequence[InPassIngestionResult] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert the discovery result to dictionary format."""
        return {
            "run_id": self.run_id,
            "theme": self.theme,
            "generated_queries": list(self.generated_queries),
            "executed_queries": list(self.executed_queries),
            "total_discovered": self.total_discovered,
            "total_ingested": self.total_ingested,
            "total_inserted": self.total_inserted,
            "total_existing": self.total_existing,
            "total_linked": self.total_linked,
            "ingestion_results": [r.to_dict() for r in self.ingestion_results],
        }

    def __getitem__(self, item: str) -> Any:
        return self.to_dict()[item]


class InPassDiscoveryStrategy:
    """Coordinates intelligent patent discovery across generated InPASS queries for a research run."""

    def __init__(
        self,
        query_generator: Optional[BasePatentQueryGenerator] = None,
        ingestion_service: Optional[InPassIngestionService] = None,
        client: Optional[InPassClient] = None,
    ) -> None:
        """Initialize the discovery strategy.

        Args:
            query_generator: BasePatentQueryGenerator instance. Defaults to DeterministicPatentQueryGenerator.
            ingestion_service: InPassIngestionService instance. Defaults to a new InPassIngestionService.
            client: Optional InPassClient instance passed through to the ingestion service.
        """
        self.query_generator = query_generator or DeterministicPatentQueryGenerator()
        self.ingestion_service = ingestion_service or InPassIngestionService(client=client)

    def generate_targeted_queries(self, theme: str, max_queries: int = 5) -> list[str]:
        """Expose direct query generation without running browser automation.

        Args:
            theme: Broad research theme.
            max_queries: Maximum number of search queries to generate.

        Returns:
            list[str]: Targeted patent queries.
        """
        return self.query_generator.generate_queries(theme=theme, max_queries=max_queries)

    def discover_for_run(
        self,
        run_id: str,
        theme: str,
        max_queries: int = 4,
        max_results_per_query: int = 3,
        on_captcha_required: Optional[Callable[[str], None]] = None,
        client: Optional[InPassClient] = None,
        captcha_solver: Optional[Callable[[str], str]] = None,
    ) -> InPassDiscoveryResult:
        """Execute a multi-query InPASS discovery campaign for a research run.

        1. Decomposes the broad research theme into a bounded set of targeted queries.
        2. Iterates over each query and executes search ingestion via InPassIngestionService.
        3. Preserves human-in-the-loop CAPTCHA checkpoints across query executions.
        4. Aggregates telemetry across all executed queries.

        Args:
            run_id: Unique research run identifier.
            theme: Broad research theme (e.g. "WATER").
            max_queries: Maximum number of targeted queries to execute (default: 4).
            max_results_per_query: Maximum patent details to ingest per query (default: 3).
            on_captcha_required: Optional notification callback for CAPTCHA entry.
            client: Optional InPassClient override for this execution.
            captcha_solver: Optional callback to solve CAPTCHA challenges.

        Returns:
            InPassDiscoveryResult: Aggregated discovery and persistence metrics.

        Raises:
            ValueError: If run_id or theme is empty, or limits < 1.
        """
        if not run_id or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")

        queries = self.generate_targeted_queries(theme=theme, max_queries=max_queries)
        logger.info("Generated %d targeted queries for theme '%s': %s", len(queries), theme, queries)

        executed: list[str] = []
        ingestion_results: list[InPassIngestionResult] = []

        total_discovered = 0
        total_ingested = 0
        total_inserted = 0
        total_existing = 0
        total_linked = 0

        for q in queries:
            logger.info("Executing InPASS discovery query: '%s' for run '%s'", q, run_id)
            result = self.ingestion_service.ingest_search_run(
                run_id=run_id,
                search_config_or_query=InPassSearchConfig(keyword=q, field_type="TI"),
                max_results=max_results_per_query,
                on_captcha_required=on_captcha_required,
                client=client,
                captcha_solver=captcha_solver,
            )

            executed.append(q)
            ingestion_results.append(result)

            total_discovered += result.discovered
            total_ingested += result.ingested
            total_inserted += result.inserted
            total_existing += result.existing
            total_linked += result.linked

        return InPassDiscoveryResult(
            run_id=run_id,
            theme=theme.strip(),
            generated_queries=tuple(queries),
            executed_queries=tuple(executed),
            total_discovered=total_discovered,
            total_ingested=total_ingested,
            total_inserted=total_inserted,
            total_existing=total_existing,
            total_linked=total_linked,
            ingestion_results=tuple(ingestion_results),
        )
