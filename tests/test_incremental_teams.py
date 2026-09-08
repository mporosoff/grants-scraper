"""Actual team entrypoint with deterministic providers and isolated canonical inputs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import chdir, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import build_opportunity_teams as teams, researcher_registry as researchers
from tests.fixtures import phase2_pipeline as fixture


def provider_response(url, json, **kwargs):
    body = json
    if "input" in body:
        vectors = []
        for text in body["input"]:
            seed = hashlib.sha256(text.encode()).digest()
            vectors.append([(seed[i % 32] + 1) / 10000 for i in range(1024)])
        payload = {"model": "voyage-4-lite", "data": [{"index": i, "embedding": vector} for i, vector in enumerate(vectors)]}
    else:
        data = __import__("json").loads(body["messages"][0]["content"])
        prompt = body["system"]
        if prompt == teams.DECOMPOSE:
            specific = all(role["quote"] in data["scope"] for role in fixture.ROLES)
            value = {"specific": specific, "objective": "Investigate catalysts and reaction kinetics",
                     "roles": fixture.ROLES if specific else []}
        else:
            edges = [{"role_id": role["id"], "claim_id": claim["claim_id"], "coverage": "direct",
                      "reason": "Exact cited experimental evidence supports the specified contribution."}
                     for role in data["roles"] for claim in data["claims"]
                     if role["quote"] in claim["evidence"] and role["label"] == claim["label"]]
            value = {"edges": edges}
            if prompt == teams.VERIFY:
                value["suitable_for_team"] = True
        payload = {"model": teams.MODEL, "usage": {"input_tokens": 100, "output_tokens": 100}, "stop_reason": "end_turn", "content": [{"type": "text", "text": __import__("json").dumps(value)}]}
    return Mock(status_code=200, json=lambda: payload)


class IncrementalTeams(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture.run_pipeline(self.root)
        self.model_path = self.root / "config/opportunity_team_model.json"
        self.empty = json.loads(self.model_path.read_text())
        self.empty["opportunities"] = []
        self.empty["generation_attempts"] = {}
        self.empty.pop("discovery_queue", None)
        self.empty.pop("accepted_scope_snapshot", None)
        self.invocation = 0
        self.model_path.write_text(json.dumps(self.empty), encoding="utf-8")

    def run_main(self, **options):
        self.invocation += 1
        current = json.loads(self.model_path.read_text())
        mode = options.pop('mode', 'maintenance' if current.get('accepted_scope_snapshot') else 'backfill')
        with chdir(self.root), redirect_stdout(io.StringIO()), patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "synthetic", "VOYAGE_API_KEY": "synthetic"}), patch.object(
                teams.requests, "post", side_effect=options.pop("response", provider_response)) as post, patch(
                    "sys.argv", ["teams", "--generate", "--write", "--workers", "1", "--mode", mode, "--state", f".spend/run-{self.invocation}", *options.pop("args", [])]):
            code = teams.main()
        report = json.loads((self.root / "evaluation/opportunity_team_generation.json").read_text())
        model = json.loads(self.model_path.read_text())
        self.assertEqual(report["provider_requests"], post.call_count)
        self.assertIn(model["generation_id"], (self.root / "data/opportunity_team_index.js").read_text())
        self.assertIn(model["generation_id"], (self.root / "data/opportunity_teams.js").read_text())
        return code, report, model, post.call_args_list

    def update_catalog(self, mutate):
        path = self.root / "data/opportunities.js"
        catalog = fixture.documents.read_catalog(path)
        mutate(catalog["opportunities"])
        rebuilt = fixture.build_catalog.build_catalog(catalog["opportunities"], fixture.NOW, "synthetic phase 3", 0)
        fixture.build_catalog.write_catalog(rebuilt, path)

    def add_call(self):
        def add(rows):
            new = deepcopy(next(row for row in rows if row["opportunity_id"].endswith(":research")))
            new.update(opportunity_id="fixture-new-call", opportunity_number="FIXTURE-NEW-CALL")
            rows.append(new)
        self.update_catalog(add)

    def test_warm_no_due_work_is_distinct_from_pending_and_reuses_per_claim(self):
        code, cold, model, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(cold["counters"]["canary_requests"], 2)
        self.assertEqual(len(model["opportunities"]), 1)
        code, warm, _, _ = self.run_main()
        self.assertEqual((code, warm["provider_requests"], warm["due_scopes"]), (0, 0, 0))
        # An unassessed new scope with the same evidenced source enters through
        # the canonical scope selector, with no changes to downstream consumers.
        self.add_call()
        code, pending, updated, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(pending["counters"]["item_vector_misses"], 0)
        self.assertEqual(pending["counters"]["canary_requests"], 2)
        self.assertEqual(len(updated["opportunities"]), 2)
        self.assertEqual(updated["opportunities"][0]["members"], model["opportunities"][0]["members"])

    def test_material_amendment_and_expiration_invalidate_only_exact_source(self):
        self.add_call()
        _, _, before, _ = self.run_main()
        def amend(rows):
            row = next(row for row in rows if row["opportunity_id"] == "fixture-new-call")
            row["document_evidence"]["document"]["sha256"] = "a" * 64
        self.update_catalog(amend)
        code, report, after, calls = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(report["source_invalidations"], ["fixture-new-call"])
        self.assertEqual(sum(call.kwargs["json"].get("system") == teams.DECOMPOSE for call in calls), 1)
        healthy = next(row for row in before["opportunities"] if row["id"].endswith(":research"))
        self.assertEqual(next(row for row in after["opportunities"] if row["id"] == healthy["id"]), healthy)
        self.model_path.write_text(json.dumps(self.empty), encoding="utf-8")
        _, _, clean, _ = self.run_main(args=["--cache", ".cache/clean-amendment"])
        self.assertEqual(sorted(after["opportunities"], key=lambda row: row["id"]),
                         sorted(clean["opportunities"], key=lambda row: row["id"]))
        def expire(rows):
            row = next(row for row in rows if row["opportunity_id"] == "fixture-new-call")
            row.update(close_date="2020-01-01", status="closed")
        self.update_catalog(expire)
        code, report, expired, _ = self.run_main()
        self.assertEqual((code, report["provider_requests"]), (0, 0))
        self.assertEqual(next(row for row in expired["opportunities"] if row["id"] == "fixture-new-call")["review_state"], "needs_revalidation")

    def test_corrected_claim_keeps_decomposition_and_matches_clean_evidence_graph(self):
        self.run_main()
        path = self.root / "config/researcher_registry.json"
        registry = json.loads(path.read_text())
        claim = registry["researchers"][0]["claims"][0]
        claim["revision"] += 1
        claim["evidence"] += " Corrected experimental provenance."
        claim["material_hash"] = researchers.material_claim_hash(claim)
        registry["registry_generation"] = researchers.registry_generation(registry)
        path.write_text(json.dumps(registry), encoding="utf-8")
        code, report, incremental, calls = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(report["counters"]["item_vector_misses"], 1)
        self.assertFalse(any(call.kwargs["json"].get("system") == teams.DECOMPOSE for call in calls))
        self.model_path.write_text(json.dumps(self.empty), encoding="utf-8")
        code, _, clean, _ = self.run_main(args=["--cache", ".cache/clean-teams"])
        self.assertEqual(code, 0)
        self.assertEqual(incremental["opportunities"], clean["opportunities"])
        refs = incremental["opportunities"][0]["roles"][0]["claim_refs"]
        self.assertEqual(refs[0]["revision"], claim["revision"])
        self.assertEqual(refs[0]["material_hash"], claim["material_hash"])

    def test_new_claim_preserves_source_only_negatives_and_compatible_team(self):
        _, _, before, _ = self.run_main()
        path = self.root / "config/researcher_registry.json"
        registry = json.loads(path.read_text())
        claim = deepcopy(registry["researchers"][0]["claims"][0])
        claim["claim_id"] = "urh-990001-c002"
        registry["researchers"][0]["claims"].append(claim)
        registry["registry_generation"] = researchers.registry_generation(registry)
        path.write_text(json.dumps(registry), encoding="utf-8")
        code, report, after, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(report["due_scopes"], 0, "A new claim does not make a broad source scientifically specific")
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(before["opportunities"][0]["members"], after["opportunities"][0]["members"])

    def test_removed_claim_withholds_before_failed_provider_and_budget_is_resumable(self):
        self.run_main()
        path = self.root / "config/researcher_registry.json"
        registry = json.loads(path.read_text())
        claim = registry["researchers"][0]["claims"][0]
        claim["status"] = "retired"
        claim["revision"] += 1
        claim["material_hash"] = researchers.material_claim_hash(claim)
        registry["registry_generation"] = researchers.registry_generation(registry)
        path.write_text(json.dumps(registry), encoding="utf-8")
        with patch.object(teams.time, "sleep"):
            code, report, model, _ = self.run_main(response=lambda *a, **k: Mock(status_code=503))
        self.assertEqual(code, 1)
        self.assertEqual(model["opportunities"][0]["review_state"], "needs_revalidation")
        self.assertGreater(report["pending_after"], 0)
        original = teams.Provider
        class SmallBudget(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, max_requests=2, **kwargs)
        with patch.object(teams, "Provider", SmallBudget):
            code, report, _, _ = self.run_main()
        self.assertEqual((code, report["provider_requests"]), (0, 2))
        self.assertTrue(report["time_budget_exhausted"])
        self.assertGreater(report["pending_after"], 0)
        code, resumed, _, _ = self.run_main()
        self.assertEqual((code, resumed["pending_after"]), (0, 0))
        self.assertEqual(self.run_main()[1]["provider_requests"], 0)

    def test_ranking_and_discovery_are_bounded_and_resume_across_invocations(self):
        def expand(rows):
            source = next(row for row in rows if row["opportunity_id"].endswith(":research"))
            for index in range(8):
                rows.append(deepcopy(source) | {"opportunity_id": f"fixture-call-{index}", "opportunity_number": f"FIXTURE-{index}"})
        self.update_catalog(expand)
        seen = set()
        for _ in range(3):
            code, report, model, _ = self.run_main(mode="backfill", args=["--max-scopes", "1"])
            self.assertEqual(code, 0)
            self.assertLessEqual(report["ranking_window"], 2)
            self.assertEqual(report["assessed_scopes"], 1)
            identifier = report["results"][0]["scope_id"]
            self.assertNotIn(identifier, seen)
            seen.add(identifier)
            self.assertGreater(report["pending_after"], 0)
            self.assertIn(identifier, model["discovery_queue"]["last_scheduled"])

    def test_partial_scheduler_batch_is_collected_before_budget_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = teams.Provider(directory, max_requests=2)
            class ImmediateExecutor:
                def submit(self, operation, scope):
                    value = operation(scope)
                    return Mock(result=lambda: value)
            def assess(scope):
                provider.calls += 1
                return scope["id"]
            completed = []
            with self.assertRaises(teams.BudgetExhausted):
                for item in teams.bounded_assess(ImmediateExecutor(), [{"id": i} for i in range(5)], assess, provider, 3):
                    completed.append(item)
            self.assertEqual([value for _, value in completed], [0, 1])
            self.assertEqual(provider.calls, 2)
        self.assertEqual(teams.discovery_checkpoint({"sequence": "bad"}, {}), {"sequence": 0, "last_scheduled": {}})

    def test_assembly_change_uses_verified_graph_without_provider_calls(self):
        self.run_main()
        with patch.object(teams, "ASSEMBLY_VERSION", "synthetic-compatible-assembly-2"):
            code, report, model, _ = self.run_main()
        self.assertEqual((code, report["provider_requests"]), (0, 0))
        self.assertEqual(len(report["assembly_updates"]), 1)
        self.assertEqual(model["opportunities"][0]["assembly_version"], "synthetic-compatible-assembly-2")

    def test_assessment_contract_change_withholds_before_failed_regeneration(self):
        self.run_main()
        with patch.object(teams, "VERIFY", teams.VERIFY + "\nSynthetic revised verification contract."), patch.object(teams.time, "sleep"):
            code, report, model, _ = self.run_main(response=lambda *a, **k: Mock(status_code=503))
        self.assertEqual(code, 1)
        self.assertEqual(report["assessment_invalidations"], ["maintained:science.example.gov:research"])
        self.assertEqual(model["opportunities"][0]["review_state"], "needs_revalidation")

    def test_item_corruption_eviction_drift_and_concurrent_writes(self):
        claims = list(teams.eligible_claims(fixture.fixture_registry()).values())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VOYAGE_API_KEY": "synthetic"}), patch.object(
                teams.requests, "post", side_effect=provider_response):
            first = teams.Provider(directory)
            cold = first.embed_claims(claims)
            item = next(path for path in Path(directory).glob("*.json") if isinstance(json.loads(path.read_text()), dict))
            item.write_text("{}", encoding="utf-8")
            recovered = teams.Provider(directory)
            self.assertEqual(recovered.embed_claims(claims), cold)
            self.assertEqual(recovered.counters["invalid_cache_entries"], 1)
            item.unlink()
            self.assertEqual(teams.Provider(directory).embed_claims(claims), cold)
            with ThreadPoolExecutor(max_workers=3) as executor:
                self.assertTrue(all(value == cold for value in executor.map(lambda _: teams.Provider(directory).embed_claims(claims), range(3))))
            with patch.dict(teams.EMBEDDING_CONFIG, {"preprocessing": "changed"}):
                changed = teams.Provider(directory)
                self.assertEqual(changed.embed_claims(claims), cold)
                self.assertEqual(changed.counters["item_vector_misses"], 2)

    def test_nonidentical_live_style_vectors_use_only_a_homogeneous_fresh_run(self):
        def variable(url, json, **kwargs):
            response = provider_response(url, json, **kwargs)
            payload = response.json()
            if "input" in json and json["input"] != teams.EMBEDDING_CANARIES:
                for row in payload["data"]:
                    row["embedding"] = [value + 0.000001 for value in row["embedding"]]
            return Mock(status_code=200, json=lambda: payload)
        code, report, model, _ = self.run_main(response=variable)
        self.assertEqual(code, 0)
        self.assertFalse(report["embedding_reuse_permitted"])
        self.assertEqual(report["counters"]["reused_vector_rows"], 0)
        self.assertEqual(report["counters"]["homogeneous_fallbacks"], 1)
        self.assertEqual(len(model["opportunities"]), 1)
        # New due work sees the persisted policy and cannot reuse that uncertain
        # space, even if the next provider preflight happens to repeat exactly.
        self.add_call()
        code, again, _, _ = self.run_main(response=variable)
        self.assertEqual(code, 0)
        self.assertFalse(again["embedding_reuse_permitted"])
        self.assertEqual(again["counters"]["reused_vector_rows"], 0)
        self.assertEqual(again["counters"]["homogeneous_policy_runs"], 1)
        self.assertGreater(again["counters"]["item_vector_misses"], 0)

    def test_variable_space_still_rejects_cache_mixing_and_gross_discontinuity(self):
        claims = list(teams.eligible_claims(fixture.fixture_registry()).values())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VOYAGE_API_KEY": "synthetic"}):
            with patch.object(teams.requests, "post", side_effect=provider_response):
                teams.Provider(directory).embed_claims(claims)
            current = teams.Provider(directory)
            with patch.object(teams.requests, "post", side_effect=provider_response):
                current.embed_claims(claims)
            self.assertGreater(current.reused_vector_rows, 0)
            def varied(url, json, **kwargs):
                response = provider_response(url, json, **kwargs)
                payload = response.json()
                for row in payload["data"]:
                    row["embedding"] = [value + .000001 for value in row["embedding"]]
                return Mock(status_code=200, json=lambda: payload)
            with patch.object(teams.requests, "post", side_effect=varied), self.assertRaises(teams.ProviderConfigurationError):
                current.embed(["a new uncached scope"], "query")
            self.assertTrue(current.space_policy_path.exists())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VOYAGE_API_KEY": "synthetic"}):
            provider = teams.Provider(directory)
            with patch.object(teams.requests, "post", side_effect=provider_response):
                provider.establish_embedding_space()
            def reversed_space(url, json, **kwargs):
                payload = provider_response(url, json, **kwargs).json()
                for row in payload["data"]:
                    row["embedding"] = [-value for value in row["embedding"]]
                return Mock(status_code=200, json=lambda: payload)
            with patch.object(teams.requests, "post", side_effect=reversed_space), self.assertRaises(teams.ProviderConfigurationError):
                provider.embed_claims(claims)


if __name__ == "__main__":
    unittest.main()
