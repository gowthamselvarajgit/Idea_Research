"""Canonical patent data models, normalization, and validation rules.

Provides the immutable PatentRecord dataclass and deterministic helpers for
sanitizing, validating, and formatting publication-level patent numbers.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Optional, Sequence, Union

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


@dataclass(frozen=True)
class PersonOrOrganization:
    """Reusable entity representing a person or organization associated with a patent."""

    name: str
    address: str = ""
    country: str = ""
    nationality: str = ""

    def __post_init__(self) -> None:
        """Validate field constraints and ensure immutability."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string.")
        if self.address is None:
            object.__setattr__(self, "address", "")
        if self.country is None:
            object.__setattr__(self, "country", "")
        if self.nationality is None:
            object.__setattr__(self, "nationality", "")

    def to_dict(self) -> dict[str, str]:
        """Serialize entity to a standard dictionary."""
        return {
            "name": self.name,
            "address": self.address,
            "country": self.country,
            "nationality": self.nationality,
        }


@dataclass(frozen=True)
class InPassPatentRecord:
    """Immutable data model representing a verified Indian InPASS patent record."""

    application_number: str
    publication_number: Optional[str] = None
    publication_date: Optional[str] = None
    filing_date: Optional[str] = None
    title: str = ""
    ipc: Optional[str] = None
    abstract: Optional[str] = None
    specification: Optional[str] = None
    claims: Optional[str] = None
    applicants: Sequence[PersonOrOrganization] = field(default_factory=tuple)
    inventors: Sequence[PersonOrOrganization] = field(default_factory=tuple)
    source: str = "INPASS"
    source_url: str = ""
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and normalize record fields upon initialization."""
        if not isinstance(self.application_number, str) or not self.application_number.strip():
            raise ValueError("application_number must be a non-empty string.")

        # Process and normalize applicants into immutable tuple
        raw_apps = self.applicants if self.applicants is not None else ()
        if not isinstance(raw_apps, (list, tuple)):
            raise TypeError(
                f"applicants must be a list or tuple of PersonOrOrganization, got {type(raw_apps).__name__}"
            )
        clean_apps = []
        for app in raw_apps:
            if isinstance(app, PersonOrOrganization):
                clean_apps.append(app)
            elif isinstance(app, dict):
                clean_apps.append(PersonOrOrganization(**app))
            else:
                raise TypeError(f"Applicant item must be PersonOrOrganization or dict, got {type(app).__name__}")
        object.__setattr__(self, "applicants", tuple(clean_apps))

        # Process and normalize inventors into immutable tuple
        raw_invs = self.inventors if self.inventors is not None else ()
        if not isinstance(raw_invs, (list, tuple)):
            raise TypeError(
                f"inventors must be a list or tuple of PersonOrOrganization, got {type(raw_invs).__name__}"
            )
        clean_invs = []
        for inv in raw_invs:
            if isinstance(inv, PersonOrOrganization):
                clean_invs.append(inv)
            elif isinstance(inv, dict):
                clean_invs.append(PersonOrOrganization(**inv))
            else:
                raise TypeError(f"Inventor item must be PersonOrOrganization or dict, got {type(inv).__name__}")
        object.__setattr__(self, "inventors", tuple(clean_invs))

        # Default source to INPASS if unset
        if not self.source:
            object.__setattr__(self, "source", "INPASS")

        # Deterministic fallback URL if unset
        if not self.source_url:
            clean_app_num = self.application_number.strip()
            object.__setattr__(
                self,
                "source_url",
                f"https://iprsearch.ipindia.gov.in/publicsearch?app={clean_app_num}",
            )

        if not isinstance(self.raw_data, dict):
            raise TypeError("raw_data must be a dictionary.")

    @property
    def patent_number(self) -> str:
        """Alias publication or application identifier for cross-system compatibility."""
        return self.publication_number or self.application_number

    @property
    def assignee(self) -> Optional[str]:
        """Convenience property returning primary applicant name."""
        return self.applicants[0].name if self.applicants else None

    def to_dict(self) -> dict[str, Any]:
        """Serialize InPassPatentRecord to a standard dictionary."""
        return {
            "application_number": self.application_number,
            "publication_number": self.publication_number,
            "publication_date": self.publication_date,
            "filing_date": self.filing_date,
            "title": self.title,
            "ipc": self.ipc,
            "abstract": self.abstract,
            "specification": self.specification,
            "claims": self.claims,
            "applicants": [app.to_dict() for app in self.applicants],
            "inventors": [inv.to_dict() for inv in self.inventors],
            "source": self.source,
            "source_url": self.source_url,
            "raw_data": self.raw_data,
        }


# Alias for regional naming preference
IndianPatentRecord = InPassPatentRecord


