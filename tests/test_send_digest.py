"""Tests for the weekly digest engine's pure logic (no SMTP, no network).

The engine lives in the deliverable bundle at docs/weekly-alerts/ so it can be
copied into a private repo; we add that folder to the path to import it.
"""

import sys
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "docs" / "weekly-alerts"))

import send_digest  # noqa: E402
from scripts.alert_match import is_new_since  # noqa: E402
from scripts.build_feeds import best_url  # noqa: E402


def rec(**kw):
    base = {
        "opportunity_id": "1", "title": "A grant", "agency": "DOE",
        "source": "Grants.gov", "close_date": "2026-12-01",
        "description": "Some description", "detail_page": "https://grants.gov/x/1",
        "posted_date": "2026-07-20",
    }
    base.update(kw)
    return base


class SelectNewTests(unittest.TestCase):
    def test_keeps_only_new_and_unseen(self):
        ranked = [
            rec(opportunity_id="1", posted_date="2026-07-25"),  # new
            rec(opportunity_id="2", posted_date="2026-07-10"),  # too old
            rec(opportunity_id="3", posted_date="2026-07-26"),  # new but already seen
        ]
        fresh = send_digest.select_new(ranked, date(2026, 7, 22), {"3"}, is_new_since)
        self.assertEqual([r["opportunity_id"] for r in fresh], ["1"])

    def test_respects_limit(self):
        ranked = [rec(opportunity_id=str(i), posted_date="2026-07-25") for i in range(50)]
        fresh = send_digest.select_new(ranked, date(2026, 7, 1), set(), is_new_since, limit=10)
        self.assertEqual(len(fresh), 10)

    def test_selects_relevant_change_events_and_deduplicates(self):
        ranked = [rec(opportunity_id="1")]
        events = [
            {
                "id": "event-1",
                "type": "deadline_changed",
                "changed_at": "2026-07-25T12:00:00Z",
                "opportunity_id": "1",
                "record": rec(opportunity_id="1"),
            },
            {
                "id": "event-2",
                "type": "amended",
                "changed_at": "2026-07-25T12:00:00Z",
                "opportunity_id": "2",
                "record": rec(opportunity_id="2"),
            },
        ]
        selected = send_digest.select_updates(
            events,
            ranked,
            set(),
            {"event-2"},
            date(2026, 7, 22),
        )
        self.assertEqual([event["id"] for event in selected], ["event-1"])


class ConsentTests(unittest.TestCase):
    def test_consent_is_fail_closed(self):
        self.assertFalse(send_digest.subscription_is_active({"active": True}))
        self.assertFalse(send_digest.subscription_is_active({"confirmed": False}))
        self.assertFalse(send_digest.subscription_is_active({"active": False, "confirmed": True}))
        self.assertTrue(send_digest.subscription_is_active({"active": True, "confirmed": True}))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.sub = {"query": "catalysis", "filters": {"source_type": ["Federal"]}, "email": "a@b.edu"}
        self.items = [rec(title="Catalysis grant", agency="DOE")]

    def test_text_has_title_link_and_unsubscribe(self):
        body = send_digest.render_text(self.sub, self.items, best_url)
        self.assertIn("Catalysis grant", body)
        self.assertIn("https://grants.gov/x/1", body)
        self.assertIn("reply", body.lower())

    def test_html_is_escaped_and_has_link(self):
        items = [rec(title="R&D <energy>")]
        html = send_digest.render_html(self.sub, items, best_url)
        self.assertIn("R&amp;D &lt;energy&gt;", html)
        self.assertNotIn("<energy>", html)

    def test_renders_deadline_change_section(self):
        updates = [{
            "label": "Deadline changed",
            "detail": "2026-09-01 → 2026-10-01",
            "record": rec(title="Changed opportunity"),
        }]
        text = send_digest.render_text(
            self.sub,
            [],
            best_url,
            updates,
        )
        self.assertIn("CHANGES TO MATCHES YOU FOLLOW", text)
        self.assertIn("Deadline changed", text)

    def test_describe_search_includes_query_and_filters(self):
        text = send_digest._describe_search(self.sub)
        self.assertIn("catalysis", text)
        self.assertIn("Federal", text)

    def test_email_is_masked(self):
        self.assertEqual(send_digest._mask("amy.researcher@example.edu"), "am…@example.edu")


if __name__ == "__main__":
    unittest.main()
