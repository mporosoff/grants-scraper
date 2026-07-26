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


class IntegrateSafetyTests(unittest.TestCase):
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
        failed = AdapterResult(
            slug="nih", display_name="Src", source_type="State", ok=False,
            error="network down", min_records=1, max_records=2000,
        )
        live, _, summaries = resolve_live_records([failed], cache, self.AS_OF)
        self.assertEqual(len(live), 1)
        self.assertEqual(summaries[0]["status"], "failed_kept_last_good")

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


if __name__ == "__main__":
    unittest.main()
