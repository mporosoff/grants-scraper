"""NASA ROSES native adapter (§18.1 D⅝ S1). Offline: no host is contacted.

Fixtures under tests/fixtures/roses/ are the live 2026-08-17 responses, kept
whole (~34 KB each) rather than trimmed: the element-count canary is only
meaningful against the real population, and the tables carry every measured
shape -- six overview rows, 3-cell colspan rows, the 3-cell row that omits a
cell (C.5), the duplicated D.3C pair, and A.7 present in Table 2 only.
"""

import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sources.adapters import nasa_roses  # noqa: E402
from scripts.sources.adapters.nasa_roses import NasaRosesAdapter  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "roses"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def payload(table3="table3.html", table2="table2.html"):
    return {
        "year": 2025,
        "amendment": 69,
        "table3_html": read(table3) if table3 else "",
        "table2_html": read(table2) if table2 else None,
    }


def adapter():
    instance = NasaRosesAdapter.__new__(NasaRosesAdapter)
    from scripts.sources.base import SourceAdapter
    SourceAdapter.__init__(instance)
    instance._client = None                 # nothing here touches the network
    return instance


class DiscoveryTests(unittest.TestCase):
    def test_the_roses_year_is_discovered_not_hard_coded(self):
        found = adapter().discover_table_urls(read("sara_landing.html"))
        self.assertEqual(found["year"], 2025)
        self.assertTrue(found["table3"].endswith("ROSES2025table3"))
        self.assertTrue(found["table2"].endswith("ROSES2025table2"))

    def test_a_newer_cycle_wins_over_an_older_one(self):
        html = ('<a href="https://solicitation.nasaprs.com/ROSES2025table3">a</a>'
                '<a href="https://solicitation.nasaprs.com/ROSES2026table3">b</a>')
        self.assertEqual(adapter().discover_table_urls(html)["year"], 2026)

    def test_a_missing_table3_link_is_an_error_not_a_silent_empty(self):
        with self.assertRaises(RuntimeError):
            adapter().discover_table_urls("<html><body>nothing</body></html>")

    def test_amendment_is_read_from_the_resolved_url(self):
        resolved = (
            "https://nspires.nasaprs.com/external/viewrepositorydocument/"
            "Table%203%20ROSES-2025_Amend%2070.html"
        )
        self.assertEqual(adapter()._amendment_of(resolved), 70)

    def test_html_without_an_amendment_cannot_erase_the_resolved_url_signal(self):
        short = "https://solicitation.nasaprs.com/ROSES2025table3"
        resolved = (
            "https://nspires.nasaprs.com/external/viewrepositorydocument/"
            "Table%203%20ROSES-2025_Amend%2070.html"
        )

        class Client:
            last_url = None

            def get_text(self, url):
                self.last_url = resolved if url == short else url
                return "<html><body>no amendment text here</body></html>"

        instance = adapter()
        instance._client = Client()
        instance.discover_table_urls = lambda: {
            "year": 2025,
            "table3": short,
            "table2": None,
        }
        fetched = instance.fetch()
        self.assertNotIn("Amend", fetched["table3_html"])
        self.assertEqual(fetched["table3_url"], resolved)
        self.assertEqual(fetched["amendment"], 70)

    def test_a_non_amended_url_has_no_amendment_diagnostic(self):
        self.assertIsNone(
            adapter()._amendment_of(
                "https://solicitation.nasaprs.com/ROSES2025table3"
            )
        )

    def test_amendment_changes_only_diagnostics_not_emitted_records(self):
        first = adapter()
        first.set_context({
            "catalog_records": [], "as_of": datetime.date(2025, 1, 1)
        })
        payload_69 = payload()
        records_69 = list(first.parse(payload_69))

        second = adapter()
        second.set_context({
            "catalog_records": [], "as_of": datetime.date(2025, 1, 1)
        })
        payload_70 = {**payload_69, "amendment": 70}
        records_70 = list(second.parse(payload_70))

        self.assertEqual(records_69, records_70)
        self.assertEqual(first.diagnostics["amendment"], 69)
        self.assertEqual(second.diagnostics["amendment"], 70)


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.rows = adapter().rows(payload())
        self.overview, self.elements = adapter().split_rows(self.rows)

    def test_overview_rows_are_separated_from_program_elements(self):
        self.assertEqual(
            [row["appendix_code"] for row in self.overview],
            ["A.1", "B.1", "C.1", "D.1", "E.1", "F.1"],
        )
        self.assertTrue(all(r["native_status"] == nasa_roses.NATIVE_OVERVIEW
                            for r in self.overview))
        self.assertNotIn("A.1", [r["appendix_code"] for r in self.elements])

    def test_appendix_order_is_preserved_not_sorted(self):
        orders = [row["appendix_order"] for row in self.rows]
        self.assertEqual(orders, sorted(orders))

    def test_duplicate_codes_are_preserved_as_distinct_elements(self):
        """D.3C appears twice in the live source, for XRISM Type 1 and Type 2."""
        d3c = [r for r in self.rows if r["appendix_code"] == "D.3C"]
        self.assertEqual(len(d3c), 2)
        self.assertNotEqual(d3c[0]["identity"], d3c[1]["identity"])
        self.assertEqual({r["identity"][0] for r in d3c}, {"D.3C"})

    def test_three_cell_rows_parse_with_and_without_colspan(self):
        by_code = {r["appendix_code"]: r for r in self.rows}
        self.assertEqual(by_code["C.3"]["native_status"],
                         nasa_roses.NATIVE_NOT_SOLICITED)   # colspan row
        self.assertIn("C.5", by_code)                        # no-colspan row

    def test_native_deadline_text_is_preserved_before_normalisation(self):
        by_code = {r["appendix_code"]: r for r in self.rows}
        self.assertIn("Step-1", by_code["A.2"]["native_deadline_text"])
        self.assertIn("Step-2", by_code["A.2"]["native_deadline_text"])

    def test_element_urls_are_preserved_and_unescaped(self):
        for row in self.elements:
            if row["element_url"]:
                self.assertNotIn("&amp;", row["element_url"])


class NativeStatusTests(unittest.TestCase):
    def test_every_measured_status_maps(self):
        rows = adapter().rows(payload())
        by_code = {r["appendix_code"]: r for r in rows}
        self.assertEqual(by_code["A.2"]["native_status"], nasa_roses.NATIVE_DATED)
        self.assertEqual(by_code["A.4"]["native_status"],
                         nasa_roses.NATIVE_NO_DUE_DATE)
        self.assertEqual(by_code["C.3"]["native_status"],
                         nasa_roses.NATIVE_NOT_SOLICITED)
        self.assertEqual(by_code["D.4"]["native_status"], nasa_roses.NATIVE_TBD)
        self.assertEqual(by_code["F.2"]["native_status"],
                         nasa_roses.NATIVE_FOLLOW_LINK)
        self.assertEqual(by_code["C.5"]["native_status"],
                         nasa_roses.NATIVE_NONE)
        self.assertEqual(by_code["A.1"]["native_status"],
                         nasa_roses.NATIVE_OVERVIEW)

    def test_dirty_date_formats_parse(self):
        """`12/03 /2025`, `12/ 15 /2025` and `1/26/2026` all occur live."""
        self.assertEqual(nasa_roses.parse_dates("12/03 /2025"),
                         [datetime.date(2025, 12, 3)])
        self.assertEqual(nasa_roses.parse_dates("12/ 15 /2025"),
                         [datetime.date(2025, 12, 15)])
        self.assertEqual(nasa_roses.parse_dates("1/26/2026"),
                         [datetime.date(2026, 1, 26)])
        self.assertEqual(nasa_roses.parse_dates("N/A"), [])

    def test_closure_is_derived_and_labelled_as_derived(self):
        """NASA publishes no closed status; the adapter must not invent one."""
        rows = adapter().rows(payload())
        statuses = {r["native_status"] for r in rows}
        self.assertNotIn("closed", statuses)
        self.assertNotIn("expired", statuses)
        by_code = {r["appendix_code"]: r for r in rows}
        past = nasa_roses.derive_currentness(
            by_code["A.2"], today=datetime.date(2030, 1, 1))
        self.assertEqual(past, nasa_roses.DERIVED_CLOSED)
        future = nasa_roses.derive_currentness(
            by_code["A.2"], today=datetime.date(2000, 1, 1))
        self.assertEqual(future, nasa_roses.DERIVED_OPEN)

    def test_no_due_date_is_open_and_not_solicited_is_undated(self):
        rows = adapter().rows(payload())
        by_code = {r["appendix_code"]: r for r in rows}
        self.assertEqual(nasa_roses.derive_currentness(by_code["A.4"]),
                         nasa_roses.DERIVED_OPEN)
        self.assertEqual(nasa_roses.derive_currentness(by_code["C.3"]),
                         nasa_roses.DERIVED_UNDATED)


class EmissionBoundaryTests(unittest.TestCase):
    """P6.1's scope decision, enforced in code rather than by convention.

    **Changed once, by P8, and only this class's first test.** P6.1 pinned
    `enabled is False` because standalone ingestion was an open decision; DEC-13
    took that decision and P8 built it, so the adapter is now an enabled catalog
    source. The other assertions in this class did **not** need changing, which is
    the useful part: without the merge's catalog context `parse()` still emits
    nothing, so P6.1's boundary survives as P8's fail-closed default.
    """

    def test_the_adapter_is_enabled_by_p8(self):
        """Was `test_the_adapter_is_disabled`; see the class docstring (DEC-13)."""
        self.assertTrue(NasaRosesAdapter.enabled)

    def test_parse_emits_nothing_without_catalog_context(self):
        self.assertEqual(list(adapter().parse(payload())), [])

    def test_collect_produces_no_catalog_records_without_context(self):
        """Unmatched elements cannot leak into opportunities.js by accident."""
        instance = adapter()
        instance.fetch = lambda: payload()
        self.assertEqual(instance.collect(), [])

    def test_standalone_inventory_is_measured_but_separate(self):
        instance = adapter()
        rows = instance.rows(payload())
        _overview, elements = instance.split_rows(rows)
        matched = {elements[0]["identity"]}
        inventory = instance.standalone_inventory(rows, catalog_matches=matched)
        self.assertEqual(len(inventory), len(elements) - 1)
        # It is a plain measurement, never a CanonicalOpportunity.
        from scripts.sources.base import CanonicalOpportunity
        for item in inventory:
            self.assertNotIsInstance(item, CanonicalOpportunity)
        # And it never reaches the catalog path.
        instance.fetch = lambda: payload()
        self.assertEqual(instance.collect(), [])


class CanaryTests(unittest.TestCase):
    def test_a_healthy_source_passes_all_three(self):
        instance = adapter()
        health = instance.check_health(payload())
        self.assertTrue(health["healthy"], health["failures"])
        self.assertEqual(health["failures"], [])
        self.assertEqual(sorted(health["divisions"]),
                         ["A", "B", "C", "D", "E", "F"])

    def test_http_200_with_zero_rows_fails_loudly(self):
        """The characteristic silent failure: a restyled page, 200, no rows."""
        instance = adapter()
        health = instance.check_health(
            {"table3_html": "<html><body><p>ok</p></body></html>",
             "table2_html": None}
        )
        self.assertFalse(health["healthy"])
        self.assertEqual(health["program_elements"], 0)
        self.assertTrue(any("division sentinel" in f for f in health["failures"]))
        self.assertTrue(any("element floor" in f for f in health["failures"]))

    def test_a_missing_division_fails_the_primary_sentinel(self):
        html = read("table3.html").replace(">F.", ">ZZ.")
        health = adapter().check_health(
            {"table3_html": html, "table2_html": None})
        self.assertFalse(health["healthy"])
        self.assertTrue(any("missing F" in f for f in health["failures"]))

    def test_catastrophic_shrinkage_trips_the_floor(self):
        """Two elements is not an annual cycle; it is a broken parse."""
        rows = adapter().rows(payload())
        # Keep all six divisions so the PRIMARY sentinel still passes; only the
        # element floor may fire. Eight rows is not an annual cycle.
        keep = [r for r in rows if r["appendix_code"] in
                ("A.1", "B.1", "C.1", "D.1", "E.1", "F.1", "A.2", "A.4")]
        health = adapter().check_health(payload(), rows=keep)
        self.assertFalse(health["healthy"])
        self.assertTrue(any("element floor" in f for f in health["failures"]))

    def test_the_cross_table_check_tolerates_the_measured_a7_gap(self):
        """A.7 is in Table 2 and not Table 3 -- legitimate, must not fail."""
        health = adapter().check_health(payload())
        self.assertEqual(health["cross_table_delta"], 1)
        self.assertEqual(health["warnings"], [])
        self.assertTrue(health["healthy"])

    def test_material_cross_table_divergence_warns_without_failing(self):
        instance = adapter()
        thin = read("table2.html").split("<tr")[0] + "</table></body></html>"
        health = instance.check_health(
            {"table3_html": read("table3.html"), "table2_html": thin})
        self.assertTrue(any("cross-table" in w for w in health["warnings"]))
        # Tertiary: a Table 2 problem warns, it does not condemn Table 3.
        self.assertTrue(health["healthy"])

    def test_a_missing_table2_warns_rather_than_failing(self):
        health = adapter().check_health(
            {"table3_html": read("table3.html"), "table2_html": None})
        self.assertTrue(health["healthy"])
        self.assertTrue(any("Table 2 unavailable" in w
                            for w in health["warnings"]))


if __name__ == "__main__":
    unittest.main()
