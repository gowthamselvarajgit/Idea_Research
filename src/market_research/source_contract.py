"""Strict contract and validation rules for external web research sources.

Defines required fields, controlled source types, and contract enforcement
functions for raw web evidence payloads and WebResearchSource objects.
"""

from typing import Any, Final

from src.market_research.source_models import (
    ALLOWED_SOURCE_TYPES,
    REQUIRED_SOURCE_TEXT_FIELDS,
    WebResearchSource,
)


class WebResearchSourceContractValidationError(ValueError, TypeError):
    """Raised when a web research source payload or object violates contract rules."""
    pass


REQUIRED_SOURCE_FIELDS: Final[frozenset[str]] = frozenset({
    "url",
    "title",
    "source_type",
    "publisher_or_domain",
    "retrieved_content",
    "retrieved_at",
})

OPTIONAL_SOURCE_FIELDS: Final[frozenset[str]] = frozenset({
    "id",
    "raw_data",
})

ALL_SOURCE_FIELDS: Final[frozenset[str]] = REQUIRED_SOURCE_FIELDS | OPTIONAL_SOURCE_FIELDS


def validate_web_research_source_payload(data: Any) -> None:
    """Validate a raw web research source dictionary against contract rules.

    Args:
        data: Dictionary payload representing an external web research source.

    Raises:
        WebResearchSourceContractValidationError: If payload violates any contract constraint.
    """
    if not isinstance(data, dict):
        raise WebResearchSourceContractValidationError(
            f"Expected a dictionary for web research source payload, got {type(data).__name__}."
        )

    data_keys = set(data.keys())

    # 1. Check for missing required fields
    missing = REQUIRED_SOURCE_FIELDS - data_keys
    if missing:
        raise WebResearchSourceContractValidationError(
            f"Web research source payload missing required field(s): {sorted(list(missing))}."
        )

    # 2. Check for unexpected extra fields
    extra = data_keys - ALL_SOURCE_FIELDS
    if extra:
        raise WebResearchSourceContractValidationError(
            f"Web research source payload contains unexpected extra field(s): {sorted(list(extra))}."
        )

    # 3. Validate required text fields
    for field_name in REQUIRED_SOURCE_TEXT_FIELDS:
        val = data[field_name]
        if not isinstance(val, str) or isinstance(val, bool):
            raise WebResearchSourceContractValidationError(
                f"Field '{field_name}' must be a string, got {type(val).__name__}."
            )
        if not val.strip():
            raise WebResearchSourceContractValidationError(
                f"Field '{field_name}' must not be empty or whitespace."
            )

    # 4. Validate source_type
    st = data["source_type"]
    if not isinstance(st, str) or isinstance(st, bool):
        raise WebResearchSourceContractValidationError(
            f"Field 'source_type' must be a string, got {type(st).__name__}."
        )
    clean_st = st.strip().lower()
    if clean_st not in ALLOWED_SOURCE_TYPES:
        raise WebResearchSourceContractValidationError(
            f"Invalid source_type: '{st}'. Allowed values: {sorted(list(ALLOWED_SOURCE_TYPES))}."
        )

    # 5. Validate optional id if provided
    if "id" in data and data["id"] is not None:
        src_id = data["id"]
        if not isinstance(src_id, str) or isinstance(src_id, bool) or not src_id.strip():
            raise WebResearchSourceContractValidationError(
                "Optional field 'id' must be a non-empty string if provided."
            )

    # 6. Validate optional raw_data if provided
    if "raw_data" in data and data["raw_data"] is not None:
        if not isinstance(data["raw_data"], dict):
            raise WebResearchSourceContractValidationError(
                f"Optional field 'raw_data' must be a dictionary, got {type(data['raw_data']).__name__}."
            )


def validate_web_research_source_record(source: WebResearchSource) -> None:
    """Validate that a WebResearchSource instance adheres to contract constraints.

    Args:
        source: WebResearchSource instance to validate.

    Raises:
        WebResearchSourceContractValidationError: If source violates contract rules.
        TypeError: If input is not a WebResearchSource.
    """
    if not isinstance(source, WebResearchSource):
        raise TypeError(
            f"Expected WebResearchSource instance, got {type(source).__name__}."
        )

    for field_name in REQUIRED_SOURCE_TEXT_FIELDS:
        val = getattr(source, field_name)
        if not isinstance(val, str) or not val.strip():
            raise WebResearchSourceContractValidationError(
                f"WebResearchSource requires a non-empty string for '{field_name}'."
            )

    if source.source_type not in ALLOWED_SOURCE_TYPES:
        raise WebResearchSourceContractValidationError(
            f"Invalid source_type: '{source.source_type}'. Allowed values: {sorted(list(ALLOWED_SOURCE_TYPES))}."
        )

    if not isinstance(source.raw_data, dict):
        raise WebResearchSourceContractValidationError("raw_data must be a dictionary.")


def validate_web_research_source_contract(target: Any) -> None:
    """Unified validation entry point for either source dictionary payload or WebResearchSource."""
    if isinstance(target, WebResearchSource):
        validate_web_research_source_record(target)
    elif isinstance(target, dict):
        validate_web_research_source_payload(target)
    else:
        raise WebResearchSourceContractValidationError(
            f"Expected WebResearchSource or dict, got {type(target).__name__}."
        )
