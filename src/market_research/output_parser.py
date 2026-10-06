"""Defensive parser for AI-generated market research JSON outputs."""

import json
from typing import Final, Optional

from src.market_research.contract import (
    ALLOWED_RELEVANCE,
    REQUIRED_MARKET_RESEARCH_FIELDS,
    validate_market_research_record,
)
from src.market_research.models import MarketResearchRecord

REQUIRED_AI_FINDING_FIELDS: Final[frozenset[str]] = REQUIRED_MARKET_RESEARCH_FIELDS


class MarketResearchOutputParseError(ValueError):
    """Raised when an AI market research response cannot be safely parsed or validated."""
    pass


class OpportunityIdMismatchError(MarketResearchOutputParseError):
    """Raised when the opportunity ID in the AI output does not match the expected opportunity."""
    pass


def parse_market_research_output(
    raw_output: str,
    expected_opportunity_id: Optional[str] = None,
) -> list[MarketResearchRecord]:
    """Parse and validate raw AI market research output text into a list of MarketResearchRecords.

    Strictly validates JSON structure, requires one or more finding objects, validates
    exact required fields per finding, and creates immutable MarketResearchRecord instances.

    Args:
        raw_output: Raw string response returned by the AI research engine.
        expected_opportunity_id: Optional expected opportunity ID for foreign key validation.

    Returns:
        list[MarketResearchRecord]: List of validated immutable market research records.

    Raises:
        TypeError: If raw_output is not a string.
        MarketResearchOutputParseError: If output is empty, malformed JSON, missing fields,
                                        contains extra fields, empty values, invalid relevance,
                                        or fails validation.
        OpportunityIdMismatchError: If opportunity_id in finding doesn't match expected_opportunity_id.
    """
    if not isinstance(raw_output, str):
        raise TypeError(f"raw_output must be a str, got {type(raw_output).__name__}.")

    clean_text = raw_output.strip()
    if not clean_text:
        raise MarketResearchOutputParseError(
            "JSON parsing failure: AI market research output is empty or whitespace."
        )

    # 1. Parse JSON safely without repairing malformed text
    try:
        data = json.loads(clean_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise MarketResearchOutputParseError(
            f"JSON parsing failure: malformed JSON in AI response: {err}"
        ) from err

    # 2. Extract list of findings
    if isinstance(data, list):
        findings_list = data
    elif isinstance(data, dict):
        if "findings" in data and isinstance(data["findings"], list):
            findings_list = data["findings"]
        elif set(data.keys()) == REQUIRED_AI_FINDING_FIELDS:
            findings_list = [data]
        else:
            raise MarketResearchOutputParseError(
                "JSON parsing failure: expected JSON array of findings or object with 'findings' key."
            )
    else:
        raise MarketResearchOutputParseError(
            f"JSON parsing failure: expected JSON list or findings object, got {type(data).__name__}."
        )

    # 3. Ensure at least one finding is present
    if not findings_list:
        raise MarketResearchOutputParseError(
            "Market research output must contain at least one finding."
        )

    results: list[MarketResearchRecord] = []
    clean_expected_id = expected_opportunity_id.strip() if expected_opportunity_id else None

    # 4. Validate each finding item strictly
    for idx, item in enumerate(findings_list):
        if not isinstance(item, dict):
            raise MarketResearchOutputParseError(
                f"Finding at index {idx} must be a JSON object, got {type(item).__name__}."
            )

        item_keys = set(item.keys())
        missing = REQUIRED_AI_FINDING_FIELDS - item_keys
        if missing:
            raise MarketResearchOutputParseError(
                f"Finding at index {idx} missing required field(s): {sorted(list(missing))}."
            )

        extra = item_keys - REQUIRED_AI_FINDING_FIELDS
        if extra:
            raise MarketResearchOutputParseError(
                f"Finding at index {idx} contains unsupported extra field(s): {sorted(list(extra))}."
            )

        # Validate non-empty string for each required field
        for field_name in REQUIRED_AI_FINDING_FIELDS:
            val = item[field_name]
            if not isinstance(val, str) or isinstance(val, bool):
                raise MarketResearchOutputParseError(
                    f"Finding at index {idx}: field '{field_name}' must be a string, got {type(val).__name__}."
                )
            if not val.strip():
                raise MarketResearchOutputParseError(
                    f"Finding at index {idx}: field '{field_name}' must not be empty or whitespace."
                )

        # Validate relevance
        raw_rel = item["relevance"]
        clean_rel = raw_rel.strip().upper()
        if clean_rel not in ALLOWED_RELEVANCE:
            raise MarketResearchOutputParseError(
                f"Finding at index {idx}: invalid relevance '{raw_rel}'. "
                f"Allowed values: {sorted(list(ALLOWED_RELEVANCE))}."
            )

        # Validate opportunity_id match
        opp_id = item["opportunity_id"].strip()
        if clean_expected_id is not None and opp_id != clean_expected_id:
            raise OpportunityIdMismatchError(
                f"Finding at index {idx}: opportunity_id '{opp_id}' does not match expected '{clean_expected_id}'."
            )

        # 5. Construct immutable MarketResearchRecord
        try:
            record = MarketResearchRecord(
                opportunity_id=opp_id,
                source_type=item["source_type"].strip(),
                source_name=item["source_name"].strip(),
                source_url=item["source_url"].strip(),
                company_or_product=item["company_or_product"].strip(),
                finding=item["finding"].strip(),
                evidence_summary=item["evidence_summary"].strip(),
                relevance=clean_rel,
                id=None,
                raw_data={"ai_raw_output": item},
            )
            validate_market_research_record(record)
        except Exception as err:
            raise MarketResearchOutputParseError(
                f"Finding at index {idx} failed model/contract validation: {err}"
            ) from err

        results.append(record)

    return results
