"""InPASS patent ingestion service connecting browser search and SQLite persistence.

Coordinates executing an InPASS search, pausing for the human-in-the-loop CAPTCHA
checkpoint, reading search result rows, retrieving detailed patent metadata, parsing
into InPassPatentRecord, and persisting patents into the research_run via PatentRepository.
"""

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Callable, Optional, Sequence

from src.patents.inpass_client import InPassClient, InPassClientError, InPassSearchConfig
from src.patents.models import InPassPatentRecord, PatentRecord
from src.patents.repository import PatentRepository

logger = logging.getLogger(__name__)


class InPassIngestionError(Exception):
    """Base exception for InPASS patent ingestion failures."""
    pass


class InPassIngestionSearchError(InPassIngestionError):
    """Raised when search execution or details retrieval fails."""
    pass


class InPassIngestionPersistenceError(InPassIngestionError):
    """Raised when database persistence or junction linking fails."""
    pass


@dataclass(frozen=True)
class InPassIngestionResult:
    """Consolidated telemetry and summary for an InPASS ingestion execution."""

    run_id: str
    query: str
    discovered: int
    ingested: int
    inserted: int
    existing: int
    linked: int
    records: Sequence[InPassPatentRecord] = field(default_factory=tuple)

    @property
    def number_discovered(self) -> int:
        return self.discovered

    @property
    def number_ingested(self) -> int:
        return self.ingested

    @property
    def number_inserted(self) -> int:
        return self.inserted

    @property
    def number_existing(self) -> int:
        return self.existing

    @property
    def number_linked(self) -> int:
        return self.linked

    def to_dict(self) -> dict[str, Any]:
        """Convert the ingestion result to dictionary format."""
        return {
            "run_id": self.run_id,
            "query": self.query,
            "discovered": self.discovered,
            "ingested": self.ingested,
            "inserted": self.inserted,
            "existing": self.existing,
            "linked": self.linked,
            "number_discovered": self.discovered,
            "number_ingested": self.ingested,
            "number_inserted": self.inserted,
            "number_existing": self.existing,
            "number_linked": self.linked,
            "records": [r.to_dict() for r in self.records],
        }

    def __getitem__(self, item: str) -> Any:
        return self.to_dict()[item]


class InPassIngestionService:
    """Orchestrates InPASS patent discovery and persistence for a research run."""

    def __init__(
        self,
        client: Optional[InPassClient] = None,
        repository: Optional[PatentRepository] = None,
    ) -> None:
        """Initialize the ingestion service.

        Args:
            client: Optional InPassClient instance. If not provided, a client will be
                    instantiated on demand during search ingestion.
            repository: Optional PatentRepository instance. Defaults to a new PatentRepository.
        """
        self.client = client
        self.repository = repository or PatentRepository()

    def ingest_search_run(
        self,
        run_id: str,
        search_config_or_query: InPassSearchConfig | str,
        max_results: int = 5,
        application_numbers: Optional[Sequence[str]] = None,
        on_captcha_required: Optional[Callable[[str], None]] = None,
        client: Optional[InPassClient] = None,
        captcha_solver: Optional[Callable[[str], str]] = None,
    ) -> InPassIngestionResult:
        """Execute an InPASS search, pause for CAPTCHA, fetch details, and persist to run.

        Workflow:
        1. Open InPASS search page and configure search criteria.
        2. Wait at the human CAPTCHA checkpoint until results page is detected.
        3. Read candidate patent rows from the results page.
        4. Select target applications (either explicit list or top `max_results`).
        5. Retrieve full PatentDetails HTML for each selected application and parse.
        6. Persist candidate patents into the database via PatentRepository.
        7. Associate all persisted patents with `run_id` in the `run_patents` table.

        Args:
            run_id: Unique research run identifier.
            search_config_or_query: Search criteria (keyword string or InPassSearchConfig).
            max_results: Maximum patents to retrieve and persist (default: 5).
            application_numbers: Optional explicit list of application numbers to ingest.
            on_captcha_required: Optional callback invoked when CAPTCHA entry is needed.
            client: Optional client override for this execution.
            captcha_solver: Optional callback to solve CAPTCHA and receive image path.

        Returns:
            InPassIngestionResult: Summary metrics and parsed InPassPatentRecord instances.

        Raises:
            ValueError: If run_id is empty or max_results < 1.
            InPassIngestionSearchError: If search or details extraction fails.
            InPassIngestionPersistenceError: If database persistence fails.
        """
        if not run_id or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        if max_results < 1:
            raise ValueError("max_results must be at least 1.")

        clean_run_id = run_id.strip()

        if isinstance(search_config_or_query, InPassSearchConfig):
            query_str = search_config_or_query.keyword
            cfg = search_config_or_query
        else:
            query_str = str(search_config_or_query).strip()
            cfg = InPassSearchConfig(keyword=query_str)

        active_client = client or self.client

        # If a client was provided, use it directly; otherwise manage lifecycle via context manager
        if active_client is not None:
            return self._execute_search_ingest(
                active_client=active_client,
                run_id=clean_run_id,
                cfg=cfg,
                query_str=query_str,
                max_results=max_results,
                application_numbers=application_numbers,
                on_captcha_required=on_captcha_required,
                captcha_solver=captcha_solver,
            )
        else:
            with InPassClient() as created_client:
                return self._execute_search_ingest(
                    active_client=created_client,
                    run_id=clean_run_id,
                    cfg=cfg,
                    query_str=query_str,
                    max_results=max_results,
                    application_numbers=application_numbers,
                    on_captcha_required=on_captcha_required,
                    captcha_solver=captcha_solver,
                )

    def _execute_search_ingest(
        self,
        active_client: InPassClient,
        run_id: str,
        cfg: InPassSearchConfig,
        query_str: str,
        max_results: int,
        application_numbers: Optional[Sequence[str]],
        on_captcha_required: Optional[Callable[[str], None]],
        captcha_solver: Optional[Callable[[str], str]] = None,
    ) -> InPassIngestionResult:
        """Internal helper executing the search, details retrieval, and persistence steps."""
        # 1. Search dispatch and CAPTCHA checkpoint
        try:
            active_client.open_search_page()
            active_client.configure_search(cfg)
            active_client.wait_for_captcha_and_results(
                on_captcha_required=on_captcha_required,
                captcha_solver=captcha_solver,
            )
            result_rows = active_client.read_current_page_results()
        except InPassClientError as err:
            logger.error("InPASS search failed for run '%s' with query '%s': %s", run_id, query_str, err)
            raise InPassIngestionSearchError(f"InPASS search failed: {err}") from err

        discovered_count = len(result_rows)

        # 2. Determine target applications to fetch
        target_app_nums: list[str] = []
        if application_numbers:
            # Match against explicit list
            requested_set = {app.strip() for app in application_numbers if app.strip()}
            for r in result_rows:
                if r.application_number in requested_set:
                    target_app_nums.append(r.application_number)
            # If explicit apps not in result_rows, still attempt retrieval
            for app in requested_set:
                if app not in target_app_nums and len(target_app_nums) < max_results:
                    target_app_nums.append(app)
        else:
            target_app_nums = [r.application_number for r in result_rows[:max_results]]

        # 3. Retrieve PatentDetails for selected applications
        parsed_records: list[InPassPatentRecord] = []
        try:
            for app_num in target_app_nums:
                record = active_client.get_patent_details(app_num, return_to_search=True)
                parsed_records.append(record)
        except InPassClientError as err:
            logger.error("Failed retrieving PatentDetails during ingestion for run '%s': %s", run_id, err)
            raise InPassIngestionSearchError(f"Failed retrieving patent details: {err}") from err

        # 4. Persist and link to run_id via PatentRepository
        canonical_patents: list[PatentRecord] = [r.to_patent_record() for r in parsed_records]
        try:
            save_stats = self.repository.save_patents_for_run(
                run_id=run_id,
                patents=canonical_patents,
            )
        except Exception as err:
            logger.error("Failed persisting InPASS patents for run '%s': %s", run_id, err)
            raise InPassIngestionPersistenceError(f"Failed persisting patents: {err}") from err

        return InPassIngestionResult(
            run_id=run_id,
            query=query_str,
            discovered=discovered_count,
            ingested=len(parsed_records),
            inserted=save_stats.get("inserted", 0),
            existing=save_stats.get("existing", 0),
            linked=save_stats.get("linked", 0),
            records=tuple(parsed_records),
        )

    def ingest_applications(
        self,
        run_id: str,
        application_numbers: Sequence[str],
        client: Optional[InPassClient] = None,
    ) -> InPassIngestionResult:
        """Fetch and persist an explicit list of application numbers for a research run.

        Args:
            run_id: Unique research run identifier.
            application_numbers: Sequence of application numbers to retrieve and persist.
            client: Optional InPassClient instance (uses self.client or starts a new one).

        Returns:
            InPassIngestionResult: Ingestion statistics and parsed records.
        """
        if not run_id or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        if not application_numbers:
            return InPassIngestionResult(
                run_id=run_id.strip(),
                query="",
                discovered=0,
                ingested=0,
                inserted=0,
                existing=0,
                linked=0,
            )

        clean_run_id = run_id.strip()
        active_client = client or self.client

        if active_client is not None:
            return self._fetch_and_persist_apps(active_client, clean_run_id, application_numbers)
        else:
            with InPassClient() as created_client:
                return self._fetch_and_persist_apps(created_client, clean_run_id, application_numbers)

    def _fetch_and_persist_apps(
        self,
        active_client: InPassClient,
        run_id: str,
        application_numbers: Sequence[str],
    ) -> InPassIngestionResult:
        """Internal helper to fetch explicit applications and persist."""
        parsed_records: list[InPassPatentRecord] = []
        try:
            for app in application_numbers:
                clean_app = app.strip()
                if not clean_app:
                    continue
                record = active_client.get_patent_details(clean_app, return_to_search=False)
                parsed_records.append(record)
        except InPassClientError as err:
            raise InPassIngestionSearchError(f"Failed retrieving patent details: {err}") from err

        canonical_patents = [r.to_patent_record() for r in parsed_records]
        try:
            save_stats = self.repository.save_patents_for_run(
                run_id=run_id,
                patents=canonical_patents,
            )
        except Exception as err:
            raise InPassIngestionPersistenceError(f"Failed persisting patents: {err}") from err

        return InPassIngestionResult(
            run_id=run_id,
            query="",
            discovered=len(application_numbers),
            ingested=len(parsed_records),
            inserted=save_stats.get("inserted", 0),
            existing=save_stats.get("existing", 0),
            linked=save_stats.get("linked", 0),
            records=tuple(parsed_records),
        )
