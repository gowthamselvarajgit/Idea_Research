"""Unit tests for EPO OPS search response XML parser."""

import unittest

from src.patents.epo_parser import EPOParserError, parse_epo_search_response
from src.patents.models import PatentRecord

MOCK_VALID_SINGLE_PATENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">
    <ops:biblio-search total-result-count="1">
        <ops:search-result>
            <exchange-documents>
                <exchange-document country="EP" doc-number="3456789" kind="A1">
                    <bibliographic-data>
                        <publication-reference>
                            <document-id>
                                <country>EP</country>
                                <doc-number>3456789</doc-number>
                                <kind>A1</kind>
                                <date>20190320</date>
                            </document-id>
                        </publication-reference>
                        <application-reference>
                            <document-id>
                                <country>EP</country>
                                <doc-number>18194000</doc-number>
                                <date>20180912</date>
                            </document-id>
                        </application-reference>
                        <invention-title lang="fr">Système d'électrolyte solide</invention-title>
                        <invention-title lang="en">Solid state electrolyte for high energy density lithium battery</invention-title>
                        <parties>
                            <applicants>
                                <applicant sequence="1" app-type="applicant">
                                    <applicant-name>
                                        <name>QUANTUM ENERGY CORP</name>
                                    </applicant-name>
                                </applicant>
                            </applicants>
                        </parties>
                    </bibliographic-data>
                    <abstract lang="fr">
                        <p>Une composition d'électrolyte solide...</p>
                    </abstract>
                    <abstract lang="en">
                        <p>A solid-state electrolyte composition that prevents dendrite formation.</p>
                    </abstract>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""

MOCK_MULTIPLE_PATENTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">
    <ops:biblio-search total-result-count="2">
        <ops:search-result>
            <exchange-documents>
                <exchange-document country="US" doc-number="11456789" kind="B2">
                    <bibliographic-data>
                        <publication-reference>
                            <document-id>
                                <date>20221004</date>
                            </document-id>
                        </publication-reference>
                        <application-reference>
                            <document-id>
                                <date>20200515</date>
                            </document-id>
                        </application-reference>
                        <invention-title lang="en">Lithium Anode Protection Layer</invention-title>
                        <parties>
                            <applicants>
                                <applicant>
                                    <applicant-name>
                                        <name>BATTERY INNOVATIONS LLC</name>
                                    </applicant-name>
                                </applicant>
                            </applicants>
                        </parties>
                    </bibliographic-data>
                    <abstract lang="en">
                        <p>Protective coating for lithium metal anodes.</p>
                    </abstract>
                </exchange-document>
                <exchange-document country="WO" doc-number="2023123456" kind="A1">
                    <bibliographic-data>
                        <publication-reference>
                            <document-id>
                                <date>20230629</date>
                            </document-id>
                        </publication-reference>
                        <application-reference>
                            <document-id>
                                <date>20221220</date>
                            </document-id>
                        </application-reference>
                        <invention-title lang="en">Ceramic Separator for Energy Storage</invention-title>
                    </bibliographic-data>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""

MOCK_WITH_MALFORMED_ENTRY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ops:world-patent-data xmlns:ops="http://ops.epo.org" xmlns="http://www.epo.org/exchange">
    <ops:biblio-search total-result-count="2">
        <ops:search-result>
            <exchange-documents>
                <!-- Malformed record: missing kind code and invalid country -->
                <exchange-document country="INVALID" doc-number="123" kind="">
                    <bibliographic-data>
                        <invention-title lang="en">Bad Patent Record</invention-title>
                    </bibliographic-data>
                </exchange-document>
                <!-- Valid record -->
                <exchange-document country="EP" doc-number="3456789" kind="B1">
                    <bibliographic-data>
                        <publication-reference>
                            <document-id>
                                <date>20200812</date>
                            </document-id>
                        </publication-reference>
                        <invention-title lang="en">Valid EP Patent</invention-title>
                    </bibliographic-data>
                    <abstract lang="en">
                        <p>Valid abstract text.</p>
                    </abstract>
                </exchange-document>
            </exchange-documents>
        </ops:search-result>
    </ops:biblio-search>
</ops:world-patent-data>"""


class TestEPOParser(unittest.TestCase):
    """Test suite for parsing EPO OPS search responses into canonical PatentRecord models."""

    def test_single_valid_patent_parsing(self):
        """Verify complete extraction of single patent record."""
        records = parse_epo_search_response(MOCK_VALID_SINGLE_PATENT_XML)

        self.assertEqual(len(records), 1)
        record = records[0]

        self.assertIsInstance(record, PatentRecord)
        self.assertEqual(record.patent_number, "EP3456789A1")
        self.assertEqual(
            record.title,
            "Solid state electrolyte for high energy density lithium battery",
        )
        self.assertEqual(
            record.abstract,
            "A solid-state electrolyte composition that prevents dendrite formation.",
        )
        self.assertEqual(record.filing_date, "2018-09-12")
        self.assertEqual(record.publication_date, "2019-03-20")
        self.assertEqual(record.assignee, "QUANTUM ENERGY CORP")
        self.assertEqual(
            record.source_url,
            "https://patents.google.com/patent/EP3456789A1/en",
        )
        self.assertIn("raw_xml", record.raw_data)
        self.assertIn("3456789", record.raw_data["raw_xml"])
        self.assertIn("QUANTUM ENERGY CORP", record.raw_data["raw_xml"])

    def test_multiple_patents_parsing(self):
        """Verify multiple patents are parsed from a search response."""
        records = parse_epo_search_response(MOCK_MULTIPLE_PATENTS_XML)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].patent_number, "US11456789B2")
        self.assertEqual(records[0].title, "Lithium Anode Protection Layer")
        self.assertEqual(records[0].assignee, "BATTERY INNOVATIONS LLC")

        self.assertEqual(records[1].patent_number, "WO2023123456A1")
        self.assertEqual(records[1].title, "Ceramic Separator for Energy Storage")
        self.assertIsNone(records[1].abstract)
        self.assertIsNone(records[1].assignee)

    def test_missing_optional_fields_handled_gracefully(self):
        """Verify patents with missing abstract/assignee don't crash and default to None."""
        records = parse_epo_search_response(MOCK_MULTIPLE_PATENTS_XML)
        wo_record = records[1]

        self.assertIsNone(wo_record.abstract)
        self.assertIsNone(wo_record.assignee)
        self.assertEqual(wo_record.filing_date, "2022-12-20")
        self.assertEqual(wo_record.publication_date, "2023-06-29")

    def test_malformed_individual_patent_is_skipped(self):
        """Verify malformed individual patent is skipped without aborting valid ones."""
        records = parse_epo_search_response(MOCK_WITH_MALFORMED_ENTRY_XML)

        # Only the valid EP patent should be returned
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].patent_number, "EP3456789B1")
        self.assertEqual(records[0].title, "Valid EP Patent")

    def test_malformed_overall_xml_raises_parser_error(self):
        """Verify invalid XML syntax raises clear EPOParserError."""
        invalid_xml = "<ops:world-patent-data><unclosed-tag>"
        with self.assertRaises(EPOParserError) as ctx:
            parse_epo_search_response(invalid_xml)

        self.assertIn("Malformed EPO OPS XML response", str(ctx.exception))

    def test_empty_or_whitespace_xml_returns_empty_list(self):
        """Verify empty string or whitespace returns empty list safely."""
        self.assertEqual(parse_epo_search_response(""), [])
        self.assertEqual(parse_epo_search_response("   "), [])


if __name__ == "__main__":
    unittest.main()
