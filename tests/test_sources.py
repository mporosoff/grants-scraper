"""Regression tests for the modular multi-source ingestion layer.

These prove the layer drops into the existing pipeline cleanly:
- external records carry every field a Grants.gov record has (so the browser,
  BM25 index, and facets treat them identically);
- the canonical model derives topics and LOI/limited/early-career signals;
- merging never overrides Grants.gov and de-duplicates safely;
- one broken adapter cannot abort collection;
- merged records index and facet correctly and survive a write/read round-trip.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_catalog import (
    build_catalog,
    iter_catalog_records,
    record_identity,
)
from scripts.sources.base import CanonicalOpportunity, SourceAdapter
from scripts.sources.registry import AdapterResult, collect
from scripts.sources.merge import (
    integrate,
    load_catalog,
    load_source_cache,
    merge_records,
    rebuild_catalog,
    resolve_live_records,
    save_catalog,
)
from scripts.sources.validate import (
    filter_publishable,
    record_is_publishable,
    within_health_bounds,
)
from scripts.sources.adapters.rss import RSSAdapter
from scripts.sources.adapters.sample import SampleFixtureAdapter
from scripts.sources.__main__ import summary_is_degraded

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "grants_db_extract.xml"


def a_base_record():
    with FIXTURE.open("rb") as stream:
        records = list(iter_catalog_records(stream, date(2026, 7, 25)))
    return next(r for r in records if r["status"] == "posted")


def an_external_record(**overrides):
    opp = CanonicalOpportunity(
        external_id=overrides.pop("external_id", "PON-1"),
        title=overrides.pop("title", "Carbon capture catalysis pilot"),
        url=overrides.pop("url", "https://example.org/pon-1"),
        description=overrides.pop("description", "A demonstration award."),
        **overrides,
    )
    return opp.to_record(slug="demo", source="Demo Source", source_type="State")


class SchemaParityTests(unittest.TestCase):
    def test_external_record_has_every_grants_gov_field(self):
        base_keys = set(a_base_record().keys())
        external_keys = set(an_external_record().keys())
        missing = base_keys - external_keys
        self.assertEqual(missing, set(), f"external record missing fields: {missing}")

    def test_derives_topics_and_signals(self):
        record = an_external_record(
            title="Early-career award: carbon capture and utilization",
            description=(
                "A letter of intent is required. Limited to one application "
                "per institution."
            ),
        )
        self.assertIn("Carbon management", record["topic_areas"])
        self.assertTrue(record["has_preliminary_stage"])
        self.assertTrue(record["limited_submission"])
        self.assertTrue(record["career_stage_signal"])

    def test_ids_are_namespaced_and_do_not_collide(self):
        record = an_external_record()
        self.assertEqual(record["opportunity_id"], "demo:PON-1")
        self.assertTrue(record_identity(record).startswith("id:demo:"))

    def test_close_date_and_missing_date_behaviour(self):
        dated = an_external_record(close_date="09/15/2026")
        self.assertEqual(dated["close_date"], "2026-09-15")
        self.assertFalse(dated["status_verification_required"])
        undated = an_external_record(close_date=None)
        self.assertIsNone(undated["close_date"])
        self.assertTrue(undated["status_verification_required"])


class MergeTests(unittest.TestCase):
    def test_adds_distinct_records(self):
        base = [a_base_record()]
        external = [an_external_record(external_id="X1", title="Membrane separations grant")]
        combined, stats = merge_records(base, external)
        self.assertEqual(stats["external_added"], 1)
        self.assertEqual(len(combined), 2)

    def test_never_overrides_grants_gov_and_is_idempotent(self):
        base = [a_base_record()]
        external = [an_external_record(external_id="X1")]
        combined, _ = merge_records(base, external)
        # Re-merging the same external record adds nothing.
        combined2, stats2 = merge_records(combined, external)
        self.assertEqual(stats2["external_added"], 0)
        self.assertEqual(stats2["dropped_duplicate_identity"], 1)
        self.assertEqual(len(combined2), len(combined))

    def test_drops_cross_source_duplicate_of_base(self):
        base_record = a_base_record()
        base = [base_record]
        clash = an_external_record(
            external_id="DUP",
            title=base_record["title"],
            close_date=base_record["close_date"],
        )
        _, stats = merge_records(base, [clash])
        self.assertEqual(stats["external_added"], 0)
        self.assertEqual(stats["dropped_cross_source_duplicate"], 1)

    def test_drops_cross_source_duplicate_by_opportunity_number(self):
        base_record = a_base_record()
        clash = an_external_record(
            external_id="SOURCE-ID",
            title="Different source title for the same solicitation",
            opportunity_number=base_record["opportunity_number"],
        )
        _, stats = merge_records([base_record], [clash])
        self.assertEqual(stats["external_added"], 0)
        self.assertEqual(stats["dropped_duplicate_identity"], 1)

    def test_catalog_wins_when_email_adds_an_nsf_prefix_to_the_number(self):
        base_record = {
            **a_base_record(),
            "opportunity_number": "26-511",
            "title": "NSF Small Business Innovation Research Phase I",
        }
        email_copy = an_external_record(
            external_id="NSF26-511",
            opportunity_number="NSF26-511",
            title="NEW NSF Small Business Innovation Research Phase I | NSF 26-511",
        )

        combined, stats = merge_records([base_record], [email_copy])

        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["source"], "Grants.gov")
        self.assertEqual(stats["dropped_cross_source_duplicate"], 1)

    def test_catalog_wins_when_email_title_only_adds_sponsor_and_acronym(self):
        base_record = {
            **a_base_record(),
            "opportunity_number": None,
            "title": "Mathematical Foundations of Artificial Intelligence",
        }
        email_copy = an_external_record(
            external_id="digest-copy",
            title=(
                "NSF Mathematical Foundations of Artificial Intelligence "
                "(MFAI) 24-569"
            ),
        )

        combined, stats = merge_records([base_record], [email_copy])

        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["source"], "Grants.gov")
        self.assertEqual(stats["dropped_cross_source_duplicate"], 1)


class RegistryTests(unittest.TestCase):
    def test_one_broken_adapter_does_not_stop_the_others(self):
        class Good(SourceAdapter):
            slug, display_name, enabled = "good", "Good", True

            def fetch(self):
                return [1]

            def parse(self, payload):
                return [CanonicalOpportunity(external_id="g1", title="Good grant")]

        class Broken(SourceAdapter):
            slug, display_name, enabled = "broken", "Broken", True

            def fetch(self):
                raise RuntimeError("network down")

            def parse(self, payload):
                return []

        records, results = collect(adapters=[Good(), Broken()])
        self.assertEqual(len(records), 1)
        by_slug = {r.slug: r for r in results}
        self.assertTrue(by_slug["good"].ok)
        self.assertFalse(by_slug["broken"].ok)
        self.assertIn("network down", by_slug["broken"].error)

    def test_disabled_adapters_are_skipped_by_default(self):
        records, results = collect(adapters=[SampleFixtureAdapter()])
        self.assertEqual(records, [])
        self.assertEqual(results, [])
        records, results = collect(
            adapters=[SampleFixtureAdapter()], include_disabled=True
        )
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r.ok for r in results))


class SourceHealthExitTests(unittest.TestCase):
    def test_summary_reports_enabled_source_degradation(self):
        healthy = {
            "validation": {"ok": True},
            "sources": [{"status": "refreshed"}],
        }
        failed = {
            "validation": {"ok": True},
            "sources": [{"status": "failed_kept_last_good"}],
        }
        unhealthy = {
            "validation": {"ok": True},
            "sources": [{"status": "unhealthy_kept_last_good"}],
        }
        recent_snapshot = {
            "validation": {"ok": True},
            "sources": [{"status": "recent_snapshot"}],
        }
        invalid = {"validation": {"ok": False}, "sources": []}
        self.assertFalse(summary_is_degraded(healthy))
        self.assertFalse(summary_is_degraded(recent_snapshot))
        self.assertTrue(summary_is_degraded(failed))
        self.assertTrue(summary_is_degraded(unhealthy))
        self.assertTrue(summary_is_degraded(invalid))


class RSSTests(unittest.TestCase):
    FEED = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Foundation X Invites Proposals for Water Research</title>
        <link>https://example.org/rfp/1</link>
        <description>Grants up to $75,000. Deadline: September 30, 2026.</description>
        <pubDate>Mon, 06 Jul 2026 12:00:00 +0000</pubDate>
        <guid>rfp-1</guid>
      </item>
    </channel></rss>"""

    def test_parses_items_and_extracts_deadline(self):
        opportunities = RSSAdapter().parse_feed(self.FEED)
        self.assertEqual(len(opportunities), 1)
        record = opportunities[0].to_record(
            slug="feed", source="Feed", source_type="Foundation"
        )
        self.assertIn("Water", record["title"])
        self.assertEqual(record["close_date"], "2026-09-30")
        self.assertEqual(record["posted_date"], "2026-07-06")

    def test_repairs_bare_ampersand_and_accepts_deadline_date_label(self):
        feed = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Integrated Data Systems & Services</title>
          <link>https://example.org/idss</link>
          <description><![CDATA[
            Full Proposal Deadline Date: July 28, 2026
          ]]></description>
        </item></channel></rss>"""
        opportunities = RSSAdapter().parse_feed(feed)
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(
            opportunities[0].title,
            "Integrated Data Systems & Services",
        )
        self.assertEqual(opportunities[0].close_date, "July 28, 2026")


class RebuildAndRoundTripTests(unittest.TestCase):
    def _base_catalog(self):
        from scripts.build_catalog import read_archive
        from zipfile import ZipFile

        with TemporaryDirectory() as directory:
            archive = Path(directory) / "extract.zip"
            with ZipFile(archive, "w") as zf:
                zf.write(FIXTURE, arcname="fixture.xml")
            records, deduped = read_archive(archive, date(2026, 7, 25))
        return build_catalog(
            records, datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
            "fixture.zip", deduped,
        ), records

    def test_rebuild_indexes_and_facets_external_records(self):
        catalog, base = self._base_catalog()
        external = [an_external_record(
            external_id="Z1",
            title="Photonics fellowship at Example Institute",
            agency="Example Institute",
        )]
        combined, _ = merge_records(base, external)
        rebuilt = rebuild_catalog(catalog, combined, results=[])

        self.assertEqual(rebuilt["record_count"], len(combined))
        # A distinctive token from the external title is now indexed.
        self.assertIn("photonic", rebuilt["search_index"]["postings"])
        # The external sub-funder shows up as a facet value.
        self.assertIn("Example Institute", rebuilt["facets"]["agency"])
        # Index and opportunity list stay aligned.
        self.assertEqual(
            len(rebuilt["search_index"]["document_lengths"]),
            len(rebuilt["opportunities"]),
        )
        self.assertIn("additional_sources", rebuilt["diagnostics"])

    def test_write_then_read_round_trip(self):
        catalog, base = self._base_catalog()
        external = [an_external_record(external_id="Z2", title="Round trip grant")]
        combined, _ = merge_records(base, external)
        rebuilt = rebuild_catalog(catalog, combined, results=[])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "opportunities.js"
            save_catalog(rebuilt, path)
            reloaded = load_catalog(path)
        self.assertEqual(reloaded["record_count"], len(combined))
        self.assertEqual(reloaded["schema_version"], catalog["schema_version"])

    def test_operational_source_evidence_stays_out_of_catalog_artifact(self):
        catalog, base = self._base_catalog()
        lifecycle = [{
            "slug": "jhu",
            "source": "JHU",
            "status": "failed_no_fallback",
            "published": 0,
            "failure_class": "request_network",
            "failure_reason": "http_403_access_challenge",
            "last_successful_refresh_at": "2026-07-01T00:00:00Z",
            "retained_data_age_days": None,
            "publication_decision": "published_zero_fail_closed",
        }]

        rebuilt = rebuild_catalog(catalog, base, results=[], lifecycle=lifecycle)
        stored = rebuilt["diagnostics"]["additional_sources"]["lifecycle"][0]

        self.assertEqual(
            stored,
            {
                "slug": "jhu",
                "source": "JHU",
                "status": "failed_no_fallback",
                "published": 0,
            },
        )


class IntegrateSafetyTests(unittest.TestCase):
    def test_documented_upstream_disabled_source_is_truthful_and_not_degraded(self):
        class DisabledUpstream(SourceAdapter):
            slug = "disabled-upstream"
            display_name = "Disabled upstream"
            source_type = "Fellowship"
            enabled = False
            disabled_reason = "official unattended route unavailable"

            def fetch(self):
                raise AssertionError("a disabled source must not run")

            def parse(self, _payload):
                return []

        catalog, _ = RebuildAndRoundTripTests()._base_catalog()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "opportunities.js"
            save_catalog(catalog, path)
            summary = integrate(
                catalog_path=path,
                adapters=[DisabledUpstream()],
                write=False,
            )

        self.assertEqual(summary["sources"], [])
        self.assertEqual(summary["disabled_sources"], [{
            "slug": "disabled-upstream",
            "source": "Disabled upstream",
            "reason": "official unattended route unavailable",
            "publication_decision": "not_run_published_zero",
        }])
        self.assertFalse(summary_is_degraded(summary))

    def test_preview_does_not_modify_the_catalog_file(self):
        catalog, _ = RebuildAndRoundTripTests()._base_catalog()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "opportunities.js"
            save_catalog(catalog, path)
            before = path.read_text(encoding="utf-8")
            # Include the disabled sample adapter, but preview only (write=False).
            summary = integrate(
                catalog_path=path,
                adapters=[SampleFixtureAdapter()],
                include_disabled=True,
                write=False,
            )
            after = path.read_text(encoding="utf-8")
        self.assertFalse(summary["written"])
        self.assertEqual(before, after)
        self.assertEqual(summary["stats"]["external_added"], 2)

    def test_selected_source_refresh_preserves_other_external_sources(self):
        catalog, _ = RebuildAndRoundTripTests()._base_catalog()
        unselected = an_external_record(external_id="UNSELECTED")
        catalog["opportunities"].append(unselected)
        with TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "opportunities.js"
            cache_path = Path(directory) / "source_records.json"
            save_catalog(catalog, catalog_path)

            summary = integrate(
                catalog_path=catalog_path,
                cache_path=cache_path,
                adapters=[SampleFixtureAdapter()],
                include_disabled=True,
                write=True,
            )
            reloaded = load_catalog(catalog_path)

        self.assertTrue(summary["written"])
        self.assertIn(
            "demo:UNSELECTED",
            {
                record["opportunity_id"]
                for record in reloaded["opportunities"]
            },
        )


class ValidationTests(unittest.TestCase):
    AS_OF = date(2026, 7, 25)

    def test_requires_official_url(self):
        no_url = an_external_record(external_id="V1", url=None)
        ok, reason = record_is_publishable(no_url, self.AS_OF)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_official_url")

    def test_rejects_expired_close_date(self):
        expired = an_external_record(
            external_id="V2", url="https://x.org/2", close_date="2020-01-01"
        )
        self.assertEqual(record_is_publishable(expired, self.AS_OF), (False, "expired"))

    def test_accepts_current_record_with_url(self):
        good = an_external_record(
            external_id="V3", url="https://x.org/3", close_date="2026-12-01"
        )
        self.assertEqual(record_is_publishable(good, self.AS_OF), (True, "ok"))

    def test_filter_splits_and_health_bounds(self):
        records = [
            an_external_record(external_id="A", url="https://x.org/a", close_date="2026-12-01"),
            an_external_record(external_id="B", url="https://x.org/b", close_date="2019-01-01"),
        ]
        kept, dropped = filter_publishable(records, self.AS_OF)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped[0]["reason"], "expired")
        self.assertTrue(within_health_bounds(5, 1, 2000))
        self.assertFalse(within_health_bounds(0, 1, 2000))
        self.assertFalse(within_health_bounds(9999, 1, 2000))


class LifecycleTests(unittest.TestCase):
    AS_OF = date(2026, 7, 25)

    def _cache_with(self, slug, ext_id):
        record = an_external_record(
            external_id=ext_id, url=f"https://x.org/{ext_id}", close_date="2026-12-01"
        )
        return {"schema_version": 1, "sources": {
            slug: {"source": "Src", "source_type": "State", "records": [record]},
        }}

    def _ok(self, slug, records):
        return AdapterResult(
            slug=slug, display_name="Src", source_type="State", ok=True,
            record_count=len(records), records=records, min_records=1, max_records=2000,
        )

    def test_failed_adapter_keeps_last_known_good(self):
        cache = self._cache_with("nih", "OLD")
        cache["sources"]["nih"]["fetched_at"] = "2026-07-20T12:00:00Z"
        failed = AdapterResult(
            slug="nih", display_name="Src", source_type="State", ok=False,
            error="network down", min_records=1, max_records=2000,
        )
        live, _, summaries = resolve_live_records([failed], cache, self.AS_OF)
        self.assertEqual(len(live), 1)
        self.assertEqual(summaries[0]["status"], "failed_kept_last_good")
        self.assertEqual(summaries[0]["failure_class"], "request_network")
        self.assertEqual(
            summaries[0]["last_successful_refresh_at"],
            "2026-07-20T12:00:00Z",
        )
        self.assertEqual(summaries[0]["retained_data_age_days"], 5)
        self.assertEqual(
            summaries[0]["publication_decision"],
            "published_filtered_last_known_good",
        )

    def test_recent_complete_snapshot_covers_an_expected_cloud_runner_block(self):
        cache = self._cache_with("jhu", "RECENT")
        cache["sources"]["jhu"]["fetched_at"] = "2026-07-20T12:00:00Z"
        failed = AdapterResult(
            slug="jhu", display_name="JHU", source_type="Fellowship", ok=False,
            error="HTTP 403", min_records=1, max_records=2000,
            fallback_grace_days=45,
        )
        live, _, summaries = resolve_live_records([failed], cache, self.AS_OF)
        self.assertEqual(len(live), 1)
        self.assertEqual(summaries[0]["status"], "recent_snapshot")
        self.assertTrue(summaries[0]["healthy"])
        self.assertEqual(summaries[0]["snapshot_age_days"], 5)

    def test_stale_snapshot_still_degrades_after_its_grace_period(self):
        cache = self._cache_with("jhu", "STALE")
        cache["sources"]["jhu"]["fetched_at"] = "2026-05-01T12:00:00Z"
        failed = AdapterResult(
            slug="jhu", display_name="JHU", source_type="Fellowship", ok=False,
            error="HTTP 403", min_records=1, max_records=2000,
            fallback_grace_days=45,
        )
        _, _, summaries = resolve_live_records([failed], cache, self.AS_OF)
        self.assertEqual(summaries[0]["status"], "failed_kept_last_good")
        self.assertFalse(summaries[0]["healthy"])

    def test_no_fallback_source_clears_snapshot_after_fetch_failure(self):
        cache = self._cache_with("jhu", "UNVERIFIED")
        cache["sources"]["jhu"]["fetched_at"] = "2026-07-20T12:00:00Z"
        failed = AdapterResult(
            slug="jhu", display_name="JHU", source_type="Fellowship", ok=False,
            error="HTTP 403", min_records=0, max_records=2000,
            retain_on_failure=False,
            diagnostics={
                "failure_class": "request_network",
                "failure_reason": "http_403_access_challenge",
            },
        )

        live, updated, summaries = resolve_live_records([failed], cache, self.AS_OF)

        self.assertEqual(live, [])
        self.assertEqual(updated["sources"]["jhu"]["records"], [])
        self.assertEqual(updated["sources"]["jhu"]["record_count"], 0)
        self.assertEqual(
            updated["sources"]["jhu"]["last_successful_refresh_at"],
            "2026-07-20T12:00:00Z",
        )
        self.assertEqual(
            updated["sources"]["jhu"]["last_successful_record_count"],
            1,
        )
        self.assertEqual(summaries[0]["status"], "failed_no_fallback")
        self.assertFalse(summaries[0]["healthy"])
        self.assertEqual(summaries[0]["failure_class"], "request_network")
        self.assertEqual(
            summaries[0]["failure_reason"],
            "http_403_access_challenge",
        )
        self.assertEqual(
            summaries[0]["last_successful_refresh_at"],
            "2026-07-20T12:00:00Z",
        )
        self.assertIsNone(summaries[0]["retained_data_age_days"])
        self.assertEqual(
            summaries[0]["publication_decision"],
            "published_zero_fail_closed",
        )

    def test_valid_empty_source_replaces_an_old_snapshot(self):
        cache = self._cache_with("jhu", "OLD")
        empty = AdapterResult(
            slug="jhu", display_name="JHU", source_type="Fellowship", ok=True,
            record_count=0, records=[], min_records=0, max_records=2000,
            retain_on_failure=False,
        )

        live, updated, summaries = resolve_live_records([empty], cache, self.AS_OF)

        self.assertEqual(live, [])
        self.assertEqual(updated["sources"]["jhu"]["records"], [])
        self.assertEqual(summaries[0]["status"], "refreshed")
        self.assertTrue(summaries[0]["healthy"])
        self.assertEqual(summaries[0]["publication_decision"], "published_fresh_records")
        self.assertIsNone(summaries[0]["failure_class"])

    def test_bounded_source_snapshot_uses_content_date_and_is_not_fresh(self):
        snapshot = AdapterResult(
            slug="jhu", display_name="JHU", source_type="Fellowship", ok=True,
            record_count=1,
            records=[an_external_record(
                external_id="SNAPSHOT",
                url="https://x.org/snapshot",
                close_date="2026-12-15",
            )],
            min_records=0,
            max_records=2000,
            retain_on_failure=False,
            diagnostics={
                "source_state": "bounded_official_snapshot",
                "source_snapshot_at": "2026-07-01",
                "source_snapshot_age_days": 24,
                "source_snapshot_max_age_days": 62,
            },
        )

        _, updated, summaries = resolve_live_records(
            [snapshot],
            {"schema_version": 1, "sources": {}},
            self.AS_OF,
        )

        self.assertEqual(updated["sources"]["jhu"]["fetched_at"], "2026-07-01T00:00:00Z")
        self.assertNotIn("last_successful_refresh_at", updated["sources"]["jhu"])
        self.assertEqual(summaries[0]["status"], "recent_snapshot")
        self.assertEqual(
            summaries[0]["publication_decision"],
            "published_bounded_source_snapshot",
        )
        self.assertEqual(summaries[0]["last_successful_refresh_at"], "2026-07-01T00:00:00Z")
        self.assertEqual(summaries[0]["retained_data_age_days"], 24)

    def test_successful_refresh_replaces_records_and_cache(self):
        cache = self._cache_with("nih", "OLD")
        fresh = [an_external_record(
            external_id="NEW", url="https://x.org/new", close_date="2026-12-15")]
        live, cache, summaries = resolve_live_records(
            [self._ok("nih", fresh)], cache, self.AS_OF)
        self.assertEqual([r["opportunity_id"] for r in live], ["demo:NEW"])
        self.assertEqual(
            cache["sources"]["nih"]["records"][0]["opportunity_id"], "demo:NEW")
        self.assertEqual(summaries[0]["status"], "refreshed")
        self.assertNotIn("last_successful_refresh_at", cache["sources"]["nih"])
        self.assertNotIn("last_successful_record_count", cache["sources"]["nih"])

    def test_successful_refresh_persists_safe_adapter_diagnostics(self):
        fresh = [an_external_record(
            external_id="NEW", url="https://x.org/new", close_date="2026-12-15")]
        result = self._ok("mail", fresh)
        result.diagnostics = {
            "streams": {
                "vpr": {"accepted_messages": 1, "parsed_records": 2},
                "cindy": {"accepted_messages": 1, "parsed_records": 4},
            }
        }
        _, cache, summaries = resolve_live_records(
            [result], {"schema_version": 1, "sources": {}}, self.AS_OF)
        self.assertEqual(
            cache["sources"]["mail"]["diagnostics"], result.diagnostics)
        self.assertEqual(summaries[0]["diagnostics"], result.diagnostics)

    def test_successful_refresh_preserves_first_seen_date(self):
        cache = self._cache_with("nih", "KEEP")
        cache["sources"]["nih"]["fetched_at"] = "2026-07-20T12:00:00Z"
        cache["sources"]["nih"]["records"][0]["source_first_seen_date"] = "2026-07-18"
        fresh = [an_external_record(
            external_id="KEEP", url="https://x.org/KEEP", close_date="2026-12-15")]
        live, cache, _ = resolve_live_records(
            [self._ok("nih", fresh)], cache, self.AS_OF)
        self.assertEqual(live[0]["source_first_seen_date"], "2026-07-18")
        self.assertEqual(
            cache["sources"]["nih"]["records"][0]["source_first_seen_date"],
            "2026-07-18",
        )

    def test_successful_refresh_dates_new_records(self):
        fresh = [an_external_record(
            external_id="NEW", url="https://x.org/new", close_date="2026-12-15")]
        live, _, _ = resolve_live_records(
            [self._ok("nih", fresh)],
            {"schema_version": 1, "sources": {}},
            self.AS_OF,
        )
        self.assertEqual(live[0]["source_first_seen_date"], "2026-07-25")

    def test_unhealthy_count_keeps_last_known_good(self):
        cache = self._cache_with("s", "GOOD")
        empty_refresh = self._ok("s", [])  # 0 records < min_records
        live, _, summaries = resolve_live_records([empty_refresh], cache, self.AS_OF)
        self.assertEqual(len(live), 1)
        self.assertEqual(summaries[0]["status"], "unhealthy_kept_last_good")

    def test_expired_records_dropped_before_publication(self):
        fresh = [
            an_external_record(external_id="EXP", url="https://x.org/e", close_date="2020-01-01"),
            an_external_record(external_id="CUR", url="https://x.org/c", close_date="2026-12-01"),
        ]
        live, _, summaries = resolve_live_records(
            [self._ok("s", fresh)], {"schema_version": 1, "sources": {}}, self.AS_OF)
        ids = [r["opportunity_id"] for r in live]
        self.assertIn("demo:CUR", ids)
        self.assertNotIn("demo:EXP", ids)
        self.assertEqual(summaries[0]["dropped_invalid"], 1)

    def test_expired_cached_records_are_not_republished_after_failure(self):
        cache = self._cache_with("s", "OLD")
        cache["sources"]["s"]["records"][0]["close_date"] = "2020-01-01"
        failed = AdapterResult(
            slug="s", display_name="Src", source_type="State", ok=False,
            error="network down", min_records=1, max_records=2000,
        )
        live, _, summaries = resolve_live_records([failed], cache, self.AS_OF)
        self.assertEqual(live, [])
        self.assertEqual(summaries[0]["status"], "failed_kept_last_good")
        self.assertEqual(summaries[0]["published"], 0)

    def test_integrate_writes_catalog_and_cache(self):
        catalog, _ = RebuildAndRoundTripTests()._base_catalog()
        with TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "opportunities.js"
            cache_path = Path(directory) / "source_records.json"
            save_catalog(catalog, catalog_path)
            summary = integrate(
                catalog_path=catalog_path, cache_path=cache_path,
                adapters=[SampleFixtureAdapter()], include_disabled=True, write=True,
            )
            self.assertTrue(summary["written"])
            self.assertTrue(summary["validation"]["ok"])
            self.assertTrue(cache_path.exists())
            cache = load_source_cache(cache_path)
            self.assertIn("sample", cache["sources"])
            reloaded = load_catalog(catalog_path)
            self.assertIn("Sample source (demo)", reloaded["facets"]["source"])


class SourceFacetTests(unittest.TestCase):
    def test_facet_counts_expose_source_type(self):
        from scripts.build_catalog import facet_counts

        base = [a_base_record()]                       # Grants.gov -> "Federal"
        external = [an_external_record(external_id="S1")]  # source_type "State"
        facets = facet_counts(base + external)
        self.assertIn("source_type", facets)
        self.assertIn("Federal", facets["source_type"])
        self.assertIn("State", facets["source_type"])

    def test_official_federal_supplements_do_not_create_one_off_source_facets(self):
        base = a_base_record()
        external = an_external_record(
            external_id="PD-26-370Y",
            title="Energy, Water, and Resource Engineering (EWRE)",
        )
        external["source"] = "U.S. National Science Foundation"
        external["source_type"] = "Federal"
        from scripts.build_catalog import normalize_record_facets, facet_counts

        normalize_record_facets(external)
        facets = facet_counts([base, external])

        self.assertEqual(external["source"], "U.S. National Science Foundation")
        self.assertIsNone(external["source_facet"])
        self.assertEqual(facets["source"], {"Grants.gov": 1})


class NIHGuideFeedTests(unittest.TestCase):
    FEED = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>NIH Announces Helium-3 Requests for Medical Research</title>
        <link>http://grants.nih.gov/grants/guide/notice-files/NOT-HL-26-006.html</link>
        <description>Notice NOT-HL-26-006 from the NIH Guide for Grants and Contracts.</description>
        <pubDate>Tue, 30 Jun 2026 04:22:48 EST</pubDate>
      </item></channel></rss>"""

    def test_nih_guide_feed_parses(self):
        from scripts.sources.adapters.rss import NIHGuideFundingOpps

        self.assertFalse(NIHGuideFundingOpps.enabled)
        opportunities = NIHGuideFundingOpps().parse_feed(self.FEED)
        self.assertEqual(len(opportunities), 1)
        record = opportunities[0].to_record(
            slug="nih-guide", source="NIH Guide", source_type="Federal"
        )
        self.assertIn("Helium-3", record["title"])
        self.assertEqual(record["source_type"], "Federal")


class NSFFeedTests(unittest.TestCase):
    def test_extracts_grants_gov_compatible_opportunity_number(self):
        from scripts.sources.adapters.rss import NSFFundingUpcoming

        feed = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Integrated Data Systems & Services (IDSS)</title>
          <link>https://www.nsf.gov/funding/opportunities/idss/nsf26-509</link>
          <description>Full Proposal Deadline Date: July 28, 2026</description>
        </item></channel></rss>"""
        opportunities = list(NSFFundingUpcoming().parse(feed))
        self.assertEqual(opportunities[0].opportunity_number, "26-509")


class NyserdaParseTests(unittest.TestCase):
    PAYLOAD = {
        "FundingOpportunities": [
            {
                "SectionTitle": "Open Solicitations",
                "FundingOpportunities": [
                    {
                        "SolicitationName": "Clean Energy Career Pathways Training",
                        "SolicitationNumber": "PON 5001",
                        "ShortDescription": "<p>Supports clean energy workforce training.</p>",
                        "SolicitationRounds": [
                            {"Status": "Closed", "Round": "1",
                             "DueDate": "5/20/2026 3:00 PM",
                             "ConceptPaperDueDate": ""},
                            {"Status": "Open", "Round": "2",
                             "DueDate": "9/23/2026 3:00 PM",
                             "ConceptPaperDueDate": "8/20/2026 3:00 PM"},
                            {"Status": "Open", "Round": "3",
                             "DueDate": "12/15/2027 3:00 PM",
                             "ConceptPaperDueDate": ""},
                        ],
                        "DueDateString": "<p><strong>Due Date:&nbsp;5/20/2026</strong>&nbsp;(Round 1);<strong> 9/23/2026</strong> (Round 2);<strong> 12/15/2027</strong> (Round 3)</p>",
                        "RevisedDate": "07/01/2026",
                        "DetailPageLink": "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?SolicitationId=abc",
                        "SolicitationLinkPDF": "https://portal.nyserda.ny.gov/files/pon-5001.pdf",
                        "SolicitationContacts": [
                            {
                                "Name": "Clean Energy Programs",
                                "Email": "programs@nyserda.ny.gov",
                                "Phone": "518-555-0100",
                                "Title": "Program Manager",
                            }
                        ],
                    },
                    {
                        "SolicitationName": "Expired Legacy Program",
                        "SolicitationNumber": "PON 4000",
                        "ShortDescription": "Closed.",
                        "DueDateString": "<p><strong>Due Date:&nbsp;7/27/2022</strong></p>",
                        "DetailPageLink": "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?SolicitationId=old",
                    },
                    {
                        "SolicitationName": "Grid Planning Request for Information",
                        "SolicitationNumber": "RFI 6000",
                        "ShortDescription": "Input only; no award is offered.",
                        "DueDateString": "<p><strong>Due Date:&nbsp;10/1/2026</strong></p>",
                        "DetailPageLink": "https://portal.nyserda.ny.gov/CORE_Solicitation_Detail_Page?SolicitationId=rfi",
                    },
                ],
            }
        ]
    }

    def test_parses_real_shape_and_picks_next_open_round(self):
        from scripts.sources.adapters.nyserda import NyserdaAdapter

        opportunities = NyserdaAdapter().parse_payload(
            self.PAYLOAD, as_of=date(2026, 7, 25))
        self.assertEqual(len(opportunities), 2)
        first = opportunities[0].to_record(
            slug="nyserda", source="NYSERDA", source_type="State")
        self.assertEqual(first["close_date"], "2026-09-23")
        self.assertEqual(first["opportunity_number"], "PON 5001")
        self.assertIn("later rounds", first["close_date_note"])
        self.assertTrue(any(
            deadline["date"] == "2027-12-15"
            and deadline["kind"] == "application"
            for deadline in first["deadlines"]
        ))
        self.assertTrue(any(
            deadline["date"] == "2026-08-20"
            and deadline["kind"] == "concept_paper"
            for deadline in first["deadlines"]
        ))
        self.assertEqual(first["source_type"], "State")
        self.assertTrue(first["detail_page"].startswith("https://portal.nyserda.ny.gov"))
        self.assertTrue(first["primary_document_url"].endswith(".pdf"))
        self.assertEqual(
            first["contacts"][0]["email"],
            "programs@nyserda.ny.gov",
        )

    def test_currentness_gate_drops_the_expired_solicitation(self):
        from scripts.sources.adapters.nyserda import NyserdaAdapter

        records = [
            opp.to_record(slug="nyserda", source="NYSERDA", source_type="State")
            for opp in NyserdaAdapter().parse_payload(
                self.PAYLOAD, as_of=date(2026, 7, 25))
        ]
        kept, dropped = filter_publishable(records, date(2026, 7, 25))
        kept_titles = {record["title"] for record in kept}
        self.assertIn("Clean Energy Career Pathways Training", kept_titles)
        self.assertNotIn("Expired Legacy Program", kept_titles)
        self.assertNotIn("Grid Planning Request for Information", kept_titles)
        self.assertEqual(dropped[0]["reason"], "expired")


class URInfoReadyParseTests(unittest.TestCase):
    PAYLOAD = [
        {"cardId": 75682, "opportunityId": 2022459,
         "title": "NIH-Atopic Dermatitis Research Network (ADRN) (U19 Clinical Trial Optional)",
         "description": "The ADRN program will support Centers that integrate research.",
         "dueDate": "08/25/2026 03:59:59", "category": "Cooperative Agreement"},
        {"cardId": 75697, "opportunityId": 2022469,
         "title": "Greenwall Foundation - Faculty Scholars Program in Bioethics",
         "description": "A career development award for early-career faculty members.",
         "dueDate": "08/04/2026 03:59:59", "category": "Scholar Award"},
    ]

    def test_parses_competition_cards(self):
        from scripts.sources.adapters.ur_infoready import URInfoReadyAdapter

        opportunities = URInfoReadyAdapter().parse_payload(self.PAYLOAD)
        self.assertEqual(len(opportunities), 2)
        first = opportunities[0].to_record(
            slug="ur-infoready", source="UR InfoReady", source_type="Internal")
        self.assertEqual(first["close_date"], "2026-08-24")
        self.assertEqual(first["source_type"], "Internal")
        self.assertEqual(
            first["detail_page"],
            "https://rochester.infoready4.com/#competitionDetail/2022459",
        )
        self.assertFalse(URInfoReadyAdapter.enabled)
        second = opportunities[1].to_record(
            slug="ur-infoready", source="UR InfoReady", source_type="Internal")
        self.assertTrue(second["career_stage_signal"])  # "early-career" detected


class DiscoverabilityTests(unittest.TestCase):
    UMBRELLA = {
        "opportunity_number": "DE-FOA-0003600",
        "title": "FY 2026 Continuation of Solicitation for the Office of Science "
                 "Financial Assistance Program",
        "agency": "Office of Science",
        "description": "Supports the Office of Science financial assistance program.",
        "topic_areas": [],
        "document_search_text": None,
    }
    ONR_UMBRELLA = {
        "opportunity_number": "N0001425SB001",
        "title": "FY25 Long Range Broad Agency Announcement (BAA) for Navy "
                 "and Marine Corps Science and Technology",
        "agency": "Office of Naval Research",
        "description": "Basic and applied scientific research.",
        "topic_areas": [],
        "document_search_text": None,
    }
    NASA_SPACETECH_UMBRELLA = {
        "opportunity_number": "NNH26ZTR001N",
        "title": "Space Technology Research, Development, Demonstration, "
                 "and Infusion (SpaceTech REDDI-2026)",
        "agency": "NASA Headquarters",
        "description": "Umbrella NASA Research Announcement.",
        "topic_areas": ["Space and aeronautics", "Technology development"],
        "document_search_text": None,
    }
    ARL_UMBRELLA = {
        "opportunity_number": "W911NF-23-S-0001",
        "title": "DEVCOM Army Research Laboratory Broad Agency Announcement "
                 "for Foundational Research",
        "agency": "Dept of the Army -- Materiel Command",
        "description": "See the separate ARL BAA topics website.",
        "topic_areas": ["Technology development"],
        "document_search_text": None,
    }

    def test_umbrella_foa_gains_program_topics_and_terms(self):
        from scripts.sources.discoverability import augment_records

        record = dict(self.UMBRELLA)
        changed = augment_records([record])
        self.assertEqual(changed, 1)
        self.assertIn("Catalysis and reaction engineering", record["topic_areas"])
        self.assertIn("catalysis", (record["document_search_text"] or "").lower())
        self.assertTrue(record["discoverability_augmented"])

    def test_unrelated_record_is_untouched(self):
        from scripts.sources.discoverability import augment_records

        record = {"title": "Rural health services grant", "agency": "HRSA",
                  "description": "", "topic_areas": ["Public health"]}
        self.assertEqual(augment_records([record]), 0)
        self.assertEqual(record["topic_areas"], ["Public health"])

    def test_augmented_umbrella_is_findable_by_catalysis(self):
        from scripts.sources.discoverability import augment_records
        from scripts.build_catalog import build_search_index, tokenize

        record = dict(self.UMBRELLA)
        augment_records([record])
        index = build_search_index([record])
        token = tokenize("catalysis")[0]  # stemmed search token
        self.assertIn(token, index["postings"])

    def test_augmentation_is_idempotent(self):
        from scripts.sources.discoverability import augment_records

        record = dict(self.UMBRELLA)
        self.assertEqual(augment_records([record]), 1)
        first_topics = list(record["topic_areas"])
        first_text = record["document_search_text"]
        self.assertEqual(augment_records([record]), 0)
        self.assertEqual(record["topic_areas"], first_topics)
        self.assertEqual(record["document_search_text"], first_text)

    def test_onr_long_range_baa_gains_official_program_scope(self):
        from scripts.sources.discoverability import augment_records

        record = dict(self.ONR_UMBRELLA)
        self.assertEqual(augment_records([record]), 1)

        text = (record["document_search_text"] or "").casefold()
        for term in (
            "catalysis", "electrochemistry", "selective extraction",
            "artificial intelligence", "quantum sensing",
        ):
            self.assertIn(term, text)
        self.assertIn("Catalysis and reaction engineering", record["topic_areas"])
        self.assertIn("Quantum science", record["topic_areas"])
        evidence = record["discoverability_evidence"][0]
        self.assertEqual(evidence["rule_id"], "onr-long-range-baa")
        self.assertTrue(all(url.startswith("https://www.onr.navy.mil/")
                            for url in evidence["official_urls"]))

    def test_spacetech_reddi_gains_taxonomy_scope_by_exact_number(self):
        from scripts.sources.discoverability import augment_records

        record = dict(self.NASA_SPACETECH_UMBRELLA)
        self.assertEqual(augment_records([record]), 1)

        text = (record["document_search_text"] or "").casefold()
        for term in (
            "space propulsion", "energy storage", "space robotics",
            "artificial intelligence", "advanced manufacturing",
            "entry descent and landing",
        ):
            self.assertIn(term, text)
        self.assertNotIn("catalysis", text)
        self.assertIn("Materials science", record["topic_areas"])
        self.assertEqual(
            record["discoverability_contribution"]["rule_ids"],
            ["nasa-spacetech-reddi-umbrella"],
        )

    def test_arl_baa_gains_current_foundational_competencies(self):
        from scripts.sources.discoverability import augment_records

        record = dict(self.ARL_UMBRELLA)
        self.assertEqual(augment_records([record]), 1)

        text = (record["document_search_text"] or "").casefold()
        for term in (
            "synthetic biology", "energy storage", "human autonomy",
            "cybersecurity", "quantum sensing", "extreme materials",
        ):
            self.assertIn(term, text)
        self.assertNotIn("catalysis", text)
        self.assertIn("Quantum science", record["topic_areas"])

    def test_noaa_baa_scope_stays_with_its_exact_line_office(self):
        from scripts.sources.discoverability import augment_records

        weather = {
            "opportunity_number": "NOAA-NWS-2024-28059",
            "title": "FY 2024-2026 Broad Agency Announcement",
            "agency": "DOC NOAA",
            "description": "Projects associated with the NWS mission.",
            "topic_areas": ["Environmental science"],
        }
        fisheries = {
            "opportunity_number": "NOAA-NMFS-FHQ-2024-27611",
            "title": "FY 2024-2026 Broad Agency Announcement",
            "agency": "DOC NOAA",
            "description": "Projects associated with the NMFS mission.",
            "topic_areas": ["Environmental science"],
        }
        unknown = {
            "opportunity_number": "NOAA-OTHER-BAA",
            "title": "FY 2024-2026 Broad Agency Announcement",
            "agency": "DOC NOAA",
            "description": "Projects associated with NOAA's mission.",
            "topic_areas": ["Environmental science"],
        }

        self.assertEqual(augment_records([weather, fisheries, unknown]), 2)
        weather_text = (weather["document_search_text"] or "").casefold()
        fisheries_text = (fisheries["document_search_text"] or "").casefold()
        self.assertIn("weather forecasting", weather_text)
        self.assertNotIn("sustainable fisheries", weather_text)
        self.assertIn("sustainable fisheries", fisheries_text)
        self.assertNotIn("weather forecasting", fisheries_text)
        self.assertNotIn("discoverability_contribution", unknown)

    def test_roses_program_element_does_not_inherit_omnibus_scope(self):
        from scripts.sources.discoverability import augment_records

        element = {
            "opportunity_number": "NNH25ZDA001N-ATMOS",
            "title": "ROSES-2025: A.14 Atmosphere Observing System",
            "agency": "NASA Headquarters",
            "description": "A specific ROSES program element.",
            "topic_areas": ["Environmental science"],
        }

        self.assertEqual(augment_records([element]), 0)
        self.assertNotIn("discoverability_contribution", element)

    def test_generic_baa_label_does_not_trigger_umbrella_recall(self):
        from scripts.sources.discoverability import augment_records

        unrelated = {
            "opportunity_number": "STATE-BAA-1",
            "title": "Broad Agency Announcement for Public Diplomacy",
            "agency": "Department of State",
            "description": "Education and cultural exchange programs.",
            "topic_areas": [],
            "document_search_text": "",
        }

        self.assertEqual(augment_records([unrelated]), 0)
        self.assertNotIn("discoverability_evidence", unrelated)

    def test_onr_title_fallback_requires_agency_and_notice_wording(self):
        from scripts.sources.discoverability import augment_records

        for record in (
            {
                "title": self.ONR_UMBRELLA["title"],
                "agency": "Another agency",
                "topic_areas": [],
            },
            {
                "title": "Focused naval materials opportunity",
                "agency": "Office of Naval Research",
                "topic_areas": [],
            },
        ):
            with self.subTest(record=record):
                self.assertEqual(augment_records([record]), 0)

    def test_eere_acronym_requires_a_whole_token(self):
        from scripts.sources.discoverability import augment_records

        false_positive = {
            "title": "Research on intelligent engineered systems",
            "agency": "National Science Foundation",
            "description": "Fundamental engineering research.",
            "topic_areas": [],
        }
        true_positive = {
            "title": "EERE advanced manufacturing program",
            "agency": "Department of Energy",
            "description": "Energy technology research.",
            "topic_areas": [],
        }

        self.assertEqual(augment_records([false_positive]), 0)
        self.assertEqual(augment_records([true_positive]), 1)
        self.assertIn("Energy", true_positive["topic_areas"])

    def test_rule_contributions_are_removed_when_record_stops_matching(self):
        from scripts.sources.discoverability import augment_records

        record = {
            "title": "EERE advanced manufacturing program",
            "agency": "Department of Energy",
            "description": "Energy technology research.",
            "topic_areas": ["Technology development"],
            "document_search_text": "official source evidence",
        }
        self.assertEqual(augment_records([record]), 1)
        self.assertIn("renewable energy", record["document_search_text"])
        self.assertIn("Energy", record["topic_areas"])

        record["title"] = "Focused engineering methods program"
        self.assertEqual(augment_records([record]), 1)
        self.assertEqual(record["document_search_text"], "official source evidence")
        self.assertEqual(record["topic_areas"], ["Technology development"])
        self.assertNotIn("discoverability_contribution", record)
        self.assertNotIn("discoverability_augmented", record)


class NSFCBETSourceTests(unittest.TestCase):
    def test_publishes_current_clusters_and_drops_an_archived_page(self):
        from scripts.sources.adapters.nsf_cbet import (
            CBET_PROGRAMS,
            NSFCBETCorePrograms,
        )

        current = """
        <main><h1>Current program</h1>
          <div class="field-funding-synopsis"><h2>Synopsis</h2>
            <p>This current program supports fundamental engineering research
            in catalysis, biological systems, energy, water, and transport
            phenomena across a broad range of applications.</p>
          </div>
        </main>
        """
        archived = """
        <main><h1>Old program</h1><h2>Status: Archived</h2></main>
        """
        payload = {
            program["number"]: current
            for program in CBET_PROGRAMS
        }
        payload[CBET_PROGRAMS[0]["number"]] = archived

        opportunities = list(NSFCBETCorePrograms().parse(payload))

        self.assertEqual(len(opportunities), 3)
        self.assertNotIn(
            CBET_PROGRAMS[0]["number"],
            {opportunity.opportunity_number for opportunity in opportunities},
        )
        ewre = next(
            opportunity
            for opportunity in opportunities
            if opportunity.opportunity_number == "PD-26-370Y"
        )
        record = ewre.to_record(
            slug="nsf-cbet",
            source="U.S. National Science Foundation",
            source_type="Federal",
        )
        self.assertTrue(record["rolling"])
        self.assertIn("Energy", record["topic_areas"])
        self.assertEqual(record["source"], "U.S. National Science Foundation")
        self.assertIsNone(record["source_facet"])


class DoeExchangeParseTests(unittest.TestCase):
    FIXTURE = (
        '<ul>'
        '<li><a href="#FoaId11111111-1111-1111-1111-111111111111">DE-FOA-0009001</a> '
        '<a href="#FoaId11111111-1111-1111-1111-111111111111">Carbon Capture Catalysis (CCC)</a> '
        'Notice Of Funding Opportunity (NOFO) 9/15/2026 05:00 PM ET 12/1/2026 05:00 PM ET</li>'
        '<li><a href="#FoaId22222222-2222-2222-2222-222222222222">RFI-0000200</a> '
        '<a href="#FoaId22222222-2222-2222-2222-222222222222">Request for Information on Widgets</a> '
        'Request for Information (RFI) 7/1/2026 05:00 PM ET</li>'
        '<li><a href="#FoaId33333333-3333-3333-3333-333333333333">DE-FOA-0008000</a> '
        '<a href="#FoaId33333333-3333-3333-3333-333333333333">Legacy Closed Program</a> '
        'Notice Of Funding Opportunity (NOFO) 2/1/2024 05:00 PM ET 4/1/2024 05:00 PM ET</li>'
        '<li><a href="#FoaId44444444-4444-4444-4444-444444444444">DE-FOA-0009050</a> '
        '<a href="#FoaId44444444-4444-4444-4444-444444444444">Geothermal Field Tests</a> '
        'Notice Of Funding Opportunity (NOFO) Geothermal Technologies (GTO) 10/30/2026 05:00 PM ET TBD</li>'
        '<li><a href="#FoaId55555555-5555-5555-5555-555555555555">DE-TA3-0003589</a> '
        '<a href="#FoaId55555555-5555-5555-5555-555555555555">Critical Minerals Topic Area 3</a> '
        'Notice Of Funding Opportunity (NOFO) Manufacturing Office '
        '<a href="#FoaId55555555-5555-5555-5555-555555555555">Listed on Announcement</a> '
        '<a href="#FoaId55555555-5555-5555-5555-555555555555">Listed on Announcement</a></li>'
        '<li><a href="#FoaId66666666-6666-6666-6666-666666666666">DE-FOA-0003588</a> '
        '<a href="#FoaId66666666-6666-6666-6666-666666666666">Notice of Intent to issue a Notice of Funding Opportunity</a> '
        'Notice of Intent to Publish Announcement (NOI) Manufacturing Office TBD</li>'
        '</ul>'
    )

    def test_parses_nofos_and_filters_non_funding(self):
        from scripts.sources.adapters.doe_exchange import ArpaEAdapter

        opps = ArpaEAdapter().parse_html(self.FIXTURE, as_of=date(2026, 7, 25))
        by_title = {o.title: o for o in opps}
        # RFI and NOI are dropped; four actual NOFOs remain.
        self.assertEqual(len(opps), 4)
        self.assertNotIn("Request for Information on Widgets", by_title)
        self.assertNotIn(
            "Notice of Intent to issue a Notice of Funding Opportunity",
            by_title,
        )
        self.assertIn("Critical Minerals Topic Area 3", by_title)

        ccc = by_title["Carbon Capture Catalysis (CCC)"].to_record(
            slug="arpa-e", source="ARPA-E eXCHANGE", source_type="Federal")
        self.assertEqual(ccc["close_date"], "2026-09-15")   # next open date
        self.assertIn("2026-12-01", [d.get("date") for d in ccc["deadlines"]])  # later round kept
        self.assertIn("11111111", ccc["detail_page"])

        geo = by_title["Geothermal Field Tests"].to_record(
            slug="arpa-e", source="ARPA-E eXCHANGE", source_type="Federal")
        self.assertEqual(geo["agency"], "Geothermal Technologies (GTO)")

        critical = by_title["Critical Minerals Topic Area 3"].to_record(
            slug="eere-exchange", source="DOE EERE Exchange", source_type="Federal")
        self.assertEqual(critical["agency"], "Manufacturing Office")
        self.assertNotIn("Listed on Announcement", critical["agency"])

    def test_tbd_is_a_deadline_placeholder_not_an_arpa_e_office(self):
        from scripts.sources.adapters.doe_exchange import ArpaEAdapter

        html = (
            '<a href="#FoaId11111111-1111-1111-1111-111111111111">DE-FOA-0009001</a>'
            '<a href="#FoaId11111111-1111-1111-1111-111111111111">Open-ended program</a>'
            'Notice Of Funding Opportunity (NOFO) TBD'
            '<a href="#FoaId22222222-2222-2222-2222-222222222222">DE-FOA-0009002</a>'
            '<a href="#FoaId22222222-2222-2222-2222-222222222222">Dated program</a>'
            'Notice Of Funding Opportunity (NOFO) 11/30/2026 05:00 PM ET'
            '<a href="#FoaId33333333-3333-3333-3333-333333333333">DE-FOA-0009003</a>'
            '<a href="#FoaId33333333-3333-3333-3333-333333333333">Second dated program</a>'
            'Notice Of Funding Opportunity (NOFO) 12/15/2026 05:00 PM ET'
        )
        records = [
            item.to_record(slug="arpa-e", source="ARPA-E eXCHANGE", source_type="Federal")
            for item in ArpaEAdapter().parse_html(html, as_of=date(2026, 9, 2))
        ]
        self.assertEqual(records[0]["agency"], "ARPA-E eXCHANGE")
        self.assertNotIn("<a", records[0]["agency"])

    def test_currentness_gate_drops_closed_foas(self):
        from scripts.sources.adapters.doe_exchange import ArpaEAdapter

        records = [
            o.to_record(slug="arpa-e", source="ARPA-E eXCHANGE", source_type="Federal")
            for o in ArpaEAdapter().parse_html(self.FIXTURE, as_of=date(2026, 7, 25))
        ]
        kept, dropped = filter_publishable(records, date(2026, 7, 25))
        kept_titles = {r["title"] for r in kept}
        self.assertIn("Carbon Capture Catalysis (CCC)", kept_titles)
        self.assertNotIn("Legacy Closed Program", kept_titles)

    def test_parser_fails_closed_when_rows_have_no_recognizable_nofo_type(self):
        from scripts.sources.adapters.doe_exchange import ArpaEAdapter

        nonfunding = (
            '<a href="#FoaId11111111-1111-1111-1111-111111111111">RFI-0000001</a>'
            '<a href="#FoaId11111111-1111-1111-1111-111111111111">RFI one</a>'
            'Request for Information (RFI)'
            '<a href="#FoaId22222222-2222-2222-2222-222222222222">NOI-0000002</a>'
            '<a href="#FoaId22222222-2222-2222-2222-222222222222">NOI two</a>'
            'Notice of Intent to Publish Announcement (NOI)'
            '<a href="#FoaId33333333-3333-3333-3333-333333333333">TPL-0000003</a>'
            '<a href="#FoaId33333333-3333-3333-3333-333333333333">TPL three</a>'
            'Teaming Partner List'
        )
        with self.assertRaisesRegex(ValueError, "no recognizable NOFO"):
            ArpaEAdapter().parse_html(nonfunding, as_of=date(2026, 7, 25))


if __name__ == "__main__":
    unittest.main()
