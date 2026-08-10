import json
import tempfile
import unittest
from pathlib import Path

from scripts.faculty_match import match_to_catalog


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
            return match_to_catalog([], str(catalog_path), str(output_path))

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

    def test_profiles_publish_summaries_and_focused_concepts(self):
        result = self._match([])
        generic = {"energy", "materials", "material science", "materials science"}

        for metadata in result["faculty"].values():
            self.assertGreater(len(metadata["research_summary"]), 40)
            self.assertGreaterEqual(len(metadata["key_terms"]), 5)
            self.assertLessEqual(len(metadata["key_terms"]), 10)
            self.assertFalse(generic & {term.lower() for term in metadata["key_terms"]})


if __name__ == "__main__":
    unittest.main()
