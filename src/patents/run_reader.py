"""Read-only service for querying and reconstructing patents associated with research runs.

Provides deterministic retrieval of canonical PatentRecord instances from the
SQLite persistence layer for downstream problem extraction and synthesis.
"""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Optional

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.patents.models import PatentRecord, build_canonical_url

logger = logging.getLogger(__name__)


class ResearchRunPatentReader:
    """Read-only query service for reconstructing PatentRecord objects for a research run."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the patent reader with the target database.

        Args:
            db_path: Path to SQLite database. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def get_patents_for_run(self, run_id: str) -> list[PatentRecord]:
        """Retrieve all patents linked to a research run as canonical PatentRecord models.

        Args:
            run_id: Unique research run identifier.

        Returns:
            list[PatentRecord]: List of reconstructed PatentRecords in deterministic order
                                (ordered by publication_date ASC, patent_number ASC).
                                Returns empty list if run_id is unknown or has no patents.
        """
        if not run_id or not run_id.strip():
            return []

        clean_run_id = run_id.strip()

        query = """
            SELECT
                p.patent_number,
                p.title,
                p.abstract,
                p.filing_date,
                p.publication_date,
                p.assignee,
                p.source_url,
                p.raw_data
            FROM patents p
            JOIN run_patents rp ON p.id = rp.patent_id
            WHERE rp.run_id = ?
            ORDER BY p.publication_date ASC, p.patent_number ASC;
        """

        patents: list[PatentRecord] = []

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (clean_run_id,))
            rows = cursor.fetchall()

            for row in rows:
                raw_data_dict: dict = {}
                if row["raw_data"]:
                    try:
                        parsed = json.loads(row["raw_data"])
                        if isinstance(parsed, dict):
                            raw_data_dict = parsed
                        else:
                            raw_data_dict = {"raw": parsed}
                    except (json.JSONDecodeError, TypeError) as err:
                        logger.warning(
                            "Malformed raw_data JSON for patent %s: %s",
                            row["patent_number"],
                            err,
                        )
                        raw_data_dict = {"raw_unparsed": row["raw_data"]}

                source_url = row["source_url"] or build_canonical_url(row["patent_number"])
                title = row["title"] or "Untitled"

                record = PatentRecord(
                    patent_number=row["patent_number"],
                    title=title,
                    abstract=row["abstract"],
                    filing_date=row["filing_date"],
                    publication_date=row["publication_date"],
                    assignee=row["assignee"],
                    source_url=source_url,
                    raw_data=raw_data_dict,
                )
                patents.append(record)

        return patents

    def count_patents_for_run(self, run_id: str) -> int:
        """Count the number of patents associated with a research run.

        Args:
            run_id: Unique research run identifier.

        Returns:
            int: Number of linked patents, or 0 if run has none or does not exist.
        """
        if not run_id or not run_id.strip():
            return 0

        clean_run_id = run_id.strip()

        query = """
            SELECT COUNT(*)
            FROM run_patents
            WHERE run_id = ?;
        """

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (clean_run_id,))
            count = cursor.fetchone()[0]
            return int(count)
