"""Research run lifecycle management and persistence service.

Manages creation, execution state transitions, and metadata persistence
for research run sessions in the SQLite database.
"""

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Optional
import uuid

from config.settings import DATABASE_PATH
from src.common.database import get_db

logger = logging.getLogger(__name__)


class ResearchRunError(Exception):
    """Base exception for research run lifecycle operations."""
    pass


class RunNotFoundError(ResearchRunError):
    """Raised when a referenced research run does not exist."""
    pass


class InvalidLifecycleTransitionError(ResearchRunError):
    """Raised when an illegal run state transition is requested."""
    pass


# Allowed state transitions:
# initialized -> running
# running -> completed
# running -> failed
VALID_TRANSITIONS: dict[str, set[str]] = {
    "initialized": {"running"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


class ResearchRunService:
    """Service managing the lifecycle transitions and retrieval of research runs."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """Initialize the service.

        Args:
            db_path: Path to SQLite database. Defaults to DATABASE_PATH.
        """
        self.db_path = Path(db_path) if db_path else DATABASE_PATH

    def create_run(
        self,
        run_name: str,
        query: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Create a new research run session in the initialized state.

        Args:
            run_name: Human-readable name or label for the research run.
            query: Optional search or research query string.
            metadata: Optional dictionary of execution metadata.

        Returns:
            str: Generated unique run ID.

        Raises:
            ValueError: If run_name is empty or whitespace.
        """
        if not run_name or not run_name.strip():
            raise ValueError("run_name must be a non-empty string.")

        run_id = str(uuid.uuid4())
        clean_name = run_name.strip()
        clean_query = query.strip() if query else None
        metadata_json = json.dumps(metadata) if metadata is not None else None

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO research_runs (id, run_name, query, status, metadata)
                VALUES (?, ?, ?, 'initialized', ?);
                """,
                (run_id, clean_name, clean_query, metadata_json),
            )

        logger.info("Created research run '%s' (id=%s) in initialized state.", clean_name, run_id)
        return run_id

    def start_run(self, run_id: str) -> None:
        """Transition an initialized research run to running.

        Args:
            run_id: Unique research run identifier.

        Raises:
            RunNotFoundError: If run_id does not exist.
            InvalidLifecycleTransitionError: If the run is not in initialized state.
        """
        self._transition_run(run_id=run_id, target_status="running")

    def complete_run(self, run_id: str) -> None:
        """Transition a running research run to completed and set completion timestamp.

        Args:
            run_id: Unique research run identifier.

        Raises:
            RunNotFoundError: If run_id does not exist.
            InvalidLifecycleTransitionError: If the run is not in running state.
        """
        self._transition_run(run_id=run_id, target_status="completed")

    def fail_run(self, run_id: str, error_message: Optional[str] = None) -> None:
        """Transition a running research run to failed, recording failure details.

        Args:
            run_id: Unique research run identifier.
            error_message: Optional error message or explanation of failure.

        Raises:
            RunNotFoundError: If run_id does not exist.
            InvalidLifecycleTransitionError: If the run is not in running state.
        """
        self._transition_run(
            run_id=run_id,
            target_status="failed",
            error_message=error_message,
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a research run record by ID with parsed metadata.

        Args:
            run_id: Unique research run identifier.

        Returns:
            Optional[dict]: Run record dictionary with deserialized metadata, or None.
        """
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, run_name, query, status, metadata, created_at, completed_at
                FROM research_runs
                WHERE id = ?;
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            run_dict = dict(row)
            if run_dict.get("metadata") is not None:
                try:
                    run_dict["metadata"] = json.loads(run_dict["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return run_dict

    def _transition_run(
        self,
        run_id: str,
        target_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Internal helper validating and executing atomic lifecycle transitions."""
        if not run_id or not run_id.strip():
            raise RunNotFoundError("run_id must be a non-empty string.")

        clean_run_id = run_id.strip()

        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, metadata FROM research_runs WHERE id = ?;",
                (clean_run_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise RunNotFoundError(f"Research run '{clean_run_id}' not found.")

            current_status = row["status"]
            allowed = VALID_TRANSITIONS.get(current_status, set())

            if target_status not in allowed:
                raise InvalidLifecycleTransitionError(
                    f"Cannot transition research run '{clean_run_id}' from '{current_status}' "
                    f"to '{target_status}'. Valid next states: {sorted(list(allowed))}."
                )

            # Prepare update statements based on target status
            if target_status == "running":
                cursor.execute(
                    """
                    UPDATE research_runs
                    SET status = 'running'
                    WHERE id = ?;
                    """,
                    (clean_run_id,),
                )
            elif target_status == "completed":
                cursor.execute(
                    """
                    UPDATE research_runs
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (clean_run_id,),
                )
            elif target_status == "failed":
                meta: dict[str, Any] = {}
                if row["metadata"]:
                    try:
                        parsed = json.loads(row["metadata"])
                        if isinstance(parsed, dict):
                            meta = parsed
                        else:
                            meta = {"raw_metadata": parsed}
                    except (json.JSONDecodeError, TypeError):
                        meta = {"raw_metadata": row["metadata"]}

                if error_message is not None:
                    meta["error"] = error_message
                    meta["error_message"] = error_message

                meta_json = json.dumps(meta) if meta else None
                cursor.execute(
                    """
                    UPDATE research_runs
                    SET status = 'failed',
                        completed_at = CURRENT_TIMESTAMP,
                        metadata = ?
                    WHERE id = ?;
                    """,
                    (meta_json, clean_run_id),
                )

        logger.info(
            "Research run '%s' transitioned: %s -> %s",
            clean_run_id,
            current_status,
            target_status,
        )
