import copy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts.build_opportunity_teams import (
    assemble, diverse_queue, eligible_claims, normalized_vectors, scopes, validate_roles, validate_edges,
    source_fingerprints, invalidate_stale_sources,
    generate_scope, coverage, attempt_completed, refresh_assemblies, ASSEMBLY_VERSION, recent_scope_ids,
)


class ProposedTeamTests(unittest.TestCase):
    def setUp(self):
        self.scope = {"id": "parent:child", "parent_id": "parent", "record_type": "publishable_child",
                      "text": "Develop catalyst materials. Measure reaction kinetics.", "source_url": "https://example.org/child"}
        self.roles = [
            {"id": "role-1", "label": "Catalyst design", "required": True, "quote": "Develop catalyst materials."},
            {"id": "role-2", "label": "Reaction kinetics", "required": True, "quote": "Measure reaction kinetics."},
        ]
        self.decomposition = {"specific": True, "objective": "Develop and measure catalytic materials", "roles": self.roles}
        self.claims = {f"person-{i}-claim": {"claim_id": f"person-{i}-claim", "revision": 1,
            "material_hash": str(i), "researcher_id": f"person-{i}", "name": f"Person {i}",
            "label": label, "evidence": label + " supported research", "source_url": "https://example.org/faculty"}
            for i, label in enumerate(["Catalyst design", "Reaction kinetics", "Catalyst design"], 1)}
        self.edges = [{"role_id": role, "claim_id": claim, "coverage": "direct", "reason": "Evidence supports this specific scientific contribution."}
            for role, claim in [("role-1", "person-1-claim"), ("role-2", "person-2-claim"), ("role-1", "person-3-claim")]]

    def test_broad_scopes_and_sibling_quotes_cannot_support_teams(self):
        self.assertEqual(validate_roles(self.scope, {"specific": False}), [])
        wrong = copy.deepcopy(self.decomposition)
        wrong["roles"][0]["quote"] = "A different sibling's fabrication requirement."
        with self.assertRaisesRegex(ValueError, "exact scope"):
            validate_roles(self.scope, wrong)

    def test_claim_ownership_and_edge_identity_are_not_model_assertions(self):
        wrong = copy.deepcopy(self.edges)
        wrong[0]["claim_id"] = "invented-claim"
        with self.assertRaises(ValueError):
            validate_edges({"edges": wrong}, self.roles, self.claims)
        with self.assertRaises(ValueError):
            validate_edges({"edges": self.edges + self.edges[:1]}, self.roles, self.claims)
        with self.assertRaises(ValueError):
            validate_edges({"edges": self.edges}, self.roles, self.claims, allowed=set())
        with self.assertRaisesRegex(ValueError, "upgrade"):
            validate_edges({"edges": self.edges[:1]}, self.roles, self.claims,
                           allowed={(self.edges[0]["role_id"], self.edges[0]["claim_id"]): "adjacent"})

    def test_distinct_two_person_options_preserve_the_same_role_coverage(self):
        team = assemble(self.scope, self.decomposition, self.edges, self.claims, "generation")
        self.assertEqual(len(team["variants"]), 2)
        self.assertTrue(all(len(v["member_ids"]) == 2 for v in team["variants"]))
        self.assertEqual(team["missing_skills"], [])
        self.assertEqual(team["gate_state"], "pass")
        self.assertTrue(all(member["claim_id"] in self.claims for member in team["members"]))

    def test_adjacent_support_never_closes_a_required_role(self):
        decomposition = copy.deepcopy(self.decomposition)
        decomposition["roles"].append({"id": "role-3", "label": "Clinical translation", "required": True,
                                       "quote": "Measure reaction kinetics."})
        edges = copy.deepcopy(self.edges)
        edges.append(edges[1] | {"role_id": "role-3", "coverage": "adjacent"})
        team = assemble(self.scope, decomposition, edges, self.claims, "generation")
        self.assertIn("Clinical translation", team["missing_skills"])
        self.assertEqual(team["gate_state"], "conditional")
        self.assertEqual(team["roles"][2]["candidate_ids"], [])

    def test_two_people_with_the_same_contribution_do_not_establish_a_team(self):
        same_role = [edge for edge in self.edges if edge["role_id"] == "role-1"]
        self.assertIsNone(assemble(self.scope, self.decomposition, same_role, self.claims, "generation"))
        redundant = self.edges[:2] + [self.edges[0] | {"role_id": "role-2"}]
        self.assertIsNone(assemble(self.scope, self.decomposition, redundant, self.claims, "generation"))

    def test_current_evidence_is_reassembled_without_weakening_or_restoring_stale_proposals(self):
        row = assemble(self.scope, self.decomposition, self.edges, self.claims, "generation")
        row.pop("assembly_version")
        existing = {row["id"]: row}
        self.assertEqual(refresh_assemblies(existing, [self.scope], self.claims, "generation"),
                         [{"scope_id": row["id"], "state": "proposed"}])
        self.assertEqual(existing[row["id"]]["assembly_version"], ASSEMBLY_VERSION)
        self.assertEqual(refresh_assemblies(existing, [self.scope], self.claims, "generation"), [])
        row.pop("assembly_version", None)
        row["roles"][1]["claim_refs"] = []
        existing = {row["id"]: row}
        self.assertEqual(refresh_assemblies(existing, [self.scope], self.claims, "generation")[0]["state"], "insufficient_evidence")
        self.assertEqual(row["review_state"], "needs_revalidation")
        self.assertEqual(refresh_assemblies(existing, [self.scope], self.claims, "generation"), [])

    def test_equal_coverage_prefers_direct_experience_over_method_transfer(self):
        edges = copy.deepcopy(self.edges)
        edges[0]["coverage"] = "method_transfer"
        team = assemble(self.scope, self.decomposition, edges, self.claims, "generation")
        self.assertEqual(team["variants"][0]["member_ids"], ["person-2", "person-3"])
        self.assertEqual(len(team["variants"]), 2, "the plausible transfer option remains available")

    def test_departed_hidden_and_retired_claims_leave_the_candidate_pool(self):
        registry = {"researchers": [{"researcher_id": "a", "display_name": "A", "status": "active",
            "auto_proposable": True, "pool_visibility": "institution", "claims": [{"claim_id": "a-1",
            "status": "active", "revision": 1, "material_hash": "hash", "label": "Catalysis",
            "evidence": "Supported catalyst synthesis", "source_urls": ["https://example.org"]}]}]}
        self.assertEqual(len(eligible_claims(registry)), 1)
        for field, value in [("status", "inactive"), ("auto_proposable", False), ("pool_visibility", "hidden")]:
            changed = copy.deepcopy(registry)
            changed["researchers"][0][field] = value
            self.assertEqual(eligible_claims(changed), {})
        registry["researchers"][0]["claims"][0]["status"] = "retired"
        self.assertEqual(eligible_claims(registry), {})

    def test_large_parent_cannot_monopolize_generation(self):
        scopes = [{"id": str(i), "parent_id": "umbrella" if i < 8 else str(i)} for i in range(12)]
        scores = {str(i): 1 - i / 20 for i in range(12)}
        selected = diverse_queue(scopes, scores, 6)
        self.assertEqual([s["id"] for s in selected], ["0", "1", "2", "8", "9", "10"])

    def test_expansion_prioritizes_uncovered_calls_and_one_topic_per_call(self):
        candidates = [{"id": "covered:one", "parent_id": "covered"},
                      {"id": "new:one", "parent_id": "new"},
                      {"id": "new:two", "parent_id": "new"},
                      {"id": "other", "parent_id": "other"}]
        scores = {"covered:one": .99, "new:one": .8, "new:two": .9, "other": .7}
        selected = diverse_queue(candidates, scores, 3, per_parent=1, covered_parents={"covered"})
        self.assertEqual([s["id"] for s in selected], ["new:two", "other", "covered:one"])

    def test_malformed_provider_output_can_retry_without_becoming_a_scientific_rejection(self):
        provider = Mock()
        for error in [json.JSONDecodeError("Incomplete JSON", "{", 1), RuntimeError("incomplete model response")]:
            provider.json.side_effect = error
            result, proposal = generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
            self.assertEqual(result["state"], "unavailable")
            self.assertIsNone(proposal)
        provider.json.side_effect = None
        provider.json.return_value = self.decomposition | {"roles": [self.roles[0] | {"quote": "Invented unsupported quote"}, self.roles[1]]}
        result, proposal = generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
        self.assertEqual(result["state"], "rejected_evidence")
        self.assertIsNone(proposal)

    def test_refresh_reserves_room_for_changed_teams_amid_a_new_call_backlog(self):
        candidates = [{"id": str(i), "parent_id": str(i)} for i in range(12)]
        scores = {str(i): 1 - i / 20 for i in range(12)}
        selected = diverse_queue(candidates, scores, 8, per_parent=1,
                                 covered_parents={"10", "11"}, maintenance_ids={"10", "11"})
        self.assertEqual([s["id"] for s in selected], ["10", "11", "0", "1", "2", "3", "4", "5"])

    def test_attempts_retry_returning_calls_and_changed_inputs_but_remember_negative_results(self):
        stale = {"review_state": "needs_revalidation"}
        self.assertFalse(attempt_completed({"key": "same", "state": "proposed"}, "same", stale))
        self.assertFalse(attempt_completed("same", "same", stale), "legacy success must not strand a reopened call")
        for state in ["not_specific", "unsuitable_scope", "insufficient_evidence", "rejected_evidence"]:
            self.assertTrue(attempt_completed({"key": "same", "state": state}, "same", stale))
            self.assertFalse(attempt_completed({"key": "old", "state": state}, "changed", stale))
        self.assertFalse(attempt_completed({"key": "same", "state": "unavailable"}, "same"))
        self.assertTrue(attempt_completed("same", "same"))
        self.assertTrue(attempt_completed({"key": "same", "state": "proposed"}, "same", {}))

    def test_emerging_calls_receive_capacity_alongside_repairs_and_catalog_expansion(self):
        candidates = [{"id": str(i), "parent_id": str(i)} for i in range(12)]
        parents = [{"opportunity_id": str(i), "posted_date": posted}
                   for i, posted in enumerate(["2025-01-01"] * 6 + ["invalid", "2026-10-01", "2026-09-01", "2026-08-22", "2026-08-01", "2026-08-01"])]
        recent = recent_scope_ids(candidates, parents, date(2026, 9, 5))
        self.assertEqual(recent, {"8", "9"})
        scores = {str(i): 1 - i / 20 for i in range(12)}
        selected = diverse_queue(candidates, scores, 8, per_parent=1,
                                 maintenance_ids={"10", "11"}, recent_ids=recent)
        self.assertEqual([s["id"] for s in selected], ["10", "11", "8", "9", "0", "1", "2", "3"])

    def test_unstarted_work_defers_at_deadline_without_calling_a_provider(self):
        provider = Mock()
        result, proposal = generate_scope(self.scope, provider, self.claims, [], "registry", 0)
        self.assertEqual(result["state"], "deferred")
        self.assertIsNone(proposal)
        provider.json.assert_not_called()
        provider.embed.assert_not_called()

    def test_coverage_reports_distinct_calls_separately_from_topics_and_combinations(self):
        rows = [{"parent_id": "one", "variants": [{}, {}]}, {"parent_id": "one"},
                {"parent_id": "two", "variants": [{}, {}, {}]},
                {"parent_id": "three", "review_state": "needs_revalidation"}]
        self.assertEqual(coverage(rows), {"scopes": 3, "parent_calls": 2, "team_combinations": 6})

    def test_broad_parents_require_a_published_child_with_its_own_text(self):
        parents = [{"opportunity_id": identifier, "title": "Broad Agency Announcement", "status": "posted",
                    "description": "Parent umbrella expertise must not leak into child roles.", "close_date": "2099-12-31"}
                   for identifier in ["with-child", "no-child", "expired"]]
        parents[-1]["close_date"] = "2020-01-01"
        child = {"subtopic_id": "with-child:one", "title": "Catalyst synthesis", "publication_state": "publishable",
                 "summary": "Develop and characterize selective catalysts through controlled synthesis and reaction kinetics under specified conditions.",
                 "source_document_url": "https://example.org/official-child"}
        sidecar = {"records": {"with-child": {"subtopics": [child, dict(child, subtopic_id="with-child:review", publication_state="review")]}}}
        with patch("scripts.build_opportunity_teams._load_catalog", return_value=parents), patch("scripts.build_opportunity_teams.load_sidecar", return_value=sidecar):
            actual = scopes()
        self.assertEqual([s["id"] for s in actual], ["with-child:one"])
        self.assertNotIn("umbrella", actual[0]["text"])
        self.assertEqual(actual[0]["source_url"], child["source_document_url"])

    def test_curated_and_generated_sources_share_invalidation_and_missing_baselines_fail_closed(self):
        model = {"opportunities": [
            {"id": "curated", "source_fingerprint": "old"},
            {"id": "generated", "generator_version": "v2", "source_fingerprint": "old"},
            {"id": "removed", "source_fingerprint": "old"},
            {"id": "untracked"},
            {"id": "unchanged", "source_fingerprint": "same"},
        ]}
        fingerprints = {"curated": "new", "generated": "new", "untracked": "current", "unchanged": "same"}
        self.assertEqual(invalidate_stale_sources(model, fingerprints), ["curated", "generated", "removed", "untracked"])
        self.assertNotIn("review_state", model["opportunities"][-1])
        self.assertNotIn("source_fingerprint", model["opportunities"][-2])
        fingerprints["curated"] = "old"
        invalidate_stale_sources(model, fingerprints)
        self.assertEqual(model["opportunities"][0]["review_state"], "needs_revalidation",
                         "Returning source text must not silently restore a withheld proposal")

    def test_declared_branches_track_parent_sources_and_eligibility_without_generating_broad_teams(self):
        parent = {"opportunity_id": "parent", "title": "Broad Agency Announcement", "status": "posted",
                  "description": "Several unrelated scientific areas.", "close_date": "2099-12-31",
                  "primary_document_url": "https://example.org/notice"}
        branch = {"id": "parent:branch", "parent_id": "parent", "record_type": "declared_branch",
                  "scope_label": "A specific reviewed branch", "objective": "One bounded objective",
                  "source_url": "https://example.org/branch"}
        model = {"opportunities": [branch]}
        with patch("scripts.build_opportunity_teams._load_catalog", return_value=[parent]), patch(
                "scripts.build_opportunity_teams.load_sidecar", return_value={"records": {}}):
            candidates = scopes()
            baseline = source_fingerprints(model, candidates)
        self.assertEqual(candidates, [], "Tracking must not admit a broad parent to team generation")
        branch["source_fingerprint"] = baseline[branch["id"]]
        self.assertEqual(invalidate_stale_sources(model, baseline), [])
        for change in ({"description": "Changed official research priorities."},
                       {"primary_document_url": "https://example.org/replaced-notice"},
                       {"close_date": "2020-01-01"}):
            with patch("scripts.build_opportunity_teams._load_catalog", return_value=[parent | change]):
                fingerprints = source_fingerprints(model, [])
            changed = copy.deepcopy(model)
            self.assertEqual(invalidate_stale_sources(changed, fingerprints), [branch["id"]])
        with patch("scripts.build_opportunity_teams._load_catalog", return_value=[]):
            self.assertEqual(invalidate_stale_sources(copy.deepcopy(model), source_fingerprints(model, [])), [branch["id"]])

    def test_child_source_changes_do_not_invalidate_an_unchanged_sibling(self):
        parent = {"opportunity_id": "parent", "title": "Broad Agency Announcement",
                  "status": "posted", "close_date": "2099-12-31"}
        child = {"subtopic_id": "parent:one", "title": "Catalyst synthesis", "publication_state": "publishable",
                 "summary": "Develop and characterize selective catalysts through controlled synthesis and reaction kinetics under specified conditions.",
                 "source_document_url": "https://example.org/official-child"}
        children = [child, child | {"subtopic_id": "parent:two"}]
        def current(rows):
            with patch("scripts.build_opportunity_teams._load_catalog", return_value=[parent]), patch(
                    "scripts.build_opportunity_teams.load_sidecar", return_value={"records": {"parent": {"subtopics": rows}}}):
                return scopes()
        baseline = current(children)
        model = {"opportunities": [{"id": row["id"], "record_type": "publishable_child",
                                    "source_fingerprint": row["source_fingerprint"]} for row in baseline]}
        changed = current([child | {"summary": child["summary"] + " New sponsor requirements."}, children[1]])
        self.assertEqual(invalidate_stale_sources(model, source_fingerprints(model, changed)), ["parent:one"])
        self.assertNotIn("review_state", model["opportunities"][1])
        self.assertEqual(invalidate_stale_sources(model, source_fingerprints(model, current([child]))),
                         ["parent:two"])

    def test_published_curated_catalog_has_explicit_current_source_baselines(self):
        model = json.loads(Path("config/opportunity_team_model.json").read_text(encoding="utf-8"))
        fingerprints = source_fingerprints(model, scopes())
        curated = [row for row in model["opportunities"] if not row.get("generator_version")]
        self.assertTrue(curated)
        for row in curated:
            self.assertRegex(row.get("source_fingerprint", ""), r"^[a-f0-9]{64}$")
            if row.get("review_state") != "needs_revalidation":
                self.assertEqual(row["source_fingerprint"], fingerprints.get(row["id"]))

    def test_vectors_use_cosine_and_reject_malformed_provider_values(self):
        vector = [3, 4] + [0] * 1022
        normalized = normalized_vectors([vector], 1)[0]
        self.assertEqual(normalized[:2], [.6, .8])
        for bad in ([0] * 1024, [True] * 1024, [float("nan")] * 1024, [1] * 1023):
            with self.assertRaises(ValueError):
                normalized_vectors([bad], 1)


if __name__ == "__main__":
    unittest.main()
