"""Market research persistence repository for storing and querying competitive intelligence and findings."""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db
from src.market_research.contract import (
    MarketResearchContractValidationError,
    validate_market_research_record,
)
from src.market_research.models import MarketResearchRecord

logger = logging.getLogger(__name__)


class MarketResearchRepositoryError(Exception):
    """Base exception for market research repository operations."""
    pass


class OpportunityNotFoundError(MarketResearchRepositoryError):
    """Raised when the opportunity referenced by a market research finding does not exist."""
    pass


class MarketResearchNotFoundError(MarketResearchRepositoryError):
    """Raised when a market research record ID is not found."""
    pass


class MarketResearchRepository:
    """Repository managing persistence and retrieval of MarketResearchRecord objects in SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the market research repository.

        Args:
            db_path: Path to SQLite database file. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def save_market_research(
        self,
        record: MarketResearchRecord,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """Persist a MarketResearchRecord, validating that the referenced opportunity exists.

        Idempotent: Re-saving an identical finding for the same opportunity or re-saving
        a record with the same ID returns the existing ID without creating duplicate rows.

        Args:
            record: Validated MarketResearchRecord instance.
            conn: Optional active database connection for transactions.

        Returns:
            str: Primary key UUID of the persisted market research record.

        Raises:
            MarketResearchRepositoryError: If inputs are invalid or database operation fails.
            OpportunityNotFoundError: If the referenced opportunity does not exist in SQLite.
        """
        if not isinstance(record, MarketResearchRecord):
            raise MarketResearchRepositoryError(
                f"Expected MarketResearchRecord instance, got {type(record).__name__}."
            )

        try:
            validate_market_research_record(record)
        except (MarketResearchContractValidationError, ValueError, TypeError) as err:
            raise MarketResearchRepositoryError(
                f"MarketResearchRecord validation failed: {err}"
            ) from err

        if conn is not None:
            return self._execute_save(conn, record)

        with get_db(self.db_path) as active_conn:
            return self._execute_save(active_conn, record)

    def _execute_save(
        self,
        conn: sqlite3.Connection,
        record: MarketResearchRecord,
    ) -> str:
        """Internal helper to atomically validate opportunity existence, check idempotency, and insert."""
        cursor = conn.cursor()

        # 1. Validate that the referenced opportunity exists in startup_opportunities
        cursor.execute(
            "SELECT id FROM startup_opportunities WHERE id = ?;",
            (record.opportunity_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise OpportunityNotFoundError(
                f"Referenced opportunity '{record.opportunity_id}' does not exist in the database."
            )

        # 2. Idempotency Check:
        # Check by provided record ID if present
        if record.id:
            cursor.execute(
                "SELECT id FROM market_research_findings WHERE id = ?;",
                (record.id.strip(),),
            )
            existing_by_id = cursor.fetchone()
            if existing_by_id:
                return existing_by_id["id"]

        # Check by (opportunity_id, source_url, company_or_product, finding) to prevent accidental duplicate findings
        cursor.execute(
            """
            SELECT id FROM market_research_findings
            WHERE opportunity_id = ? AND source_url = ? AND company_or_product = ? AND finding = ?;
            """,
            (record.opportunity_id, record.source_url, record.company_or_product, record.finding),
        )
        existing_finding = cursor.fetchone()
        if existing_finding:
            existing_id = existing_finding["id"]
            logger.info(
                "Market research finding already exists for opportunity '%s' (id=%s). Returning existing ID.",
                record.opportunity_id,
                existing_id,
            )
            return existing_id

        # 3. Determine record UUID (preserve explicit or generate new)
        rec_id = record.id.strip() if record.id else str(uuid.uuid4())

        # 4. Serialize raw_data JSON
        raw_data_json = json.dumps(record.raw_data)

        # 5. Insert market research finding row
        try:
            cursor.execute(
                """
                INSERT INTO market_research_findings (
                    id, opportunity_id, source_type, source_name, source_url,
                    company_or_product, finding, evidence_summary, relevance,
                    raw_data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rec_id,
                    record.opportunity_id,
                    record.source_type,
                    record.source_name,
                    record.source_url,
                    record.company_or_product,
                    record.finding,
                    record.evidence_summary,
                    record.relevance,
                    raw_data_json,
                ),
            )
        except sqlite3.Error as err:
            raise MarketResearchRepositoryError(
                f"Failed to insert market_research_finding: {err}"
            ) from err

        logger.info(
            "Saved market research finding (id=%s) for opportunity '%s' regarding '%s'.",
            rec_id,
            record.opportunity_id,
            record.company_or_product,
        )
        return rec_id

    def get_by_id(
        self,
        finding_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[MarketResearchRecord]:
        """Retrieve and reconstruct a MarketResearchRecord by primary key ID.

        Args:
            finding_id: Primary key UUID of the market research finding.
            conn: Optional database connection.

        Returns:
            Optional[MarketResearchRecord]: Reconstructed record or None if not found.
        """
        if not finding_id or not finding_id.strip():
            return None

        clean_id = finding_id.strip()
        query = """
            SELECT id, opportunity_id, source_type, source_name, source_url,
                   company_or_product, finding, evidence_summary, relevance,
                   raw_data, created_at
            FROM market_research_findings
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

    def get_for_opportunity(
        self,
        opportunity_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[MarketResearchRecord]:
        """Retrieve all market research records for a specific opportunity ID in deterministic order.

        Args:
            opportunity_id: Opportunity UUID foreign key.
            conn: Optional database connection.

        Returns:
            list[MarketResearchRecord]: Reconstructed records ordered by created_at ASC, rowid ASC.
        """
        if not opportunity_id or not opportunity_id.strip():
            return []

        clean_opp_id = opportunity_id.strip()
        query = """
            SELECT id, opportunity_id, source_type, source_name, source_url,
                   company_or_product, finding, evidence_summary, relevance,
                   raw_data, created_at
            FROM market_research_findings
            WHERE opportunity_id = ?
            ORDER BY created_at ASC, rowid ASC;
        """
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(query, (clean_opp_id,))
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

        with get_db(self.db_path) as active_conn:
            cursor = active_conn.cursor()
            cursor.execute(query, (clean_opp_id,))
            rows = cursor.fetchall()
            return [self._reconstruct_record(cursor, r) for r in rows]

    # Aliases for convenient caller ergonomics
    get_market_research_by_id = get_by_id
    get_findings_for_opportunity = get_for_opportunity

    def _reconstruct_record(
        self,
        cursor: sqlite3.Cursor,
        row: sqlite3.Row,
    ) -> MarketResearchRecord:
        """Reconstruct a complete MarketResearchRecord instance from a market_research_findings database row."""
        raw_str = row["raw_data"]
        try:
            raw_dict = json.loads(raw_str) if raw_str else {}
            if not isinstance(raw_dict, dict):
                raw_dict = {}
        except (json.JSONDecodeError, TypeError):
            raw_dict = {}

        return MarketResearchRecord(
            opportunity_id=row["opportunity_id"],
            source_type=row["source_type"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            company_or_product=row["company_or_product"],
            finding=row["finding"],
            evidence_summary=row["evidence_summary"],
            relevance=row["relevance"],
            id=str(row["id"]) if row["id"] else None,
            raw_data=raw_dict,
        )
