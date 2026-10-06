"""Unit tests for SearchResult data model."""

from dataclasses import FrozenInstanceError
import unittest

from src.market_research.search_models import (
    REQUIRED_SEARCH_RESULT_TEXT_FIELDS,
    SearchResult,
)


class TestSearchResultModels(unittest.TestCase):
    """Test suite for immutable SearchResult dataclass."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for SearchResult."""
        return {
            "url": "https://drainrobo.example.com/products/crawler",
            "title": "DrainRobo Inspection Crawler Specifications",
            "snippet": "Leading autonomous microcrawler designed for commercial pipe lines and confined spaces.",
            "domain": "drainrobo.example.com",
            "raw_data": {"rank": 1, "engine": "mock_search"},
        }

    def test_valid_construction(self) -> None:
        """SearchResult constructs successfully with valid attributes."""
        kwargs = self._sample_kwargs()
        result = SearchResult(**kwargs)

        self.assertEqual(result.url, kwargs["url"])
        self.assertEqual(result.title, kwargs["title"])
        self.assertEqual(result.snippet, kwargs["snippet"])
        self.assertEqual(result.domain, kwargs["domain"])
        self.assertEqual(result.source, kwargs["domain"])
        self.assertIsNone(result.id)
        self.assertEqual(result.raw_data, {"rank": 1, "engine": "mock_search"})

    def test_url_scheme_validation(self) -> None:
        """Only valid HTTP/HTTPS URLs are accepted."""
        # Valid HTTPS and HTTP
        s_https = SearchResult(**self._sample_kwargs())
        self.assertTrue(s_https.url.startswith("https://"))

        kwargs_http = self._sample_kwargs()
        kwargs_http["url"] = "http://drainrobo.example.com/item"
        s_http = SearchResult(**kwargs_http)
        self.assertTrue(s_http.url.startswith("http://"))

        # Invalid schemes or non-URLs
        invalid_urls = [
            "ftp://files.example.com/doc",
            "file:///etc/passwd",
            "javascript:void(0)",
            "not-a-url",
            "",
            "   ",
        ]
        for bad_url in invalid_urls:
            with self.subTest(bad_url=bad_url):
                kwargs = self._sample_kwargs()
                kwargs["url"] = bad_url
                with self.assertRaises(ValueError):
                    SearchResult(**kwargs)

    def test_empty_required_text_fields(self) -> None:
        """Empty or whitespace-only text values raise ValueError."""
        for field_name in REQUIRED_SEARCH_RESULT_TEXT_FIELDS:
            for bad_val in ["", "   ", None, 123, True]:
                with self.subTest(field=field_name, val=bad_val):
                    kwargs = self._sample_kwargs()
                    kwargs[field_name] = bad_val
                    with self.assertRaises(ValueError):
                        SearchResult(**kwargs)

    def test_whitespace_stripping(self) -> None:
        """Leading/trailing whitespace is stripped from text fields."""
        kwargs = self._sample_kwargs()
        kwargs["title"] = "  Whitespace Title  "
        kwargs["snippet"] = "  Whitespace snippet.  "
        kwargs["domain"] = "  example.com  "

        result = SearchResult(**kwargs)
        self.assertEqual(result.title, "Whitespace Title")
        self.assertEqual(result.snippet, "Whitespace snippet.")
        self.assertEqual(result.domain, "example.com")

    def test_optional_id(self) -> None:
        """id defaults to None and accepts non-empty string when provided."""
        # Default None
        res1 = SearchResult(**self._sample_kwargs())
        self.assertIsNone(res1.id)

        # Valid string
        kwargs = self._sample_kwargs()
        kwargs["id"] = "res-uuid-123"
        res2 = SearchResult(**kwargs)
        self.assertEqual(res2.id, "res-uuid-123")

        # Invalid ID
        for bad_id in ["", "   ", 123, False]:
            with self.subTest(bad_id=bad_id):
                kwargs = self._sample_kwargs()
                kwargs["id"] = bad_id
                with self.assertRaises(ValueError):
                    SearchResult(**kwargs)

    def test_raw_data_validation(self) -> None:
        """Non-dictionary raw_data raises TypeError."""
        for bad_raw in ["not_a_dict", [1, 2], 123, None]:
            with self.subTest(bad_raw=bad_raw):
                kwargs = self._sample_kwargs()
                kwargs["raw_data"] = bad_raw
                with self.assertRaises(TypeError):
                    SearchResult(**kwargs)

    def test_immutability(self) -> None:
        """SearchResult is frozen and cannot be mutated."""
        result = SearchResult(**self._sample_kwargs())

        with self.assertRaises(FrozenInstanceError):
            result.title = "New Title"  # type: ignore

        with self.assertRaises(FrozenInstanceError):
            result.id = "new-id"  # type: ignore

    def test_to_dict_and_from_dict(self) -> None:
        """Serialization to dictionary and deserialization preserves all attributes."""
        kwargs = self._sample_kwargs()
        kwargs["id"] = "res-uuid-999"
        result = SearchResult(**kwargs)
        data = result.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["url"], kwargs["url"])
        self.assertEqual(data["domain"], kwargs["domain"])
        self.assertEqual(data["id"], "res-uuid-999")

        reconstructed = SearchResult.from_dict(data)
        self.assertEqual(reconstructed.url, result.url)
        self.assertEqual(reconstructed.title, result.title)
        self.assertEqual(reconstructed.id, result.id)

        with self.assertRaises(TypeError):
            SearchResult.from_dict("invalid")  # type: ignore


if __name__ == "__main__":
    unittest.main()
