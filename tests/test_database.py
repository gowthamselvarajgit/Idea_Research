"""Database foundation and schema verification tests."""

import sqlite3
import unittest

from config.settings import DATABASE_PATH
from src.common.database import get_connection, get_db, init_db


class TestDatabaseFoundation(unittest.TestCase):
    """Test suite for SQLite database foundation and updated schema."""

    EXPECTED_TABLES = [
        "research_runs",
        "patents",
        "run_patents",
        "extracted_problems",
        "problem_patents",
        "startup_opportunities",
        "opportunity_problems",
    ]

    def test_database_initialization_and_opening(self):
        """1 & 2: Verify initialization runs and database can be opened."""
        db_path = init_db()
        self.assertTrue(db_path.exists(), f"Database file not found at {db_path}")

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
                cursor.execute(f"SELECT * FROM {expected} LIMIT 1;")
                cursor.fetchall()

    def test_foreign_key_support_enabled_and_enforced(self):
        """4: Verify foreign-key support is enabled and enforced on junctions."""
        with get_db(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys;")
            fk_status = cursor.fetchone()[0]
            self.assertEqual(fk_status, 1, "Foreign key support is not enabled (PRAGMA foreign_keys != 1)")

            # Test enforcement on run_patents junction
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO run_patents (run_id, patent_id)
                    VALUES ('non_existent_run', 'non_existent_patent');
                    """
                )

            # Test enforcement on problem_patents junction
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO problem_patents (problem_id, patent_id)
                    VALUES ('non_existent_problem', 'non_existent_patent');
                    """
                )

            # Test enforcement on opportunity_problems junction
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO opportunity_problems (opportunity_id, problem_id)
                    VALUES ('non_existent_opportunity', 'non_existent_problem');
                    """
                )

    def test_patent_number_is_globally_unique(self):
        """Verify that patents.patent_number is globally unique across runs."""
        conn = get_connection(DATABASE_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patents (id, patent_number, title)
                VALUES ('pat_temp_1', 'US9999999A', 'First Entry');
                """
            )
            # Attempt to insert a second patent with the identical patent_number
            with self.assertRaises(sqlite3.IntegrityError):
                cursor.execute(
                    """
                    INSERT INTO patents (id, patent_number, title)
                    VALUES ('pat_temp_2', 'US9999999A', 'Duplicate Entry');
                    """
                )
        finally:
            conn.rollback()
            conn.close()

    def test_patent_source_url_column_exists(self):
        """Verify dedicated canonical source_url exists on patents table."""
        with get_db(DATABASE_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(patents);")
            columns = {row["name"] for row in cursor.fetchall()}
            self.assertIn("source_url", columns, "Column 'source_url' missing from patents table")

    def test_junction_tables_functionality(self):
        """Verify multi-patent linking to runs, problems, and opportunities."""
        conn = get_connection(DATABASE_PATH)
        try:
            cursor = conn.cursor()

            # 1. Setup two research runs
            cursor.execute("INSERT INTO research_runs (id, run_name) VALUES ('run_a', 'Run A');")
            cursor.execute("INSERT INTO research_runs (id, run_name) VALUES ('run_b', 'Run B');")

            # 2. Setup two distinct patents
            cursor.execute(
                "INSERT INTO patents (id, patent_number, title, source_url) VALUES ('pat_1', 'US1001', 'Patent One', 'https://patents.google.com/patent/US1001');"
            )
            cursor.execute(
                "INSERT INTO patents (id, patent_number, title, source_url) VALUES ('pat_2', 'US1002', 'Patent Two', 'https://patents.google.com/patent/US1002');"
            )

            # 3. Test run_patents: Patent 1 discovered in BOTH Run A and Run B (deduplicated master patent)
            cursor.execute("INSERT INTO run_patents (run_id, patent_id) VALUES ('run_a', 'pat_1');")
            cursor.execute("INSERT INTO run_patents (run_id, patent_id) VALUES ('run_b', 'pat_1');")
            cursor.execute("INSERT INTO run_patents (run_id, patent_id) VALUES ('run_a', 'pat_2');")

            cursor.execute("SELECT COUNT(*) FROM run_patents WHERE patent_id = 'pat_1';")
            self.assertEqual(cursor.fetchone()[0], 2, "Patent 1 should be linked to 2 distinct runs")

            # 4. Test problem_patents: Single problem synthesized from MULTIPLE patents (pat_1 and pat_2)
            cursor.execute(
                "INSERT INTO extracted_problems (id, run_id, problem_title) VALUES ('prob_1', 'run_a', 'Heat Dissipation Bottleneck');"
            )
            cursor.execute("INSERT INTO problem_patents (problem_id, patent_id) VALUES ('prob_1', 'pat_1');")
            cursor.execute("INSERT INTO problem_patents (problem_id, patent_id) VALUES ('prob_1', 'pat_2');")

            cursor.execute("SELECT COUNT(*) FROM problem_patents WHERE problem_id = 'prob_1';")
            self.assertEqual(cursor.fetchone()[0], 2, "Problem 1 should link to 2 patents")

            # 5. Test opportunity_problems: Single opportunity addressing MULTIPLE problems
            cursor.execute(
                "INSERT INTO extracted_problems (id, run_id, problem_title) VALUES ('prob_2', 'run_a', 'Material Degradation');"
            )
            cursor.execute(
                "INSERT INTO startup_opportunities (id, run_id, opportunity_title) VALUES ('opp_1', 'run_a', 'NextGen Heat Management');"
            )
            cursor.execute("INSERT INTO opportunity_problems (opportunity_id, problem_id) VALUES ('opp_1', 'prob_1');")
            cursor.execute("INSERT INTO opportunity_problems (opportunity_id, problem_id) VALUES ('opp_1', 'prob_2');")

            cursor.execute("SELECT COUNT(*) FROM opportunity_problems WHERE opportunity_id = 'opp_1';")
            self.assertEqual(cursor.fetchone()[0], 2, "Opportunity 1 should reference 2 problems")

        finally:
            # Rollback all test insertions to guarantee database stays completely empty
            conn.rollback()
            conn.close()

    def test_no_fake_or_sample_records_persisted(self):
        """5: Verify no fake/sample research records exist in any table."""
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
