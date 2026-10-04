"""Opportunity synthesis contract defining the structured schema and validation rules.

Enforces synthesis principles for translating verified problem statements into
grounded, venture-scale startup opportunity records without unsupported market claims.
"""

from typing import Any, Final
from src.opportunities.models import OpportunityRecord


class OpportunityContractValidationError(ValueError, TypeError):
    """Raised when opportunity synthesis data violates schema, type, or semantic contract rules."""
    pass


# Canonical required fields for AI synthesis outputs (persistence fields 'id' and 'raw_data' excluded)
REQUIRED_OPPORTUNITY_AI_FIELDS: Final[frozenset[str]] = frozenset({
    "opportunity_title",
    "solution_concept",
    "target_customer",
    "value_proposition",
    "source_problem_ids",
})

# Reusable aliases for subsequent parser and service components
REQUIRED_AI_FIELDS: Final[frozenset[str]] = REQUIRED_OPPORTUNITY_AI_FIELDS
REQUIRED_OPPORTUNITY_FIELDS: Final[frozenset[str]] = REQUIRED_OPPORTUNITY_AI_FIELDS

# Semantic constraints on vague / non-actionable customer profiles
BANNED_GENERIC_CUSTOMERS: Final[frozenset[str]] = frozenset({
    "everyone",
    "businesses",
    "consumers",
    "users",
    "general public",
    "anyone",
    "all businesses",
    "people",
})

OPPORTUNITY_CONTRACT_PRINCIPLES: Final[str] = """
Opportunity Synthesis Core Principles:

1. Required Output Fields:
   - opportunity_title: Concise, specific startup opportunity name describing the commercial venture,
     not merely repeating the source patent or problem title.
   - solution_concept: Concrete product or service concept explaining what the startup would actually provide.
   - target_customer: Specific paying customer or industrial user segment facing the pain point.
     Vague catch-alls like 'everyone', 'businesses', or 'consumers' are strictly prohibited.
   - value_proposition: Clear explanation of the important commercial outcome or operational value delivered.
   - source_problem_ids: List or tuple of verified ProblemRecord IDs that directly generated this opportunity.

2. Strict Scope & Boundaries:
   - Persistence fields ('id' and 'raw_data') must NOT be produced by the AI synthesis stage.
   - Ground solutions strictly in verified technical problems and engineering constraints.
   - No patent claims or legal infringement conclusions are required or permitted at this stage.
   - Do NOT fabricate traction, imaginary funding rounds, or fictitious LOIs.
"""


def validate_opportunity_ai_output(data: Any) -> None:
    """Validate that a raw AI synthesis output dictionary adheres strictly to the opportunity contract.

    Enforces:
        - Input must be a dictionary.
        - Exact required fields present (no missing, no unexpected extra fields).
        - Correct basic types (str for text fields, list/tuple of str for source_problem_ids).
        - Non-empty strings after stripping whitespace.
        - Non-empty source_problem_ids sequence with non-empty string IDs.
        - Semantic minimum content rules and rejection of generic customer catch-alls.

    Args:
        data: Parsed dictionary from AI synthesis response.

    Raises:
        OpportunityContractValidationError: If any contract rule or type constraint is violated.
    """
    if not isinstance(data, dict):
        raise OpportunityContractValidationError(
            f"Expected a dictionary for opportunity AI output, got {type(data).__name__}."
        )

    # 1. Enforce exact required fields (no missing, no extra)
    data_keys = set(data.keys())
    missing = REQUIRED_OPPORTUNITY_AI_FIELDS - data_keys
    if missing:
        raise OpportunityContractValidationError(
            f"Opportunity AI output is missing required field(s): {sorted(list(missing))}."
        )

    extra = data_keys - REQUIRED_OPPORTUNITY_AI_FIELDS
    if extra:
        raise OpportunityContractValidationError(
            f"Opportunity AI output contains unexpected extra field(s): {sorted(list(extra))}."
        )

    # 2. Validate required text fields
    text_min_lengths = {
        "opportunity_title": 5,
        "solution_concept": 10,
        "target_customer": 3,
        "value_proposition": 10,
    }

    for field_name, min_len in text_min_lengths.items():
        val = data[field_name]
        # Basic type check: must be string, not bool or int
        if not isinstance(val, str) or isinstance(val, bool):
            raise OpportunityContractValidationError(
                f"Field '{field_name}' must be a string, got {type(val).__name__}."
            )

        clean_val = val.strip()
        if not clean_val:
            raise OpportunityContractValidationError(
                f"Field '{field_name}' must not be empty or whitespace."
            )

        if len(clean_val) < min_len:
            raise OpportunityContractValidationError(
                f"Field '{field_name}' fails minimum length requirement ({len(clean_val)} < {min_len})."
            )

    # Specific semantic check: target_customer must not be vague
    target_cust = data["target_customer"].strip().lower()
    if target_cust in BANNED_GENERIC_CUSTOMERS:
        raise OpportunityContractValidationError(
            f"target_customer '{data['target_customer']}' is too generic. "
            "Specify a concrete paying customer/user segment; avoid vague values like 'everyone', 'businesses', or 'consumers'."
        )

    # 3. Validate source_problem_ids
    prob_ids = data["source_problem_ids"]
    if not isinstance(prob_ids, (list, tuple)) or isinstance(prob_ids, (str, bytes)):
        raise OpportunityContractValidationError(
            f"Field 'source_problem_ids' must be a list or tuple of strings, got {type(prob_ids).__name__}."
        )

    if len(prob_ids) == 0:
        raise OpportunityContractValidationError(
            "Field 'source_problem_ids' must contain at least one problem ID."
        )

    for i, pid in enumerate(prob_ids):
        if not isinstance(pid, str) or isinstance(pid, bool):
            raise OpportunityContractValidationError(
                f"source_problem_ids[{i}] must be a string, got {type(pid).__name__}."
            )
        if not pid.strip():
            raise OpportunityContractValidationError(
                f"source_problem_ids[{i}] must not be empty or whitespace."
            )


def validate_opportunity_record(record: OpportunityRecord) -> None:
    """Validate that an OpportunityRecord strictly adheres to domain and synthesis constraints.

    Args:
        record: OpportunityRecord instance to validate.

    Raises:
        OpportunityContractValidationError: If validation fails.
        TypeError: If record is not an OpportunityRecord.
    """
    if not isinstance(record, OpportunityRecord):
        raise TypeError(f"Expected OpportunityRecord instance, got {type(record).__name__}.")

    # Title length / clarity check
    if len(record.opportunity_title.strip()) < 5:
        raise OpportunityContractValidationError(
            "opportunity_title must be at least 5 characters long."
        )

    # Solution concept check
    if len(record.solution_concept.strip()) < 10:
        raise OpportunityContractValidationError(
            "solution_concept must provide substantial technical detail (at least 10 characters)."
        )

    # Target customer check
    clean_customer = record.target_customer.strip()
    if len(clean_customer) < 3:
        raise OpportunityContractValidationError(
            "target_customer must specify a clear customer profile (at least 3 characters)."
        )
    if clean_customer.lower() in BANNED_GENERIC_CUSTOMERS:
        raise OpportunityContractValidationError(
            f"target_customer '{record.target_customer}' is too generic; specify a concrete customer segment."
        )

    # Value proposition check
    if len(record.value_proposition.strip()) < 10:
        raise OpportunityContractValidationError(
            "value_proposition must clearly articulate customer benefit (at least 10 characters)."
        )

    # Source problem IDs check
    if not record.source_problem_ids:
        raise OpportunityContractValidationError(
            "OpportunityRecord must link to at least one valid source_problem_id."
        )


def validate_opportunity_contract(target: Any) -> None:
    """Unified validation entry point for either AI output dictionary or OpportunityRecord.

    Args:
        target: Dictionary of AI output or OpportunityRecord instance.
    """
    if isinstance(target, OpportunityRecord):
        validate_opportunity_record(target)
    elif isinstance(target, dict):
        validate_opportunity_ai_output(target)
    else:
        raise OpportunityContractValidationError(
            f"Expected OpportunityRecord or dict, got {type(target).__name__}."
        )
