"""Problem persistence repository for storing and querying extracted technical problems."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.problems.extraction_contract import (
    ProblemContractValidationError,
    validate_problem_record,
)
from src.problems.models import ProblemRecord

logger = logging.getLogger(__name__)


class ProblemRepositoryError(Exception):
    """Base exception for problem repository operations."""
    pass


class ProblemNotFoundError(ProblemRepositoryError):
    """Raised when a requested problem ID is not found."""
    pass


class ProblemPatentNotFoundError(ProblemRepositoryError):
    """Raised when a source patent number referenced by a problem does not exist in the database."""
    pass


class ProblemRepository:
    """Repository managing persistence and retrieval of extracted ProblemRecords in SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the problem repository.

        Args:
            db_path: Path to SQLite database. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def save_problem(
        self,
        problem: ProblemRecord,
        run_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """Atomically persist a validated ProblemRecord and link it to its source patents.

        Args:
            problem: Validated ProblemRecord instance.
            run_id: Associated research run identifier.
            conn: Optional active database connection for batch transactions.

        Returns:
            str: Primary key UUID of the newly persisted problem record.

        Raises:
            ProblemRepositoryError: If inputs are invalid or database operation fails.
            ProblemPatentNotFoundError: If any source patent number does not exist in SQLite.
        """
        if not isinstance(problem, ProblemRecord):
            raise ProblemRepositoryError(
                f"Expected ProblemRecord instance, got {type(problem).__name__}."
            )
        if not run_id or not run_id.strip():
            raise ProblemRepositoryError("run_id must be a non-empty string.")

        try:
            validate_problem_record(problem)
        except (ProblemContractValidationError, ValueError) as err:
            raise ProblemRepositoryError(f"ProblemRecord validation failed: {err}") from err

        clean_run_id = run_id.strip()

        if conn is not None:
            return self._execute_save(conn, problem, clean_run_id)

        with get_db(self.db_path) as active_conn:
            return self._execute_save(active_conn, problem, clean_run_id)

    def _execute_save(
        self,
        conn: sqlite3.Connection,
        problem: ProblemRecord,
        run_id: str,
    ) -> str:
        """Internal helper to atomically save problem and patent links within a connection."""
        cursor = conn.cursor()

        # 1. Resolve all source patent numbers to patent IDs
        patent_id_map: list[str] = []
        for pat_num in problem.source_patent_numbers:
            cursor.execute(
                "SELECT id FROM patents WHERE patent_number = ?;",
                (pat_num,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProblemPatentNotFoundError(
                    f"Referenced source patent '{pat_num}' does not exist in the database."
                )
            patent_id_map.append(row["id"])

        problem_id = str(uuid.uuid4())

        # 2. Package all ProblemRecord fields inside raw_data JSON for 100% round-trip fidelity
        stored_payload = {
            "problem_title": problem.problem_title,
            "problem_description": problem.problem_description,
            "affected_users": problem.affected_users,
            "bottleneck_type": problem.bottleneck_type,
            "technical_domain": problem.technical_domain,
            "current_workaround": problem.current_workaround,
            "problem_frequency": problem.problem_frequency,
            "problem_severity": problem.problem_severity,
            "evidence_summary": problem.evidence_summary,
            "evidence_confidence": problem.evidence_confidence,
            "source_patent_numbers": list(problem.source_patent_numbers),
            "raw_data": problem.raw_data,
        }
        raw_data_json = json.dumps(stored_payload)

        # 3. Insert problem record into extracted_problems
        try:
            cursor.execute(
                """
                INSERT INTO extracted_problems (
                    id, run_id, problem_title, problem_description,
                    bottleneck_type, technical_domain, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    problem_id,
                    run_id,
                    problem.problem_title,
                    problem.problem_description,
                    problem.bottleneck_type,
                    problem.technical_domain,
                    raw_data_json,
                ),
            )
        except sqlite3.Error as err:
            raise ProblemRepositoryError(f"Failed to insert extracted_problem: {err}") from err

        # 4. Link problem to each resolved patent in problem_patents
        for patent_id in patent_id_map:
            self.link_problem_to_patent(problem_id, patent_id, conn=conn)

        logger.info(
            "Saved problem '%s' (id=%s) linked to %d patents in run '%s'.",
            problem.problem_title,
            problem_id,
            len(patent_id_map),
            run_id,
        )
        return problem_id

    def link_problem_to_patent(
        self,
        problem_id: str,
        patent_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Idempotently link an extracted problem to a patent record in problem_patents.

        Args:
            problem_id: Extracted problem UUID.
            patent_id: Patent record UUID.
            conn: Optional active database connection.
        """
        stmt = """
            INSERT INTO problem_patents (problem_id, patent_id)
            VALUES (?, ?)
            ON CONFLICT (problem_id, patent_id) DO NOTHING;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(stmt, (problem_id, patent_id))
            return

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(stmt, (problem_id, patent_id))

    def get_problem_by_id(
        self,
        problem_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[ProblemRecord]:
        """Retrieve and reconstruct a complete ProblemRecord by primary key ID.

        Args:
            problem_id: Extracted problem UUID.
            conn: Optional database connection.

        Returns:
            Optional[ProblemRecord]: Reconstructed ProblemRecord, or None if not found.
        """
        if not problem_id or not problem_id.strip():
            return None

        clean_id = problem_id.strip()
        query = """
            SELECT id, run_id, problem_title, problem_description,
                   bottleneck_type, technical_domain, raw_data, created_at
            FROM extracted_problems
            WHERE id = ?;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_id,))
            row = cursor.fetchone()
            return self._reconstruct_record(cursor, row) if row else None

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_id,))
            row = cursor.fetchone()
            return self._reconstruct_record(cursor, row) if row else None

    def get_problems_for_run(
        self,
        run_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[ProblemRecord]:
        """Retrieve all ProblemRecords associated with a research run in deterministic order.

        Args:
            run_id: Research run identifier.
            conn: Optional database connection.

        Returns:
            list[ProblemRecord]: Reconstructed ProblemRecords ordered by created_at ASC, id ASC.
        """
        if not run_id or not run_id.strip():
            return []

        clean_run_id = run_id.strip()
        query = """
            SELECT id, run_id, problem_title, problem_description,
                   bottleneck_type, technical_domain, raw_data, created_at
            FROM extracted_problems
            WHERE run_id = ?
            ORDER BY created_at ASC, rowid ASC;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_run_id,))
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_run_id,))
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

    def get_patents_for_problem(
        self,
        problem_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[str]:
        """Retrieve all patent record IDs linked to a specific problem.

        Args:
            problem_id: Extracted problem UUID.
            conn: Optional database connection.

        Returns:
            list[str]: Linked patent record IDs ordered by patent_id ASC.
        """
        if not problem_id or not problem_id.strip():
            return []

        clean_id = problem_id.strip()
        query = """
            SELECT patent_id
            FROM problem_patents
            WHERE problem_id = ?
            ORDER BY patent_id ASC;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_id,))
            return [r["patent_id"] for r in cursor.fetchall()]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_id,))
            return [r["patent_id"] for r in cursor.fetchall()]

    def _reconstruct_record(
        self,
        cursor: sqlite3.Cursor,
        row: sqlite3.Row,
    ) -> ProblemRecord:
        """Reconstruct a complete ProblemRecord instance from an extracted_problems row."""
        payload: dict[str, Any] = {}
        raw_str = row["raw_data"]
        if raw_str:
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, dict):
                    payload = parsed
            except (json.JSONDecodeError, TypeError):
                payload = {}

        source_patents = tuple(payload.get("source_patent_numbers", ()))
        if not source_patents:
            # Fallback: resolve from problem_patents junction
            cursor.execute(
                """
                SELECT p.patent_number
                FROM patents p
                JOIN problem_patents pp ON p.id = pp.patent_id
                WHERE pp.problem_id = ?
                ORDER BY p.patent_number ASC;
                """,
                (row["id"],),
            )
            source_patents = tuple(r["patent_number"] for r in cursor.fetchall())

        return ProblemRecord(
            problem_title=payload.get("problem_title", row["problem_title"]),
            problem_description=payload.get("problem_description", row["problem_description"] or ""),
            affected_users=payload.get("affected_users", "unknown"),
            bottleneck_type=payload.get("bottleneck_type", row["bottleneck_type"] or "unknown"),
            technical_domain=payload.get("technical_domain", row["technical_domain"] or "unknown"),
            current_workaround=payload.get("current_workaround", "unknown"),
            problem_frequency=payload.get("problem_frequency", "unknown"),
            problem_severity=payload.get("problem_severity", "unknown"),
            evidence_summary=payload.get("evidence_summary", "unknown"),
            evidence_confidence=payload.get("evidence_confidence", "medium"),
            source_patent_numbers=source_patents,
            raw_data=payload.get("raw_data", {}),
        )
