"""Unit tests for domain-agnostic ResearchQueryGenerator."""

import unittest
from unittest.mock import patch

from src.market_research.research_query_generator import (
    DEFAULT_MAX_RESEARCH_QUERIES,
    DEFAULT_RESEARCH_CATEGORIES,
    GeneratedResearchQueries,
    ResearchQueryGenerator,
    ResearchQueryItem,
    build_research_query,
    generate_google_news_queries,
    generate_research_queries,
)
from src.patents.research_config import (
    COSMETICS_RESEARCH_CONFIG,
    WATER_RESEARCH_CONFIG,
    ResearchDomainConfig,
)


class TestResearchQueryGenerator(unittest.TestCase):
    """Test suite for domain-agnostic market research query generation."""

    def setUp(self) -> None:
        self.generator = ResearchQueryGenerator()

    def test_valid_research_domain_config_produces_queries(self) -> None:
        """1. Valid ResearchDomainConfig produces a structured GeneratedResearchQueries object."""
        result = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=10)

        self.assertIsInstance(result, GeneratedResearchQueries)
        self.assertEqual(result.domain_name, "Cosmetics & Skincare")
        self.assertEqual(len(result.queries), 10)
        self.assertEqual(len(result.items), 10)
        for item in result.items:
            self.assertIsInstance(item, ResearchQueryItem)
            self.assertIn(item.query, result.queries)

    def test_multiple_themes_are_handled(self) -> None:
        """2. Multiple themes within the configuration are processed into research queries."""
        config = ResearchDomainConfig(
            domain_name="Agriculture",
            themes=("precision agriculture", "crop monitoring", "automated irrigation"),
        )
        result = self.generator.generate_queries(config, max_queries=15)

        # Confirm queries originating from multiple distinct themes exist
        originating_themes = {item.theme for item in result.items}
        self.assertIn("precision agriculture", originating_themes)
        self.assertIn("crop monitoring", originating_themes)
        self.assertTrue(len(originating_themes) >= 2)

    def test_query_categories_are_represented(self) -> None:
        """3. All generic research intent categories are represented across generated queries."""
        config = ResearchDomainConfig(
            domain_name="Renewable Energy",
            themes=("solar energy",),
        )
        result = self.generator.generate_queries(config, max_queries=7)

        expected_categories = {
            "competitors",
            "products",
            "technology",
            "customer_problems",
            "complaints_reviews",
            "market_gaps",
            "emerging_trends",
        }
        represented_categories = {item.category for item in result.items}
        self.assertEqual(represented_categories, expected_categories)

    def test_duplicate_queries_are_removed(self) -> None:
        """4. Near-duplicate or identical queries are eliminated while preserving order."""
        config = ResearchDomainConfig(
            domain_name="Duplicate Test",
            themes=("skincare", "skincare", "skincare products"),
        )
        result = self.generator.generate_queries(config, max_queries=20)

        # Ensure no duplicates in queries list
        self.assertEqual(len(result.queries), len(set(q.lower() for q in result.queries)))

        # "skincare products" as theme with intent "products" does not produce "skincare products products"
        self.assertNotIn("skincare products products", result.queries)

    def test_ordering_is_deterministic(self) -> None:
        """5. Query generation order is 100% deterministic and repeatable across runs."""
        first_run = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=15)
        for _ in range(10):
            subsequent_run = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=15)
            self.assertEqual(first_run.queries, subsequent_run.queries)
            self.assertEqual(first_run.items, subsequent_run.items)

    def test_output_count_is_bounded(self) -> None:
        """6. max_queries strictly bounds the resulting query count."""
        for limit in [1, 3, 5, 12]:
            with self.subTest(limit=limit):
                res = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=limit)
                self.assertEqual(len(res.queries), limit)
                self.assertEqual(len(res.items), limit)

    def test_empty_or_invalid_configuration_is_rejected(self) -> None:
        """7. Invalid configurations and invalid max_queries raise ValueError."""
        # Non-ResearchDomainConfig inputs
        with self.assertRaises(ValueError):
            self.generator.generate_queries(None)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            self.generator.generate_queries("not a config")  # type: ignore[arg-type]

        # Invalid max_queries
        for bad_max in [0, -1, "10", True, False, None]:
            with self.subTest(bad_max=bad_max):
                with self.assertRaises(ValueError):
                    self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=bad_max)  # type: ignore[arg-type]

        # Invalid config construction
        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="", themes=["valid theme"])

        with self.assertRaises(ValueError):
            ResearchDomainConfig(domain_name="Valid", themes=[])

    def test_water_configuration_works(self) -> None:
        """8. Predefined WATER_RESEARCH_CONFIG generates clean water research queries."""
        result = self.generator.generate_queries(WATER_RESEARCH_CONFIG, max_queries=7)

        self.assertEqual(result.domain_name, "Water Quality & Infrastructure")
        self.assertEqual(len(result.queries), 7)

        # First theme in water config is WATER MONITORING
        self.assertIn("WATER MONITORING competitors", result.queries)
        self.assertIn("WATER MONITORING products", result.queries)
        self.assertIn("WATER MONITORING technology", result.queries)
        self.assertIn("WATER MONITORING market gaps", result.queries)

    def test_cosmetics_configuration_works(self) -> None:
        """9. Predefined COSMETICS_RESEARCH_CONFIG generates natural cosmetics queries."""
        result = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=10)

        self.assertEqual(result.domain_name, "Cosmetics & Skincare")
        self.assertEqual(len(result.queries), 10)

        # Check natural phrasing from first theme "skincare"
        expected_skincare_queries = [
            "skincare competitors",
            "skincare products",
            "skincare technology",
            "skincare customer problems",
            "skincare complaints reviews",
            "skincare market gaps",
            "skincare emerging trends",
        ]
        for expected_q in expected_skincare_queries:
            self.assertIn(expected_q, result.queries)

    def test_custom_configuration_works(self) -> None:
        """10. Completely custom configurations (e.g. Robotics) generate valid queries."""
        robotics_config = ResearchDomainConfig(
            domain_name="Robotics & Autonomous Systems",
            themes=("pipe inspection robot", "drone delivery"),
        )
        result = self.generator.generate_queries(robotics_config, max_queries=8)

        self.assertEqual(result.domain_name, "Robotics & Autonomous Systems")
        self.assertEqual(len(result.queries), 8)
        self.assertIn("pipe inspection robot competitors", result.queries)
        self.assertIn("pipe inspection robot technology", result.queries)
        self.assertIn("drone delivery competitors", result.queries)

    def test_no_network_or_search_calls_occur(self) -> None:
        """11. Generator executes purely in-memory without making network or search calls."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = self.generator.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=5)
            self.assertEqual(len(result.queries), 5)
            mock_urlopen.assert_not_called()

    def test_convenience_function_and_collection_protocol(self) -> None:
        """12. Helper function generate_research_queries and collection protocol methods work."""
        res = generate_research_queries(COSMETICS_RESEARCH_CONFIG, max_queries=4)

        # len()
        self.assertEqual(len(res), 4)

        # indexing
        self.assertEqual(res[0], "skincare competitors")

        # iter()
        iterated = list(res)
        self.assertEqual(iterated, list(res.queries))

        # to_dict()
        data = res.to_dict()
        self.assertEqual(data["domain_name"], "Cosmetics & Skincare")
        self.assertEqual(data["query_count"], 4)
        self.assertEqual(len(data["queries"]), 4)
        self.assertEqual(len(data["items"]), 4)

    def test_build_research_query_token_deduplication(self) -> None:
        """13. build_research_query avoids repeating tokens already present in the theme."""
        # Simple combine
        self.assertEqual(
            build_research_query("skincare", "competitors"),
            "skincare competitors",
        )
        # Theme already has the word
        self.assertEqual(
            build_research_query("skincare products", "products"),
            "skincare products",
        )
        self.assertEqual(
            build_research_query("beauty technology", "technology"),
            "beauty technology",
        )
        # Whitespace normalization
        self.assertEqual(
            build_research_query("   skincare   formulation  ", "  market   gaps  "),
            "skincare formulation market gaps",
        )

    def test_build_research_query_quoted_subject_anchor(self) -> None:
        """14. build_research_query with quote_subject_anchor=True quotes the theme anchor."""
        # Single word theme
        self.assertEqual(
            build_research_query("skincare", "competitors", quote_subject_anchor=True),
            '"skincare" competitors',
        )
        # Multi-word theme
        self.assertEqual(
            build_research_query("WATER QUALITY", "technology", quote_subject_anchor=True),
            '"WATER QUALITY" technology',
        )
        # Already quoted theme does not double-quote
        self.assertEqual(
            build_research_query('"skincare"', "market gaps", quote_subject_anchor=True),
            '"skincare" market gaps',
        )
        # Theme with token overlap
        self.assertEqual(
            build_research_query("skincare products", "products", quote_subject_anchor=True),
            '"skincare products"',
        )

    def test_generate_google_news_queries_anchors_themes(self) -> None:
        """15. generate_google_news_queries quotes the primary theme anchor for all categories."""
        cosmetics_res = generate_google_news_queries(COSMETICS_RESEARCH_CONFIG, max_queries=7)
        self.assertEqual(len(cosmetics_res.queries), 7)
        for q in cosmetics_res.queries:
            # Theme anchor "skincare" is quoted at the start
            self.assertTrue(q.startswith('"skincare"'))

        # Intent modifier words are unquoted
        self.assertIn('"skincare" competitors', cosmetics_res.queries)
        self.assertIn('"skincare" products', cosmetics_res.queries)
        self.assertIn('"skincare" technology', cosmetics_res.queries)
        self.assertIn('"skincare" customer problems', cosmetics_res.queries)

        # Non-skincare domain works identically
        water_res = generate_google_news_queries(WATER_RESEARCH_CONFIG, max_queries=5)
        self.assertEqual(len(water_res.queries), 5)
        for q in water_res.queries:
            self.assertTrue(q.startswith('"WATER MONITORING"'))
        self.assertIn('"WATER MONITORING" competitors', water_res.queries)

    def test_quote_subject_anchor_flag_in_generator(self) -> None:
        """16. ResearchQueryGenerator(quote_subject_anchor=True) and generator.generate_google_news_queries work."""
        gen_quoted = ResearchQueryGenerator(quote_subject_anchor=True)
        res = gen_quoted.generate_queries(COSMETICS_RESEARCH_CONFIG, max_queries=3)
        self.assertEqual(res[0], '"skincare" competitors')

        gen_default = ResearchQueryGenerator()
        res_gnews = gen_default.generate_google_news_queries(COSMETICS_RESEARCH_CONFIG, max_queries=3)
        self.assertEqual(res_gnews[0], '"skincare" competitors')


if __name__ == "__main__":
    unittest.main()
