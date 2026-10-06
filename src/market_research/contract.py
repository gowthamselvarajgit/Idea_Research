"""Strict contract and validation rules for market research findings.

Defines schemas, controlled relevance levels, required fields, and contract
enforcement functions for structured market research findings.
"""

from typing import Any, Final

from src.market_research.models import (
    ALLOWED_RELEVANCE,
    REQUIRED_MARKET_RESEARCH_TEXT_FIELDS,
    MarketResearchRecord,
)


class MarketResearchContractValidationError(ValueError, TypeError):
    """Raised when market research data violates schema, type, or semantic contract rules."""
    pass


REQUIRED_MARKET_RESEARCH_FIELDS: Final[frozenset[str]] = frozenset({
    "opportunity_id",
    "source_type",
    "source_name",
    "source_url",
    "company_or_product",
    "finding",
    "evidence_summary",
    "relevance",
})

OPTIONAL_MARKET_RESEARCH_FIELDS: Final[frozenset[str]] = frozenset({
    "id",
    "raw_data",
})

ALL_MARKET_RESEARCH_FIELDS: Final[frozenset[str]] = (
    REQUIRED_MARKET_RESEARCH_FIELDS | OPTIONAL_MARKET_RESEARCH_FIELDS
)

MARKET_RESEARCH_CONTRACT_PRINCIPLES: Final[str] = """
Market Research Core Principles:

1. Grounded Market Evidence:
   - Each research record must tie directly to an existing startup opportunity (opportunity_id).
   - Findings must cite concrete external sources with valid source_url, source_type, and source_name.
   - Specific existing companies, products, or direct competitors must be identified (company_or_product).

2. Rigorous Findings & Evidence:
   - finding: Precise statement of the discovery, market saturation, gap, or customer pain point.
   - evidence_summary: Concrete factual summary backing the finding.
   - Empty or whitespace-only text values are strictly prohibited.

3. Controlled Relevance:
   - relevance must be strictly one of: HIGH, MEDIUM, LOW.
   - HIGH: Directly addresses core product premise, primary competitor, or decisive customer objection.
   - MEDIUM: Relevant adjacent industry player, secondary competitor, or general market trend.
   - LOW: Tangentially related or contextual market background.

4. Immutability & Scope:
   - Records are immutable once created.
   - External data scrapers and raw payloads must be stored cleanly in raw_data.
"""


def validate_market_research_payload(data: Any) -> None:
    """Validate a raw market research dictionary payload against strict contract constraints.

    Args:
        data: Parsed dictionary payload of market research findings.

    Raises:
        MarketResearchContractValidationError: If payload violates any contract constraint.
    """
    if not isinstance(data, dict):
        raise MarketResearchContractValidationError(
            f"Expected a dictionary for market research payload, got {type(data).__name__}."
        )

    # 1. Enforce required fields (no missing)
    data_keys = set(data.keys())
    missing = REQUIRED_MARKET_RESEARCH_FIELDS - data_keys
    if missing:
        raise MarketResearchContractValidationError(
            f"Market research payload missing required field(s): {sorted(list(missing))}."
        )

    # 2. Reject unexpected extra fields
    extra = data_keys - ALL_MARKET_RESEARCH_FIELDS
    if extra:
        raise MarketResearchContractValidationError(
            f"Market research payload contains unexpected extra field(s): {sorted(list(extra))}."
        )

    # 3. Validate required text fields
    for field_name in REQUIRED_MARKET_RESEARCH_TEXT_FIELDS:
        val = data[field_name]
        if not isinstance(val, str) or isinstance(val, bool):
            raise MarketResearchContractValidationError(
                f"Field '{field_name}' must be a string, got {type(val).__name__}."
            )
        if not val.strip():
            raise MarketResearchContractValidationError(
                f"Field '{field_name}' must not be empty or whitespace."
            )

    # 4. Validate relevance
    rel = data["relevance"]
    if not isinstance(rel, str) or isinstance(rel, bool):
        raise MarketResearchContractValidationError(
            f"Field 'relevance' must be a string, got {type(rel).__name__}."
        )
    clean_rel = rel.strip().upper()
    if clean_rel not in ALLOWED_RELEVANCE:
        raise MarketResearchContractValidationError(
            f"Invalid relevance: '{rel}'. Allowed values: {sorted(list(ALLOWED_RELEVANCE))}."
        )

    # 5. Validate optional id if provided
    if "id" in data and data["id"] is not None:
        rec_id = data["id"]
        if not isinstance(rec_id, str) or isinstance(rec_id, bool) or not rec_id.strip():
            raise MarketResearchContractValidationError(
                "Optional field 'id' must be a non-empty string if provided."
            )

    # 6. Validate optional raw_data if provided
    if "raw_data" in data and data["raw_data"] is not None:
        if not isinstance(data["raw_data"], dict):
            raise MarketResearchContractValidationError(
                f"Optional field 'raw_data' must be a dictionary, got {type(data['raw_data']).__name__}."
            )


def validate_market_research_record(record: MarketResearchRecord) -> None:
    """Validate that a MarketResearchRecord strictly adheres to the domain contract.

    Args:
        record: MarketResearchRecord instance.

    Raises:
        MarketResearchContractValidationError: If record violates contract rules.
        TypeError: If input is not a MarketResearchRecord.
    """
    if not isinstance(record, MarketResearchRecord):
        raise TypeError(
            f"Expected MarketResearchRecord instance, got {type(record).__name__}."
        )

    for field_name in REQUIRED_MARKET_RESEARCH_TEXT_FIELDS:
        val = getattr(record, field_name)
        if not isinstance(val, str) or not val.strip():
            raise MarketResearchContractValidationError(
                f"MarketResearchRecord requires a non-empty string for '{field_name}'."
            )

    if record.relevance not in ALLOWED_RELEVANCE:
        raise MarketResearchContractValidationError(
            f"Invalid relevance '{record.relevance}'. Allowed values: {sorted(list(ALLOWED_RELEVANCE))}."
        )

    if not isinstance(record.raw_data, dict):
        raise MarketResearchContractValidationError(
            "raw_data must be a dictionary."
        )


def validate_market_research_contract(target: Any) -> None:
    """Unified validation entry point for either research dictionary payload or MarketResearchRecord.

    Args:
        target: Dictionary payload or MarketResearchRecord instance.

    Raises:
        MarketResearchContractValidationError: If contract is violated.
    """
    if isinstance(target, MarketResearchRecord):
        validate_market_research_record(target)
    elif isinstance(target, dict):
        validate_market_research_payload(target)
    else:
        raise MarketResearchContractValidationError(
            f"Expected MarketResearchRecord or dict, got {type(target).__name__}."
        )
