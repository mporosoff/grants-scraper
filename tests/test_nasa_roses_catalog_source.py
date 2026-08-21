"""P8.2/P8.3 — ROSES as a catalog source: identity, dedup and precedence.

Offline. Every fixture is the committed ROSES capture plus hand-authored catalog
records, so nothing here touches the network.

What this file pins, and why each rule exists (docs/TOPIC_LAYER_PLAN.md §18.1 P8):

* **Identity within ROSES is `(appendix_code, program_title)`**, cycle-scoped,
  because the measured source contains `D.3C` twice.
* **Cross-source matching is deterministic**: the appendix code printed in a
  catalog record's title, corroborated by an `NNH<yy>ZDA<nnn>[A-Z]-` solicitation
  number. **No fuzzy-title matching is introduced by P8** — the normalised-title
  test that exists in `merge_records` is the framework's pre-existing collision
  backstop, and these tests show it agreeing rather than being relied upon.
* **Grants.gov owns every field of a record it already publishes.** ROSES
  corroborates; it never overwrites.
"""

from datetime import date
import pathlib
import unittest

from scripts.sources.adapters import nasa_roses
from scripts.sources.adapters.nasa_roses import (
    NasaRosesAdapter,
    RosesReconciliationError,
    catalog_roses_index,
    cycle_of,
    element_external_id,
    element_solicitation_number,
)
from scripts.sources.merge import merge_records

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "roses"
TODAY = date(2026, 8, 18)


def payload(**overrides):
    data = {
        "year": 2025,
        "table3_html": (FIXTURES / "table3.html").read_text(encoding="utf-8"),
        "table2_html": (FIXTURES / "table2.html").read_text(encoding="utf-8"),
        "amendment": 69,
    }
    data.update(overrides)
    return data


def catalog_record(number, title, **overrides):
    """A minimal Grants.gov-shaped record, in the shape merge_records reads."""
    record = {
        "opportunity_id": number or title,
        "opportunity_number": number,
        "title": title,
        "agency": "NASA Headquarters",
        "source": "Grants.gov",
        "source_type": "Federal",
        "status": "posted",
        "close_date": "2026-12-31",
        "posted_date": "2026-01-01",
        "detail_page": "https://www.grants.gov/x/1",
    }
    record.update(overrides)
    return record


#: The ten ROSES elements the committed catalog actually carries, verbatim.
CATALOG_ROSES = [
    catalog_record("NNH25ZDA001N-RRNES", "ROSES 2025: A.4 Rapid Response and Novel Research in Earth Science"),
    catalog_record("NNH25ZDA001N-INNOVATE", "ROSES 2025: A.10 INNOVATE"),
    catalog_record("NNH25ZDA001N-AES", "ROSES25: A.13 Accelerating Earth Solutions"),
    catalog_record("NNH25ZDA001N-ATMOS", "ROSES25: A.14 Atmosphere"),
    catalog_record("NNH25ZDA001N-BIOS", "ROSES25: A.15 Biosphere"),
    catalog_record("NNH25ZDA001N-HFR", "ROSES25: B.2 Heliophysics Foundational Research"),
    catalog_record("NNH25ZDA001N-SCUBED", "ROSES 2025: C.2 Solar System Science"),
    catalog_record("NNH25ZDA001N-PSEF", "ROSES25: C.4 Planetary Science Enabling Facilities"),
    catalog_record("NNH25ZDA001N-HWOPSI", "ROSES25: D.8 Habitable Worlds Observatory Precursor Science"),
    catalog_record("NNH25ZDA001N-RIA", "ROSES25: F.17 Research Initiation Awards"),
]


def reconciled(catalog=None, *, today=TODAY, data=None):
    instance = NasaRosesAdapter()
    data = data or payload()
    instance.set_context(
        {"catalog_records": CATALOG_ROSES if catalog is None else catalog,
         "as_of": today}
    )
    opportunities = list(instance.parse(data))
    return instance, opportunities


def records_of(instance, opportunities):
    return [
        opportunity.to_record(
            slug=instance.slug,
            source=instance.display_name,
            source_type=instance.source_type,
        )
        for opportunity in opportunities
    ]


class SourceIdentityTests(unittest.TestCase):
    """Identity within ROSES: `(code, title)`, cycle-scoped."""

    TYPE_1 = {"appendix_code": "D.3C", "title": "XRISM General Observer - Type 1"}
    TYPE_2 = {"appendix_code": "D.3C", "title": "XRISM General Observer - Type 2"}

    def test_same_code_different_title_stays_distinct(self):
        """`D.3C` occurs twice in the measured source. One id would lose a row."""
        self.assertNotEqual(
            element_external_id(self.TYPE_1, 2025),
            element_external_id(self.TYPE_2, 2025),
        )

    def test_an_ordinary_update_does_not_mint_a_second_identity(self):
        """A changed due date, status or amendment flag is the same element."""
        base = dict(self.TYPE_1, due_date_cells=["N/A", "02/27/2026"],
                    native_status="dated", amended=False)
        updated = dict(self.TYPE_1, due_date_cells=["N/A", "11/30/2026"],
                       native_status="dated", amended=True)
        self.assertEqual(
            element_external_id(base, 2025), element_external_id(updated, 2025)
        )

    def test_identity_is_cycle_scoped(self):
        self.assertNotEqual(
            element_external_id(self.TYPE_1, 2025),
            element_external_id(self.TYPE_1, 2026),
        )
        self.assertEqual(cycle_of(2025), "25")
        self.assertEqual(cycle_of(2026), "26")

    def test_the_solicitation_number_is_read_never_synthesised(self):
        self.assertEqual(
            element_solicitation_number(
                {"element_url": "https://solicitation.nasaprs.com/NNH25ZDA001N-ATMOS"}
            ),
            "NNH25ZDA001N-ATMOS",
        )
        self.assertEqual(
            element_solicitation_number(
                {"element_url": "https://nspires.nasaprs.com/x/summary.do?solNum=NNH25ZDA001N-HWOICA"}
            ),
            "NNH25ZDA001N-HWOICA",
        )
        # solId-only rows publish no solicitation number, so we invent none.
        self.assertIsNone(
            element_solicitation_number(
                {"element_url": "https://nspires.nasaprs.com/x/summary.do?solId={ABC}"}
            )
        )
        self.assertIsNone(element_solicitation_number({"element_url": None}))


class CatalogIndexTests(unittest.TestCase):
    """The cross-source key, read off the catalog rather than guessed."""

    def test_every_committed_roses_record_indexes_by_code(self):
        index = catalog_roses_index(CATALOG_ROSES)
        self.assertEqual(len(index["by_code"]), 10)
        self.assertEqual(index["unresolved"], [])
        self.assertIn(("25", "A.14"), index["by_code"])
        self.assertIn(("25", "F.17"), index["by_code"])

    def test_both_title_spellings_parse(self):
        """`ROSES25:` and `ROSES 2025:` both occur in the committed catalog."""
        index = catalog_roses_index([
            catalog_record("NNH25ZDA001N-X", "ROSES25: A.1 Something"),
            catalog_record("NNH25ZDA001N-Y", "ROSES 2025: B.2 Something Else"),
        ])
        self.assertEqual(set(index["by_code"]), {("25", "A.1"), ("25", "B.2")})

    def test_a_non_roses_record_is_ignored(self):
        index = catalog_roses_index([
            catalog_record("DE-FOA-0003600", "DOE Office of Science Financial Assistance")
        ])
        self.assertEqual(index["by_code"], {})
        self.assertEqual(index["unresolved"], [])

    def test_a_roses_number_without_a_parseable_code_is_unresolved(self):
        index = catalog_roses_index([
            catalog_record("NNH25ZDA001N-MYSTERY", "Some retitled NASA opportunity")
        ])
        self.assertEqual(index["by_code"], {})
        self.assertEqual(len(index["unresolved"]), 1)
        self.assertEqual(
            index["unresolved"][0]["reason"],
            "roses_number_without_parseable_appendix_code",
        )


class ReconciliationTests(unittest.TestCase):
    """The measured split, reproduced deterministically from committed evidence."""

    def test_the_measured_split_is_reproduced(self):
        instance, opportunities = reconciled()
        diagnostics = instance.diagnostics
        self.assertEqual(diagnostics["elements"], 63)
        self.assertEqual(diagnostics["overview_rows"], 6)
        self.assertEqual(diagnostics["matched"], 10)
        self.assertEqual(diagnostics["unmatched"], 53)
        self.assertEqual(diagnostics["actionable_unmatched"], 2)
        self.assertEqual(len(opportunities), 2)

    def test_matched_elements_are_never_emitted(self):
        instance, opportunities = reconciled()
        emitted_codes = {
            record["title"].split(":")[1].strip().split(" ")[0]
            for record in records_of(instance, opportunities)
        }
        for record in CATALOG_ROSES:
            code = record["title"].split(":")[1].strip().split(" ")[0]
            self.assertNotIn(code, emitted_codes)

    def test_an_actionable_unmatched_element_appears_exactly_once(self):
        instance, opportunities = reconciled()
        ids = [
            record["opportunity_id"] for record in records_of(instance, opportunities)
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("nasa-roses:") for i in ids))

    def test_a_duplicate_source_code_alone_suppresses_nothing(self):
        """Corrected 2026-08-20 against the source, and this test was the defect.

        It previously asserted that a repeated appendix code held **both** rows for
        review. The measured source says otherwise: `D.3C` names two distinct
        program elements -- different titles, appendix positions 38 and 39,
        different submission routes, and both listed independently in Table 2 as
        well as Table 3 -- so `(cycle, code, title)` separates them and the repeated
        code only breaks the *cross-source* key. With no catalog record carrying
        `D.3C`, nothing is ambiguous and neither row may be suppressed.
        """
        instance, _opportunities = reconciled()
        diagnostics = instance.diagnostics
        # Still reported as a source fact, because it is one.
        self.assertEqual(diagnostics["ambiguous_source_codes"], ["D.3C"])
        # But it suppresses nothing: no catalog record carries D.3C.
        self.assertEqual(diagnostics["review"], [])
        inventory = [
            item for item in diagnostics["inactive_inventory"]
            if item["appendix_code"].upper() == "D.3C"
        ]
        self.assertEqual(len(inventory), 2)
        self.assertEqual(
            {item["title"] for item in inventory},
            {"XRISM General Observer - Type 1", "XRISM General Observer - Type 2"},
        )
        # They are absent from the catalog because they are past their date, which
        # is the only reason that applies to them today.
        for item in inventory:
            self.assertEqual(item["derived_currentness"], nasa_roses.DERIVED_CLOSED)

    def test_the_accounting_closes(self):
        """63 = matched + unmatched + held-for-review, and unmatched splits cleanly."""
        instance, _ = reconciled()
        d = instance.diagnostics
        self.assertEqual(d["matched"] + d["unmatched"] + len(d["review"]), 63)
        self.assertEqual(
            d["actionable_unmatched"] + d["inactive_unmatched"], d["unmatched"]
        )
        self.assertEqual(d["inactive_unmatched"], 51)

    def test_an_unresolvable_catalog_record_fails_closed(self):
        """Cannot prove non-duplication -> emit nothing, loudly, and keep the snapshot."""
        catalog = CATALOG_ROSES + [
            catalog_record("NNH25ZDA001N-MYSTERY", "A retitled NASA opportunity")
        ]
        instance = NasaRosesAdapter()
        instance.set_context({"catalog_records": catalog, "as_of": TODAY})
        with self.assertRaises(RosesReconciliationError):
            list(instance.parse(payload()))

    def test_reconciliation_is_deterministic(self):
        first, first_opportunities = reconciled()
        second, second_opportunities = reconciled()
        self.assertEqual(
            [r["opportunity_id"] for r in records_of(first, first_opportunities)],
            [r["opportunity_id"] for r in records_of(second, second_opportunities)],
        )
        self.assertEqual(first.diagnostics["matched"], second.diagnostics["matched"])

    def test_an_empty_catalog_emits_every_actionable_element(self):
        """With nothing published, every actionable element is a candidate."""
        instance, opportunities = reconciled(catalog=[catalog_record("X-1", "Unrelated")])
        self.assertEqual(instance.diagnostics["matched"], 0)
        self.assertEqual(instance.diagnostics["unmatched"], 63)
        # 12 elements are open today; two of them share the ambiguous D.3C code and
        # are withheld, so the emitted count is the open set minus those.
        self.assertEqual(len(opportunities), instance.diagnostics["actionable_unmatched"])
        self.assertGreater(len(opportunities), 2)


class DuplicateAppendixCodeTests(unittest.TestCase):
    """The two identities, and which one a repeated code can actually break.

    **Added 2026-08-20 as a forward guard.** `D.3C`'s rows are past-dated today, so
    nothing live depends on this — which is exactly why it needs a deterministic
    test. If a future amendment repeats a code on two *open* elements, they must
    publish as two records, not vanish.
    """

    TWINS = [
        {"appendix_code": "D.3C", "title": "XRISM General Observer - Type 1",
         "due_date_cells": ["N/A", "12/03/2026 (Phase-1 via ARK RPS)"],
         "native_deadline_text": "N/A | 12/03/2026 (Phase-1 via ARK RPS)",
         "element_url": "https://nspires.nasaprs.com/x/summary.do?solId={SHARED}",
         "is_overview": False, "appendix_order": 38, "division": "D",
         "amended": True, "native_status": nasa_roses.NATIVE_DATED},
        {"appendix_code": "D.3C", "title": "XRISM General Observer - Type 2",
         "due_date_cells": ["N/A", "12/03/2026 (via NSPIRES)"],
         "native_deadline_text": "N/A | 12/03/2026 (via NSPIRES)",
         "element_url": "https://nspires.nasaprs.com/x/summary.do?solId={SHARED}",
         "is_overview": False, "appendix_order": 39, "division": "D",
         "amended": True, "native_status": nasa_roses.NATIVE_DATED},
    ]

    def _report(self, catalog):
        return NasaRosesAdapter().reconcile(
            self.TWINS, catalog_records=catalog, year=2025, today=TODAY
        )

    def test_two_unmatched_actionable_twins_are_both_publishable(self):
        """The case the old behaviour would have silently suppressed."""
        report = self._report([])
        self.assertEqual(len(report["actionable_unmatched"]), 2)
        self.assertEqual(report["review"], [])
        self.assertEqual(report["ambiguous_source_codes"], ["D.3C"])

    def test_they_emit_as_two_distinct_records(self):
        instance = NasaRosesAdapter()
        report = self._report([])
        records = [
            instance.opportunity_for(element, 2025).to_record(
                slug=instance.slug, source=instance.display_name,
                source_type=instance.source_type,
            )
            for element in report["actionable_unmatched"]
        ]
        self.assertEqual(len({r["opportunity_id"] for r in records}), 2)
        self.assertEqual(len({r["title"] for r in records}), 2)
        # A shared solId does not collapse them, because it is not the key.
        self.assertEqual(len({r["detail_page"] for r in records}), 1)

    def test_they_survive_the_merge_as_two_records(self):
        instance = NasaRosesAdapter()
        report = self._report([])
        external = [
            instance.opportunity_for(element, 2025).to_record(
                slug=instance.slug, source=instance.display_name,
                source_type=instance.source_type,
            )
            for element in report["actionable_unmatched"]
        ]
        combined, stats = merge_records(CATALOG_ROSES, external)
        self.assertEqual(stats["external_added"], 2)
        self.assertEqual(stats["dropped_cross_source_duplicate"], 0)
        self.assertEqual(stats["dropped_duplicate_identity"], 0)
        emitted = [r for r in combined if r["source"] == "NASA ROSES"]
        self.assertEqual(len(emitted), 2)

    def test_a_catalog_record_on_the_duplicated_code_fails_closed(self):
        """The genuinely ambiguous case: which of the two is the catalog record?"""
        catalog = [catalog_record("NNH25ZDA001N-XRISM", "ROSES25: D.3C XRISM General Observer")]
        report = self._report(catalog)
        self.assertEqual(len(report["review"]), 2)
        self.assertEqual(report["actionable_unmatched"], [])
        self.assertEqual(report["matched"], [])
        self.assertEqual(report["unmatched"], [])
        for element in report["review"]:
            self.assertEqual(
                element["review_reason"], "ambiguous_code_matches_catalog_record"
            )
            self.assertEqual(element["matched_catalog_ids"], ["NNH25ZDA001N-XRISM"])

    def test_the_ambiguous_case_emits_nothing_through_parse(self):
        """End to end: fail closed means zero records, not a guess."""
        instance = NasaRosesAdapter()
        html = (FIXTURES / "table3.html").read_text(encoding="utf-8")
        instance.set_context({
            "catalog_records": CATALOG_ROSES + [
                catalog_record("NNH25ZDA001N-XRISM", "ROSES25: D.3C XRISM General Observer")
            ],
            "as_of": TODAY,
        })
        opportunities = list(instance.parse(payload(table3_html=html)))
        emitted_codes = {
            opportunity.title.split(":")[1].strip().split(" ")[0]
            for opportunity in opportunities
        }
        self.assertNotIn("D.3C", emitted_codes)
        self.assertEqual(len(instance.diagnostics["review"]), 2)

    def test_an_unrepeated_code_is_never_routed_to_review(self):
        single = [dict(self.TWINS[0], appendix_code="D.3Z")]
        report = NasaRosesAdapter().reconcile(
            single, catalog_records=[], year=2025, today=TODAY
        )
        self.assertEqual(report["ambiguous_source_codes"], [])
        self.assertEqual(report["review"], [])
        self.assertEqual(len(report["actionable_unmatched"]), 1)


class EmittedRecordShapeTests(unittest.TestCase):
    """P8.3: what an emitted record claims, and what it deliberately does not."""

    def setUp(self):
        self.instance, self.opportunities = reconciled()
        self.records = records_of(self.instance, self.opportunities)

    def test_the_title_follows_the_catalogs_existing_roses_convention(self):
        for record in self.records:
            self.assertRegex(record["title"], r"^ROSES\d{2}: [A-F]\.\d+[A-Z]? .+")

    def test_source_attribution_is_nasa_roses_not_grants_gov(self):
        for record in self.records:
            self.assertEqual(record["source"], "NASA ROSES")
            self.assertEqual(record["source_type"], "Federal")
            self.assertEqual(record["agency"], "NASA Headquarters")

    def test_the_official_url_is_nasas_own_element_page(self):
        for record in self.records:
            self.assertTrue(record["detail_page"].startswith("https://"))
            self.assertIn("nasaprs.com", record["detail_page"])

    def test_nasas_own_deadline_wording_is_preserved(self):
        notes = [record["close_date_note"] for record in self.records]
        self.assertTrue(any(note and "/" in note for note in notes))

    def test_a_solicitation_number_is_present_only_when_published(self):
        numbers = {record["opportunity_number"] for record in self.records}
        self.assertIn(None, numbers)                      # solId-only row
        self.assertTrue(any(n and n.startswith("NNH") for n in numbers))

    def test_every_emitted_record_has_a_future_close_date_or_is_rolling(self):
        for record in self.records:
            if record["close_date"]:
                self.assertGreaterEqual(date.fromisoformat(record["close_date"]), TODAY)


class MergePrecedenceTests(unittest.TestCase):
    """P8.3: Grants.gov owns what it already publishes. ROSES never overwrites."""

    def setUp(self):
        self.instance, self.opportunities = reconciled()
        self.external = records_of(self.instance, self.opportunities)

    def test_an_existing_catalog_record_is_not_duplicated(self):
        combined, stats = merge_records(CATALOG_ROSES, self.external)
        self.assertEqual(stats["base_count"], len(CATALOG_ROSES))
        self.assertEqual(stats["external_added"], len(self.external))
        titles = [record["title"] for record in combined]
        self.assertEqual(len(titles), len(set(titles)))

    def test_a_grants_gov_record_arriving_later_wins_on_the_number(self):
        """When Grants.gov starts carrying an element we already emitted, base wins."""
        emitted = [r for r in self.external if r["opportunity_number"]]
        self.assertTrue(emitted, "expected at least one emitted record with a number")
        rival = catalog_record(emitted[0]["opportunity_number"], "ROSES25: D.9 Some Title")
        combined, stats = merge_records([rival], self.external)
        # The number collides, so the external copy is dropped. Which counter
        # catches it is an implementation detail of merge_records: a shared
        # `opportunity_number` makes `record_identity` equal, so it is usually the
        # stronger identity test rather than the cross-source one.
        self.assertEqual(
            stats["dropped_duplicate_identity"]
            + stats["dropped_cross_source_duplicate"],
            1,
        )
        surviving = [
            r for r in combined
            if str(r.get("opportunity_number")) == rival["opportunity_number"]
        ]
        self.assertEqual(len(surviving), 1)
        self.assertEqual(surviving[0]["source"], "Grants.gov")

    def test_base_fields_are_never_overwritten_by_the_external_record(self):
        rival = catalog_record(
            "NNH25ZDA001N-HWOICA",
            "ROSES25: D.9 Habitable Worlds Observatory Instrument Concept Assessments",
            close_date="2027-01-15",
            detail_page="https://www.grants.gov/search-results-detail/999999",
        )
        combined, _stats = merge_records([rival], self.external)
        kept = [r for r in combined if r["opportunity_number"] == rival["opportunity_number"]]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["close_date"], "2027-01-15")
        self.assertEqual(kept[0]["detail_page"], rival["detail_page"])
        self.assertEqual(kept[0]["source"], "Grants.gov")

    def test_normalised_title_collision_also_drops_the_external_record(self):
        """The framework's pre-existing backstop, shown agreeing with P8's key."""
        rival = catalog_record(None, self.external[0]["title"])
        combined, stats = merge_records([rival], self.external)
        self.assertEqual(stats["dropped_cross_source_duplicate"], 1)
        self.assertEqual(len(combined), len(self.external))

    def test_merging_twice_does_not_create_a_second_identity(self):
        once, _ = merge_records(CATALOG_ROSES, self.external)
        twice, _ = merge_records(CATALOG_ROSES, self.external + self.external)
        self.assertEqual(len(once), len(twice))
        ids = [r["opportunity_id"] for r in twice]
        self.assertEqual(len(ids), len(set(ids)))


class InactiveInventoryStaysOutTests(unittest.TestCase):
    """P8.2's last clause: inventory cannot leak into catalog output."""

    def test_no_inactive_element_reaches_the_merged_catalog(self):
        instance, opportunities = reconciled()
        external = records_of(instance, opportunities)
        combined, _stats = merge_records(CATALOG_ROSES, external)
        inactive = instance.diagnostics["inactive_inventory"]
        self.assertGreaterEqual(len(inactive), 40)
        # Compare on the full ROSES title an emitted record would carry, not on a
        # substring: "Habitable Worlds" legitimately appears in both an inactive
        # element (D.10) and an emitted one (D.9), and a substring test would call
        # that a leak when the two are different program elements.
        merged_titles = {r["title"] for r in combined}
        for item in inactive:
            would_be = f"ROSES25: {item['appendix_code']} {item['title']}"
            self.assertNotIn(would_be, merged_titles)

    def test_inactive_inventory_is_visible_as_diagnostics(self):
        instance, _ = reconciled()
        inactive = instance.diagnostics["inactive_inventory"]
        self.assertTrue(all(set(item) >= {
            "appendix_code", "title", "native_status", "derived_currentness"
        } for item in inactive))
        self.assertNotIn(
            nasa_roses.DERIVED_OPEN,
            {item["derived_currentness"] for item in inactive},
        )


if __name__ == "__main__":
    unittest.main()
