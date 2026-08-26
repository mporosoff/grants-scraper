from pathlib import Path
import unittest

from scripts.update_catalog_docs import (
    REPOSITORY_ROOT,
    catalog_stats,
    load_catalog,
    render_docs,
    update_catalog_asset_reference,
)
from scripts.build_catalog import catalog_metadata_javascript_bytes


class CatalogDocumentationTests(unittest.TestCase):
    def test_generated_statistics_cover_each_primary_route(self):
        stats = catalog_stats(
            load_catalog(REPOSITORY_ROOT / "data" / "opportunities.js")
        )

        self.assertEqual(
            stats["direct"] + stats["agency_route"] + stats["grants_route"],
            stats["record_count"],
        )
        self.assertGreaterEqual(stats["agency_url_total"], stats["agency_route"])
        self.assertEqual(stats["past_deadlines"], 0)
        self.assertEqual(sum(stats["source_counts"].values()), stats["record_count"])
        self.assertEqual(
            stats["non_grants_count"],
            stats["record_count"] - stats["source_counts"].get("Grants.gov", 0),
        )

    def test_committed_documentation_matches_generated_catalog(self):
        readme_path = REPOSITORY_ROOT / "README.md"
        project_path = REPOSITORY_ROOT / "PROJECT.md"
        explorer_path = REPOSITORY_ROOT / "match_explorer.html"
        team_path = REPOSITORY_ROOT / "team_match.html"
        metadata_path = REPOSITORY_ROOT / "data" / "catalog-metadata.js"
        readme = readme_path.read_text(encoding="utf-8")
        project = project_path.read_text(encoding="utf-8")
        explorer = explorer_path.read_text(encoding="utf-8")
        team = team_path.read_text(encoding="utf-8")
        catalog = load_catalog(REPOSITORY_ROOT / "data" / "opportunities.js")
        stats = catalog_stats(catalog)

        self.assertEqual(render_docs(readme, project, stats), (readme, project))
        self.assertEqual(
            update_catalog_asset_reference(explorer, catalog),
            explorer,
        )
        self.assertEqual(update_catalog_asset_reference(team, catalog), team)
        self.assertEqual(
            metadata_path.read_bytes(),
            catalog_metadata_javascript_bytes(catalog),
        )

    def test_generator_requires_unique_marker_pairs(self):
        stats = catalog_stats(
            load_catalog(REPOSITORY_ROOT / "data" / "opportunities.js")
        )
        with self.assertRaisesRegex(ValueError, "marker pair"):
            render_docs("README without markers", "PROJECT without markers", stats)

    def test_catalog_asset_reference_uses_latest_pipeline_timestamp(self):
        html = '<script src="./data/opportunities.js"></script>'
        catalog = {
            "generated_at": "2026-07-27T12:00:00Z",
            "document_evidence_generated_at": "2026-07-27T12:05:06.123456Z",
            "detail_enrichment_generated_at": "2026-07-27T12:03:00",
        }
        self.assertEqual(
            update_catalog_asset_reference(html, catalog),
            '<script src="./data/opportunities.js?v='
            'catalog-20260727T120506123456Z"></script>',
        )
        metadata_html = '<script src="./data/catalog-metadata.js"></script>'
        self.assertEqual(
            update_catalog_asset_reference(metadata_html, catalog),
            '<script src="./data/catalog-metadata.js?v='
            'catalog-20260727T120506123456Z"></script>',
        )


if __name__ == "__main__":
    unittest.main()
