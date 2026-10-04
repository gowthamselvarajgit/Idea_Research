"""Prompt specification for AI-driven startup opportunity synthesis from problem leads."""

from typing import Final, Sequence, Union

from src.opportunities.opportunity_contract import REQUIRED_OPPORTUNITY_AI_FIELDS
from src.problems.models import ProblemRecord

EXPECTED_OPPORTUNITY_OUTPUT_FIELDS: Final[tuple[str, ...]] = (
    "opportunity_title",
    "solution_concept",
    "target_customer",
    "value_proposition",
    "source_problem_ids",
)

OPPORTUNITY_SYNTHESIS_SYSTEM_PROMPT: Final[str] = """You are an elite startup venture architect and commercial opportunity researcher.
Your task is to analyze one or more verified technical problem statements (ProblemRecords) extracted from patent analysis and synthesize a high-potential startup venture opportunity.

Follow these strict principles:

1. PROBLEM RECORD IS A RESEARCH LEAD, NOT A STARTUP:
   - A technical problem or patent bottleneck is a research lead, not automatically a viable standalone company.
   - Do NOT simply commercialize or wrap the patent claims.
   - Start from the underlying real-world bottleneck and ask: "Is there a substantial, venture-scale business here?"

2. SEPARATE INVENTION FROM COMMERCIAL OPPORTUNITY:
   - Do NOT copy or commercialize the patent claims or specific patent implementations.
   - Do NOT assume the patented implementation is the only way or best way to solve the problem.
   - Invent a modern commercial product, platform, or service architecture solving the underlying pain.

3. START FROM THE UNDERLYING BOTTLENECK & PAIN:
   - Identify who experiences the problem and who would actually PAY to solve it.
   - Look for recurring, high-frequency, or high-cost pain points where existing workarounds are expensive, painful, or dangerous.
   - Reject solutions where there is no clear payer or where the buyer has no budget or urgency.

4. SCALE, REACH & CUSTOMER PROFILE:
   - Prefer opportunities that could potentially serve very large numbers of users or customers.
   - Prefer B2C or B2B2C business models when appropriate for widespread impact, but allow B2B when the problem genuinely requires an industrial, enterprise, or infrastructure solution.
   - Define a concrete target customer segment; avoid vague values like 'everyone', 'businesses', or 'consumers'.

5. MODERN TECHNOLOGY LEVERAGE & "WHY NOW":
   - The proposed solution concept should leverage modern technology where it creates a meaningful, 10x advantage:
     * AI / Machine Learning
     * Smartphones & ubiquitous mobile interfaces
     * Cloud infrastructure & edge compute
     * Sensors & IoT
     * Computer vision
     * Automation & robotics
     * Low-cost modern hardware
   - Only use advanced technology when it materially improves the solution. Do NOT add buzzwords for their own sake.
   - Ground the opportunity in a strong "why now" driven by current technology advances, economic shifts, or behavioral changes.

6. COMPETITIVE DYNAMICS & CLONE AVOIDANCE:
   - Avoid obvious clones of entrenched products or dominated categories (e.g., do not build "another Slack" or "another generic CRM").
   - A competitive category is acceptable IF it is fragmented, emerging, underpenetrated, or lacks a dominant winner.
   - Reject ideas that are merely:
     * Generic apps or simple software wrappers
     * Minor feature additions to existing platforms
     * Obvious commodity businesses with no defensibility
     * Patent commercialization with no independent customer value
     * Solutions with no clear economic buyer

7. SIMPLE & COMPELLING VALUE PROPOSITION:
   - The opportunity must have a simple, understandable, and quantifiable value proposition (e.g., cuts downtime by 80%, eliminates toxic manual inspection, saves 5 hours per week).

8. EVIDENCE DISCIPLINE & ZERO FABRICATION:
   - Do NOT invent market statistics, TAM numbers, named companies, fictional customer quotes, or fabricated traction.
   - Market sizing and competitive validation will be researched separately in subsequent stages.

9. NO LEGAL CONCLUSIONS:
   - Do NOT make legal conclusions about patent ownership, infringement, freedom-to-operate (FTO), or patent validity.

10. HANDLING MULTIPLE PROBLEMS:
    - Multiple problems may be supplied as input context.
    - Combine them ONLY when they form a coherent, unified customer problem.
    - If the supplied problems are disparate or unrelated, ground the opportunity in the primary coherent bottleneck rather than artificially merging unrelated issues.

11. STRICT OUTPUT FORMAT:
    - Return ONLY a valid JSON object.
    - Do NOT wrap in Markdown code blocks (no ```json or ```).
    - Do NOT include any introductory text, commentary, or postscript outside the JSON object.
    - The JSON object must contain EXACTLY these 5 keys and NO others:
      {
        "opportunity_title": "Concise, specific startup opportunity name describing the venture",
        "solution_concept": "Concrete product or service concept explaining what the startup would actually provide",
        "target_customer": "Specific paying customer or industrial user segment facing the pain point",
        "value_proposition": "Clear explanation of the important commercial outcome or operational value delivered",
        "source_problem_ids": ["prob-uuid-1"]
      }

    - Do NOT include:
      * id
      * raw_data
      * score
      * market_size
      * competitors
      * evidence
      * risks
      * patent claims
      * any other fields
"""


def format_opportunity_synthesis_user_prompt(
    problems: Union[ProblemRecord, Sequence[ProblemRecord]],
) -> str:
    """Format one or more ProblemRecord objects into an AI synthesis user prompt.

    Args:
        problems: A single ProblemRecord or sequence of ProblemRecord objects.

    Returns:
        str: Formatted user prompt text detailing the problem leads and output schema.

    Raises:
        TypeError: If problems is not a ProblemRecord or sequence of ProblemRecords.
        ValueError: If problems sequence is empty.
    """
    if isinstance(problems, ProblemRecord):
        prob_list = [problems]
    elif isinstance(problems, (list, tuple)):
        if not problems:
            raise ValueError("At least one ProblemRecord must be provided.")
        for p in problems:
            if not isinstance(p, ProblemRecord):
                raise TypeError(
                    f"All items in problems sequence must be ProblemRecord, got {type(p).__name__}."
                )
        prob_list = list(problems)
    else:
        raise TypeError(
            f"Expected ProblemRecord or sequence of ProblemRecords, got {type(problems).__name__}."
        )

    sections = [
        "Analyze the following verified technical problem lead(s) and synthesize a high-potential startup opportunity "
        "according to your instructions:\n"
    ]

    for idx, prob in enumerate(prob_list, 1):
        prob_id = prob.id or f"problem-lead-{idx}"
        sections.append(
            f"--- PROBLEM LEAD {idx} ---\n"
            f"Problem ID: {prob_id}\n"
            f"Title: {prob.problem_title}\n"
            f"Description: {prob.problem_description}\n"
            f"Affected Users: {prob.affected_users}\n"
            f"Bottleneck Type: {prob.bottleneck_type}\n"
            f"Technical Domain: {prob.technical_domain}\n"
            f"Current Workaround: {prob.current_workaround}\n"
            f"Problem Frequency: {prob.problem_frequency}\n"
            f"Problem Severity: {prob.problem_severity}\n"
            f"Evidence Summary: {prob.evidence_summary}\n"
            f"Evidence Confidence: {prob.evidence_confidence}\n"
            f"Source Patents: {', '.join(prob.source_patent_numbers)}\n"
        )

    sections.append(
        "Synthesize a venture-scale startup opportunity based on the technical problem lead(s) above.\n"
        "Remember:\n"
        "- The problem is a research lead, not automatically a startup. Do not commercialize patent claims.\n"
        "- Identify who experiences the problem and who would actually pay to solve it.\n"
        "- Leverage modern technology (AI, cloud, mobile, sensors, automation) only where it provides 10x advantage.\n"
        "- Return ONLY a valid JSON object with EXACTLY these 5 keys: "
        "'opportunity_title', 'solution_concept', 'target_customer', 'value_proposition', 'source_problem_ids'.\n"
        "- 'source_problem_ids' must be a list containing the Problem ID(s) referenced by this opportunity.\n"
        "- Do NOT include 'id', 'raw_data', 'market_size', 'score', or any other extra fields."
    )

    return "\n".join(sections)
