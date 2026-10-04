"""Unit tests for intelligent patent discovery strategy and query generation."""

import unittest
from unittest.mock import MagicMock

from src.patents.discovery_strategy import (
    DEFAULT_TECHNICAL_FACETS,
    BasePatentQueryGenerator,
    DeterministicPatentQueryGenerator,
    InPassDiscoveryResult,
    InPassDiscoveryStrategy,
)
from src.patents.inpass_client import InPassClient, InPassSearchConfig
from src.patents.inpass_ingestion_service import (
    InPassIngestionResult,
    InPassIngestionService,
)


class TestDeterministicPatentQueryGenerator(unittest.TestCase):
    """Test suite for DeterministicPatentQueryGenerator."""

    def setUp(self) -> None:
        self.generator = DeterministicPatentQueryGenerator()

    def test_single_word_theme_generates_targeted_queries(self) -> None:
        """Single word theme should generate targeted concept queries combining theme + facets."""
        queries = self.generator.generate_queries(theme="WATER", max_queries=5)

        expected = [
            "WATER MONITORING",
            "WATER QUALITY",
            "WATER CONTAMINATION",
            "WATER PURIFICATION",
            "WATER LEAKAGE",
        ]
        self.assertEqual(queries, expected)
        self.assertEqual(len(queries), 5)

    def test_multi_word_theme_preserves_theme_and_expands_without_duplicate_facets(self) -> None:
        """Multi-word theme includes the original theme first and excludes facets already in the theme."""
        queries = self.generator.generate_queries(theme="WATER QUALITY", max_queries=4)

        # "QUALITY" is already in theme tokens, so it should be skipped in facet expansion
        expected = [
            "WATER QUALITY",
            "WATER QUALITY MONITORING",
            "WATER QUALITY CONTAMINATION",
            "WATER QUALITY PURIFICATION",
        ]
        self.assertEqual(queries, expected)
        self.assertNotIn("WATER QUALITY QUALITY", queries)

    def test_respects_max_queries_limit(self) -> None:
        """Should strictly respect max_queries limits."""
        queries_1 = self.generator.generate_queries(theme="WATER", max_queries=1)
        self.assertEqual(len(queries_1), 1)
        self.assertEqual(queries_1, ["WATER MONITORING"])

        queries_3 = self.generator.generate_queries(theme="WATER", max_queries=3)
        self.assertEqual(len(queries_3), 3)

        queries_8 = self.generator.generate_queries(theme="SOLAR", max_queries=8)
        self.assertEqual(len(queries_8), 8)

    def test_normalizes_whitespace_and_casing(self) -> None:
        """Casing and erratic whitespace should be normalized cleanly."""
        queries_lower = self.generator.generate_queries(theme="   water   ", max_queries=3)
        queries_upper = self.generator.generate_queries(theme="WATER", max_queries=3)
        queries_mixed = self.generator.generate_queries(theme="  wAtEr  \t\n", max_queries=3)

        self.assertEqual(queries_lower, queries_upper)
        self.assertEqual(queries_mixed, queries_upper)

    def test_duplicate_and_near_duplicate_removal(self) -> None:
        """Generator should not emit duplicate token sets."""
        custom_facets = ["MONITORING", "monitoring", "MONITORING", "QUALITY", "DETECTION"]
        gen = DeterministicPatentQueryGenerator(facets=custom_facets)
        queries = gen.generate_queries(theme="WATER", max_queries=5)

        self.assertEqual(queries, ["WATER MONITORING", "WATER QUALITY", "WATER DETECTION"])

    def test_custom_facets_injection(self) -> None:
        """Generator should accept and prioritize custom technical facets."""
        custom_facets = ["FILTER", "DESALINATION", "MEMBRANE"]
        gen = DeterministicPatentQueryGenerator(facets=custom_facets)
        queries = gen.generate_queries(theme="WATER", max_queries=3)

        self.assertEqual(queries, ["WATER FILTER", "WATER DESALINATION", "WATER MEMBRANE"])

    def test_empty_facets_fallback_to_clean_theme(self) -> None:
        """If custom facets list is empty, generator falls back to the clean theme."""
        gen = DeterministicPatentQueryGenerator(facets=[])
        queries = gen.generate_queries(theme="WATER", max_queries=5)

        self.assertEqual(queries, ["WATER"])

    def test_deterministic_output(self) -> None:
        """Calling generate_queries multiple times with same inputs must yield identical lists."""
        first_run = self.generator.generate_queries(theme="BATTERY", max_queries=6)
        for _ in range(25):
            subsequent_run = self.generator.generate_queries(theme="BATTERY", max_queries=6)
            self.assertEqual(first_run, subsequent_run)

    def test_empty_or_invalid_theme_raises_value_error(self) -> None:
        """Empty string or whitespace-only themes must raise ValueError."""
        with self.assertRaises(ValueError):
            self.generator.generate_queries(theme="")

        with self.assertRaises(ValueError):
            self.generator.generate_queries(theme="   \t \n  ")

        with self.assertRaises(ValueError):
            self.generator.generate_queries(theme=None)  # type: ignore[arg-type]

    def test_invalid_max_queries_raises_value_error(self) -> None:
        """max_queries < 1 must raise ValueError."""
        with self.assertRaises(ValueError):
            self.generator.generate_queries(theme="WATER", max_queries=0)

        with self.assertRaises(ValueError):
            self.generator.generate_queries(theme="WATER", max_queries=-5)


class TestInPassDiscoveryResult(unittest.TestCase):
    """Test suite for InPassDiscoveryResult data structure."""

    def test_result_fields_and_dict_conversion(self) -> None:
        """Verify dataclass fields, immutability, and dict representation."""
        result = InPassDiscoveryResult(
            run_id="run-100",
            theme="WATER",
            generated_queries=("WATER MONITORING", "WATER QUALITY"),
            executed_queries=("WATER MONITORING", "WATER QUALITY"),
            total_discovered=10,
            total_ingested=6,
            total_inserted=4,
            total_existing=2,
            total_linked=6,
            ingestion_results=(),
        )

        self.assertEqual(result.run_id, "run-100")
        self.assertEqual(result.theme, "WATER")
        self.assertEqual(result["total_discovered"], 10)
        self.assertEqual(result["total_inserted"], 4)
        self.assertEqual(len(result["generated_queries"]), 2)

        data = result.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["run_id"], "run-100")
        self.assertEqual(data["total_ingested"], 6)


class TestInPassDiscoveryStrategy(unittest.TestCase):
    """Test suite for InPassDiscoveryStrategy multi-query orchestration."""

    def setUp(self) -> None:
        self.mock_ingestion_service = MagicMock(spec=InPassIngestionService)
        self.mock_query_generator = MagicMock(spec=BasePatentQueryGenerator)
        self.strategy = InPassDiscoveryStrategy(
            query_generator=self.mock_query_generator,
            ingestion_service=self.mock_ingestion_service,
        )

    def test_generate_targeted_queries_delegates_to_generator(self) -> None:
        """Strategy exposes direct query generation using configured generator."""
        self.mock_query_generator.generate_queries.return_value = ["WATER MONITORING", "WATER QUALITY"]
        queries = self.strategy.generate_targeted_queries("WATER", max_queries=2)

        self.assertEqual(queries, ["WATER MONITORING", "WATER QUALITY"])
        self.mock_query_generator.generate_queries.assert_called_once_with(theme="WATER", max_queries=2)

    def test_discover_for_run_validates_inputs(self) -> None:
        """discover_for_run should reject empty run_id."""
        with self.assertRaises(ValueError):
            self.strategy.discover_for_run(run_id="", theme="WATER")

        with self.assertRaises(ValueError):
            self.strategy.discover_for_run(run_id="   ", theme="WATER")

    def test_discover_for_run_executes_each_generated_query(self) -> None:
        """Strategy executes InPassIngestionService for every generated query and aggregates stats."""
        self.mock_query_generator.generate_queries.return_value = [
            "WATER MONITORING",
            "WATER QUALITY",
            "WATER PURIFICATION",
        ]

        # Mock results returned by ingestion_service for the 3 queries
        res1 = InPassIngestionResult(
            run_id="run-test-1",
            query="WATER MONITORING",
            discovered=4,
            ingested=2,
            inserted=2,
            existing=0,
            linked=2,
        )
        res2 = InPassIngestionResult(
            run_id="run-test-1",
            query="WATER QUALITY",
            discovered=3,
            ingested=2,
            inserted=1,
            existing=1,
            linked=2,
        )
        res3 = InPassIngestionResult(
            run_id="run-test-1",
            query="WATER PURIFICATION",
            discovered=5,
            ingested=3,
            inserted=3,
            existing=0,
            linked=3,
        )
        self.mock_ingestion_service.ingest_search_run.side_effect = [res1, res2, res3]

        captcha_callback = MagicMock()
        mock_client = MagicMock(spec=InPassClient)

        result = self.strategy.discover_for_run(
            run_id="run-test-1",
            theme="WATER",
            max_queries=3,
            max_results_per_query=2,
            on_captcha_required=captcha_callback,
            client=mock_client,
        )

        # Verify query generator called with correct theme and max_queries
        self.mock_query_generator.generate_queries.assert_called_once_with(theme="WATER", max_queries=3)

        # Verify 3 ingestion calls made
        self.assertEqual(self.mock_ingestion_service.ingest_search_run.call_count, 3)

        # Verify search configs used title field "TI" and target queries
        calls = self.mock_ingestion_service.ingest_search_run.call_args_list
        self.assertEqual(calls[0].kwargs["search_config_or_query"].keyword, "WATER MONITORING")
        self.assertEqual(calls[0].kwargs["search_config_or_query"].field_type, "TI")
        self.assertEqual(calls[0].kwargs["max_results"], 2)
        self.assertEqual(calls[0].kwargs["on_captcha_required"], captcha_callback)
        self.assertEqual(calls[0].kwargs["client"], mock_client)

        self.assertEqual(calls[1].kwargs["search_config_or_query"].keyword, "WATER QUALITY")
        self.assertEqual(calls[2].kwargs["search_config_or_query"].keyword, "WATER PURIFICATION")

        # Verify aggregated totals
        self.assertEqual(result.run_id, "run-test-1")
        self.assertEqual(result.theme, "WATER")
        self.assertEqual(result.total_discovered, 4 + 3 + 5)
        self.assertEqual(result.total_ingested, 2 + 2 + 3)
        self.assertEqual(result.total_inserted, 2 + 1 + 3)
        self.assertEqual(result.total_existing, 0 + 1 + 0)
        self.assertEqual(result.total_linked, 2 + 2 + 3)
        self.assertEqual(len(result.ingestion_results), 3)
        self.assertEqual(list(result.executed_queries), [
            "WATER MONITORING",
            "WATER QUALITY",
            "WATER PURIFICATION",
        ])

    def test_discover_for_run_forwards_captcha_solver(self) -> None:
        """Strategy should forward captcha_solver callback to ingestion_service."""
        self.mock_query_generator.generate_queries.return_value = ["WATER MONITORING"]
        mock_solver = MagicMock(return_value="SOLVE_CODE")
        self.mock_ingestion_service.ingest_search_run.return_value = InPassIngestionResult(
            run_id="run-solver",
            query="WATER MONITORING",
            discovered=1,
            ingested=1,
            inserted=1,
            existing=0,
            linked=1,
        )

        self.strategy.discover_for_run(
            run_id="run-solver",
            theme="WATER",
            max_queries=1,
            captcha_solver=mock_solver,
        )

        call_kwargs = self.mock_ingestion_service.ingest_search_run.call_args.kwargs
        self.assertEqual(call_kwargs["captcha_solver"], mock_solver)


if __name__ == "__main__":
    unittest.main()

