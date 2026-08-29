import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.faculty_match import (
    DIRECTORY_GZIP_BUDGET,
    DIRECTORY_RAW_BUDGET,
    GRAPH_GZIP_BUDGET,
    GRAPH_RAW_BUDGET,
    MAX_FACULTY_PER_OPPORTUNITY,
    MAX_OPPORTUNITIES_PER_FACULTY,
    _faculty_idf,
    _generation_id,
    _load_js_object,
    _projection_fingerprint,
    generate_assets,
    score_profile_opportunity,
    validate_assets,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "hajim_faculty.json"
CATALOG = ROOT / "data" / "opportunities.js"
DIRECTORY = ROOT / "data" / "hajim_faculty_directory.js"
GRAPH = ROOT / "data" / "faculty_matches.js"
QUALITY = ROOT / "tests" / "fixtures" / "hajim_relevance_quality.json"


class FacultyMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.directory, _ = _load_js_object(DIRECTORY, "HAJIM_FACULTY_DIRECTORY")
        cls.graph, _ = _load_js_object(GRAPH, "FACULTY_MATCHES")

    def test_generated_assets_share_one_current_identity(self):
        validate_assets(self.directory, self.graph)
        self.assertEqual(self.directory["generation_id"], self.graph["generation_id"])
        self.assertEqual(self.directory["asset_version"], self.directory["generation_id"])
        self.assertEqual(self.directory["projection_fingerprints"], self.graph["projection_fingerprints"])
        self.assertEqual(self.directory["faculty_source"], self.graph["faculty_source"])
        self.assertEqual(self.directory["catalog"], self.graph["catalog"])
        self.assertEqual(self.directory["faculty_source"]["record_count"], 156)
        self.assertEqual(self.directory["faculty_source"]["rankable_record_count"], 145)
        self.assertEqual(self.directory["faculty_source"]["unlisted_interest_count"], 11)

    def test_identity_changes_with_either_projection_and_rejects_tampering(self):
        directory_fingerprint = _projection_fingerprint(self.directory)
        graph_fingerprint = _projection_fingerprint(self.graph)
        self.assertEqual(directory_fingerprint, self.directory["projection_fingerprints"]["directory"])
        self.assertEqual(graph_fingerprint, self.directory["projection_fingerprints"]["graph"])
        changed_graph = copy.deepcopy(self.graph)
        changed_graph["edges"][0]["score"] += 0.001
        changed_fingerprints = {
            "directory": directory_fingerprint,
            "graph": _projection_fingerprint(changed_graph),
        }
        changed_generation = _generation_id(
            self.directory["faculty_source"]["sha256"],
            self.directory["catalog"]["fingerprint"],
            changed_fingerprints,
        )
        self.assertNotEqual(changed_generation, self.directory["generation_id"])
        with self.assertRaisesRegex(ValueError, "fingerprints"):
            validate_assets(self.directory, changed_graph)

    def test_edges_are_normalized_bounded_and_exclude_unrankable_profiles(self):
        edges = self.graph["edges"]
        self.assertEqual(len(edges), len({(edge["faculty_id"], edge["opportunity_id"]) for edge in edges}))
        self.assertTrue(all(len(indexes) <= MAX_FACULTY_PER_OPPORTUNITY
                            for indexes in self.graph["by_opportunity"].values()))
        self.assertTrue(all(len(indexes) <= MAX_OPPORTUNITIES_PER_FACULTY
                            for indexes in self.graph["by_faculty"].values()))
        unrankable = {profile["faculty_id"] for profile in self.directory["profiles"] if not profile["rankable"]}
        self.assertFalse(unrankable & set(self.graph["by_faculty"]))
        self.assertEqual(
            sorted(index for values in self.graph["by_opportunity"].values() for index in values),
            list(range(len(edges))),
        )

    def test_generic_or_theme_only_overlap_cannot_admit(self):
        profile = {
            "faculty_id": "generic",
            "rankable": True,
            "research_interests_text": "materials; energy; research systems",
            "research_phrases": ["materials", "energy", "research systems"],
            "derived_themes": ["Materials / Polymers / Nanoscience"],
        }
        opportunity = {
            "opportunity_id": "generic-opportunity",
            "title": "Materials and energy research systems",
            "description": "A broad program for materials, energy, data, and health.",
            "topic_areas": ["Materials / Polymers / Nanoscience"],
        }
        self.assertIsNone(score_profile_opportunity(profile, opportunity, {}))

    def test_multiconcept_phrase_admits_with_local_evidence(self):
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        record = {
            "opportunity_id": "catalysis-fixture",
            "title": "CO2 capture and conversion",
            "description": "Heterogeneous thermal catalysis for reactive separations.",
        }
        edge = score_profile_opportunity(by_id["marc-d-porosoff"], record, idf)
        self.assertIsNotNone(edge)
        self.assertIn("CO2 capture and conversion", edge["matched_profile_phrases"])
        self.assertTrue(edge["opportunity_evidence"])

    def test_human_reviewed_multidisciplinary_quality_fixture(self):
        fixture = json.loads(QUALITY.read_text(encoding="utf-8"))
        profiles = self.config["profiles"]
        by_id = {profile["faculty_id"]: profile for profile in profiles}
        idf = _faculty_idf(profiles)
        self.assertGreaterEqual(len({case["discipline"] for case in fixture["cases"]}), 8)
        failures = []
        for case in fixture["cases"]:
            scores = {
                faculty_id: score_profile_opportunity(by_id[faculty_id], case["opportunity"], idf)
                for faculty_id in case["expected_profile_ids"] + case["irrelevant_near_neighbors"]
            }
            for faculty_id in case["expected_profile_ids"]:
                if scores[faculty_id] is None:
                    failures.append(f"{case['id']}: expected {faculty_id} was not admitted")
            expected_scores = [scores[item]["score"] for item in case["expected_profile_ids"] if scores[item]]
            for faculty_id in case["irrelevant_near_neighbors"]:
                irrelevant = scores[faculty_id]
                if irrelevant and (not expected_scores or irrelevant["score"] >= max(expected_scores)):
                    failures.append(f"{case['id']}: near-neighbor {faculty_id} outranked expected profile")
        self.assertEqual(failures, [])

    def test_assets_stay_within_explicit_raw_and_gzip_budgets(self):
        directory_bytes = DIRECTORY.read_bytes()
        graph_bytes = GRAPH.read_bytes()
        self.assertLessEqual(len(directory_bytes), DIRECTORY_RAW_BUDGET)
        self.assertLessEqual(len(gzip.compress(directory_bytes, mtime=0)), DIRECTORY_GZIP_BUDGET)
        self.assertLessEqual(len(graph_bytes), GRAPH_RAW_BUDGET)
        self.assertLessEqual(len(gzip.compress(graph_bytes, mtime=0)), GRAPH_GZIP_BUDGET)

    def test_repeated_generation_is_byte_for_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first_directory = Path(directory) / "first-directory.js"
            first_graph = Path(directory) / "first-graph.js"
            second_directory = Path(directory) / "second-directory.js"
            second_graph = Path(directory) / "second-graph.js"
            generate_assets(CONFIG, CATALOG, first_directory, first_graph)
            generate_assets(CONFIG, CATALOG, second_directory, second_graph)
            self.assertEqual(first_directory.read_bytes(), second_directory.read_bytes())
            self.assertEqual(first_graph.read_bytes(), second_graph.read_bytes())

    def test_generation_updates_page_markers_and_team_directory_version_together(self):
        old_generation = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finder = root / "match_explorer.html"
            team = root / "team_match.html"
            finder.write_text(
                f'<meta name="hajim-match-generation" content="{old_generation}" />\n',
                encoding="utf-8",
            )
            team.write_text(
                f'<meta name="hajim-match-generation" content="{old_generation}" />\n'
                f'<script src="data/hajim_faculty_directory.js?v={old_generation}"></script>\n',
                encoding="utf-8",
            )
            directory_out = root / "directory.js"
            graph_out = root / "graph.js"
            generated_directory, _ = generate_assets(
                CONFIG, CATALOG, directory_out, graph_out, (finder, team),
            )
            generation = generated_directory["generation_id"]
            self.assertNotEqual(generation, old_generation)
            self.assertIn(f'content="{generation}"', finder.read_text(encoding="utf-8"))
            team_text = team.read_text(encoding="utf-8")
            self.assertIn(f'content="{generation}"', team_text)
            self.assertIn(f'data/hajim_faculty_directory.js?v={generation}', team_text)

    def test_nightly_refresh_uses_canonical_config_and_atomic_outputs(self):
        workflow = (ROOT / ".github" / "workflows" / "refresh-opportunities.yml").read_text(encoding="utf-8")
        self.assertIn("python -m scripts.faculty_match match", workflow)
        self.assertIn("--faculty-config config/hajim_faculty.json", workflow)
        self.assertIn("--directory-out data/hajim_faculty_directory.js", workflow)
        self.assertIn("--version-target match_explorer.html", workflow)
        self.assertIn("--version-target team_match.html", workflow)
        self.assertIn("data/hajim_faculty_directory.js?v=${faculty_generation}", workflow)
        self.assertIn("data/faculty_matches.js?v=${faculty_generation}", workflow)
        self.assertNotIn("--profiles faculty_profiles.json", workflow)
        self.assertLess(
            workflow.index("- name: Rotate through official links and record health and redirects"),
            workflow.index("- name: Rebuild Hajim faculty directory and match graph atomically"),
        )


if __name__ == "__main__":
    unittest.main()
