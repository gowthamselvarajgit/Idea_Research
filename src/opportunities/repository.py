"""Opportunity persistence repository for storing and querying synthesized venture opportunities."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.opportunities.models import OpportunityRecord
from src.opportunities.opportunity_contract import (
    OpportunityContractValidationError,
    validate_opportunity_record,
)

logger = logging.getLogger(__name__)


class OpportunityRepositoryError(Exception):
    """Base exception for opportunity repository operations."""
    pass


class OpportunityNotFoundError(OpportunityRepositoryError):
    """Raised when a requested opportunity ID is not found."""
    pass


class OpportunityProblemNotFoundError(OpportunityRepositoryError):
    """Raised when a source problem ID referenced by an opportunity does not exist in the database."""
    pass


class OpportunityRepository:
    """Repository managing persistence and retrieval of OpportunityRecords in SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the opportunity repository.

        Args:
            db_path: Path to SQLite database. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def save_opportunity(
        self,
        opportunity: OpportunityRecord,
        run_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """Atomically persist an OpportunityRecord and link it to its source problems.

        Args:
            opportunity: Validated OpportunityRecord instance.
            run_id: Associated research run identifier.
            conn: Optional active database connection for batch transactions.

        Returns:
            str: Primary key UUID of the persisted opportunity record.

        Raises:
            OpportunityRepositoryError: If inputs are invalid or database operation fails.
            OpportunityProblemNotFoundError: If any source problem ID does not exist in SQLite.
        """
        if not isinstance(opportunity, OpportunityRecord):
            raise OpportunityRepositoryError(
                f"Expected OpportunityRecord instance, got {type(opportunity).__name__}."
            )
        if not run_id or not run_id.strip():
            raise OpportunityRepositoryError("run_id must be a non-empty string.")

        try:
            validate_opportunity_record(opportunity)
        except (OpportunityContractValidationError, ValueError) as err:
            raise OpportunityRepositoryError(
                f"OpportunityRecord validation failed: {err}"
            ) from err

        clean_run_id = run_id.strip()

        if conn is not None:
            return self._execute_save(conn, opportunity, clean_run_id)

        with get_db(self.db_path) as active_conn:
            return self._execute_save(active_conn, opportunity, clean_run_id)

    def _execute_save(
        self,
        conn: sqlite3.Connection,
        opportunity: OpportunityRecord,
        run_id: str,
    ) -> str:
        """Internal helper to atomically validate problems, save opportunity, and link records."""
        cursor = conn.cursor()

        # 1. Validate that every source problem ID exists in extracted_problems
        for prob_id in opportunity.source_problem_ids:
            cursor.execute(
                "SELECT id FROM extracted_problems WHERE id = ?;",
                (prob_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise OpportunityProblemNotFoundError(
                    f"Referenced source problem '{prob_id}' does not exist in the database."
                )

        # 2. Determine opportunity UUID (preserve provided or generate new)
        opp_id = opportunity.id.strip() if opportunity.id else str(uuid.uuid4())

        # 3. Idempotency Check:
        # Check by explicit opportunity ID if provided
        if opportunity.id:
            cursor.execute(
                "SELECT id FROM startup_opportunities WHERE id = ?;",
                (opp_id,),
            )
            existing_by_id = cursor.fetchone()
            if existing_by_id:
                # Ensure links exist and return existing ID
                for prob_id in opportunity.source_problem_ids:
                    self.link_opportunity_to_problem(opp_id, prob_id, conn=conn)
                return opp_id

        # Check by run_id, opportunity_title, and exact matching source problems
        if opportunity.source_problem_ids:
            clean_pids = list(opportunity.source_problem_ids)
            placeholders = ",".join("?" for _ in clean_pids)
            cursor.execute(
                f"""
                SELECT so.id
                FROM startup_opportunities so
                JOIN opportunity_problems op ON so.id = op.opportunity_id
                WHERE so.run_id = ? AND so.opportunity_title = ? AND op.problem_id IN ({placeholders})
                GROUP BY so.id
                HAVING COUNT(DISTINCT op.problem_id) = ?;
                """,
                [run_id, opportunity.opportunity_title] + clean_pids + [len(clean_pids)],
            )
            existing_row = cursor.fetchone()
            if existing_row:
                existing_id = existing_row["id"]
                logger.info(
                    "Opportunity '%s' already exists for run '%s' (id=%s). Returning existing ID.",
                    opportunity.opportunity_title,
                    run_id,
                    existing_id,
                )
                return existing_id

        # 4. Package complete OpportunityRecord fields inside raw_data JSON for 100% round-trip fidelity
        stored_payload = {
            "opportunity_title": opportunity.opportunity_title,
            "solution_concept": opportunity.solution_concept,
            "target_customer": opportunity.target_customer,
            "value_proposition": opportunity.value_proposition,
            "source_problem_ids": list(opportunity.source_problem_ids),
            "raw_data": opportunity.raw_data,
        }
        raw_data_json = json.dumps(stored_payload)

        # 5. Insert opportunity row into startup_opportunities
        try:
            cursor.execute(
                """
                INSERT INTO startup_opportunities (
                    id, run_id, opportunity_title, solution_concept,
                    target_customer, value_proposition, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    opp_id,
                    run_id,
                    opportunity.opportunity_title,
                    opportunity.solution_concept,
                    opportunity.target_customer,
                    opportunity.value_proposition,
                    raw_data_json,
                ),
            )
        except sqlite3.Error as err:
            raise OpportunityRepositoryError(
                f"Failed to insert startup_opportunity: {err}"
            ) from err

        # 6. Link opportunity to each validated source problem in opportunity_problems
        for prob_id in opportunity.source_problem_ids:
            self.link_opportunity_to_problem(opp_id, prob_id, conn=conn)

        logger.info(
            "Saved opportunity '%s' (id=%s) linked to %d problems in run '%s'.",
            opportunity.opportunity_title,
            opp_id,
            len(opportunity.source_problem_ids),
            run_id,
        )
        return opp_id

    def link_opportunity_to_problem(
        self,
        opportunity_id: str,
        problem_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Idempotently link an opportunity to a problem in opportunity_problems.

        Args:
            opportunity_id: Startup opportunity UUID.
            problem_id: Extracted problem UUID.
            conn: Optional active database connection.
        """
        stmt = """
            INSERT INTO opportunity_problems (opportunity_id, problem_id)
            VALUES (?, ?)
            ON CONFLICT (opportunity_id, problem_id) DO NOTHING;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(stmt, (opportunity_id, problem_id))
            return

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(stmt, (opportunity_id, problem_id))

    def get_opportunity_by_id(
        self,
        opportunity_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[OpportunityRecord]:
        """Retrieve and reconstruct a complete OpportunityRecord by primary key ID.

        Args:
            opportunity_id: Startup opportunity UUID.
            conn: Optional database connection.

        Returns:
            Optional[OpportunityRecord]: Reconstructed OpportunityRecord, or None if not found.
        """
        if not opportunity_id or not opportunity_id.strip():
            return None

        clean_id = opportunity_id.strip()
        query = """
            SELECT id, run_id, opportunity_title, solution_concept,
                   target_customer, value_proposition, raw_data, created_at
            FROM startup_opportunities
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

    def get_opportunities_for_run(
        self,
        run_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[OpportunityRecord]:
        """Retrieve all OpportunityRecords associated with a research run in deterministic order.

        Args:
            run_id: Research run identifier.
            conn: Optional database connection.

        Returns:
            list[OpportunityRecord]: Reconstructed records ordered by created_at ASC, rowid ASC.
        """
        if not run_id or not run_id.strip():
            return []

        clean_run_id = run_id.strip()
        query = """
            SELECT id, run_id, opportunity_title, solution_concept,
                   target_customer, value_proposition, raw_data, created_at
            FROM startup_opportunities
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

    def get_problems_for_opportunity(
        self,
        opportunity_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[str]:
        """Retrieve all problem record IDs linked to a specific opportunity.

        Args:
            opportunity_id: Startup opportunity UUID.
            conn: Optional database connection.

        Returns:
            list[str]: Linked problem IDs ordered by problem_id ASC.
        """
        if not opportunity_id or not opportunity_id.strip():
            return []

        clean_id = opportunity_id.strip()
        query = """
            SELECT problem_id
            FROM opportunity_problems
            WHERE opportunity_id = ?
            ORDER BY problem_id ASC;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_id,))
            return [r["problem_id"] for r in cursor.fetchall()]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_id,))
            return [r["problem_id"] for r in cursor.fetchall()]

    def _reconstruct_record(
        self,
        cursor: sqlite3.Cursor,
        row: sqlite3.Row,
    ) -> OpportunityRecord:
        """Reconstruct a complete OpportunityRecord instance from a startup_opportunities row."""
        payload: dict[str, Any] = {}
        raw_str = row["raw_data"]
        if raw_str:
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, dict):
                    payload = parsed
            except (json.JSONDecodeError, TypeError):
                payload = {}

        source_problems = tuple(payload.get("source_problem_ids", ()))
        if not source_problems:
            cursor.execute(
                """
                SELECT problem_id
                FROM opportunity_problems
                WHERE opportunity_id = ?
                ORDER BY problem_id ASC;
                """,
                (row["id"],),
            )
            source_problems = tuple(r["problem_id"] for r in cursor.fetchall())

        opp_raw_data = payload.get("raw_data", {}) if "raw_data" in payload else payload

        return OpportunityRecord(
            opportunity_title=payload.get("opportunity_title", row["opportunity_title"]),
            solution_concept=payload.get("solution_concept", row["solution_concept"] or ""),
            target_customer=payload.get("target_customer", row["target_customer"] or ""),
            value_proposition=payload.get("value_proposition", row["value_proposition"] or ""),
            source_problem_ids=source_problems,
            id=str(row["id"]) if row["id"] else None,
            raw_data=opp_raw_data,
        )
