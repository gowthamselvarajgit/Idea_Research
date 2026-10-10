"""Explicit evidence-status classification for market research findings.

Classifies market research findings into:
- SUPPORTED: The collected source contains specific evidence relevant to the finding.
- HYPOTHESIS: The finding is plausible but is not sufficiently supported by the collected source.
- NEEDS_RESEARCH: The claim requires further investigation or its supporting evidence is missing or inadequate.

Citation URL matching alone does not establish support. Grounding inspects actual
source content deterministically without extra network requests or AI calls,
failing conservatively to NEEDS_RESEARCH when support cannot be established.
"""

from collections.abc import Sequence
from dataclasses import replace
import logging
import math
import re
from typing import Any, Final, Optional, Union

from src.market_research.models import MarketResearchRecord
from src.market_research.source_models import WebResearchSource

logger = logging.getLogger(__name__)

EVIDENCE_STATUS_SUPPORTED: Final[str] = "SUPPORTED"
EVIDENCE_STATUS_HYPOTHESIS: Final[str] = "HYPOTHESIS"
EVIDENCE_STATUS_NEEDS_RESEARCH: Final[str] = "NEEDS_RESEARCH"

ALLOWED_EVIDENCE_STATUSES: Final[frozenset[str]] = frozenset({
    EVIDENCE_STATUS_SUPPORTED,
    EVIDENCE_STATUS_HYPOTHESIS,
    EVIDENCE_STATUS_NEEDS_RESEARCH,
})

STOP_WORDS: Final[frozenset[str]] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't",
    "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers",
    "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll",
    "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its",
    "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't",
    "so", "some", "such", "than", "that", "that's", "the", "their",
    "theirs", "them", "themselves", "then", "there", "there's", "these",
    "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what",
    "what's", "when", "when's", "where", "where's", "which", "while", "who",
    "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't",
    "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
})

GENERIC_RESEARCH_WORDS: Final[frozenset[str]] = frozenset({
    "market", "research", "industry", "company", "product", "technology",
    "solution", "report", "finding", "evidence", "article", "source",
    "provides", "according", "stated", "confirmed", "competitor", "startup",
    "business", "data", "information", "analysis", "study", "overview",
})

GENERIC_ENTITY_NAMES: Final[frozenset[str]] = frozenset({
    "", "n/a", "none", "unknown", "market", "industry", "general",
    "competitor", "various", "multiple", "unspecified",
})

HYPOTHESIS_PATTERNS: Final[tuple[str, ...]] = (
    r"\bhypothesi[sz]\w*",
    r"\bconjecture\w*",
    r"\bspeculat\w*",
    r"\btheor\w*\b(?:\s+possible|\s+could|\s+might|\s+unproven)",
    r"\bcould\s+potentially\b",
    r"\bmight\s+potentially\b",
    r"\bmay\s+potentially\b",
    r"\bpotentially\s+(?:could|might|may)\b",
    r"\bconceivably\b",
    r"\bplausible\s+(?:hypothesis|assumption|inference|possibility)\b",
    r"\bworking\s+hypothesis\b",
    r"\bunproven\b",
    r"\bunverified\s+(?:claim|assumption|hypothesis|inference)\b",
    r"\bremains\s+to\s+be\s+seen\b",
    r"\byet\s+to\s+be\s+confirmed\b",
    r"\bunconfirmed\b",
    r"\bpossible\s+(?:future|trend|outcome|scenario)\b",
    r"\bsuggests\s+a\s+possible\b",
    r"\bit\s+is\s+posited\b",
    r"\bposits\s+that\b",
    r"\bpresumed\s+to\b",
    r"\bworking\s+assumption\b",
)

_HYPOTHESIS_REGEX: Final[re.Pattern] = re.compile(
    "|".join(HYPOTHESIS_PATTERNS),
    re.IGNORECASE,
)


def is_hypothesis_claim(finding: MarketResearchRecord) -> bool:
    """Check if the finding is presented as a hypothesis, possibility, or inference."""
    if not isinstance(finding, MarketResearchRecord):
        return False

    text_to_check = f"{finding.finding} {finding.evidence_summary}"
    if _HYPOTHESIS_REGEX.search(text_to_check):
        return True

    if isinstance(finding.raw_data, dict):
        status = finding.raw_data.get("evidence_status")
        if isinstance(status, str) and status.upper() == EVIDENCE_STATUS_HYPOTHESIS:
            return True
        ai_out = finding.raw_data.get("ai_raw_output")
        if isinstance(ai_out, dict):
            ai_finding = str(ai_out.get("finding", ""))
            ai_evidence = str(ai_out.get("evidence_summary", ""))
            if _HYPOTHESIS_REGEX.search(f"{ai_finding} {ai_evidence}"):
                return True

    return False


def extract_candidate_passages(content: Optional[str]) -> list[str]:
    """Extract candidate sentence and paragraph passages from source content."""
    if not content or not isinstance(content, str):
        return []

    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    passages: list[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", normalized) if p.strip()]

    for para in paragraphs:
        cleaned_para = " ".join(para.split())
        if 20 <= len(cleaned_para) <= 450:
            passages.append(cleaned_para)

        sentences = [
            " ".join(s.split())
            for s in re.split(r"(?<=[.!?])\s+", para)
            if len(" ".join(s.split())) >= 20
        ]
        passages.extend(sentences)

        for i in range(len(sentences) - 1):
            pair = f"{sentences[i]} {sentences[i+1]}"
            if len(pair) <= 500:
                passages.append(pair)

    if not passages:
        chunks = [
            " ".join(c.split())
            for c in re.split(r"\n+|(?<=[.!?])\s+", normalized)
            if len(" ".join(c.split())) >= 20
        ]
        passages.extend(chunks)
        for i in range(len(chunks) - 1):
            pair = f"{chunks[i]} {chunks[i+1]}"
            if len(pair) <= 500:
                passages.append(pair)

    seen: set[str] = set()
    result: list[str] = []
    for p in passages:
        if p not in seen and len(p) >= 20:
            seen.add(p)
            result.append(p)

    return result


def extract_normalized_currencies(text: str) -> set[float]:
    """Extract dollar currency amounts and normalize to numeric float values.

    Handles:
    - $5M, $5m, $5 M -> 5_000_000.0
    - $5B, $5b, $5 billion -> 5_000_000_000.0
    - $5K, $5k, $5 thousand -> 5_000.0
    - $5,000,000, $5,000,000.00 -> 5_000_000.0
    - $1.5B, $1.5 billion -> 1_500_000_000.0
    - 5 million dollars, 5 billion USD
    """
    results: set[float] = set()
    pattern = re.compile(
        r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
        r"(?:\s*(billion|million|thousand|[bmk]))?\b",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        num_str = m.group(1).replace(",", "")
        scale_str = (m.group(2) or "").lower()
        try:
            val = float(num_str)
        except ValueError:
            continue
        if scale_str in ("b", "billion"):
            val *= 1_000_000_000.0
        elif scale_str in ("m", "million"):
            val *= 1_000_000.0
        elif scale_str in ("k", "thousand"):
            val *= 1_000.0
        results.add(round(val, 2))

    alt_pattern = re.compile(
        r"\b([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
        r"\s*(billion|million|thousand|[bmk])?\s*(?:dollars|usd)\b",
        re.IGNORECASE,
    )
    for m in alt_pattern.finditer(text):
        num_str = m.group(1).replace(",", "")
        scale_str = (m.group(2) or "").lower()
        try:
            val = float(num_str)
        except ValueError:
            continue
        if scale_str in ("b", "billion"):
            val *= 1_000_000_000.0
        elif scale_str in ("m", "million"):
            val *= 1_000_000.0
        elif scale_str in ("k", "thousand"):
            val *= 1_000.0
        results.add(round(val, 2))

    return results


def _extract_claim_features(finding: MarketResearchRecord) -> dict[str, Any]:
    """Extract informative key words, critical metrics, entity words, and phrases."""
    claim_text = f"{finding.finding} {finding.evidence_summary}"

    all_words = re.findall(r"\b[a-zA-Z0-9$%.-]+\b", claim_text.lower())
    clean_words = {w.strip(".$,") for w in all_words if len(w.strip(".$, ")) >= 2}

    informative_words = {
        w for w in clean_words
        if w not in STOP_WORDS
        and w not in GENERIC_RESEARCH_WORDS
        and (len(w) >= 3 or w in {"ro", "ai", "ml", "ev", "ip", "ar", "vr", "b2b", "saas"})
    }

    metric_matches = re.findall(
        r"\$\d+(?:\.\d+)?[kmb]?|\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?\s*(?:million|billion|thousand)\b",
        claim_text.lower(),
    )
    critical_metrics = {m.strip() for m in metric_matches if m.strip()}
    currency_values = extract_normalized_currencies(claim_text)
    pct_matches = re.findall(r"\b\d+(?:\.\d+)?%", claim_text.lower())
    percentage_values = {float(p.rstrip("%")) for p in pct_matches}

    company = (finding.company_or_product or "").strip().lower()
    is_specific_entity = company not in GENERIC_ENTITY_NAMES
    entity_words: set[str] = set()
    if is_specific_entity:
        entity_tokens = re.findall(r"\b[a-zA-Z0-9]{3,}\b", company)
        entity_words = {
            w for w in entity_tokens
            if w not in STOP_WORDS and w not in GENERIC_RESEARCH_WORDS
        }

    finding_words = [
        w.lower().strip(".,:;!?()\"'")
        for w in finding.finding.split()
        if w.lower().strip(".,:;!?()\"'") and w.lower().strip(".,:;!?()\"'") not in STOP_WORDS
    ]
    phrases: list[str] = []
    if len(finding_words) >= 4:
        for i in range(len(finding_words) - 3):
            phrases.append(" ".join(finding_words[i:i+4]))

    return {
        "informative_words": informative_words,
        "critical_metrics": critical_metrics,
        "currency_values": currency_values,
        "percentage_values": percentage_values,
        "is_specific_entity": is_specific_entity,
        "entity_words": entity_words,
        "phrases": phrases,
    }


OPPOSING_TERM_PAIRS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = (
    # Directional trends
    (
        ("increased", "increase", "increasing", "increases", "rose", "rising", "grow", "grew", "growth", "surged", "surge"),
        ("decreased", "decrease", "decreasing", "decreases", "fell", "falling", "declined", "decline", "declining", "dropped", "drop", "slumped", "contracted", "contraction"),
    ),
    # Expansion vs Contraction
    (
        ("expanded", "expand", "expanding", "expansion", "scaled", "scale"),
        ("contracted", "contract", "contracting", "contraction", "shrank", "shrink", "shrinking", "downsized", "downsizing"),
    ),
    # Hiring vs Layoffs
    (
        ("hired", "hires", "hiring", "expanded workforce", "new hires", "recruited"),
        ("laid off", "layoffs", "layoff", "downsized", "fired", "workforce cuts", "job cuts", "staff cuts"),
    ),
    # Partnership / Agreement
    (
        ("formed", "signed", "entered", "partnered", "agreed", "joint venture"),
        ("rejected", "denied", "terminated", "refused", "abandoned", "called off", "cancelled"),
    ),
    # M&A
    (
        ("acquired", "bought", "purchased", "acquisition", "merger"),
        ("sued", "suing", "lawsuit", "sued for", "terminated", "abandoned", "called off", "failed", "collapsed"),
    ),
    # Product Lifecycle
    (
        ("launched", "released", "introduced", "debuted", "unveiled", "rolled out"),
        ("recalled", "recall", "discontinued", "withdrew", "withdrawn", "scrapped", "halted"),
    ),
    # Funding & Deals
    (
        ("secured", "closed", "won", "raised", "obtained"),
        ("lost", "forfeited", "failed to raise", "missed", "collapsed"),
    ),
    # Approvals
    (
        ("approved", "approval", "cleared", "authorized", "certified"),
        ("rejected", "rejection", "denied", "prohibited", "banned", "failed approval"),
    ),
    # Research & Action
    (
        ("conducted", "authored", "performed", "published study", "carried out"),
        ("criticized", "disputed", "questioned", "challenged", "refuted", "rejected the study"),
    ),
)

AFFIRMATIVE_PREDICATES: Final[tuple[str, ...]] = (
    "effective", "efficacy", "safe", "safety", "achieved", "achieve",
    "approved", "approval", "viable", "compliant", "proven", "proved", "proving",
    "prevented", "prevents", "success", "successful", "resolved", "verified", "certified",
    "authorized", "functional", "operational",
)

ANTONYM_MAP: Final[dict[str, tuple[str, ...]]] = {
    "effective": ("ineffective", "inefficient", "not effective", "failed to prevent"),
    "efficacy": ("inefficacy", "ineffective", "no efficacy"),
    "safe": ("unsafe", "hazardous", "dangerous", "toxic", "harmful", "never safe", "not safe"),
    "safety": ("hazard", "danger", "safety failure", "safety risk"),
    "achieved": ("failed to achieve", "unable to achieve", "did not achieve", "failed"),
    "approved": ("unapproved", "rejected", "denied", "banned", "failed approval"),
    "approval": ("rejection", "denial", "prohibition", "failed to achieve approval"),
    "viable": ("unviable", "infeasible", "not viable"),
    "compliant": ("non-compliant", "noncompliant", "violating"),
    "proven": ("unproven", "disproven", "disproved", "debunked", "unsubstantiated", "disputed", "challenged", "refuted"),
    "proved": ("disproved", "disproven", "debunked", "disputed", "challenged", "refuted"),
    "proving": ("disproving", "debunking", "disputing", "challenging"),
}

NEGATION_PREFIXES: Final[str] = (
    r"\b(?:not|never|no|neither|barely|hardly|scarcely|cannot|can't|couldn't|didn't|"
    r"doesn't|don't|wasn't|weren't|isn't|aren't|won't|wouldn't|failed\s+to|"
    r"failure\s+to|unable\s+to|unsuccessful\s+in|refused\s+to|rejected\s+by)\b"
)

CLAUSE_SPLITTERS: Final[re.Pattern[str]] = re.compile(
    r";|--|\b(?:but|whereas|while|however|although|though|yet|conversely|in\s+contrast|on\s+the\s+other\s+hand)\b",
    re.IGNORECASE,
)


def clause_applies_to_target_entity(
    clause_lower: str,
    target_entity: str,
    entity_tokens: Sequence[str],
) -> bool:
    """Determine whether a clause with an opposing predicate applies to the target entity."""
    competitor_markers = (
        "competitor", "rival", "alternative", "competitors", "rivals",
        "peer", "competing", "other company", "another company",
    )
    has_competitor_marker = any(
        re.search(rf"\b{re.escape(cm)}(?:'s|\b)", clause_lower)
        for cm in competitor_markers
    )

    has_target = bool(
        target_entity and target_entity in clause_lower
    ) or bool(
        entity_tokens and all(re.search(rf"\b{re.escape(t)}\b", clause_lower) for t in entity_tokens)
    )

    if has_competitor_marker:
        if re.search(
            r"(?:competitor|rival|alternative|competing)\w*(?:'s)?\s+(?:\w+\s+){0,3}"
            r"(?:is|are|was|were|remains?|proved|found)\s+(?:\w+\s+){0,2}"
            r"(?:unsafe|not\s+safe|ineffective|hazardous|dangerous|toxic|harmful|unapproved|rejected)",
            clause_lower,
        ):
            return False
        if not has_target:
            return False

    if target_entity:
        other_entities = re.findall(r"\b(?:product|company|system|unit|device)\s+([a-zA-Z0-9]+)\b", clause_lower)
        target_parts = re.findall(r"\b(?:product|company|system|unit|device)\s+([a-zA-Z0-9]+)\b", target_entity)
        if other_entities and target_parts:
            if any(oe not in target_parts for oe in other_entities) and not has_target:
                return False

    return True


def check_negation_contradiction(
    finding_text: str,
    cand_lower: str,
    target_entity: Optional[str] = None,
) -> bool:
    """Check if candidate passage negates an affirmative predicate asserted in the finding.

    Scrutinizes entity and clause scope so opposing predicates about distinct entities
    (e.g., Product B or a competitor) do not falsely disqualify support for the target entity.
    """
    finding_lower = finding_text.lower()
    entity_norm = (target_entity or "").strip().lower()
    entity_tokens = [
        w for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", entity_norm)
        if w not in STOP_WORDS and w not in GENERIC_RESEARCH_WORDS
    ] if entity_norm and entity_norm not in GENERIC_ENTITY_NAMES else []

    if not entity_norm:
        entity_match = re.search(r"\b(?:product|company|system|unit)\s+([a-zA-Z0-9]+)\b", finding_lower)
        if entity_match:
            entity_norm = entity_match.group(0)
            entity_tokens = entity_norm.split()

    clauses = [c.strip() for c in CLAUSE_SPLITTERS.split(cand_lower) if c.strip()]
    if not clauses:
        clauses = [cand_lower]

    for pred in AFFIRMATIVE_PREDICATES:
        has_pred_in_finding = bool(re.search(rf"\b{re.escape(pred)}\b", finding_lower))
        finding_has_neg = bool(
            re.search(rf"{NEGATION_PREFIXES}\s+(?:\w+\s+){{0,2}}{re.escape(pred)}\b", finding_lower)
        )
        if has_pred_in_finding and not finding_has_neg:
            for clause in clauses:
                # 1. Direct negation: e.g. "not safe", "never safe"
                has_neg_pred = bool(
                    re.search(rf"{NEGATION_PREFIXES}\s+(?:\w+\s+){{0,2}}{re.escape(pred)}\b", clause)
                )
                if has_neg_pred:
                    if clause_applies_to_target_entity(clause, entity_norm, entity_tokens):
                        return True

                # 2. Antonym match: e.g. "unsafe", "hazardous"
                if pred in ANTONYM_MAP:
                    for ant in ANTONYM_MAP[pred]:
                        if re.search(rf"\b{re.escape(ant)}\b", clause):
                            # Double negation check (litotes): e.g. "not unsafe"
                            is_double_neg = bool(
                                re.search(rf"{NEGATION_PREFIXES}\s+(?:\w+\s+){{0,2}}{re.escape(ant)}\b", clause)
                            )
                            if not is_double_neg:
                                if clause_applies_to_target_entity(clause, entity_norm, entity_tokens):
                                    return True
    return False


def check_polar_contradiction(finding_text: str, cand_lower: str) -> bool:
    """Check for opposing direction, relationship, or action verbs between finding and passage."""
    finding_lower = finding_text.lower()

    # Compound refutations of deals, acquisitions, partnerships, contracts
    if re.search(
        r"\b(?:terminated|failed|abandoned|called\s+off|halted|blocked|rejected|collapsed|refused)\s+(?:the\s+)?(?:acquisition|merger|partnership|deal|contract|talks)\b",
        cand_lower,
    ):
        if any(t in finding_lower for t in ("acquired", "bought", "merger", "partnered", "partnership", "deal")):
            return True

    for group_a, group_b in OPPOSING_TERM_PAIRS:
        has_a_finding = any(re.search(rf"\b{re.escape(t)}\b", finding_lower) for t in group_a)
        has_b_finding = any(re.search(rf"\b{re.escape(t)}\b", finding_lower) for t in group_b)
        has_a_cand = any(re.search(rf"\b{re.escape(t)}\b", cand_lower) for t in group_a)
        has_b_cand = any(re.search(rf"\b{re.escape(t)}\b", cand_lower) for t in group_b)

        if has_a_finding and not has_b_finding:
            if has_b_cand and not has_a_cand:
                return True
        if has_b_finding and not has_a_finding:
            if has_a_cand and not has_b_cand:
                return True
    return False


def check_mixed_event_contradiction(finding_text: str, cand_lower: str) -> bool:
    """Check if passage describes a subsequent reversal that contradicts the finding's proposition.

    Evaluates the actual proposition expressed:
    - Pure historical launch ("The company launched its product") remains valid even if a recall
      is later reported in the same source.
    - Claims of ongoing availability ("remains available", "currently available", "on the market")
      or unreversed successful status are contradicted by a subsequent recall.
    - Claims of non-recall ("was never recalled", "no recalls") are directly contradicted.
    """
    finding_lower = finding_text.lower()

    # Reversal / recall / withdrawal actions in candidate passage
    has_recall_or_reversal = bool(
        re.search(
            r"\b(?:recalled|recall|withdrawn|withdrew|discontinued|pulled\s+from\s+(?:the\s+)?market|"
            r"scrapped|halted\s+sales|canceled|terminated|collapsed)\b",
            cand_lower,
        )
    )
    if not has_recall_or_reversal:
        return False

    # 1. Finding claims non-recall or absence of failure
    if re.search(
        r"\b(?:never\s+recalled|not\s+recalled|no\s+recalls?|without\s+recalls?|unrecalled|no\s+cancellations?)\b",
        finding_lower,
    ):
        return True

    # 2. Finding claims current availability, ongoing commercial deployment, or active market presence
    if re.search(
        r"\b(?:currently\s+available|remains\s+available|still\s+available|on\s+the\s+market|"
        r"in\s+active\s+(?:use|deployment|operation|service)|ongoing\s+(?:commercialization|deployment|use)|"
        r"actively\s+deployed|continuous\s+operation|uninterrupted)\b",
        finding_lower,
    ):
        return True

    # 3. Finding claims an unreversed successful status or flawless record
    if re.search(
        r"\b(?:unreversed|unbroken\s+record|flawless\s+deployment|without\s+issue|without\s+incident)\b",
        finding_lower,
    ):
        return True

    return False


def check_causation_contradiction(finding_text: str, cand_lower: str) -> bool:
    """Check if the candidate passage denies causation asserted by the finding."""
    finding_lower = finding_text.lower()
    has_causal_assertion = bool(
        re.search(r"\b(?:caused|causes|causing|directly\s+caused)\b", finding_lower)
    )
    if not has_causal_assertion:
        return False

    if re.search(
        r"\b(?:not\s+the\s+cause|was\s+not\s+caused\s+by|did\s+not\s+cause|no\s+causal\s+(?:link|relationship)|merely\s+correlated|not\s+responsible\s+for|unrelated\s+to|not\s+the\s+cause)\b",
        cand_lower,
    ):
        return True
    if re.search(r"\b(?:occurred\s+concurrently|occurred\s+together|coincided\s+with)\b", cand_lower) and re.search(
        r"\b(?:not\s+the\s+cause|was\s+not\s+the\s+cause|not\s+caused)\b", cand_lower
    ):
        return True
    if re.search(r"\b(?:entirely|instead|actually)\s+caused\s+by\b", cand_lower):
        return True
    return False


def check_retraction_contradiction(cand_lower: str) -> bool:
    """Check if the candidate passage describes a claim that was later corrected or retracted."""
    return bool(
        re.search(
            r"\b(?:initially\s+(?:claimed|stated|reported|thought)|later\s+retracted|"
            r"retracted\s+the\s+claim|proved\s+this\s+was\s+(?:incorrect|false|untrue)|"
            r"subsequent\s+(?:testing|reports|investigation)\s+(?:proved|showed)\s+this\s+was\s+(?:incorrect|false)|"
            r"was\s+incorrect|later\s+corrected\s+to|proven\s+false)\b",
            cand_lower,
        )
    )


def check_numerical_conflict(finding_text: str, cand_lower: str) -> bool:
    """Check for conflicting numerical values, percentages, currencies, or counts for the same noun."""
    finding_lower = finding_text.lower()

    # 1. Percentages
    finding_pct_strs = re.findall(r"\b\d+(?:\.\d+)?%", finding_lower)
    if finding_pct_strs:
        cand_pct_strs = re.findall(r"\b\d+(?:\.\d+)?%", cand_lower)
        if cand_pct_strs:
            finding_pcts = {float(p.rstrip("%")) for p in finding_pct_strs}
            cand_pcts = {float(p.rstrip("%")) for p in cand_pct_strs}
            matched_pct = any(
                math.isclose(f, c, rel_tol=1e-5)
                for f in finding_pcts
                for c in cand_pcts
            )
            if not matched_pct:
                return True

    # 2. Currency: deterministic numeric normalization
    finding_currs = extract_normalized_currencies(finding_lower)
    if finding_currs:
        cand_currs = extract_normalized_currencies(cand_lower)
        if cand_currs:
            matched_curr = any(
                math.isclose(f, c, rel_tol=1e-5)
                for f in finding_currs
                for c in cand_currs
            )
            if not matched_curr:
                return True

    # 3. Cardinal counts associated with nouns
    finding_counts = re.findall(r"\b(\d+(?:,\d{3})*)\s+([a-zA-Z]{3,})\b", finding_lower)
    for num_str, noun in finding_counts:
        num_clean = num_str.replace(",", "")
        if noun in {"the", "and", "for", "with", "from", "million", "billion", "thousand", "dollars", "usd"}:
            continue
        if re.search(rf"\b{re.escape(noun)}\b", cand_lower):
            cand_raw_counts = re.findall(rf"\b(\d+(?:,\d{3})*)\s+(?:\w+\s+)?{re.escape(noun)}\b", cand_lower)
            cand_counts = [c.replace(",", "") for c in cand_raw_counts]
            if cand_counts and num_clean not in cand_counts:
                return True

    return False


def is_passage_contradiction(finding: MarketResearchRecord, cand_lower: str) -> bool:
    """Deterministically determine if a candidate passage contradicts or negates the finding."""
    claim_text = f"{finding.finding} {finding.evidence_summary}"
    target_entity = finding.company_or_product

    if check_negation_contradiction(claim_text, cand_lower, target_entity=target_entity):
        return True
    if check_polar_contradiction(claim_text, cand_lower):
        return True
    if check_mixed_event_contradiction(claim_text, cand_lower):
        return True
    if check_causation_contradiction(claim_text, cand_lower):
        return True
    if check_retraction_contradiction(cand_lower):
        return True
    if check_numerical_conflict(claim_text, cand_lower):
        return True
    return False


def find_supporting_passage(
    finding: MarketResearchRecord,
    source: Optional[WebResearchSource],
) -> Optional[str]:
    """Find a specific, relevant passage in the collected source that supports the finding.

    Returns the passage string if found, or None if no sufficient evidence is found.
    Deterministic, conservative, and does not invent passages.
    """
    if not isinstance(finding, MarketResearchRecord) or not isinstance(source, WebResearchSource):
        return None

    content = source.retrieved_content
    if not content or not isinstance(content, str) or not content.strip():
        return None

    features = _extract_claim_features(finding)
    informative_words = features["informative_words"]
    critical_metrics = features["critical_metrics"]
    currency_values = features.get("currency_values", set())
    percentage_values = features.get("percentage_values", set())
    is_specific_entity = features["is_specific_entity"]
    entity_words = features["entity_words"]
    phrases = features["phrases"]

    if not informative_words and not phrases:
        return None

    source_title_lower = (source.title or "").lower()
    source_domain_lower = (source.publisher_or_domain or "").lower()

    candidates = extract_candidate_passages(content)
    best_passage: Optional[str] = None
    best_score: float = 0.0

    for cand in candidates:
        cand_lower = cand.lower()

        # Check entity requirement: for entity-specific claims, entity must be present
        # in either the passage or source page title/domain metadata
        if is_specific_entity and entity_words:
            entity_in_passage = any(ew in cand_lower for ew in entity_words)
            entity_in_meta = any(
                ew in source_title_lower or ew in source_domain_lower
                for ew in entity_words
            )
            if not entity_in_passage and not entity_in_meta:
                continue

        # Check critical metrics: if claim specifies quantitative figures,
        # at least one metric must be present in the candidate passage
        if critical_metrics:
            metric_satisfied = False
            if currency_values:
                cand_currs = extract_normalized_currencies(cand_lower)
                if any(any(math.isclose(cv, cc, rel_tol=1e-5) for cc in cand_currs) for cv in currency_values):
                    metric_satisfied = True
            if not metric_satisfied and percentage_values:
                cand_pcts = {float(p.rstrip("%")) for p in re.findall(r"\b\d+(?:\.\d+)?%", cand_lower)}
                if any(any(math.isclose(pv, cp, rel_tol=1e-5) for cp in cand_pcts) for pv in percentage_values):
                    metric_satisfied = True
            if not metric_satisfied:
                metric_satisfied = any(m in cand_lower for m in critical_metrics)

            if not metric_satisfied:
                continue

        # Contradiction check: disallow passages that contradict, negate, or conflict with claim
        if is_passage_contradiction(finding, cand_lower):
            continue

        # Check direct substantive phrase match
        matched_phrase = False
        for phrase in phrases:
            if phrase in cand_lower:
                matched_phrase = True
                break

        if matched_phrase:
            return cand

        # Check informative words overlap
        matched_words = {w for w in informative_words if w in cand_lower}
        overlap_count = len(matched_words)
        total_count = len(informative_words)

        if total_count <= 2:
            is_supported = (overlap_count == total_count)
        elif total_count in (3, 4):
            is_supported = (overlap_count >= 2 and (overlap_count / total_count) >= 0.5)
        else:
            is_supported = (overlap_count >= 3 and (overlap_count / total_count) >= 0.35)

        if is_supported:
            score = overlap_count / total_count
            if score > best_score:
                best_score = score
                best_passage = cand

    return best_passage


def classify_finding_evidence_status(
    finding: MarketResearchRecord,
    source: Optional[WebResearchSource] = None,
) -> tuple[str, Optional[str]]:
    """Classify the evidence status of a finding against a collected source.

    Returns:
        tuple of (evidence_status, supporting_passage)
        where evidence_status is one of: SUPPORTED, HYPOTHESIS, NEEDS_RESEARCH.
        supporting_passage is the specific text excerpt if SUPPORTED, else None.
    """
    if not isinstance(finding, MarketResearchRecord):
        return EVIDENCE_STATUS_NEEDS_RESEARCH, None

    # 1. Unmatched, malformed, or missing source can NEVER produce SUPPORTED
    if source is None or not isinstance(source, WebResearchSource):
        if is_hypothesis_claim(finding):
            return EVIDENCE_STATUS_HYPOTHESIS, None
        return EVIDENCE_STATUS_NEEDS_RESEARCH, None

    # 2. Missing or empty source content can NEVER produce SUPPORTED
    content = source.retrieved_content
    if not content or not isinstance(content, str) or not content.strip():
        if is_hypothesis_claim(finding):
            return EVIDENCE_STATUS_HYPOTHESIS, None
        return EVIDENCE_STATUS_NEEDS_RESEARCH, None

    # 3. Check for specific supporting passage in source content
    supporting_passage = find_supporting_passage(finding, source)

    if supporting_passage is not None:
        return EVIDENCE_STATUS_SUPPORTED, supporting_passage

    # 4. No sufficient supporting evidence in collected source content
    if is_hypothesis_claim(finding):
        return EVIDENCE_STATUS_HYPOTHESIS, None

    return EVIDENCE_STATUS_NEEDS_RESEARCH, None


def classify_evidence_status(
    finding: MarketResearchRecord,
    source: Optional[WebResearchSource] = None,
) -> str:
    """Classify and return only the evidence status string."""
    status, _ = classify_finding_evidence_status(finding, source)
    return status


def get_finding_evidence_status(
    finding: MarketResearchRecord,
    default: str = EVIDENCE_STATUS_NEEDS_RESEARCH,
) -> str:
    """Retrieve evidence status from a finding's raw_data safely."""
    if isinstance(finding, MarketResearchRecord) and isinstance(finding.raw_data, dict):
        status = finding.raw_data.get("evidence_status")
        if isinstance(status, str) and status.upper() in ALLOWED_EVIDENCE_STATUSES:
            return status.upper()
    return default
