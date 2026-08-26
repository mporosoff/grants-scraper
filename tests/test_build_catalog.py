from datetime import date, datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from scripts.build_catalog import (
    build_catalog,
    catalog_asset_version,
    catalog_metadata,
    catalog_metadata_javascript_bytes,
    catalog_release_identity,
    clean_text,
    compact_catalog_payload,
    discover_latest_extract,
    is_current,
    iter_catalog_records,
    normalize_disciplines,
    read_archive,
    safe_http_url,
    tokenize,
    topic_areas,
    write_catalog,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "grants_db_extract.xml"
)


class CatalogExtractTests(unittest.TestCase):
    def test_catalog_asset_version_preserves_same_second_precision(self):
        first = {"generated_at": "2026-08-26T12:00:00.123455Z"}
        second = {"generated_at": "2026-08-26T12:00:00.123456Z"}

        self.assertEqual(
            catalog_asset_version(first),
            "catalog-20260826T120000123455Z",
        )
        self.assertEqual(
            catalog_asset_version(second),
            "catalog-20260826T120000123456Z",
        )
        self.assertNotEqual(
            catalog_asset_version(first),
            catalog_asset_version(second),
        )

    def test_compacts_only_deadline_evidence_duplicated_in_the_same_record(self):
        citation = {
            "document_url": "https://example.org/notice.pdf",
            "quote": "Applications are due September 30, 2026.",
        }
        distinct_citation = {
            "document_url": "https://example.org/other.pdf",
            "quote": "A separate source quote.",
        }
        catalog = {
            "opportunities": [{
                "document_evidence": {
                    "facts": [{"id": "evidence-1", "citation": citation}]
                },
                "deadlines": [
                    {
                        "evidence_id": "evidence-1",
                        "note": citation["quote"],
                        "citation": citation,
                    },
                    {
                        "note": "Keep this distinct note.",
                        "citation": distinct_citation,
                    },
                ],
            }],
        }

        compacted = compact_catalog_payload(catalog)

        self.assertNotIn("note", compacted["opportunities"][0]["deadlines"][0])
        self.assertNotIn("citation", compacted["opportunities"][0]["deadlines"][0])
        self.assertEqual(
            compacted["opportunities"][0]["deadlines"][1]["note"],
            "Keep this distinct note.",
        )
        self.assertEqual(
            compacted["opportunities"][0]["deadlines"][1]["citation"],
            distinct_citation,
        )
        self.assertIn("citation", catalog["opportunities"][0]["deadlines"][0])

    def test_free_form_disciplines_are_mapped_to_controlled_values(self):
        raw = (
            "chemistry, computer science, earth systems science, economics, "
            "mathematics, neuroscience, physics, or a related field"
        )

        self.assertEqual(
            normalize_disciplines([raw]),
            [
                "Engineering and Physical Sciences",
                "Environmental and Life Sciences",
                "Medical and Health",
                "Business and Economic Development",
            ],
        )

    def test_streams_current_posted_and_forecast_records(self):
        with FIXTURE.open("rb") as xml_stream:
            records = list(
                iter_catalog_records(xml_stream, date(2026, 7, 25))
            )

        self.assertEqual(len(records), 3)
        self.assertEqual(
            {record["status"] for record in records},
            {"posted", "forecasted"},
        )
        posted = next(
            record for record in records if record["status"] == "posted"
        )
        self.assertEqual(posted["award_ceiling"], 1_000_000)
        self.assertEqual(posted["award_source"], "Grants.gov XML extract")
        self.assertEqual(posted["deadlines"][0]["kind"], "application")
        self.assertEqual(
            posted["deadlines"][0]["confidence"],
            "official_structured",
        )
        self.assertEqual(posted["detail_enrichment_status"], "pending")
        self.assertIn(
            "Public and state institutions of higher education",
            posted["applicant_types"],
        )
        self.assertIn("Carbon management", posted["topic_areas"])
        self.assertIn(
            "Engineering and Physical Sciences", posted["disciplines"]
        )
        undated = next(
            record
            for record in records
            if record["opportunity_number"] == "OPEN-UNDATED-1"
        )
        self.assertTrue(undated["status_verification_required"])

    def test_ordinary_rolling_language_does_not_reopen_expired_notice(self):
        values = {
            "CloseDate": ["11132009"],
            "Description": [
                "The project uses a rolling assessment of changing needs."
            ],
        }

        self.assertFalse(is_current(values, "posted", date(2026, 7, 25)))

    def test_explicit_close_date_controls_rolling_application_notice(self):
        values = {
            "CloseDate": ["05312021"],
            "Description": [
                "Applications are reviewed on a rolling basis."
            ],
        }

        self.assertFalse(is_current(values, "posted", date(2026, 7, 25)))

    def test_expired_forecast_deadline_is_not_current(self):
        values = {
            "EstimatedSynopsisCloseDate": ["12052019"],
            "LastUpdatedDate": ["12022019"],
            "FiscalYear": ["2020"],
        }

        self.assertFalse(is_current(values, "forecasted", date(2026, 7, 25)))

    def test_undated_forecast_from_old_fiscal_year_is_not_current(self):
        values = {
            "LastUpdatedDate": ["07112025"],
            "FiscalYear": ["2025"],
        }

        self.assertFalse(is_current(values, "forecasted", date(2026, 7, 25)))

    def test_recent_undated_forecast_for_current_year_is_current(self):
        values = {
            "LastUpdatedDate": ["07202026"],
            "FiscalYear": ["2026"],
        }

        self.assertTrue(is_current(values, "forecasted", date(2026, 7, 25)))

    def test_informational_notice_with_placeholder_date_is_not_current(self):
        values = {
            "OpportunityTitle": [
                "DE-FOA-123 Notice of Intent to Issue a Funding Opportunity"
            ],
            "CloseDate": ["12312099"],
            "FundingInstrumentType": ["O"],
        }

        self.assertFalse(is_current(values, "posted", date(2026, 7, 25)))

    def test_far_future_lifecycle_sentinel_is_not_an_application_deadline(self):
        xml = b"""<Grants><OpportunitySynopsisDetail_1_0>
          <OpportunityID>9001</OpportunityID>
          <OpportunityNumber>PD-26-366Y</OpportunityNumber>
          <OpportunityTitle>Transport Phenomena</OpportunityTitle>
          <CloseDate>08202076</CloseDate>
          <Description>Proposals are accepted anytime.</Description>
        </OpportunitySynopsisDetail_1_0></Grants>"""

        records = list(iter_catalog_records(BytesIO(xml), date(2026, 8, 23)))

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["close_date"])
        self.assertEqual(records[0]["deadlines"], [])
        self.assertTrue(records[0]["rolling"])

    def test_noi_abbreviation_and_explicit_test_records_are_not_current(self):
        self.assertFalse(is_current({
            "OpportunityTitle": ["NOI: Future research program"],
            "CloseDate": ["12312029"],
        }, "posted", date(2026, 7, 25)))
        self.assertFalse(is_current({
            "OpportunityTitle": ["DEMO-123"],
            "AgencyName": ["IV&V Test Agency"],
            "Description": ["This is a test NOFO. Do not apply."],
            "CloseDate": ["12312029"],
        }, "posted", date(2026, 7, 25)))

    def test_reads_zip_and_builds_searchable_catalog(self):
        with TemporaryDirectory() as directory:
            archive_path = Path(directory) / "extract.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.write(FIXTURE, arcname="fixture.xml")

            records, deduplicated = read_archive(
                archive_path, date(2026, 7, 25)
            )
            catalog = build_catalog(
                records,
                datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
                archive_path.name,
                deduplicated,
            )
            output = Path(directory) / "opportunities.js"
            write_catalog(catalog, output)
            javascript = output.read_text(encoding="utf-8")
            metadata_javascript = output.with_name(
                "catalog-metadata.js"
            ).read_text(encoding="utf-8")

        self.assertEqual(catalog["record_count"], 3)
        self.assertEqual(catalog["status_counts"]["posted"], 2)
        self.assertIn("carbon", catalog["search_index"]["postings"])
        self.assertIn("membrane", catalog["search_index"]["postings"])
        prefix = "globalThis.GRANT_CATALOG="
        payload = javascript.split(prefix, 1)[1].strip().removesuffix(";")
        self.assertEqual(json.loads(payload)["schema_version"], 3)
        self.assertEqual(
            catalog["diagnostics"]["quality"]["per_award_amount_count"],
            1,
        )
        metadata_prefix = "globalThis.GRANT_CATALOG_METADATA="
        metadata_payload = metadata_javascript.split(
            metadata_prefix, 1
        )[1].strip().removesuffix(";")
        metadata = json.loads(metadata_payload)
        self.assertEqual(metadata, catalog_metadata(catalog))
        self.assertEqual(
            metadata["release_identity"], catalog_release_identity(catalog)
        )
        self.assertEqual(
            metadata_javascript.encode("utf-8"),
            catalog_metadata_javascript_bytes(catalog),
        )
        self.assertLess(len(metadata_javascript.encode("utf-8")), 2_048)

    def test_discovers_newest_enhanced_extract(self):
        html = """
        <a href="https://example.test/GrantsDBExtract20260723v2.zip">old</a>
        <a href="/extracts/GrantsDBExtract20260725v2.zip">new</a>
        """

        url = discover_latest_extract(html, "https://grants.gov/xml-extract")

        self.assertEqual(
            url,
            "https://grants.gov/extracts/GrantsDBExtract20260725v2.zip",
        )


class TokenTests(unittest.TestCase):
    def test_repairs_flattened_description_boundaries(self):
        self.assertEqual(
            clean_text("Partner.Projects follow.ObjectivesEach project applies."),
            "Partner. Projects follow. Objectives: Each project applies.",
        )

    def test_tokenizer_removes_noise_and_normalizes_simple_inflections(self):
        self.assertEqual(
            tokenize("Catalytic materials and batteries for applications"),
            ["catalytic", "material", "battery"],
        )

    def test_tokenizer_normalizes_scientific_subscripts(self):
        self.assertEqual(tokenize("CO₂ H₂ PM₂.₅"), ["co2", "h2", "pm2.5"])

    def test_source_urls_must_be_absolute_http_urls(self):
        self.assertIsNone(safe_http_url("N/A"))
        self.assertIsNone(safe_http_url("/relative/path"))
        self.assertEqual(
            safe_http_url("www.nsf.gov/funding"),
            "https://www.nsf.gov/funding",
        )
        self.assertEqual(
            safe_http_url("http://grants.nih.gov/example"),
            "https://grants.nih.gov/example",
        )

    def test_catalysis_topic_does_not_match_the_ordinary_verb_catalyze(self):
        self.assertNotIn(
            "Catalysis and reaction engineering",
            topic_areas(
                "Community innovation",
                "The program will catalyze partnerships and use catalytic "
                "capital as a catalyst for economic growth.",
                [],
            ),
        )
        self.assertIn(
            "Catalysis and reaction engineering",
            topic_areas(
                "Heterogeneous catalysis",
                "Develop catalytic reactor systems.",
                [],
            ),
        )

    def test_artificial_intelligence_is_not_tagged_as_arts(self):
        self.assertNotIn(
            "Arts and culture",
            topic_areas(
                "Artificial intelligence for scientific discovery",
                "Develop reliable AI systems and machine learning methods.",
                [],
            ),
        )
        self.assertIn(
            "Arts and culture",
            topic_areas(
                "Community arts program",
                "Support museums, music, and cultural organizations.",
                [],
            ),
        )


if __name__ == "__main__":
    unittest.main()
