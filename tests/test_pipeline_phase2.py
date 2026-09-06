"""Deterministic Phase 2 contracts. No network, browser, or production writes."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from scripts import build_catalog, build_changes, build_opportunity_teams as teams
from scripts import extract_document_evidence as docs, subtopic_records, subtopic_sources
from scripts.sources import intake
from scripts.sources.merge import integrate, merge_records
from scripts.sources.http import PoliteClient
from tests.fixtures import phase2_pipeline as fixture
from tests import test_document_evidence as evidence_fixture


class PipelineAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.result = fixture.run_pipeline(cls.root)
        cls.catalog = cls.result["catalog"]
        cls.by_id = {r["opportunity_id"]: r for r in cls.catalog["opportunities"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_normal_merge_consumes_accepted_inputs_and_keeps_true_duplicate_authority(self):
        summary = json.loads((self.root / "merge-summary.json").read_text())
        self.assertTrue(summary["written"])
        self.assertEqual(len(self.by_id), 4)
        maintained = next(s for s in summary["sources"] if s["slug"] == "maintained")
        self.assertEqual(maintained["published"], 4)
        self.assertEqual(summary["stats"]["dropped_duplicate_identity"], 1)
        gg = self.by_id["990001"]
        self.assertEqual((gg["award_floor"], gg["award_ceiling"]), (750000, 2000000))
        self.assertEqual(gg["source"], "Grants.gov")
        self.assertNotIn("maintained:science.example.gov:duplicate", self.by_id)

    def test_coordinated_and_hermetic_workflows_enrich_after_canonical_merge(self):
        workflow = (fixture.ROOT / ".github/workflows/refresh-opportunities.yml").read_text()
        commands = ["python -m scripts.enrich_catalog", "python -m scripts.sources merge", "python -m scripts.extract_document_evidence",
                    "python -m scripts.faculty_match", "python -m scripts.build_opportunity_teams --generate", "python -m scripts.build_changes"]
        positions = [workflow.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        offline = (fixture.ROOT / "tools/hermetic_build.sh").read_text()
        self.assertLess(offline.index("python -m scripts.sources merge"), offline.index("python -m scripts.extract_document_evidence"))

    def test_shared_html_and_pdf_evidence_reaches_final_index_and_facets(self):
        html = self.by_id["maintained:science.example.gov:research"]
        pdf = self.by_id["maintained:science.example.gov:topics"]
        self.assertEqual(html["document_evidence_status"], "current")
        self.assertEqual(pdf["document_evidence"]["extraction"]["content_kind"], "pdf")
        self.assertIn("zirconia", html["document_search_text"])
        self.assertNotIn("zirconia", html["description"])
        self.assertIn("zirconia", self.catalog["search_index"]["postings"])
        self.assertEqual(self.catalog["facets"], build_catalog.facet_counts(self.catalog["opportunities"]))
        self.assertIsNone(html["award_ceiling"], "Unstructured funding must remain a cited fact")
        preliminary = next(d for d in html["deadlines"] if d["kind"] == "letter_of_intent")
        self.assertEqual(preliminary["date"], "2026-11-01")
        self.assertTrue(preliminary["timezone"])

    def test_real_team_generator_writes_qualified_panel_and_skips_unsuitable_scopes(self):
        report = self.result["report"]
        states = {r["scope_id"]: r["state"] for r in report["results"]}
        self.assertEqual(states["maintained:science.example.gov:research"], "proposed")
        self.assertEqual(states["maintained:science.example.gov:workshop"], "not_specific")
        model = json.loads((self.root / "config/opportunity_team_model.json").read_text())
        self.assertEqual(len(model["opportunities"]), 1)
        self.assertEqual(len(model["opportunities"][0]["members"]), 2)
        self.assertEqual(model["opportunities"][0]["gate_state"], "pass")
        self.assertIn(model["generation_id"], (self.root / "data/opportunity_team_index.js").read_text())
        self.assertIn(model["generation_id"], (self.root / "match_explorer.html").read_text())
        self.assertIn(model["generation_id"], (self.root / "team_match.html").read_text())
        self.assertTrue((self.root / "data/faculty_matches.js").exists())
        self.assertTrue((self.root / "feeds/all.xml").exists())
        for event in self.result["events"]:
            self.assertIn(event["opportunity_id"], self.by_id)
            self.assertEqual(event["record"]["detail_page"], self.by_id[event["opportunity_id"]]["detail_page"])

    def test_generic_pdf_children_keep_independent_evidence_and_publication_gate(self):
        children = self.result["children"]["records"]["maintained:science.example.gov:topics"]["subtopics"]
        self.assertEqual(len(children), 3)
        self.assertTrue(all(c["publication_state"] == "review" for c in children))
        self.assertTrue(all(c["source_document_url"] == fixture.PDF_URL for c in children))
        first = children[0]
        self.assertIn("catalyst", first["summary"])
        self.assertNotIn("polymer films", first["summary"])
        self.assertNotIn("photon interactions", first["summary"])

    def test_material_amendment_invalidates_team_and_emits_change_without_structured_stamp(self):
        identifier = "maintained:science.example.gov:research"
        amended = deepcopy(self.catalog)
        row = next(r for r in amended["opportunities"] if r["opportunity_id"] == identifier)
        entry, _ = docs.build_document_entry(row, docs.source_for_record(row),
            fixture.response(fixture.NOTICE, fixture.html_notice(fixture.manifest_entry(), "Study optical imaging with photon detectors and microscopy.")),
            self.result["cache"]["records"][identifier], fixture.NOW + timedelta(days=1))
        replacement = docs.merge_document_entry(row, entry)
        amended["opportunities"] = [replacement if r["opportunity_id"] == identifier else r for r in amended["opportunities"]]
        events = build_changes.diff_catalogs(self.catalog, amended, as_of=fixture.AS_OF)
        self.assertEqual([(e["type"], e["opportunity_id"]) for e in events], [("amended", identifier)])
        model = json.loads((self.root / "config/opportunity_team_model.json").read_text())
        with tempfile.TemporaryDirectory() as temporary, patch("scripts.currentness.date", fixture.FixedDate):
            path = Path(temporary) / "catalog.js"
            build_catalog.write_catalog(amended, path)
            candidates = teams.scopes(path, self.root / "data/subtopics.js")
            affected = teams.invalidate_stale_sources(model, teams.source_fingerprints(model, candidates, path))
        self.assertTrue(affected)
        self.assertEqual(model["opportunities"][0]["review_state"], "needs_revalidation")

    def test_removed_or_expired_parent_removes_children_and_withholds_teams(self):
        sidecar = deepcopy(self.result["children"])
        identifier = "maintained:science.example.gov:topics"
        docs.merge_subtopic_sidecar(sidecar, [(identifier, {"status": "current", "subtopics": []})], set(self.by_id), as_of="2026-09-07")
        self.assertEqual(sidecar["records"][identifier]["subtopics"], [])
        docs.merge_subtopic_sidecar(sidecar, [], set(), as_of="2027-01-01")
        self.assertEqual(sidecar["records"], {})
        with patch("scripts.currentness.date") as clock:
            clock.today.return_value = fixture.AS_OF.replace(year=2027)
            self.assertEqual(teams.scopes(self.root / "data/opportunities.js", self.root / "data/subtopics.js"), [])

    def test_material_hash_invalidates_team_even_when_extracted_scope_text_is_unchanged(self):
        with patch("scripts.currentness.date", fixture.FixedDate):
            before = teams.scopes(self.root / "data/opportunities.js", self.root / "data/subtopics.js")
            changed = deepcopy(self.catalog)
            target = next(r for r in changed["opportunities"] if r["opportunity_id"].endswith(":research"))
            target["document_evidence"]["document"]["sha256"] = "a" * 64
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "catalog.js"
                build_catalog.write_catalog(changed, path)
                after = teams.scopes(path, self.root / "data/subtopics.js")
        old = next(s for s in before if s["id"] == target["opportunity_id"])
        new = next(s for s in after if s["id"] == target["opportunity_id"])
        self.assertEqual(old["text"], new["text"])
        self.assertNotEqual(old["source_fingerprint"], new["source_fingerprint"])


class EvidenceLifecycle(unittest.TestCase):
    def setUp(self):
        self.record = evidence_fixture.base_record() | {"opportunity_id": "supplemental:one", "source": "Official council"}
        self.source = docs.source_for_record(self.record)
        self.entry, _ = docs.build_document_entry(self.record, self.source, evidence_fixture.response(), None, fixture.NOW)

    def test_metadata_checks_do_not_change_material_version_or_quotes(self):
        same, extracted = docs.build_document_entry(self.record, self.source,
            evidence_fixture.response(etag='"metadata-only"'), self.entry, fixture.NOW + timedelta(days=1))
        self.assertFalse(extracted)
        self.assertEqual(same["facts"], self.entry["facts"])
        self.assertEqual(same["document"]["version"], self.entry["document"]["version"])
        self.assertFalse(same["document"]["changed_since_previous"])
        before = {"opportunities": [docs.merge_document_entry(self.record, self.entry)]}
        after = {"opportunities": [docs.merge_document_entry(self.record, same)]}
        self.assertNotIn("amended", [e["type"] for e in build_changes.diff_catalogs(before, after, as_of=fixture.AS_OF)])

    def test_failure_withholds_old_quotes_deadlines_topics_and_derived_flags(self):
        current = docs.merge_document_entry(self.record, self.entry)
        catalog = build_catalog.build_catalog([current], fixture.NOW, "fixture", 0)
        cache = docs.empty_cache()
        cache["records"][self.record["opportunity_id"]] = self.entry
        final, updated = docs.enrich_document_evidence(catalog, cache, now=fixture.NOW + timedelta(days=15), request_delay=0,
                                                     fetcher=Mock(side_effect=RuntimeError("blocked")))
        failed = final["opportunities"][0]
        cached = updated["records"][self.record["opportunity_id"]]
        self.assertEqual(cached["checked_at"], self.entry["checked_at"])
        self.assertEqual(cached["status"], "failed")
        self.assertIsNone(failed["document_evidence"])
        self.assertFalse(failed["has_preliminary_stage"])
        self.assertFalse(failed["limited_submission"])
        self.assertEqual(len(failed["deadlines"]), 1)
        self.assertNotIn("citation", failed["deadlines"][0])
        self.assertFalse(failed["document_search_text"])
        sidecar = {"records": {self.record["opportunity_id"]: {"subtopics": [{"subtopic_id": "old"}]}}}
        docs.merge_subtopic_sidecar(sidecar, list(updated["records"].items()), {self.record["opportunity_id"]}, as_of="2026-09-21")
        self.assertEqual(sidecar["records"][self.record["opportunity_id"]]["subtopics"], [])

    def test_route_changes_withhold_evidence_even_outside_fetch_budget(self):
        catalog = build_catalog.build_catalog([self.record | {"primary_document_url": "https://agency.example/new.html"}], fixture.NOW, "fixture", 0)
        cache = docs.empty_cache()
        cache["records"][self.record["opportunity_id"]] = self.entry
        final, _ = docs.enrich_document_evidence(catalog, cache, max_documents=0, now=fixture.NOW)
        self.assertEqual(final["opportunities"][0]["document_evidence_status"], "source_changed")
        self.assertIsNone(final["opportunities"][0]["document_evidence"])

    def test_supplemental_detail_route_needs_no_grants_identifier_or_fact_gap(self):
        record = self.record | {"primary_document_url": None, "detail_page": "https://agency.example/detail", "award_floor": 100, "award_ceiling": 200}
        self.assertEqual(docs.source_for_record(record)["url"], record["detail_page"])
        detail = Mock(side_effect=AssertionError("Grants.gov API used for supplemental ID"))
        self.assertEqual(subtopic_sources.attachment_sources(record, detail_fetcher=detail, collector=Mock()), [])
        detail.assert_not_called()

    def test_exchange_fragment_hash_and_extraction_exclude_siblings(self):
        fragment = "FoaId11111111-1111-1111-1111-111111111111"
        url = "https://arpa-e-foa.energy.gov/Default.aspx#" + fragment
        html = f'<html><div id="{fragment}"><h2>Funding</h2><p>Award range is between $500,000 and $1 million.</p></div><div id="sibling">Sibling gene therapy research.</div></html>'.encode()
        selected = docs.scoped_html(html, url)
        self.assertNotIn(b"gene therapy", selected)
        self.assertEqual(selected, docs.scoped_html(html.replace(b"gene therapy", b"new sibling content"), url))
        with self.assertRaises(ValueError):
            docs.scoped_html(html, url.replace("11111111-", "22222222-", 1))


class IntakeSafety(unittest.TestCase):
    def test_native_url_preview_acceptance_normal_refresh_and_duplicate_trace(self):
        guid = "11111111-1111-1111-1111-111111111111"
        url = "https://arpa-e-foa.energy.gov/#FoaId" + guid
        listing = f'<a href="#FoaId{guid}">DE-FOA-0009999</a><a href="#FoaId{guid}">Official bounded catalyst research</a> Notice Of Funding Opportunity (NOFO) 12/31/2026 05:00 PM ET TBD'
        listing += "".join(listing.replace(guid, guid.replace("11111111-", f"{i:08d}-", 1)).replace("0009999", f"000999{i}")
                           .replace("Notice Of Funding Opportunity (NOFO)", "Request for Information (RFI)") for i in (2, 3))
        with patch.object(docs, "validate_public_url", side_effect=lambda value: value):
            entry, native = intake.preview_url(url, "arpa-e", client=Mock(get_text=Mock(return_value=listing)), as_of=fixture.AS_OF)
        self.assertEqual(native["opportunity_id"], "arpa-e:DE-FOA-0009999")
        self.assertTrue(native["deadlines"][0]["time"])
        self.assertEqual(native["deadlines"][0]["timezone"], "ET")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "accepted.json"
            intake.accept([entry], inputs)
            base = native | {"opportunity_id": "990001", "source": "Grants.gov", "funding_opportunity_url": "https://grants.gov/search-results-detail/990001", "detail_page": "https://grants.gov/search-results-detail/990001"}
            build_catalog.write_catalog(build_catalog.build_catalog([base], fixture.NOW, "fixture", 0), root / "catalog.js")
            with patch.object(PoliteClient, "get_text", return_value=listing):
                summary = integrate(catalog_path=root / "catalog.js", cache_path=root / "sources.json", intake_path=inputs,
                                    adapters=[intake.supported_adapter("arpa-e"), intake.MaintainedInputs()], write=True)
            self.assertEqual(summary["intake"][0]["state"], "canonical")
            self.assertEqual(summary["intake"][0]["opportunity_ids"], ["990001"])
            self.assertEqual(summary["stats"]["final_count"], 1)
        with self.assertRaisesRegex(ValueError, "supports"):
            intake.supported_adapter("sample")
        with patch.object(docs, "validate_public_url", side_effect=lambda value: value), self.assertRaisesRegex(ValueError, "exactly one"):
            intake.preview_url(url + "wrong", "arpa-e", client=Mock(get_text=Mock(return_value=listing)), as_of=fixture.AS_OF)

    def test_manifest_unknowns_quotes_and_strict_schema(self):
        entry = fixture.manifest_entry()
        row = intake.validate_record(entry, as_of=fixture.AS_OF, verify_quotes=True,
            fetcher=lambda url: fixture.response(url, fixture.html_notice(entry)))
        self.assertIsNone(row["award_ceiling"])
        for key, value in [("award_ceiling", True), ("award_floor", float("nan")), ("close_date", "tomorrow"),
                           ("external_id", "../unsafe"), ("extra", {"auto_proposable": True}), ("title", "")]:
            invalid = deepcopy(entry)
            invalid["opportunity"][key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                intake.validate_record(invalid, as_of=fixture.AS_OF)
        invalid = deepcopy(entry)
        del invalid["opportunity"]["award_ceiling"]
        with self.assertRaisesRegex(ValueError, "null"):
            intake.validate_record(invalid, as_of=fixture.AS_OF)
        invalid = deepcopy(entry)
        invalid["citations"]["title"]["quote"] = "This quote is not present in the official document."
        with self.assertRaisesRegex(ValueError, "not found"):
            intake.validate_record(invalid, as_of=fixture.AS_OF, verify_quotes=True,
                fetcher=lambda url: fixture.response(url, fixture.html_notice(entry)))

    def test_unsafe_maintained_urls_fail_even_without_dns(self):
        for url in ["file:///notice", "http://localhost/a", "http://127.0.0.1/a", "http://[::1]/", "http://169.254.169.254/latest",
                    "http://10.1.2.3/", "https://user:secret@example.gov/a", "https://example.gov:8080/a", "https://grantforward.com/a"]:
            with self.subTest(url=url), self.assertRaises((ValueError, RuntimeError)):
                intake.public_source_url(url, resolve=False)

    def test_shared_fetch_blocks_redirects_private_dns_and_credentials(self):
        for address in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"]:
            with self.subTest(address=address), self.assertRaises(RuntimeError):
                docs.validate_public_url("https://agency.example/", resolver=lambda *a: [(None, None, None, None, (address, 443))])
        response = Mock(status_code=302, headers={"Location": "http://127.0.0.1/admin"})
        session = Mock()
        session.get.return_value = response
        with patch("scripts.extract_document_evidence.validate_public_url", side_effect=["https://agency.example/", RuntimeError("private")]):
            with self.assertRaises(RuntimeError):
                docs.download_document("https://agency.example/", headers={"Authorization": "secret", "Cookie": "secret"}, session=session)
        self.assertEqual(session.get.call_count, 1)
        sent = session.get.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", sent)
        self.assertNotIn("Cookie", sent)
        response.close.assert_called()

    def test_size_and_schema_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intake.json"
            for value in [{"schema_version": True, "entries": []}, {"schema_version": 1, "entries": [{}] * 21}, {"schema_version": 1, "entries": [], "extra": True}]:
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(ValueError):
                    intake.load_inputs(path)
            path.write_bytes(b" " * (intake.MAX_MANIFEST_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "size"):
                intake.load_inputs(path)

    def test_shared_fetch_is_anonymous_bounded_and_preserves_notice_fragment(self):
        redirect = Mock(status_code=302, headers={"Location": "/current"})
        response = Mock(status_code=200, headers={"Content-Type": "text/html"}, encoding="utf-8")
        response.iter_content.return_value = [b"notice"]
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = [redirect, response]
        with patch.object(docs.requests, "Session", return_value=session), patch.object(docs, "validate_public_url", side_effect=lambda value: value):
            result = docs.download_document("https://agency.example/old#notice")
        self.assertFalse(session.trust_env)
        self.assertEqual(result["url"], "https://agency.example/current#notice")
        self.assertEqual(result["content"], b"notice")
        session.__exit__.assert_called_once()
        for headers, chunks in [({"Content-Length": "100"}, []), ({}, [b"123", b"456"])]:
            response = Mock(status_code=200, headers=headers)
            response.iter_content.return_value = chunks
            with patch.object(docs, "validate_public_url", side_effect=lambda value: value), self.assertRaisesRegex(RuntimeError, "limit"):
                docs.download_document("https://agency.example/notice", session=Mock(get=Mock(return_value=response)), maximum_bytes=5)
            response.close.assert_called_once()

    def test_distinct_explicit_numbers_survive_same_title_and_duplicate_precedence(self):
        first = intake.validate_record(fixture.manifest_entry(), as_of=fixture.AS_OF)
        other = intake.validate_record(fixture.manifest_entry("second"), as_of=fixture.AS_OF)
        self.assertEqual(len(merge_records([first], [other])[0]), 2)
        duplicate = deepcopy(first) | {"opportunity_id": "990001", "source": "Grants.gov", "award_ceiling": 1234}
        merged, _ = merge_records([duplicate], [first, other])
        self.assertEqual(len(merged), 2)
        self.assertEqual(next(r for r in merged if r["opportunity_id"] == "990001")["award_ceiling"], 1234)

    def test_unavailable_source_does_not_emit_false_withdrawal_but_verified_removal_does(self):
        row = intake.validate_record(fixture.manifest_entry(), as_of=fixture.AS_OF)
        previous = {"opportunities": [row]}
        for state in ("failed_no_fallback", "failed_kept_last_good", "unhealthy_no_fallback"):
            current = {"opportunities": [], "diagnostics": {"additional_sources": {"lifecycle": [{"slug": "maintained", "source": row["source"], "status": state, "healthy": False}]}}}
            self.assertEqual(build_changes.diff_catalogs(previous, current, as_of=fixture.AS_OF), [])
        current["diagnostics"]["additional_sources"]["lifecycle"][0].update(status="refreshed", healthy=True)
        self.assertEqual(build_changes.diff_catalogs(previous, current, as_of=fixture.AS_OF)[0]["type"], "closed_or_removed")
        current["diagnostics"]["additional_sources"]["lifecycle"][0]["withheld_ids"] = [row["opportunity_id"]]
        self.assertEqual(build_changes.diff_catalogs(previous, current, as_of=fixture.AS_OF), [])


if __name__ == "__main__":
    unittest.main()
