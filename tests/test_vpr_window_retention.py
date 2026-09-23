"""Windowed mail is an observation, not a complete sponsor inventory."""
import copy
from datetime import date
import unittest
from unittest.mock import patch

from scripts.build_changes import diff_catalogs
from scripts.sources.adapters.vpr_email import VPREmailAdapter
from scripts.sources.base import CanonicalOpportunity
from scripts.sources.merge import resolve_live_records, rebuild_catalog, merge_records
from scripts.sources.registry import AdapterResult, collect
from scripts.submission_schedule import next_submission


DAY = date(2026, 9, 23)
SOURCE = VPREmailAdapter.display_name


def row(ident, close_date="2026-09-28", **fields):
    value = CanonicalOpportunity(title=f"Research award {ident}", external_id=ident,
        url=f"https://sponsor.example/{ident}", close_date=close_date).to_record(
            slug="vpr-email", source=SOURCE, source_type="Internal")
    return {**value, **fields}


def cache(*records):
    return {"schema_version": 1, "sources": {"vpr-email": {
        "source": SOURCE, "source_type": "Internal",
        "fetched_at": "2026-09-07T12:00:00Z", "records": list(records)}}}


def observed(*records, **fields):
    return AdapterResult(slug="vpr-email", display_name=SOURCE,
        source_type="Internal", ok=True, records=list(records),
        record_count=len(records), min_records=1, max_records=500,
        snapshot_complete=False, **fields)


class WindowLifecycle(unittest.TestCase):
    def test_rotation_keeps_future_record_and_actual_observation_dates(self):
        old = row("old", source_first_seen_date="2026-08-09")
        original = copy.deepcopy(old)
        live, saved, summaries = resolve_live_records(
            [observed(row("fresh"))], cache(old), DAY)
        kept = next(r for r in live if r["opportunity_id"] == old["opportunity_id"])
        self.assertEqual(old, original)
        self.assertEqual({k: kept[k] for k in old}, old)
        self.assertEqual(kept["source_last_seen_date"], "2026-09-07")
        self.assertEqual(kept["source_observation"], "retained_outside_window")
        self.assertEqual(live[0]["source_last_seen_date"], "2026-09-23")
        self.assertEqual(summaries[0]["retained_outside_window_ids"], [old["opportunity_id"]])
        self.assertFalse(summaries[0]["snapshot_complete"])
        # Another successful window cannot turn the carried observation fresh.
        again, _, _ = resolve_live_records([observed(row("fresh"))], saved, date(2026, 9, 24))
        self.assertEqual(again[-1]["source_last_seen_date"], "2026-09-07")

    def test_deadline_inclusive_then_expires_without_reopening(self):
        old = row("old", close_date="2026-09-23")
        self.assertEqual(len(resolve_live_records([observed(row("fresh"))], cache(old), DAY)[0]), 2)
        self.assertEqual(len(resolve_live_records([observed(row("fresh"))], cache(old), date(2026, 9, 24))[0]), 1)

    def test_new_deadline_and_identity_fields_supersede_the_old_row(self):
        old = row("same", agency="Earlier sponsor")
        changed = row("same", close_date="2026-10-20", agency="Correct sponsor")
        live, _, _ = resolve_live_records([observed(changed)], cache(old), DAY)
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["close_date"], "2026-10-20")
        self.assertEqual(live[0]["agency"], "Correct sponsor")

    def test_only_newly_expired_or_withdrawn_observations_are_healthy_and_durable(self):
        for fields in ({"close_date": "2026-09-22"}, {"status": "withdrawn"},
                       {"status": "cancelled"}, {"status": "closed"}):
            with self.subTest(fields=fields):
                old = row("same")
                live, saved, summaries = resolve_live_records([observed(row("same", **fields))], cache(old), DAY)
                self.assertEqual(live, [])
                self.assertTrue(summaries[0]["healthy"])
                self.assertEqual(saved["sources"]["vpr-email"]["records"], [])
                later, _, _ = resolve_live_records([observed(row("new"))], saved, DAY)
                self.assertNotIn(old["opportunity_id"], [r["opportunity_id"] for r in later])

    def test_internal_prerequisite_and_undated_verification_do_not_change(self):
        limited = row("limited", close_date="2027-01-19", limited_submission=True,
            deadlines=[{"kind": "application", "date": "2027-01-19"},
                       {"kind": "internal", "date": "2026-08-21"}])
        undated = row("undated", close_date=None)
        live, _, _ = resolve_live_records([observed(row("fresh"))], cache(limited, undated), DAY)
        kept = {r["opportunity_id"]: r for r in live}
        self.assertEqual(next_submission(kept[limited["opportunity_id"]], DAY)["access"], "prerequisite_closed")
        self.assertTrue(kept[undated["opportunity_id"]]["status_verification_required"])
        self.assertIsNone(kept[undated["opportunity_id"]]["close_date"])

    def test_duplicate_prior_identity_is_carried_once_and_refreshed_alias_wins(self):
        old = row("old", opportunity_number="TEST-26-01", agency="Test sponsor", agency_authority="source_listed")
        duplicate = dict(old)
        live, _, _ = resolve_live_records([observed(row("fresh"))], cache(old, duplicate), DAY)
        self.assertEqual([r["opportunity_id"] for r in live].count(old["opportunity_id"]), 1)
        alias = dict(old, opportunity_id="vpr-email:replacement")
        # Same canonical source-owned number means the new alias supersedes it.
        live, _, _ = resolve_live_records([observed(alias)], cache(old), DAY)
        self.assertEqual([r["opportunity_id"] for r in live], [alias["opportunity_id"]])

    def test_newest_cached_version_wins_before_currentness_filtering(self):
        old = row("same", close_date="2026-09-28", description="Old scope")
        latest = row("same", close_date="2026-10-20", description="Revised scope")
        live, _, _ = resolve_live_records([observed(row("other"))], cache(old, latest), DAY)
        kept = next(r for r in live if r["opportunity_id"] == old["opportunity_id"])
        self.assertEqual(kept["close_date"], latest["close_date"])
        self.assertEqual(kept["description"], latest["description"])
        for terminal in (dict(latest, close_date="2026-09-22"), dict(latest, status="withdrawn"),
                         dict(latest, detail_page=None, funding_opportunity_url=None)):
            live, _, _ = resolve_live_records([observed(row("other"))], cache(old, terminal), DAY)
            self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:other"])

    def test_latest_fresh_version_controls_real_merge_and_closure_feed(self):
        old = row("same")
        baseline = rebuild_catalog({}, [old], [], [])
        for latest in (dict(old, close_date="2026-10-20"), dict(old, status="withdrawn"),
                       dict(old, close_date="2026-09-22")):
            with self.subTest(latest=latest):
                result = observed(old, latest)
                live, saved, lifecycle = resolve_live_records([result], cache(old), DAY)
                combined, _ = merge_records([], live)
                actual = rebuild_catalog(baseline, combined, [result], lifecycle)
                events = diff_catalogs(baseline, actual, as_of=DAY)
                if latest.get("status") == "withdrawn" or latest["close_date"] < DAY.isoformat():
                    self.assertEqual(actual["opportunities"], [])
                    self.assertEqual(len([e for e in events if e["type"] == "closed_or_removed"]), 1)
                else:
                    self.assertEqual(len(actual["opportunities"]), 1)
                    self.assertEqual(actual["opportunities"][0]["close_date"], "2026-10-20")
                self.assertEqual(len(saved["sources"]["vpr-email"]["records"]), len(live))

    def test_current_reopening_supersedes_earlier_terminal_and_invalid_versions(self):
        latest = row("same", close_date="2026-10-20")
        for old in (dict(latest, status="withdrawn"), dict(latest, detail_page=None, funding_opportunity_url=None)):
            live, _, life = resolve_live_records([observed(old, latest)], cache(old), DAY)
            self.assertEqual(len(live), 1)
            self.assertEqual(live[0]["status"], "posted")
            self.assertEqual(life[0]["observed_terminal_records"], [])

    def test_colliding_programs_are_withheld_without_guessing_or_claiming_closure(self):
        old = row("same", title="Example Foundation", description="First program")
        conflict = dict(old, detail_page="https://sponsor.example/other-program", description="Different program",
                        close_date="2026-10-20")
        baseline = rebuild_catalog({}, [old], [], [])
        live, saved, life = resolve_live_records([observed(old, conflict, row("fresh"))], cache(old), DAY)
        self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:fresh"])
        self.assertEqual(life[0]["identity_collision_ids"], ["vpr-email:same"])
        actual = rebuild_catalog(baseline, live, [], life)
        self.assertFalse(any(e["type"] == "closed_or_removed" for e in diff_catalogs(baseline, actual, as_of=DAY)))
        later, _, _ = resolve_live_records([observed(row("new"))], saved, DAY)
        self.assertNotIn(old["opportunity_id"], [r["opportunity_id"] for r in later])
        self.assertEqual(conflict["description"], "Different program")

    def test_tracking_and_documented_number_title_aliases_allow_genuine_revision(self):
        old = row("same", detail_page="http://www.sponsor.example/program/?utm_source=old")
        latest = dict(old, detail_page="https://sponsor.example/program#deadline", close_date="2026-10-20")
        live, _, life = resolve_live_records([observed(old, latest)], cache(old), DAY)
        self.assertEqual(live[0]["close_date"], "2026-10-20")
        self.assertEqual(life[0]["identity_collision_ids"], [])
        numbered = dict(old, opportunity_number="EX-2026-001", agency="Example agency", agency_authority="source_listed")
        revision = dict(numbered, detail_page="https://sponsor.example/notices/revision-2", close_date="2026-10-21")
        live, _, _ = resolve_live_records([observed(numbered, revision)], cache(numbered), DAY)
        self.assertEqual(live[0]["close_date"], "2026-10-21")

    def test_collisions_and_terminal_versions_are_not_republished_from_failed_cache(self):
        old = row("same")
        for latest in (dict(old, status="withdrawn"), dict(old, detail_page="https://sponsor.example/different-program")):
            failure = observed(); failure.ok = False
            live, _, _ = resolve_live_records([failure], cache(old, latest), DAY)
            self.assertEqual(live, [])
            live, _, _ = resolve_live_records([observed(row("other"))], cache(old, latest), DAY)
            self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:other"])

    def test_cached_identity_precedes_fresh_supersession_and_terminal_feed(self):
        old = row("same", title="Shared foundation")
        baseline = rebuild_catalog({}, [old], [], [])
        for state in ("posted", "withdrawn", "closed"):
            conflict = dict(old, detail_page="https://sponsor.example/different-program", status=state)
            live, saved, life = resolve_live_records([observed(conflict)], cache(old), DAY)
            self.assertEqual(live, [])
            self.assertEqual(life[0]["identity_collision_ids"], [old["opportunity_id"]])
            self.assertEqual(life[0]["observed_terminal_records"], [])
            actual = rebuild_catalog(baseline, live, [], life)
            self.assertFalse(any(e["type"] == "closed_or_removed" for e in diff_catalogs(baseline, actual, as_of=DAY)))
            self.assertEqual(len(saved["sources"]["vpr-email"]["identity_witnesses"]["observations"]), 2)

    def test_collision_witnesses_survive_rotation_failures_and_no_fallback(self):
        old = row("same")
        conflict = dict(old, detail_page="https://sponsor.example/other-program")
        for retain in (True, False):
            live, saved, _ = resolve_live_records([observed(old, conflict)], cache(), DAY)
            self.assertEqual(live, [])
            witness = copy.deepcopy(saved["sources"]["vpr-email"]["identity_witnesses"])
            failure = observed(); failure.ok = False; failure.retain_on_failure = retain
            live, saved, _ = resolve_live_records([failure], saved, DAY)
            self.assertEqual(live, [])
            self.assertEqual(saved["sources"]["vpr-email"]["identity_witnesses"], witness)
            for fresh in (conflict, old, dict(conflict, status="withdrawn")):
                live, saved, life = resolve_live_records([observed(fresh)], saved, DAY)
                self.assertEqual(live, [])
                self.assertEqual(life[0]["identity_collision_ids"], [old["opportunity_id"]])
                self.assertEqual(saved["sources"]["vpr-email"]["identity_witnesses"], witness)

    def test_terminal_clear_keeps_identity_but_allows_same_program_reopening(self):
        old = row("same")
        live, saved, _ = resolve_live_records([observed(dict(old, status="withdrawn"))], cache(old), DAY)
        self.assertEqual(live, [])
        self.assertEqual(saved["sources"]["vpr-email"]["records"], [])
        reopened, _, _ = resolve_live_records([observed(old)], copy.deepcopy(saved), DAY)
        self.assertEqual(len(reopened), 1)
        conflict = dict(old, detail_page="https://sponsor.example/another-program")
        live, _, life = resolve_live_records([observed(conflict)], saved, DAY)
        self.assertEqual(live, [])
        self.assertEqual(life[0]["identity_collision_ids"], [old["opportunity_id"]])

    def test_verified_official_alias_can_resolve_retained_ambiguity(self):
        url = "https://simpler.grants.gov/opportunity/12345678-1234-1234-1234-123456789abc"
        old = row("same", detail_page=url, funding_opportunity_url=url)
        official = "https://www.grants.gov/search-results-detail/123456"
        linked = dict(old, detail_page=official, funding_opportunity_url=official)
        live, saved, _ = resolve_live_records([observed(linked)], cache(old), DAY)
        self.assertEqual(live, [])
        # A retained source receipt proves the earlier URL's exact official ID.
        mapped = dict(old, official_identity={"version": 1, "source_url": url,
            "target_url": official, "utf8_sha256": "a" * 64,
            "retrieved_at": "2026-09-23T12:00:00Z",
            "locator": "View on Grants.gov / version-history anchor"})
        live, saved, life = resolve_live_records([observed(mapped, linked)], saved, DAY)
        self.assertEqual(len(live), 1)
        self.assertEqual(life[0]["identity_collision_ids"], [])
        self.assertEqual(len(saved["sources"]["vpr-email"]["identity_witnesses"]["observations"]), 3)
        later, _, _ = resolve_live_records([observed(linked)], saved, DAY)
        self.assertEqual(len(later), 1)

    def test_contradictory_official_ids_are_not_resolved_by_number_and_title(self):
        old = row("same", opportunity_number="EX-26-001", agency="Example agency", agency_authority="source_listed",
            detail_page="https://www.grants.gov/search-results-detail/123456", funding_opportunity_url=None)
        conflict = dict(old, detail_page="https://www.grants.gov/search-results-detail/654321")
        live, _, _ = resolve_live_records([observed(conflict)], cache(old), DAY)
        self.assertEqual(live, [])

    def test_witness_capacity_and_malformed_history_fail_before_cache_mutation(self):
        for saved in (cache(row("old")), cache()):
            if not saved["sources"]["vpr-email"]["records"]:
                saved["sources"]["vpr-email"]["identity_witnesses"] = {"version": True, "observations": []}
            original = copy.deepcopy(saved)
            with patch("scripts.sources.merge.IDENTITY_WITNESS_LIMIT", 1):
                with self.assertRaisesRegex(ValueError, "identity witness"):
                    resolve_live_records([observed(row("new"))], saved, DAY)
            self.assertEqual(saved, original)

    def test_invalid_only_window_durably_suppresses_without_false_refresh(self):
        old = row("same")
        invalid = dict(old, detail_page=None, funding_opportunity_url=None)
        one, saved, summaries = resolve_live_records([observed(invalid)], cache(old), DAY)
        self.assertEqual(one, [])
        self.assertFalse(summaries[0]["healthy"])
        self.assertEqual(saved["sources"]["vpr-email"]["records"], [])
        self.assertEqual(saved["sources"]["vpr-email"]["fetched_at"], "2026-09-07T12:00:00Z")
        self.assertEqual(saved["sources"]["vpr-email"]["last_successful_refresh_at"], "2026-09-07T12:00:00Z")
        two, _, _ = resolve_live_records([observed(row("other"))], saved, DAY)
        self.assertEqual([r["opportunity_id"] for r in two], ["vpr-email:other"])

    def test_unsafe_old_record_and_invalid_fresh_replacement_are_not_carried(self):
        old = row("same")
        invalid = dict(row("same"), close_date="not-a-date")
        bad_old = row("unsafe", detail_page=None, funding_opportunity_url=None)
        live, _, _ = resolve_live_records([observed(invalid, row("fresh"))], cache(old, bad_old), DAY)
        self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:fresh"])

    def test_combined_capacity_overflow_never_truncates_or_mutates_cache(self):
        saved = cache(row("old")); before = copy.deepcopy(saved)
        result = observed(row("fresh")); result.max_records = 1
        with self.assertRaisesRegex(ValueError, "incremental snapshot exceeds"):
            resolve_live_records([result], saved, DAY)
        self.assertEqual(saved, before)

    def test_complete_source_still_replaces_its_snapshot(self):
        result = observed(row("fresh")); result.snapshot_complete = True
        live, _, summaries = resolve_live_records([result], cache(row("old")), DAY)
        self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:fresh"])
        self.assertNotIn("snapshot_complete", summaries[0])
        self.assertNotIn("source_last_seen_date", live[0])

    def test_failed_window_preserves_current_cache_without_claiming_refresh(self):
        result = observed(); result.ok = False; result.error = "required stream absent"
        live, _, summaries = resolve_live_records([result], cache(row("old"), row("expired", close_date="2026-09-22")), DAY)
        self.assertEqual([r["opportunity_id"] for r in live], ["vpr-email:old"])
        self.assertFalse(summaries[0]["snapshot_complete"])
        self.assertFalse(summaries[0]["healthy"])
        self.assertEqual(summaries[0]["status"], "failed_kept_last_good")

    def test_registry_carries_declared_completeness_on_success_and_failure(self):
        class Window(VPREmailAdapter):
            def collect(self):
                return [row("new")]
        class Failed(Window):
            def collect(self):
                raise ValueError("changed email format")
        for adapter in (Window(), Failed()):
            _, results = collect(adapters=[adapter])
            self.assertFalse(results[0].snapshot_complete)


class WindowChanges(unittest.TestCase):
    def catalogs(self, previous, current, complete=False):
        result = observed(*current); result.snapshot_complete = complete
        lifecycle = [{"slug": "vpr-email", "source": SOURCE, "status": "refreshed", "healthy": True,
                      **({"snapshot_complete": False} if not complete else {})}]
        base = {"opportunities": previous, "generated_at": "2026-09-23T12:00:00Z"}
        return base, rebuild_catalog(base, current, [result], lifecycle)

    def test_absence_from_incremental_scan_never_creates_a_closure(self):
        for deadline in ("2026-09-28", None):
            for complete in (False, True):
                before, after = self.catalogs([row("old", close_date=deadline)], [], complete)
                events = diff_catalogs(before, after, as_of=DAY)
                closed = [e for e in events if e["type"] == "closed_or_removed"]
                self.assertEqual(bool(closed), complete)

    def test_independently_elapsed_deadline_still_closes_after_window_rotation(self):
        before, after = self.catalogs([row("old", close_date="2026-09-22")], [])
        events = diff_catalogs(before, after, as_of=DAY)
        self.assertEqual([e["type"] for e in events], ["closed_or_removed"])

    def test_explicit_terminal_current_record_is_not_suppressed_by_incomplete_scan(self):
        before, after = self.catalogs([row("old")], [row("old", status="withdrawn")])
        events = diff_catalogs(before, after, as_of=DAY)
        self.assertEqual([e["type"] for e in events], ["closed_or_removed"])
        self.assertEqual(events[0]["record"]["status"], "withdrawn")

    def test_filtered_terminal_observation_closes_through_the_actual_lifecycle(self):
        for fields in ({"status": "withdrawn"}, {"status": "closed"}, {"close_date": "2026-09-22"}):
            with self.subTest(fields=fields):
                old, fresh = row("old"), row("old", **fields)
                result = observed(fresh)
                live, _, lifecycle = resolve_live_records([result], cache(old), DAY)
                self.assertEqual(live, [])
                before = {"opportunities": [old], "generated_at": "2026-09-23T12:00:00Z"}
                after = rebuild_catalog(before, live, [result], lifecycle)
                events = diff_catalogs(before, after, as_of=DAY)
                self.assertEqual([e["type"] for e in events], ["closed_or_removed"])
                for key in ("status", "close_date", "deadlines"):
                    self.assertEqual(events[0]["record"][key], fresh[key])

    def test_terminal_observed_alias_closes_prior_canonical_identity(self):
        old = row("old", opportunity_number="TEST-26-01", agency="Test sponsor", agency_authority="source_listed")
        fresh = dict(old, opportunity_id="vpr-email:new-alias", status="withdrawn")
        result = observed(fresh)
        live, _, lifecycle = resolve_live_records([result], cache(old), DAY)
        before = {"opportunities": [old], "generated_at": "2026-09-23T12:00:00Z"}
        events = diff_catalogs(before, rebuild_catalog(before, live, [result], lifecycle), as_of=DAY)
        self.assertEqual([(e["opportunity_id"], e["record"]["status"]) for e in events], [(old["opportunity_id"], "withdrawn")])


if __name__ == "__main__":
    unittest.main()
