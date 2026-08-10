"""Tests for the server-side search matcher used by weekly email digests.

Verifies that a saved search ranks/filters the same way the browser app does,
by reusing the real ``build_search_index`` and mirroring ``bm25Scores``.
"""

import unittest
from datetime import date
from unittest.mock import patch

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
        self.as_of = date(2026, 7, 25)

    def test_query_ranks_relevant_first(self):
        results = search_catalog(self.catalog, "catalysis", as_of=self.as_of)
        self.assertTrue(results)
        self.assertEqual(results[0]["opportunity_id"], "1")

    def test_common_abbreviation_finds_expanded_catalog_language(self):
        carbon = _base(
            opportunity_id="carbon",
            title="Carbon dioxide removal research",
            description="Capture atmospheric carbon dioxide for durable storage.",
        )
        unrelated = _base(
            opportunity_id="unrelated",
            title="Coastal habitat restoration",
            description="Restore marine habitats and coastal ecosystems.",
        )
        catalog = make_catalog([carbon, unrelated])

        for query in ("CO2", "CO₂"):
            with self.subTest(query=query):
                results = search_catalog(catalog, query, as_of=self.as_of)
                self.assertEqual(
                    [item["opportunity_id"] for item in results],
                    ["carbon"],
                )

    def test_existing_literal_abbreviation_is_not_broadened(self):
        literal = _base(
            opportunity_id="literal",
            title="AI safety evaluation",
            description="Evaluation methods for AI systems.",
        )
        long_form_only = _base(
            opportunity_id="long-form",
            title="Artificial intelligence infrastructure",
            description="Infrastructure for artificial intelligence research.",
        )
        catalog = make_catalog([literal, long_form_only])

        results = search_catalog(catalog, "AI", as_of=self.as_of)

        self.assertEqual(
            [item["opportunity_id"] for item in results],
            ["literal"],
        )

    def test_new_relevant_announcement_outranks_stronger_old_match(self):
        old = _base(
            opportunity_id="old",
            title="Established catalysis program",
            posted_date="2026-05-01",
        )
        new = _base(
            opportunity_id="new",
            title="New catalysis announcement",
            posted_date="2026-07-25",
        )
        catalog = make_catalog([old, new])
        with patch(
            "scripts.alert_match.bm25_scores",
            return_value=([100.0, 25.0], True),
        ):
            results = search_catalog(catalog, "catalysis", as_of=self.as_of)
        self.assertEqual([item["opportunity_id"] for item in results], ["new", "old"])

    def test_weak_new_match_does_not_hijack_relevance(self):
        old = _base(
            opportunity_id="old",
            title="Established catalysis program",
            posted_date="2026-05-01",
        )
        weak_new = _base(
            opportunity_id="weak-new",
            title="Marginally related new announcement",
            posted_date="2026-07-25",
        )
        catalog = make_catalog([old, weak_new])
        with patch(
            "scripts.alert_match.bm25_scores",
            return_value=([100.0, 19.9], True),
        ):
            results = search_catalog(catalog, "catalysis", as_of=self.as_of)
        self.assertEqual([item["opportunity_id"] for item in results], ["old", "weak-new"])

    def test_new_relevance_priority_expires_after_two_weeks(self):
        old = _base(
            opportunity_id="old",
            title="Established catalysis program",
            posted_date="2026-05-01",
        )
        no_longer_new = _base(
            opportunity_id="fifteen-days-old",
            title="Recent catalysis announcement",
            posted_date="2026-07-10",
        )
        catalog = make_catalog([old, no_longer_new])
        with patch(
            "scripts.alert_match.bm25_scores",
            return_value=([100.0, 25.0], True),
        ):
            results = search_catalog(catalog, "catalysis", as_of=self.as_of)
        self.assertEqual(
            [item["opportunity_id"] for item in results],
            ["old", "fifteen-days-old"],
        )

    def test_query_excludes_nonmatching(self):
        ids = {r["opportunity_id"] for r in search_catalog(self.catalog, "catalysis", as_of=self.as_of)}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)  # marine biology should not match "catalysis"

    def test_filter_only_returns_by_recency(self):
        results = search_catalog(self.catalog, "", {"source_type": ["State"]}, as_of=self.as_of)
        self.assertEqual([r["opportunity_id"] for r in results], ["3"])

    def test_query_and_filter_combine_as_and(self):
        results = search_catalog(self.catalog, "energy", {"source_type": ["Federal"]}, as_of=self.as_of)
        ids = {r["opportunity_id"] for r in results}
        self.assertIn("1", ids)      # federal energy
        self.assertNotIn("3", ids)   # energy but State -> filtered out

    def test_facet_is_or_within(self):
        self.assertTrue(matches_filters(RECORDS[0], {"topic": ["Energy", "Nonexistent"]}))
        self.assertFalse(matches_filters(RECORDS[0], {"topic": ["Nonexistent"]}))

    def test_opportunity_number_exact_match_ranks_first(self):
        results = search_catalog(self.catalog, "NYSERDA-3", as_of=self.as_of)
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
        results = search_catalog(self.catalog, "", as_of=self.as_of)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["opportunity_id"], "3")  # 07-25 newest

    def test_runtime_gate_drops_an_expired_match(self):
        expired = _base(
            opportunity_id="expired",
            title="Catalysis expired",
            description="catalysis",
            close_date="2026-07-24",
        )
        catalog = make_catalog([*RECORDS, expired])
        ids = {
            item["opportunity_id"]
            for item in search_catalog(
                catalog,
                "catalysis",
                as_of=self.as_of,
            )
        }
        self.assertNotIn("expired", ids)


if __name__ == "__main__":
    unittest.main()
