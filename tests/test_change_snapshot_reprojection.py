from copy import deepcopy
from datetime import date
import json
import unittest
from xml.etree import ElementTree

from scripts.build_changes import (
    refresh_current_generation_snapshots,
    render_change_feed,
)
from scripts.submission_schedule import next_submission, project


GENERATION = "2026-11-01T21:07:21.809150Z"
FEED_GENERATION = "2026-11-01T21:15:13Z"
AS_OF = date(2026, 11, 1)


def scaled_projection():
    # Bounded public SCALED regression from candidate c3b755938cb2b59c:
    # the retained new event used Part 2; Part 1 supplies the required concept.
    old = {
        "opportunity_id": "364174",
        "opportunity_number": "DE-FOA-0003641",
        "title": "Grid Supply Chain Alternatives to Lead Energy Dominance (SCALED)",
        "agency": "National Energy Technology Laboratory",
        "source": "Grants.gov",
        "status": "posted",
        "close_date": "2027-02-08",
        "detail_page": "https://www.grants.gov/search-results-detail/364174",
        "primary_document_url": "https://grants.gov/grantsws/rest/opportunity/att/download/355416",
        "deadlines": [{"kind": "application", "date": "2027-02-08"}],
    }
    old = project(old, AS_OF)
    current = deepcopy(old)
    current["primary_document_url"] = "https://apply07.grants.gov:443/grantsws/rest/opportunity/att/download/355417"
    current["deadlines"].append({
        "kind": "concept_paper", "date": "2026-11-20", "required": True,
        "evidence_id": "evidence-364174-03d5dd02e03c",
        "source_url": current["primary_document_url"],
    })
    current = project(current, AS_OF)
    event = {
        "id": "d14ef23da1bd1d2e753f", "type": "new", "label": "New opportunity",
        "changed_at": GENERATION, "opportunity_id": "364174",
        "detail": "First appeared in the public catalog", "record": old,
    }
    historical = deepcopy(event)
    historical.update(id="prior-generation-event", changed_at="2026-10-31T21:07:21Z")
    unrelated = deepcopy(event)
    unrelated.update(id="other-current-event", opportunity_id="364188")
    unrelated["record"]["opportunity_id"] = "364188"
    feed = {
        "schema_version": 1, "generated_at": FEED_GENERATION, "retention_days": 90,
        "events": [event, unrelated, historical],
    }
    return feed, {"generated_at": GENERATION, "opportunities": [current]}


class ChangeSnapshotReprojectionTests(unittest.TestCase):
    def test_scaled_current_event_exposes_required_concept_without_rewriting_history(self):
        feed, catalog = scaled_projection()
        old_event = feed["events"][0]
        self.assertEqual(next_submission(old_event["record"], AS_OF)["date"], "2027-02-08")

        repaired = refresh_current_generation_snapshots(feed, catalog, affected_ids=["364174"])
        event = repaired["events"][0]
        submission = next_submission(event["record"], AS_OF)
        self.assertEqual(submission["date"], "2026-11-20")
        self.assertEqual(submission["event"]["kind"], "concept_paper")
        self.assertTrue(submission["event"]["required"])
        self.assertEqual(event["record"]["close_date"], "2027-02-08")
        self.assertTrue(event["record"]["primary_document_url"].endswith("/355417"))
        self.assertEqual({k: v for k, v in event.items() if k != "record"},
                         {k: v for k, v in old_event.items() if k != "record"})
        self.assertEqual(repaired["events"][1:], feed["events"][1:])
        self.assertEqual({k: v for k, v in repaired.items() if k != "events"},
                         {k: v for k, v in feed.items() if k != "events"})
        self.assertEqual(len(repaired["events"]), len(feed["events"]))

    def test_projection_is_explicit_nonmutating_and_idempotent(self):
        feed, catalog = scaled_projection()
        originals = deepcopy((feed, catalog))
        self.assertEqual(refresh_current_generation_snapshots(feed, catalog, affected_ids=[]), feed)
        repaired = refresh_current_generation_snapshots(feed, catalog, affected_ids=["364174"])
        again = refresh_current_generation_snapshots(repaired, catalog, affected_ids=["364174"])
        self.assertEqual(render_change_feed(repaired), render_change_feed(again))
        self.assertEqual((feed, catalog), originals)
        repaired["events"][0]["record"]["deadlines"][0]["date"] = "2099-01-01"
        self.assertEqual((feed, catalog), originals)

    def test_exact_generation_stamp_does_not_replace_a_same_day_historical_event(self):
        feed, catalog = scaled_projection()
        feed["events"][0]["changed_at"] = "2026-11-01T20:07:21.809150Z"
        self.assertEqual(refresh_current_generation_snapshots(feed, catalog, affected_ids=["364174"]), feed)

    def test_missing_generation_or_selected_record_fails_without_modifying_input(self):
        feed, catalog = scaled_projection()
        original = deepcopy(feed)
        for current, selected, reason in (
            ({"opportunities": catalog["opportunities"]}, ["364174"], "generation_required"),
            (catalog, ["missing"], "record_missing"),
            (catalog, "364174", "ids_required"),
        ):
            with self.assertRaisesRegex(ValueError, reason):
                refresh_current_generation_snapshots(feed, current, affected_ids=selected)
        self.assertEqual(feed, original)

    def test_renderer_preserves_feed_clock_and_event_identity_in_both_formats(self):
        feed, catalog = scaled_projection()
        repaired = refresh_current_generation_snapshots(feed, catalog, affected_ids=["364174"])
        rendered = render_change_feed(repaired)
        self.assertEqual(set(rendered), {"changes.json", "changes.xml"})
        decoded = json.loads(rendered["changes.json"])
        self.assertEqual(decoded, repaired)
        atom = ElementTree.fromstring(rendered["changes.xml"])
        ns = {"a": "http://www.w3.org/2005/Atom"}
        self.assertEqual(atom.findtext("a:updated", namespaces=ns), FEED_GENERATION)
        entries = atom.findall("a:entry", ns)
        self.assertEqual([entry.findtext("a:id", namespaces=ns) for entry in entries],
                         ["urn:funding-finder:change:" + event["id"] for event in feed["events"]])
        self.assertEqual(entries[0].findtext("a:updated", namespaces=ns), GENERATION)
        self.assertEqual(entries[0].findtext("a:summary", namespaces=ns), feed["events"][0]["detail"])
        # SCALED's Atom entry has no deadline body; its correct Grants.gov link
        # and generic announcement stay identical while the JSON is repaired.
        self.assertEqual(rendered["changes.xml"], render_change_feed(feed)["changes.xml"])


if __name__ == "__main__":
    unittest.main()
