"""Opportunity evaluation persistence repository for storing and querying venture viability evaluations."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional, Sequence
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.evaluation.models import OpportunityEvaluationRecord
from src.evaluation.opportunity_evaluation_contract import (
    OpportunityEvaluationContractValidationError,
    validate_opportunity_evaluation_record,
)

logger = logging.getLogger(__name__)


class OpportunityEvaluationRepositoryError(Exception):
    """Base exception for opportunity evaluation repository operations."""
    pass


class OpportunityNotFoundError(OpportunityEvaluationRepositoryError):
    """Raised when the opportunity referenced by an evaluation does not exist."""
    pass


class EvaluationNotFoundError(OpportunityEvaluationRepositoryError):
    """Raised when an evaluation record ID is not found."""
    pass


class OpportunityEvaluationRepository:
    """Repository managing persistence and retrieval of OpportunityEvaluationRecord objects in SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the evaluation repository.

        Args:
            db_path: Path to SQLite database file. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def save_evaluation(
        self,
        evaluation: OpportunityEvaluationRecord,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """Persist an OpportunityEvaluationRecord, validating that the opportunity exists.

        Idempotent: Re-saving an evaluation for the same opportunity returns the existing ID
        without creating duplicate rows.

        Args:
            evaluation: Validated OpportunityEvaluationRecord instance.
            conn: Optional active database connection for transactions.

        Returns:
            str: Primary key UUID of the persisted evaluation record.

        Raises:
            OpportunityEvaluationRepositoryError: If inputs are invalid or database operation fails.
            OpportunityNotFoundError: If the referenced opportunity does not exist in the database.
        """
        if not isinstance(evaluation, OpportunityEvaluationRecord):
            raise OpportunityEvaluationRepositoryError(
                f"Expected OpportunityEvaluationRecord instance, got {type(evaluation).__name__}."
            )

        try:
            validate_opportunity_evaluation_record(evaluation)
        except (OpportunityEvaluationContractValidationError, ValueError, TypeError) as err:
            raise OpportunityEvaluationRepositoryError(
                f"OpportunityEvaluationRecord validation failed: {err}"
            ) from err

        if conn is not None:
            return self._execute_save(conn, evaluation)

        with get_db(self.db_path) as active_conn:
            return self._execute_save(active_conn, evaluation)

    def _execute_save(
        self,
        conn: sqlite3.Connection,
        evaluation: OpportunityEvaluationRecord,
    ) -> str:
        """Internal helper to atomically validate opportunity existence, check idempotency, and insert."""
        cursor = conn.cursor()

        # 1. Validate that the referenced opportunity exists in startup_opportunities
        cursor.execute(
            "SELECT id FROM startup_opportunities WHERE id = ?;",
            (evaluation.opportunity_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise OpportunityNotFoundError(
                f"Referenced opportunity '{evaluation.opportunity_id}' does not exist in the database."
            )

        # 2. Idempotency Check:
        # Check by provided evaluation ID if present
        if evaluation.id:
            cursor.execute(
                "SELECT id FROM opportunity_evaluations WHERE id = ?;",
                (evaluation.id.strip(),),
            )
            existing_by_id = cursor.fetchone()
            if existing_by_id:
                return existing_by_id["id"]

        # Check by opportunity_id to prevent duplicate evaluations for the same opportunity
        cursor.execute(
            "SELECT id FROM opportunity_evaluations WHERE opportunity_id = ?;",
            (evaluation.opportunity_id,),
        )
        existing_for_opp = cursor.fetchone()
        if existing_for_opp:
            existing_id = existing_for_opp["id"]
            logger.info(
                "Evaluation already exists for opportunity '%s' (id=%s). Returning existing ID.",
                evaluation.opportunity_id,
                existing_id,
            )
            return existing_id

        # 3. Determine evaluation UUID
        eval_id = evaluation.id.strip() if evaluation.id else str(uuid.uuid4())

        # 4. Serialize JSON fields
        rejection_reasons_json = json.dumps(list(evaluation.rejection_reasons))
        raw_data_json = json.dumps(evaluation.raw_data)

        # 5. Insert evaluation row
        try:
            cursor.execute(
                """
                INSERT INTO opportunity_evaluations (
                    id, opportunity_id, overall_score,
                    problem_severity_score, frequency_score, user_scale_score,
                    willingness_to_pay_score, market_gap_score, technology_leverage_score,
                    competition_score, wow_factor_score, recurring_potential_score,
                    social_impact_score, execution_feasibility_score,
                    rejection_reasons, recommendation, rationale, raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    eval_id,
                    evaluation.opportunity_id,
                    evaluation.overall_score,
                    evaluation.problem_severity_score,
                    evaluation.frequency_score,
                    evaluation.user_scale_score,
                    evaluation.willingness_to_pay_score,
                    evaluation.market_gap_score,
                    evaluation.technology_leverage_score,
                    evaluation.competition_score,
                    evaluation.wow_factor_score,
                    evaluation.recurring_potential_score,
                    evaluation.social_impact_score,
                    evaluation.execution_feasibility_score,
                    rejection_reasons_json,
                    evaluation.recommendation,
                    evaluation.rationale,
                    raw_data_json,
                ),
            )
        except sqlite3.Error as err:
            raise OpportunityEvaluationRepositoryError(
                f"Failed to insert opportunity_evaluation: {err}"
            ) from err

        logger.info(
            "Saved evaluation (id=%s) for opportunity '%s' with recommendation '%s'.",
            eval_id,
            evaluation.opportunity_id,
            evaluation.recommendation,
        )
        return eval_id

    def get_evaluation_by_id(
        self,
        evaluation_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[OpportunityEvaluationRecord]:
        """Retrieve and reconstruct an OpportunityEvaluationRecord by primary key ID.

        Args:
            evaluation_id: Primary key UUID of the evaluation record.
            conn: Optional database connection.

        Returns:
            Optional[OpportunityEvaluationRecord]: Reconstructed record or None if not found.
        """
        if not evaluation_id or not evaluation_id.strip():
            return None

        clean_id = evaluation_id.strip()
        query = """
            SELECT id, opportunity_id, overall_score,
                   problem_severity_score, frequency_score, user_scale_score,
                   willingness_to_pay_score, market_gap_score, technology_leverage_score,
                   competition_score, wow_factor_score, recurring_potential_score,
                   social_impact_score, execution_feasibility_score,
                   rejection_reasons, recommendation, rationale, raw_data, created_at
            FROM opportunity_evaluations
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

    def get_evaluation_for_opportunity(
        self,
        opportunity_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[OpportunityEvaluationRecord]:
        """Retrieve an evaluation record for a specific opportunity ID.

        Args:
            opportunity_id: Opportunity UUID foreign key.
            conn: Optional database connection.

        Returns:
            Optional[OpportunityEvaluationRecord]: Reconstructed record or None if not found.
        """
        if not opportunity_id or not opportunity_id.strip():
            return None

        clean_opp_id = opportunity_id.strip()
        query = """
            SELECT id, opportunity_id, overall_score,
                   problem_severity_score, frequency_score, user_scale_score,
                   willingness_to_pay_score, market_gap_score, technology_leverage_score,
                   competition_score, wow_factor_score, recurring_potential_score,
                   social_impact_score, execution_feasibility_score,
                   rejection_reasons, recommendation, rationale, raw_data, created_at
            FROM opportunity_evaluations
            WHERE opportunity_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_opp_id,))
            row = cursor.fetchone()
            return self._reconstruct_record(cursor, row) if row else None

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_opp_id,))
            row = cursor.fetchone()
            return self._reconstruct_record(cursor, row) if row else None

    def get_evaluations_for_opportunities(
        self,
        opportunity_ids: Sequence[str],
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[OpportunityEvaluationRecord]:
        """Retrieve evaluation records for multiple opportunity IDs.

        Args:
            opportunity_ids: Sequence of opportunity UUID strings.
            conn: Optional database connection.

        Returns:
            list[OpportunityEvaluationRecord]: Reconstructed records ordered by created_at ASC.
        """
        if not opportunity_ids:
            return []

        clean_ids = [str(oid).strip() for oid in opportunity_ids if str(oid).strip()]
        if not clean_ids:
            return []

        placeholders = ",".join("?" for _ in clean_ids)
        query = f"""
            SELECT id, opportunity_id, overall_score,
                   problem_severity_score, frequency_score, user_scale_score,
                   willingness_to_pay_score, market_gap_score, technology_leverage_score,
                   competition_score, wow_factor_score, recurring_potential_score,
                   social_impact_score, execution_feasibility_score,
                   rejection_reasons, recommendation, rationale, raw_data, created_at
            FROM opportunity_evaluations
            WHERE opportunity_id IN ({placeholders})
            ORDER BY created_at ASC, rowid ASC;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, clean_ids)
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, clean_ids)
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

    def _reconstruct_record(
        self,
        cursor: sqlite3.Cursor,
        row: sqlite3.Row,
    ) -> OpportunityEvaluationRecord:
        """Reconstruct an OpportunityEvaluationRecord from an opportunity_evaluations database row."""
        reasons_json = row["rejection_reasons"]
        try:
            reasons = tuple(json.loads(reasons_json)) if reasons_json else ()
        except (json.JSONDecodeError, TypeError):
            reasons = ()

        raw_str = row["raw_data"]
        try:
            raw_dict = json.loads(raw_str) if raw_str else {}
            if not isinstance(raw_dict, dict):
                raw_dict = {}
        except (json.JSONDecodeError, TypeError):
            raw_dict = {}

        return OpportunityEvaluationRecord(
            opportunity_id=row["opportunity_id"],
            overall_score=int(row["overall_score"]),
            problem_severity_score=int(row["problem_severity_score"]),
            frequency_score=int(row["frequency_score"]),
            user_scale_score=int(row["user_scale_score"]),
            willingness_to_pay_score=int(row["willingness_to_pay_score"]),
            market_gap_score=int(row["market_gap_score"]),
            technology_leverage_score=int(row["technology_leverage_score"]),
            competition_score=int(row["competition_score"]),
            wow_factor_score=int(row["wow_factor_score"]),
            recurring_potential_score=int(row["recurring_potential_score"]),
            social_impact_score=int(row["social_impact_score"]),
            execution_feasibility_score=int(row["execution_feasibility_score"]),
            rejection_reasons=reasons,
            recommendation=row["recommendation"],
            rationale=row["rationale"],
            id=str(row["id"]) if row["id"] else None,
            raw_data=raw_dict,
        )
