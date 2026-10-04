"""Adapter preparing canonical PatentRecord context for AI problem extraction."""

from typing import Any
from src.patents.models import PatentRecord


def build_patent_extraction_input(patent: PatentRecord) -> dict[str, str]:
    """Convert a canonical PatentRecord into the text context expected by an extractor.

    Maps all core metadata fields to a clean dictionary, converting missing/None
    optional values to empty strings and excluding internal raw payloads.

    Args:
        patent: Normalized PatentRecord instance.

    Returns:
        dict[str, str]: Standardized dictionary containing exactly 7 keys:
            - patent_number
            - title
            - abstract
            - filing_date
            - publication_date
            - assignee
            - source_url

    Raises:
        TypeError: If input is not an instance of PatentRecord.
    """
    if not isinstance(patent, PatentRecord):
        raise TypeError(f"Expected PatentRecord instance, got {type(patent).__name__}.")

    return {
        "patent_number": patent.patent_number,
        "title": patent.title if patent.title is not None else "",
        "abstract": patent.abstract if patent.abstract is not None else "",
        "filing_date": patent.filing_date if patent.filing_date is not None else "",
        "publication_date": patent.publication_date if patent.publication_date is not None else "",
        "assignee": patent.assignee if patent.assignee is not None else "",
        "source_url": patent.source_url if patent.source_url is not None else "",
    }
