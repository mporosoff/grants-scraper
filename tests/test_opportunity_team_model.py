from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.import_opportunity_team_model import (
    CONTENT_HASHED_ASSETS,
    MAX_BROWSER_BYTES,
    MAX_INDEX_BYTES,
    _canonical_bytes,
    _generated_javascript,
    availability_projection,
    browser_projection,
    update_version_target,
    write_outputs,
)
from scripts.researcher_registry import legacy_faculty_projection, load_registry, registry_counts


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "opportunity_team_model.json"
BROWSER_PATH = ROOT / "data" / "opportunity_teams.js"
INDEX_PATH = ROOT / "data" / "opportunity_team_index.js"
GENERATION_MARKER = 'meta name="opportunity-team-generation" content="{generation}"'


class OpportunityTeamModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.registry = load_registry(ROOT / "config" / "researcher_registry.json")
        cls.browser_bytes = BROWSER_PATH.read_bytes()
        cls.index_bytes = INDEX_PATH.read_bytes()

    def test_generation_is_content_derived_and_browser_projection_is_exact(self):
        payload = copy.deepcopy(self.config)
        generation = payload.pop("generation_id")
        self.assertEqual(hashlib.sha256(_canonical_bytes(payload)).hexdigest(), generation)
        expected = _generated_javascript(
            "OPPORTUNITY_TEAM_DATA",
            browser_projection(self.config),
        )
        self.assertEqual(self.browser_bytes, expected)
        self.assertEqual(
            self.index_bytes,
            _generated_javascript(
                "OPPORTUNITY_TEAM_INDEX",
                availability_projection(self.config),
            ),
        )
        for path in (CONFIG_PATH, BROWSER_PATH, INDEX_PATH, ROOT / "match_explorer.html", ROOT / "team_match.html"):
            self.assertNotIn(b"\r\n", path.read_bytes(), f"{path.name} must be platform-stable LF")

    def test_roster_and_pool_contracts_are_generated_from_the_registry(self):
        counts = registry_counts(self.registry)
        self.assertEqual(self.config["source_roster_counts"], {
            key: counts[key] for key in ("total", "rankable", "unrankable")
        })
        self.assertEqual(self.config["pool_counts"], counts["pool_counts"])
        self.assertEqual(
            self.config["researcher_registry_generation"],
            self.registry["registry_generation"],
        )
        self.assertEqual(self.config["faculty"], legacy_faculty_projection(self.registry))
        self.assertEqual(len(self.config["faculty"]), counts["total"])
        states = {state: 0 for state in ("main", "standby", "unadmitted")}
        for profile in self.config["faculty"]:
            states[profile["pool_state"]] += 1
            self.assertTrue(profile["source_urls"])
            self.assertRegex(profile["source_checked_date"], r"^\d{4}-\d{2}-\d{2}$")
            if profile["pool_state"] == "main":
                self.assertGreaterEqual(len(profile["terms"]), 2)
            if profile["pool_state"] == "standby":
                self.assertEqual(len(profile["terms"]), 1)
        self.assertEqual(states, self.config["pool_counts"])

    def test_oversized_projection_fails_before_overwriting_any_output(self):
        oversized = copy.deepcopy(self.config)
        oversized["opportunities"][0]["objective"] = "x" * MAX_BROWSER_BYTES
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("config.json", "teams.js", "index.js")]
            for path in paths:
                path.write_text("previous valid artifact", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds"):
                write_outputs(oversized, *paths)
            self.assertTrue(all(path.read_text(encoding="utf-8") == "previous valid artifact" for path in paths))

    def test_ten_specific_scopes_preserve_explanations_and_honest_gaps(self):
        opportunities = [row for row in self.config["opportunities"] if not row.get("generator_version")]
        self.assertEqual(len(opportunities), 10)
        states = {"pass": 0, "conditional": 0, "fail": 0}
        allowed_types = {"specific_parent", "publishable_child", "declared_branch"}
        for opportunity in opportunities:
            states[opportunity["gate_state"]] += 1
            self.assertIn(opportunity["record_type"], allowed_types)
            self.assertNotIn("broad", opportunity["record_type"])
            self.assertIn(len(opportunity["members"]), {3, 4})
            self.assertEqual(len(opportunity["roles"]), 4)
            self.assertTrue(opportunity["why_team"])
            self.assertTrue(opportunity["source_url"].startswith("http"))
            for member in opportunity["members"]:
                self.assertTrue(member["why_person"])
                self.assertTrue(member["evidence_phrase"])
                self.assertTrue(member["source_url"].startswith("http"))
            for role in opportunity["roles"]:
                self.assertIn(role["coverage"], {
                    "direct", "method_transfer", "adjacent", "direct_and_adjacent", "gap",
                })
                self.assertTrue(role["rationale"])
                self.assertTrue(role["source_url"].startswith("http"))
                self.assertTrue(set(role["candidate_ids"]).isdisjoint(role["alternative_ids"]))
        self.assertEqual(states, {"pass": 2, "conditional": 7, "fail": 1})
        self.assertEqual(
            sum(opportunity["record_type"] == "publishable_child" for opportunity in opportunities),
            3,
        )
        self.assertTrue(any(opportunity["missing_skills"] for opportunity in opportunities))

    def test_html_and_runtime_references_share_the_generated_identity(self):
        generation = self.config["generation_id"]
        for name in ("match_explorer.html", "team_match.html"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(GENERATION_MARKER.format(generation=generation), source)
            code_hash = hashlib.sha256((ROOT / "assets/opportunity-team.js").read_bytes()).hexdigest()
            self.assertIn(f"assets/opportunity-team.js?v={code_hash}", source)
            self.assertIn(f"data/opportunity_team_index.js?v={generation}", source)
            self.assertNotIn("hajim-pr1", source)
        page = (ROOT / "match_explorer.html").read_text(encoding="utf-8")
        for path in ("assets/search-retrieval.js",):
            self.assertIn(f'{path}?v={hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}', page)
        panel_hash = hashlib.sha256((ROOT / "assets/opportunity-team-panel.js").read_bytes()).hexdigest()
        self.assertIn(f"assets/opportunity-team-panel.js?v={panel_hash}", page)
        app_css_hash = hashlib.sha256((ROOT / "assets" / "app.css").read_bytes()).hexdigest()
        app_js_hash = hashlib.sha256((ROOT / "assets" / "app.js").read_bytes()).hexdigest()
        self.assertIn(f"assets/app.css?v={app_css_hash}", page)
        self.assertIn(f"assets/app.js?v={app_js_hash}", page)
        team_page = (ROOT / "team_match.html").read_text(encoding="utf-8")
        self.assertIn(f"assets/app.css?v={app_css_hash}", team_page)

    def test_refresh_binds_team_drawer_code_without_changing_model_generation(self):
        generation = self.config["generation_id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for asset in CONTENT_HASHED_ASSETS:
                target = root / asset
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"fixture {asset}".encode())
            page = root / "match_explorer.html"
            page.write_text(
                '<meta name="opportunity-team-generation" content="' + generation + '">'
                '<script src="assets/opportunity-team.js?v=old"></script>'
                '<script src="assets/opportunity-team-panel.js?v=old"></script>',
                encoding="utf-8",
            )
            update_version_target(page, generation)
            first = page.read_text(encoding="utf-8")
            panel = root / "assets/opportunity-team-panel.js"
            panel.write_bytes(b"changed drawer only")
            update_version_target(page, generation)
            updated = page.read_text(encoding="utf-8")
            self.assertNotEqual(first, updated)
            self.assertIn(GENERATION_MARKER.format(generation=generation), updated)
            self.assertIn(f'assets/opportunity-team.js?v={hashlib.sha256((root / "assets/opportunity-team.js").read_bytes()).hexdigest()}', updated)
            self.assertIn(f'assets/opportunity-team-panel.js?v={hashlib.sha256(panel.read_bytes()).hexdigest()}', updated)

    def test_browser_projection_stays_compact(self):
        self.assertLessEqual(len(self.browser_bytes), MAX_BROWSER_BYTES)
        self.assertLessEqual(len(gzip.compress(self.browser_bytes, compresslevel=9)), 500_000)
        self.assertLessEqual(len(self.index_bytes), MAX_INDEX_BYTES)
        self.assertLessEqual(len(gzip.compress(self.index_bytes, compresslevel=9)), 65_536)

    def test_import_provenance_and_curated_cheme_descriptors_are_preserved(self):
        hashes = self.config["source_hashes"]
        self.assertEqual(
            hashes["faculty_workbook"],
            "4cc24fad355c5716a462b93e1f60d0c7d55d9368d7cfede330ff41daa36af130",
        )
        for key in ("faculty_model", "team_gate_model", "benchmark_lock", "faculty_expansion_lock", "team_gate_lock"):
            self.assertRegex(hashes[key], r"^[a-f0-9]{64}$")
        curated = (ROOT / "data" / "faculty_matches.js").read_text(encoding="utf-8")
        self.assertIn("heterogeneous thermal catalysis", curated)
        self.assertIn("electrocatalytic aqueous PFAS defluorination", curated)
        self.assertIn("solid-state battery electrolytes", curated)


if __name__ == "__main__":
    unittest.main()
