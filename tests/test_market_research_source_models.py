"""Unit tests for WebResearchSource data model and validation."""

from dataclasses import FrozenInstanceError
import unittest

from src.market_research.source_models import (
    ALLOWED_SOURCE_TYPES,
    REQUIRED_SOURCE_TEXT_FIELDS,
    WebResearchSource,
)


class TestWebResearchSourceModels(unittest.TestCase):
    """Test suite for immutable WebResearchSource dataclass."""

    def _sample_kwargs(self) -> dict:
        """Helper providing valid default attributes for WebResearchSource."""
        return {
            "url": "https://drainrobo.example.com/specs",
            "title": "DrainRobo X Autonomous Crawler Specs",
            "source_type": "competitor",
            "publisher_or_domain": "drainrobo.example.com",
            "retrieved_content": "Detailed hardware datasheet specifying 50m tether and lack of gas sensors.",
            "retrieved_at": "2026-10-06T20:00:00Z",
            "raw_data": {"http_status": 200, "content_length": 4500},
        }

    def test_valid_construction(self) -> None:
        """WebResearchSource constructs successfully with valid attributes."""
        kwargs = self._sample_kwargs()
        source = WebResearchSource(**kwargs)

        self.assertEqual(source.url, kwargs["url"])
        self.assertEqual(source.title, kwargs["title"])
        self.assertEqual(source.source_type, "competitor")
        self.assertEqual(source.publisher_or_domain, kwargs["publisher_or_domain"])
        self.assertEqual(source.retrieved_content, kwargs["retrieved_content"])
        self.assertEqual(source.retrieved_at, kwargs["retrieved_at"])
        self.assertIsNone(source.id)
        self.assertEqual(source.raw_data, kwargs["raw_data"])

    def test_every_allowed_source_type(self) -> None:
        """Every allowed source_type is accepted and normalized to lowercase."""
        for st in ALLOWED_SOURCE_TYPES:
            with self.subTest(source_type=st):
                kwargs = self._sample_kwargs()
                kwargs["source_type"] = st.upper()  # Test case-insensitivity
                source = WebResearchSource(**kwargs)
                self.assertEqual(source.source_type, st)

    def test_invalid_source_type(self) -> None:
        """Invalid source_type strings or non-strings raise ValueError or TypeError."""
        for bad_st in ["invalid", "forum", "wiki", "unknown", "", "   "]:
            with self.subTest(bad_st=bad_st):
                kwargs = self._sample_kwargs()
                kwargs["source_type"] = bad_st
                with self.assertRaises(ValueError):
                    WebResearchSource(**kwargs)

        for bad_type in [123, None, True, False]:
            with self.subTest(bad_type=bad_type):
                kwargs = self._sample_kwargs()
                kwargs["source_type"] = bad_type
                with self.assertRaises(TypeError):
                    WebResearchSource(**kwargs)

    def test_empty_required_text_fields(self) -> None:
        """Empty or whitespace strings or non-strings raise ValueError for required text fields."""
        for field_name in REQUIRED_SOURCE_TEXT_FIELDS:
            for invalid_val in ["", "   ", None, 123, True]:
                with self.subTest(field=field_name, val=invalid_val):
                    kwargs = self._sample_kwargs()
                    kwargs[field_name] = invalid_val
                    with self.assertRaises(ValueError):
                        WebResearchSource(**kwargs)

    def test_whitespace_stripping(self) -> None:
        """Leading and trailing whitespace is stripped from text fields."""
        kwargs = self._sample_kwargs()
        kwargs["url"] = "  https://example.com/item  "
        kwargs["title"] = "  Example Title  "
        kwargs["publisher_or_domain"] = "  example.com  "

        source = WebResearchSource(**kwargs)
        self.assertEqual(source.url, "https://example.com/item")
        self.assertEqual(source.title, "Example Title")
        self.assertEqual(source.publisher_or_domain, "example.com")

    def test_optional_id(self) -> None:
        """Optional id defaults to None and accepts valid string when provided."""
        # Default None
        source1 = WebResearchSource(**self._sample_kwargs())
        self.assertIsNone(source1.id)

        # Explicit valid ID
        kwargs = self._sample_kwargs()
        kwargs["id"] = "source-uuid-101"
        source2 = WebResearchSource(**kwargs)
        self.assertEqual(source2.id, "source-uuid-101")

        # Invalid ID
        for bad_id in ["", "   ", 123, True]:
            with self.subTest(bad_id=bad_id):
                kwargs = self._sample_kwargs()
                kwargs["id"] = bad_id
                with self.assertRaises(ValueError):
                    WebResearchSource(**kwargs)

    def test_invalid_raw_data(self) -> None:
        """Non-dictionary raw_data raises TypeError."""
        for bad_raw in ["not_a_dict", [1, 2], 123, None]:
            with self.subTest(bad_raw=bad_raw):
                kwargs = self._sample_kwargs()
                kwargs["raw_data"] = bad_raw
                with self.assertRaises(TypeError):
                    WebResearchSource(**kwargs)

    def test_immutability(self) -> None:
        """WebResearchSource is frozen and raises FrozenInstanceError on mutation."""
        source = WebResearchSource(**self._sample_kwargs())

        with self.assertRaises(FrozenInstanceError):
            source.title = "New Title"  # type: ignore

        with self.assertRaises(FrozenInstanceError):
            source.id = "new-id"  # type: ignore

    def test_to_dict(self) -> None:
        """to_dict serializes WebResearchSource to standard dictionary."""
        kwargs = self._sample_kwargs()
        source = WebResearchSource(**kwargs)
        data = source.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["url"], kwargs["url"])
        self.assertEqual(data["title"], kwargs["title"])
        self.assertEqual(data["source_type"], "competitor")
        self.assertEqual(data["publisher_or_domain"], kwargs["publisher_or_domain"])
        self.assertEqual(data["retrieved_content"], kwargs["retrieved_content"])
        self.assertEqual(data["retrieved_at"], kwargs["retrieved_at"])
        self.assertIsNone(data["id"])
        self.assertEqual(data["raw_data"], kwargs["raw_data"])

    def test_from_dict(self) -> None:
        """from_dict constructs an identical WebResearchSource."""
        kwargs = self._sample_kwargs()
        kwargs["id"] = "source-uuid-500"
        source = WebResearchSource.from_dict(kwargs)

        self.assertEqual(source.id, "source-uuid-500")
        self.assertEqual(source.url, kwargs["url"])
        self.assertEqual(source.source_type, "competitor")

        with self.assertRaises(TypeError):
            WebResearchSource.from_dict("invalid")  # type: ignore


if __name__ == "__main__":
    unittest.main()
