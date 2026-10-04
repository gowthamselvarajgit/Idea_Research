"""EPO patent discovery service connecting search client, response parser, and deduplication.

Coordinates querying EPO OPS, parsing raw XML responses into canonical PatentRecord
models, performing in-memory publication deduplication, and gathering telemetry.
"""

from dataclasses import asdict, dataclass
import logging
from typing import Optional
import xml.etree.ElementTree as ET

from src.patents.base_client import PatentClientError
from src.patents.epo_client import EPOClient, EPOClientError
from src.patents.epo_parser import EPOParserError, _local_tag, parse_epo_search_response
from src.patents.models import PatentRecord

logger = logging.getLogger(__name__)


class EPODiscoveryError(PatentClientError):
    """Raised when an unrecoverable discovery failure occurs."""
    pass


@dataclass(frozen=True)
class DiscoveryStats:
    """Telemetry and execution metrics for a discovery attempt."""

    query: str
    requested_count: int
    raw_results_parsed: int
    valid_patents_returned: int
    duplicates_removed: int
    malformed_records_skipped: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class EPODiscoveryService:
    """Orchestrates patent discovery via EPO OPS without database dependencies."""

    def __init__(self, client: Optional[EPOClient] = None) -> None:
        """Initialize the discovery service.

        Args:
            client: EPOClient instance. Defaults to a new EPOClient.
        """
        self.client = client or EPOClient()
        self.last_stats: Optional[DiscoveryStats] = None

    def discover(
        self,
        query: str,
        max_results: int = 10,
        start_index: int = 1,
    ) -> list[PatentRecord]:
        """Discover and parse patents from EPO OPS for a given CQL query.

        Performs search dispatch, XML parsing, and in-memory deduplication by
        normalized publication number.

        Args:
            query: CQL search query string.
            max_results: Maximum records to retrieve.
            start_index: 1-indexed pagination start offset.

        Returns:
            list[PatentRecord]: Deduplicated list of valid patent records.

        Raises:
            EPODiscoveryError: On client network, auth, or parser failures.
        """
        if not query or not query.strip():
            self.last_stats = DiscoveryStats(
                query="",
                requested_count=max_results,
                raw_results_parsed=0,
                valid_patents_returned=0,
                duplicates_removed=0,
                malformed_records_skipped=0,
            )
            return []

        # 1. Dispatch search request via EPOClient
        try:
            raw_xml = self.client.search(
                query=query.strip(),
                max_results=max_results,
                start_index=start_index,
            )
        except EPOClientError as err:
            raise EPODiscoveryError(f"EPO search request failed: {err}") from err

        if not raw_xml or not raw_xml.strip():
            self.last_stats = DiscoveryStats(
                query=query.strip(),
                requested_count=max_results,
                raw_results_parsed=0,
                valid_patents_returned=0,
                duplicates_removed=0,
                malformed_records_skipped=0,
            )
            return []

        # 2. Count candidate exchange-documents in raw XML to track skipped/malformed records
        malformed_skipped = 0
        try:
            root = ET.fromstring(raw_xml.strip())
            total_doc_elements = sum(
                1 for e in root.iter() if _local_tag(e) == "exchange-document"
            )
        except ET.ParseError as err:
            raise EPODiscoveryError(f"EPO XML response parsing failed: {err}") from err

        # 3. Parse XML payload into PatentRecord instances
        try:
            parsed_records = parse_epo_search_response(raw_xml)
        except EPOParserError as err:
            raise EPODiscoveryError(f"EPO response parsing failed: {err}") from err

        malformed_skipped = max(0, total_doc_elements - len(parsed_records))

        # 4. In-Memory Deduplication: deduplicate by normalized patent_number preserving first occurrence
        seen_numbers: set[str] = set()
        deduped_records: list[PatentRecord] = []
        duplicates_removed = 0

        for record in parsed_records:
            if record.patent_number in seen_numbers:
                duplicates_removed += 1
                logger.debug("Duplicate patent publication filtered out: %s", record.patent_number)
            else:
                seen_numbers.add(record.patent_number)
                deduped_records.append(record)

        # 5. Record discovery statistics
        self.last_stats = DiscoveryStats(
            query=query.strip(),
            requested_count=max_results,
            raw_results_parsed=len(parsed_records),
            valid_patents_returned=len(deduped_records),
            duplicates_removed=duplicates_removed,
            malformed_records_skipped=malformed_skipped,
        )

        return deduped_records

    # Alias for search contract
    search = discover
