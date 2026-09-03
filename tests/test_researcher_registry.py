from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest

from scripts.researcher_registry import (
    apply_approved_submission,
    canonical_bytes,
    dependency_report,
    directory_projection,
    legacy_faculty_projection,
    load_registry,
    material_claim_hash,
    matching_profiles,
    registry_counts,
    registry_generation,
    validate_registry,
    validate_opportunity_team_dependencies,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "researcher_registry.json"
TEAM_MODEL_PATH = ROOT / "config" / "opportunity_team_model.json"


def assignment_json(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    return json.loads(source[source.index("{"):].rstrip().rstrip(";"))


class ResearcherRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(REGISTRY_PATH)
        cls.team_model = json.loads(TEAM_MODEL_PATH.read_text(encoding="utf-8"))

    def test_generation_ids_and_claim_ownership_are_stable(self):
        self.assertEqual(self.registry["registry_generation"], registry_generation(self.registry))
        self.assertGreaterEqual(len(self.registry["researchers"]), 158)
        researcher_ids = {row["researcher_id"] for row in self.registry["researchers"]}
        self.assertEqual(len(researcher_ids), len(self.registry["researchers"]))
        self.assertTrue(all(re.fullmatch(r"urh-[0-9]{6}", value) for value in researcher_ids))
        for researcher in self.registry["researchers"]:
            self.assertNotIn(researcher["researcher_id"], researcher["legacy_ids"])
            for claim in researcher["claims"]:
                self.assertTrue(claim["claim_id"].startswith(researcher["researcher_id"] + "-c"))
                self.assertEqual(claim["material_hash"], material_claim_hash(claim))

    def test_legacy_claim_ids_are_bounded_global_strings(self):
        claims = [claim for researcher in self.registry["researchers"] for claim in researcher["claims"]]
        legacy_ids = [legacy_id for claim in claims for legacy_id in claim["legacy_claim_ids"]]
        self.assertEqual(len(legacy_ids), len({legacy_id.casefold() for legacy_id in legacy_ids}))
        self.assertTrue(all(isinstance(legacy_id, str) and 0 < len(legacy_id) <= 80 for legacy_id in legacy_ids))

        malformed = copy.deepcopy(self.registry)
        malformed["researchers"][0]["claims"][0]["legacy_claim_ids"] = "aaron-bauer:CV077"
        with self.assertRaisesRegex(ValueError, r"must be a list"):
            validate_registry(malformed, require_generation=False)

        duplicate = copy.deepcopy(self.registry)
        duplicate["researchers"][0]["claims"][0]["legacy_claim_ids"] = ["collision:CV001"]
        duplicate["researchers"][1]["claims"][0]["legacy_claim_ids"] = ["COLLISION:cv001"]
        with self.assertRaisesRegex(ValueError, r"globally unique"):
            validate_registry(duplicate, require_generation=False)

    def test_public_directory_and_manifest_are_exact_registry_projections(self):
        directory = assignment_json(ROOT / "data" / "researcher_directory.js")
        manifest = json.loads((ROOT / "data" / "researcher_registry_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(directory, directory_projection(self.registry))
        self.assertEqual(manifest["registry_generation"], self.registry["registry_generation"])
        self.assertEqual(manifest["counts"], registry_counts(self.registry))
        self.assertEqual(manifest["researcher_ids"], [row["researcher_id"] for row in self.registry["researchers"]])

    def test_team_model_researcher_projection_and_references_resolve(self):
        self.assertEqual(self.team_model["faculty"], legacy_faculty_projection(self.registry))
        identities = {row["researcher_id"] for row in self.registry["researchers"]}
        for opportunity in self.team_model["opportunities"]:
            for member in opportunity["members"]:
                self.assertIn(member["faculty_id"], identities)
            for role in opportunity["roles"]:
                self.assertTrue(set(role["candidate_ids"]).issubset(identities))
                self.assertTrue(set(role["alternative_ids"]).issubset(identities))

    def test_department_forward_matcher_uses_registry_claims(self):
        generated = assignment_json(ROOT / "data" / "faculty_matches.js")
        profiles = {row["name"]: row for row in matching_profiles(self.registry)}
        self.assertEqual(generated["registry_generation"], self.registry["registry_generation"])
        self.assertEqual(set(generated["faculty"]), set(profiles))
        for name, metadata in generated["faculty"].items():
            self.assertEqual(metadata["researcher_id"], profiles[name]["researcher_id"])
            self.assertEqual(metadata["claim_refs"], profiles[name]["claim_refs"])

    def test_department_projection_keeps_legacy_lookup_name_and_canonical_display_name(self):
        profile = next(
            row for row in matching_profiles(self.registry)
            if row["researcher_id"] == "urh-000014"
        )
        self.assertEqual(profile["name"], "Astrid M. Muller")
        self.assertEqual(profile["resolved_name"], "Astrid M. Müller")

    def test_cosmetic_and_scientific_changes_have_bounded_dependency_effects(self):
        renamed = copy.deepcopy(self.registry)
        renamed["researchers"][0]["display_name"] += " Test"
        renamed.pop("registry_generation")
        renamed["registry_generation"] = registry_generation(renamed)
        cosmetic = dependency_report(self.registry, renamed, self.team_model)
        self.assertEqual(cosmetic["affected_team_scopes"], [])

        selected_id = self.team_model["opportunities"][0]["members"][0]["faculty_id"]
        scientific = copy.deepcopy(self.registry)
        researcher = next(row for row in scientific["researchers"] if row["researcher_id"] == selected_id)
        researcher["claims"][0]["evidence"] += " (reviewed update)"
        researcher["claims"][0]["material_hash"] = material_claim_hash(researcher["claims"][0])
        scientific.pop("registry_generation")
        scientific["registry_generation"] = registry_generation(scientific)
        report = dependency_report(self.registry, scientific, self.team_model)
        self.assertTrue(report["affected_team_scopes"])
        expected = {
            opportunity["id"]
            for opportunity in self.team_model["opportunities"]
            if selected_id in {member["faculty_id"] for member in opportunity["members"]}
            or any(selected_id in role["candidate_ids"] + role["alternative_ids"] for role in opportunity["roles"])
        }
        self.assertEqual({row["scope_id"] for row in report["affected_team_scopes"]}, expected)

    def test_team_calibrations_reject_referenced_evidence_changes(self):
        validate_opportunity_team_dependencies(self.registry, self.team_model)
        selected = self.team_model["opportunities"][0]["members"][0]
        changed = copy.deepcopy(self.registry)
        researcher = next(
            row for row in changed["researchers"]
            if row["researcher_id"] == selected["faculty_id"]
        )
        claim = next(
            claim for claim in researcher["claims"]
            if claim["status"] == "active" and claim["label"] == selected["evidence_term"]
        )
        claim["status"] = "retired"
        claim["material_hash"] = material_claim_hash(claim)
        changed.pop("registry_generation")
        changed["registry_generation"] = registry_generation(changed)
        validate_registry(changed)
        with self.assertRaisesRegex(
            ValueError,
            r"calibrated opportunity-team scopes require recalibration.*urh-[0-9]{6}",
        ):
            validate_opportunity_team_dependencies(changed, self.team_model)
        approved_profile = {
            key: researcher[key]
            for key in (
                "display_name", "sort_name", "aliases", "orcid_id", "home_unit", "relationship",
                "pool_visibility", "auto_proposable", "status", "research_summary", "source_urls",
                "source_checked_date", "claims",
            )
        }
        with self.assertRaisesRegex(ValueError, r"require recalibration"):
            apply_approved_submission(
                self.registry,
                {
                    "schema_version": 1,
                    "state": "approved",
                    "researcher_id": selected["faculty_id"],
                    "approved_at": "2026-09-03T12:00:00Z",
                    "approved_profile": approved_profile,
                },
                self.registry["registry_generation"],
                team_model=self.team_model,
            )

        ineligible = copy.deepcopy(self.registry)
        researcher = next(
            row for row in ineligible["researchers"]
            if row["researcher_id"] == selected["faculty_id"]
        )
        researcher["status"] = "inactive"
        researcher["auto_proposable"] = False
        ineligible.pop("registry_generation")
        ineligible["registry_generation"] = registry_generation(ineligible)
        validate_registry(ineligible)
        with self.assertRaisesRegex(ValueError, r"require recalibration"):
            validate_opportunity_team_dependencies(ineligible, self.team_model)

    def test_unreferenced_and_cosmetic_edits_do_not_invalidate_team_calibrations(self):
        referenced = {
            identity
            for opportunity in self.team_model["opportunities"]
            for identity in (
                [member["faculty_id"] for member in opportunity["members"]]
                + [
                    value
                    for role in opportunity["roles"]
                    for field in ("candidate_ids", "alternative_ids")
                    for value in role[field]
                ]
            )
        }
        changed = copy.deepcopy(self.registry)
        unreferenced = next(
            row for row in changed["researchers"]
            if row["researcher_id"] not in referenced
            and row["status"] == "active"
            and row["auto_proposable"]
        )
        unreferenced["status"] = "inactive"
        unreferenced["auto_proposable"] = False
        referenced_profile = next(
            row for row in changed["researchers"]
            if row["researcher_id"] in referenced
        )
        referenced_profile["display_name"] += " Renamed"
        changed.pop("registry_generation")
        changed["registry_generation"] = registry_generation(changed)
        validate_registry(changed)
        validate_opportunity_team_dependencies(changed, self.team_model)

    def test_approved_updates_are_registry_only_and_claim_revisions_increment(self):
        target = copy.deepcopy(self.registry["researchers"][0])
        old_revision = target["claims"][0]["revision"]
        target["claims"][0]["evidence"] += " reviewed"
        approved_profile = {
            key: target[key]
            for key in (
                "display_name", "sort_name", "aliases", "orcid_id", "home_unit", "relationship",
                "pool_visibility", "auto_proposable", "status", "research_summary", "source_urls",
                "source_checked_date", "claims",
            )
        }
        updated, _ = apply_approved_submission(self.registry, {
            "schema_version": 1, "state": "approved", "researcher_id": target["researcher_id"],
            "approved_at": "2026-09-03T12:00:00Z", "approved_profile": approved_profile,
        }, self.registry["registry_generation"])
        updated_target = next(row for row in updated["researchers"] if row["researcher_id"] == target["researcher_id"])
        self.assertEqual(updated_target["claims"][0]["revision"], old_revision + 1)
        self.assertNotEqual(updated["registry_generation"], self.registry["registry_generation"])

        unchanged_profile = {
            key: copy.deepcopy(updated_target[key])
            for key in approved_profile
        }
        unchanged_profile["claims"][0]["revision"] = 1
        unchanged, _ = apply_approved_submission(updated, {
            "schema_version": 1, "state": "approved", "researcher_id": target["researcher_id"],
            "approved_at": "2026-09-03T12:05:00Z", "approved_profile": unchanged_profile,
        }, updated["registry_generation"])
        unchanged_target = next(row for row in unchanged["researchers"] if row["researcher_id"] == target["researcher_id"])
        self.assertEqual(unchanged_target["claims"][0]["revision"], old_revision + 1)

        invalid_profile = copy.deepcopy(approved_profile)
        invalid_profile["claims"][0]["revision"] = 0
        with self.assertRaisesRegex(ValueError, r"positive integer"):
            apply_approved_submission(self.registry, {
                "schema_version": 1, "state": "approved", "researcher_id": target["researcher_id"],
                "approved_at": "2026-09-03T12:00:00Z", "approved_profile": invalid_profile,
            }, self.registry["registry_generation"])

        omitted_profile = copy.deepcopy(approved_profile)
        omitted_profile["claims"] = omitted_profile["claims"][1:]
        with self.assertRaisesRegex(ValueError, r"must remain present and be retired"):
            apply_approved_submission(self.registry, {
                "schema_version": 1, "state": "approved", "researcher_id": target["researcher_id"],
                "approved_at": "2026-09-03T12:00:00Z", "approved_profile": omitted_profile,
            }, self.registry["registry_generation"])

    def test_data_only_add_retire_rename_and_pool_changes_remain_valid(self):
        added, _ = apply_approved_submission(self.registry, {
            "schema_version": 1,
            "state": "approved",
            "researcher_id": None,
            "approved_at": "2026-09-03T12:00:00Z",
            "approved_profile": {
                "display_name": "Example Researcher",
                "sort_name": "Researcher, Example",
                "aliases": [],
                "orcid_id": "",
                "home_unit": "Example unit",
                "relationship": "reference_only_researcher",
                "pool_visibility": "hidden",
                "auto_proposable": False,
                "status": "active",
                "research_summary": "A bounded registry acceptance fixture.",
                "source_urls": ["https://example.edu/researcher"],
                "source_checked_date": "2026-09-03",
                "claims": [{
                    "claim_id": "", "revision": 1, "status": "active",
                    "label": "Example capability", "category": "Interdisciplinary research",
                    "type": "Capability", "evidence": "Example capability",
                    "source_urls": ["https://example.edu/researcher"],
                    "verified_on": "2026-09-03", "evidence_level": "administrator_reviewed",
                    "legacy_claim_ids": [],
                }],
            },
        }, self.registry["registry_generation"])
        self.assertEqual(registry_counts(added)["total"], registry_counts(self.registry)["total"] + 1)
        added_target = next(row for row in added["researchers"] if row["display_name"] == "Example Researcher")
        self.assertTrue(added_target["claims"][0]["claim_id"].startswith(added_target["researcher_id"]))
        preassigned_profile = {
            key: copy.deepcopy(added_target[key])
            for key in (
                "display_name", "sort_name", "aliases", "orcid_id", "home_unit", "relationship",
                "pool_visibility", "auto_proposable", "status", "research_summary", "source_urls",
                "source_checked_date", "claims",
            )
        }
        preassigned_profile["claims"][0]["claim_id"] = "urh-999999-c001"
        with self.assertRaisesRegex(ValueError, r"cannot preassign claim IDs"):
            apply_approved_submission(self.registry, {
                "schema_version": 1, "state": "approved", "researcher_id": None,
                "approved_at": "2026-09-03T12:00:00Z", "approved_profile": preassigned_profile,
            }, self.registry["registry_generation"])

        changed = copy.deepcopy(self.registry)
        target = next(row for row in changed["researchers"] if row["auto_proposable"] and len(row["claims"]) >= 2)
        stable_id = target["researcher_id"]
        original_pool = registry_counts(changed)["pool_counts"]
        target["display_name"] += " Renamed"
        target["auto_proposable"] = False
        target["claims"][0]["status"] = "retired"
        target["claims"][0]["material_hash"] = material_claim_hash(target["claims"][0])
        changed.pop("registry_generation")
        changed["registry_generation"] = registry_generation(changed)
        self.assertEqual(validate_registry(changed), changed)
        changed_target = next(row for row in changed["researchers"] if row["researcher_id"] == stable_id)
        self.assertEqual(changed_target["researcher_id"], stable_id)
        self.assertNotEqual(registry_counts(changed)["pool_counts"], original_pool)

    def test_no_parallel_hard_coded_faculty_source_remains(self):
        matcher = (ROOT / "scripts" / "faculty_match.py").read_text(encoding="utf-8")
        runtime = (ROOT / "assets" / "opportunity-team.js").read_text(encoding="utf-8")
        self.assertFalse((ROOT / "faculty_profiles.json").exists())
        for symbol in ("FACULTY_KEYTERMS", "FACULTY_RESEARCH_SUMMARIES", "FACULTY_DOMAINS"):
            self.assertNotIn(symbol, matcher)
        self.assertNotRegex(runtime, r"faculty\.length\s*!==\s*\d+")
        self.assertNotRegex(runtime, r"pools\.main\s*!==\s*\d+")
        self.assertIn("directory.counts", runtime)


if __name__ == "__main__":
    unittest.main()
