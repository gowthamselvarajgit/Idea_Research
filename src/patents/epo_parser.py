"""Response parser for EPO Open Patent Services (OPS) XML payloads.

Parses raw XML from EPO OPS search responses and maps each exchange-document
into the canonical immutable PatentRecord model with strict validation.
"""

import logging
from typing import Optional
import xml.etree.ElementTree as ET

from src.patents.base_client import PatentClientError
from src.patents.models import (
    PatentRecord,
    build_canonical_url,
    normalize_patent_components,
)

logger = logging.getLogger(__name__)


class EPOParserError(PatentClientError):
    """Raised when the root EPO XML is completely malformed or unparseable."""
    pass


def _local_tag(elem: ET.Element) -> str:
    """Return the tag name stripped of any XML namespace prefix."""
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def _clean_date(raw_date: Optional[str]) -> Optional[str]:
    """Format EPO date strings (typically YYYYMMDD) into standard YYYY-MM-DD."""
    if not raw_date:
        return None
    cleaned = raw_date.strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}"
    if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
        return cleaned
    return cleaned if cleaned else None


def _get_element_full_text(elem: Optional[ET.Element]) -> Optional[str]:
    """Extract and concatenate all text from an element and its descendants."""
    if elem is None:
        return None
    texts = [t for t in elem.itertext() if t]
    combined = " ".join(" ".join(texts).split())
    return combined if combined else None


def _parse_exchange_document(doc_elem: ET.Element) -> Optional[PatentRecord]:
    """Parse a single exchange-document XML node into a PatentRecord.

    Skips and returns None if required publication identifiers are missing or invalid.
    """
    # 1. Identify Country, Document Number, and Kind Code
    country = doc_elem.attrib.get("country")
    doc_number = doc_elem.attrib.get("doc-number")
    kind = doc_elem.attrib.get("kind")

    # If missing on root attributes, fallback to publication-reference/document-id
    if not (country and doc_number and kind):
        for elem in doc_elem.iter():
            if _local_tag(elem) == "publication-reference":
                for child in elem.iter():
                    tag = _local_tag(child)
                    if tag == "country" and not country:
                        country = child.text
                    elif tag == "doc-number" and not doc_number:
                        doc_number = child.text
                    elif tag == "kind" and not kind:
                        kind = child.text

    try:
        patent_number = normalize_patent_components(
            country=country or "",
            document_number=doc_number or "",
            kind_code=kind or "",
        )
    except ValueError as err:
        logger.warning(
            "Skipping malformed EPO patent candidate (country=%s, doc=%s, kind=%s): %s",
            country,
            doc_number,
            kind,
            err,
        )
        return None

    # 2. Extract Title (prefer English lang='en')
    title: str = "Untitled"
    titles = [e for e in doc_elem.iter() if _local_tag(e) == "invention-title"]
    if titles:
        en_title = next(
            (t for t in titles if t.attrib.get("lang", "").lower().startswith("en")),
            None,
        )
        selected_title_elem = en_title if en_title is not None else titles[0]
        extracted_title = _get_element_full_text(selected_title_elem)
        if extracted_title:
            title = extracted_title

    # 3. Extract Abstract (prefer English lang='en')
    abstract: Optional[str] = None
    abstracts = [e for e in doc_elem.iter() if _local_tag(e) == "abstract"]
    if abstracts:
        en_abstract = next(
            (a for a in abstracts if a.attrib.get("lang", "").lower().startswith("en")),
            None,
        )
        selected_abstract_elem = en_abstract if en_abstract is not None else abstracts[0]
        abstract = _get_element_full_text(selected_abstract_elem)


    # 4. Extract Filing Date (from application-reference)
    filing_date: Optional[str] = None
    for elem in doc_elem.iter():
        if _local_tag(elem) == "application-reference":
            for child in elem.iter():
                if _local_tag(child) == "date" and child.text:
                    filing_date = _clean_date(child.text)
                    break
            if filing_date:
                break

    # 5. Extract Publication Date (from publication-reference)
    publication_date: Optional[str] = None
    for elem in doc_elem.iter():
        if _local_tag(elem) == "publication-reference":
            for child in elem.iter():
                if _local_tag(child) == "date" and child.text:
                    publication_date = _clean_date(child.text)
                    break
            if publication_date:
                break

    # 6. Extract Applicant / Assignee (under parties/applicants)
    assignee: Optional[str] = None
    for elem in doc_elem.iter():
        if _local_tag(elem) in ("applicant", "applicant-name"):
            name_text = _get_element_full_text(elem)
            if name_text:
                assignee = name_text
                break

    # 7. Generate Canonical URL & Preserve Raw XML
    source_url = build_canonical_url(patent_number)
    raw_xml_str = ET.tostring(doc_elem, encoding="unicode")
    raw_data = {"raw_xml": raw_xml_str}

    return PatentRecord(
        patent_number=patent_number,
        title=title,
        abstract=abstract,
        filing_date=filing_date,
        publication_date=publication_date,
        assignee=assignee,
        source_url=source_url,
        raw_data=raw_data,
    )


def parse_epo_search_response(xml_content: str) -> list[PatentRecord]:
    """Parse raw EPO OPS search XML response into a list of canonical PatentRecord instances.

    Args:
        xml_content: Raw XML response string from EPOClient.search().

    Returns:
        list[PatentRecord]: Parsed and validated patent records.

    Raises:
        EPOParserError: If the overall XML syntax is invalid.
    """
    if not xml_content or not xml_content.strip():
        return []

    try:
        root = ET.fromstring(xml_content.strip())
    except ET.ParseError as err:
        raise EPOParserError(f"Malformed EPO OPS XML response: {err}") from err

    records: list[PatentRecord] = []

    # Search for all exchange-document elements across any namespace
    for elem in root.iter():
        if _local_tag(elem) == "exchange-document":
            parsed_record = _parse_exchange_document(elem)
            if parsed_record:
                records.append(parsed_record)

    return records
