"""P8.5 — the six lifecycle cases, and fail-closed source health.

Offline. These run the **whole** merge path rather than the adapter alone, because
the claim P8 has to earn is about the published catalog: emission →
`filter_publishable` → health bounds → the snapshot cache → `merge_records` →
`rebuild_catalog` → `validate_catalog` → `write_catalog`.

The point of cases 4 and 5 together is that **the 51 inactive elements need no
human follow-up**: the scheduled refresh re-reads the whole inventory every run, so
an element leaves when it stops being actionable and returns when it starts again.

Case 6 is the one that protects what is already published: a broken parse must not
be readable as "NASA removed everything".
"""

from datetime import date
import json
import pathlib
import tempfile
import unittest

from scripts.sources.adapters.nasa_roses import NasaRosesAdapter
from scripts.sources.merge import integrate, load_catalog

AS_OF = date(2026, 8, 18)
PAST = "02/27/2026"
FUTURE = "12/03/2026"
LATER = "01/15/2027"

DIVISIONS = ("A", "B", "C", "D", "E", "F")


def _row(code, title, cells, *, overview=False):
    link = (
        "https://nspires.nasaprs.com/external/viewrepositorydocument?cmdocumentid=1"
        if overview
        else f"https://nspires.nasaprs.com/external/solicitations/summary.do?solId={{{code}}}"
    )
    tds = "".join(f"<td>{cell}</td>" for cell in cells)
    return (
        f'<tr><td><a href="{link}">{code}</a></td>'
        f"<td>{title}</td>{tds}</tr>"
    )


def table3(extra_rows=()):
    """A Table-3-shaped page: six overview rows, 42 inactive fillers, plus extras.

    The fillers exist so the measured health floor (40 elements) and the six
    division sentinel both pass, which is a precondition for any lifecycle claim.
    They are all past their date, so they are inactive inventory and never emitted.
    """
    rows = [
        _row(f"{division}.1", f"{division} Division Overview",
             ["N/A", "N/A"], overview=True)
        for division in DIVISIONS
    ]
    for division in DIVISIONS:
        for index in range(2, 9):
            rows.append(
                _row(f"{division}.{index}", f"{division} Filler Program {index}",
                     ["N/A", PAST])
            )
    rows.extend(extra_rows)
    return (
        "<html><body><table>"
        "<tr><th>APPENDIX</th><th>PROGRAM</th><th>NOI</th><th>Proposal</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )


def payload(extra_rows=(), *, table2=True):
    html = table3(extra_rows)
    return {
        "year": 2025,
        "table3_html": html,
        "table2_html": html if table2 else None,
        "amendment": 70,
    }


def target_element(cells):
    """The one element each lifecycle case moves through its states."""
    return _row("C.9", "Controlled Lifecycle Element", cells)


def grants_gov_record(**overrides):
    record = {
        "opportunity_id": "111111",
        "opportunity_number": "GG-BASE-1",
        "title": "An unrelated Grants.gov opportunity",
        "agency": "Test Agency",
        "source": "Grants.gov",
        "source_type": "Federal",
        "status": "posted",
        "posted_date": "2026-01-01",
        "close_date": "2027-06-30",
        "detail_page": "https://www.grants.gov/x/111111",
    }
    record.update(overrides)
    return record


class LifecycleHarness(unittest.TestCase):
    """One temp catalog plus one temp snapshot cache, driven through integrate()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.catalog_path = self.root / "opportunities.js"
        self.cache_path = self.root / "source_records.json"
        self.write_catalog([grants_gov_record()])

    def write_catalog(self, records):
        catalog = {
            "schema_version": 3,
            "generated_at": f"{AS_OF.isoformat()}T00:00:00Z",
            "source": {"name": "Grants.gov", "url": "https://www.grants.gov/"},
            "record_count": len(records),
            "opportunities": records,
            "diagnostics": {},
        }
        self.catalog_path.write_bytes(
            ("globalThis.GRANT_CATALOG=" + json.dumps(catalog) + ";\n").encode("utf-8")
        )

    def refresh(self, data, *, catalog_extra=()):
        """One scheduled refresh. Returns (summary, catalog, roses_records)."""
        instance = NasaRosesAdapter()
        instance.fetch = lambda: data
        if catalog_extra:
            existing = load_catalog(self.catalog_path)["opportunities"]
            self.write_catalog(list(existing) + list(catalog_extra))
        summary = integrate(
            catalog_path=self.catalog_path,
            cache_path=self.cache_path,
            adapters=[instance],
            include_disabled=True,
            write=True,
            as_of=AS_OF,
        )
        catalog = load_catalog(self.catalog_path)
        roses = [
            record for record in catalog["opportunities"]
            if str(record.get("opportunity_id", "")).startswith("nasa-roses:")
        ]
        return summary, catalog, roses

    def assertConsistent(self, catalog):
        """The invariants `assets/app.js` asserts, checked here rather than assumed."""
        records = catalog["opportunities"]
        self.assertEqual(catalog["record_count"], len(records))
        self.assertEqual(catalog["search_index"]["document_count"], len(records))
        identities = [
            record.get("opportunity_number") or record.get("opportunity_id")
            for record in records
        ]
        self.assertEqual(len(identities), len(set(identities)))


class SixLifecycleCases(LifecycleHarness):

    def test_1_an_inactive_unmatched_element_stays_absent(self):
        _summary, catalog, roses = self.refresh(payload([target_element(["N/A", PAST])]))
        self.assertEqual(roses, [])
        self.assertConsistent(catalog)

    def test_2_an_actionable_unmatched_element_enters_the_catalog(self):
        summary, catalog, roses = self.refresh(
            payload([target_element(["N/A", FUTURE])])
        )
        self.assertEqual(len(roses), 1)
        self.assertEqual(roses[0]["title"], "ROSES25: C.9 Controlled Lifecycle Element")
        self.assertEqual(roses[0]["close_date"], "2026-12-03")
        self.assertEqual(roses[0]["source"], "NASA ROSES")
        self.assertEqual(summary["sources"][0]["status"], "refreshed")
        self.assertConsistent(catalog)

    def test_3_an_actionable_matched_element_does_not_duplicate(self):
        existing = grants_gov_record(
            opportunity_id="222222",
            opportunity_number="NNH25ZDA001N-CTRL",
            title="ROSES25: C.9 Controlled Lifecycle Element",
        )
        _summary, catalog, roses = self.refresh(
            payload([target_element(["N/A", FUTURE])]), catalog_extra=[existing]
        )
        self.assertEqual(roses, [])
        matching = [
            record for record in catalog["opportunities"]
            if "C.9 Controlled Lifecycle Element" in record["title"]
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["source"], "Grants.gov")
        self.assertConsistent(catalog)

    def test_4_a_published_element_leaves_when_it_stops_being_actionable(self):
        _s1, _c1, roses = self.refresh(payload([target_element(["N/A", FUTURE])]))
        self.assertEqual(len(roses), 1)
        # Next scheduled refresh: NASA's date has passed.
        _s2, catalog, roses_after = self.refresh(
            payload([target_element(["N/A", PAST])])
        )
        self.assertEqual(roses_after, [])
        self.assertConsistent(catalog)

    def test_5_inactive_inventory_returns_automatically_when_it_reopens(self):
        """No human follow-up: the refresh re-reads the whole inventory."""
        _s1, _c1, roses = self.refresh(payload([target_element(["Not Solicited This Year"])]))
        self.assertEqual(roses, [])
        _s2, catalog, roses_after = self.refresh(
            payload([target_element(["N/A", LATER])])
        )
        self.assertEqual(len(roses_after), 1)
        self.assertEqual(roses_after[0]["close_date"], "2027-01-15")
        self.assertConsistent(catalog)

    def test_6_a_broken_parse_does_not_delete_published_nasa_records(self):
        _s1, _c1, roses = self.refresh(payload([target_element(["N/A", FUTURE])]))
        self.assertEqual(len(roses), 1)
        # HTTP 200, zero rows: the characteristic silent failure of an agency page.
        summary, catalog, roses_after = self.refresh(
            {"year": 2025, "table3_html": "<html><body><p>ok</p></body></html>",
             "table2_html": None, "amendment": None}
        )
        self.assertEqual(len(roses_after), 1, "last known good must be retained")
        self.assertEqual(summary["sources"][0]["status"], "failed_kept_last_good")
        self.assertIsNotNone(summary["sources"][0]["error"])
        self.assertConsistent(catalog)


class HealthIsEvaluatedBeforeRemovalTests(LifecycleHarness):
    """Missing rows may only mean "removed" once the source is known healthy."""

    def test_a_missing_division_is_a_failure_not_a_removal(self):
        _s1, _c1, roses = self.refresh(payload([target_element(["N/A", FUTURE])]))
        self.assertEqual(len(roses), 1)
        html = table3([target_element(["N/A", FUTURE])]).replace(">F.", ">ZZ.")
        summary, catalog, roses_after = self.refresh(
            {"year": 2025, "table3_html": html, "table2_html": None,
             "amendment": None}
        )
        self.assertEqual(len(roses_after), 1)
        self.assertIn("division sentinel", summary["sources"][0]["error"])
        self.assertConsistent(catalog)

    def test_catastrophic_shrinkage_is_a_failure_not_a_removal(self):
        _s1, _c1, roses = self.refresh(payload([target_element(["N/A", FUTURE])]))
        self.assertEqual(len(roses), 1)
        rows = [
            _row(f"{division}.1", f"{division} Division Overview",
                 ["N/A", "N/A"], overview=True)
            for division in DIVISIONS
        ] + [_row("A.2", "Only Element", ["N/A", FUTURE])]
        html = (
            "<html><body><table>"
            "<tr><th>APPENDIX</th><th>PROGRAM</th><th>NOI</th><th>Proposal</th></tr>"
            + "".join(rows) + "</table></body></html>"
        )
        summary, catalog, roses_after = self.refresh(
            {"year": 2025, "table3_html": html, "table2_html": None,
             "amendment": None}
        )
        self.assertEqual(len(roses_after), 1)
        self.assertIn("element floor", summary["sources"][0]["error"])
        self.assertConsistent(catalog)

    def test_a_healthy_refresh_with_nothing_actionable_is_not_a_failure(self):
        """Zero emitted records is the steady state, not a broken source."""
        summary, catalog, roses = self.refresh(payload())
        self.assertEqual(roses, [])
        self.assertEqual(summary["sources"][0]["status"], "refreshed")
        self.assertIsNone(summary["sources"][0]["error"])
        self.assertConsistent(catalog)


class InventoryVisibilityTests(LifecycleHarness):
    """The inactive inventory must be inspectable without being publishable."""

    def test_the_inventory_is_recorded_in_the_snapshot_diagnostics(self):
        self.refresh(payload([target_element(["N/A", PAST])]))
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        diagnostics = cache["sources"]["nasa-roses"]["diagnostics"]
        self.assertEqual(diagnostics["elements"], 43)
        self.assertEqual(diagnostics["actionable_unmatched"], 0)
        self.assertEqual(diagnostics["inactive_unmatched"], 43)
        titles = {item["title"] for item in diagnostics["inactive_inventory"]}
        self.assertIn("Controlled Lifecycle Element", titles)
        self.assertEqual(cache["sources"]["nasa-roses"]["records"], [])

    def test_the_catalog_diagnostics_carry_the_same_counts(self):
        _summary, catalog, _roses = self.refresh(
            payload([target_element(["N/A", FUTURE])])
        )
        adapters = catalog["diagnostics"]["additional_sources"]["adapters"]
        roses = [entry for entry in adapters if entry["slug"] == "nasa-roses"][0]
        self.assertTrue(roses["ok"])
        self.assertEqual(roses["record_count"], 1)
        self.assertEqual(roses["diagnostics"]["actionable_unmatched"], 1)
        self.assertEqual(roses["diagnostics"]["matched"], 0)


if __name__ == "__main__":
    unittest.main()
