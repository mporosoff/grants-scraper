from pathlib import Path
import unittest

from scripts.update_catalog_docs import (
    REPOSITORY_ROOT,
    catalog_stats,
    load_catalog,
    render_docs,
)


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
        readme = readme_path.read_text(encoding="utf-8")
        project = project_path.read_text(encoding="utf-8")
        stats = catalog_stats(
            load_catalog(REPOSITORY_ROOT / "data" / "opportunities.js")
        )

        self.assertEqual(render_docs(readme, project, stats), (readme, project))

    def test_generator_requires_unique_marker_pairs(self):
        stats = catalog_stats(
            load_catalog(REPOSITORY_ROOT / "data" / "opportunities.js")
        )
        with self.assertRaisesRegex(ValueError, "marker pair"):
            render_docs("README without markers", "PROJECT without markers", stats)


if __name__ == "__main__":
    unittest.main()
