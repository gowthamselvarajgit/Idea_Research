"""Canonical patent data models, normalization, and validation rules.

Provides the immutable PatentRecord dataclass and deterministic helpers for
sanitizing, validating, and formatting publication-level patent numbers.
"""

from dataclasses import dataclass, field
import re
from typing import Optional

# Canonical pattern: [2 uppercase letters][document number starting with digit or US prefix][kind code starting with a letter]
PATENT_NUMBER_PATTERN = re.compile(
    r"^([A-Z]{2})((?:[0-9]|D[0-9]|RE[0-9]|PP[0-9])[0-9A-Z]{0,13})([A-Z][0-9A-Z]{0,2})$"
)

# Component-specific patterns
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")
DOC_NUMBER_PATTERN = re.compile(r"^(?:[0-9]|D[0-9]|RE[0-9]|PP[0-9])[0-9A-Z]{0,13}$")
KIND_CODE_PATTERN = re.compile(r"^[A-Z][0-9A-Z]{0,2}$")

# Characters to strip during sanitization: spaces, commas, hyphens, slashes, dots
PUNCTUATION_STRIP_PATTERN = re.compile(r"[\s,\-\/\.]+")


def clean_patent_string(val: str) -> str:
    """Strip punctuation and whitespace, then uppercase the string.

    Args:
        val: Input string.

    Returns:
        Uppercased string stripped of spaces, commas, hyphens, slashes, and dots.
    """
    if not isinstance(val, str):
        raise ValueError(f"Expected string input, got {type(val).__name__}")
    return PUNCTUATION_STRIP_PATTERN.sub("", val).strip().upper()


def validate_patent_number(patent_number: str) -> None:
    """Validate a normalized patent number against finalized publication-level rules.

    Rules:
        1. Exactly 2 uppercase country letters.
        2. Non-empty alphanumeric document number (1-14 characters).
        3. Kind code beginning with a letter and up to 3 alphanumeric characters.
        4. Reject malformed values rather than guessing.

    Args:
        patent_number: Normalized patent number string.

    Raises:
        ValueError: If the patent number fails validation.
    """
    if not isinstance(patent_number, str) or not patent_number:
        raise ValueError("Patent number must be a non-empty string.")

    match = PATENT_NUMBER_PATTERN.fullmatch(patent_number)
    if not match:
        raise ValueError(
            f"Malformed patent number: '{patent_number}'. "
            "Must strictly follow format: [2-letter country][1-14 char doc number][kind code starting with a letter]."
        )


def is_valid_patent_number(patent_number: str) -> bool:
    """Check if a patent number is valid without raising an exception."""
    try:
        validate_patent_number(patent_number)
        return True
    except (ValueError, TypeError):
        return False


def normalize_patent_number(raw_number: str) -> str:
    """Normalize a raw patent publication string into canonical format.

    Args:
        raw_number: Raw patent string (e.g. 'US 11,456,789-B2', 'ep-3456789-a1').

    Returns:
        Canonical normalized patent number (e.g. 'US11456789B2', 'EP3456789A1').

    Raises:
        ValueError: If the cleaned value fails validation.
    """
    cleaned = clean_patent_string(raw_number)
    validate_patent_number(cleaned)
    return cleaned


def normalize_patent_components(country: str, document_number: str, kind_code: str) -> str:
    """Construct and validate a normalized patent number from separate components.

    Args:
        country: 2-letter country code (e.g. 'US', 'EP', 'WO').
        document_number: Base document number (e.g. '11456789', '20230123456').
        kind_code: Document kind code (e.g. 'B2', 'A1', 'B').

    Returns:
        Canonical concatenated patent publication number.

    Raises:
        ValueError: If any component is invalid or empty.
    """
    clean_country = clean_patent_string(country) if country else ""
    clean_doc = clean_patent_string(document_number) if document_number else ""
    clean_kind = clean_patent_string(kind_code) if kind_code else ""

    if not clean_country or not COUNTRY_CODE_PATTERN.fullmatch(clean_country):
        raise ValueError(
            f"Invalid country code: '{country}'. Must be exactly 2 uppercase letters."
        )

    if not clean_doc or not DOC_NUMBER_PATTERN.fullmatch(clean_doc):
        raise ValueError(
            f"Invalid document number: '{document_number}'. Must be a non-empty alphanumeric string up to 14 characters."
        )

    if not clean_kind or not KIND_CODE_PATTERN.fullmatch(clean_kind):
        raise ValueError(
            f"Invalid kind code: '{kind_code}'. Must start with a letter and have up to 3 alphanumeric characters."
        )

    assembled = f"{clean_country}{clean_doc}{clean_kind}"
    validate_patent_number(assembled)
    return assembled


def build_canonical_url(patent_number: str) -> str:
    """Generate the deterministic Google Patents destination URL.

    Args:
        patent_number: Canonical or raw patent number.

    Returns:
        Canonical destination URL string.
    """
    normalized = normalize_patent_number(patent_number)
    return f"https://patents.google.com/patent/{normalized}/en"


@dataclass(frozen=True)
class PatentRecord:
    """Immutable normalized patent publication record."""

    patent_number: str
    title: str
    abstract: Optional[str]
    filing_date: Optional[str]
    publication_date: Optional[str]
    assignee: Optional[str]
    source_url: str
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate record integrity upon instantiation."""
        validate_patent_number(self.patent_number)
        if not self.source_url:
            object.__setattr__(self, "source_url", build_canonical_url(self.patent_number))
