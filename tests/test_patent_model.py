"""Unit tests for canonical PatentRecord model, validation, and normalization."""

from dataclasses import FrozenInstanceError
import unittest

from src.patents.models import (
    IndianPatentRecord,
    InPassPatentRecord,
    PatentRecord,
    PersonOrOrganization,
    build_canonical_url,
    clean_patent_string,
    is_valid_patent_number,
    normalize_patent_components,
    normalize_patent_number,
    validate_patent_number,
)


class TestPatentModelAndNormalization(unittest.TestCase):
    """Test suite for patent validation, normalization, and model immutability."""

    def test_us_grant_normalization(self):
        """Verify standard US patent grant normalization."""
        raw = "US 11,456,789 B2"
        normalized = normalize_patent_number(raw)
        self.assertEqual(normalized, "US11456789B2")

    def test_us_application_normalization(self):
        """Verify US published application normalization."""
        raw = "US 2023/0123456 A1"
        normalized = normalize_patent_number(raw)
        self.assertEqual(normalized, "US20230123456A1")

    def test_ep_publication_normalization(self):
        """Verify European Patent Office (EPO) publication normalization."""
        raw_app = "EP-3456789-A1"
        self.assertEqual(normalize_patent_number(raw_app), "EP3456789A1")

        raw_grant = "EP 3.456.789 B1"
        self.assertEqual(normalize_patent_number(raw_grant), "EP3456789B1")

    def test_wo_publication_normalization(self):
        """Verify WIPO PCT publication normalization."""
        raw = "WO 2023/123456 A1"
        normalized = normalize_patent_number(raw)
        self.assertEqual(normalized, "WO2023123456A1")

    def test_removal_of_punctuation_and_whitespace(self):
        """Verify removal of spaces, commas, hyphens, slashes, and dots."""
        raw = " U.S. , 11-456/789 . B2 "
        # Notice dots between U.S. are stripped, yielding US11456789B2
        normalized = normalize_patent_number(raw)
        self.assertEqual(normalized, "US11456789B2")

    def test_uppercase_conversion(self):
        """Verify automatic conversion of lowercase inputs to uppercase."""
        raw = "us11456789b2"
        self.assertEqual(normalize_patent_number(raw), "US11456789B2")
        self.assertEqual(normalize_patent_number("ep3456789a1"), "EP3456789A1")

    def test_canonical_url_generation(self):
        """Verify deterministic Google Patents destination URL construction."""
        expected_us = "https://patents.google.com/patent/US11456789B2/en"
        self.assertEqual(build_canonical_url("US 11,456,789 B2"), expected_us)

        expected_ep = "https://patents.google.com/patent/EP3456789A1/en"
        self.assertEqual(build_canonical_url("ep-3456789-a1"), expected_ep)

    def test_malformed_number_rejection(self):
        """Verify rejection of non-patent strings, symbols, or bad structure."""
        malformed_samples = [
            "NOT_A_PATENT",
            "1234567890",
            "US@@@@B2",
            "U11456789B2",  # 1-letter country code
            "USA11456789B2",  # 3-letter country code
            "",
            "   ",
        ]
        for sample in malformed_samples:
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    normalize_patent_number(sample)
                self.assertFalse(is_valid_patent_number(sample))

    def test_missing_kind_code_rejection(self):
        """Verify that numbers without a kind code are rejected rather than guessed."""
        missing_kind_samples = [
            "US11456789",
            "EP3456789",
            "WO2023123456",
            "US 11,456,789",
        ]
        for sample in missing_kind_samples:
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    normalize_patent_number(sample)
                self.assertFalse(is_valid_patent_number(sample))

    def test_missing_document_number_rejection(self):
        """Verify rejection when document number is empty or absent."""
        missing_doc_samples = [
            "USA1",  # Country US + Kind A1 without doc number
            "EPB2",  # Country EP + Kind B2 without doc number
        ]
        for sample in missing_doc_samples:
            with self.subTest(sample=sample):
                with self.assertRaises(ValueError):
                    normalize_patent_number(sample)
                self.assertFalse(is_valid_patent_number(sample))

        # Also test via components helper
        with self.assertRaises(ValueError):
            normalize_patent_components(country="US", document_number="", kind_code="B2")

    def test_normalize_patent_components(self):
        """Verify component-based assembly and validation."""
        assembled = normalize_patent_components(
            country="US",
            document_number=" 11,456,789 ",
            kind_code="b2",
        )
        self.assertEqual(assembled, "US11456789B2")

        assembled_ep = normalize_patent_components(
            country="ep",
            document_number="3456789",
            kind_code="A1",
        )
        self.assertEqual(assembled_ep, "EP3456789A1")

        # Test invalid country component
        with self.assertRaises(ValueError):
            normalize_patent_components(country="USA", document_number="123456", kind_code="A1")

        # Test invalid kind component
        with self.assertRaises(ValueError):
            normalize_patent_components(country="US", document_number="123456", kind_code="1A")

    def test_patent_record_dataclass_success_and_immutability(self):
        """Verify PatentRecord creation, field integrity, and frozen immutability."""
        record = PatentRecord(
            patent_number="US11456789B2",
            title="Solid Electrolyte System",
            abstract="A solid electrolyte composition for lithium batteries.",
            filing_date="2021-03-15",
            publication_date="2022-10-04",
            assignee="NextGen Battery Corp",
            source_url="https://patents.google.com/patent/US11456789B2/en",
            raw_data={"patentId": "US11456789B2"},
        )

        self.assertEqual(record.patent_number, "US11456789B2")
        self.assertEqual(record.assignee, "NextGen Battery Corp")

        # Test immutability
        with self.assertRaises(FrozenInstanceError):
            record.title = "Modified Title"  # type: ignore

    def test_patent_record_with_none_assignee(self):
        """Verify PatentRecord correctly accepts None for assignee (no fallback to inventors)."""
        record = PatentRecord(
            patent_number="EP3456789A1",
            title="Electrochemical Cell",
            abstract=None,
            filing_date="2020-01-10",
            publication_date="2021-07-15",
            assignee=None,
            source_url="https://patents.google.com/patent/EP3456789A1/en",
        )
        self.assertIsNone(record.assignee)

    def test_patent_record_rejects_invalid_patent_number(self):
        """Verify PatentRecord raises ValueError when given an invalid patent number."""
        with self.assertRaises(ValueError):
            PatentRecord(
                patent_number="INVALID_NUMBER",
                title="Bad Patent",
                abstract=None,
                filing_date=None,
                publication_date=None,
                assignee=None,
                source_url="",
            )

    def test_person_or_organization_model(self):
        """Verify PersonOrOrganization fields, validation, and immutability."""
        person = PersonOrOrganization(
            name="Dr. Jane Smith",
            address="123 Science Park, Bangalore",
            country="India",
            nationality="Indian",
        )
        self.assertEqual(person.name, "Dr. Jane Smith")
        self.assertEqual(person.address, "123 Science Park, Bangalore")
        self.assertEqual(person.country, "India")
        self.assertEqual(person.nationality, "Indian")

        # Immutability
        with self.assertRaises(FrozenInstanceError):
            person.name = "Dr. John Smith"  # type: ignore

        # Validation: empty name rejected
        with self.assertRaises(ValueError):
            PersonOrOrganization(name="")

        # Defaults for optional fields
        org = PersonOrOrganization(name="Innovation Labs Ltd")
        self.assertEqual(org.address, "")
        self.assertEqual(org.country, "")
        self.assertEqual(org.nationality, "")

    def test_inpass_patent_record_all_metadata_fields(self):
        """Verify all InPASS patent metadata fields are represented correctly."""
        applicant = PersonOrOrganization(
            name="Vellore Institute of Technology",
            address="Katpadi, Vellore - 632014, Tamil Nadu",
            country="India",
            nationality="Indian",
        )
        inventor = PersonOrOrganization(
            name="Dr. S. Ramesh",
            address="School of Advanced Sciences, VIT, Vellore",
            country="India",
            nationality="Indian",
        )

        record = InPassPatentRecord(
            application_number="202641109752",
            publication_number="38/2026",
            publication_date="18/09/2026",
            filing_date="12/09/2026",
            title="A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
            ipc="G01N 21/47, G01N 21/21, G01N 21/49, G01N 21/51, G01N 33/18",
            abstract="A dual-wavelength optical detection system for microplastics in water streams.",
            specification="Detailed specification of the optical detector array and flow channel.",
            claims="1. An optical detection apparatus comprising: a laser source, a detector...",
            applicants=[applicant],
            inventors=[inventor],
            source="INPASS",
            source_url="https://iprsearch.ipindia.gov.in/publicsearch?app=202641109752",
            raw_data={"test_key": "test_val"},
        )

        # Check all 13 core fields
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.publication_number, "38/2026")
        self.assertEqual(record.publication_date, "18/09/2026")
        self.assertEqual(record.filing_date, "12/09/2026")
        self.assertEqual(
            record.title,
            "A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
        )
        self.assertEqual(record.ipc, "G01N 21/47, G01N 21/21, G01N 21/49, G01N 21/51, G01N 33/18")
        self.assertEqual(record.abstract, "A dual-wavelength optical detection system for microplastics in water streams.")
        self.assertEqual(record.specification, "Detailed specification of the optical detector array and flow channel.")
        self.assertEqual(record.claims, "1. An optical detection apparatus comprising: a laser source, a detector...")
        self.assertEqual(len(record.applicants), 1)
        self.assertEqual(record.applicants[0], applicant)
        self.assertEqual(len(record.inventors), 1)
        self.assertEqual(record.inventors[0], inventor)
        self.assertEqual(record.source, "INPASS")
        self.assertEqual(record.source_url, "https://iprsearch.ipindia.gov.in/publicsearch?app=202641109752")
        self.assertEqual(record.raw_data, {"test_key": "test_val"})

        # Backward compatibility properties
        self.assertEqual(record.patent_number, "38/2026")
        self.assertEqual(record.assignee, "Vellore Institute of Technology")

        # Immutability
        with self.assertRaises(FrozenInstanceError):
            record.title = "New Title"  # type: ignore

    def test_inpass_patent_record_multiple_applicants_and_inventors(self):
        """Verify an InPASS patent record can contain multiple structured applicants and inventors."""
        applicants = [
            PersonOrOrganization(
                name="Indian Institute of Technology Madras",
                address="IIT P.O., Chennai - 600036",
                country="India",
                nationality="Indian",
            ),
            PersonOrOrganization(
                name="Tech Innovations Pvt Ltd",
                address="Whitefield, Bangalore - 560066",
                country="India",
                nationality="Indian",
            ),
        ]

        inventors = [
            PersonOrOrganization(
                name="Prof. Rajesh Kumar",
                address="Department of Mechanical Engineering, IIT Madras",
                country="India",
                nationality="Indian",
            ),
            PersonOrOrganization(
                name="Dr. Ananya Sharma",
                address="Center for Water Research, IIT Madras",
                country="India",
                nationality="Indian",
            ),
            PersonOrOrganization(
                name="Karthik Subramanian",
                address="Tech Innovations Pvt Ltd, Bangalore",
                country="India",
                nationality="Indian",
            ),
        ]

        record = IndianPatentRecord(
            application_number="202641109752",
            title="Multispectral Water Sensor",
            applicants=applicants,
            inventors=inventors,
        )

        # Multiple applicants verified
        self.assertEqual(len(record.applicants), 2)
        self.assertEqual(record.applicants[0].name, "Indian Institute of Technology Madras")
        self.assertEqual(record.applicants[1].name, "Tech Innovations Pvt Ltd")
        self.assertEqual(record.assignee, "Indian Institute of Technology Madras")

        # Multiple inventors verified
        self.assertEqual(len(record.inventors), 3)
        self.assertEqual(record.inventors[0].name, "Prof. Rajesh Kumar")
        self.assertEqual(record.inventors[1].name, "Dr. Ananya Sharma")
        self.assertEqual(record.inventors[2].name, "Karthik Subramanian")

        # Verify each applicant and inventor retains structured address, country, nationality
        for app in record.applicants:
            self.assertTrue(app.name)
            self.assertEqual(app.country, "India")
            self.assertEqual(app.nationality, "Indian")

        for inv in record.inventors:
            self.assertTrue(inv.name)
            self.assertEqual(inv.country, "India")
            self.assertEqual(inv.nationality, "Indian")

        # Verify to_dict serializes structured entities
        data = record.to_dict()
        self.assertEqual(len(data["applicants"]), 2)
        self.assertEqual(len(data["inventors"]), 3)
        self.assertEqual(data["applicants"][0]["name"], "Indian Institute of Technology Madras")
        self.assertEqual(data["inventors"][0]["name"], "Prof. Rajesh Kumar")

    def test_inpass_patent_record_validation(self):
        """Verify InPassPatentRecord input validation."""
        # Empty application number must raise ValueError
        with self.assertRaises(ValueError):
            InPassPatentRecord(application_number="")

        # Invalid applicant item type must raise TypeError
        with self.assertRaises(TypeError):
            InPassPatentRecord(
                application_number="202641109752",
                applicants=[123],  # type: ignore
            )

        # Invalid raw_data type must raise TypeError
        with self.assertRaises(TypeError):
            InPassPatentRecord(
                application_number="202641109752",
                raw_data="not-a-dict",  # type: ignore
            )



if __name__ == "__main__":
    unittest.main()
