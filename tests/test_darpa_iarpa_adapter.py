"""Offline contracts for official inventories, actionability and site integration."""

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import quote

from scripts.build_catalog import record_identity
from scripts.build_changes import diff_catalogs
from scripts.build_feeds import build_feeds
from scripts.sources.adapters.darpa_iarpa import (
    DARPA, IARPA, DARPA_LIST, IARPA_LIST, DarpaIarpaAdapter, iarpa_inventory,
)
from scripts.sources.merge import merge_records, rebuild_catalog, resolve_live_records
from scripts.sources.registry import REGISTRY, collect


FIXTURES = Path(__file__).parent / "fixtures" / "darpa_iarpa"
AS_OF = date(2026, 9, 5)
QBI = "https://www.darpa.mil/research/programs/quantum-benchmarking-initiative"
IARPA_PROGRAM = "https://www.iarpa.gov/research-programs/example"


def payload():
    return {
        "darpa": json.loads((FIXTURES / "darpa.json").read_text(encoding="utf-8")),
        "iarpa": (FIXTURES / "iarpa_empty.html").read_text(encoding="utf-8"),
        "pages": {url: (FIXTURES / f"{name}.html").read_text(encoding="utf-8") for name, url in [
            ("qbi", QBI), ("shine", "https://www.darpa.mil/research/programs/shine"),
            ("resilient", "https://www.darpa.mil/research/programs/resilient"),
        ]},
    }


def adapter():
    instance = DarpaIarpaAdapter()
    instance.set_context({"as_of": AS_OF})
    return instance


def records(data=None):
    instance = adapter()
    with patch.object(instance, "fetch", return_value=data or payload()):
        return instance.collect()


def with_iarpa():
    """Synthetic open call using the verified IARPA program page structure."""
    data = payload()
    data["iarpa"] = '''<table class="iarpa-table table" id="rs">
      <thead><tr><th>Name</th><th>R&amp;D #</th></tr></thead><tbody>
      <tr><td><a href="/research-programs/example">Example quantum sensing research</a></td>
      <td>IARPA-BAA-26-01</td></tr></tbody></table>'''
    data["pages"][IARPA_PROGRAM] = '''<meta name="description" content="Innovative quantum sensing research.">
      <h2>Solicitation Status</h2>
      <p class="baa_content_block-content baa_content_status">BROAD AGENCY ANNOUNCEMENT (BAA)<br>OPEN</p>
      <a href="https://sam.gov/opp/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/view">IARPA-BAA-26-01</a>
      <h3 class="baa_content_block-label">Proposers' Day Date</h3>
      <p class="baa_content_block-content">September 6, 2026</p>
      <h3 class="baa_content_block-label">Release Date</h3>
      <p class="baa_content_block-content">August 1, 2026</p>
      <h3 class="baa_content_block-label">Proposal Due Date for Initial Round of Selections</h3>
      <p class="baa_content_block-content">September 1, 2026</p>
      <h3 class="baa_content_block-label">Proposal Due Date</h3>
      <p class="baa_content_block-content">October 15, 2026</p>
      <h3 class="baa_content_block-label">Closing Date</h3>
      <p class="baa_content_block-content">December 31, 2026</p>'''
    return data


class InventoryTests(unittest.TestCase):
    def test_single_enabled_adapter_and_live_population(self):
        self.assertEqual(sum(item.slug == "darpa-iarpa" for item in REGISTRY), 1)
        self.assertTrue(adapter().enabled)
        instance = adapter()
        calls = instance.parse(payload())
        self.assertEqual({call.opportunity_number for call in calls}, {
            "DARPA-PA-25-07-06", "DARPA-PA-25-07-04", "DARPA-PA-26-02-02", "DARPA-PA-26-02-01",
        })
        self.assertTrue(instance.diagnostics["iarpa_explicit_empty"])

    def test_exact_program_deadline_overrides_stale_table_and_sibling(self):
        calls = {call["opportunity_number"]: call for call in records()}
        stage_a = calls["DARPA-PA-26-02-02"]
        self.assertEqual(stage_a["close_date"], "2026-11-30")
        self.assertEqual(calls["DARPA-PA-26-02-01"]["close_date"], "2026-12-30")
        self.assertEqual(stage_a["deadlines"][0]["source_url"], QBI)
        self.assertIn("industrial", stage_a["description"])
        self.assertFalse(stage_a["status_verification_required"])
        self.assertIn("sam.gov/opp/", stage_a["detail_page"])

    def test_join_duplicates_and_repeat_collection_keep_stable_ids(self):
        data = payload()
        data["darpa"] *= 2
        self.assertEqual(records(data), records())

    def test_umbrella_events_rfis_and_other_darpa_topics_are_excluded(self):
        data = payload()
        seed = next(row for row in data["darpa"] if row["field_opportunity_number"] == "DARPA-PA-25-07-06" and row["field_body_with_summary"])
        for title in ["RFI: SHINE", "Proposers' Day: SHINE", "Draft SHINE", "Future Program: SHINE", "Industry Day: SHINE"]:
            with self.subTest(title=title):
                data["darpa"] = [{**seed, "title": title}]
                self.assertEqual(records(data), [])
        data["darpa"] = [{**seed, "field_opportunity_number": "DARPA-PA-25-07"}]
        self.assertEqual(records(data), [])

    def test_expired_missing_and_future_open_dates_never_admit_a_call(self):
        for original, replacement in [("Nov. 30, 2026", "Aug. 30, 2026"),
                                      ("Nov. 30, 2026", "TBD"),
                                      ("March 9, 2026", "December 9, 2026")]:
            data = payload()
            data["pages"][QBI] = data["pages"][QBI].replace(original, replacement)
            self.assertNotIn("DARPA-PA-26-02-02", [r["opportunity_number"] for r in records(data)])

    def test_missing_exact_child_block_is_a_source_failure(self):
        data = payload()
        data["pages"][QBI] = data["pages"][QBI].replace("DARPA-PA-26-02-02", "DARPA-PA-26-02-99")
        with self.assertRaisesRegex(ValueError, "exact solicitation"):
            records(data)

    def test_unknown_inventory_shapes_fail_closed(self):
        for html in ["<html>maintenance</html>", '<table id="rs"><th>R&amp;D #</th><tbody></tbody></table>']:
            with self.assertRaises(ValueError):
                iarpa_inventory(html)
        data = payload()
        data["darpa"] = []
        with self.assertRaises(ValueError):
            records(data)

    def test_unofficial_and_non_notice_action_links_are_rejected(self):
        for bad in ["https://sam.gov.evil.test/", "https://sam.gov/search/", "javascript:alert(1)"]:
            data = payload()
            for row in data["darpa"]:
                row["field_external_url"] = bad
            self.assertEqual(records(data), [])

    def test_fetch_is_bounded_to_official_inventories_and_programs(self):
        data = payload()
        pages = {DARPA_LIST: json.dumps(data["darpa"]), IARPA_LIST: data["iarpa"], **data["pages"]}
        instance = adapter()
        with patch.object(instance._client, "get_text", side_effect=pages.__getitem__) as get:
            self.assertEqual(len(instance.collect()), 4)
        self.assertEqual(set(call.args[0] for call in get.call_args_list), set(pages))
        self.assertEqual(get.call_count, 5)


class IarpaTests(unittest.TestCase):
    def test_open_research_call_uses_proposal_date_and_own_sponsor(self):
        call = next(r for r in records(with_iarpa()) if r["agency"] == IARPA)
        self.assertEqual(call["close_date"], "2026-10-15")
        self.assertEqual(call["posted_date"], "2026-08-01")
        self.assertEqual(call["deadlines"][0]["source_url"], IARPA_PROGRAM)
        self.assertEqual(call["source_type"], "Federal")

    def test_closed_draft_rfi_and_event_status_are_not_research_calls(self):
        for status in ["CLOSED", "DRAFT OPEN", "RFI OPEN", "Proposers' Day OPEN"]:
            data = with_iarpa()
            data["pages"][IARPA_PROGRAM] = data["pages"][IARPA_PROGRAM].replace("<br>OPEN", f"<br>{status}")
            self.assertTrue(all(r["agency"] != IARPA for r in records(data)))

    def test_expired_proposal_is_not_revived_by_future_closing_or_event(self):
        data = with_iarpa()
        data["pages"][IARPA_PROGRAM] = data["pages"][IARPA_PROGRAM].replace("October 15, 2026", "August 15, 2026")
        self.assertTrue(all(r["agency"] != IARPA for r in records(data)))

    def test_other_solicitation_link_does_not_confirm_current_row(self):
        data = with_iarpa()
        data["pages"][IARPA_PROGRAM] = data["pages"][IARPA_PROGRAM].replace("IARPA-BAA-26-01", "IARPA-BAA-25-01")
        self.assertTrue(all(r["agency"] != IARPA for r in records(data)))

    def test_page_failure_clears_entire_adapter_snapshot(self):
        instance = adapter()
        with patch.object(instance, "fetch", side_effect=ValueError("IARPA missing")):
            _, results = collect([instance])
        cache = {"sources": {instance.slug: {"records": records(), "fetched_at": "2026-09-04"}}}
        live, updated, summary = resolve_live_records(results, cache, AS_OF)
        self.assertEqual(live, [])
        self.assertEqual(updated["sources"][instance.slug]["records"], [])
        self.assertEqual(summary[0]["status"], "failed_no_fallback")


class IdentityAndIntegrationTests(unittest.TestCase):
    def test_browser_fixture_matches_adapter_records_and_search_index(self):
        catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
        actual = rebuild_catalog({"schema_version": 3}, records(with_iarpa()), [])
        for field in ("opportunities", "search_index", "facets"):
            self.assertEqual(catalog[field], actual[field], field)

    def test_normalized_sponsor_and_number_dedup_preserves_grants_gov(self):
        external = records()[0]
        base = {**external, "source": "Grants.gov", "opportunity_id": "12345",
                "agency": "DARPA - Defense Sciences Office", "opportunity_number": "darpa pa 25 07 06"}
        merged, stats = merge_records([base], [external])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["opportunity_id"], "12345")
        self.assertEqual(merged[0]["source"], "Grants.gov")
        self.assertEqual(stats["external_added"], 0)
        self.assertEqual(record_identity(base), record_identity(external))

    def test_same_number_other_sponsor_and_same_title_other_number_survive(self):
        call = records()[0]
        another_sponsor = {**call, "agency": IARPA, "opportunity_id": "iarpa:other"}
        another_number = {**call, "opportunity_number": "DARPA-PA-25-07-99", "opportunity_id": "darpa:other"}
        unrelated = {**call, "agency": "Department of Energy", "opportunity_id": "doe:other"}
        merged, _ = merge_records([call], [another_sponsor, another_number, unrelated])
        self.assertEqual(len(merged), 4)
        self.assertEqual(len({record_identity(r) for r in merged}), 4)

    def test_snapshot_indexes_facets_feeds_and_alert_events_include_both_sponsors(self):
        calls = records(with_iarpa())
        catalog = rebuild_catalog({"schema_version": 3, "generated_at": "2026-09-05T12:00:00Z"}, calls, [])
        self.assertIn(DARPA, catalog["facets"]["agency"])
        self.assertIn(IARPA, catalog["facets"]["agency"])
        self.assertEqual(catalog["facets"]["source_type"]["Federal"], 5)
        self.assertIn("quantum", catalog["search_index"]["postings"])
        self.assertEqual(len(catalog["search_index"]["document_lengths"]), 5)
        events = diff_catalogs({"opportunities": []}, catalog, as_of=AS_OF)
        self.assertEqual({e["opportunity_id"] for e in events if e["type"] == "new"}, {r["opportunity_id"] for r in calls})
        with TemporaryDirectory() as directory:
            build_feeds(catalog, Path(directory), as_of=AS_OF)
            feed = (Path(directory) / "source-type/federal.xml").read_text(encoding="utf-8")
            for call in calls:
                self.assertIn(quote(call["opportunity_id"], safe=""), feed)
                self.assertIn(call["detail_page"], feed)


if __name__ == "__main__":
    unittest.main()
