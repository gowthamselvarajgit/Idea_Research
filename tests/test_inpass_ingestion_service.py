"""Tests for InPassIngestionService connecting InPASS search, parsing, and SQLite persistence."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.common.database import get_db, init_db
from src.common.research_runs import ResearchRunService
from src.patents.inpass_client import (
    InPassCaptchaTimeoutError,
    InPassClient,
    InPassNavigationError,
    InPassSearchConfig,
    InPassSearchResultRow,
)
from src.patents.inpass_ingestion_service import (
    InPassIngestionError,
    InPassIngestionPersistenceError,
    InPassIngestionResult,
    InPassIngestionSearchError,
    InPassIngestionService,
)
from src.patents.models import InPassPatentRecord, PatentRecord, PersonOrOrganization
from src.patents.repository import PatentRepository
from src.patents.run_reader import ResearchRunPatentReader


class TestInPassIngestionService(unittest.TestCase):
    """Test suite for InPassIngestionService with isolated SQLite databases and mock clients."""

    def setUp(self) -> None:
        """Create isolated temporary database and service instances."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inpass_ingestion.db"
        init_db(self.db_path)

        self.repo = PatentRepository(self.db_path)
        self.run_service = ResearchRunService(self.db_path)
        self.reader = ResearchRunPatentReader(self.db_path)

        self.mock_client = MagicMock(spec=InPassClient)
        self.service = InPassIngestionService(client=self.mock_client, repository=self.repo)

    def tearDown(self) -> None:
        """Clean up temporary resources."""
        self.temp_dir.cleanup()

    def _sample_inpass_record(
        self,
        app_num: str = "202641109752",
        title: str = "INLINE OPTICAL DETECTION OF MICROPLASTICS",
        pub_num: str = "38/2026",
    ) -> InPassPatentRecord:
        """Helper to create a realistic InPassPatentRecord."""
        applicant = PersonOrOrganization(
            name="Vivekanandha College of Engineering for Women",
            address="Elayampalayam, Tiruchengode",
            country="India",
            nationality="India",
        )
        inventor = PersonOrOrganization(
            name="T.ASHA",
            address="Department of ECE",
            country="India",
            nationality="India",
        )
        return InPassPatentRecord(
            application_number=app_num,
            publication_number=pub_num,
            publication_date="18/09/2026",
            filing_date="12/09/2026",
            title=title,
            ipc="G01N 21/47, G01N 33/18",
            abstract="Optical sensing system for detecting microplastics in flowing water.",
            specification="Detailed description of optical chamber and sensors.",
            claims="1. An optical sensing system comprising a chamber.",
            applicants=[applicant],
            inventors=[inventor],
            source="INPASS",
            source_url=f"https://iprsearch.ipindia.gov.in/publicsearch?app={app_num}",
        )

    def test_ingest_search_run_success(self) -> None:
        """Verify full ingestion workflow: configure, CAPTCHA wait, parse, persist, and link."""
        run_id = self.run_service.create_run(run_name="Water Research", query="WATER")
        self.run_service.start_run(run_id)

        # Mock client search results
        row1 = InPassSearchResultRow(application_number="202641109752", title="Water Patent A")
        row2 = InPassSearchResultRow(application_number="202641109913", title="Water Patent B")
        self.mock_client.read_current_page_results.return_value = [row1, row2]

        # Mock patent details retrieval
        rec1 = self._sample_inpass_record("202641109752", "Water Patent A")
        rec2 = self._sample_inpass_record("202641109913", "Water Patent B")

        def mock_get_details(app_num, return_to_search=True):
            if app_num == "202641109752":
                return rec1
            return rec2

        self.mock_client.get_patent_details.side_effect = mock_get_details

        callback_mock = MagicMock()
        result = self.service.ingest_search_run(
            run_id=run_id,
            search_config_or_query="WATER",
            max_results=2,
            on_captcha_required=callback_mock,
        )

        # Telemetry & result assertions
        self.assertIsInstance(result, InPassIngestionResult)
        self.assertEqual(result.run_id, run_id)
        self.assertEqual(result.query, "WATER")
        self.assertEqual(result.discovered, 2)
        self.assertEqual(result.ingested, 2)
        self.assertEqual(result.inserted, 2)
        self.assertEqual(result.existing, 0)
        self.assertEqual(result.linked, 2)
        self.assertEqual(len(result.records), 2)

        # Client method interactions
        self.mock_client.open_search_page.assert_called_once()
        self.mock_client.configure_search.assert_called_once()
        self.mock_client.wait_for_captcha_and_results.assert_called_once_with(
            on_captcha_required=callback_mock,
            captcha_solver=None,
        )

        # Verify database persistence
        patents_in_db = self.repo.get_patents_for_run(run_id)
        self.assertEqual(len(patents_in_db), 2)
        stored_numbers = {p["patent_number"] for p in patents_in_db}
        self.assertIn("IN202641109752A", stored_numbers)
        self.assertIn("IN202641109913A", stored_numbers)

    def test_ingest_search_run_explicit_application_numbers(self) -> None:
        """Verify that passing explicit application_numbers filters results accordingly."""
        run_id = self.run_service.create_run(run_name="Targeted InPASS Run")
        row1 = InPassSearchResultRow(application_number="202641109752", title="Water Patent A")
        row2 = InPassSearchResultRow(application_number="202641109913", title="Water Patent B")
        row3 = InPassSearchResultRow(application_number="202641109024", title="Water Patent C")
        self.mock_client.read_current_page_results.return_value = [row1, row2, row3]

        rec2 = self._sample_inpass_record("202641109913", "Water Patent B")
        self.mock_client.get_patent_details.return_value = rec2

        result = self.service.ingest_search_run(
            run_id=run_id,
            search_config_or_query="WATER",
            application_numbers=["202641109913"],
        )

        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.records[0].application_number, "202641109913")
        self.mock_client.get_patent_details.assert_called_once_with("202641109913", return_to_search=True)

    def test_ingest_search_run_max_results_limit(self) -> None:
        """Verify max_results limits how many details are fetched and persisted."""
        run_id = self.run_service.create_run(run_name="Limited InPASS Run")
        rows = [
            InPassSearchResultRow(application_number=f"20264110000{i}", title=f"Patent {i}")
            for i in range(5)
        ]
        self.mock_client.read_current_page_results.return_value = rows
        self.mock_client.get_patent_details.side_effect = lambda app, **kw: self._sample_inpass_record(app)

        result = self.service.ingest_search_run(
            run_id=run_id,
            search_config_or_query="WATER",
            max_results=2,
        )

        self.assertEqual(result.discovered, 5)
        self.assertEqual(result.ingested, 2)
        self.assertEqual(self.mock_client.get_patent_details.call_count, 2)

    def test_validation_errors(self) -> None:
        """Verify validation errors for bad arguments."""
        with self.assertRaises(ValueError):
            self.service.ingest_search_run(run_id="", search_config_or_query="WATER")

        with self.assertRaises(ValueError):
            self.service.ingest_search_run(run_id="run-1", search_config_or_query="WATER", max_results=0)

    def test_search_failure_raises_ingestion_search_error(self) -> None:
        """Verify client errors during search raise InPassIngestionSearchError."""
        run_id = self.run_service.create_run(run_name="Failing Run")
        self.mock_client.open_search_page.side_effect = InPassNavigationError("Timeout opening portal")

        with self.assertRaises(InPassIngestionSearchError):
            self.service.ingest_search_run(run_id=run_id, search_config_or_query="WATER")

    def test_duplicate_patent_safe_handling(self) -> None:
        """Verify that ingesting duplicate patents across runs updates safely without error."""
        run_id_1 = self.run_service.create_run(run_name="Run 1")
        run_id_2 = self.run_service.create_run(run_name="Run 2")

        rec = self._sample_inpass_record("202641109752", "Original Title")
        self.mock_client.read_current_page_results.return_value = [
            InPassSearchResultRow(application_number="202641109752", title="Original Title")
        ]
        self.mock_client.get_patent_details.return_value = rec

        # First ingestion in Run 1: inserted = 1
        res1 = self.service.ingest_search_run(run_id=run_id_1, search_config_or_query="WATER")
        self.assertEqual(res1.inserted, 1)
        self.assertEqual(res1.existing, 0)
        self.assertEqual(res1.linked, 1)

        # Second ingestion in Run 2 with updated title: existing = 1, inserted = 0
        rec_updated = self._sample_inpass_record("202641109752", "Updated Title")
        self.mock_client.get_patent_details.return_value = rec_updated

        res2 = self.service.ingest_search_run(run_id=run_id_2, search_config_or_query="WATER")
        self.assertEqual(res2.inserted, 0)
        self.assertEqual(res2.existing, 1)
        self.assertEqual(res2.linked, 1)

        # Third ingestion in Run 2 again: existing = 1, linked = 0 (idempotent link)
        res3 = self.service.ingest_search_run(run_id=run_id_2, search_config_or_query="WATER")
        self.assertEqual(res3.inserted, 0)
        self.assertEqual(res3.existing, 1)
        self.assertEqual(res3.linked, 0)

        # Database state: only 1 patent row in patents table
        with get_db(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patents;")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT title FROM patents WHERE patent_number = 'IN202641109752A';")
            self.assertEqual(cursor.fetchone()[0], "Updated Title")

            # run_patents junction links: 1 link for run 1, 1 link for run 2
            cursor.execute("SELECT COUNT(*) FROM run_patents;")
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_ingest_explicit_applications_list(self) -> None:
        """Verify ingest_applications directly ingests application numbers."""
        run_id = self.run_service.create_run(run_name="Explicit List Run")
        rec = self._sample_inpass_record("202641109752")
        self.mock_client.get_patent_details.return_value = rec

        result = self.service.ingest_applications(
            run_id=run_id,
            application_numbers=["202641109752"],
        )

        self.assertEqual(result.ingested, 1)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.linked, 1)

    def test_end_to_end_research_run_integration(self) -> None:
        """Integration test proving:

        research_run
        → InPASS search result
        → parsed InPassPatentRecord
        → persisted canonical patent in SQLite
        → run_patents association
        → retrieved through ResearchRunPatentReader.
        """
        # 1. Initialize and start research run
        run_id = self.run_service.create_run(
            run_name="Microplastics InPASS Study",
            query="MICROPLASTICS WATER",
            metadata={"source": "INPASS", "priority": "high"},
        )
        self.run_service.start_run(run_id)

        # 2. Simulate InPASS search results arrival
        row = InPassSearchResultRow(
            application_number="202641109752",
            title="A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
            date="12/09/2026",
            status="Published",
        )
        self.mock_client.read_current_page_results.return_value = [row]

        # 3. Simulate PatentDetails parsed record
        parsed_record = self._sample_inpass_record(
            app_num="202641109752",
            title="A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
        )
        self.mock_client.get_patent_details.return_value = parsed_record

        # 4. Ingest into research run
        result = self.service.ingest_search_run(
            run_id=run_id,
            search_config_or_query=InPassSearchConfig(keyword="MICROPLASTICS WATER"),
            max_results=1,
        )

        # 5. Complete research run
        self.run_service.complete_run(run_id)

        # 6. Verify run status
        run_data = self.run_service.get_run(run_id)
        self.assertIsNotNone(run_data)
        self.assertEqual(run_data["status"], "completed")

        # 7. Verify persisted patent via PatentRepository
        patents = self.repo.get_patents_for_run(run_id)
        self.assertEqual(len(patents), 1)
        db_patent = patents[0]
        self.assertEqual(db_patent["patent_number"], "IN202641109752A")
        self.assertEqual(
            db_patent["title"],
            "A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
        )
        self.assertEqual(db_patent["filing_date"], "12/09/2026")
        self.assertEqual(db_patent["publication_date"], "18/09/2026")
        self.assertEqual(db_patent["assignee"], "Vivekanandha College of Engineering for Women")
        self.assertIn("Optical sensing system", db_patent["abstract"])

        # 8. Verify canonical reconstruction via ResearchRunPatentReader
        reconstructed = self.reader.get_patents_for_run(run_id)
        self.assertEqual(len(reconstructed), 1)
        patent_obj = reconstructed[0]
        self.assertIsInstance(patent_obj, PatentRecord)
        self.assertEqual(patent_obj.patent_number, "IN202641109752A")
        self.assertEqual(patent_obj.assignee, "Vivekanandha College of Engineering for Women")
        self.assertEqual(patent_obj.raw_data["source"], "INPASS")
        self.assertEqual(patent_obj.raw_data["application_number"], "202641109752")
        self.assertEqual(patent_obj.raw_data["publication_number"], "38/2026")
        self.assertIn("specification", patent_obj.raw_data)
        self.assertIn("claims", patent_obj.raw_data)

    def test_ingest_search_run_forwards_captcha_solver(self):
        """Verify captcha_solver is passed through to wait_for_captcha_and_results."""
        run_id = self.run_service.create_run(run_name="Solver Test Run")
        self.mock_client.read_current_page_results.return_value = []
        solver_mock = MagicMock(return_value="SOLV1")

        self.service.ingest_search_run(
            run_id=run_id,
            search_config_or_query="WATER",
            captcha_solver=solver_mock,
        )

        self.mock_client.wait_for_captcha_and_results.assert_called_once_with(
            on_captcha_required=None,
            captcha_solver=solver_mock,
        )


if __name__ == "__main__":
    unittest.main()

