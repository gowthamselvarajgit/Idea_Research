"""Strict contract and validation rules for search discovery results.

Enforces schema structure, non-empty text fields, and valid HTTP/HTTPS URLs
for search result payloads and SearchResult objects.
"""

from typing import Any, Final
import urllib.parse

from src.market_research.search_models import (
    REQUIRED_SEARCH_RESULT_TEXT_FIELDS,
    SearchResult,
)


class SearchResultContractValidationError(ValueError, TypeError):
    """Raised when a search result payload or record violates contract rules."""
    pass


REQUIRED_SEARCH_RESULT_FIELDS: Final[frozenset[str]] = frozenset({
    "url",
    "title",
    "snippet",
    "domain",
})

OPTIONAL_SEARCH_RESULT_FIELDS: Final[frozenset[str]] = frozenset({
    "id",
    "raw_data",
})

ALL_SEARCH_RESULT_FIELDS: Final[frozenset[str]] = (
    REQUIRED_SEARCH_RESULT_FIELDS | OPTIONAL_SEARCH_RESULT_FIELDS
)


def validate_search_result_payload(data: Any) -> None:
    """Validate a raw search result dictionary against contract constraints.

    Args:
        data: Dictionary payload representing a search discovery item.

    Raises:
        SearchResultContractValidationError: If payload violates any contract constraint.
    """
    if not isinstance(data, dict):
        raise SearchResultContractValidationError(
            f"Expected a dictionary for search result payload, got {type(data).__name__}."
        )

    data_keys = set(data.keys())

    # 1. Enforce required fields
    missing = REQUIRED_SEARCH_RESULT_FIELDS - data_keys
    if missing:
        raise SearchResultContractValidationError(
            f"Search result payload missing required field(s): {sorted(list(missing))}."
        )

    # 2. Reject unsupported extra fields
    extra = data_keys - ALL_SEARCH_RESULT_FIELDS
    if extra:
        raise SearchResultContractValidationError(
            f"Search result payload contains unexpected extra field(s): {sorted(list(extra))}."
        )

    # 3. Validate required text fields
    for field_name in REQUIRED_SEARCH_RESULT_TEXT_FIELDS:
        val = data[field_name]
        if not isinstance(val, str) or isinstance(val, bool):
            raise SearchResultContractValidationError(
                f"Field '{field_name}' must be a string, got {type(val).__name__}."
            )
        if not val.strip():
            raise SearchResultContractValidationError(
                f"Field '{field_name}' must not be empty or whitespace."
            )

    # 4. Validate URL scheme
    url = data["url"].strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise SearchResultContractValidationError(
            f"URL must be a valid HTTP or HTTPS address, got '{url}'."
        )

    # 5. Validate optional id if provided
    if "id" in data and data["id"] is not None:
        item_id = data["id"]
        if not isinstance(item_id, str) or isinstance(item_id, bool) or not item_id.strip():
            raise SearchResultContractValidationError(
                "Optional field 'id' must be a non-empty string if provided."
            )

    # 6. Validate optional raw_data if provided
    if "raw_data" in data and data["raw_data"] is not None:
        if not isinstance(data["raw_data"], dict):
            raise SearchResultContractValidationError(
                f"Optional field 'raw_data' must be a dictionary, got {type(data['raw_data']).__name__}."
            )


def validate_search_result_record(record: SearchResult) -> None:
    """Validate that a SearchResult instance strictly adheres to contract rules.

    Args:
        record: SearchResult instance.

    Raises:
        SearchResultContractValidationError: If record violates contract.
        TypeError: If input is not a SearchResult.
    """
    if not isinstance(record, SearchResult):
        raise TypeError(f"Expected SearchResult instance, got {type(record).__name__}.")

    for field_name in REQUIRED_SEARCH_RESULT_TEXT_FIELDS:
        val = getattr(record, field_name)
        if not isinstance(val, str) or not val.strip():
            raise SearchResultContractValidationError(
                f"SearchResult requires a non-empty string for '{field_name}'."
            )

    parsed = urllib.parse.urlparse(record.url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise SearchResultContractValidationError(
            f"SearchResult URL must be a valid HTTP or HTTPS address, got '{record.url}'."
        )

    if not isinstance(record.raw_data, dict):
        raise SearchResultContractValidationError("raw_data must be a dictionary.")


def validate_search_result_contract(target: Any) -> None:
    """Unified validation entry point for either search result payload or SearchResult instance."""
    if isinstance(target, SearchResult):
        validate_search_result_record(target)
    elif isinstance(target, dict):
        validate_search_result_payload(target)
    else:
        raise SearchResultContractValidationError(
            f"Expected SearchResult or dict, got {type(target).__name__}."
        )
