"""Unit tests for patent research domain and theme configuration."""

from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import MagicMock

from src.patents.discovery_strategy import (
    DeterministicPatentQueryGenerator,
    InPassDiscoveryStrategy,
)
from src.patents.inpass_client import InPassClient
from src.patents.inpass_ingestion_service import (
    InPassIngestionResult,
    InPassIngestionService,
)
from src.patents.research_config import (
    COSMETICS_RESEARCH_CONFIG,
    DEFAULT_RESEARCH_CONFIG,
    WATER_RESEARCH_CONFIG,
    PatentResearchConfig,
    ResearchDomainConfig,
    get_default_research_config,
)


class TestPatentResearchConfig(unittest.TestCase):
    """Test suite for research domain/theme configuration and discovery engine integration."""

    def test_valid_cosmetics_research_configuration(self) -> None:
        """Verify the pre-configured Cosmetics & Skincare research configuration."""
        config = COSMETICS_RESEARCH_CONFIG

        self.assertEqual(config.domain_name, "Cosmetics & Skincare")
        self.assertIsNotNone(config.description)
        self.assertIn("Cosmetics", config.description or "")
        self.assertEqual(len(config.themes), 10)

        expected_themes = (
            "skincare",
            "cosmetics",
            "skincare products",
            "cosmetic ingredients",
            "skin care technology",
            "personalised skincare",
            "AI skin analysis",
            "beauty technology",
            "cosmetic formulation",
            "skincare recommendation",
        )
        self.assertEqual(config.themes, expected_themes)
        self.assertEqual(config.queries, expected_themes)

        # Check default helpers and alias
        self.assertIs(DEFAULT_RESEARCH_CONFIG, COSMETICS_RESEARCH_CONFIG)
        self.assertIs(get_default_research_config(), COSMETICS_RESEARCH_CONFIG)
        self.assertIs(PatentResearchConfig, ResearchDomainConfig)

        # Check serialization
        data = config.to_dict()
        self.assertEqual(data["domain_name"], "Cosmetics & Skincare")
        self.assertEqual(data["themes"], list(expected_themes))
        self.assertEqual(data["queries"], list(expected_themes))

    def test_valid_water_research_configuration(self) -> None:
        """Verify the pre-configured Water research configuration preserves water themes."""
        config = WATER_RESEARCH_CONFIG

        self.assertEqual(config.domain_name, "Water Quality & Infrastructure")
        self.assertIsNotNone(config.description)
        self.assertTrue(len(config.themes) >= 10)
        self.assertIn("WATER MONITORING", config.themes)
        self.assertIn("WATER QUALITY", config.themes)
        self.assertIn("WATER CONTAMINATION", config.themes)
        self.assertIn("WATER PURIFICATION", config.themes)
        self.assertEqual(config.queries, config.themes)

    def test_custom_research_configuration(self) -> None:
        """Verify a completely custom domain configuration (e.g. Agriculture) can be created."""
        ag_themes = (
            "precision agriculture",
            "crop monitoring",
            "irrigation",
            "farm automation",
        )
        ag_config = ResearchDomainConfig(
            domain_name="Agriculture",
            description="Precision agriculture, crop monitoring, and automated irrigation.",
            themes=ag_themes,
        )

        self.assertEqual(ag_config.domain_name, "Agriculture")
        self.assertEqual(ag_config.description, "Precision agriculture, crop monitoring, and automated irrigation.")
        self.assertEqual(ag_config.themes, ag_themes)
        self.assertEqual(ag_config.queries, ag_themes)

        # Immutability
        with self.assertRaises(FrozenInstanceError):
            ag_config.domain_name = "Modified Agriculture"  # type: ignore[misc]

        # Initialization via queries keyword argument
        robotics_config = ResearchDomainConfig(
            domain_name="Robotics",
            queries=["pipeline inspection", "underwater robotics"],
        )
        self.assertEqual(robotics_config.domain_name, "Robotics")
        self.assertEqual(robotics_config.themes, ("pipeline inspection", "underwater robotics"))

    def test_invalid_or_empty_domain(self) -> None:
        """Verify that empty, whitespace, None, or non-string domain names raise ValueError."""
        valid_themes = ["skincare", "cosmetics"]

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="", themes=valid_themes)

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="   \t \n", themes=valid_themes)

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name=None, themes=valid_themes)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name=123, themes=valid_themes)  # type: ignore[arg-type]

    def test_invalid_or_empty_themes(self) -> None:
        """Verify that missing, empty, or non-sequence themes raise ValueError."""
        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=[])

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=None)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes="skincare")  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=())

    def test_theme_validation(self) -> None:
        """Verify individual theme item validation and whitespace trimming."""
        # Empty string item
        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=["skincare", ""])

        # Whitespace-only item
        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=["skincare", "   "])

        # Non-string item
        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=["skincare", None])  # type: ignore[list-item]

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Cosmetics", themes=["skincare", 999])  # type: ignore[list-item]

        # Whitespace normalization
        cfg = ResearchDomainConfig(domain_name="Cosmetics", themes=["  skincare  ", "\tcosmetics\n"])
        self.assertEqual(cfg.themes, ("skincare", "cosmetics"))

    def test_discovery_strategy_using_configured_themes(self) -> None:
        """Verify InPassDiscoveryStrategy generates and executes queries using domain configuration."""
        # 1. Strategy initialized with COSMETICS_RESEARCH_CONFIG
        strategy = InPassDiscoveryStrategy(research_config=COSMETICS_RESEARCH_CONFIG)
        queries = strategy.generate_targeted_queries(max_queries=5)

        expected_top_5 = [
            "skincare",
            "cosmetics",
            "skincare products",
            "cosmetic ingredients",
            "skin care technology",
        ]
        self.assertEqual(queries, expected_top_5)

        # 2. Strategy generating queries for custom Agriculture config override
        agriculture_config = ResearchDomainConfig(
            domain_name="Agriculture",
            themes=(
                "precision agriculture",
                "crop monitoring",
                "irrigation",
                "farm automation",
            ),
        )
        ag_queries = strategy.generate_targeted_queries(
            research_config=agriculture_config,
            max_queries=4,
        )
        self.assertEqual(ag_queries, [
            "precision agriculture",
            "crop monitoring",
            "irrigation",
            "farm automation",
        ])

        # 3. Execution of discover_for_run with configured cosmetics
        mock_ingestion = MagicMock(spec=InPassIngestionService)
        mock_client = MagicMock(spec=InPassClient)
        mock_ingestion.ingest_search_run.return_value = InPassIngestionResult(
            run_id="run-cosmetics-1",
            query="skincare",
            discovered=3,
            ingested=2,
            inserted=2,
            existing=0,
            linked=2,
        )

        cosmetics_strategy = InPassDiscoveryStrategy(
            ingestion_service=mock_ingestion,
            research_config=COSMETICS_RESEARCH_CONFIG,
        )

        res = cosmetics_strategy.discover_for_run(
            run_id="run-cosmetics-1",
            max_queries=2,
            max_results_per_query=2,
            client=mock_client,
        )

        self.assertEqual(res.run_id, "run-cosmetics-1")
        self.assertEqual(res.theme, "Cosmetics & Skincare")
        self.assertEqual(list(res.generated_queries), ["skincare", "cosmetics"])
        self.assertEqual(list(res.executed_queries), ["skincare", "cosmetics"])
        self.assertEqual(mock_ingestion.ingest_search_run.call_count, 2)

    def test_existing_water_behaviour_remains_compatible(self) -> None:
        """Verify that existing WATER query generation and discovery remain 100% backward compatible."""
        # 1. Direct query generator with WATER string
        generator = DeterministicPatentQueryGenerator()
        water_queries = generator.generate_queries(theme="WATER", max_queries=5)
        expected_water = [
            "WATER MONITORING",
            "WATER QUALITY",
            "WATER CONTAMINATION",
            "WATER PURIFICATION",
            "WATER LEAKAGE",
        ]
        self.assertEqual(water_queries, expected_water)

        # 2. Strategy default execution with WATER string
        strategy = InPassDiscoveryStrategy()
        strategy_queries = strategy.generate_targeted_queries(theme="WATER", max_queries=3)
        self.assertEqual(strategy_queries, [
            "WATER MONITORING",
            "WATER QUALITY",
            "WATER CONTAMINATION",
        ])

        # 3. Multi-word water theme
        multi_queries = generator.generate_queries(theme="WATER QUALITY", max_queries=3)
        self.assertEqual(multi_queries, [
            "WATER QUALITY",
            "WATER QUALITY MONITORING",
            "WATER QUALITY CONTAMINATION",
        ])

        # 4. discover_for_run with WATER string theme
        mock_ingestion = MagicMock(spec=InPassIngestionService)
        mock_ingestion.ingest_search_run.return_value = InPassIngestionResult(
            run_id="run-water-legacy",
            query="WATER MONITORING",
            discovered=2,
            ingested=1,
            inserted=1,
            existing=0,
            linked=1,
        )

        water_strategy = InPassDiscoveryStrategy(ingestion_service=mock_ingestion)
        water_result = water_strategy.discover_for_run(
            run_id="run-water-legacy",
            theme="WATER",
            max_queries=1,
            max_results_per_query=2,
        )

        self.assertEqual(water_result.theme, "WATER")
        self.assertEqual(list(water_result.executed_queries), ["WATER MONITORING"])


if __name__ == "__main__":
    unittest.main()
