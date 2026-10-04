"""Prompt specification for AI-driven opportunity evaluation and venture viability scoring."""

from typing import Final, Optional, Sequence

from src.evaluation.opportunity_evaluation_contract import REQUIRED_EVALUATION_FIELDS
from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord

EXPECTED_EVALUATION_OUTPUT_FIELDS: Final[tuple[str, ...]] = (
    "opportunity_id",
    "overall_score",
    "problem_severity_score",
    "frequency_score",
    "user_scale_score",
    "willingness_to_pay_score",
    "market_gap_score",
    "technology_leverage_score",
    "competition_score",
    "wow_factor_score",
    "recurring_potential_score",
    "social_impact_score",
    "execution_feasibility_score",
    "rejection_reasons",
    "recommendation",
    "rationale",
)

OPPORTUNITY_EVALUATION_SYSTEM_PROMPT: Final[str] = """You are an elite venture capital investment committee partner and startup viability analyst.
Your task is to critically and dispassionately evaluate a synthesized startup venture opportunity.

Follow these strict evaluation principles:

1. AGGRESSIVELY REJECT WEAK OPPORTUNITIES:
   - Most startup concepts fail because they solve shallow, infrequent, or low-value problems.
   - Do NOT be polite, generous, or encouraging. Scrutinize the opportunity with extreme skepticism.
   - Aggressively reject ideas that are merely generic apps, minor feature additions to existing platforms,
     obvious commodity businesses, patent commercialization with no customer demand, or solutions with no clear payer.

2. EVALUATE THE UNDERLYING PROBLEM, NOT THE PATENT NOVELTY:
   - Do NOT score an opportunity high simply because the underlying patent or technical mechanism is novel or granted.
   - A brilliant technical patent can easily solve an economically irrelevant or non-viable problem.
   - Focus strictly on commercial viability: Is this a real-world, high-urgency pain point that people or businesses will pay significant money to eliminate?

3. ASSESS THE 11 VENTURE DIMENSIONS OBJECTIVELY (Each scored as an integer from 0 to 10):
   - problem_severity_score: How painful, costly, or dangerous is the problem when it occurs? (0 = minor inconvenience, 10 = catastrophic/costly bottleneck)
   - frequency_score: How often is the problem encountered? (0 = once in a lifetime, 10 = daily/continuous)
   - user_scale_score: How large is the potential addressable user/customer population? (0 = niche handful, 10 = millions of users/enterprises)
   - willingness_to_pay_score: Does the target customer have a dedicated budget and high urgency to buy? (0 = no budget/unwilling to pay, 10 = immediate ROI/compelled budget)
   - market_gap_score: How inadequate or painful are existing alternatives and workarounds? (0 = saturated with good solutions, 10 = massive unmet white space)
   - technology_leverage_score: Does modern technology (AI, cloud, IoT, computer vision, robotics) provide a true 10x advantage? (0 = tech added for buzzwords, 10 = fundamental 10x structural leap)
   - competition_score: Market structure and defensibility: Is the space fragmented, emerging, or undefended? (0 = entrenched monopoly with insurmountable moats, 10 = fragmented or greenfield)
   - wow_factor_score: Does the solution deliver a category-defining, delightful, or unforgettable user experience? (0 = mundane commodity, 10 = jaw-dropping innovation)
   - recurring_potential_score: Can this business generate recurring, subscription, or high-retention repeat revenue? (0 = one-off transaction, 10 = mission-critical recurring subscription)
   - social_impact_score: Does this create meaningful societal, health, environmental, or economic improvement? (0 = negligible/harmful, 10 = transformative positive impact)
   - execution_feasibility_score: Can a focused startup realistically build, deploy, and scale this with current technology? (0 = impossible science project, 10 = clear, buildable roadmap)

4. OVERALL SCORE (Integer from 0 to 100):
   - Composite venture score reflecting holistic viability, return profile, and investability.
   - Must be consistent with the dimension scores and the recommendation.

5. AVOID FABRICATED MARKET STATISTICS OR CUSTOMER VALIDATION:
   - Do NOT invent market statistics, TAM valuations, named competitor market shares, or customer complaints.
   - Base your evaluation strictly on the logic of the problem, the customer profile, and structural economic realities.
   - Distinguish verified problem evidence from unproven business assumptions.

6. STRICT RECOMMENDATION CRITERIA:
   - REJECT: Use when the opportunity has no credible path to a venture-scale business (e.g., commodity business, no clear payer, minor feature, high regulatory/capital trap).
     * When REJECT is selected, you MUST provide at least one concrete, non-empty reason in rejection_reasons.
   - VALIDATE: Use when the opportunity is promising and potentially attractive, but important assumptions remain unproven (e.g., willingness to pay, adoption friction, or technical scalability).
     * rejection_reasons may be empty or list key risk factors to validate.
   - PURSUE: Use ONLY when the opportunity has unusually strong evidence and logic across multiple dimensions (severe pain, clear high-budget payer, large scale, strong defensibility).
     * Reserve PURSUE for exceptional, top-tier opportunities.

7. STRICT OUTPUT FORMAT:
   - Return ONLY a valid JSON object.
   - Do NOT wrap in Markdown code blocks (no ```json or ```).
   - Do NOT include any introductory or concluding text outside the JSON object.
   - The JSON object must contain EXACTLY these 16 keys and NO others:
     {
       "opportunity_id": "Exact ID of the evaluated opportunity",
       "overall_score": 85,
       "problem_severity_score": 9,
       "frequency_score": 8,
       "user_scale_score": 8,
       "willingness_to_pay_score": 9,
       "market_gap_score": 7,
       "technology_leverage_score": 9,
       "competition_score": 8,
       "wow_factor_score": 8,
       "recurring_potential_score": 7,
       "social_impact_score": 8,
       "execution_feasibility_score": 8,
       "rejection_reasons": [],
       "recommendation": "PURSUE | VALIDATE | REJECT",
       "rationale": "Substantive justification explaining the scoring and recommendation (minimum 15 characters)"
     }
"""


def format_opportunity_evaluation_user_prompt(
    opportunity: OpportunityRecord,
    problems: Optional[Sequence[ProblemRecord]] = None,
) -> str:
    """Format an OpportunityRecord and optional ProblemRecord leads into an AI evaluation user prompt.

    Args:
        opportunity: OpportunityRecord instance to evaluate.
        problems: Optional sequence of originating ProblemRecord instances for additional context.

    Returns:
        str: Formatted user prompt string detailing the opportunity and output requirements.

    Raises:
        TypeError: If opportunity is not an OpportunityRecord.
    """
    if not isinstance(opportunity, OpportunityRecord):
        raise TypeError(f"Expected OpportunityRecord instance, got {type(opportunity).__name__}.")

    opp_id = opportunity.id or "opportunity-lead-1"

    sections = [
        "Critically evaluate the following startup opportunity according to your instructions:\n",
        f"Opportunity ID: {opp_id}\n"
        f"Title: {opportunity.opportunity_title}\n"
        f"Solution Concept: {opportunity.solution_concept}\n"
        f"Target Customer: {opportunity.target_customer}\n"
        f"Value Proposition: {opportunity.value_proposition}\n"
        f"Source Problem IDs: {', '.join(opportunity.source_problem_ids)}\n",
    ]

    if problems:
        sections.append("--- SOURCE PROBLEM CONTEXT ---")
        for idx, prob in enumerate(problems, 1):
            sections.append(
                f"Problem {idx} (ID: {prob.id or 'unknown'}):\n"
                f"  Title: {prob.problem_title}\n"
                f"  Description: {prob.problem_description}\n"
                f"  Affected Users: {prob.affected_users}\n"
                f"  Bottleneck Type: {prob.bottleneck_type}\n"
                f"  Technical Domain: {prob.technical_domain}\n"
                f"  Current Workaround: {prob.current_workaround}\n"
                f"  Severity: {prob.problem_severity} | Frequency: {prob.problem_frequency}\n"
            )

    sections.append(
        "Evaluate this opportunity rigorously:\n"
        "- Assess severity, frequency, scale, willingness to pay, market gap, tech leverage, competition, wow factor, recurring potential, social impact, and feasibility.\n"
        "- Use REJECT if the opportunity lacks a credible path to a viable business, and provide concrete rejection_reasons.\n"
        "- Use VALIDATE if promising but key assumptions need testing.\n"
        "- Use PURSUE only for exceptionally strong opportunities.\n"
        f"- Ensure 'opportunity_id' in your JSON output exactly matches: '{opp_id}'.\n"
        "- Return ONLY a valid JSON object matching the exact 16 required schema fields."
    )

    return "\n".join(sections)
