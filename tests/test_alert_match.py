"""Tests for the server-side search matcher used by weekly email digests.

Verifies that a saved search ranks/filters the same way the browser app does,
by reusing the real ``build_search_index`` and mirroring ``bm25Scores``.
"""

import unittest
from datetime import date

from scripts import build_catalog
from scripts.alert_match import (
    is_new_since,
    matches_filters,
    search_catalog,
)


def _base(**overrides):
    record = {
        "opportunity_id": "x",
        "opportunity_number": "OPP-X",
        "title": "Untitled",
        "agency": "Agency",
        "source": "Grants.gov",
        "source_type": "Federal",
        "status": "posted",
        "topic_areas": [],
        "disciplines": [],
        "funding_categories": [],
        "funding_instruments": ["Grant"],
        "applicant_types": ["Institutions of higher education"],
        "eligibility_text": "",
        "description": "",
        "document_search_text": "",
        "posted_date": "2026-07-01",
        "close_date": "2026-12-01",
    }
    record.update(overrides)
    return record


RECORDS = [
    _base(
        opportunity_id="1", opportunity_number="DE-FOA-1",
        title="Catalysis for clean hydrogen production",
        agency="Department of Energy",
        topic_areas=["Catalysis and reaction engineering", "Energy"],
        disciplines=["Chemistry"], funding_categories=["Energy"],
        description="Advancing heterogeneous catalysis and electrocatalysis for hydrogen.",
        document_search_text="catalysis hydrogen", posted_date="2026-07-20",
    ),
    _base(
        opportunity_id="2", opportunity_number="NSF-2",
        title="Coastal ecology and marine biology research",
        agency="National Science Foundation",
        topic_areas=["Biology and biotechnology", "Environmental science"],
        disciplines=["Biological Sciences"], funding_categories=["Science and Technology"],
        description="Marine ecosystems and coastal biology.", posted_date="2026-07-10",
    ),
    _base(
        opportunity_id="3", opportunity_number="NYSERDA-3",
        title="Solar energy storage demonstration",
        agency="NYSERDA", source="NYSERDA", source_type="State",
        topic_areas=["Energy", "Manufacturing"], disciplines=["Engineering"],
        funding_categories=["Energy"], applicant_types=["For-profit organizations"],
        description="Grid-scale solar storage.", posted_date="2026-07-25",
    ),
]


def make_catalog(records):
    return {
        "opportunities": records,
        "search_index": build_catalog.build_search_index(records),
        "record_count": len(records),
    }


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_catalog(RECORDS)

    def test_query_ranks_relevant_first(self):
        results = search_catalog(self.catalog, "catalysis")
        self.assertTrue(results)
        self.assertEqual(results[0]["opportunity_id"], "1")

    def test_query_excludes_nonmatching(self):
        ids = {r["opportunity_id"] for r in search_catalog(self.catalog, "catalysis")}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)  # marine biology should not match "catalysis"

    def test_filter_only_returns_by_recency(self):
        results = search_catalog(self.catalog, "", {"source_type": ["State"]})
        self.assertEqual([r["opportunity_id"] for r in results], ["3"])

    def test_query_and_filter_combine_as_and(self):
        results = search_catalog(self.catalog, "energy", {"source_type": ["Federal"]})
        ids = {r["opportunity_id"] for r in results}
        self.assertIn("1", ids)      # federal energy
        self.assertNotIn("3", ids)   # energy but State -> filtered out

    def test_facet_is_or_within(self):
        self.assertTrue(matches_filters(RECORDS[0], {"topic": ["Energy", "Nonexistent"]}))
        self.assertFalse(matches_filters(RECORDS[0], {"topic": ["Nonexistent"]}))

    def test_opportunity_number_exact_match_ranks_first(self):
        results = search_catalog(self.catalog, "NYSERDA-3")
        self.assertEqual(results[0]["opportunity_id"], "3")

    def test_is_new_since(self):
        self.assertTrue(is_new_since(RECORDS[2], date(2026, 7, 24)))   # posted 07-25
        self.assertFalse(is_new_since(RECORDS[1], date(2026, 7, 24)))  # posted 07-10

    def test_same_day_and_source_first_seen_are_not_missed(self):
        self.assertTrue(is_new_since(RECORDS[2], date(2026, 7, 25)))
        undated_external = _base(
            posted_date=None,
            last_updated=None,
            source_first_seen_date="2026-07-25",
        )
        self.assertTrue(is_new_since(undated_external, date(2026, 7, 25)))

    def test_empty_query_no_filters_returns_all_newest_first(self):
        results = search_catalog(self.catalog, "")
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["opportunity_id"], "3")  # 07-25 newest


if __name__ == "__main__":
    unittest.main()
