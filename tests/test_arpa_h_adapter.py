"""Bounded offline tests for the official ARPA-H current-opportunity adapter."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sources.adapters.arpa_h import (  # noqa: E402
    ArpaHAdapter,
    parse_listing,
)
from scripts.sources.base import SourceAdapter  # noqa: E402


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "arpa_h"
    / "open_opportunities.html"
)


def adapter():
    instance = ArpaHAdapter.__new__(ArpaHAdapter)
    SourceAdapter.__init__(instance)
    instance._client = None
    return instance


def payload():
    listing = FIXTURE.read_text(encoding="utf-8")
    pages = {
        "/explore-funding/programs/fastpass": (
            "Solicitation Notice ID: ARPA-H-SOL-26-160 "
            "Full Proposal Due: November 10, 2026"
        ),
        "/explore-funding/programs/rest": (
            "Notice ID: ARPA-H-SOL-26-159 "
            "Solution Summary Requested by: August 12, 2026"
        ),
        "/explore-funding/programs/stream": (
            "Notice ID: ARPA-H-SOL-24-105 Proposal Due: September 14, 2026"
        ),
        "/explore-funding/initiatives-and-sprints/tigar": (
            "Notice ID: ARPA-H-SOL-26-144 Full Proposal Due: September 17, 2026"
        ),
        "/explore-funding/initiatives-and-sprints/ascent-ibo": (
            "Notice ID: ARPA-H-SOL-24-106 "
            "Solution Summary Requested by: October 15, 2026"
        ),
        "/explore-funding/sbir/2026-sbir-sttr-topics": (
            "Notice ID: 7599226SN106 Proposal Package Due: September 11, 2026"
        ),
    }
    return {"listing_html": listing, "detail_pages": pages}


class ListingTests(unittest.TestCase):
    def test_the_frozen_public_population_has_ten_rows(self):
        rows = parse_listing(payload()["listing_html"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(
            {row["opportunity_class"] for row in rows},
            {"program", "initiative", "small_business", "mission_office_iso"},
        )
        self.assertEqual(
            sum(row["opportunity_class"] == "mission_office_iso" for row in rows),
            4,
        )

    def test_duplicate_links_do_not_duplicate_opportunities(self):
        listing = payload()["listing_html"]
        duplicate = listing.replace(
            "</body>",
            '<a href="/explore-funding/programs/fastpass">FASTPASS</a></body>',
        )
        self.assertEqual(len(parse_listing(duplicate)), 10)


class ParseTests(unittest.TestCase):
    def test_detail_pages_supply_notice_ids_and_dates(self):
        records = list(adapter().parse(payload()))
        by_id = {record.external_id: record for record in records}
        self.assertEqual(by_id["fastpass"].opportunity_number, "ARPA-H-SOL-26-160")
        self.assertEqual(by_id["fastpass"].close_date, "2026-11-10")
        self.assertEqual(by_id["tigar"].close_date, "2026-09-17")
        self.assertEqual(by_id["2026-sbir-sttr-topics"].opportunity_number,
                         "7599226SN106")

    def test_shared_umbrella_numbers_are_not_claimed_as_child_ids(self):
        by_id = {record.external_id: record for record in adapter().parse(payload())}
        self.assertIsNone(by_id["stream"].opportunity_number)
        self.assertIsNone(by_id["ascent-ibo"].opportunity_number)

    def test_canary_rejects_a_silent_population_collapse(self):
        thin = payload()
        thin["listing_html"] = (
            '<a href="/explore-funding/programs/fastpass">FASTPASS</a>'
        )
        thin["detail_pages"] = {
            "/explore-funding/programs/fastpass": "Notice ID: ARPA-H-SOL-26-160"
        }
        with self.assertRaisesRegex(ValueError, "canary failed"):
            adapter().parse(thin)

    def test_adapter_is_enabled_after_live_and_offline_canaries(self):
        self.assertTrue(ArpaHAdapter.enabled)


if __name__ == "__main__":
    unittest.main()
