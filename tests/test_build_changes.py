from copy import deepcopy
from datetime import date
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.build_changes import diff_catalogs, write_change_feed
from scripts.build_catalog import catalog_javascript_bytes
from scripts.submission_schedule import project
from tools.catalog_publication_evidence import change_snapshot_findings


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
    def test_normal_writer_preserves_invitation_quotes_and_retained_history(self):
        # Native candidate 5f30d210 failed publication when the writer changed
        # this official title's en dash inside both invitation-evidence fields.
        as_of = date(2026, 11, 18)
        title = "DOJ FY 2026 Invited to Apply \u2013 Model Cities Initiative (MCI)"
        record = project(rec("364275", title=title, close_date="2026-11-30",
            opportunity_number="O-BJA-2026-172814",
            deadlines=[{"kind": "application", "date": "2026-11-30",
                "source_field": "CloseDate", "confidence": "official_structured",
                "invitation_required": True, "prerequisite": "invitation",
                "invitation_evidence": {"source_field": "title", "quote": title,
                    "source_url": "https://www.grants.gov/search-results-detail/364275"}}]), as_of)
        current = catalog([record])
        current["generated_at"] = "2026-11-18T18:56:51.080828Z"
        canonical = json.loads(catalog_javascript_bytes(current).decode().split("=", 1)[1].strip().removesuffix(";"))
        previous = catalog([])
        expected = diff_catalogs(previous, canonical, as_of=as_of)[0]
        self.assertEqual(expected["id"], "ea1602cf180474dde010")
        historical = deepcopy(expected)
        historical.update(id="retained-history", changed_at="2026-11-17T18:56:51Z",
            detail="Previously recorded \u2014 keep this wording")
        originals = deepcopy((previous, canonical, historical))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "changes.json").write_text(json.dumps({"events": [historical]}, ensure_ascii=False), encoding="utf-8")
            summary = write_change_feed(previous, canonical, out, as_of=as_of)
            feed = json.loads((out / "changes.json").read_bytes())
            self.assertEqual(summary, {"new_event_count": 1, "retained_event_count": 2})
            self.assertEqual(feed["events"], [expected, historical])
            snapshot = feed["events"][0]["record"]
            self.assertEqual(snapshot["deadlines"], canonical["opportunities"][0]["deadlines"])
            self.assertEqual(snapshot["next_submission"], canonical["opportunities"][0]["next_submission"])
            self.assertEqual(snapshot["next_submission"]["event"]["invitation_evidence"]["quote"], title)
            self.assertEqual(change_snapshot_findings(canonical, feed), [])
            atom = ElementTree.parse(out / "changes.xml")
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entries = atom.findall("a:entry", ns)
            self.assertEqual(entries[0].findtext("a:title", namespaces=ns), "New opportunity: " + title.replace("\u2013", "-"))
            self.assertEqual(entries[1].findtext("a:summary", namespaces=ns), "Previously recorded - keep this wording")
        self.assertEqual((previous, canonical, historical), originals)

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
