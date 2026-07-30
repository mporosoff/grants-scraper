from datetime import date
import unittest

from scripts.currentness import filter_current, non_funding_reason, record_is_current


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


if __name__ == "__main__":
    unittest.main()
