"""Prompt specification for AI-driven market research and competitive intelligence.

Prepares structured prompts for investigating existing companies, competitive solutions,
market saturation, customer complaints, and market gaps connected to a startup opportunity.
"""

from typing import Final, Optional, Sequence

from src.opportunities.models import OpportunityRecord
from src.problems.models import ProblemRecord

MARKET_RESEARCH_SYSTEM_PROMPT: Final[str] = """You are an elite competitive intelligence researcher, market analyst, and startup venture strategist.
Your task is to conduct rigorous, evidence-based market research on a proposed startup venture opportunity.

Follow these strict investigation principles:

1. INVESTIGATE THE COMPLETE MARKET LANDSCAPE:
   You must investigate and gather evidence on:
   - Existing companies solving the same or closely related problem.
   - Existing products, platforms, or commercial solutions in the space.
   - What existing solutions actually provide (core features, operating models, architectures).
   - Who their customers/users are (enterprise, SMB, prosumer, end consumer).
   - Important weaknesses, gaps, or limitations visible from public evidence and user feedback.
   - Market structure: Assess whether the category is crowded, fragmented, emerging, or underpenetrated.
   - Evidence of user pain, customer complaints, friction, or unsatisfied demand with current solutions.
   - Potential gaps and underserved niches that a new startup could address.
   - Meaningful differentiation: Assess why the opportunity may or may not be meaningfully different from existing solutions.

2. PATENT IS A RESEARCH LEAD, NOT A BLUEPRINT:
   - The patent is only a technical research lead, not a commercial product.
   - We are researching the underlying problem and customer pain, NOT copying or commercializing the patent claims.
   - Do not assume patent claims define commercial market boundaries.

3. BALANCED VIEW OF COMPETITION:
   - Competition is NOT automatically bad: existing competitors validate that customer demand and willingness to pay exist.
   - An existing competitor does NOT automatically mean rejection: evaluate whether the market is large, growing, fragmented, or poorly served.
   - Distinguish between entrenched monopolies with insurmountable moats versus fragmented or slow-moving legacy incumbents.

4. STRICT ANTI-FABRICATION & EVIDENCE DISCIPLINE:
   - Do NOT fabricate companies, products, URLs, statistics, customer complaints, or market evidence.
   - Do NOT invent unsupported TAM, revenue numbers, market growth percentages, or fictional user counts.
   - Base all findings on real-world market facts or conservative industry realities.

5. EPISTEMIC PRECISION - DISTINGUISH THREE TIERS OF KNOWLEDGE:
   Every finding or statement must explicitly distinguish:
   - KNOWN FACTS: Verified, real-world existing companies, products, pricing models, or public facts.
   - EVIDENCE NEEDED: Points that require live web verification, customer interviews, or primary sourcing.
   - HYPOTHESES / INFERENCES: Analytical deductions, positioning hypotheses, or extrapolations, explicitly labeled as such.

6. STRUCTURED FINDING STANDARDS:
   - Focus on concrete findings that can be verified and evaluated.
   - Highlight direct competitor features, pricing friction, technical limitations, and unaddressed user segments.
   - Rate findings by relevance (HIGH = decisive direct competitor/pain point, MEDIUM = adjacent player/trend, LOW = contextual background).

7. STRICT OUTPUT FORMAT:
   - Return ONLY a valid JSON array of findings (or a JSON object with a "findings" list).
   - Do NOT wrap in Markdown code blocks (no ```json or ```).
   - Do NOT include any introductory or concluding text outside the JSON.
   - Each finding object must contain EXACTLY these 8 keys:
     {
       "opportunity_id": "Exact ID of the researched opportunity",
       "source_type": "competitor_site | industry_report | news | review_forum | official | other",
       "source_name": "Name of publication, platform, or source organization",
       "source_url": "Direct URL or citation reference",
       "company_or_product": "Name of existing company, product, or solution discovered",
       "finding": "Concrete finding or key market insight",
       "evidence_summary": "Factual summary of the collected market evidence",
       "relevance": "HIGH | MEDIUM | LOW"
     }
"""



def format_market_research_user_prompt(
    opportunity: OpportunityRecord,
    problems: Optional[Sequence[ProblemRecord]] = None,
    evidence: Optional[object] = None,
) -> str:
    """Format an OpportunityRecord, optional problems, and optional evidence into a user prompt.

    Args:
        opportunity: OpportunityRecord instance representing the venture opportunity to research.
        problems: Optional sequence of originating ProblemRecord instances for technical context.
        evidence: Optional research evidence string, sequence of findings, or context dictionary.

    Returns:
        str: Formatted user prompt text detailing the opportunity, context, and research requirements.

    Raises:
        TypeError: If opportunity is not an OpportunityRecord, or if problems contains invalid objects.
    """
    if not isinstance(opportunity, OpportunityRecord):
        raise TypeError(f"Expected OpportunityRecord instance, got {type(opportunity).__name__}.")

    if problems is not None:
        if not isinstance(problems, (list, tuple)):
            raise TypeError(
                f"problems must be a list or tuple of ProblemRecord objects, got {type(problems).__name__}."
            )
        for idx, p in enumerate(problems):
            if not isinstance(p, ProblemRecord):
                raise TypeError(
                    f"problems[{idx}] must be a ProblemRecord instance, got {type(p).__name__}."
                )

    opp_id = opportunity.id or "opportunity-research-1"

    sections = [
        "Conduct structured, evidence-based market research on the following startup venture opportunity:\n",
        "--- STARTUP OPPORTUNITY ---",
        f"Opportunity ID: {opp_id}",
        f"Title: {opportunity.opportunity_title}",
        f"Solution Concept: {opportunity.solution_concept}",
        f"Target Customer: {opportunity.target_customer}",
        f"Value Proposition: {opportunity.value_proposition}",
        f"Source Problem IDs: {', '.join(opportunity.source_problem_ids)}\n",
    ]

    if problems:
        sections.append("--- SOURCE PROBLEM CONTEXT ---")
        for idx, prob in enumerate(problems, 1):
            prob_id = prob.id or f"problem-lead-{idx}"
            sections.append(
                f"Problem Lead {idx} (ID: {prob_id}):\n"
                f"  Title: {prob.problem_title}\n"
                f"  Description: {prob.problem_description}\n"
                f"  Affected Users: {prob.affected_users}\n"
                f"  Bottleneck Type: {prob.bottleneck_type}\n"
                f"  Technical Domain: {prob.technical_domain}\n"
                f"  Current Workaround: {prob.current_workaround}\n"
                f"  Severity: {prob.problem_severity} | Frequency: {prob.problem_frequency}\n"
                f"  Evidence Summary: {prob.evidence_summary}\n"
                f"  Source Patents: {', '.join(prob.source_patent_numbers)}\n"
            )

    if evidence:
        sections.append("--- SUPPLIED RESEARCH EVIDENCE / CONTEXT ---")
        if isinstance(evidence, str):
            clean_ev = evidence.strip()
            if clean_ev:
                sections.append(clean_ev)
        elif isinstance(evidence, (list, tuple)):
            for idx, item in enumerate(evidence, 1):
                sections.append(f"Evidence Item {idx}: {str(item).strip()}")
        elif isinstance(evidence, dict):
            import json
            sections.append(json.dumps(evidence, indent=2))
        else:
            sections.append(str(evidence).strip())
        sections.append("")

    sections.append(
        "--- RESEARCH OBJECTIVES & INSTRUCTIONS ---\n"
        "Investigate the market landscape thoroughly across these dimensions:\n"
        "1. Existing Companies: Identify existing companies solving the same or closely related problem.\n"
        "2. Existing Products/Solutions: Detail existing commercial products, platforms, or tools.\n"
        "3. Solution Capabilities: Explain what existing solutions actually provide and how they operate.\n"
        "4. Customer Segments: Identify who currently buys and uses these existing solutions.\n"
        "5. Visible Weaknesses: Identify notable limitations, friction, high costs, or architectural gaps.\n"
        "6. Category Dynamics: Assess if the category is crowded, fragmented, emerging, or underpenetrated.\n"
        "7. User Pain & Demand: Document evidence of user complaints, workarounds, or unsatisfied demand.\n"
        "8. Market Gaps: Identify underserved customer segments or white space a startup could address.\n"
        "9. Meaningful Differentiation: Evaluate why this opportunity may or may not be defensibly differentiated.\n"
        "\n"
        "Strict Requirements:\n"
        "- ZERO FABRICATION: Do NOT invent companies, products, URLs, statistics, TAM numbers, or user reviews.\n"
        "- EPISTEMIC CLARITY: Explicitly categorize findings as (1) Known Facts, (2) Evidence Needing Verification, or (3) Hypotheses/Inferences.\n"
        "- PROBLEM FOCUS: The patent is only a lead; focus on the underlying customer problem, not patent claims.\n"
        "- COMPETITION PERSPECTIVE: Competition validates demand; an existing competitor does not mean automatic rejection.\n"
        f"- OUTPUT FORMAT: Return ONLY a valid JSON array of findings with opportunity_id='{opp_id}'."
    )


    return "\n".join(sections)
