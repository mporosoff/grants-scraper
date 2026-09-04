import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.faculty_match import (
    AGENCY_SCOPE,
    BRIDGE_THEMES,
    THEME_LEXICON,
    match_to_catalog,
    update_version_target,
)
from scripts.researcher_registry import load_registry, matching_profiles


class FacultyMatchRelevanceTests(unittest.TestCase):
    def _match(self, opportunities):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "catalog.js"
            output_path = Path(temp_dir) / "matches.js"
            catalog_path.write_text(
                "globalThis.GRANT_CATALOG="
                + json.dumps({"opportunities": opportunities})
                + ";\n",
                encoding="utf-8",
            )
            registry = load_registry()
            return match_to_catalog(
                matching_profiles(registry), str(catalog_path), str(output_path),
                registry_generation=registry["registry_generation"],
            )

    def test_broad_catalog_topics_cannot_create_a_research_match(self):
        result = self._match([{
            "opportunity_id": "egypt",
            "title": "Egypt Annual Program Statement",
            "description": (
                "Commercial diplomacy, infrastructure, trade facilitation, workforce "
                "training, critical minerals, and energy exports in Egypt."
            ),
            "topic_areas": [
                "Materials science", "Energy", "Manufacturing",
                "Artificial intelligence and machine learning",
            ],
            "posted_date": "2026-07-20",
        }])

        self.assertEqual(result["multi_pi_suggestions"], [])
        self.assertTrue(all(not matches for matches in result["pi_matches"].values()))

    def test_relevance_and_recency_are_both_reflected_in_ranking(self):
        result = self._match([
            {
                "opportunity_id": "older-strong",
                "title": "Integrated carbon conversion catalysts",
                "description": (
                    "Heterogeneous thermal catalysis and carbon dioxide capture and "
                    "conversion are both central to this research call."
                ),
                "topic_areas": ["Carbon management", "Catalysis and reaction engineering"],
                "posted_date": "2026-02-01",
            },
            {
                "opportunity_id": "newer-focused",
                "title": "Catalyst research opportunity",
                "description": "Research on heterogeneous thermal catalysis.",
                "topic_areas": ["Catalysis and reaction engineering"],
                "posted_date": "2026-08-09",
            },
            {
                "opportunity_id": "old-focused",
                "title": "Earlier catalyst research opportunity",
                "description": "Research on heterogeneous thermal catalysis.",
                "topic_areas": ["Catalysis and reaction engineering"],
                "posted_date": "2025-12-01",
            },
        ])

        porosoff = result["pi_matches"]["Marc D. Porosoff"]
        self.assertEqual(
            [match["id"] for match in porosoff[:3]],
            ["older-strong", "newer-focused", "old-focused"],
        )
        self.assertGreater(porosoff[0]["relevance_score"], porosoff[1]["relevance_score"])
        self.assertGreater(porosoff[1]["recency_score"], porosoff[2]["recency_score"])

    def test_archived_programs_do_not_enter_current_team_matches(self):
        result = self._match([
            {
                "opportunity_id": "archived-catalysis",
                "title": "Archived Catalysis Program",
                "description": "Heterogeneous thermal catalysis research.",
                "topic_areas": ["Catalysis and reaction engineering"],
                "posted_date": "2026-04-01",
                "status": "archived",
            },
            {
                "opportunity_id": "current-catalysis",
                "title": "Current Catalysis Research",
                "description": "Heterogeneous thermal catalysis research.",
                "topic_areas": ["Catalysis and reaction engineering"],
                "posted_date": "2026-04-02",
                "status": "posted",
            },
        ])

        ids = {
            match["id"]
            for matches in result["pi_matches"].values()
            for match in matches
        }
        self.assertIn("current-catalysis", ids)
        self.assertNotIn("archived-catalysis", ids)

    def test_profiles_publish_summaries_and_focused_concepts(self):
        result = self._match([])
        generic = {"energy", "materials", "material science", "materials science"}

        for metadata in result["faculty"].values():
            self.assertGreater(len(metadata["research_summary"]), 40)
            self.assertGreaterEqual(len(metadata["key_terms"]), 5)
            self.assertLessEqual(len(metadata["key_terms"]), 10)
            self.assertFalse(generic & {term.lower() for term in metadata["key_terms"]})

    def test_live_matcher_configuration_is_published_with_generated_metadata(self):
        result = self._match([])

        self.assertEqual(result["theme_lexicon"], THEME_LEXICON)
        self.assertEqual(result["bridge_themes"], BRIDGE_THEMES)
        self.assertEqual(result["agency_scope"], AGENCY_SCOPE)
        self.assertIn("broad agency announcement", result["broad_pattern"])
        self.assertTrue(all(item["pattern"] and item["domains"] for item in AGENCY_SCOPE))

    def test_nightly_refresh_rebuilds_team_matcher_metadata(self):
        workflow = Path(".github/workflows/refresh-opportunities.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("python -m scripts.faculty_match", workflow)
        self.assertIn("--registry config/researcher_registry.json", workflow)
        self.assertIn("--catalog data/opportunities.js", workflow)
        self.assertIn("--out data/faculty_matches.js", workflow)
        self.assertIn("--version-target team_match.html", workflow)

    def test_version_target_tracks_exact_generated_match_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matches_path = root / "data" / "faculty_matches.js"
            matches_path.parent.mkdir()
            matches_path.write_bytes(b"globalThis.FACULTY_MATCHES={};\n")
            page_path = root / "team_match.html"
            page_path.write_text(
                '<script src="data/faculty_matches.js?v=stale"></script>\r\n',
                encoding="utf-8",
                newline="",
            )

            digest = update_version_target(page_path, matches_path)

            expected = hashlib.sha256(matches_path.read_bytes()).hexdigest()
            self.assertEqual(digest, expected)
            self.assertIn(f"data/faculty_matches.js?v={expected}", page_path.read_text(encoding="utf-8"))
            self.assertNotIn(b"\r\n", page_path.read_bytes())

    def test_version_target_requires_one_exact_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matches_path = root / "matches.js"
            matches_path.write_text("matches", encoding="utf-8")
            for name, source in {
                "missing": "<html></html>\n",
                "duplicate": (
                    '<script src="data/faculty_matches.js?v=one"></script>\n'
                    '<script src="./data/faculty_matches.js?v=two"></script>\n'
                ),
            }.items():
                with self.subTest(name=name):
                    page_path = root / f"{name}.html"
                    page_path.write_text(source, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Expected one faculty-matches version reference"):
                        update_version_target(page_path, matches_path)

    def test_generated_javascript_uses_platform_independent_line_endings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "catalog.js"
            output_path = Path(temp_dir) / "matches.js"
            catalog_path.write_text(
                "globalThis.GRANT_CATALOG={\"opportunities\":[]};\n",
                encoding="utf-8",
                newline="\n",
            )
            registry = load_registry()
            match_to_catalog(
                matching_profiles(registry), str(catalog_path), str(output_path),
                registry_generation=registry["registry_generation"],
            )
            self.assertNotIn(b"\r\n", output_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
