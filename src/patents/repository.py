"""Patent persistence repository for SQLite storage.

Provides atomic upsert, retrieval, and research run association for canonical
PatentRecord instances using the existing database layer.
"""

import json
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_connection, get_db
from src.patents.models import PatentRecord


class PatentRepository:
    """Persistence repository for patent entities and research run associations."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to SQLite database. Defaults to config.settings.DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def upsert_patent(
        self,
        patent: PatentRecord,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """Insert a new patent or update existing metadata for the publication number.

        Args:
            patent: Normalized PatentRecord instance.
            conn: Optional existing sqlite3.Connection for transactional batching.

        Returns:
            str: The patent's permanent primary key identifier in the database.
        """
        if conn is not None:
            return self._execute_upsert(conn, patent)

        with get_db(self.db_path) as active_conn:
            return self._execute_upsert(active_conn, patent)

    def _execute_upsert(self, conn: sqlite3.Connection, patent: PatentRecord) -> str:
        """Internal helper to execute the upsert logic within a connection."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, abstract, filing_date, publication_date, assignee, source_url, raw_data
            FROM patents
            WHERE patent_number = ?;
            """,
            (patent.patent_number,),
        )
        existing = cursor.fetchone()

        raw_data_json = json.dumps(patent.raw_data) if patent.raw_data else None

        if existing is None:
            patent_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO patents (
                    id, patent_number, title, abstract, filing_date,
                    publication_date, assignee, source_url, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    patent_id,
                    patent.patent_number,
                    patent.title,
                    patent.abstract,
                    patent.filing_date,
                    patent.publication_date,
                    patent.assignee,
                    patent.source_url,
                    raw_data_json,
                ),
            )
            return patent_id

        # Update existing record: prefer non-null / non-empty new values
        patent_id = existing["id"]
        updated_title = patent.title if (patent.title and patent.title != "Untitled") else existing["title"]
        updated_abstract = patent.abstract if patent.abstract else existing["abstract"]
        updated_filing_date = patent.filing_date if patent.filing_date else existing["filing_date"]
        updated_pub_date = patent.publication_date if patent.publication_date else existing["publication_date"]
        updated_assignee = patent.assignee if patent.assignee else existing["assignee"]
        updated_source_url = patent.source_url if patent.source_url else existing["source_url"]
        updated_raw_data = raw_data_json if raw_data_json else existing["raw_data"]

        cursor.execute(
            """
            UPDATE patents
            SET title = ?,
                abstract = ?,
                filing_date = ?,
                publication_date = ?,
                assignee = ?,
                source_url = ?,
                raw_data = ?
            WHERE id = ?;
            """,
            (
                updated_title,
                updated_abstract,
                updated_filing_date,
                updated_pub_date,
                updated_assignee,
                updated_source_url,
                updated_raw_data,
                patent_id,
            ),
        )
        return patent_id

    def get_patent_by_number(
        self,
        patent_number: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a patent dictionary by its normalized patent number."""
        query = "SELECT * FROM patents WHERE patent_number = ?;"

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (patent_number,))
            row = cursor.fetchone()
            return dict(row) if row else None

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (patent_number,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_patent_by_id(
        self,
        patent_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[dict[str, Any]]:
        """Retrieve a patent dictionary by its primary key ID."""
        query = "SELECT * FROM patents WHERE id = ?;"

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (patent_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (patent_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def link_patent_to_run(
        self,
        run_id: str,
        patent_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> bool:
        """Associate a patent with a research run in the run_patents junction table.

        Idempotent: Repeated calls for the same run_id and patent_id will not duplicate.

        Args:
            run_id: Research run ID.
            patent_id: Permanent patent ID.
            conn: Optional existing connection.

        Returns:
            bool: True if a new junction link was created, False if already linked.
        """
        stmt = """
            INSERT INTO run_patents (run_id, patent_id)
            VALUES (?, ?)
            ON CONFLICT (run_id, patent_id) DO NOTHING;
        """

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(stmt, (run_id, patent_id))
            return cursor.rowcount > 0

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(stmt, (run_id, patent_id))
            return cursor.rowcount > 0

    def get_patents_for_run(
        self,
        run_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve all patent records associated with a specific research run."""
        query = """
            SELECT p.*
            FROM patents p
            JOIN run_patents rp ON p.id = rp.patent_id
            WHERE rp.run_id = ?
            ORDER BY rp.created_at ASC;
        """

        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (run_id,))
            return [dict(row) for row in cursor.fetchall()]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (run_id,))
            return [dict(row) for row in cursor.fetchall()]

    def save_patents_for_run(
        self,
        run_id: str,
        patents: list[PatentRecord],
    ) -> dict[str, int]:
        """Atomically upsert candidate patents and link them to a research run.

        Args:
            run_id: Research run identifier.
            patents: List of PatentRecord instances.

        Returns:
            dict[str, int]: Counts of total, inserted, existing/updated, and linked patents.
        """
        inserted_count = 0
        existing_count = 0
        linked_count = 0

        with get_db(self.db_path) as conn:
            for patent in patents:
                # Check existence prior to upsert for accurate telemetry
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM patents WHERE patent_number = ?;",
                    (patent.patent_number,),
                )
                was_existing = cursor.fetchone() is not None

                patent_id = self.upsert_patent(patent, conn=conn)

                if was_existing:
                    existing_count += 1
                else:
                    inserted_count += 1

                newly_linked = self.link_patent_to_run(run_id, patent_id, conn=conn)
                if newly_linked:
                    linked_count += 1

        return {
            "total": len(patents),
            "inserted": inserted_count,
            "existing": existing_count,
            "linked": linked_count,
        }
