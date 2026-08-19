"""Cov4 -- the two-axis gate, at the production call site.

Offline. Nothing here reaches the network: every classifier verdict is either a
stub or a **committed** verdict replayed from the frozen evaluation artifacts.

What these tests have to earn, in the order the package states it:

1. the implementation is the frozen specification and not a re-design of it --
   the prompt and the number regex are asserted byte-identical to
   `tools/cov4_ownership.py`, and the guard is asserted to agree with frozen O2
   on all 43 committed candidates;
2. ownership and fundability are two axes and stay two axes;
3. only `inline` and `inferred` children enter the gate, proven by driving the
   real NASA `native` and Army `referenced` paths and counting classifier calls;
4. classifier approval never upgrades provenance and never lifts a ceiling;
5. every named failure mode fails closed;
6. BUG-9's fabrication does not survive the production path;
7. the frozen evaluation artifacts still score what they scored, replayed
   through production code rather than through the experiment harness.

The truth labels and the classifier outputs in `evaluation/` are inputs here and
are never rewritten. Where a number is asserted it is the number
`docs/MEAS3_RUN_DESIGN.md` 5d already published.
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts import subtopic_cov4 as cov4          # noqa: E402
from scripts import subtopic_records as records    # noqa: E402
from scripts.subtopic_segmentation import (        # noqa: E402
    SegmentationResult, Subtopic,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "evaluation"
AS_OF = "2026-08-26"


# --- fixtures ---------------------------------------------------------------

def span(code="Topic Area 1", title="Topic Area 1: Improved Oil and Gas Recovery",
         summary="Applications are sought for improved recovery technologies.",
         ordinal=1):
    """One accepted span, in the shape `build_records` consumes."""
    return Subtopic(
        subtopic_code=code,
        subtopic_code_norm=code.casefold().replace(" ", "-"),
        subtopic_ordinal=ordinal,
        ordinal_label="numeric",
        title=title,
        title_fingerprint=title.casefold(),
        summary=summary,
        subtopic_terms={"recovery": 1},
        page_start=4,
        page_end=5,
        anchor="p4",
        char_start=0,
        char_end=len(summary),
        program_area_labels=(),
        topic_areas=(),
        own_deadline=None,
    )


def result(spans, confidence="medium", method="numbered", family="topic_area"):
    return SegmentationResult(
        subtopics=tuple(spans), method=method, confidence=confidence,
        family=family,
    )


def parent(number="DE-FOA-0003215", identifier="363594",
           title="Annual Recurring University Training and Research"):
    return {
        "opportunity_id": identifier,
        "opportunity_number": number,
        "title": title,
        "status": "posted",
        "close_date": "2026-12-31",
    }


def attachment_document(name="FundOpp_DE-FOA-0003215.pdf"):
    return {
        "url": "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/1",
        "name": name,
        "sha256": "a" * 64,
        "source_kind": "primary_notice",
    }


def agency_document(url="https://netl-exchange.energy.gov/Default.aspx"):
    return {
        "url": url,
        "name": None,
        "sha256": "b" * 64,
        "source_kind": "subtopic_agency_notice",
    }


class CountingClassifier:
    """A stub that records every call, so "zero calls" is a measurement."""

    def __init__(self, fundability=cov4.ACCEPT, owned=True):
        self.calls = []
        self._fundability = fundability
        self._owned = owned

    def __call__(self, candidate, *, api_key=None, session=None):
        self.calls.append(candidate)
        return {
            "fundability": self._fundability,
            "classifier_owned": self._owned,
            "reason": "stub",
            "error": None,
            "detail": None,
        }


def build(parent_record, spans, document, *, provenance=None, confidence="medium"):
    return records.build_records(
        parent_record, result(spans, confidence=confidence),
        document=document, as_of=AS_OF, provenance=provenance,
    )


# --- 1. fidelity to the frozen specification --------------------------------

class FrozenSpecificationTests(unittest.TestCase):
    """The implementation must BE the measurement, not resemble it."""

    def frozen(self):
        import tools.cov4_ownership as frozen_spec
        return frozen_spec

    def test_the_prompt_is_byte_identical_to_the_frozen_o1_prompt(self):
        """Cov4 ships the prompt the experiment selected, untuned."""
        self.assertEqual(cov4.PROMPT, self.frozen().O1_PROMPT)

    def test_the_solicitation_regex_is_byte_identical_to_the_frozen_one(self):
        self.assertEqual(
            cov4.SOLICITATION_RE.pattern, self.frozen().SOLICITATION_RE.pattern
        )
        self.assertEqual(
            cov4.SOLICITATION_RE.flags, self.frozen().SOLICITATION_RE.flags
        )

    def test_the_configuration_is_the_frozen_one(self):
        self.assertEqual(cov4.MODEL, "claude-sonnet-5")
        self.assertEqual(cov4.REPEATS, 1)
        self.assertEqual(cov4.API_URL, "https://api.anthropic.com/v1/messages")
        self.assertEqual(cov4.API_VERSION, "2023-06-01")
        self.assertEqual(cov4.API_KEY_ENV, "ANTHROPIC_API_KEY")

    def test_the_guard_agrees_with_frozen_o2_on_every_committed_candidate(self):
        """43 real-document candidates, decided identically. No drift."""
        from tools.cov4_ownership import (
            CONFLICT, OWNED, UNESTABLISHED, ownership_o2,
        )
        from tools.run_cov4_ownership import load_candidates

        translate = {OWNED: cov4.OWNED, CONFLICT: cov4.NOT_OWNED,
                     UNESTABLISHED: cov4.UNESTABLISHED}
        candidates = load_candidates()
        self.assertEqual(len(candidates), 43)
        for candidate in candidates:
            frozen_verdict = ownership_o2(candidate)
            production = cov4.determine_ownership(candidate)
            self.assertEqual(
                translate[frozen_verdict["ownership"]], production["ownership"],
                candidate["candidate_id"],
            )
            self.assertEqual(
                frozen_verdict["consulted_prose"], production["consulted_prose"],
                candidate["candidate_id"],
            )

    def test_no_anthropic_sdk_and_no_new_dependency_is_imported(self):
        source = (ROOT / "scripts" / "subtopic_cov4.py").read_text(
            encoding="utf-8")
        self.assertNotIn("import anthropic", source)
        self.assertNotIn("from anthropic", source)
        self.assertIn("import requests", source)

    def test_the_module_never_embeds_a_credential(self):
        source = (ROOT / "scripts" / "subtopic_cov4.py").read_text(
            encoding="utf-8")
        self.assertNotIn("sk-ant", source)
        self.assertIn('os.environ.get(API_KEY_ENV)', source)


# --- 2. the ownership axis, deterministic -----------------------------------

class OwnershipGuardTests(unittest.TestCase):
    """The four `source_kind`s, and the distinction the measurement preserved."""

    def test_a_grants_gov_attachment_is_owned_without_reading_prose(self):
        for kind in ("primary_notice", "secondary_attachment"):
            verdict = cov4.determine_ownership({
                "source_kind": kind,
                "parent_opportunity_number": "DE-FOA-0003215",
                "excerpt": "belongs to DE-FOA-0003627",
            })
            self.assertEqual(verdict["ownership"], cov4.OWNED, kind)
            self.assertFalse(verdict["consulted_prose"], kind)

    def test_an_agency_page_does_not_establish_ownership_automatically(self):
        for kind in ("agency_notice", "subtopic_agency_notice"):
            verdict = cov4.determine_ownership({
                "source_kind": kind,
                "parent_opportunity_number": "DE-FOA-0003215",
                "excerpt": "Area of Interest 3: Carbon Storage Field Projects.",
            })
            self.assertEqual(verdict["ownership"], cov4.UNESTABLISHED, kind)
            self.assertNotEqual(verdict["ownership"], cov4.OWNED, kind)

    def test_an_agency_page_naming_the_parent_is_owned(self):
        verdict = cov4.determine_ownership({
            "source_kind": "agency_notice",
            "parent_opportunity_number": "DE-FOA-0003215",
            "excerpt": "Topics under DE-FOA-0003215 are listed below.",
        })
        self.assertEqual(verdict["ownership"], cov4.OWNED)

    def test_an_agency_page_naming_only_another_opportunity_is_not_owned(self):
        verdict = cov4.determine_ownership({
            "source_kind": "subtopic_agency_notice",
            "parent_opportunity_number": "DE-FOA-0003215",
            "excerpt": "an area of interest under DE-FOA-0003627",
        })
        self.assertEqual(verdict["ownership"], cov4.NOT_OWNED)

    def test_an_unknown_or_missing_source_kind_fails_closed(self):
        """An old cache entry with no `source_kind` must never be owned."""
        for kind in (None, "", "mystery_kind"):
            verdict = cov4.determine_ownership({
                "source_kind": kind,
                "parent_opportunity_number": "DE-FOA-0003215",
            })
            self.assertEqual(verdict["ownership"], cov4.UNESTABLISHED, repr(kind))

    def test_unestablished_is_its_own_outcome_and_never_collapses_to_owned(self):
        self.assertEqual(
            len({cov4.OWNED, cov4.NOT_OWNED, cov4.UNESTABLISHED}), 3
        )
        self.assertNotEqual(cov4.UNESTABLISHED, cov4.OWNED)

    def test_number_matching_is_normalised_not_literal(self):
        self.assertEqual(
            cov4.normalise_number("DE-FOA-0003215"),
            cov4.normalise_number("de foa 0003215"),
        )


class OverAggressionTrapTests(unittest.TestCase):
    """The measured cases a naive "foreign number anywhere" rule destroys."""

    def cases(self):
        payload = json.loads(
            (EVALUATION / "cov4_ownership.json").read_text(encoding="utf-8")
        )
        return {row["candidate_id"]: row for row in payload["candidates"]}

    def test_a_predecessor_citation_does_not_reject_a_genuine_child(self):
        """`own:360678-predecessor-citation` -- HEP, page 96, cites DE-FOA-0003354."""
        candidate = self.cases()["own:360678-predecessor-citation"]
        self.assertIn("DE-FOA-0003354", candidate["excerpt"])
        verdict = cov4.determine_ownership(candidate)
        self.assertEqual(verdict["ownership"], cov4.OWNED)
        self.assertFalse(verdict["consulted_prose"])

    def test_an_amendment_history_does_not_reject_a_genuine_child(self):
        candidate = self.cases()["own:363065-amendment-history"]
        verdict = cov4.determine_ownership(candidate)
        self.assertEqual(verdict["ownership"], cov4.OWNED)
        self.assertFalse(verdict["consulted_prose"])

    def test_an_ordinary_cross_reference_inside_an_attachment_is_ignored(self):
        candidate = {
            "source_kind": "secondary_attachment",
            "parent_opportunity_number": "DE-FOA-0003600",
            "excerpt": (
                "See also DE-FOA-0003354 and FA9550-24-S-0001 for related work; "
                "this topic continues the programme described there."
            ),
        }
        self.assertEqual(
            cov4.determine_ownership(candidate)["ownership"], cov4.OWNED
        )


# --- 3. the provenance boundary, at the production call site ----------------

class ProvenanceBoundaryTests(unittest.TestCase):
    """Only `inline` and `inferred` may enter Cov4. Proven by counting calls."""

    def test_the_boundary_is_exactly_inline_and_inferred(self):
        self.assertEqual(
            cov4.CLASSIFIED_PROVENANCE,
            frozenset({records.INLINE, records.INFERRED}),
        )
        self.assertNotIn(records.NATIVE, cov4.CLASSIFIED_PROVENANCE)
        self.assertNotIn(records.REFERENCED, cov4.CLASSIFIED_PROVENANCE)

    def test_a_native_child_makes_zero_classifier_calls(self):
        """Real ROSES rows, real `native` children, straight through the gate."""
        from tests.test_nasa_roses_provenance import adapter, roses_rows

        rows = roses_rows()
        _overview, elements = adapter().split_rows(rows)
        children = adapter().subtopic_children(
            rows,
            parent_matches={elements[0]["identity"]: "363224",
                            elements[1]["identity"]: "363240"},
            as_of=AS_OF,
        )
        self.assertTrue(children)
        classifier = CountingClassifier()
        kept, diagnostics = cov4.apply_gate(
            parent(), children, None, classifier=classifier
        )
        self.assertEqual(classifier.calls, [])
        self.assertEqual(diagnostics["classifier_calls"], 0)
        self.assertEqual(diagnostics["offered"], 0)
        self.assertEqual(diagnostics["bypassed"], len(children))
        self.assertEqual(diagnostics["bypassed_provenance"],
                         {records.NATIVE: len(children)})
        self.assertEqual(kept, children)

    def test_a_native_child_is_returned_completely_unannotated(self):
        from tests.test_nasa_roses_provenance import adapter, roses_rows

        rows = roses_rows()
        _overview, elements = adapter().split_rows(rows)
        children = adapter().subtopic_children(
            rows, parent_matches={elements[0]["identity"]: "363224"})
        kept, _diagnostics = cov4.apply_gate(
            parent(), children, None, classifier=CountingClassifier())
        for record in kept:
            self.assertNotIn("cov4_ownership", record)
            self.assertNotIn("cov4_fundability", record)
            self.assertNotIn("cov4_review", record)

    def test_the_roses_adapter_never_reaches_the_classifier_at_all(self):
        """ROSES does not pass through `subtopic_fields`; prove it stays out."""
        from tests.test_nasa_roses_provenance import adapter, roses_rows

        rows = roses_rows()
        _overview, elements = adapter().split_rows(rows)
        classifier = CountingClassifier()
        original = cov4.classify_fundability
        cov4.classify_fundability = classifier
        try:
            children = adapter().subtopic_children(
                rows, parent_matches={elements[0]["identity"]: "363224"})
            adapter().standalone_inventory(rows)
        finally:
            cov4.classify_fundability = original
        self.assertEqual(len(children), 1)
        self.assertEqual(classifier.calls, [])

    def test_an_army_referenced_child_makes_zero_classifier_calls(self):
        """Driven through `subtopic_fields`, which is the production call site."""
        from scripts import extract_document_evidence as ede
        from tests.test_subtopic_referenced import PARENT, fetch_ok

        classifier = CountingClassifier()
        original_fetch = ede.referenced_fetch
        original_classify = cov4.classify_fundability
        ede.referenced_fetch = fetch_ok
        cov4.classify_fundability = classifier
        try:
            fields = ede.subtopic_fields(
                PARENT, b"", [], {"url": "https://example.org/notice.pdf"},
                f"{AS_OF}T00:00:00Z", True,
            )
        finally:
            ede.referenced_fetch = original_fetch
            cov4.classify_fundability = original_classify

        self.assertEqual(len(fields["subtopics"]), 14)
        self.assertEqual(classifier.calls, [])
        self.assertEqual(fields["subtopic_cov4"]["classifier_calls"], 0)
        self.assertEqual(fields["subtopic_cov4"]["offered"], 0)
        self.assertEqual(fields["subtopic_cov4"]["bypassed"], 14)
        self.assertEqual(fields["subtopic_cov4"]["bypassed_provenance"],
                         {records.REFERENCED: 14})
        for record in fields["subtopics"]:
            self.assertEqual(record["subtopic_source"], records.REFERENCED)
            self.assertNotIn("cov4_fundability", record)

    def test_an_ordinary_generic_inferred_child_enters_cov4(self):
        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources

        classifier = CountingClassifier()
        document = attachment_document()
        original = subtopic_sources.best_segmentation
        original_classify = cov4.classify_fundability
        subtopic_sources.best_segmentation = (
            lambda *a, **k: (result([span()]), document, {"attempts": ()})
        )
        cov4.classify_fundability = classifier
        try:
            fields = ede.subtopic_fields(
                parent(number="DE-FOA-0003215"), b"", [], document,
                f"{AS_OF}T00:00:00Z", True,
            )
        finally:
            subtopic_sources.best_segmentation = original
            cov4.classify_fundability = original_classify

        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(fields["subtopic_cov4"]["offered"], 1)
        self.assertEqual(fields["subtopic_cov4"]["classifier_calls"], 1)
        self.assertEqual(fields["subtopic_cov4"]["published"], 1)
        self.assertEqual(len(fields["subtopics"]), 1)
        self.assertEqual(
            fields["subtopics"][0]["subtopic_source"], records.INFERRED
        )

    def test_an_inline_child_is_judged_exactly_like_an_inferred_one(self):
        """§5.1 makes `inline` reachable only by override; Cov4 still gates it."""
        classifier = CountingClassifier()
        built = build(parent(), [span()], attachment_document(),
                      provenance=records.INLINE)
        self.assertEqual(built[0]["subtopic_source"], records.INLINE)
        kept, diagnostics = cov4.apply_gate(
            parent(), built, attachment_document(), classifier=classifier)
        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(diagnostics["offered"], 1)
        self.assertEqual(diagnostics["published"], 1)
        self.assertEqual(kept[0]["subtopic_source"], records.INLINE)

    def test_the_candidate_carries_everything_the_specification_names(self):
        classifier = CountingClassifier()
        document = attachment_document()
        built = build(parent(), [span()], document)
        cov4.apply_gate(parent(), built, document, classifier=classifier)
        candidate = classifier.calls[0]
        for field in (
            "parent_record_id", "parent_opportunity_number", "parent_title",
            "source_kind", "source_document_name", "source_document_url",
            "source_document_hash", "subtopic_code", "title", "excerpt",
            "provenance",
        ):
            self.assertIsNotNone(candidate[field], field)
        self.assertEqual(candidate["source_kind"], "primary_notice")
        self.assertEqual(candidate["parent_opportunity_number"], "DE-FOA-0003215")


# --- 4. provenance is never upgraded by approval ----------------------------

class ProvenanceIsNeverUpgradedTests(unittest.TestCase):
    def test_an_approved_inferred_child_stays_inferred(self):
        built = build(parent(), [span()], attachment_document())
        kept, _d = cov4.apply_gate(
            parent(), built, attachment_document(), classifier=CountingClassifier())
        self.assertEqual(kept[0]["subtopic_source"], records.INFERRED)
        self.assertNotEqual(kept[0]["subtopic_source"], records.NATIVE)
        self.assertNotEqual(kept[0]["subtopic_source"], records.REFERENCED)

    def test_approval_does_not_lift_the_inferred_confidence_ceiling(self):
        """`inferred` is capped at `medium`; a passing verdict does not change it."""
        built = build(parent(), [span()], attachment_document(),
                      confidence="high")
        self.assertEqual(built[0]["confidence"], "medium")   # §5.1 ceiling
        kept, _d = cov4.apply_gate(
            parent(), built, attachment_document(), classifier=CountingClassifier())
        self.assertEqual(kept[0]["confidence"], "medium")

    def test_the_full_chain_candidate_provenance_ownership_classifier_tier(self):
        """candidate -> provenance -> ownership -> classifier -> eligibility."""
        document = attachment_document()
        built = build(parent(), [span()], document, confidence="high")
        # provenance
        self.assertEqual(built[0]["subtopic_source"], records.INFERRED)
        # ceiling, before Cov4 has seen it
        self.assertEqual(built[0]["confidence"], "medium")
        kept, diagnostics = cov4.apply_gate(
            parent(), built, document, classifier=CountingClassifier())
        record = kept[0]
        # ownership
        self.assertEqual(record["cov4_ownership"], cov4.OWNED)
        self.assertEqual(record["cov4_ownership_basis"],
                         "grants_gov_attachment_binding")
        # fundability
        self.assertEqual(record["cov4_fundability"], cov4.ACCEPT)
        # eligibility: not queued, and the tier is still the capped one
        self.assertNotIn("cov4_review", record)
        self.assertEqual(record["confidence"], "medium")
        self.assertEqual(diagnostics["published"], 1)
        self.assertEqual(diagnostics["review"], 0)
        self.assertEqual(diagnostics["dropped"], 0)


# --- 5. the two axes stay two axes ------------------------------------------

class TwoAxesTests(unittest.TestCase):
    def test_a_fundable_child_of_the_wrong_parent_is_still_rejected(self):
        """The whole invariant, in one assertion."""
        document = agency_document()
        built = build(
            parent(),
            [span(summary="an area of interest under DE-FOA-0003627, listed "
                          "among many open NETL funding opportunities")],
            document,
        )
        classifier = CountingClassifier(fundability=cov4.ACCEPT)
        kept, diagnostics = cov4.apply_gate(
            parent(), built, document, classifier=classifier)
        self.assertEqual(kept, [])
        self.assertEqual(diagnostics["ownership"], {cov4.NOT_OWNED: 1})
        self.assertEqual(diagnostics["fundability"], {cov4.ACCEPT: 1})
        self.assertEqual(diagnostics["dropped"], 1)
        self.assertEqual(diagnostics["published"], 0)

    def test_an_owned_but_unfundable_child_is_rejected_on_the_other_axis(self):
        document = attachment_document()
        built = build(parent(), [span(title="V. Application Review Information")],
                      document)
        kept, diagnostics = cov4.apply_gate(
            parent(), built, document,
            classifier=CountingClassifier(fundability=cov4.REJECT))
        self.assertEqual(kept, [])
        self.assertEqual(diagnostics["ownership"], {cov4.OWNED: 1})
        self.assertEqual(diagnostics["fundability"], {cov4.REJECT: 1})

    def test_both_axes_are_reported_independently(self):
        document = agency_document()
        built = build(parent(), [span(), span(code="Topic Area 2", ordinal=2)],
                      document)
        _kept, diagnostics = cov4.apply_gate(
            parent(), built, document, classifier=CountingClassifier())
        self.assertIn("ownership", diagnostics)
        self.assertIn("fundability", diagnostics)
        self.assertEqual(sum(diagnostics["ownership"].values()), 2)
        self.assertEqual(sum(diagnostics["fundability"].values()), 2)

    def test_the_classifier_ownership_opinion_never_decides_publication(self):
        """O1 answers ownership too; the guard, not the model, decides it."""
        document = agency_document()
        built = build(parent(), [span()], document)
        kept, diagnostics = cov4.apply_gate(
            parent(), built, document,
            classifier=CountingClassifier(fundability=cov4.ACCEPT, owned=True))
        self.assertEqual(diagnostics["published"], 0)
        self.assertEqual(kept[0]["cov4_ownership"], cov4.UNESTABLISHED)
        self.assertTrue(kept[0]["cov4_review"])


# --- 6. fail-closed ---------------------------------------------------------

class FailClosedTests(unittest.TestCase):
    """Every named failure mode. None may publish an unchecked span."""

    class Boom:
        def __init__(self, exc):
            self.exc = exc

        def post(self, *a, **k):
            raise self.exc

    class Response:
        def __init__(self, status_code=200, payload=None, raises=False):
            self.status_code = status_code
            self._payload = payload
            self._raises = raises

        def json(self):
            if self._raises:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")
            return self._payload

    class Session:
        def __init__(self, response):
            self.response = response

        def post(self, *a, **k):
            return self.response

    def session(self, response):
        return self.Session(response)

    def text_response(self, text):
        return self.Response(payload={"content": [{"type": "text", "text": text}]})

    def test_a_missing_credential_is_unresolved_and_makes_no_request(self):
        """The test must never depend on the real credential being present."""
        import os

        called = []

        class Recorder:
            def post(self, *a, **k):
                called.append(a)

        saved = os.environ.pop(cov4.API_KEY_ENV, None)
        try:
            verdict = cov4.classify_fundability({}, session=Recorder())
        finally:
            if saved is not None:
                os.environ[cov4.API_KEY_ENV] = saved
        self.assertEqual(verdict["fundability"], cov4.UNRESOLVED)
        self.assertEqual(verdict["error"], "missing_credential")
        self.assertEqual(called, [])

    def test_a_timeout_is_unresolved(self):
        verdict = cov4.classify_fundability(
            {}, api_key="k", session=self.Boom(TimeoutError("timed out")))
        self.assertEqual(verdict["fundability"], cov4.UNRESOLVED)
        self.assertEqual(verdict["error"], "request_failed")
        self.assertEqual(verdict["detail"], "TimeoutError")

    def test_a_non_2xx_response_is_unresolved(self):
        for status in (401, 429, 500, 503):
            verdict = cov4.classify_fundability(
                {}, api_key="k",
                session=self.session(self.Response(status_code=status)))
            self.assertEqual(verdict["fundability"], cov4.UNRESOLVED, status)
            self.assertEqual(verdict["error"], "http_error", status)
            self.assertEqual(verdict["detail"], f"status_{status}")

    def test_malformed_json_is_unresolved(self):
        verdict = cov4.classify_fundability(
            {}, api_key="k",
            session=self.session(self.Response(raises=True)))
        self.assertEqual(verdict["fundability"], cov4.UNRESOLVED)
        self.assertEqual(verdict["error"], "malformed_response")

    def test_an_unparseable_classifier_response_is_unresolved(self):
        for text in ("", "I cannot answer that.", "yes, definitely fundable"):
            verdict = cov4.classify_fundability(
                {}, api_key="k", session=self.session(self.text_response(text)))
            self.assertEqual(verdict["fundability"], cov4.UNRESOLVED, text)
            self.assertEqual(verdict["error"], "unparseable_response", text)

    def test_an_unexpected_output_enum_is_unresolved(self):
        for body in ('{"owned": "yes", "fundable": "maybe"}',
                     '{"owned": "yes"}',
                     '{"owned": "yes", "fundable": true}'):
            verdict = cov4.classify_fundability(
                {}, api_key="k", session=self.session(self.text_response(body)))
            self.assertEqual(verdict["fundability"], cov4.UNRESOLVED, body)
            self.assertEqual(verdict["error"], "unexpected_enum", body)

    def test_a_well_formed_answer_still_parses(self):
        """The failure tests are only meaningful if the success path works."""
        verdict = cov4.classify_fundability(
            {}, api_key="k",
            session=self.session(self.text_response(
                '{"owned": "yes", "fundable": "yes", "reason": "a programme"}')))
        self.assertEqual(verdict["fundability"], cov4.ACCEPT)
        self.assertTrue(verdict["classifier_owned"])
        self.assertIsNone(verdict["error"])

    def test_no_failure_mode_lets_an_unchecked_span_publish(self):
        document = attachment_document()
        built = build(parent(), [span()], document)
        for failure in (
            lambda *a, **k: cov4._unresolved("missing_credential"),
            lambda *a, **k: cov4._unresolved("request_failed", detail="Timeout"),
            lambda *a, **k: cov4._unresolved("http_error", detail="status_429"),
            lambda *a, **k: cov4._unresolved("malformed_response"),
            lambda *a, **k: cov4._unresolved("unparseable_response"),
            lambda *a, **k: cov4._unresolved("unexpected_enum"),
        ):
            kept, diagnostics = cov4.apply_gate(
                parent(), built, document, classifier=failure)
            self.assertEqual(diagnostics["published"], 0)
            self.assertEqual(diagnostics["review"], 1)
            self.assertTrue(kept[0]["cov4_review"])
            # `low` has never published (§13), which is what "queued" means here.
            self.assertEqual(kept[0]["confidence"], "low")

    def test_a_classifier_outage_does_not_fail_the_catalog_build(self):
        """An unreachable API costs recall, never the parent's facts (§9.3)."""
        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources

        document = attachment_document()
        original = subtopic_sources.best_segmentation
        original_classify = cov4.classify_fundability
        subtopic_sources.best_segmentation = (
            lambda *a, **k: (result([span()]), document, {"attempts": ()})
        )
        cov4.classify_fundability = (
            lambda *a, **k: cov4._unresolved("request_failed", detail="SSLError")
        )
        try:
            fields = ede.subtopic_fields(
                parent(), b"", [], document, f"{AS_OF}T00:00:00Z", True)
        finally:
            subtopic_sources.best_segmentation = original
            cov4.classify_fundability = original_classify

        self.assertNotIn("subtopic_reason", fields)      # not an error outcome
        self.assertEqual(fields["subtopic_cov4"]["review"], 1)
        self.assertEqual(fields["subtopic_cov4"]["published"], 0)
        self.assertEqual(
            fields["subtopic_cov4"]["classifier_errors"], {"request_failed": 1}
        )
        self.assertEqual(fields["subtopics"][0]["confidence"], "low")

    def test_diagnostics_never_carry_a_credential_or_a_request_header(self):
        verdict = cov4.classify_fundability(
            {}, api_key="sk-ant-secret-value",
            session=self.Boom(RuntimeError("failed for url with sk-ant-secret-value")))
        serialized = json.dumps(verdict)
        self.assertNotIn("sk-ant", serialized)
        self.assertNotIn("x-api-key", serialized)
        self.assertEqual(verdict["detail"], "RuntimeError")


# --- 7. BUG-9 ---------------------------------------------------------------

class Bug9Tests(unittest.TestCase):
    """The aggregating agency page must stop fabricating another FOA's child.

    Parent `DE-FOA-0003215` (record `363594`), NETL's landing page, and a
    candidate whose own text attributes it to `DE-FOA-0003627`. Semantically it
    is a real topic -- the classifier accepts it, and that is the point.
    """

    CANDIDATE_SUMMARY = (
        "Topic Area 1: Improved Oil and Gas Recovery - an area of interest "
        "under DE-FOA-0003627, listed among many open NETL funding "
        "opportunities on this page."
    )

    def test_the_frozen_case_is_the_one_being_tested(self):
        payload = json.loads(
            (EVALUATION / "cov4_ownership.json").read_text(encoding="utf-8"))
        row = {c["candidate_id"]: c for c in payload["candidates"]}[
            "own:363594-foreign-number"]
        self.assertEqual(row["parent_opportunity_number"], "DE-FOA-0003215")
        self.assertIn("DE-FOA-0003627", row["excerpt"])
        self.assertEqual(row["owned"], "no")
        self.assertEqual(row["fundable"], "yes")

    def test_the_fabrication_does_not_publish_through_the_production_path(self):
        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources

        document = agency_document()
        classifier = CountingClassifier(fundability=cov4.ACCEPT)
        original = subtopic_sources.best_segmentation
        original_classify = cov4.classify_fundability
        subtopic_sources.best_segmentation = (
            lambda *a, **k: (
                result([span(summary=self.CANDIDATE_SUMMARY)]),
                document, {"attempts": ()},
            )
        )
        cov4.classify_fundability = classifier
        try:
            fields = ede.subtopic_fields(
                parent(), b"", [], document, f"{AS_OF}T00:00:00Z", True)
        finally:
            subtopic_sources.best_segmentation = original
            cov4.classify_fundability = original_classify

        self.assertEqual(fields["subtopics"], [])
        self.assertEqual(fields["subtopic_cov4"]["ownership"],
                         {cov4.NOT_OWNED: 1})
        # Fundable, and rejected anyway. Two axes.
        self.assertEqual(fields["subtopic_cov4"]["fundability"],
                         {cov4.ACCEPT: 1})
        self.assertEqual(fields["subtopic_cov4"]["dropped"], 1)
        self.assertEqual(fields["subtopic_cov4"]["published"], 0)

    def test_the_fabrication_does_not_publish_through_the_cov1_refresh_path(self):
        """BUG-9's real path: `subtopic_only_primary` -> `subtopic_agency_notice`."""
        from datetime import datetime, timezone

        from scripts import extract_document_evidence as ede
        from scripts import subtopic_sources

        record = parent()
        record["primary_document_url"] = None
        record["primary_document_name"] = None
        record["funding_opportunity_url"] = (
            "https://netl-exchange.energy.gov/Default.aspx")
        record["award_floor"] = 100000

        self.assertIsNone(ede.source_for_record(record))

        classifier = CountingClassifier(fundability=cov4.ACCEPT)
        captured = {}
        original = subtopic_sources.best_segmentation
        original_classify = cov4.classify_fundability

        def fake_segmentation(rec, content, doc, **kwargs):
            captured["source_kind"] = (doc or {}).get("source_kind")
            return (result([span(summary=self.CANDIDATE_SUMMARY)]), doc,
                    {"attempts": ()})

        subtopic_sources.best_segmentation = fake_segmentation
        cov4.classify_fundability = classifier
        try:
            store, metrics = ede.refresh_subtopics_without_source(
                [record],
                max_documents=5,
                fetcher=lambda url, headers: {
                    "content": b"<html>NETL open opportunities</html>",
                    "url": url, "content_type": "text/html",
                },
                now=datetime(2026, 8, 26, 12, tzinfo=timezone.utc),
                enabled=True,
            )
        finally:
            subtopic_sources.best_segmentation = original
            cov4.classify_fundability = original_classify

        self.assertEqual(captured["source_kind"], "subtopic_agency_notice")
        self.assertEqual(metrics["attempted"], 1)
        self.assertEqual(metrics["with_subtopics"], 0)
        fields = store["363594"]
        self.assertEqual(fields["subtopics"], [])
        self.assertEqual(fields["subtopic_cov4"]["ownership"],
                         {cov4.NOT_OWNED: 1})
        self.assertEqual(fields["subtopic_cov4"]["dropped"], 1)


# --- 8. the frozen evaluation artifacts, replayed through production --------

class FrozenRegressionTests(unittest.TestCase):
    """The committed evidence base, scored by production code.

    Truth labels and classifier outputs are read, never rewritten. The ownership
    axis is recomputed by the production guard; the fundability axis is the
    **committed** O1 verdict from `evaluation/cov4_ownership_runs.jsonl`, so this
    is a regression over the measured run rather than a new one.
    """

    @classmethod
    def setUpClass(cls):
        from tools.run_cov4_ownership import load_candidates

        cls.candidates = {row["candidate_id"]: row for row in load_candidates()}
        cls.verdicts = {}
        for line in (EVALUATION / "cov4_ownership_runs.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cls.verdicts[row["candidate_id"]] = row

    def gate(self, candidate_id):
        """(ownership, fundability, publishes) for one committed candidate."""
        candidate = self.candidates[candidate_id]
        ownership = cov4.determine_ownership(candidate)["ownership"]
        fundability = {"yes": cov4.ACCEPT, "no": cov4.REJECT}.get(
            self.verdicts[candidate_id]["fundable"], cov4.UNRESOLVED)
        publishes = ownership == cov4.OWNED and fundability == cov4.ACCEPT
        return ownership, fundability, publishes

    def scored(self):
        """Every candidate whose truth is decided on both axes."""
        for candidate_id, candidate in self.candidates.items():
            if "unresolved" in (candidate["owned"], candidate["fundable"]):
                continue
            yield candidate_id, candidate

    def test_the_artifacts_are_the_committed_ones(self):
        self.assertEqual(len(self.candidates), 43)
        self.assertEqual(len(self.verdicts), 43)
        self.assertTrue(
            all(row["status_code"] == 200 for row in self.verdicts.values())
        )

    def test_no_genuine_child_is_lost(self):
        lost = [
            candidate_id for candidate_id, candidate in self.scored()
            if candidate["owned"] == "yes" and candidate["fundable"] == "yes"
            and not self.gate(candidate_id)[2]
        ]
        self.assertEqual(lost, [])

    def test_no_fabrication_survives(self):
        fabrications = [
            candidate_id for candidate_id, candidate in self.scored()
            if self.gate(candidate_id)[2]
            and not (candidate["owned"] == "yes" and candidate["fundable"] == "yes")
        ]
        self.assertEqual(fabrications, [])

    def test_the_combined_gate_reproduces_the_published_figures(self):
        """5d.5: 28 published correctly, 0 fabrications, 0 genuine children lost."""
        published = sum(
            1 for candidate_id, _c in self.scored() if self.gate(candidate_id)[2]
        )
        self.assertEqual(published, 28)

    def test_every_cross_opportunity_candidate_is_rejected(self):
        cross = [cid for cid, c in self.candidates.items() if c["owned"] == "no"]
        self.assertEqual(len(cross), 2)
        for candidate_id in cross:
            ownership, _fundability, publishes = self.gate(candidate_id)
            self.assertEqual(ownership, cov4.NOT_OWNED, candidate_id)
            self.assertFalse(publishes, candidate_id)

    def test_measured_contaminants_are_rejected(self):
        """All 12, and the 12th is the label-precedence case 5d.5 discloses.

        `363594:x-other-foa-topic` carries the one-axis `contaminant` label in
        the challenge set and the two-axis `owned: no / fundable: yes` label in
        the ownership set. The classifier accepts it on fundability, which is why
        the one-axis reading records FP=1 -- and the guard rejects it on
        ownership, so **it does not publish under either reading**. That is the
        assertion that matters, so it is the one made here.
        """
        contaminants = [
            candidate_id for candidate_id, candidate in self.candidates.items()
            if candidate["fundable"] == "no"
        ]
        self.assertEqual(len(contaminants), 12)
        for candidate_id in contaminants:
            self.assertFalse(self.gate(candidate_id)[2], candidate_id)
        rejected_on_fundability = [
            candidate_id for candidate_id in contaminants
            if self.gate(candidate_id)[1] == cov4.REJECT
        ]
        self.assertEqual(len(rejected_on_fundability), 11)
        self.assertEqual(
            sorted(set(contaminants) - set(rejected_on_fundability)),
            ["363594:x-other-foa-topic"],
        )
        self.assertEqual(
            self.gate("363594:x-other-foa-topic")[0], cov4.NOT_OWNED
        )

    def test_the_office_container_false_positives_are_rejected(self):
        """5d.4 re-tested these 5/5 rather than trusting them at n=1."""
        for candidate_id in ("360678:x-org-bes",
                             "360678:x-org-office-of-science"):
            ownership, fundability, publishes = self.gate(candidate_id)
            self.assertEqual(ownership, cov4.OWNED, candidate_id)
            self.assertEqual(fundability, cov4.REJECT, candidate_id)
            self.assertFalse(publishes, candidate_id)

    def test_the_f1_and_f4_cases_remain_compatible_with_the_gate(self):
        """5a.3's shapes, kept and rejected as the challenge set labels them."""
        challenge = json.loads(
            (EVALUATION / "cov4_challenge.json").read_text(encoding="utf-8"))
        shapes = {"f1_bare_numbered", "f4_named_bulleted",
                  "f1_bare_numbered_decoy", "f4_adjacent_decoy",
                  "navigation_toc"}
        seen = {}
        for row in challenge["candidates"]:
            if row["shape"] not in shapes:
                continue
            seen[row["shape"]] = seen.get(row["shape"], 0) + 1
            publishes = self.gate(row["candidate_id"])[2]
            self.assertEqual(
                publishes, row["truth_label"] == "fundable", row["candidate_id"]
            )
        self.assertEqual(seen, {"f1_bare_numbered": 2, "f4_named_bulleted": 3,
                                "f1_bare_numbered_decoy": 1,
                                "f4_adjacent_decoy": 3, "navigation_toc": 1})

    def test_unresolved_cases_stay_unresolved_and_are_never_promoted(self):
        """Neither of the two may auto-publish; neither is silently accepted."""
        # Ownership unresolved: the aggregating page that prints no number.
        ownership, fundability, publishes = self.gate(
            "own:363594-aggregator-unnumbered")
        self.assertEqual(ownership, cov4.UNESTABLISHED)
        self.assertEqual(fundability, cov4.ACCEPT)
        self.assertFalse(publishes)
        # Fundability unresolved by DEC-11: `(n) Public-Private Partnerships`.
        self.assertEqual(self.candidates["360678:nppp"]["fundable"], "unresolved")
        self.assertFalse(self.gate("360678:nppp")[2])

    def test_the_unestablished_case_routes_to_review_rather_than_dropping(self):
        """`unestablished` is not a conflict: it is queued, not deleted."""
        candidate = self.candidates["own:363594-aggregator-unnumbered"]
        built = build(
            parent(), [span(title=candidate["title"],
                            summary=candidate["excerpt"])],
            agency_document(candidate["source_document_url"]),
        )
        kept, diagnostics = cov4.apply_gate(
            parent(), built, agency_document(candidate["source_document_url"]),
            classifier=CountingClassifier(fundability=cov4.ACCEPT),
        )
        self.assertEqual(diagnostics["review"], 1)
        self.assertEqual(diagnostics["dropped"], 0)
        self.assertEqual(diagnostics["published"], 0)
        self.assertEqual(kept[0]["confidence"], "low")
        self.assertEqual(kept[0]["cov4_ownership"], cov4.UNESTABLISHED)

    def test_no_f1_or_f4_recogniser_was_added(self):
        """Scope boundary: the challenge rows are hand-extracted, not produced."""
        challenge = json.loads(
            (EVALUATION / "cov4_challenge.json").read_text(encoding="utf-8"))
        self.assertIn("not_a_recogniser", challenge)
        patterns = (ROOT / "scripts" / "subtopic_patterns.py").read_text(
            encoding="utf-8")
        self.assertNotIn("f4_named_bulleted", patterns)
        self.assertNotIn("f1_bare_numbered", patterns)


# --- 9. the flag-off path ---------------------------------------------------

class FlagOffTests(unittest.TestCase):
    def test_the_flag_off_path_still_adds_nothing_at_all(self):
        from scripts import extract_document_evidence as ede

        self.assertEqual(
            ede.subtopic_fields(parent(), b"", [], {},
                                f"{AS_OF}T00:00:00Z", False),
            {},
        )

    def test_an_empty_span_set_costs_no_classifier_call(self):
        classifier = CountingClassifier()
        kept, diagnostics = cov4.apply_gate(
            parent(), [], attachment_document(), classifier=classifier)
        self.assertEqual(kept, [])
        self.assertEqual(classifier.calls, [])
        self.assertEqual(diagnostics["classifier_calls"], 0)


if __name__ == "__main__":
    unittest.main()
