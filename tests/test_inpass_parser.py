"""Unit tests for the InPASS PatentDetails HTML parser."""

import unittest

from src.patents.inpass_parser import InPassParserError, parse_inpass_patent_details
from src.patents.models import InPassPatentRecord, PersonOrOrganization

REPRESENTATIVE_INPASS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Patent Details</title></head>
<body>
<table class="table table-bordered">
  <tbody>
    <tr>
      <td>Application Number</td>
      <td>202641109752</td>
    </tr>
    <tr>
      <td>Publication Number</td>
      <td>38/2026</td>
    </tr>
    <tr>
      <td>Publication Date</td>
      <td>18/09/2026</td>
    </tr>
    <tr>
      <td>Filing Date</td>
      <td>12/09/2026</td>
    </tr>
    <tr>
      <td>Invention Title</td>
      <td>A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER</td>
    </tr>
    <tr>
      <td>International Classification</td>
      <td>G01N 21/47, G01N 21/21, G01N 21/49</td>
    </tr>
    <tr>
      <td colspan="2">Applicant</td>
    </tr>
    <tr>
      <td colspan="2">
        <table class="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Address</th>
              <th>Country</th>
              <th>Nationality</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Vellore Institute of Technology</td>
              <td>Katpadi, Vellore - 632014, Tamil Nadu</td>
              <td>India</td>
              <td>Indian</td>
            </tr>
            <tr>
              <td>Dr. R. Kavitha</td>
              <td>VIT University, Vellore</td>
              <td>India</td>
              <td>Indian</td>
            </tr>
          </tbody>
        </table>
      </td>
    </tr>
    <tr>
      <td colspan="2">Inventor</td>
    </tr>
    <tr>
      <td colspan="2">
        <table class="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Address</th>
              <th>Country</th>
              <th>Nationality</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>T. ASHA</td>
              <td>Department of EEE, VIT</td>
              <td>India</td>
              <td>Indian</td>
            </tr>
            <tr>
              <td>S. HARINI SHREE</td>
              <td>Department of EEE, VIT</td>
              <td>India</td>
              <td>Indian</td>
            </tr>
          </tbody>
        </table>
      </td>
    </tr>
    <tr>
      <td colspan="2">Abstract</td>
    </tr>
    <tr>
      <td colspan="2">
        An inline dual-wavelength optical detection system for detecting microplastics in flowing water streams.
      </td>
    </tr>
    <tr>
      <td colspan="2">Complete Specification</td>
    </tr>
    <tr>
      <td colspan="2">
        <p>FIELD OF THE INVENTION</p>
        <p>The present invention relates to optical sensor systems for microplastics.</p>
        <p>BACKGROUND OF THE INVENTION</p>
        <p>Existing water monitoring solutions suffer from high latency and sample contamination.</p>
      </td>
    </tr>
    <tr>
      <td colspan="2">Claims</td>
    </tr>
    <tr>
      <td colspan="2">
        <p>1. An optical detection apparatus comprising: a flow cell and dual-wavelength laser.</p>
        <p>2. The apparatus of claim 1, further comprising a photodetector array.</p>
      </td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""


class TestInPassParser(unittest.TestCase):
    """Test suite for InPASS PatentDetails HTML parser."""

    def test_parse_full_representative_html(self):
        """Verify complete extraction of standard metadata, 2 applicants, 2 inventors, abstract, spec, and claims."""
        record = parse_inpass_patent_details(REPRESENTATIVE_INPASS_HTML)

        self.assertIsInstance(record, InPassPatentRecord)
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.publication_number, "38/2026")
        self.assertEqual(record.publication_date, "18/09/2026")
        self.assertEqual(record.filing_date, "12/09/2026")
        self.assertEqual(
            record.title,
            "A SYSTEM AND METHOD FOR INLINE DUAL-WAVELENGTH OPTICAL DETECTION OF MICROPLASTICS IN FLOWING WATER",
        )
        self.assertEqual(record.ipc, "G01N 21/47, G01N 21/21, G01N 21/49")
        self.assertEqual(
            record.abstract,
            "An inline dual-wavelength optical detection system for detecting microplastics in flowing water streams.",
        )
        self.assertIn("FIELD OF THE INVENTION", record.specification)
        self.assertIn("Existing water monitoring solutions suffer from high latency", record.specification)
        self.assertIn("1. An optical detection apparatus comprising", record.claims)
        self.assertIn("2. The apparatus of claim 1", record.claims)

        # 2 Applicants verified
        self.assertEqual(len(record.applicants), 2)
        app1, app2 = record.applicants[0], record.applicants[1]
        self.assertEqual(app1.name, "Vellore Institute of Technology")
        self.assertEqual(app1.address, "Katpadi, Vellore - 632014, Tamil Nadu")
        self.assertEqual(app1.country, "India")
        self.assertEqual(app1.nationality, "Indian")

        self.assertEqual(app2.name, "Dr. R. Kavitha")
        self.assertEqual(app2.address, "VIT University, Vellore")
        self.assertEqual(app2.country, "India")
        self.assertEqual(app2.nationality, "Indian")

        # 2 Inventors verified
        self.assertEqual(len(record.inventors), 2)
        inv1, inv2 = record.inventors[0], record.inventors[1]
        self.assertEqual(inv1.name, "T. ASHA")
        self.assertEqual(inv1.address, "Department of EEE, VIT")
        self.assertEqual(inv1.country, "India")
        self.assertEqual(inv1.nationality, "Indian")

        self.assertEqual(inv2.name, "S. HARINI SHREE")
        self.assertEqual(inv2.address, "Department of EEE, VIT")
        self.assertEqual(inv2.country, "India")
        self.assertEqual(inv2.nationality, "Indian")

        # Verify source and cross-compatibility properties
        self.assertEqual(record.source, "INPASS")
        self.assertEqual(record.patent_number, "38/2026")
        self.assertEqual(record.assignee, "Vellore Institute of Technology")

    def test_parse_missing_optional_applicant_and_inventor_sections(self):
        """Verify that missing Applicant and Inventor sections produce empty lists without error."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr><td>Publication Number</td><td>38/2026</td></tr>
          <tr><td>Invention Title</td><td>Water Purification Sensor</td></tr>
          <tr><td>Abstract</td><td>Compact inline sensor.</td></tr>
          <tr><td>Complete Specification</td><td>Description of the sensor.</td></tr>
          <tr><td>Claims</td><td>1. A sensor.</td></tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)

        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.publication_number, "38/2026")
        self.assertEqual(len(record.applicants), 0)
        self.assertEqual(len(record.inventors), 0)
        self.assertEqual(record.to_dict()["applicants"], [])
        self.assertEqual(record.to_dict()["inventors"], [])
        self.assertIsNone(record.assignee)

    def test_parse_missing_optional_metadata_fields(self):
        """Verify that missing optional metadata fields default gracefully to None or empty values."""
        minimal_html = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
        </table>
        """
        record = parse_inpass_patent_details(minimal_html)

        self.assertEqual(record.application_number, "202641109752")
        self.assertIsNone(record.publication_number)
        self.assertIsNone(record.publication_date)
        self.assertIsNone(record.filing_date)
        self.assertEqual(record.title, "")
        self.assertIsNone(record.ipc)
        self.assertIsNone(record.abstract)
        self.assertIsNone(record.specification)
        self.assertIsNone(record.claims)
        self.assertEqual(len(record.applicants), 0)
        self.assertEqual(len(record.inventors), 0)
        self.assertEqual(record.patent_number, "202641109752")  # Fallback to application number

    def test_applicant_and_inventor_separation(self):
        """Verify that Applicant and Inventor sections are strictly segregated and not confused."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr><td colspan="2">Applicant</td></tr>
          <tr><td colspan="2">
            <table>
              <tr><th>Name</th><th>Address</th><th>Country</th><th>Nationality</th></tr>
              <tr><td>Corporate Applicant Inc</td><td>100 Tech Blvd</td><td>India</td><td>Indian</td></tr>
            </table>
          </td></tr>
          <tr><td colspan="2">Inventor</td></tr>
          <tr><td colspan="2">
            <table>
              <tr><th>Name</th><th>Address</th><th>Country</th><th>Nationality</th></tr>
              <tr><td>Dr. Individual Researcher</td><td>200 Lab Way</td><td>India</td><td>Indian</td></tr>
            </table>
          </td></tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)

        self.assertEqual(len(record.applicants), 1)
        self.assertEqual(record.applicants[0].name, "Corporate Applicant Inc")

        self.assertEqual(len(record.inventors), 1)
        self.assertEqual(record.inventors[0].name, "Dr. Individual Researcher")

        self.assertNotEqual(record.applicants[0].name, record.inventors[0].name)

    def test_cleaning_html_tags_and_preserving_text(self):
        """Verify that HTML tags, unclosed breaks, and entities are stripped while preserving text structure."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>&nbsp; 202641109752 &nbsp;</td></tr>
          <tr><td>Invention Title</td><td><b>A &amp; B</b> Method for Water Analysis<br></td></tr>
          <tr><td>Abstract</td><td><p>Line 1 of abstract.</p><p>Line 2 with &quot;quotes&quot;.</p></td></tr>
          <tr><td>Complete Specification</td><td><div>Paragraph 1.</div><div>Paragraph 2.</div></td></tr>
          <tr><td>Claims</td><td><p>1. Claim first part.<br>Claim second part.</p><p>2. Claim second.</p></td></tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)

        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.title, "A & B Method for Water Analysis")
        self.assertIn('Line 2 with "quotes".', record.abstract)
        self.assertNotIn("<p>", record.abstract)
        self.assertNotIn("<div>", record.specification)
        self.assertIn("Paragraph 1.\n\nParagraph 2.", record.specification)
        self.assertNotIn("<br>", record.claims)
        self.assertIn("1. Claim first part.\nClaim second part.\n\n2. Claim second.", record.claims)

    def test_parse_missing_application_number_raises_error(self):
        """Verify that an HTML payload without Application Number raises InPassParserError."""
        bad_html = """
        <table>
          <tr><td>Publication Number</td><td>38/2026</td></tr>
          <tr><td>Title</td><td>Some Title</td></tr>
        </table>
        """
        with self.assertRaises(InPassParserError):
            parse_inpass_patent_details(bad_html)

    def test_parse_empty_payload_raises_error(self):
        """Verify that empty or None HTML payloads raise InPassParserError."""
        with self.assertRaises(InPassParserError):
            parse_inpass_patent_details("")

        with self.assertRaises(InPassParserError):
            parse_inpass_patent_details("   ")

        with self.assertRaises(InPassParserError):
            parse_inpass_patent_details(None)  # type: ignore


    def test_parse_real_inpass_filing_date_and_ipc_aliases(self):
        """Verify extraction with real InPASS labels 'Application Filing Date' and 'Classification (IPC)'."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr><td>Application Filing Date</td><td>12/09/2026</td></tr>
          <tr><td>Classification (IPC)</td><td>G01N 21/47, G01N 21/21, G01N 21/49</td></tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.filing_date, "12/09/2026")
        self.assertEqual(record.ipc, "G01N 21/47, G01N 21/21, G01N 21/49")

    def test_parse_real_inpass_abstract_in_same_cell(self):
        """Verify extraction of Abstract when label and text reside in the same table cell."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr>
            <td colspan="2">
              <strong>Abstract:</strong><br>
              <br>
              An inline continuous optical detection system for detecting microplastics in flowing water.
            </td>
          </tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(
            record.abstract,
            "An inline continuous optical detection system for detecting microplastics in flowing water.",
        )

    def test_parse_real_inpass_complete_specification_and_claims_textarea(self):
        """Verify extraction and splitting of COMPLETE_SPECIFICATION textarea into specification and claims."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr>
            <td colspan="2">
              <strong><u>Complete Specification</u></strong><br>
              <textarea id="COMPLETE_SPECIFICATION" name="COMPLETE_SPECIFICATION">
Description:FIELD OF THE INVENTION
The present invention relates to inline water sensors.
BACKGROUND OF THE INVENTION
Conventional sensors have high false-positive rates. , Claims:1. An inline sensor comprising an optical chamber and light source.
2. The sensor of claim 1, further comprising a microcontroller.
              </textarea>
            </td>
          </tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)
        self.assertEqual(record.application_number, "202641109752")
        self.assertIsNotNone(record.specification)
        self.assertIsNotNone(record.claims)
        self.assertIn("FIELD OF THE INVENTION", record.specification)
        self.assertIn("Conventional sensors have high false-positive rates.", record.specification)
        self.assertNotIn("Claims:1.", record.specification)
        self.assertTrue(record.claims.startswith("1. An inline sensor comprising"))
        self.assertIn("2. The sensor of claim 1", record.claims)

    def test_parse_real_inpass_all_five_structures_combined(self):
        """Verify simultaneous extraction of all five real InPASS structures."""
        html_content = """
        <table>
          <tr><td>Application Number</td><td>202641109752</td></tr>
          <tr><td>Publication Number</td><td>38/2026</td></tr>
          <tr><td>Publication Date</td><td>18/09/2026</td></tr>
          <tr><td>Application Filing Date</td><td>12/09/2026</td></tr>
          <tr><td>Invention Title</td><td>INLINE OPTICAL DETECTION OF MICROPLASTICS</td></tr>
          <tr><td>Classification (IPC)</td><td>G01N 21/47, G01N 33/18</td></tr>
          <tr>
            <td colspan="2">
              <strong>Abstract:</strong><br><br>
              A dual-wavelength optical sensor for microplastic detection in water.
            </td>
          </tr>
          <tr>
            <td colspan="2">
              <strong><u>Complete Specification</u></strong><br>
              <textarea class="Complete-Specification" id="COMPLETE_SPECIFICATION">
Detailed description of inline optical detection apparatus. , Claims:1. An optical sensor apparatus.
2. The apparatus of claim 1.
              </textarea>
            </td>
          </tr>
        </table>
        """
        record = parse_inpass_patent_details(html_content)
        self.assertEqual(record.application_number, "202641109752")
        self.assertEqual(record.publication_number, "38/2026")
        self.assertEqual(record.publication_date, "18/09/2026")
        self.assertEqual(record.filing_date, "12/09/2026")
        self.assertEqual(record.title, "INLINE OPTICAL DETECTION OF MICROPLASTICS")
        self.assertEqual(record.ipc, "G01N 21/47, G01N 33/18")
        self.assertEqual(record.abstract, "A dual-wavelength optical sensor for microplastic detection in water.")
        self.assertEqual(record.specification, "Detailed description of inline optical detection apparatus.")
        self.assertEqual(record.claims, "1. An optical sensor apparatus.\n2. The apparatus of claim 1.")


if __name__ == "__main__":
    unittest.main()

