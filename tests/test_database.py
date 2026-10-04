"""Database foundation verification tests."""

import sqlite3
import unittest

from config.settings import DATABASE_PATH
from src.common.database import get_connection, get_db, init_db


class TestDatabaseFoundation(unittest.TestCase):
    """Test suite for SQLite database foundation."""

    EXPECTED_TABLES = [
        "research_runs",
        "patents",
        "extracted_problems",
        "startup_opportunities",
    ]

    def test_database_initialization_and_opening(self):
        """1 & 2: Verify initialization runs and database can be opened."""
        db_path = init_db()
        self.assertTrue(db_path.exists(), f"Database file not found at {db_path}")

        # Verify connection can be opened
        conn = get_connection(db_path)
        try:
            self.assertIsInstance(conn, sqlite3.Connection)
        finally:
            conn.close()

    def test_expected_tables_exist_and_queryable(self):
        """3: Verify expected tables exist and can be queried."""
        with get_db(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row["name"] for row in cursor.fetchall()}

            for expected in self.EXPECTED_TABLES:
                self.assertIn(expected, tables, f"Expected table '{expected}' not found in database")
                # Ensure each table can be queried directly with SELECT
                cursor.execute(f"SELECT * FROM {expected} LIMIT 1;")
                cursor.fetchall()

    def test_foreign_key_support_enabled(self):
        """4: Verify foreign-key support is enabled and enforced."""
        with get_db(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys;")
            fk_status = cursor.fetchone()[0]
            self.assertEqual(fk_status, 1, "Foreign key support is not enabled (PRAGMA foreign_keys != 1)")

            # Test enforcement: inserting a child record with invalid FK must fail
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO patents (id, run_id, patent_number)
                    VALUES ('test_p1', 'non_existent_run_id', 'US123456');
                    """
                )

    def test_no_fake_or_sample_records_inserted(self):
        """5: Verify no fake/sample research records are present."""
        with get_db(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            for table in self.EXPECTED_TABLES:
                cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table};")
                count = cursor.fetchone()["cnt"]
                self.assertEqual(
                    count,
                    0,
                    f"Table '{table}' contains {count} records, expected 0 (no sample/fake data allowed)",
                )


if __name__ == "__main__":
    unittest.main()
