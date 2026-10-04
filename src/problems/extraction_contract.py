"""Problem extraction contract defining the structured schema and validation rules.

Enforces extraction principles for translating patent disclosures into verified,
grounded problem records without fabricating commercial demand or unsupported claims.
"""

from typing import Final
from src.problems.models import ProblemRecord


# Controlled enumeration values
ALLOWED_CONFIDENCE: Final[frozenset[str]] = frozenset({"high", "medium", "low"})
ALLOWED_SEVERITY: Final[frozenset[str]] = frozenset({"high", "medium", "low", "unknown"})
ALLOWED_FREQUENCY: Final[frozenset[str]] = frozenset({
    "daily",
    "weekly",
    "monthly",
    "occasional",
    "rare",
    "unknown",
})


class ProblemContractValidationError(ValueError):
    """Raised when an extracted ProblemRecord violates controlled field constraints."""
    pass


# Principles and guidance for LLM extractor prompts
EXTRACTION_CONTRACT_PRINCIPLES: Final[str] = """
Problem Extraction Core Principles:

1. Patent != Problem:
   - The patent describes a technical solution or invention.
   - The extractor must identify the underlying real-world problem, failure mode,
     or unmet technical bottleneck that necessitated the invention.

2. Separate Evidence from Inference:
   - Explicit patent evidence (claims, background, comparative examples) must be
     distinguished from reasonable extrapolations.
   - Unsupported assumptions must never be presented as proven facts.

3. Core Questions Addressed:
   - Who experiences the problem? (affected_users)
   - What are they trying to accomplish?
   - What makes the task difficult or inefficient today? (bottleneck_type, problem_description)
   - What is the current workaround or compromise? (current_workaround)
   - How frequently does the problem occur? (problem_frequency: daily, weekly, monthly, occasional, rare, unknown)
   - How severe/costly/frustrating is it? (problem_severity: high, medium, low, unknown)
   - What evidence in the patent supports the problem? (evidence_summary)
   - How confident are we in this problem formulation? (evidence_confidence: high, medium, low)

4. No Fabricated Knowledge:
   - When the patent does not provide sufficient evidence to ascertain frequency or severity,
     use 'unknown'.
   - Do NOT invent market size, TAM, customer willingness-to-pay, or commercial traction.
"""


def validate_problem_record(record: ProblemRecord) -> None:
    """Validate that a ProblemRecord strictly adheres to the extraction contract.

    Verifies controlled vocabulary for evidence_confidence, problem_severity,
    and problem_frequency.

    Args:
        record: ProblemRecord instance to validate.

    Raises:
        ProblemContractValidationError: If any controlled field contains an invalid value.
        TypeError: If record is not a ProblemRecord.
    """
    if not isinstance(record, ProblemRecord):
        raise TypeError(f"Expected ProblemRecord instance, got {type(record).__name__}.")

    # Validate evidence_confidence
    norm_confidence = record.evidence_confidence.lower().strip()
    if norm_confidence not in ALLOWED_CONFIDENCE:
        raise ProblemContractValidationError(
            f"Invalid evidence_confidence: '{record.evidence_confidence}'. "
            f"Allowed values are: {sorted(list(ALLOWED_CONFIDENCE))}."
        )

    # Validate problem_severity
    norm_severity = record.problem_severity.lower().strip()
    if norm_severity not in ALLOWED_SEVERITY:
        raise ProblemContractValidationError(
            f"Invalid problem_severity: '{record.problem_severity}'. "
            f"Allowed values are: {sorted(list(ALLOWED_SEVERITY))}."
        )

    # Validate problem_frequency
    norm_frequency = record.problem_frequency.lower().strip()
    if norm_frequency not in ALLOWED_FREQUENCY:
        raise ProblemContractValidationError(
            f"Invalid problem_frequency: '{record.problem_frequency}'. "
            f"Allowed values are: {sorted(list(ALLOWED_FREQUENCY))}."
        )
