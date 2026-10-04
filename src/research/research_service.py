"""Research orchestration service coordinating end-to-end patent discovery and persistence.

Connects research run lifecycle management (ResearchRunService) with intelligent
patent discovery strategy (InPassDiscoveryStrategy) and InPASS ingestion.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.common.research_runs import ResearchRunService
from src.patents.discovery_strategy import (
    InPassDiscoveryResult,
    InPassDiscoveryStrategy,
)
from src.patents.inpass_client import InPassClient

logger = logging.getLogger(__name__)


class ResearchServiceError(Exception):
    """Base exception for research service operations."""
    pass


class PatentResearchExecutionError(ResearchServiceError):
    """Raised when patent research run execution fails and error raising is requested."""

    def __init__(self, message: str, result: Optional["PatentResearchResult"] = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class PatentResearchResult:
    """Consolidated telemetry and summary for an orchestrated patent research run."""

    run_id: str
    theme: str
    generated_queries: Sequence[str]
    executed_queries: Sequence[str]
    discovered_count: int
    ingested_count: int
    inserted_count: int
    existing_count: int
    linked_count: int
    final_run_status: str
    error: Optional[str] = None
    discovery_result: Optional[InPassDiscoveryResult] = None

    @property
    def is_success(self) -> bool:
        """True if the research run completed successfully."""
        return self.final_run_status == "completed"

    @property
    def status(self) -> str:
        """Alias for final_run_status."""
        return self.final_run_status

    @property
    def total_discovered(self) -> int:
        """Alias for discovered_count."""
        return self.discovered_count

    @property
    def total_ingested(self) -> int:
        """Alias for ingested_count."""
        return self.ingested_count

    @property
    def total_inserted(self) -> int:
        """Alias for inserted_count."""
        return self.inserted_count

    @property
    def total_existing(self) -> int:
        """Alias for existing_count."""
        return self.existing_count

    @property
    def total_linked(self) -> int:
        """Alias for linked_count."""
        return self.linked_count

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to dictionary format."""
        return {
            "run_id": self.run_id,
            "theme": self.theme,
            "generated_queries": list(self.generated_queries),
            "executed_queries": list(self.executed_queries),
            "discovered_count": self.discovered_count,
            "ingested_count": self.ingested_count,
            "inserted_count": self.inserted_count,
            "existing_count": self.existing_count,
            "linked_count": self.linked_count,
            "final_run_status": self.final_run_status,
            "error": self.error,
            "discovery_result": self.discovery_result.to_dict() if self.discovery_result else None,
        }

    def __getitem__(self, item: str) -> Any:
        return self.to_dict()[item]


class ResearchService:
    """Application-level orchestration service for executing end-to-end patent research runs."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        run_service: Optional[ResearchRunService] = None,
        discovery_strategy: Optional[InPassDiscoveryStrategy] = None,
    ) -> None:
        """Initialize the research service.

        Args:
            db_path: Path to SQLite database. Defaults to DATABASE_PATH.
            run_service: Optional ResearchRunService instance.
            discovery_strategy: Optional InPassDiscoveryStrategy instance.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH
        self.run_service = run_service or ResearchRunService(db_path=self.db_path)
        self.discovery_strategy = discovery_strategy or InPassDiscoveryStrategy()

    def run_patent_research(
        self,
        theme: str,
        max_queries: int = 4,
        max_results_per_query: int = 3,
        on_captcha_required: Optional[Callable[[str], None]] = None,
        run_name: Optional[str] = None,
        client: Optional[InPassClient] = None,
        raise_on_error: bool = False,
        captcha_solver: Optional[Callable[[str], str]] = None,
    ) -> PatentResearchResult:
        """Execute a complete patent research run for a given theme.

        Lifecycle:
        1. Validates inputs.
        2. Generates targeted InPASS search queries.
        3. Creates research run in 'initialized' state via ResearchRunService.
        4. Transitions research run to 'running'.
        5. Executes InPassDiscoveryStrategy across queries with human CAPTCHA checkpoint.
        6. On success: transitions research run to 'completed'.
        7. On failure/timeout: transitions research run to 'failed' and captures error.
        8. Returns structured PatentResearchResult with run-level telemetry.

        Args:
            theme: Broad research theme (e.g. "WATER").
            max_queries: Maximum number of targeted queries to generate and execute (must be >= 1).
            max_results_per_query: Maximum patent details to retrieve per query (must be >= 1).
            on_captcha_required: Optional callback invoked when CAPTCHA entry is required.
            run_name: Optional custom run name. Defaults to 'Patent Research: <theme>'.
            client: Optional InPassClient instance override.
            raise_on_error: If True, re-raises discovery/execution exceptions after marking run failed.
            captcha_solver: Optional callback accepting (image_path: str) and returning (captcha_text: str).

        Returns:
            PatentResearchResult: Consolidated telemetry and final execution status.

        Raises:
            ValueError: If theme is empty/invalid or limits are < 1.
            PatentResearchExecutionError: If execution fails and raise_on_error is True.
        """
        if not isinstance(theme, str) or not theme.strip():
            raise ValueError("Research theme must be a non-empty string.")
        if max_queries < 1:
            raise ValueError("max_queries must be at least 1.")
        if max_results_per_query < 1:
            raise ValueError("max_results_per_query must be at least 1.")

        clean_theme = theme.strip()

        # 1. Generate targeted search queries
        generated_queries = self.discovery_strategy.generate_targeted_queries(
            theme=clean_theme,
            max_queries=max_queries,
        )
        logger.info(
            "ResearchService generated %d queries for theme '%s': %s",
            len(generated_queries),
            clean_theme,
            generated_queries,
        )

        # 2. Create research run in initialized state
        active_run_name = run_name.strip() if run_name and run_name.strip() else f"Patent Research: {clean_theme}"
        initial_metadata = {
            "theme": clean_theme,
            "max_queries": max_queries,
            "max_results_per_query": max_results_per_query,
            "generated_queries": list(generated_queries),
            "strategy": "InPassDiscoveryStrategy",
        }
        run_id = self.run_service.create_run(
            run_name=active_run_name,
            query=clean_theme,
            metadata=initial_metadata,
        )

        # 3. Transition research run to running
        self.run_service.start_run(run_id)

        # 4. Execute multi-query discovery with error handling and run lifecycle management
        try:
            discovery_result = self.discovery_strategy.discover_for_run(
                run_id=run_id,
                theme=clean_theme,
                max_queries=max_queries,
                max_results_per_query=max_results_per_query,
                on_captcha_required=on_captcha_required,
                client=client,
                captcha_solver=captcha_solver,
            )

            # 5. Complete research run on success
            self.run_service.complete_run(run_id)

            return PatentResearchResult(
                run_id=run_id,
                theme=clean_theme,
                generated_queries=tuple(discovery_result.generated_queries),
                executed_queries=tuple(discovery_result.executed_queries),
                discovered_count=discovery_result.total_discovered,
                ingested_count=discovery_result.total_ingested,
                inserted_count=discovery_result.total_inserted,
                existing_count=discovery_result.total_existing,
                linked_count=discovery_result.total_linked,
                final_run_status="completed",
                error=None,
                discovery_result=discovery_result,
            )

        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            logger.error(
                "Patent research run '%s' failed for theme '%s': %s",
                run_id,
                clean_theme,
                error_message,
            )

            # Transition run to failed
            try:
                self.run_service.fail_run(run_id=run_id, error_message=error_message)
            except Exception as fail_err:
                logger.error("Failed to mark run '%s' as failed in database: %s", run_id, fail_err)

            # Inspect database to capture any partial links if persistence succeeded before failure
            partial_linked = 0
            try:
                with get_db(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM run_patents WHERE run_id = ?;", (run_id,))
                    row = cursor.fetchone()
                    if row:
                        partial_linked = row[0]
            except Exception:
                pass

            result = PatentResearchResult(
                run_id=run_id,
                theme=clean_theme,
                generated_queries=tuple(generated_queries),
                executed_queries=(),
                discovered_count=0,
                ingested_count=0,
                inserted_count=0,
                existing_count=0,
                linked_count=partial_linked,
                final_run_status="failed",
                error=error_message,
                discovery_result=None,
            )

            if raise_on_error:
                raise PatentResearchExecutionError(
                    f"Patent research run '{run_id}' failed: {error_message}",
                    result=result,
                ) from exc

            return result
