from datetime import date
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.build_changes import diff_catalogs, write_change_feed


AS_OF = date(2026, 7, 30)


def rec(ident, **overrides):
    value = {
        "opportunity_id": ident,
        "opportunity_number": f"TEST-{ident}",
        "title": f"Opportunity {ident}",
        "agency": "Test Agency",
        "source": "Grants.gov",
        "status": "posted",
        "posted_date": "2026-07-01",
        "close_date": "2026-10-30",
        "last_updated": "2026-07-01",
        "version": "1",
        "detail_page": f"https://www.grants.gov/x/{ident}",
    }
    value.update(overrides)
    return value


def catalog(records):
    return {
        "generated_at": "2026-07-30T12:00:00Z",
        "opportunities": records,
    }


class ChangeFeedTests(unittest.TestCase):
    def test_detects_new_deadline_amendment_closing_and_removal(self):
        previous = catalog([
            rec("1"),
            rec("2"),
            rec("3", close_date="2026-08-29"),
            rec("5"),
        ])
        current = catalog([
            rec("1", close_date="2026-09-15", last_updated="2026-07-29"),
            rec("3", close_date="2026-08-29"),
            rec("4", close_date="2026-12-01"),
            rec("5", status="cancelled"),
        ])

        events = diff_catalogs(previous, current, as_of=AS_OF)
        kinds = {(event["type"], event["opportunity_id"]) for event in events}

        self.assertIn(("deadline_changed", "1"), kinds)
        self.assertIn(("amended", "1"), kinds)
        self.assertIn(("closing_soon", "3"), kinds)
        self.assertIn(("new", "4"), kinds)
        self.assertIn(("closed_or_removed", "2"), kinds)
        self.assertIn(("closed_or_removed", "5"), kinds)

    def test_writes_valid_atom_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            summary = write_change_feed(
                catalog([]),
                catalog([rec("1")]),
                out,
                as_of=AS_OF,
            )

            self.assertEqual(summary["new_event_count"], 1)
            ElementTree.parse(out / "changes.xml")
            self.assertTrue((out / "changes.json").exists())

    def test_detects_non_closing_status_transition(self):
        events = diff_catalogs(
            catalog([rec("1", status="forecasted")]),
            catalog([rec("1", status="posted")]),
            as_of=AS_OF,
        )

        status_event = next(event for event in events if event["type"] == "status_changed")
        self.assertEqual(status_event["opportunity_id"], "1")
        self.assertEqual(status_event["old_status"], "forecasted")
        self.assertEqual(status_event["new_status"], "posted")


if __name__ == "__main__":
    unittest.main()
