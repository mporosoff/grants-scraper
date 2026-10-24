from datetime import date
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.currentness import filter_current, non_funding_reason, record_is_current
from scripts.submission_schedule import administrative_submission_closed


AS_OF = date(2026, 7, 30)


def record(**overrides):
    value = {
        "opportunity_id": "1",
        "title": "Research grant",
        "status": "posted",
        "close_date": "2026-08-30",
        "archive_date": "2026-09-30",
        "funding_instruments": ["Grant"],
        "description": "",
    }
    value.update(overrides)
    return value


class CurrentnessTests(unittest.TestCase):
    def test_source_verification_expires_without_a_new_catalog_or_official_closure(self):
        value = record(close_date='2027-01-01', source_review_after='2026-07-30')
        before = deepcopy(value)
        self.assertTrue(record_is_current(value, AS_OF)[0])
        self.assertEqual(record_is_current(value, date(2026, 7, 31)), (False, 'source_review_expired'))
        for invalid in ('2026-02-30', 'tomorrow', 123):
            self.assertEqual(record_is_current(dict(value, source_review_after=invalid), AS_OF),
                             (False, 'invalid_source_review_date'))
        self.assertEqual(value, before)

    def test_keeps_future_and_rolling_records(self):
        self.assertTrue(record_is_current(record(), AS_OF)[0])
        self.assertTrue(
            record_is_current(
                record(close_date=None, archive_date=None, rolling=True),
                AS_OF,
            )[0]
        )

    def test_rejects_past_deadline_even_if_status_says_posted(self):
        current, reason = record_is_current(
            record(close_date="2026-07-29"),
            AS_OF,
        )
        self.assertFalse(current)
        self.assertEqual(reason, "expired")

    def test_rejects_unknown_or_closed_status(self):
        self.assertFalse(
            record_is_current(record(status="closed"), AS_OF)[0]
        )
        self.assertFalse(
            record_is_current(record(status=""), AS_OF)[0]
        )

    def test_rejects_placeholder_notice_of_intent(self):
        notice = record(
            title="DE-FOA-123 Notice of Intent to Issue a Funding Opportunity",
            close_date="2099-12-31",
        )
        self.assertEqual(non_funding_reason(notice), "informational_notice")
        self.assertFalse(record_is_current(notice, AS_OF)[0])

    def test_rejects_other_instrument_not_accepting_applications(self):
        notice = record(
            funding_instruments=["Other"],
            description="This notice is not accepting applications.",
        )
        self.assertEqual(
            non_funding_reason(notice),
            "not_accepting_applications",
        )

    def test_filter_reports_exclusion_reason(self):
        kept, excluded = filter_current(
            [record(), record(opportunity_id="2", close_date="2026-01-01")],
            AS_OF,
        )
        self.assertEqual([item["opportunity_id"] for item in kept], ["1"])
        self.assertEqual(excluded[0]["reason"], "expired")

    def test_administrative_close_does_not_reopen_the_actual_application_deadline(self):
        from tests.test_administrative_close_contract import corrected_record
        value = corrected_record()
        before = deepcopy(value)
        for day, expected in ((13, True), (14, True), (15, False), (19, False)):
            with self.subTest(day=day):
                instant = date(2026, 10, day)
                self.assertEqual(record_is_current(value, instant)[0], expected)
                self.assertEqual(administrative_submission_closed(value, instant), not expected)
        self.assertEqual(record_is_current(value, date(2026, 10, 19))[1], 'submission_closed')
        self.assertEqual(value, before)  # Cached next_submission is not the runtime clock.

    def test_administrative_override_preserves_alternate_submission_paths(self):
        from tests.test_administrative_close_contract import corrected_record
        alternatives = [
            {'kind': 'application', 'date': '2026-11-03', 'cycle': 'Second cycle'},
            {'kind': 'application', 'date': '2026-11-03', 'track': 'Other track'},
            {'kind': 'application', 'date': '2026-11-03', 'application_class': 'resubmission'},
            {'kind': 'application', 'date': None, 'rolling': True},
            {'kind': 'application', 'date': None, 'rolling': True, 'application_class': 'resubmission'},
        ]
        for alternative in alternatives:
            with self.subTest(alternative=alternative):
                value = corrected_record()
                value['deadlines'].append(alternative)
                self.assertFalse(administrative_submission_closed(value, date(2026, 10, 19)))
                self.assertTrue(record_is_current(value, date(2026, 10, 19))[0])
        value = corrected_record()
        value['rolling'] = True
        self.assertTrue(record_is_current(value, date(2026, 10, 19))[0])

    def test_override_requires_a_qualified_same_source_close_and_proven_closed_schedule(self):
        from tests.test_administrative_close_contract import corrected_record
        values = [record(close_date='2026-12-16', deadlines=[{'kind': 'submission', 'date': '2026-12-16'}])]
        unqualified = corrected_record()
        for event in unqualified['deadlines']:
            event.pop('date_qualifier', None)
        values.append(unqualified)
        other_close = corrected_record()
        other_close['close_date'] = '2026-12-17'
        values.append(other_close)
        administrative_only = corrected_record()
        administrative_only['deadlines'] = administrative_only['deadlines'][:1]
        values.append(administrative_only)
        for value in values:
            with self.subTest(record=value):
                self.assertFalse(administrative_submission_closed(value, date(2026, 10, 19)))
                self.assertTrue(record_is_current(value, date(2026, 10, 19))[0])

    def test_current_feeds_and_digest_exclude_the_same_closed_administrative_record(self):
        from tests.test_administrative_close_contract import corrected_record
        from scripts.alert_match import search_catalog
        from scripts.build_feeds import build_feeds
        value = corrected_record()
        catalog = {'generated_at': '2026-10-19T17:00:00Z', 'opportunities': [value]}
        self.assertEqual(search_catalog(catalog, as_of=date(2026, 10, 19)), [])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            feeds = build_feeds(catalog, out, as_of=date(2026, 10, 19))
            self.assertEqual(feeds[0]['count'], 0)
            self.assertEqual(json.loads((out / 'index.json').read_text())['excluded_noncurrent'], 1)
            self.assertNotIn('362893', (out / 'all.xml').read_text())


if __name__ == "__main__":
    unittest.main()
