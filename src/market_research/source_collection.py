"""Component for batch collecting web research sources from known URLs.

Coordinates retrieval of multiple web sources using WebSourceClient, captures
structured error diagnostics for failed URLs, and preserves deterministic result ordering.
"""

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Final, Iterable, Optional, Sequence

from src.market_research.source_models import WebResearchSource
from src.market_research.web_source_client import WebSourceClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceCollectionFailure:
    """Immutable record of a failed URL retrieval attempt.

    Attributes:
        url: The URL that failed retrieval.
        error_type: Class name of the error encountered (e.g. WebSourceHTTPError).
        error_message: Descriptive explanation of the failure.
    """

    url: str
    error_type: str
    error_message: str

    def to_dict(self) -> dict[str, str]:
        """Serialize failure to a standard dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class SourceCollectionResult:
    """Immutable result of a batch web source collection operation.

    Attributes:
        sources: Tuple of successfully retrieved and validated WebResearchSource records.
        failures: Tuple of structured failure records for URLs that could not be retrieved.
    """

    sources: tuple[WebResearchSource, ...] = field(default_factory=tuple)
    failures: tuple[SourceCollectionFailure, ...] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        """Number of successfully collected sources."""
        return len(self.sources)

    @property
    def failure_count(self) -> int:
        """Number of failed URLs."""
        return len(self.failures)

    @property
    def total_count(self) -> int:
        """Total number of URLs processed."""
        return len(self.sources) + len(self.failures)

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a standard dictionary."""
        return {
            "sources": [s.to_dict() for s in self.sources],
            "failures": [f.to_dict() for f in self.failures],
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
        }


class WebSourceCollector:
    """Orchestrates multi-URL collection with error tolerance and deduplication."""

    def __init__(self, client: Optional[WebSourceClient] = None) -> None:
        """Initialize the collector with an optional custom or mocked WebSourceClient.

        Args:
            client: WebSourceClient instance. Defaults to a standard WebSourceClient.
        """
        self.client = client if client is not None else WebSourceClient()

    def collect_sources(
        self,
        urls: Iterable[str],
        source_type: str = "other",
        *,
        deduplicate: bool = True,
    ) -> SourceCollectionResult:
        """Retrieve web sources for a sequence of URLs, continuing past individual failures.

        Args:
            urls: Iterable of URL strings to retrieve.
            source_type: Controlled classification to forward to WebSourceClient.
            deduplicate: If True, skips redundant fetches of identical normalized URLs.

        Returns:
            SourceCollectionResult: Containing tuples of successful sources and structured failures.
        """
        if urls is None:
            return SourceCollectionResult()

        sources: list[WebResearchSource] = []
        failures: list[SourceCollectionFailure] = []
        seen_urls: set[str] = set()

        for raw_url in urls:
            if not isinstance(raw_url, str):
                failures.append(
                    SourceCollectionFailure(
                        url=str(raw_url),
                        error_type="TypeError",
                        error_message=f"URL must be a string, got {type(raw_url).__name__}.",
                    )
                )
                continue

            clean_url = raw_url.strip()
            if not clean_url:
                failures.append(
                    SourceCollectionFailure(
                        url=raw_url,
                        error_type="ValueError",
                        error_message="URL cannot be empty or whitespace.",
                    )
                )
                continue

            if deduplicate and clean_url in seen_urls:
                logger.debug("Skipping duplicate URL fetch for '%s'.", clean_url)
                continue

            seen_urls.add(clean_url)

            try:
                source = self.client.fetch_source(url=clean_url, source_type=source_type)
                sources.append(source)
            except Exception as exc:
                logger.warning("Failed to collect web source from '%s': %s", clean_url, exc)
                failures.append(
                    SourceCollectionFailure(
                        url=clean_url,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )

        return SourceCollectionResult(
            sources=tuple(sources),
            failures=tuple(failures),
        )


def collect_sources(
    urls: Iterable[str],
    source_type: str = "other",
    client: Optional[WebSourceClient] = None,
    *,
    deduplicate: bool = True,
) -> SourceCollectionResult:
    """Convenience functional wrapper for collecting sources from multiple URLs.

    Args:
        urls: Iterable of URL strings.
        source_type: Source classification to forward to the client.
        client: Optional injected WebSourceClient.
        deduplicate: If True, skips duplicate URLs.

    Returns:
        SourceCollectionResult: Successful sources and failure diagnostics.
    """
    collector = WebSourceCollector(client=client)
    return collector.collect_sources(
        urls=urls,
        source_type=source_type,
        deduplicate=deduplicate,
    )
