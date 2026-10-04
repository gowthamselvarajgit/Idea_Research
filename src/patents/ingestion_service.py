"""End-to-end patent ingestion service connecting EPO discovery and SQLite persistence.

Coordinates the discover -> parse -> persist workflow by orchestrating
EPODiscoveryService and PatentRepository for a specified research run.
"""

from dataclasses import asdict, dataclass
import logging
from typing import Any, Optional

from src.patents.discovery_service import DiscoveryStats, EPODiscoveryError, EPODiscoveryService
from src.patents.models import PatentRecord
from src.patents.repository import PatentRepository

logger = logging.getLogger(__name__)


class EPOIngestionError(Exception):
    """Base exception for patent ingestion failures."""
    pass


class EPOIngestionDiscoveryError(EPOIngestionError):
    """Raised when patent discovery fails during ingestion."""
    pass


class EPOIngestionRepositoryError(EPOIngestionError):
    """Raised when persisting patents fails during ingestion."""
    pass


@dataclass(frozen=True)
class IngestionResult:
    """Consolidated execution telemetry and statistics for an ingestion run."""

    query: str
    run_id: str
    discovered: int
    inserted: int
    existing: int
    linked: int
    discovery_stats: Optional[DiscoveryStats] = None

    @property
    def number_discovered(self) -> int:
        return self.discovered

    @property
    def number_inserted(self) -> int:
        return self.inserted

    @property
    def number_existing(self) -> int:
        return self.existing

    @property
    def number_linked(self) -> int:
        return self.linked

    @property
    def discovery_statistics(self) -> Optional[dict[str, Any]]:
        return self.discovery_stats.to_dict() if self.discovery_stats else None

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to a dictionary representation."""
        return {
            "query": self.query,
            "run_id": self.run_id,
            "discovered": self.discovered,
            "inserted": self.inserted,
            "existing": self.existing,
            "linked": self.linked,
            "number_discovered": self.discovered,
            "number_inserted": self.inserted,
            "number_existing": self.existing,
            "number_linked": self.linked,
            "discovery_stats": self.discovery_stats.to_dict() if self.discovery_stats else None,
            "discovery_statistics": self.discovery_stats.to_dict() if self.discovery_stats else None,
        }

    def __getitem__(self, item: str) -> Any:
        return self.to_dict()[item]


class EPOIngestionService:
    """Orchestrates end-to-end patent discovery and persistence for a research run."""

    def __init__(
        self,
        discovery_service: Optional[EPODiscoveryService] = None,
        repository: Optional[PatentRepository] = None,
    ) -> None:
        """Initialize the ingestion service with discovery and repository dependencies.

        Args:
            discovery_service: EPODiscoveryService instance. Defaults to a new instance.
            repository: PatentRepository instance. Defaults to a new instance.
        """
        self.discovery_service = discovery_service or EPODiscoveryService()
        self.repository = repository or PatentRepository()

    def ingest_run(
        self,
        run_id: str,
        query: str,
        max_results: int = 25,
    ) -> IngestionResult:
        """Execute discover -> parse -> persist pipeline for a research run.

        1. Calls EPODiscoveryService to search and parse candidate patents.
        2. Persists and links the discovered patents to run_id via PatentRepository.
        3. Returns combined telemetry including discovery and persistence statistics.

        Args:
            run_id: Unique research run identifier.
            query: CQL patent search query.
            max_results: Maximum patents to discover (default: 25).

        Returns:
            IngestionResult: Combined discovery and persistence metrics.

        Raises:
            ValueError: If run_id is empty.
            EPOIngestionDiscoveryError: If discovery fails.
            EPOIngestionRepositoryError: If database persistence fails.
        """
        if not run_id or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")

        clean_run_id = run_id.strip()
        clean_query = query.strip() if query else ""

        # 1. Discover patents via EPODiscoveryService
        try:
            discovered_patents: list[PatentRecord] = self.discovery_service.discover(
                query=clean_query,
                max_results=max_results,
            )
            discovery_stats = self.discovery_service.last_stats
        except (EPODiscoveryError, Exception) as err:
            logger.error("Patent discovery failed for run '%s' with query '%s': %s", clean_run_id, clean_query, err)
            raise EPOIngestionDiscoveryError(f"Patent discovery failed: {err}") from err

        # 2. Persist patents and link to run via PatentRepository
        try:
            save_stats = self.repository.save_patents_for_run(
                run_id=clean_run_id,
                patents=discovered_patents,
            )
        except Exception as err:
            logger.error("Patent persistence failed for run '%s': %s", clean_run_id, err)
            raise EPOIngestionRepositoryError(f"Patent persistence failed: {err}") from err

        # 3. Combine telemetry
        return IngestionResult(
            query=clean_query,
            run_id=clean_run_id,
            discovered=len(discovered_patents),
            inserted=save_stats.get("inserted", 0),
            existing=save_stats.get("existing", 0),
            linked=save_stats.get("linked", 0),
            discovery_stats=discovery_stats,
        )
