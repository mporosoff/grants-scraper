"""P6.3 — the Army TDAC referenced source, and the router boundary around it.

Offline. The fixture is the live page as fetched on 2026-08-22; no test here reaches
the network.

The claim this file has to earn is narrow and was measured before it was built
(`docs/DOD_MEAS7_INSPECTION.md`): **one solicitation delegates its fundable topic
list to one stable external page, so those children are `referenced` and are
unreachable by any document parser.** Everything else — ONR, other DoD agencies, a
generic `army.mil` parser — is deliberately out of scope, and two tests pin that.
"""

from datetime import date
import pathlib
import unittest

from scripts import subtopic_records, subtopic_referenced as ref

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "army_tdac" / "topics.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
AS_OF = "2026-08-22"

PARENT = {
    "opportunity_id": "345241",
    "opportunity_number": "W911NF-23-S-0003",
    "title": "DEVCOM ANALYSIS CENTER BROAD AGENCY ANNOUNCEMENT FOR APPLIED RESEARCH",
    "agency": "Dept of the Army -- Materiel Command",
    "status": "posted",
    "close_date": "2028-01-04",
}


def fetch_ok(_url):
    return PAGE


def fetch_boom(_url):
    raise ConnectionError("simulated transport failure")


class ParseTests(unittest.TestCase):
    """1 and 2: the measured page yields 14 unique children, deduped by id."""

    def setUp(self):
        self.topics = ref.parse_army_tdac(PAGE)

    def test_the_measured_page_yields_fourteen_topics(self):
        self.assertEqual(len(self.topics), 14)

    def test_duplicated_markup_still_yields_fourteen(self):
        """The page prints a 13-topic index and then 14 full entries."""
        self.assertEqual(PAGE.count("<p><strong>Title:"), 27)
        self.assertEqual(len({t["announcement_id_norm"] for t in self.topics}), 14)

    def test_dedup_keeps_the_richer_block_not_the_index_stub(self):
        """Dedup is by Announcement ID, and the entry with the description wins."""
        first = self.topics[0]
        self.assertEqual(first["announcement_id"], "TDAC BAA-001")
        self.assertGreater(first["block_length"], 2000)

    def test_every_topic_carries_a_parseable_announcement_id(self):
        for topic in self.topics:
            self.assertRegex(topic["announcement_id"], r"^TDAC BAA-\d+$")
            self.assertTrue(topic["announcement_id_norm"])

    def test_titles_and_tpocs_are_captured(self):
        titles = {t["title"] for t in self.topics}
        self.assertIn("Personnel Survivability", titles)
        self.assertIn("Humans in Multi-Agent Systems", titles)
        self.assertTrue(all(t["tpoc"] for t in self.topics))

    def test_same_title_different_announcement_id_stays_distinct(self):
        """3: the source's own identity wins; titles are never the key."""
        html = (
            "<p>W911NF-23-S-0003</p>"
            "<p><strong>Title: Identical Topic Name</strong></p>"
            "<p><strong>Announcement ID: </strong>TDAC BAA-101</p>"
            "<p><strong>TPOC: </strong>a@army.mil</p>"
            "<p><strong>Title: Identical Topic Name</strong></p>"
            "<p><strong>Announcement ID: </strong>TDAC BAA-102</p>"
            "<p><strong>TPOC: </strong>b@army.mil</p>"
        )
        topics = ref.parse_army_tdac(html)
        self.assertEqual(len(topics), 2)
        self.assertEqual(
            {t["announcement_id"] for t in topics}, {"TDAC BAA-101", "TDAC BAA-102"}
        )


class ApplicabilityTests(unittest.TestCase):
    """11: the source answers for one parent and stays silent for everything else."""

    def test_the_measured_parent_matches_in_any_punctuation(self):
        self.assertTrue(ref.applies_to({"opportunity_number": "W911NF-23-S-0003"}))
        self.assertTrue(ref.applies_to({"opportunity_number": "w911nf23s0003"}))

    def test_an_unrelated_dod_parent_does_not_trigger_the_source(self):
        for number in ("N0001425SB001", "W911NF-23-S-0001", "HR001126S0016",
                       "FA238424S2334", None, ""):
            with self.subTest(number=number):
                result, document, diagnostics = ref.first_refusal(
                    {"opportunity_number": number}, fetch=fetch_ok
                )
                self.assertIsNone(result)
                self.assertIsNone(document)
                self.assertEqual(diagnostics["reason"], "not_applicable")

    def test_declining_costs_no_fetch(self):
        calls = []
        ref.first_refusal(
            {"opportunity_number": "N0001425SB001"},
            fetch=lambda url: calls.append(url) or PAGE,
        )
        self.assertEqual(calls, [])


class HealthTests(unittest.TestCase):
    """4, 5, 6: every unhealthy shape declines rather than publishing zero."""

    def test_the_measured_page_is_healthy(self):
        health = ref.check_health(PAGE, ref.parse_army_tdac(PAGE))
        self.assertTrue(health["healthy"], health["failures"])
        self.assertEqual(health["topics"], 14)

    def test_a_page_that_stops_naming_the_baa_declines(self):
        html = PAGE.replace("W911NF-23-S-0003", "W911NF-99-S-9999")
        topics = ref.parse_army_tdac(html)
        health = ref.check_health(html, topics)
        self.assertFalse(health["healthy"])
        self.assertTrue(any("parent assertion" in f for f in health["failures"]))
        result, _document, diagnostics = ref.first_refusal(
            PARENT, fetch=lambda _u: html
        )
        self.assertIsNone(result)
        self.assertEqual(diagnostics["reason"], "unhealthy_declined")

    def test_http_200_with_zero_topics_declines(self):
        html = "<html><body><p>W911NF-23-S-0003</p><p>ok</p></body></html>"
        result, _document, diagnostics = ref.first_refusal(
            PARENT, fetch=lambda _u: html
        )
        self.assertIsNone(result)
        self.assertEqual(diagnostics["health"]["topics"], 0)
        self.assertTrue(any("topic floor" in f
                            for f in diagnostics["health"]["failures"]))

    def test_catastrophic_shrinkage_declines(self):
        """Two topics is not an Army retiring a few; it is a broken parse."""
        html = (
            "<p>W911NF-23-S-0003</p>"
            "<p><strong>Title: One</strong></p>"
            "<p><strong>Announcement ID: </strong>TDAC BAA-001</p>"
            "<p><strong>Title: Two</strong></p>"
            "<p><strong>Announcement ID: </strong>TDAC BAA-002</p>"
        )
        result, _document, diagnostics = ref.first_refusal(
            PARENT, fetch=lambda _u: html
        )
        self.assertIsNone(result)
        self.assertFalse(diagnostics["health"]["healthy"])

    def test_a_transport_failure_is_reported_not_raised(self):
        """§17.11: a failed fetch is a fact about the fetch path."""
        result, document, diagnostics = ref.first_refusal(PARENT, fetch=fetch_boom)
        self.assertIsNone(result)
        self.assertIsNone(document)
        self.assertEqual(diagnostics["reason"], "fetch_failed_ConnectionError")
        self.assertFalse(diagnostics["healthy"])


class FundabilityBoundaryTests(unittest.TestCase):
    """7: only the measured Title + Announcement ID structure is ingested."""

    def setUp(self):
        self.topics = ref.parse_army_tdac(PAGE)
        self.titles = {t["title"] for t in self.topics}

    def test_navigation_and_headings_are_not_topics(self):
        for junk in ("TOP STORIES", "Social Sharing", "TDAC BAA Research Topics",
                     "Army.mil", "Home"):
            self.assertNotIn(junk, self.titles)

    def test_tpoc_names_and_emails_are_never_children(self):
        for title in self.titles:
            self.assertNotIn("@", title)
        self.assertNotIn("TDACBAA@army.mil", self.titles)

    def test_a_block_without_an_announcement_id_is_not_a_topic(self):
        html = (
            "<p>W911NF-23-S-0003</p>"
            "<p><strong>Title: Army Research Laboratory</strong></p>"
            "<p>Some organizational blurb with no announcement id at all.</p>"
        )
        self.assertEqual(ref.parse_army_tdac(html), [])


class ProvenanceTests(unittest.TestCase):
    """8: `referenced`, never `native`, and method stays orthogonal."""

    def setUp(self):
        self.result, self.document, _d = ref.first_refusal(PARENT, fetch=fetch_ok)
        self.records = subtopic_records.build_records(
            PARENT, self.result, document=self.document, as_of=AS_OF,
            provenance=subtopic_records.REFERENCED,
        )

    def test_fourteen_referenced_children_are_built(self):
        self.assertEqual(len(self.records), 14)

    def test_every_child_is_referenced_and_none_is_native(self):
        for record in self.records:
            self.assertEqual(record["subtopic_source"], subtopic_records.REFERENCED)
            self.assertNotEqual(record["subtopic_source"], subtopic_records.NATIVE)

    def test_no_segmentation_method_or_pattern_family_is_claimed(self):
        """Nothing inferred these, so neither field may name a mechanism."""
        for record in self.records:
            self.assertIsNone(record["segmentation_method"])
            self.assertIsNone(record["pattern_family"])

    def test_the_evidence_anchor_is_the_source_url_and_pages_are_absent(self):
        """§6.7's `inline` vs `referenced` field table, in code."""
        for record in self.records:
            self.assertEqual(record["evidence_anchor"], ref.ARMY_TDAC_TOPICS_URL)
            self.assertIsNone(record["page_start"])
            self.assertIsNone(record["page_end"])
            self.assertEqual(record["source_document_url"], ref.ARMY_TDAC_TOPICS_URL)

    def test_child_identity_is_the_announcement_id_scoped_to_the_parent(self):
        ids = [record["subtopic_id"] for record in self.records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("345241:tdac-baa-001", ids)
        for record in self.records:
            self.assertEqual(record["parent_opportunity_number"], "W911NF-23-S-0003")
            self.assertEqual(record["parent_id"], "345241")

    def test_confidence_respects_the_referenced_ceiling(self):
        for record in self.records:
            self.assertEqual(record["confidence"], "high")

    def test_children_carry_a_term_map_so_they_are_retrievable(self):
        for record in self.records:
            self.assertTrue(record["subtopic_terms"])


class RouterBoundaryTests(unittest.TestCase):
    """9 and 10: first refusal, and what declining must never cost."""

    def test_generic_segmentation_is_not_invoked_when_the_source_answers(self):
        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources

        calls = []
        original = subtopic_sources.best_segmentation
        subtopic_sources.best_segmentation = lambda *a, **k: calls.append(a) or None
        original_fetch = ede.referenced_fetch
        ede.referenced_fetch = fetch_ok
        try:
            fields = ede.subtopic_fields(
                PARENT, b"", [], {"url": "https://example.org/notice.pdf"},
                f"{AS_OF}T00:00:00Z", True,
            )
        finally:
            subtopic_sources.best_segmentation = original
            ede.referenced_fetch = original_fetch

        self.assertEqual(calls, [], "generic segmentation must not run")
        self.assertEqual(len(fields["subtopics"]), 14)
        self.assertIsNone(fields["subtopic_method"])
        self.assertEqual(
            fields["subtopic_referenced"]["reason"], "answered"
        )
        for record in fields["subtopics"]:
            self.assertEqual(record["subtopic_source"], subtopic_records.REFERENCED)

    def test_an_unhealthy_referenced_source_falls_through_to_generic(self):
        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources
        from scripts.subtopic_segmentation import SegmentationResult

        calls = []
        sentinel = SegmentationResult.empty("fallback_ran")
        original = subtopic_sources.best_segmentation
        subtopic_sources.best_segmentation = (
            lambda *a, **k: calls.append(a) or (sentinel, None, {"attempts": ()})
        )
        original_fetch = ede.referenced_fetch
        ede.referenced_fetch = lambda _u: "<html><body>W911NF-23-S-0003</body></html>"
        try:
            fields = ede.subtopic_fields(
                PARENT, b"", [], {"url": "https://example.org/notice.pdf"},
                f"{AS_OF}T00:00:00Z", True,
            )
        finally:
            subtopic_sources.best_segmentation = original
            ede.referenced_fetch = original_fetch

        self.assertEqual(len(calls), 1, "fallback must run when the source declines")
        self.assertEqual(fields["subtopics"], [])
        self.assertEqual(fields["subtopic_reason"], "fallback_ran")

    def test_the_flag_off_path_adds_nothing_at_all(self):
        """§0.5: with the flag off the entry literal is untouched."""
        from scripts import extract_document_evidence as ede

        self.assertEqual(
            ede.subtopic_fields(PARENT, b"", [], {}, f"{AS_OF}T00:00:00Z", False), {}
        )


class UnchangedNeighboursTests(unittest.TestCase):
    """12: P6.1 and P8 behaviour is not touched by any of this."""

    def test_the_nasa_adapter_still_emits_nothing_without_catalog_context(self):
        from scripts.sources.adapters.nasa_roses import NasaRosesAdapter

        instance = NasaRosesAdapter()
        payload = {
            "year": 2025,
            "table3_html": (pathlib.Path(__file__).parent / "fixtures" / "roses"
                            / "table3.html").read_text(encoding="utf-8"),
            "table2_html": None,
            "amendment": 69,
        }
        self.assertEqual(list(instance.parse(payload)), [])

    def test_the_nasa_adapter_is_still_an_enabled_catalog_source(self):
        from scripts.sources.adapters.nasa_roses import NasaRosesAdapter

        self.assertTrue(NasaRosesAdapter.enabled)
        self.assertEqual(NasaRosesAdapter.min_records, 0)

    def test_the_provenance_ladder_default_is_still_inferred(self):
        self.assertEqual(
            subtopic_records.classify_provenance(object()), subtopic_records.INFERRED
        )

    def test_referenced_children_would_still_be_rechecked_when_cov4_lands(self):
        """The forward obligation, kept visible rather than assumed discharged.

        Cov4 does not exist yet, so `referenced` bypasses a classifier that is not
        there. When Cov4 lands, its call site must be gated on provenance and this
        test's docstring is the pointer to re-check it (§18.1 Cov4, P6.3.3).
        """
        self.assertEqual(
            subtopic_records.PROVENANCE_CEILING[subtopic_records.REFERENCED], "high"
        )
        self.assertEqual(
            subtopic_records.PROVENANCE_CEILING[subtopic_records.INFERRED], "medium"
        )


if __name__ == "__main__":
    unittest.main()
