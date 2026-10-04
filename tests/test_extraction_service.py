"""Unit tests for ProblemExtractionService using mocked dependencies."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.patents.models import PatentRecord
from src.problems.ai_client import AIClientError, AIClientTimeoutError
from src.problems.extraction_contract import ProblemContractValidationError
from src.problems.extraction_prompt import (
    PROBLEM_EXTRACTION_SYSTEM_PROMPT,
    format_patent_extraction_user_prompt,
)
from src.problems.extraction_service import (
    PatentNotInRunError,
    ProblemExtractionAIError,
    ProblemExtractionPersistenceError,
    ProblemExtractionService,
    ProblemExtractionServiceError,
)
from src.problems.models import ProblemRecord
from src.problems.output_parser import (
    ProblemOutputParseError,
    parse_problem_extraction_output,
)
from src.problems.patent_input import build_patent_extraction_input
from src.problems.repository import ProblemRepository, ProblemRepositoryError


class TestProblemExtractionService(unittest.TestCase):
    """Test suite for ProblemExtractionService with mocked dependencies."""

    def setUp(self) -> None:
        """Set up test fixtures with fake patent, valid AI output, and mocks."""
        self.mock_ai_client = MagicMock()
        self.mock_repository = MagicMock(spec=ProblemRepository)
        self.mock_patent_reader = MagicMock()

        self.sample_patent = PatentRecord(
            patent_number="US11223344B2",
            title="Solid-state battery thermal management system",
            abstract=(
                "A battery pack thermal dissipation architecture utilizing phase change "
                "materials and embedded micro-channels to prevent localized thermal hotspots "
                "during high-rate fast-charging cycles."
            ),
            filing_date="2022-01-15",
            publication_date="2023-08-10",
            assignee="NextGen Power Corp",
            source_url="https://patents.google.com/patent/US11223344B2/en",
            raw_data={"test": True},
        )

        self.valid_ai_dict = {
            "problem_title": "Localized thermal hotspots during high-rate battery charging",
            "problem_description": (
                "High current density during fast charging causes non-uniform heating and "
                "accelerated cell degradation."
            ),
            "affected_users": "EV Battery Pack Thermal Engineers",
            "bottleneck_type": "thermal runaway and localized degradation",
            "technical_domain": "Energy Storage Systems",
            "current_workaround": "Throttling charge rate and bulky liquid cooling plates",
            "problem_frequency": "daily",
            "problem_severity": "high",
            "evidence_summary": (
                "Patent notes uneven thermal distribution during fast charging leads to "
                "premature capacity loss."
            ),
            "evidence_confidence": "high",
        }
        self.valid_ai_json = json.dumps(self.valid_ai_dict)

        self.mock_ai_client.generate.return_value = self.valid_ai_json
        self.mock_patent_reader.get_patents_for_run.return_value = [self.sample_patent]
        self.mock_repository.save_problem.return_value = "prob-uuid-1234"
        self.mock_repository.get_problem_for_run_and_patent.return_value = None

        self.service = ProblemExtractionService(
            ai_client=self.mock_ai_client,
            repository=self.mock_repository,
            patent_reader=self.mock_patent_reader,
        )

    def test_successful_extraction_and_persistence(self) -> None:
        """Verify successful end-to-end extraction and persistence."""
        run_id = "run-001"
        patent_id = "US11223344B2"

        result = self.service.extract_problem_for_patent(run_id=run_id, patent_id=patent_id)

        self.assertIsInstance(result, ProblemRecord)
        self.assertEqual(result.problem_title, self.valid_ai_dict["problem_title"])
        self.assertEqual(result.affected_users, self.valid_ai_dict["affected_users"])
        self.assertEqual(result.bottleneck_type, self.valid_ai_dict["bottleneck_type"])
        self.assertEqual(result.problem_frequency, "daily")
        self.assertEqual(result.problem_severity, "high")
        self.assertEqual(result.evidence_confidence, "high")
        self.assertEqual(result.source_patent_numbers, ("US11223344B2",))
        self.assertEqual(result.id, "prob-uuid-1234")

    def test_correct_patent_input_passed_to_prompt_builder(self) -> None:
        """Verify correct patent input dictionary is passed into the prompt builder."""
        with patch(
            "src.problems.extraction_service.build_patent_extraction_input",
            wraps=build_patent_extraction_input,
        ) as mock_input_builder:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

            mock_input_builder.assert_called_once_with(self.sample_patent)
            call_arg = mock_input_builder.call_args[0][0]
            self.assertEqual(call_arg.patent_number, "US11223344B2")
            self.assertEqual(call_arg.title, self.sample_patent.title)
            self.assertEqual(call_arg.abstract, self.sample_patent.abstract)

    def test_system_prompt_passed_unchanged(self) -> None:
        """Verify that the system prompt passed to AI client matches PROBLEM_EXTRACTION_SYSTEM_PROMPT."""
        self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.mock_ai_client.generate.assert_called_once()
        _, kwargs = self.mock_ai_client.generate.call_args
        self.assertEqual(kwargs["system_prompt"], PROBLEM_EXTRACTION_SYSTEM_PROMPT)

    def test_user_prompt_passed_correctly(self) -> None:
        """Verify that the user prompt passed to AI client is correctly formatted."""
        expected_input = build_patent_extraction_input(self.sample_patent)
        expected_user_prompt = format_patent_extraction_user_prompt(expected_input)

        self.service.extract_problem_for_patent("run-001", "US11223344B2")

        _, kwargs = self.mock_ai_client.generate.call_args
        self.assertEqual(kwargs["user_prompt"], expected_user_prompt)

    def test_ai_client_called_exactly_once(self) -> None:
        """Verify that the injected AI client generate method is called exactly once."""
        self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertEqual(self.mock_ai_client.generate.call_count, 1)

    def test_parser_receives_ai_response_and_source_patent_number(self) -> None:
        """Verify that the parser receives the exact AI text and source patent number tuple."""
        with patch(
            "src.problems.extraction_service.parse_problem_extraction_output",
            wraps=parse_problem_extraction_output,
        ) as mock_parser:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

            mock_parser.assert_called_once_with(
                response_text=self.valid_ai_json,
                source_patent_numbers=("US11223344B2",),
            )

    def test_repository_receives_parsed_problem_record_and_run_id(self) -> None:
        """Verify that the repository receives the parsed ProblemRecord and returns record with ID."""
        result = self.service.extract_problem_for_patent("run-xyz", "US11223344B2")

        call_args = self.mock_repository.save_problem.call_args
        self.assertIsNotNone(call_args)
        saved_problem = call_args[1]["problem"]
        self.assertIsNone(saved_problem.id)  # before save, id was None
        self.assertEqual(call_args[1]["run_id"], "run-xyz")
        self.assertEqual(result.id, "prob-uuid-1234")  # after save, id is populated

    def test_patent_not_belonging_to_run(self) -> None:
        """Verify that PatentNotInRunError is raised when patent is not in the research run."""
        # Reader returns patents, but none match the requested patent
        self.mock_patent_reader.get_patents_for_run.return_value = [self.sample_patent]

        with self.assertRaises(PatentNotInRunError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US9999999B1")

        self.assertIn("US9999999B1", str(ctx.exception))
        self.assertIn("run-001", str(ctx.exception))
        self.assertIsInstance(ctx.exception, ProblemExtractionServiceError)

        # AI client and repository must never be called
        self.mock_ai_client.generate.assert_not_called()
        self.mock_repository.save_problem.assert_not_called()

    def test_patent_not_in_run_empty_run(self) -> None:
        """Verify PatentNotInRunError when research run has zero patents."""
        self.mock_patent_reader.get_patents_for_run.return_value = []

        with self.assertRaises(PatentNotInRunError):
            self.service.extract_problem_for_patent("empty-run", "US11223344B2")

        self.mock_ai_client.generate.assert_not_called()
        self.mock_repository.save_problem.assert_not_called()

    def test_ai_client_failure(self) -> None:
        """Verify that an AI failure raises ProblemExtractionAIError with cause preserved."""
        original_error = AIClientTimeoutError("Subprocess agy timed out after 120s.")
        self.mock_ai_client.generate.side_effect = original_error

        with self.assertRaises(ProblemExtractionAIError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertIs(ctx.exception.__cause__, original_error)
        self.assertIsInstance(ctx.exception, ProblemExtractionServiceError)
        # Persistence must not occur
        self.mock_repository.save_problem.assert_not_called()

    def test_parser_failure_malformed_json(self) -> None:
        """Verify that parser failure raises ProblemExtractionServiceError with cause preserved."""
        self.mock_ai_client.generate.return_value = "Not valid json at all"

        with self.assertRaises(ProblemExtractionServiceError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertIsNotNone(ctx.exception.__cause__)
        self.assertIn("Failed to parse", str(ctx.exception))
        # Persistence must not occur
        self.mock_repository.save_problem.assert_not_called()

    def test_parser_failure_missing_keys(self) -> None:
        """Verify that parser failure due to missing keys raises ProblemExtractionServiceError."""
        incomplete_json = json.dumps({"problem_title": "Only one field"})
        self.mock_ai_client.generate.return_value = incomplete_json

        with self.assertRaises(ProblemExtractionServiceError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertIsNotNone(ctx.exception.__cause__)
        self.mock_repository.save_problem.assert_not_called()

    def test_repository_failure(self) -> None:
        """Verify that repository save failure raises ProblemExtractionPersistenceError with cause."""
        db_error = ProblemRepositoryError("SQLite database locked.")
        self.mock_repository.save_problem.side_effect = db_error

        with self.assertRaises(ProblemExtractionPersistenceError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertIs(ctx.exception.__cause__, db_error)
        self.assertIsInstance(ctx.exception, ProblemExtractionServiceError)

    def test_invalid_run_id(self) -> None:
        """Verify that invalid run_id values raise ProblemExtractionServiceError."""
        invalid_ids = ["", "   ", None, 123, []]
        for invalid in invalid_ids:
            with self.subTest(invalid_run_id=invalid):
                with self.assertRaises(ProblemExtractionServiceError):
                    self.service.extract_problem_for_patent(run_id=invalid, patent_id="US11223344B2")

        self.mock_patent_reader.get_patents_for_run.assert_not_called()
        self.mock_ai_client.generate.assert_not_called()
        self.mock_repository.save_problem.assert_not_called()

    def test_invalid_patent_id(self) -> None:
        """Verify that invalid patent_id values raise ProblemExtractionServiceError."""
        invalid_ids = ["", "   ", None, 123, []]
        for invalid in invalid_ids:
            with self.subTest(invalid_patent_id=invalid):
                with self.assertRaises(ProblemExtractionServiceError):
                    self.service.extract_problem_for_patent(run_id="run-001", patent_id=invalid)

        self.mock_patent_reader.get_patents_for_run.assert_not_called()
        self.mock_ai_client.generate.assert_not_called()
        self.mock_repository.save_problem.assert_not_called()

    def test_patent_reader_failure(self) -> None:
        """Verify that an unexpected patent reader exception raises ProblemExtractionServiceError."""
        self.mock_patent_reader.get_patents_for_run.side_effect = RuntimeError("Disk error reading run")

        with self.assertRaises(ProblemExtractionServiceError) as ctx:
            self.service.extract_problem_for_patent("run-001", "US11223344B2")

        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        self.mock_ai_client.generate.assert_not_called()
        self.mock_repository.save_problem.assert_not_called()

    def test_constructor_dependency_injection(self) -> None:
        """Verify constructor enforces required dependencies."""
        with self.assertRaises(ValueError):
            ProblemExtractionService(ai_client=None, repository=self.mock_repository, patent_reader=self.mock_patent_reader)

        with self.assertRaises(ValueError):
            ProblemExtractionService(ai_client=self.mock_ai_client, repository=None, patent_reader=self.mock_patent_reader)

        with self.assertRaises(ValueError):
            ProblemExtractionService(ai_client=self.mock_ai_client, repository=self.mock_repository, patent_reader=None)

    def test_constructor_supports_problem_repository_kwarg(self) -> None:
        """Verify constructor supports problem_repository keyword argument."""
        service = ProblemExtractionService(
            ai_client=self.mock_ai_client,
            problem_repository=self.mock_repository,
            patent_reader=self.mock_patent_reader,
        )
        self.assertIs(service.repository, self.mock_repository)

    def test_patent_matched_with_punctuation_variations(self) -> None:
        """Verify patent can be matched when formatted with spaces/dashes."""
        result = self.service.extract_problem_for_patent("run-001", "US 11,223,344-B2")
        self.assertEqual(result.source_patent_numbers, ("US11223344B2",))

    def test_extract_problems_for_run_with_multiple_patents(self) -> None:
        """Verify that extract_problems_for_run retrieves patents exactly once and processes in order."""
        patent1 = PatentRecord(
            patent_number="IN202641114086A",
            title="Pollution Monitoring Robot",
            abstract="ESP32 based monitoring robot.",
            filing_date="2024-01-10",
            publication_date="2024-06-20",
            assignee="Tech University",
            source_url="https://ipindiaservices.gov.in/test1",
        )
        patent2 = PatentRecord(
            patent_number="IN202641114195A",
            title="Swarm Agriculture Monitoring System",
            abstract="Swarm based monitoring system.",
            filing_date="2024-02-15",
            publication_date="2024-07-15",
            assignee="AgriTech Labs",
            source_url="https://ipindiaservices.gov.in/test2",
        )
        self.mock_patent_reader.get_patents_for_run.return_value = [patent1, patent2]

        prob1 = ProblemRecord(
            problem_title="Water pollution in closed drains",
            problem_description="Manual inspection is hazardous.",
            affected_users="Sanitation workers",
            bottleneck_type="Access difficulty",
            technical_domain="Robotics",
            current_workaround="Manual rods",
            problem_frequency="weekly",
            problem_severity="high",
            evidence_summary="Patent addresses drain inspection.",
            evidence_confidence="high",
            source_patent_numbers=("IN202641114086A",),
        )
        prob2 = ProblemRecord(
            problem_title="Crop disease spread across large fields",
            problem_description="Delayed detection destroys yield.",
            affected_users="Farmers",
            bottleneck_type="Scalable monitoring",
            technical_domain="Agriculture",
            current_workaround="Visual spot checks",
            problem_frequency="daily",
            problem_severity="critical",
            evidence_summary="Patent details swarm drone surveillance.",
            evidence_confidence="high",
            source_patent_numbers=("IN202641114195A",),
        )

        with patch.object(self.service, "_extract_problem_from_record", side_effect=[prob1, prob2]) as mock_extract:
            results = self.service.extract_problems_for_run("run-test-123")

            # 1. get_patents_for_run called exactly once
            self.mock_patent_reader.get_patents_for_run.assert_called_once_with("run-test-123")

            # 2. Both patents passed directly into extraction helper
            self.assertEqual(mock_extract.call_count, 2)
            mock_extract.assert_any_call(target_patent=patent1, run_id="run-test-123")
            mock_extract.assert_any_call(target_patent=patent2, run_id="run-test-123")

            # 3. Order preserved and return values correct
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], prob1)
            self.assertEqual(results[1], prob2)

    def test_extract_problems_for_run_fault_isolation(self) -> None:
        """Verify that a failure on one patent does not abort extraction for remaining patents."""
        patent1 = PatentRecord(
            patent_number="IN202641114086A",
            title="Pollution Monitoring Robot",
            abstract="ESP32 based monitoring robot.",
            filing_date="2024-01-10",
            publication_date="2024-06-20",
            assignee="Tech University",
            source_url="https://ipindiaservices.gov.in/test1",
        )
        patent2 = PatentRecord(
            patent_number="IN202641114195A",
            title="Swarm Agriculture Monitoring System",
            abstract="Swarm based monitoring system.",
            filing_date="2024-02-15",
            publication_date="2024-07-15",
            assignee="AgriTech Labs",
            source_url="https://ipindiaservices.gov.in/test2",
        )
        self.mock_patent_reader.get_patents_for_run.return_value = [patent1, patent2]

        prob2 = ProblemRecord(
            problem_title="Crop disease spread across large fields",
            problem_description="Delayed detection destroys yield.",
            affected_users="Farmers",
            bottleneck_type="Scalable monitoring",
            technical_domain="Agriculture",
            current_workaround="Visual spot checks",
            problem_frequency="daily",
            problem_severity="critical",
            evidence_summary="Patent details swarm drone surveillance.",
            evidence_confidence="high",
            source_patent_numbers=("IN202641114195A",),
        )

        # Patent 1 fails with AI error, Patent 2 succeeds
        with patch.object(
            self.service,
            "_extract_problem_from_record",
            side_effect=[ProblemExtractionAIError("AI CLI timed out"), prob2],
        ) as mock_extract:
            with self.assertLogs("src.problems.extraction_service", level="ERROR") as log_capture:
                results = self.service.extract_problems_for_run("run-test-123")

                # Both patents were attempted despite the first failing
                self.assertEqual(mock_extract.call_count, 2)
                mock_extract.assert_any_call(target_patent=patent1, run_id="run-test-123")
                mock_extract.assert_any_call(target_patent=patent2, run_id="run-test-123")

                # Successful patent returned
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0], prob2)

                # Failure was logged with patent number and reason, not silently swallowed
                log_output = "\n".join(log_capture.output)
                self.assertIn("IN202641114086A", log_output)
                self.assertIn("AI CLI timed out", log_output)

    def test_extract_problems_for_run_empty_run(self) -> None:
        """Verify that an empty run returns an empty list without attempting extraction."""
        self.mock_patent_reader.get_patents_for_run.return_value = []

        with patch.object(self.service, "_extract_problem_from_record") as mock_extract:
            results = self.service.extract_problems_for_run("run-empty-001")

            self.assertEqual(results, [])
            mock_extract.assert_not_called()
            self.mock_patent_reader.get_patents_for_run.assert_called_once_with("run-empty-001")

    def test_extract_problems_for_run_invalid_run_id(self) -> None:
        """Verify that invalid run_id values raise ProblemExtractionServiceError."""
        invalid_ids = ["", "   ", None, 123, []]
        for invalid in invalid_ids:
            with self.subTest(invalid_run_id=invalid):
                with self.assertRaises(ProblemExtractionServiceError):
                    self.service.extract_problems_for_run(run_id=invalid)

    def test_extract_problem_idempotency_skips_ai(self) -> None:
        """Verify that extracting an already-extracted patent returns the existing record without calling AI."""
        run_id = "run-001"
        patent_id = "US11223344B2"

        existing_problem = ProblemRecord(
            problem_title="Already Extracted Problem",
            problem_description="Existing problem description.",
            affected_users="Battery Engineers",
            bottleneck_type="Thermal Degradation",
            technical_domain="Energy Storage",
            current_workaround="Liquid cooling",
            problem_frequency="daily",
            problem_severity="high",
            evidence_summary="Extracted previously.",
            evidence_confidence="high",
            source_patent_numbers=("US11223344B2",),
        )

        # Repository indicates this problem was already extracted
        self.mock_repository.get_problem_for_run_and_patent.return_value = existing_problem

        result = self.service.extract_problem_for_patent(run_id=run_id, patent_id=patent_id)

        # 1. Existing record returned
        self.assertEqual(result, existing_problem)

        # 2. AI client was NOT called
        self.mock_ai_client.generate.assert_not_called()

        # 3. Repository save was NOT called
        self.mock_repository.save_problem.assert_not_called()

        # 4. Lookup was performed with correct run_id and patent number
        self.mock_repository.get_problem_for_run_and_patent.assert_called_once_with(
            run_id=run_id,
            patent_id_or_number=patent_id,
        )

    def test_extract_problems_for_run_different_patents_create_separate_problems(self) -> None:
        """Verify that different patents in the same run create separate problems."""
        patent1 = PatentRecord(
            patent_number="IN202641114086A",
            title="Pollution Monitoring Robot",
            abstract="ESP32 based monitoring robot.",
            filing_date="2024-01-10",
            publication_date="2024-06-20",
            assignee="Tech University",
            source_url="https://ipindiaservices.gov.in/test1",
        )
        patent2 = PatentRecord(
            patent_number="IN202641114195A",
            title="Swarm Agriculture Monitoring System",
            abstract="Swarm based monitoring system.",
            filing_date="2024-02-15",
            publication_date="2024-07-15",
            assignee="AgriTech Labs",
            source_url="https://ipindiaservices.gov.in/test2",
        )
        self.mock_patent_reader.get_patents_for_run.return_value = [patent1, patent2]
        # No existing problems
        self.mock_repository.get_problem_for_run_and_patent.return_value = None

    def test_batch_extraction_idempotency_second_run_skips_ai(self) -> None:
        """Verify that running extract_problems_for_run twice does not call AI on the second run."""
        patent1 = PatentRecord(
            patent_number="IN202641114086A",
            title="Pollution Monitoring Robot",
            abstract="ESP32 based monitoring robot.",
            filing_date="2024-01-10",
            publication_date="2024-06-20",
            assignee="Tech University",
            source_url="https://ipindiaservices.gov.in/test1",
        )
        self.mock_patent_reader.get_patents_for_run.return_value = [patent1]

        # First run: no existing problem -> AI generates and repository saves
        self.mock_repository.get_problem_for_run_and_patent.return_value = None
        results1 = self.service.extract_problems_for_run("run-batch-idempotency")
        self.assertEqual(len(results1), 1)
        self.assertEqual(self.mock_ai_client.generate.call_count, 1)
        self.assertEqual(self.mock_repository.save_problem.call_count, 1)

        # Second run: problem now exists in repository
        first_problem = results1[0]
        self.mock_repository.get_problem_for_run_and_patent.return_value = first_problem
        self.mock_ai_client.generate.reset_mock()
        self.mock_repository.save_problem.reset_mock()

        results2 = self.service.extract_problems_for_run("run-batch-idempotency")
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0], first_problem)
        # AI was not called
        self.mock_ai_client.generate.assert_not_called()
        # Save was not called
        self.mock_repository.save_problem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
