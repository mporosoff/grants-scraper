"""Cov6 -- publication semantics, and `_demote()` narrowed to its measured risk.

Offline. Two things are settled here and they are separable:

1. **The three concepts are three concepts.** Provenance says who asserted the
   relationship; confidence says how well this run read it; the `cov4_*` fields
   say what the gate decided; and publication eligibility is *derived from all
   three* by `subtopic_records.publication_eligibility` and stored nowhere. The
   `medium -> queued` reading and the §5.1 `inferred -> medium` ceiling are not
   in conflict once those are kept apart: a generic child does not auto-publish,
   by design, and Cov4's job is to shrink and clean the review queue rather than
   to open a publication path.
2. **`_demote()` keeps its measured protection and loses its overreach.** It
   demotes when the winning document is secondary to the record's own
   announcement, and no longer when the record simply has no announcement for it
   to be secondary to.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts import subtopic_cov4 as cov4          # noqa: E402
from scripts import subtopic_records as records    # noqa: E402
from scripts import subtopic_sources as sources    # noqa: E402
from scripts.subtopic_segmentation import (        # noqa: E402
    SegmentationResult, Subtopic,
)

AS_OF = "2026-08-27"
DOC_HASH = "c" * 64


def span(code="Topic Area 1", title="Topic Area 1: Electrocatalysis", ordinal=1):
    summary = "Applications are sought for electrocatalysis research."
    return Subtopic(
        subtopic_code=code, subtopic_code_norm=code.casefold().replace(" ", "-"),
        subtopic_ordinal=ordinal, ordinal_label="numeric", title=title,
        title_fingerprint=title.casefold(), summary=summary,
        subtopic_terms={"electrocatalysis": 1}, page_start=4, page_end=5,
        anchor="p4", char_start=0, char_end=len(summary),
        program_area_labels=(), topic_areas=(), own_deadline=None,
    )


def parent():
    return {"opportunity_id": "363526", "opportunity_number": "NOFOAFRLAFOSR20260004",
            "title": "FY26 DEPSCoR Research Collaboration", "status": "posted"}


def document(kind="primary_notice", url="https://example.gov/notice.pdf"):
    return {"url": url, "name": "notice.pdf", "sha256": DOC_HASH,
            "source_kind": kind}


def built(confidence="high", provenance=None, doc=None):
    return records.build_records(
        parent(),
        SegmentationResult(subtopics=(span(),), method="toc",
                           confidence=confidence, family="topic_area"),
        document=doc or document(), as_of=AS_OF, provenance=provenance,
    )


def gated(fundability=cov4.ACCEPT, owned=True, doc=None, provenance=None,
          confidence="high"):
    """One record driven through the real Cov4 gate with a stub classifier."""
    doc = doc or document()

    def classifier(candidate, *, api_key=None, session=None):
        return {"fundability": fundability, "classifier_owned": owned,
                "reason": "stub", "error": None, "detail": None}

    kept, diagnostics = cov4.apply_gate(
        parent(), built(confidence=confidence, provenance=provenance, doc=doc),
        doc, classifier=classifier)
    return kept, diagnostics


# --- 1. the restated Cov4 constants cannot drift ----------------------------

class ConstantFidelityTests(unittest.TestCase):
    """`subtopic_records` restates them because importing back would cycle."""

    def test_the_judged_provenance_set_matches_cov4s(self):
        self.assertEqual(
            records._COV4_JUDGED_PROVENANCE, cov4.CLASSIFIED_PROVENANCE
        )

    def test_the_verdict_values_match_cov4s(self):
        self.assertEqual(records._COV4_OWNED, cov4.OWNED)
        self.assertEqual(records._COV4_ACCEPT, cov4.ACCEPT)

    def test_importing_records_does_not_import_cov4(self):
        """The one-way dependency the restatement exists to preserve."""
        source = (pathlib.Path(__file__).parents[1] / "scripts"
                  / "subtopic_records.py").read_text(encoding="utf-8")
        self.assertNotIn("import subtopic_cov4", source)
        self.assertNotIn("from scripts.subtopic_cov4", source)


# --- 2. the three concepts, kept apart --------------------------------------

class SeparationOfConcernsTests(unittest.TestCase):

    def test_confidence_is_not_a_permission(self):
        """A `medium` generic child is well-read and still does not publish."""
        record = dict(gated()[0][0])                  # capped to medium by §5.1
        self.assertEqual(record["subtopic_source"], records.INFERRED)
        self.assertEqual(record["confidence"], "medium")
        state, reason = records.publication_eligibility(record)
        self.assertEqual(state, records.REVIEW)
        self.assertEqual(reason, "tier_medium")

    def test_an_inferred_record_that_never_met_cov4_fails_closed(self):
        """A record built outside the gate carries no verdict, so it has none.

        This is the shape of anything cached before Cov4 existed, and of any
        future caller that forgets the gate. It must queue, not publish.
        """
        record = built(confidence="high")[0]
        self.assertNotIn("cov4_ownership", record)
        state, reason = records.publication_eligibility(record)
        self.assertEqual(state, records.REVIEW)
        self.assertEqual(reason, "cov4_ownership_None")

    def test_provenance_is_not_a_permission_either(self):
        """A `high` rung with a weak read stays weak; §5.1 is a ceiling."""
        record = records.build_records(
            parent(),
            SegmentationResult(subtopics=(span(),), method="numbered",
                               confidence="low", family="topic_area"),
            document=document(), as_of=AS_OF, provenance=records.REFERENCED,
        )[0]
        self.assertEqual(record["subtopic_source"], records.REFERENCED)
        self.assertEqual(record["confidence"], "low")
        self.assertFalse(records.is_publishable(record))

    def test_cov4_review_state_lives_in_its_own_fields(self):
        kept, _d = gated(fundability=cov4.UNRESOLVED)
        record = kept[0]
        self.assertTrue(record["cov4_review"])
        self.assertEqual(record["cov4_fundability"], cov4.UNRESOLVED)
        # The evidence tier is untouched -- that is the Cov6 change.
        self.assertEqual(record["confidence"], "medium")
        self.assertFalse(records.is_publishable(record))

    def test_publication_eligibility_is_derived_and_never_stored(self):
        kept, _d = gated()
        self.assertNotIn("publication_state", kept[0])
        self.assertNotIn("publishable", kept[0])
        self.assertEqual(
            records.publication_eligibility(kept[0])[0], records.REVIEW
        )


# --- 3. §7.1's rule, exactly ------------------------------------------------

class PublicationRuleTests(unittest.TestCase):
    """`high` publishes; `medium`/`low` publish only on a hash-matched approval."""

    def approved(self, record, sha=DOC_HASH, status="approve"):
        return {record["subtopic_id"]: {"status": status,
                                        "document_sha256": sha}}

    def test_a_high_confidence_referenced_child_publishes_unattended(self):
        record = records.build_records(
            parent(),
            SegmentationResult(subtopics=(span(),), method=None,
                               confidence="high", family=None),
            document=document(), as_of=AS_OF, provenance=records.REFERENCED,
        )[0]
        state, reason = records.publication_eligibility(record)
        self.assertEqual(state, records.PUBLISHABLE)
        self.assertEqual(reason, "high_confidence")

    def test_a_cov4_approved_inferred_child_follows_the_rule_and_queues(self):
        """The answer to 'how can an inferred child ever publish': by approval."""
        kept, diagnostics = gated()
        record = kept[0]
        self.assertEqual(diagnostics["published"], 1)     # Cov4-approved
        self.assertEqual(record["cov4_ownership"], cov4.OWNED)
        self.assertEqual(record["cov4_fundability"], cov4.ACCEPT)
        self.assertFalse(records.is_publishable(record))  # ...still queued
        self.assertTrue(
            records.is_publishable(record, approvals=self.approved(record))
        )

    def test_an_approval_against_a_different_document_is_stale(self):
        kept, _d = gated()
        record = kept[0]
        state, reason = records.publication_eligibility(
            record, approvals=self.approved(record, sha="d" * 64))
        self.assertEqual(state, records.REVIEW)
        self.assertEqual(reason, "approval_stale")

    def test_a_rejecting_label_is_not_an_approval(self):
        kept, _d = gated()
        record = kept[0]
        for status in ("reject", "could_not_verify"):
            state, reason = records.publication_eligibility(
                record, approvals=self.approved(record, status=status))
            self.assertEqual(state, records.REVIEW, status)
            self.assertEqual(reason, "approval_not_granted", status)

    def test_an_approval_cannot_override_a_failed_cov4_axis(self):
        """Fail-closed outranks a human label; the axes are checked first."""
        kept, _d = gated(fundability=cov4.UNRESOLVED)
        record = kept[0]
        self.assertFalse(
            records.is_publishable(record, approvals=self.approved(record))
        )


# --- 4. fail-closed, through the publication predicate ----------------------

class FailClosedTests(unittest.TestCase):

    def test_a_cov4_rejected_candidate_never_reaches_the_predicate(self):
        kept, diagnostics = gated(fundability=cov4.REJECT)
        self.assertEqual(kept, [])
        self.assertEqual(diagnostics["dropped"], 1)

    def test_a_not_owned_candidate_never_reaches_the_predicate(self):
        doc = document(kind="subtopic_agency_notice",
                       url="https://netl-exchange.energy.gov/Default.aspx")
        result = records.build_records(
            parent(),
            SegmentationResult(
                subtopics=(span(title="Topic Area 1 under DE-FOA-0003627"),),
                method="numbered", confidence="medium", family="topic_area"),
            document=doc, as_of=AS_OF)

        def classifier(candidate, *, api_key=None, session=None):
            return {"fundability": cov4.ACCEPT, "classifier_owned": True,
                    "reason": "stub", "error": None, "detail": None}

        kept, diagnostics = cov4.apply_gate(
            parent(), result, doc, classifier=classifier)
        self.assertEqual(kept, [])
        self.assertEqual(diagnostics["ownership"], {cov4.NOT_OWNED: 1})

    def test_an_unestablished_candidate_is_kept_and_cannot_publish(self):
        doc = document(kind="subtopic_agency_notice",
                       url="https://agency.example/programs")
        kept, diagnostics = gated(doc=doc)
        self.assertEqual(diagnostics["review"], 1)
        record = kept[0]
        state, reason = records.publication_eligibility(record)
        self.assertEqual(state, records.REVIEW)
        self.assertEqual(reason, "cov4_ownership_unestablished")

    def test_every_classifier_failure_mode_is_unpublishable(self):
        for error in ("missing_credential", "request_failed", "http_error",
                      "malformed_response", "unparseable_response",
                      "unexpected_enum"):
            def failing(candidate, *, api_key=None, session=None, _e=error):
                return cov4._unresolved(_e)

            kept, _d = cov4.apply_gate(
                parent(), built(), document(), classifier=failing)
            state, reason = records.publication_eligibility(kept[0])
            self.assertEqual(state, records.REVIEW, error)
            self.assertEqual(reason, "cov4_fundability_unresolved", error)

    def test_an_unresolved_inline_span_cannot_publish_at_its_high_ceiling(self):
        """The hole the old `demote to low` closed by accident, closed on purpose.

        `inline`'s §5.1 ceiling is `high`, so a publication rule that read only
        the tier would publish a span whose classifier call failed.
        """
        kept, _d = gated(fundability=cov4.UNRESOLVED,
                         provenance=records.INLINE, confidence="high")
        record = kept[0]
        self.assertEqual(record["subtopic_source"], records.INLINE)
        self.assertEqual(record["confidence"], "high")       # ceiling allows it
        self.assertFalse(records.is_publishable(record))     # the gate does not

    def test_a_classifier_outage_publishes_nothing_new(self):
        def failing(candidate, *, api_key=None, session=None):
            return cov4._unresolved("request_failed", detail="SSLError")

        kept, diagnostics = cov4.apply_gate(
            parent(), built(), document(), classifier=failing)
        self.assertEqual(diagnostics["published"], 0)
        self.assertEqual(
            [r for r in kept if records.is_publishable(r)], []
        )


# --- 5. `_demote()` --------------------------------------------------------

class DemoteScopeTests(unittest.TestCase):
    """The narrowing, stated against the two populations that decide it."""

    def result(self, confidence="high"):
        return SegmentationResult(subtopics=(span(),), method="toc",
                                  confidence=confidence, family="topic_area")

    def test_a_record_with_no_announcement_has_nothing_to_be_secondary_to(self):
        """§18.1 Cov6's case: `363526`, reached only through its attachments."""
        self.assertIsNone(sources._announcement_url({"opportunity_id": "363526"},
                                                    None))
        kept = sources._demote(self.result(), document(), None)
        self.assertEqual(kept.confidence, "high")

    def test_a_designated_announcement_makes_another_file_secondary(self):
        """CDC `360339`'s shape: a primary exists and the list came elsewhere."""
        record = {"opportunity_id": "360339",
                  "primary_document_url": "https://example.gov/notice.pdf"}
        announcement = sources._announcement_url(record, None)
        self.assertEqual(announcement, "https://example.gov/notice.pdf")
        demoted = sources._demote(
            self.result(), document(url="https://example.gov/indicators.pdf"),
            announcement)
        self.assertEqual(demoted.confidence, "low")

    def test_the_announcement_itself_is_never_secondary_to_itself(self):
        record = {"primary_document_url": "https://example.gov/notice.pdf"}
        announcement = sources._announcement_url(record, None)
        kept = sources._demote(self.result(), document(), announcement)
        self.assertEqual(kept.confidence, "high")

    def test_a_supplied_primary_identifies_the_announcement_when_the_record_does_not(self):
        """Preserves the pre-Cov6 behaviour for every ordinarily-reached record."""
        announcement = sources._announcement_url(
            {"opportunity_id": "1001"}, {"url": "https://example.gov/notice.pdf"})
        self.assertEqual(announcement, "https://example.gov/notice.pdf")
        demoted = sources._demote(
            self.result(), document(url="https://example.gov/appendix.pdf"),
            announcement)
        self.assertEqual(demoted.confidence, "low")

    def test_a_record_url_outranks_a_supplied_document(self):
        announcement = sources._announcement_url(
            {"primary_document_url": "https://example.gov/designated.pdf"},
            {"url": "https://example.gov/supplied.pdf"})
        self.assertEqual(announcement, "https://example.gov/designated.pdf")

    def test_an_already_low_result_is_left_alone(self):
        unchanged = sources._demote(self.result("low"), document(), "https://x")
        self.assertEqual(unchanged.confidence, "low")

    def test_an_empty_result_is_left_alone(self):
        empty = SegmentationResult.empty("no_layer_accepted")
        self.assertIs(sources._demote(empty, document(), "https://x"), empty)


class DemoteThroughBestSegmentationTests(unittest.TestCase):
    """The two regression cases §18.1 Cov6 requires, end to end."""

    def setUp(self):
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from fixtures.minipdf import build_pdf, heading, line
        from scripts.extract_document_evidence import extract_containers

        self.extract_containers = extract_containers

        def body(subject):
            return (f"This element supports fundamental studies of {subject}, "
                    f"including operando characterization and reactor design "
                    f"relevant to {subject}. Awards support single investigators "
                    f"and small teams pursuing {subject} at laboratory scale.")

        topics = ["Topic Area 1 Electrocatalysis",
                  "Topic Area 2 Membrane Separations",
                  "Topic Area 3 Materials Discovery"]
        pages = [[heading("Overview"), line("Program announcement overview.")]]
        for text in topics:
            pages.append([heading(text), line(body(text))])
        self.notice = build_pdf(
            pages, outline=[(t, i + 1, 0) for i, t in enumerate(topics)])
        self.bland = build_pdf([
            [heading("I. OVERVIEW INFORMATION"), line(body("administration"))],
            [heading("II. BASIC INFORMATION"), line(body("submission"))],
        ])

    def run_case(self, record, primary_content, primary_document, names, blobs):
        def download(url, headers=None):
            name = url.rsplit("/", 1)[-1]
            if name not in blobs:
                raise RuntimeError(name)
            return {"content": blobs[name], "content_type": "application/pdf",
                    "url": url}

        return sources.best_segmentation(
            record, primary_content, primary_document,
            extract_containers=self.extract_containers,
            download=download,
            detail_fetcher=lambda _oid: {"data": {"n": names}},
            collector=lambda data: [
                {"download_url": f"https://example.gov/{n}", "file_name": n,
                 "id": str(i)} for i, n in enumerate(data["n"])],
        )

    def test_a_previously_demoted_own_announcement_keeps_its_tier(self):
        """`363526`: no primary, so its own attachment is not a secondary."""
        result, chosen, _d = self.run_case(
            {"opportunity_id": "363526"}, None, None,
            ["NOFOAFRLAFOSR20260004 DEPSCoR-RC.pdf"],
            {"NOFOAFRLAFOSR20260004 DEPSCoR-RC.pdf": self.notice},
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(result.confidence, "high")
        record = records.build_records(
            parent(), result, document=chosen, as_of=AS_OF)[0]
        self.assertEqual(record["subtopic_source"], records.INFERRED)
        self.assertEqual(record["confidence"], "medium")   # §5.1, not `low`
        self.assertFalse(records.is_publishable(record))   # still not published

    def test_a_genuine_secondary_still_demotes_and_still_fails_closed(self):
        """The measured risk survives the narrowing untouched."""
        result, chosen, _d = self.run_case(
            {"opportunity_id": "360339",
             "primary_document_url": "https://example.gov/notice.pdf"},
            self.bland,
            {"url": "https://example.gov/notice.pdf", "name": "notice.pdf",
             "content_type": "application/pdf"},
            ["indicators.pdf"], {"indicators.pdf": self.notice},
        )
        self.assertEqual(len(result.subtopics), 3)
        self.assertEqual(result.confidence, "low")
        record = records.build_records(
            parent(), result, document=chosen, as_of=AS_OF)[0]
        self.assertEqual(record["confidence"], "low")
        self.assertFalse(records.is_publishable(record))

    def test_ranking_by_quality_is_restored_for_no_primary_records(self):
        """Flattening every candidate to `low` made span count the only tiebreak.

        The weak document yields more spans; the strong one must still win.
        """
        from fixtures.minipdf import build_pdf, heading, line

        many = build_pdf([[heading(f"{n}. Indicator {n}"),
                           line("Reporting category for programme monitoring "
                                "and evaluation across the award period.")]
                          for n in range(1, 8)])
        result, chosen, _d = self.run_case(
            {"opportunity_id": "363526"}, None, None,
            ["indicators.pdf", "announcement.pdf"],
            {"indicators.pdf": many, "announcement.pdf": self.notice},
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(chosen["name"], "announcement.pdf")
        self.assertEqual(len(result.subtopics), 3)


# --- 6. the neighbours Cov6 must not touch ---------------------------------

class UnchangedNeighboursTests(unittest.TestCase):

    def test_nasa_native_children_are_untouched_by_the_predicate_path(self):
        from tests.test_nasa_roses_provenance import adapter, roses_rows

        rows = roses_rows()
        _overview, elements = adapter().split_rows(rows)
        children = adapter().subtopic_children(
            rows, parent_matches={elements[0]["identity"]: "363224"},
            as_of=AS_OF)
        kept, diagnostics = cov4.apply_gate(parent(), children, None)
        self.assertEqual(diagnostics["classifier_calls"], 0)
        self.assertEqual(kept, children)
        for record in kept:
            self.assertEqual(record["subtopic_source"], records.NATIVE)
            # Not judged by Cov4, so the predicate falls through to the tier.
            self.assertEqual(
                records.publication_eligibility(record)[1],
                f"tier_{record.get('confidence')}",
            )

    def test_army_referenced_children_still_publish_on_their_own_tier(self):
        from scripts import extract_document_evidence as ede
        from tests.test_subtopic_referenced import PARENT, fetch_ok

        original = ede.referenced_fetch
        ede.referenced_fetch = fetch_ok
        try:
            fields = ede.subtopic_fields(
                PARENT, b"", [], {"url": "https://example.org/notice.pdf"},
                f"{AS_OF}T00:00:00Z", True)
        finally:
            ede.referenced_fetch = original

        self.assertEqual(len(fields["subtopics"]), 14)
        self.assertEqual(fields["subtopic_cov4"]["classifier_calls"], 0)
        for record in fields["subtopics"]:
            self.assertEqual(record["subtopic_source"], records.REFERENCED)
            self.assertEqual(record["confidence"], "high")
            state, reason = records.publication_eligibility(record)
            self.assertEqual(state, records.PUBLISHABLE)
            self.assertEqual(reason, "high_confidence")

    def test_the_flag_off_path_still_adds_nothing(self):
        from scripts import extract_document_evidence as ede

        self.assertEqual(
            ede.subtopic_fields(parent(), b"", [], {},
                                f"{AS_OF}T00:00:00Z", False),
            {},
        )


# --- 7. diagnostics ---------------------------------------------------------

class CacheMetricsTests(unittest.TestCase):

    def test_the_cache_reports_publication_eligibility_alongside_tiers(self):
        cache = records.empty_cache()
        kept, _d = gated()
        records.upsert_parent(cache, "363526", kept, as_of=AS_OF)
        metrics = records.cache_metrics(cache)
        self.assertEqual(metrics["subtopic_confidence_counts"], {"medium": 1})
        self.assertEqual(
            metrics["subtopic_publication_counts"], {records.REVIEW: 1}
        )
        self.assertEqual(
            metrics["subtopic_publication_reasons"], {"tier_medium": 1}
        )


if __name__ == "__main__":
    unittest.main()
