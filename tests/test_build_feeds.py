"""Tests for static Atom feed generation."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from scripts import build_feeds

ATOM = "{http://www.w3.org/2005/Atom}"

RECORDS = [
    {
        "opportunity_id": "1", "opportunity_number": "DE-FOA-1",
        "title": "Catalysis & hydrogen <production>",  # special chars must be escaped
        "agency": "Department of Energy", "source": "Grants.gov", "source_type": "Federal",
        "status": "posted", "topic_areas": ["Catalysis and reaction engineering", "Energy"],
        "description": "Heterogeneous catalysis for clean hydrogen.",
        "detail_page": "https://www.grants.gov/x/1", "posted_date": "2026-07-20",
        "close_date": "2026-12-01",
    },
    {
        "opportunity_id": "2", "opportunity_number": "NYSERDA-3",
        "title": "Solar energy storage", "agency": "NYSERDA", "source": "NYSERDA",
        "source_type": "State", "status": "posted", "topic_areas": ["Energy"],
        "description": "Grid-scale storage.", "url": "https://nyserda.example/3",
        "posted_date": "2026-07-25", "close_date": "2026-11-15",
    },
]


class BuildFeedsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"opportunities": RECORDS}
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "feeds"
        self.manifest = build_feeds.build_feeds(
            self.catalog,
            self.out,
            as_of=date(2026, 7, 25),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_feed_is_valid_atom_with_all_entries(self):
        tree = ElementTree.parse(self.out / "all.xml")  # raises if malformed
        entries = tree.findall(f"{ATOM}entry")
        self.assertEqual(len(entries), 2)

    def test_special_characters_are_escaped(self):
        # Parsing already proves well-formedness; confirm the title survived intact.
        tree = ElementTree.parse(self.out / "all.xml")
        titles = {e.findtext(f"{ATOM}title") for e in tree.findall(f"{ATOM}entry")}
        self.assertIn("Catalysis & hydrogen <production>", titles)

    def test_entries_are_newest_first(self):
        tree = ElementTree.parse(self.out / "all.xml")
        ids = [e.findtext(f"{ATOM}id") for e in tree.findall(f"{ATOM}entry")]
        self.assertTrue(ids[0].endswith(":2"))  # posted 2026-07-25 is newest

    def test_per_topic_and_source_type_feeds_exist(self):
        self.assertTrue((self.out / "source-type/federal.xml").exists())
        self.assertTrue((self.out / "source-type/state.xml").exists())
        self.assertTrue((self.out / "topic/energy.xml").exists())

    def test_best_url_prefers_official_link(self):
        self.assertEqual(build_feeds.best_url(RECORDS[0]), "https://www.grants.gov/x/1")
        self.assertEqual(build_feeds.best_url(RECORDS[1]), "https://nyserda.example/3")

    def test_manifest_lists_all_feed(self):
        with open(self.out / "index.json", encoding="utf-8") as handle:
            manifest = json.load(handle)
        urls = {feed["url"] for feed in manifest["feeds"]}
        self.assertIn(f"{build_feeds.FEEDS_BASE}/all.xml", urls)

    def test_catalog_timestamp_makes_generation_deterministic(self):
        catalog = {
            "generated_at": "2026-07-27T10:30:00Z",
            "opportunities": RECORDS,
        }
        build_feeds.build_feeds(catalog, self.out, as_of=date(2026, 7, 25))
        first = (self.out / "all.xml").read_text(encoding="utf-8")
        build_feeds.build_feeds(catalog, self.out, as_of=date(2026, 7, 25))
        second = (self.out / "all.xml").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertIn("2026-07-27T10:30:00Z", first)

    def test_obsolete_managed_facet_feed_is_removed(self):
        obsolete = self.out / "topic" / "obsolete.xml"
        obsolete.write_text("<feed/>", encoding="utf-8")
        build_feeds.build_feeds(
            self.catalog,
            self.out,
            as_of=date(2026, 7, 25),
        )
        self.assertFalse(obsolete.exists())

    def test_source_first_seen_dates_sort_undated_external_records(self):
        undated = dict(
            RECORDS[0],
            opportunity_id="3",
            posted_date=None,
            last_updated=None,
            source_first_seen_date="2026-07-26",
        )
        recent = build_feeds.sorted_recent([RECORDS[0], undated], 2)
        self.assertEqual(recent[0]["opportunity_id"], "3")

    def test_runtime_gate_excludes_expired_records(self):
        expired = dict(
            RECORDS[0],
            opportunity_id="expired",
            close_date="2026-07-24",
        )
        build_feeds.build_feeds(
            {"opportunities": [*RECORDS, expired]},
            self.out,
            as_of=date(2026, 7, 25),
        )
        tree = ElementTree.parse(self.out / "all.xml")
        ids = [entry.findtext(f"{ATOM}id") for entry in tree.findall(f"{ATOM}entry")]
        self.assertFalse(any(value.endswith(":expired") for value in ids))
        manifest = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["excluded_noncurrent"], 1)


if __name__ == "__main__":
    unittest.main()
