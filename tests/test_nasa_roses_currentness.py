"""P8.4 — NASA's native status and Funding Finder's derived currentness.

Offline. Every state below is one NASA actually publishes, counted in
`docs/ROSES_SOURCE_INSPECTION.md` §4 from a live fetch:

    N/A 32 · Not Solicited This Year 14 · TBD 4 · No Due Date [3]/[4]/[5] 3 ·
    Not Solicited see C.2 and F.3 1 · Follow link from title 1 · dates ~60

The rule this file pins is DEC-13's: **an unmatched element enters the public
catalog when it is current/actionable and stays out while it is inactive, past,
TBD or Not Solicited This Year** — and the two fields never merge, because NASA
publishes no `closed` state and ours is inferred.
"""

from datetime import date
import unittest

from scripts.sources.adapters import nasa_roses
from scripts.sources.adapters.nasa_roses import (
    NasaRosesAdapter,
    classify_native_status,
    derive_currentness,
    parse_dates,
)

TODAY = date(2026, 8, 18)


def element(*date_cells, code="X.1", title="Some Program Element", overview=False):
    """One Table 3 row in the shape `parse_table` produces."""
    row = {
        "appendix_code": code,
        "title": title,
        "due_date_cells": list(date_cells),
        "native_deadline_text": " | ".join(date_cells),
        "element_url": "https://nspires.nasaprs.com/x/summary.do?solId={A}",
        "is_overview": overview,
        "appendix_order": 1,
        "division": code.split(".")[0],
        "amended": False,
    }
    row["native_status"] = classify_native_status(row["due_date_cells"], overview)
    row["identity"] = (row["appendix_code"], row["title"])
    return row


class NativeStatusVocabularyTests(unittest.TestCase):
    """Every measured source state maps to NASA's own wording, not ours."""

    CASES = [
        (("N/A", "12/03 /2026"), nasa_roses.NATIVE_DATED),
        (("N/A", "N/A"), nasa_roses.NATIVE_NONE),
        (("Not Solicited This Year",), nasa_roses.NATIVE_NOT_SOLICITED),
        (("Not Solicited see C.2 and F.3",), nasa_roses.NATIVE_NOT_SOLICITED),
        (("TBD", "TBD"), nasa_roses.NATIVE_TBD),
        (("No Due Date [3]",), nasa_roses.NATIVE_NO_DUE_DATE),
        (("No Due Date [4]",), nasa_roses.NATIVE_NO_DUE_DATE),
        (("Follow link from title",), nasa_roses.NATIVE_FOLLOW_LINK),
        (("12/15/2026 (Step-1)", "02/02 /2027 (Step-2)"), nasa_roses.NATIVE_DATED),
        (("N/A", "09/17/2026 (Phase-1 via ARK RPS)"), nasa_roses.NATIVE_DATED),
        (("N/A", "10/14/2026 (Mandatory NOI)"), nasa_roses.NATIVE_DATED),
    ]

    def test_every_measured_state_maps(self):
        for cells, expected in self.CASES:
            with self.subTest(cells=cells):
                self.assertEqual(classify_native_status(list(cells), False), expected)

    def test_no_state_maps_to_closed(self):
        """NASA publishes no `closed` status, so we must never invent one."""
        for cells, _expected in self.CASES:
            self.assertNotEqual(
                classify_native_status(list(cells), False), "closed"
            )
        self.assertNotIn(
            "closed",
            {
                nasa_roses.NATIVE_DATED, nasa_roses.NATIVE_NONE,
                nasa_roses.NATIVE_NOT_SOLICITED, nasa_roses.NATIVE_TBD,
                nasa_roses.NATIVE_NO_DUE_DATE, nasa_roses.NATIVE_FOLLOW_LINK,
                nasa_roses.NATIVE_OVERVIEW,
            },
        )

    def test_an_overview_row_is_its_own_state(self):
        self.assertEqual(
            classify_native_status(["N/A", "N/A"], True), nasa_roses.NATIVE_OVERVIEW
        )

    def test_dirty_date_formatting_still_parses(self):
        for text in ("12/03 /2026", "12/ 15 /2026", "1/26/2027", "02/02 /2027"):
            with self.subTest(text=text):
                self.assertTrue(parse_dates(text))


class DerivedCurrentnessTests(unittest.TestCase):
    """Ours, inferred from dates, and never confused with NASA's."""

    def test_a_future_date_is_open(self):
        self.assertEqual(
            derive_currentness(element("N/A", "12/03 /2026"), TODAY),
            nasa_roses.DERIVED_OPEN,
        )

    def test_a_past_date_is_closed_by_inference(self):
        self.assertEqual(
            derive_currentness(element("N/A", "02/27/2026"), TODAY),
            nasa_roses.DERIVED_CLOSED,
        )

    def test_todays_date_is_still_open(self):
        self.assertEqual(
            derive_currentness(element("N/A", "08/18/2026"), TODAY),
            nasa_roses.DERIVED_OPEN,
        )

    def test_the_latest_date_governs_a_two_step_element(self):
        """A passed Step-1 with a future Step-2 is still actionable."""
        self.assertEqual(
            derive_currentness(
                element("06/01/2026 (Step-1)", "11/30/2026 (Step-2)"), TODAY
            ),
            nasa_roses.DERIVED_OPEN,
        )

    def test_rolling_submission_is_open(self):
        self.assertEqual(
            derive_currentness(element("No Due Date [3]"), TODAY),
            nasa_roses.DERIVED_OPEN,
        )

    def test_undated_states_are_undated_not_closed(self):
        """Not solicited, TBD, follow-link and N/A are unknown, not closed."""
        for cells in (
            ("Not Solicited This Year",),
            ("Not Solicited see C.2 and F.3",),
            ("TBD", "TBD"),
            ("Follow link from title",),
            ("N/A", "N/A"),
        ):
            with self.subTest(cells=cells):
                self.assertEqual(
                    derive_currentness(element(*cells), TODAY),
                    nasa_roses.DERIVED_UNDATED,
                )

    def test_an_amended_date_is_evaluated_like_any_other(self):
        """Amendment is a version signal, not a status."""
        amended = dict(element("N/A", "11/30/2026"), amended=True)
        self.assertEqual(derive_currentness(amended, TODAY), nasa_roses.DERIVED_OPEN)
        self.assertEqual(amended["native_status"], nasa_roses.NATIVE_DATED)


class EmissionFollowsCurrentnessTests(unittest.TestCase):
    """DEC-13 in one table: which states reach the public catalog, and which do not."""

    EMITTED = [("N/A", "12/03 /2026"), ("No Due Date [3]",),
               ("06/01/2026 (Step-1)", "11/30/2026 (Step-2)")]
    WITHHELD = [("N/A", "02/27/2026"), ("Not Solicited This Year",),
                ("Not Solicited see C.2 and F.3",), ("TBD", "TBD"),
                ("Follow link from title",), ("N/A", "N/A")]

    def _reconcile(self, cells):
        instance = NasaRosesAdapter()
        rows = [element(*cells, code="C.9", title="Controlled Element")]
        return instance.reconcile(
            rows, catalog_records=[], year=2025, today=TODAY
        )

    def test_actionable_states_are_emitted(self):
        for cells in self.EMITTED:
            with self.subTest(cells=cells):
                report = self._reconcile(cells)
                self.assertEqual(len(report["actionable_unmatched"]), 1)
                self.assertEqual(len(report["inactive_unmatched"]), 0)

    def test_inactive_states_stay_out(self):
        for cells in self.WITHHELD:
            with self.subTest(cells=cells):
                report = self._reconcile(cells)
                self.assertEqual(len(report["actionable_unmatched"]), 0)
                self.assertEqual(len(report["inactive_unmatched"]), 1)

    def test_native_and_derived_are_reported_separately(self):
        report = self._reconcile(("N/A", "02/27/2026"))
        inactive = report["inactive_unmatched"][0]
        self.assertEqual(inactive["native_status"], nasa_roses.NATIVE_DATED)
        self.assertEqual(inactive["derived_currentness"], nasa_roses.DERIVED_CLOSED)
        # The raw wording NASA printed survives alongside both.
        self.assertIn("02/27/2026", inactive["native_deadline_text"])

    def test_an_overview_row_is_never_a_candidate(self):
        instance = NasaRosesAdapter()
        rows = [
            element("N/A", "N/A", code="A.1", title="Earth Science Overview",
                    overview=True),
            element("N/A", "12/03 /2026", code="A.2", title="Real Element"),
        ]
        report = instance.reconcile(rows, catalog_records=[], year=2025, today=TODAY)
        self.assertEqual(report["elements"], 1)
        self.assertEqual(len(report["actionable_unmatched"]), 1)
        self.assertEqual(
            report["actionable_unmatched"][0]["title"], "Real Element"
        )


class EmittedRecordCurrentnessTests(unittest.TestCase):
    """The emitted record must agree with the catalog-wide currentness rule."""

    def _record(self, *cells):
        instance = NasaRosesAdapter()
        opportunity = instance.opportunity_for(
            element(*cells, code="C.9", title="Controlled Element"), 2025
        )
        return opportunity.to_record(
            slug=instance.slug, source=instance.display_name,
            source_type=instance.source_type,
        )

    def test_a_dated_record_carries_that_date_as_its_close_date(self):
        record = self._record("N/A", "12/03 /2026")
        self.assertEqual(record["close_date"], "2026-12-03")

    def test_a_two_step_record_closes_on_the_last_date(self):
        record = self._record("06/01/2026 (Step-1)", "11/30/2026 (Step-2)")
        self.assertEqual(record["close_date"], "2026-11-30")

    def test_a_rolling_record_carries_no_close_date(self):
        """No invented date. NASA published none."""
        record = self._record("No Due Date [3]")
        self.assertIsNone(record["close_date"])
        self.assertIn("No Due Date", record["close_date_note"])

    def test_the_record_agrees_with_scripts_currentness(self):
        from scripts.currentness import record_is_current

        current, reason = record_is_current(self._record("N/A", "12/03 /2026"), TODAY)
        self.assertTrue(current)
        self.assertEqual(reason, "current_by_close_date")

    def test_a_record_whose_date_passes_stops_being_current(self):
        from scripts.currentness import record_is_current

        record = self._record("N/A", "12/03 /2026")
        current, reason = record_is_current(record, date(2027, 1, 1))
        self.assertFalse(current)
        self.assertEqual(reason, "expired")

    def test_the_publishable_filter_agrees_with_the_emission_rule(self):
        from scripts.sources.validate import record_is_publishable

        ok, reason = record_is_publishable(self._record("N/A", "12/03 /2026"), TODAY)
        self.assertTrue(ok, reason)
        expired = self._record("N/A", "02/27/2026")
        ok, reason = record_is_publishable(expired, TODAY)
        self.assertFalse(ok)
        self.assertEqual(reason, "expired")


if __name__ == "__main__":
    unittest.main()
