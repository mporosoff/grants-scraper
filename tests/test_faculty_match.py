import json
import tempfile
import unittest
from pathlib import Path

from scripts.faculty_match import match_to_catalog


class FacultyMatchDateRankingTests(unittest.TestCase):
    def test_generated_matches_and_groups_are_newest_first(self):
        opportunities = []
        for oid, title, listing_date in (
            ("older", "Older materials opportunity", "2026-02-01"),
            ("newer", "Newer materials opportunity", "2026-08-09"),
        ):
            opportunities.append({
                "opportunity_id": oid,
                "title": title,
                "description": "Functional materials and polymer coatings.",
                "topic_areas": ["Materials science"],
                "disciplines": ["Engineering"],
                "source_first_seen_date": listing_date,
                "detail_page": f"https://example.test/{oid}",
            })

        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "catalog.js"
            output_path = Path(temp_dir) / "matches.js"
            catalog_path.write_text(
                "globalThis.GRANT_CATALOG=" + json.dumps({"opportunities": opportunities}) + ";\n",
                encoding="utf-8",
            )
            result = match_to_catalog([], str(catalog_path), str(output_path))

        self.assertGreater(len(result["multi_pi_suggestions"]), 1)
        self.assertEqual(
            [group["opportunity_id"] for group in result["multi_pi_suggestions"][:2]],
            ["newer", "older"],
        )
        self.assertEqual(result["multi_pi_suggestions"][0]["listing_date"], "2026-08-09")
        yates_matches = result["pi_matches"]["Matthew Z. Yates"]
        self.assertEqual([match["id"] for match in yates_matches[:2]], ["newer", "older"])


if __name__ == "__main__":
    unittest.main()
