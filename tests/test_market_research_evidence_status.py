"""Focused tests for explicit evidence-status classification for market research findings."""

import unittest
from unittest.mock import MagicMock

from src.market_research.citation_grounding import (
    correlate_finding_with_sources,
    correlate_findings_with_sources,
)
from src.market_research.evidence_status import (
    ALLOWED_EVIDENCE_STATUSES,
    EVIDENCE_STATUS_HYPOTHESIS,
    EVIDENCE_STATUS_NEEDS_RESEARCH,
    EVIDENCE_STATUS_SUPPORTED,
    classify_evidence_status,
    classify_finding_evidence_status,
    find_supporting_passage,
    get_finding_evidence_status,
    is_hypothesis_claim,
)
from src.market_research.models import MarketResearchRecord
from src.market_research.source_models import WebResearchSource
from src.market_research.web_evidence_analyzer import WebEvidenceAnalyzer


class TestMarketResearchEvidenceStatus(unittest.TestCase):
    """Test suite covering deterministic evidence-status classification and metadata preservation."""

    def _sample_source(
        self,
        url: str = "https://aquamembrane.example.com/spec",
        content: str = (
            "AquaMembrane X reverse osmosis technical specifications confirm filtration units "
            "require quarterly chemical washes to prevent biofouling in high-salinity water treatment."
        ),
        title: str = "AquaMembrane Technical Datasheet",
        publisher: str = "AquaMembrane Press",
        pub_date: str = "2026-08-15",
        source_type: str = "competitor",
    ) -> WebResearchSource:
        """Helper to create a WebResearchSource."""
        return WebResearchSource(
            url=url,
            title=title,
            source_type=source_type,
            publisher_or_domain=publisher,
            retrieved_content=content,
            retrieved_at="2026-10-10T10:00:00Z",
            raw_data={
                "search_query": "membrane biofouling",
                "search_engine": "google_news_rss",
                "search_publisher": publisher,
                "pub_date": pub_date,
                "http_status": 200,
            },
        )

    def _sample_finding(
        self,
        source_url: str = "https://aquamembrane.example.com/spec",
        company_or_product: str = "AquaMembrane X",
        finding: str = "AquaMembrane X requires quarterly chemical washes due to biofouling.",
        evidence_summary: str = "Public specifications confirm quarterly chemical wash requirement.",
        opp_id: str = "opp-101",
        raw_data: dict = None,
    ) -> MarketResearchRecord:
        """Helper to create a MarketResearchRecord."""
        return MarketResearchRecord(
            opportunity_id=opp_id,
            source_type="competitor_site",
            source_name="AquaMembrane Press",
            source_url=source_url,
            company_or_product=company_or_product,
            finding=finding,
            evidence_summary=evidence_summary,
            relevance="HIGH",
            raw_data=raw_data if raw_data is not None else {"ai_raw_output": {"finding": finding}},
        )

    # 1. Matching citation with specific relevant evidence
    def test_matching_citation_with_specific_relevant_evidence_is_supported(self) -> None:
        """A matching citation whose collected content contains specific evidence is SUPPORTED."""
        source = self._sample_source()
        finding = self._sample_finding()

        correlated = correlate_finding_with_sources(finding, [source])

        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertFalse(correlated.raw_data.get("unmatched_citation"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

        # Passage from the source must be present without inventing content
        passage = correlated.raw_data.get("supporting_passage")
        self.assertIsNotNone(passage)
        self.assertIn("quarterly chemical washes", passage)
        self.assertIn("AquaMembrane X", passage)

    # 2. Matching citation whose source content does NOT support the claim
    def test_matching_citation_with_irrelevant_content_is_needs_research(self) -> None:
        """A matched citation URL whose content does not support the finding produces NEEDS_RESEARCH."""
        irrelevant_content = (
            "Global automotive manufacturing saw steady electric vehicle adoption in 2026. "
            "Battery recycling facilities reported record operational efficiency across Europe."
        )
        source = self._sample_source(content=irrelevant_content)
        finding = self._sample_finding()

        correlated = correlate_finding_with_sources(finding, [source])

        # Citation is verified against the URL, but evidence status is NEEDS_RESEARCH
        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertFalse(correlated.raw_data.get("unmatched_citation"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertIsNone(correlated.raw_data.get("supporting_passage"))

    # 3. Unmatched citation
    def test_unmatched_citation_produces_needs_research_and_unverified(self) -> None:
        """An unmatched citation URL must never produce SUPPORTED and defaults to NEEDS_RESEARCH."""
        source = self._sample_source(url="https://aquamembrane.example.com/spec")
        finding = self._sample_finding(source_url="https://uncollected-competitor.example.com/other")

        correlated = correlate_finding_with_sources(finding, [source])

        self.assertFalse(correlated.raw_data.get("citation_verified"))
        self.assertTrue(correlated.raw_data.get("unmatched_citation"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertNotEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)
        self.assertIsNone(correlated.raw_data.get("supporting_passage"))

    # 4. Missing or empty source content
    def test_missing_or_empty_source_content_produces_needs_research(self) -> None:
        """Matched citations with missing, None, or whitespace-only content produce NEEDS_RESEARCH."""
        for empty_content in [None, "", "   \n\t  "]:
            with self.subTest(empty_content=repr(empty_content)):
                mock_source = MagicMock(spec=WebResearchSource)
                mock_source.url = "https://aquamembrane.example.com/spec"
                mock_source.title = "AquaMembrane Spec"
                mock_source.publisher_or_domain = "aquamembrane.example.com"
                mock_source.source_type = "competitor"
                mock_source.retrieved_content = empty_content
                mock_source.raw_data = {"http_status": 200}

                finding = self._sample_finding()

                correlated = correlate_finding_with_sources(finding, [mock_source])

                self.assertTrue(correlated.raw_data.get("citation_verified"))
                self.assertEqual(
                    correlated.raw_data.get("evidence_status"),
                    EVIDENCE_STATUS_NEEDS_RESEARCH,
                )
                self.assertIsNone(correlated.raw_data.get("supporting_passage"))

    # 5. Hypothesis without sufficient evidence
    def test_hypothesis_without_sufficient_evidence_is_hypothesis(self) -> None:
        """Findings presented as hypotheses/possibilities without sufficient evidence are HYPOTHESIS."""
        general_source = self._sample_source(
            content="AquaMembrane operates commercial facilities in North America and produces industrial filters."
        )
        speculative_finding = self._sample_finding(
            finding="We hypothesize that AquaMembrane could potentially capture 30% of market share by 2028.",
            evidence_summary="Working hypothesis based on competitor facility expansion.",
        )

        correlated = correlate_finding_with_sources(speculative_finding, [general_source])

        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_HYPOTHESIS)
        self.assertIsNone(correlated.raw_data.get("supporting_passage"))

    # 6. Unmatched hypothesis is also HYPOTHESIS
    def test_unmatched_hypothesis_is_hypothesis(self) -> None:
        """An unverified citation for an explicitly hypothesized claim is HYPOTHESIS, never SUPPORTED."""
        source = self._sample_source(url="https://known.example.com/a")
        speculative_finding = self._sample_finding(
            source_url="https://unknown.example.com/b",
            finding="It is speculated that AquaMembrane might potentially enter the direct-to-consumer market.",
            evidence_summary="Unverified conjecture from industry discussions.",
        )

        correlated = correlate_finding_with_sources(speculative_finding, [source])

        self.assertFalse(correlated.raw_data.get("citation_verified"))
        self.assertTrue(correlated.raw_data.get("unmatched_citation"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_HYPOTHESIS)

    # 7. Preservation of existing raw_data
    def test_preservation_of_existing_raw_data_keys(self) -> None:
        """Evidence-status classification preserves all existing keys in finding.raw_data."""
        initial_raw = {
            "ai_raw_output": {"finding": "test", "relevance": "HIGH"},
            "analyst_notes": "Important lead",
            "pub_date": "2026-08-15",
            "publication_date": "2026-08-15",
            "custom_metadata_tag": 999,
        }
        finding = self._sample_finding(raw_data=initial_raw)
        source = self._sample_source()

        correlated = correlate_finding_with_sources(finding, [source])

        # Verify preserved keys
        self.assertEqual(correlated.raw_data.get("ai_raw_output"), initial_raw["ai_raw_output"])
        self.assertEqual(correlated.raw_data.get("analyst_notes"), "Important lead")
        self.assertEqual(correlated.raw_data.get("pub_date"), "2026-08-15")
        self.assertEqual(correlated.raw_data.get("publication_date"), "2026-08-15")
        self.assertEqual(correlated.raw_data.get("custom_metadata_tag"), 999)

        # Verify newly added keys
        self.assertTrue(correlated.raw_data.get("citation_verified"))
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

    # 8. Citation verification remaining separate from evidence status
    def test_citation_verification_remains_separate_from_evidence_status(self) -> None:
        """citation_verified and evidence_status represent independent evaluations."""
        # Case A: citation_verified=True, evidence_status=SUPPORTED
        src_good = self._sample_source()
        f_good = self._sample_finding()
        c_good = correlate_finding_with_sources(f_good, [src_good])
        self.assertTrue(c_good.raw_data["citation_verified"])
        self.assertEqual(c_good.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)

        # Case B: citation_verified=True, evidence_status=NEEDS_RESEARCH
        src_mismatch = self._sample_source(content="Unrelated text about lunar exploration.")
        f_mismatch = self._sample_finding()
        c_mismatch = correlate_finding_with_sources(f_mismatch, [src_mismatch])
        self.assertTrue(c_mismatch.raw_data["citation_verified"])
        self.assertEqual(c_mismatch.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # Case C: citation_verified=True, evidence_status=HYPOTHESIS
        src_general = self._sample_source(content="Water filter sales grew slightly.")
        f_hypo = self._sample_finding(finding="We hypothesize AquaMembrane could potentially double capacity.")
        c_hypo = correlate_finding_with_sources(f_hypo, [src_general])
        self.assertTrue(c_hypo.raw_data["citation_verified"])
        self.assertEqual(c_hypo.raw_data["evidence_status"], EVIDENCE_STATUS_HYPOTHESIS)

        # Case D: citation_verified=False, evidence_status=NEEDS_RESEARCH
        f_unmatched = self._sample_finding(source_url="https://different.example.com/url")
        c_unmatched = correlate_finding_with_sources(f_unmatched, [src_good])
        self.assertFalse(c_unmatched.raw_data["citation_verified"])
        self.assertEqual(c_unmatched.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # Case E: citation_verified=False, evidence_status=HYPOTHESIS
        f_unmatched_hypo = self._sample_finding(
            source_url="https://different.example.com/url",
            finding="Could potentially enter new markets under working hypothesis.",
        )
        c_unmatched_hypo = correlate_finding_with_sources(f_unmatched_hypo, [src_good])
        self.assertFalse(c_unmatched_hypo.raw_data["citation_verified"])
        self.assertEqual(c_unmatched_hypo.raw_data["evidence_status"], EVIDENCE_STATUS_HYPOTHESIS)

    # 9. Existing findings and legacy records remain compatible
    def test_legacy_records_and_existing_findings_compatibility(self) -> None:
        """Legacy records without evidence_status remain fully valid and handled gracefully."""
        legacy_record = MarketResearchRecord(
            opportunity_id="opp-legacy-01",
            source_type="competitor_site",
            source_name="Legacy Publisher",
            source_url="https://legacy.example.com/page",
            company_or_product="LegacyProduct",
            finding="Legacy finding recorded without evidence_status.",
            evidence_summary="Legacy evidence summary.",
            relevance="MEDIUM",
            id="legacy-id-123",
            raw_data={"ai_raw_output": {"finding": "Legacy finding"}},
        )

        # Model validation succeeds
        self.assertEqual(legacy_record.id, "legacy-id-123")
        self.assertNotIn("evidence_status", legacy_record.raw_data)

        # Safe accessor returns default NEEDS_RESEARCH without throwing
        self.assertEqual(get_finding_evidence_status(legacy_record), EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertEqual(
            get_finding_evidence_status(legacy_record, default="CUSTOM_DEFAULT"),
            "CUSTOM_DEFAULT",
        )

        # Serialization / deserialization round-trip works cleanly
        data_dict = legacy_record.to_dict()
        reconstructed = MarketResearchRecord.from_dict(data_dict)
        self.assertEqual(reconstructed.id, legacy_record.id)
        self.assertEqual(reconstructed.raw_data, legacy_record.raw_data)

    # 10. Publication date, publisher name, search score are not treated as proof of truth
    def test_source_metadata_is_not_treated_as_proof_of_claim_truth(self) -> None:
        """Publisher prestige, dates, and search metrics do not elevate unsupported claims to SUPPORTED."""
        source = WebResearchSource(
            url="https://prestigious-journal.example.com/article",
            title="Leading Journal of Industry",
            source_type="news",
            publisher_or_domain="The Wall Street Journal",
            retrieved_content="Quarterly economic index reported broad macroeconomic cooling.",
            retrieved_at="2026-10-10T12:00:00Z",
            raw_data={
                "search_engine": "premium_search",
                "search_relevance_score": 0.99,
                "relevance_reason": "High relevance search match",
                "pub_date": "2026-10-01",
                "search_publisher": "The Wall Street Journal",
            },
        )
        finding = self._sample_finding(
            source_url="https://prestigious-journal.example.com/article",
            company_or_product="AquaMembrane X",
            finding="AquaMembrane X requires quarterly chemical washes due to biofouling.",
        )

        correlated = correlate_finding_with_sources(finding, [source])

        # Metadata was copied for discovery tracking
        self.assertEqual(correlated.raw_data.get("search_publisher"), "The Wall Street Journal")
        self.assertEqual(correlated.raw_data.get("pub_date"), "2026-10-01")

        # But evidence status is NOT SUPPORTED
        self.assertEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertNotEqual(correlated.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

    # 11. Malformed or invalid URLs never produce SUPPORTED
    def test_malformed_url_never_produces_supported(self) -> None:
        """Malformed or non-HTTP URLs never produce SUPPORTED."""
        for bad_url in ["not-a-url", "ftp://example.com/data", "javascript:void(0)", "https://"]:
            with self.subTest(bad_url=bad_url):
                finding = self._sample_finding(source_url=bad_url)
                correlated = correlate_finding_with_sources(finding, [self._sample_source()])

                self.assertFalse(correlated.raw_data.get("citation_verified"))
                self.assertNotEqual(
                    correlated.raw_data.get("evidence_status"),
                    EVIDENCE_STATUS_SUPPORTED,
                )

    # 12. Batch correlation with correlate_findings_with_sources
    def test_batch_correlation_assigns_correct_statuses(self) -> None:
        """Batch correlate_findings_with_sources classifies all findings accurately."""
        src_supported = self._sample_source(
            url="https://spec.example.com/ro",
            content="AquaMembrane X requires quarterly chemical washes to prevent biofouling.",
        )
        src_unsupported = self._sample_source(
            url="https://other.example.com/info",
            content="General news regarding European water utility regulations.",
        )

        f1 = self._sample_finding(
            source_url="https://spec.example.com/ro",
            finding="AquaMembrane X requires quarterly chemical washes due to biofouling.",
        )
        f2 = self._sample_finding(
            source_url="https://other.example.com/info",
            finding="AquaMembrane X raised $20M in Series B funding.",
        )
        f3 = self._sample_finding(
            source_url="https://other.example.com/info",
            finding="It is hypothesized that competitor Y could potentially acquire AquaMembrane X.",
        )
        f4 = self._sample_finding(
            source_url="https://notfound.example.com/404",
            finding="Uncollected source citation claim.",
        )

        results = correlate_findings_with_sources([f1, f2, f3, f4], [src_supported, src_unsupported])

        self.assertEqual(len(results), 4)
        self.assertEqual(results[0].raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)
        self.assertEqual(results[1].raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertEqual(results[2].raw_data["evidence_status"], EVIDENCE_STATUS_HYPOTHESIS)
        self.assertEqual(results[3].raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 13. Adversarial Negation Tests (NEG-01, NEG-02, NEG-03)
    def test_adversarial_negation_cases_prevent_supported(self) -> None:
        """Negated claims (not effective, failed to achieve, never safe) must be NEEDS_RESEARCH."""
        # NEG-01: effective vs not effective
        f_eff = self._sample_finding(
            finding="AquaMembrane X is highly effective at preventing membrane biofouling in RO filtration units.",
            evidence_summary="Clinical study evaluates membrane biofouling prevention.",
        )
        s_not_eff = self._sample_source(
            content="Independent clinical evaluations concluded that AquaMembrane X is not effective at preventing membrane biofouling in RO filtration units."
        )
        res_eff = correlate_finding_with_sources(f_eff, [s_not_eff])
        self.assertTrue(res_eff.raw_data["citation_verified"])
        self.assertEqual(res_eff.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)
        self.assertIsNone(res_eff.raw_data.get("supporting_passage"))

        # NEG-02: achieved vs failed to achieve
        f_ach = self._sample_finding(
            company_or_product="BioPure",
            source_url="https://bionews.example.com/reg",
            finding="BioPure achieved full regulatory approval for commercial wastewater treatment in Europe.",
        )
        s_fail_ach = self._sample_source(
            url="https://bionews.example.com/reg",
            source_type="news",
            publisher="bionews.example.com",
            content="European environmental authorities announced today that BioPure failed to achieve regulatory approval for commercial wastewater treatment in Europe."
        )
        res_ach = correlate_finding_with_sources(f_ach, [s_fail_ach])
        self.assertTrue(res_ach.raw_data["citation_verified"])
        self.assertEqual(res_ach.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # NEG-03: safe vs never safe
        f_safe = self._sample_finding(
            company_or_product="ChemWash",
            source_url="https://chemwash.example.com/safety",
            finding="ChemWash is safe for reverse osmosis filtration units in industrial plants.",
        )
        s_unsafe = self._sample_source(
            url="https://chemwash.example.com/safety",
            source_type="industry",
            publisher="chemwash.example.com",
            content="Laboratory investigations demonstrate that ChemWash is never safe for reverse osmosis filtration units in industrial plants."
        )
        res_safe = correlate_finding_with_sources(f_safe, [s_unsafe])
        self.assertTrue(res_safe.raw_data["citation_verified"])
        self.assertEqual(res_safe.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 14. Adversarial Contradiction Tests (CONTRA-01, CONTRA-02)
    def test_adversarial_contradiction_cases_prevent_supported(self) -> None:
        """Contradictory directional trends (increased vs decreased, expanded vs laid off) must be NEEDS_RESEARCH."""
        # CONTRA-01: increased vs decreased
        f_rev = self._sample_finding(
            company_or_product="SolarGrid",
            source_url="https://cleantech.example.com/earnings",
            finding="SolarGrid increased its quarterly revenue as commercial microgrid operations expanded.",
        )
        s_rev_dec = self._sample_source(
            url="https://cleantech.example.com/earnings",
            source_type="news",
            publisher="cleantech.example.com",
            content="In the latest earnings release, SolarGrid decreased its quarterly revenue as commercial microgrid operations contracted significantly."
        )
        res_rev = correlate_finding_with_sources(f_rev, [s_rev_dec])
        self.assertTrue(res_rev.raw_data["citation_verified"])
        self.assertEqual(res_rev.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # CONTRA-02: expanded workforce vs laid off
        f_work = self._sample_finding(
            company_or_product="Apex Energy",
            source_url="https://energydaily.example.com/apex",
            finding="Apex Energy expanded its engineering workforce with 500 new hires across battery storage facilities.",
        )
        s_layoff = self._sample_source(
            url="https://energydaily.example.com/apex",
            source_type="news",
            publisher="energydaily.example.com",
            content="Facing mounting debts, Apex Energy laid off 500 workers across its battery storage facilities."
        )
        res_work = correlate_finding_with_sources(f_work, [s_layoff])
        self.assertTrue(res_work.raw_data["citation_verified"])
        self.assertEqual(res_work.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 15. Adversarial Relationship Tests (REL-01, REL-02)
    def test_adversarial_relationship_cases_prevent_supported(self) -> None:
        """Disputed/rejected relationships (formed vs rejected, acquired vs terminated talks) must be NEEDS_RESEARCH."""
        # REL-01: formed vs rejected partnership
        f_part = self._sample_finding(
            company_or_product="Acme Corp",
            source_url="https://techdaily.example.com/deal",
            finding="Acme Corp formed a strategic partnership with MegaTech to deploy AI filtration solutions.",
        )
        s_rej = self._sample_source(
            url="https://techdaily.example.com/deal",
            source_type="news",
            publisher="techdaily.example.com",
            content="Spokespersons confirmed today that Acme Corp rejected a strategic partnership with MegaTech to deploy AI filtration solutions."
        )
        res_part = correlate_finding_with_sources(f_part, [s_rej])
        self.assertTrue(res_part.raw_data["citation_verified"])
        self.assertEqual(res_part.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # REL-02: acquired vs terminated acquisition talks
        f_acq = self._sample_finding(
            company_or_product="NanoClean",
            source_url="https://watertech.example.com/mna",
            finding="NanoClean acquired MembranePro to consolidate market share in industrial wastewater treatment.",
        )
        s_term = self._sample_source(
            url="https://watertech.example.com/mna",
            source_type="news",
            publisher="watertech.example.com",
            content="Regulatory filings reveal that NanoClean terminated acquisition talks with MembranePro regarding industrial wastewater treatment."
        )
        res_acq = correlate_finding_with_sources(f_acq, [s_term])
        self.assertTrue(res_acq.raw_data["citation_verified"])
        self.assertEqual(res_acq.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 16. Adversarial Numerical Discrepancy Tests (NUM-01, NUM-02, NUM-03)
    def test_adversarial_numerical_mismatches_prevent_supported(self) -> None:
        """Conflicting numbers (percentages, currency, counts) must be NEEDS_RESEARCH."""
        # NUM-01: 40% vs 14%
        f_pct = self._sample_finding(
            company_or_product="HydroTech",
            source_url="https://hydrotech.example.com/specs",
            finding="HydroTech achieved 40% energy efficiency gains in field desalination tests.",
        )
        s_pct = self._sample_source(
            url="https://hydrotech.example.com/specs",
            content="In recent testing, HydroTech achieved 14% energy efficiency gains in field desalination tests."
        )
        res_pct = correlate_finding_with_sources(f_pct, [s_pct])
        self.assertEqual(res_pct.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # NUM-02: $50M vs $5M
        f_curr = self._sample_finding(
            company_or_product="CleanWater",
            source_url="https://vcwire.example.com/cleanwater",
            finding="VentureCorp invested $50 million in CleanWater systems to scale municipal installations.",
        )
        s_curr = self._sample_source(
            url="https://vcwire.example.com/cleanwater",
            source_type="news",
            publisher="vcwire.example.com",
            content="VentureCorp invested $5 million in CleanWater systems to scale municipal installations."
        )
        res_curr = correlate_finding_with_sources(f_curr, [s_curr])
        self.assertEqual(res_curr.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # NUM-03: 50 installations vs 5 installations
        f_count = self._sample_finding(
            company_or_product="FilterPro",
            source_url="https://filterpro.example.com/deployments",
            finding="FilterPro has 50 active commercial installations across municipal wastewater utilities.",
        )
        s_count = self._sample_source(
            url="https://filterpro.example.com/deployments",
            content="Company records indicate FilterPro has 5 active commercial installations across municipal wastewater utilities."
        )
        res_count = correlate_finding_with_sources(f_count, [s_count])
        self.assertEqual(res_count.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 17. Adversarial Causation Tests (CAUSE-01, CAUSE-02)
    def test_adversarial_causation_cases_prevent_supported(self) -> None:
        """Causation asserted in finding but denied in source must be NEEDS_RESEARCH."""
        # CAUSE-01: treatment caused failure vs was not the cause
        f_cause = self._sample_finding(
            company_or_product="AquaMembrane",
            source_url="https://watertech.example.com/acid-wash",
            finding="Acid wash treatment caused irreversible membrane degradation in AquaMembrane units.",
        )
        s_no_cause = self._sample_source(
            url="https://watertech.example.com/acid-wash",
            source_type="industry",
            publisher="watertech.example.com",
            content="Acid wash treatment and irreversible membrane degradation occurred concurrently in AquaMembrane units, though extensive testing proved the acid wash was not the cause."
        )
        res_cause = correlate_finding_with_sources(f_cause, [s_no_cause])
        self.assertEqual(res_cause.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # CAUSE-02: crawlers caused savings vs wage cuts caused savings
        f_att = self._sample_finding(
            company_or_product="RoboDrain",
            source_url="https://infratech.example.com/crawlers",
            finding="RoboDrain automated crawlers directly caused a 30% reduction in pipe maintenance costs.",
        )
        s_att = self._sample_source(
            url="https://infratech.example.com/crawlers",
            source_type="news",
            publisher="infratech.example.com",
            content="While RoboDrain automated crawlers operated in the network, the 30% reduction in pipe maintenance costs was entirely caused by workforce wage cuts."
        )
        res_att = correlate_finding_with_sources(f_att, [s_att])
        self.assertEqual(res_att.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 18. Adversarial Misleading Keyword Overlap Tests (OVERLAP-01, OVERLAP-02, OVERLAP-03)
    def test_adversarial_keyword_overlap_cases_prevent_supported(self) -> None:
        """High lexical overlap with conflicting actions (acquired vs sued, secured vs lost, launched vs recalled) must be NEEDS_RESEARCH."""
        # OVERLAP-01: acquired vs sued
        f_sued = self._sample_finding(
            company_or_product="AquaMembrane",
            source_url="https://techlegal.example.com/dispute",
            finding="AquaMembrane acquired BioFilter for $50 million to expand its membrane technology.",
        )
        s_sued = self._sample_source(
            url="https://techlegal.example.com/dispute",
            source_type="news",
            publisher="techlegal.example.com",
            content="In a heated courtroom battle, AquaMembrane sued BioFilter for $50 million over patent infringement regarding membrane technology."
        )
        res_sued = correlate_finding_with_sources(f_sued, [s_sued])
        self.assertEqual(res_sued.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # OVERLAP-02: secured $10M vs lost $10M
        f_lost = self._sample_finding(
            company_or_product="SolarGrid",
            source_url="https://venturedesk.example.com/round",
            finding="SolarGrid secured $10 million in Series A funding to develop smart microgrids.",
        )
        s_lost = self._sample_source(
            url="https://venturedesk.example.com/round",
            source_type="news",
            publisher="venturedesk.example.com",
            content="Due to governance disputes, SolarGrid lost a $10 million in Series A funding to develop smart microgrids."
        )
        res_lost = correlate_finding_with_sources(f_lost, [s_lost])
        self.assertEqual(res_lost.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

        # OVERLAP-03: launched vs recalled
        f_rec = self._sample_finding(
            company_or_product="RoboDrain",
            source_url="https://robodrain.example.com/crawler",
            finding="RoboDrain launched autonomous pipe inspection crawlers across industrial municipal markets.",
        )
        s_rec = self._sample_source(
            url="https://robodrain.example.com/crawler",
            content="Following catastrophic electrical shorts, RoboDrain recalled autonomous pipe inspection crawlers across industrial municipal markets."
        )
        res_rec = correlate_finding_with_sources(f_rec, [s_rec])
        self.assertEqual(res_rec.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 19. Audit Genuine Support Cases (GENUINE-01, GENUINE-02, GENUINE-03)
    def test_audit_genuine_support_cases_are_supported(self) -> None:
        """Genuine corroborations must be SUPPORTED."""
        # GENUINE-01: quarterly chemical washes
        f1 = self._sample_finding(
            finding="AquaMembrane X requires quarterly chemical washes due to biofouling.",
        )
        s1 = self._sample_source(
            content="AquaMembrane X reverse osmosis technical specifications confirm filtration units require quarterly chemical washes to prevent biofouling in high-salinity applications."
        )
        res1 = correlate_finding_with_sources(f1, [s1])
        self.assertEqual(res1.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)
        self.assertIsNotNone(res1.raw_data.get("supporting_passage"))

        # GENUINE-02: $15M Series B funding
        f2 = self._sample_finding(
            company_or_product="CleanTech Systems",
            source_url="https://cleantech.example.com/series-b",
            finding="CleanTech Systems raised $15 million in Series B funding led by GreenFund.",
        )
        s2 = self._sample_source(
            url="https://cleantech.example.com/series-b",
            source_type="news",
            publisher="cleantech.example.com",
            content="GreenFund led a $15 million in Series B funding round for CleanTech Systems to accelerate industrial water commercialization."
        )
        res2 = correlate_finding_with_sources(f2, [s2])
        self.assertEqual(res2.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)

        # GENUINE-03: 99.5% salt rejection
        f3 = self._sample_finding(
            company_or_product="PermeaTech",
            source_url="https://permeatech.example.com/validation",
            finding="PermeaTech demonstrated 99.5% salt rejection in seawater reverse osmosis pilot trials.",
        )
        s3 = self._sample_source(
            url="https://permeatech.example.com/validation",
            content="Third-party testing demonstrated that PermeaTech demonstrated 99.5% salt rejection in seawater reverse osmosis pilot trials during 500 hours of continuous operation."
        )
        res3 = correlate_finding_with_sources(f3, [s3])
        self.assertEqual(res3.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)

    # 20. Audit Explicit Hypothesis Cases (HYPO-01, HYPO-02)
    def test_audit_explicit_hypothesis_cases_are_hypothesis(self) -> None:
        """Speculative findings without factual backing must be HYPOTHESIS."""
        # HYPO-01
        f1 = self._sample_finding(
            company_or_product="AquaMembrane",
            source_url="https://aquamembrane.example.com/about",
            finding="We hypothesize that AquaMembrane could potentially capture 30% of market share by 2028.",
        )
        s1 = self._sample_source(
            url="https://aquamembrane.example.com/about",
            content="AquaMembrane operates commercial facilities in North America and produces reverse osmosis filtration units for municipal customers."
        )
        res1 = correlate_finding_with_sources(f1, [s1])
        self.assertEqual(res1.raw_data["evidence_status"], EVIDENCE_STATUS_HYPOTHESIS)

        # HYPO-02
        f2 = self._sample_finding(
            company_or_product="SolarGrid",
            source_url="https://solargrid.example.com/profile",
            finding="It is conjectured that SolarGrid might potentially enter European microgrid markets next year.",
        )
        s2 = self._sample_source(
            url="https://solargrid.example.com/profile",
            source_type="news",
            publisher="solargrid.example.com",
            content="SolarGrid operates microgrids exclusively within the southwestern United States and maintains no foreign business units."
        )
        res2 = correlate_finding_with_sources(f2, [s2])
        self.assertEqual(res2.raw_data["evidence_status"], EVIDENCE_STATUS_HYPOTHESIS)

    # 21. Edge Case: Negation in an unrelated sentence does not disqualify supporting sentence
    def test_edge_case_negation_in_unrelated_sentence(self) -> None:
        """Negation in an unrelated sentence does not prevent supporting sentence from being SUPPORTED."""
        multi_sentence_content = (
            "AquaMembrane X technical specifications confirm reverse osmosis units require "
            "quarterly chemical washes to prevent biofouling in high-salinity applications. "
            "Competitor Beta is not effective at municipal wastewater treatment."
        )
        source = self._sample_source(content=multi_sentence_content)
        finding = self._sample_finding(
            finding="AquaMembrane X requires quarterly chemical washes due to biofouling."
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)
        self.assertIn("quarterly chemical washes", res.raw_data["supporting_passage"])

    # 22. Edge Case: Source discussing claim and its subsequent correction
    def test_edge_case_source_discussing_claim_and_correction(self) -> None:
        """When source explains a claim was initially made but subsequently proved incorrect, status is NEEDS_RESEARCH."""
        correction_content = (
            "AquaMembrane initially stated units required quarterly chemical washes, but subsequent "
            "field testing proved this was incorrect and washes are needed monthly."
        )
        source = self._sample_source(content=correction_content)
        finding = self._sample_finding(
            finding="AquaMembrane X requires quarterly chemical washes due to biofouling."
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 23. Edge Case: Different numbers with the same unit
    def test_edge_case_different_numbers_with_same_unit(self) -> None:
        """Conflicting numbers attached to the same unit/noun must produce NEEDS_RESEARCH."""
        source = self._sample_source(
            content="Company deployment metrics indicate FilterPro has been deployed across 5 municipal sites."
        )
        finding = self._sample_finding(
            company_or_product="FilterPro",
            finding="FilterPro has been deployed across 50 municipal sites.",
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 24. Edge Case: Similar words with different meanings (conducted vs criticized study)
    def test_edge_case_similar_words_different_meanings(self) -> None:
        """Contradicting role (conducted vs criticized study) must produce NEEDS_RESEARCH."""
        source = self._sample_source(
            content="AquaMembrane criticized a study on reverse osmosis membrane biofouling rates published by competitors."
        )
        finding = self._sample_finding(
            company_or_product="AquaMembrane",
            finding="AquaMembrane conducted a study on reverse osmosis membrane biofouling rates.",
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data["evidence_status"], EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 25. Edge Case: Genuinely supporting paraphrase without exact wording
    def test_edge_case_genuinely_supporting_paraphrase(self) -> None:
        """High lexical overlap with synonymous phrasing without contradiction produces SUPPORTED."""
        source = self._sample_source(
            content="AquaMembrane units require scheduled chemical cleaning to prevent biofouling on reverse osmosis filters."
        )
        finding = self._sample_finding(
            company_or_product="AquaMembrane",
            finding="AquaMembrane requires periodic chemical cleaning to prevent biofouling on reverse osmosis filters.",
            evidence_summary="Operational cleaning guidelines.",
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data["evidence_status"], EVIDENCE_STATUS_SUPPORTED)
        self.assertIsNotNone(res.raw_data.get("supporting_passage"))

    # 26. Reliability: Currency Normalization - Equivalent formats must compare as equal
    def test_currency_normalization_equivalent_formats_are_supported(self) -> None:
        """Equivalent currency formats compare as equal and produce SUPPORTED."""
        cases = [
            # $5M = $5 million
            ("$5M", "$5 million", "CleanWater", "https://news.example.com/cleanwater"),
            # $5B = $5 billion
            ("$5B", "$5 billion", "MegaWater", "https://news.example.com/megawater"),
            # $5K = $5 thousand
            ("$5K", "$5 thousand", "NanoFilter", "https://news.example.com/nanofilter"),
            # $5,000,000 = $5 million
            ("$5,000,000", "$5 million", "CleanWater", "https://news.example.com/cleanwater2"),
            # $1.5B = $1.5 billion
            ("$1.5B", "$1.5 billion", "GlobalMembrane", "https://news.example.com/globalmembrane"),
        ]
        for f_curr, s_curr, entity, url in cases:
            finding = self._sample_finding(
                company_or_product=entity,
                source_url=url,
                finding=f"VentureCorp invested {f_curr} in {entity} systems to scale municipal installations.",
                evidence_summary="Funding round confirmation.",
                raw_data={"ai_raw_output": {"finding": "round"}, "custom_meta": 123},
            )
            source = self._sample_source(
                url=url,
                publisher="news.example.com",
                content=f"VentureCorp invested {s_curr} in {entity} systems to scale municipal installations across the country.",
            )
            res = correlate_finding_with_sources(finding, [source])
            self.assertEqual(
                res.raw_data.get("evidence_status"),
                EVIDENCE_STATUS_SUPPORTED,
                f"Failed for {f_curr} vs {s_curr}",
            )
            self.assertTrue(res.raw_data.get("citation_verified"))
            self.assertEqual(res.raw_data.get("custom_meta"), 123)
            self.assertIsNotNone(res.raw_data.get("supporting_passage"))

    # 27. Reliability: Currency Normalization - Different magnitudes must be detected as conflicts
    def test_currency_normalization_different_magnitudes_are_needs_research(self) -> None:
        """Different currency magnitudes are detected as numerical conflicts producing NEEDS_RESEARCH."""
        conflict_cases = [
            # $5 million vs $5 billion
            ("$5 million", "$5 billion", "CleanWater", "https://news.example.com/cw1"),
            # $5 million vs $50 million
            ("$5 million", "$50 million", "CleanWater", "https://news.example.com/cw2"),
            # $1.5B vs $1.5M
            ("$1.5B", "$1.5M", "GlobalMembrane", "https://news.example.com/gm1"),
        ]
        for f_curr, s_curr, entity, url in conflict_cases:
            finding = self._sample_finding(
                company_or_product=entity,
                source_url=url,
                finding=f"VentureCorp invested {f_curr} in {entity} systems to scale municipal installations.",
                evidence_summary="Investment metrics.",
                raw_data={"ai_raw_output": {"finding": "round"}, "orig_key": "preserved"},
            )
            source = self._sample_source(
                url=url,
                publisher="news.example.com",
                content=f"VentureCorp invested {s_curr} in {entity} systems to scale municipal installations worldwide.",
            )
            res = correlate_finding_with_sources(finding, [source])
            self.assertEqual(
                res.raw_data.get("evidence_status"),
                EVIDENCE_STATUS_NEEDS_RESEARCH,
                f"Expected conflict for {f_curr} vs {s_curr}",
            )
            self.assertTrue(res.raw_data.get("citation_verified"))
            self.assertEqual(res.raw_data.get("orig_key"), "preserved")

    # 28. Reliability: Different units and unrelated numerical mentions do not conflict
    def test_unrelated_numerical_mentions_and_units_do_not_conflict(self) -> None:
        """Numerical mentions attached to unrelated nouns do not cause false conflict."""
        finding = self._sample_finding(
            company_or_product="FilterPro",
            source_url="https://filterpro.example.com/sites",
            finding="FilterPro has 5 municipal operational sites for wastewater filtration.",
            evidence_summary="Site deployment data.",
        )
        source = self._sample_source(
            url="https://filterpro.example.com/sites",
            content="FilterPro has 5 municipal operational sites for wastewater filtration while employing 50 engineers.",
        )
        res = correlate_finding_with_sources(finding, [source])
        self.assertEqual(res.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

    # 29. Reliability: Mixed-Event Contradiction Handling - Historical Launch vs Subsequent Recall
    def test_mixed_event_historical_launch_vs_subsequent_recall(self) -> None:
        """A historical launch claim remains SUPPORTED, but availability/non-recall claims are rejected."""
        source_url = "https://robodrain.example.com/news"
        mixed_source = self._sample_source(
            url=source_url,
            content=(
                "RoboDrain launched its autonomous pipe inspection crawlers across municipal utilities in March "
                "and recalled it in April due to hardware failures."
            ),
        )

        # 1. Pure historical launch claim remains SUPPORTED
        f_launch = self._sample_finding(
            company_or_product="RoboDrain",
            source_url=source_url,
            finding="RoboDrain launched its autonomous pipe inspection crawlers across municipal utilities.",
            evidence_summary="Historical product launch confirmation.",
            raw_data={"tracking_id": "launch-hist"},
        )
        res_launch = correlate_finding_with_sources(f_launch, [mixed_source])
        self.assertEqual(res_launch.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)
        self.assertTrue(res_launch.raw_data.get("citation_verified"))
        self.assertEqual(res_launch.raw_data.get("tracking_id"), "launch-hist")
        self.assertIsNotNone(res_launch.raw_data.get("supporting_passage"))

        # 2. Claim that product remains available / on the market is contradicted (NEEDS_RESEARCH)
        f_avail = self._sample_finding(
            company_or_product="RoboDrain",
            source_url=source_url,
            finding="RoboDrain crawlers remain available on the market across municipal utilities.",
            evidence_summary="Active market availability.",
        )
        res_avail = correlate_finding_with_sources(f_avail, [mixed_source])
        self.assertEqual(res_avail.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)

        # 3. Claim of unreversed successful status is contradicted (NEEDS_RESEARCH)
        f_unrev = self._sample_finding(
            company_or_product="RoboDrain",
            source_url=source_url,
            finding="RoboDrain maintains an unreversed successful status for deployed crawlers across municipal utilities.",
            evidence_summary="Operational track record.",
        )
        res_unrev = correlate_finding_with_sources(f_unrev, [mixed_source])
        self.assertEqual(res_unrev.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)

        # 4. Claim that product was never recalled is contradicted (NEEDS_RESEARCH)
        f_norecall = self._sample_finding(
            company_or_product="RoboDrain",
            source_url=source_url,
            finding="RoboDrain crawlers were never recalled across municipal utilities.",
            evidence_summary="Absence of product recalls.",
        )
        res_norecall = correlate_finding_with_sources(f_norecall, [mixed_source])
        self.assertEqual(res_norecall.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)

    # 30. Reliability: Subject-Scope Errors - Opposing Predicates on Distinct Entities
    def test_subject_scope_opposing_predicates(self) -> None:
        """Opposing predicates on distinct entities or competitors do not disqualify target entity."""
        url = "https://filtration.example.com/safety-review"

        # 1. Product A is safe, but Product B is unsafe -> SUPPORTED for Product A
        f1 = self._sample_finding(
            company_or_product="Product A",
            source_url=url,
            finding="Product A is safe for industrial reverse osmosis filtration units.",
            evidence_summary="Safety datasheet.",
            raw_data={"entity_check": "prod_a"},
        )
        s1 = self._sample_source(
            url=url,
            content="Product A is safe for industrial reverse osmosis filtration units, but Product B is unsafe.",
        )
        res1 = correlate_finding_with_sources(f1, [s1])
        self.assertEqual(res1.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)
        self.assertTrue(res1.raw_data.get("citation_verified"))
        self.assertEqual(res1.raw_data.get("entity_check"), "prod_a")
        self.assertIsNotNone(res1.raw_data.get("supporting_passage"))

        # 2. Product A is safe, but Product A's competitor is unsafe -> SUPPORTED for Product A
        f2 = self._sample_finding(
            company_or_product="Product A",
            source_url=url,
            finding="Product A is safe for industrial reverse osmosis filtration units.",
            evidence_summary="Safety analysis.",
        )
        s2 = self._sample_source(
            url=url,
            content="Product A is safe for industrial reverse osmosis filtration units, but Product A's competitor is unsafe.",
        )
        res2 = correlate_finding_with_sources(f2, [s2])
        self.assertEqual(res2.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

        # 3. Product A is safe, but Product B is not safe -> SUPPORTED for Product A
        f3 = self._sample_finding(
            company_or_product="Product A",
            source_url=url,
            finding="Product A is safe for industrial reverse osmosis filtration units.",
            evidence_summary="Safety evaluation.",
        )
        s3 = self._sample_source(
            url=url,
            content="Product A is safe for industrial reverse osmosis filtration units, but Product B is not safe.",
        )
        res3 = correlate_finding_with_sources(f3, [s3])
        self.assertEqual(res3.raw_data.get("evidence_status"), EVIDENCE_STATUS_SUPPORTED)

        # 4. Product A is safe, but Product A is not safe (same entity contradiction) -> NEEDS_RESEARCH
        f4 = self._sample_finding(
            company_or_product="Product A",
            source_url=url,
            finding="Product A is safe for industrial reverse osmosis filtration units.",
            evidence_summary="Safety report.",
        )
        s4 = self._sample_source(
            url=url,
            content="Product A is safe for industrial reverse osmosis filtration units, but Product A is not safe under pressure.",
        )
        res4 = correlate_finding_with_sources(f4, [s4])
        self.assertEqual(res4.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)

        # 5. Product A is safe vs Product A is not safe (direct denial) -> NEEDS_RESEARCH
        f5 = self._sample_finding(
            company_or_product="Product A",
            source_url=url,
            finding="Product A is safe for industrial reverse osmosis filtration units.",
        )
        s5 = self._sample_source(
            url=url,
            content="Testing proved that Product A is not safe for industrial reverse osmosis filtration units.",
        )
        res5 = correlate_finding_with_sources(f5, [s5])
        self.assertEqual(res5.raw_data.get("evidence_status"), EVIDENCE_STATUS_NEEDS_RESEARCH)
