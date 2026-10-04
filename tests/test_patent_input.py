"""Unit tests for patent_input extraction adapter."""

import unittest

from src.patents.models import PatentRecord
from src.problems.patent_input import build_patent_extraction_input


class TestPatentInputAdapter(unittest.TestCase):
    """Test suite for converting PatentRecord instances to extraction input dictionaries."""

    def _sample_patent(
        self,
        patent_number: str = "US11223344B2",
        title: str = "Solid Electrolyte Separator",
        abstract: str | None = "Electrolyte composition for secondary batteries.",
        filing_date: str | None = "2020-03-15",
        publication_date: str | None = "2021-09-30",
        assignee: str | None = "Advanced Energy Tech Inc",
        source_url: str = "https://patents.google.com/patent/US11223344B2/en",
        raw_data: dict | None = None,
    ) -> PatentRecord:
        """Helper to create test PatentRecord instances."""
        return PatentRecord(
            patent_number=patent_number,
            title=title,
            abstract=abstract,
            filing_date=filing_date,
            publication_date=publication_date,
            assignee=assignee,
            source_url=source_url,
            raw_data=raw_data if raw_data is not None else {"internal_key": "raw_payload"},
        )

    def test_all_fields_mapped_correctly(self) -> None:
        """Verify all 7 required keys are mapped with correct values."""
        patent = self._sample_patent()
        result = build_patent_extraction_input(patent)

        expected_keys = {
            "patent_number",
            "title",
            "abstract",
            "filing_date",
            "publication_date",
            "assignee",
            "source_url",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(len(result), 7)

        self.assertEqual(result["patent_number"], "US11223344B2")
        self.assertEqual(result["title"], "Solid Electrolyte Separator")
        self.assertEqual(result["abstract"], "Electrolyte composition for secondary batteries.")
        self.assertEqual(result["filing_date"], "2020-03-15")
        self.assertEqual(result["publication_date"], "2021-09-30")
        self.assertEqual(result["assignee"], "Advanced Energy Tech Inc")
        self.assertEqual(result["source_url"], "https://patents.google.com/patent/US11223344B2/en")

    def test_normalized_patent_number_preserved(self) -> None:
        """The canonical patent number is preserved exactly without alteration."""
        test_numbers = ["US11223344B2", "EP3456789A1", "WO2022012345A1"]

        for num in test_numbers:
            patent = self._sample_patent(
                patent_number=num,
                source_url=f"https://patents.google.com/patent/{num}/en",
            )
            result = build_patent_extraction_input(patent)
            self.assertEqual(result["patent_number"], num)

    def test_missing_optional_values_become_empty_strings(self) -> None:
        """Optional fields that are None are safely converted to empty strings."""
        patent = self._sample_patent(
            abstract=None,
            filing_date=None,
            publication_date=None,
            assignee=None,
        )
        result = build_patent_extraction_input(patent)

        self.assertEqual(result["abstract"], "")
        self.assertEqual(result["filing_date"], "")
        self.assertEqual(result["publication_date"], "")
        self.assertEqual(result["assignee"], "")

        # Verify none of the values in the dictionary are None
        for key, val in result.items():
            self.assertIsNotNone(val, f"Key '{key}' should not have None value")
            self.assertIsInstance(val, str, f"Key '{key}' should be a string")

    def test_raw_data_is_not_included(self) -> None:
        """The heavy internal raw_data dictionary is excluded from extraction input."""
        patent = self._sample_patent(raw_data={
            "raw_xml": "<xml>huge text</xml>",
            "ipc_codes": ["H01M"],
            "scores": [1, 2, 3],
        })
        result = build_patent_extraction_input(patent)

        self.assertNotIn("raw_data", result)
        self.assertNotIn("raw_xml", result)
        self.assertEqual(len(result), 7)

    def test_input_is_not_mutated(self) -> None:
        """The original PatentRecord remains completely unchanged after calling the adapter."""
        patent = self._sample_patent(
            patent_number="US10500000B2",
            title="Battery Anode Architecture",
            abstract=None,
            filing_date="2018-01-01",
            publication_date="2019-01-01",
            assignee="Sila Corp",
            source_url="https://patents.google.com/patent/US10500000B2/en",
            raw_data={"doc": "US10500000B2"},
        )

        # Record initial states
        initial_number = patent.patent_number
        initial_title = patent.title
        initial_abstract = patent.abstract
        initial_raw = dict(patent.raw_data)

        # Call adapter
        _ = build_patent_extraction_input(patent)

        # Assert post-call equality
        self.assertEqual(patent.patent_number, initial_number)
        self.assertEqual(patent.title, initial_title)
        self.assertIsNone(patent.abstract)
        self.assertEqual(patent.raw_data, initial_raw)

    def test_invalid_input_raises_type_error(self) -> None:
        """Passing any object that is not a PatentRecord raises TypeError."""
        invalid_inputs = [
            {"patent_number": "US11223344B2", "title": "Mock"},
            "US11223344B2",
            12345,
            None,
            ["US11223344B2"],
        ]

        for bad_input in invalid_inputs:
            with self.assertRaises(TypeError, msg=f"Should reject {type(bad_input).__name__}"):
                build_patent_extraction_input(bad_input)  # type: ignore

    def test_output_is_deterministic(self) -> None:
        """Multiple calls with the same patent record produce identical outputs."""
        patent = self._sample_patent()
        run1 = build_patent_extraction_input(patent)
        run2 = build_patent_extraction_input(patent)
        run3 = build_patent_extraction_input(patent)

        self.assertEqual(run1, run2)
        self.assertEqual(run2, run3)


if __name__ == "__main__":
    unittest.main()
