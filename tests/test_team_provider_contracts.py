"""Synthetic provider fixtures; none of these responses enter published inputs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import chdir, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch

import requests

from scripts import build_opportunity_teams as teams
from scripts.researcher_registry import content_hash, load_registry
from tests import test_build_opportunity_teams as fixture_tests


def response(value):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}


class TeamProviderContracts(unittest.TestCase):
    setUp = fixture_tests.ProposedTeamTests.setUp

    def test_decision_flags_and_negative_shapes_are_explicit(self):
        negative = {"specific": False, "objective": "A broad scientific program", "roles": []}
        for flag in (None, "false", "true", 0, 1, [], {}):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                teams.validate_roles(self.scope, negative | {"specific": flag})
        for bad in ({}, {"specific": False}, negative | {"roles": self.roles},
                    negative | {"roles": None}, negative | {"objective": ""},
                    negative | {"suitable_for_team": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                teams.validate_roles(self.scope, bad)
        self.assertEqual(teams.validate_roles(self.scope, negative), [])
        for flag in (None, "true", 1, 0):
            value = copy.deepcopy(self.decomposition)
            value["roles"][0]["required"] = flag
            with self.assertRaises(ValueError):
                teams.validate_roles(self.scope, value)

    def test_verification_negatives_do_not_bypass_edge_validation(self):
        data = {"roles": self.roles, "claims": list(self.claims.values()), "proposed_edges": self.edges}
        for value in ({}, {"suitable_for_team": False}, {"suitable_for_team": False, "edges": self.edges},
                      {"suitable_for_team": "false", "edges": []}, {"suitable_for_team": 0, "edges": []},
                      {"suitable_for_team": True, "edges": None}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                teams.validate_response(teams.VERIFY, data, value)
        self.assertEqual(teams.validate_response(teams.VERIFY, data, {"suitable_for_team": False, "edges": []})["edges"], [])

    def test_unknown_claims_and_coverage_upgrades_never_reach_cache(self):
        for prompt in (teams.ADJUDICATE, teams.VERIFY):
            for altered in ({"claim_id": "unknown"}, {"role_id": "unknown"}, {"claim_id": []}, {"coverage": []}):
                data = {"roles": self.roles, "claims": list(self.claims.values()), "proposed_edges": self.edges}
                value = {"edges": [self.edges[0] | altered]}
                if prompt == teams.VERIFY:
                    value["suitable_for_team"] = True
                with tempfile.TemporaryDirectory() as directory, patch.object(teams.time, "sleep"), self.subTest(prompt=prompt, altered=altered):
                    provider = teams.Provider(directory)
                    with patch.object(provider, "post", return_value=response(value)) as post, self.assertRaises(ValueError):
                        provider.json(prompt, data)
                    self.assertEqual(post.call_count, 3)
                    self.assertEqual(list(Path(directory).iterdir()), [])
        data["proposed_edges"] = [self.edges[0] | {"coverage": "adjacent"}]
        with tempfile.TemporaryDirectory() as directory, patch.object(teams.time, "sleep"):
            provider = teams.Provider(directory)
            with patch.object(provider, "post", return_value=response({"suitable_for_team": True, "edges": self.edges[:1]})), self.assertRaisesRegex(ValueError, "upgrade"):
                provider.json(teams.VERIFY, data)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_poisoned_cache_is_evicted_and_success_is_validated_then_reused(self):
        data = {"scope": self.scope["text"], "record_type": self.scope["record_type"]}
        for poison in ("{", "{}", json.dumps(self.decomposition | {"roles": []})):
            with tempfile.TemporaryDirectory() as directory, self.subTest(poison=poison):
                provider = teams.Provider(directory)
                path = provider.cache / (content_hash([teams.RESPONSE_VERSION, teams.MODEL, teams.DECOMPOSE, data]) + ".json")
                path.write_text(poison, encoding="utf-8")
                with patch.object(provider, "post", return_value=response(self.decomposition)) as post:
                    self.assertEqual(provider.json(teams.DECOMPOSE, data), self.decomposition)
                    self.assertEqual(provider.json(teams.DECOMPOSE, data), self.decomposition)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(provider.counters["invalid_cache_entries"], 1)
                self.assertEqual(provider.counters["cache_hits"], 1)
                self.assertEqual(json.loads(path.read_text()), self.decomposition)

    def test_invalid_output_retries_are_bounded_and_never_admit_a_negative(self):
        data = {"scope": self.scope["text"], "record_type": self.scope["record_type"]}
        invalid_quote = copy.deepcopy(self.decomposition)
        invalid_quote["roles"][0]["quote"] = "Invented unsupported scientific requirement."
        for payload in (response({}), response(invalid_quote), {"stop_reason": "max_tokens"},
                        {"stop_reason": "end_turn", "content": [{"type": "text", "text": "{"}]},
                        {"stop_reason": "end_turn", "content": None}, []):
            with tempfile.TemporaryDirectory() as directory, patch.object(teams.time, "sleep") as sleep, self.subTest(payload=payload):
                provider = teams.Provider(directory)
                with patch.object(provider, "post", return_value=payload) as post, self.assertRaises(ValueError):
                    provider.json(teams.DECOMPOSE, data)
                self.assertEqual(post.call_count, 3)
                self.assertEqual(provider.counters["invalid_outputs"], 3)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_valid_scientific_negative_is_cached_and_revalidated(self):
        data = {"scope": self.scope["text"], "record_type": self.scope["record_type"]}
        negative = {"specific": False, "objective": "A broad scientific program", "roles": []}
        with tempfile.TemporaryDirectory() as directory:
            provider = teams.Provider(directory)
            with patch.object(provider, "post", return_value=response(negative)) as post:
                for _ in range(2):
                    result, proposal = teams.generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
                    self.assertEqual(result["state"], "not_specific")
                    self.assertIsNone(proposal)
            self.assertEqual(post.call_count, 1)
            with patch.object(teams, "validate_response", side_effect=ValueError("contract changed")), patch.object(teams.time, "sleep"), patch.object(provider, "post", return_value=response(negative)), self.assertRaises(ValueError):
                provider.json(teams.DECOMPOSE, data)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_timeouts_count_actual_network_attempts_and_do_not_leak_messages(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-key"}), patch.object(teams.time, "sleep"):
            provider = teams.Provider(directory)
            with patch.object(teams.requests, "post", side_effect=requests.Timeout("private request text must not appear")) as post:
                result, proposal = teams.generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
            self.assertEqual((provider.calls, provider.counters["failed_requests"], post.call_count), (3, 3, 3))
            self.assertEqual(provider.counters["retries"], 2)
            self.assertEqual(result["state"], "unavailable")
            self.assertNotIn("private", json.dumps(result))
            self.assertIsNone(proposal)

    def test_authentication_failure_is_not_retried_by_current_or_later_scopes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-key"}), patch.object(teams.time, "sleep") as sleep:
            provider = teams.Provider(directory)
            with patch.object(teams.requests, "post", return_value=Mock(status_code=401)) as post:
                for _ in range(2):
                    result, _ = teams.generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
                    self.assertEqual(result["state"], "unavailable")
            self.assertEqual((post.call_count, provider.calls), (1, 1))
            sleep.assert_not_called()

    def test_request_budget_counts_retries_and_stops_before_an_extra_call(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-key"}), patch.object(teams.time, "sleep"):
            provider = teams.Provider(directory, max_requests=2)
            with patch.object(teams.requests, "post", side_effect=requests.Timeout) as post:
                result, _ = teams.generate_scope(self.scope, provider, self.claims, [], "registry", float("inf"))
            self.assertEqual(post.call_count, 2)
            self.assertEqual(result["state"], "deferred")
            self.assertEqual(result["reason_code"], "budget_exhausted")

    def test_concurrent_cache_writes_only_publish_complete_values(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = teams.Provider(directory)
            path = provider.cache / "shared.json"
            values = [{"worker": i, "payload": [i] * 2000} for i in range(20)]
            def write(value):
                provider.write_cache(path, value)
                actual = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn(actual, values)
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(write, values))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_embedding_cache_corruption_and_failed_calls_recover(self):
        vector = [1.0] + [0.0] * 1023
        with tempfile.TemporaryDirectory() as directory, patch.object(teams.time, "sleep"):
            provider = teams.Provider(directory)
            path = provider.cache / (content_hash(["voyage-4-lite", 1024, "document", ["Synthetic claim"]]) + ".vectors.json")
            path.write_text("[[false]]", encoding="utf-8")
            with patch.object(provider, "post", side_effect=[requests.Timeout(), {"model": "voyage-4-lite", "data": [{"index": 0, "embedding": vector}]}]) as post:
                self.assertEqual(provider.embed(["Synthetic claim"], "document"), [vector])
                self.assertEqual(provider.embed(["Synthetic claim"], "document"), [vector])
            self.assertEqual(post.call_count, 2)
            self.assertEqual(provider.counters["invalid_cache_entries"], 1)

    def test_cooldowns_are_not_completed_decisions_and_changes_are_immediately_due(self):
        receipt = {"key": "input", "state": "rejected_evidence", "response_contract": teams.RESPONSE_VERSION, "retry_after": 200}
        self.assertFalse(teams.attempt_completed(receipt, "input"))
        self.assertFalse(teams.attempt_due(receipt, "input", 100))
        self.assertTrue(teams.attempt_due(receipt, "input", 200))
        self.assertTrue(teams.attempt_due(receipt, "amended", 100))
        for corrupt in (None, "forever", float("nan"), float("inf")):
            self.assertTrue(teams.attempt_due(receipt | {"retry_after": corrupt}, "input", 100))

    def test_initialization_failure_replaces_a_stale_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            path = Path("receipt.json")
            path.write_text('{"status":"completed","run_id":"old"}', encoding="utf-8")
            with patch("sys.argv", ["teams", "--generate", "--report", str(path)]), patch.object(teams, "load_registry", side_effect=ValueError("invalid registry")), self.assertRaises(ValueError):
                teams.main()
            report = json.loads(path.read_text())
            self.assertEqual(report["status"], "starting")
            self.assertNotEqual(report["run_id"], "old")
            self.assertTrue(report["generation_requested"])

    def test_workflow_summary_cannot_report_another_invocation_as_success(self):
        workflow = Path(".github/workflows/refresh-opportunities.yml").read_text(encoding="utf-8")
        block = workflow.split("- name: Report automatic team coverage and remaining work", 1)[1]
        code = textwrap.dedent(block.split("python - <<'PY'\n", 1)[1].split("          PY", 1)[0])
        current = {"run_id": "fixture-run", "run_attempt": "2", "generation_requested": True,
                   "status": "completed", "coverage_after": {"parent_calls": 999}, "assessed_scopes": 3}
        invalid = ["{", "[]", json.dumps(current | {"run_id": "previous"}),
                   json.dumps(current | {"run_attempt": "1"}), json.dumps(current | {"status": "starting"}),
                   json.dumps(current | {"generation_requested": False})]
        for receipt in [*invalid, json.dumps(current)]:
            with tempfile.TemporaryDirectory() as directory, chdir(directory), self.subTest(receipt=receipt):
                Path("evaluation").mkdir()
                Path("evaluation/opportunity_team_generation.json").write_text(receipt, encoding="utf-8")
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "fixture-run", "GITHUB_RUN_ATTEMPT": "2",
                                             "GITHUB_STEP_SUMMARY": "summary.md", "TEAM_GENERATION_OUTCOME": "failure"}):
                    exec(compile(code, "workflow-summary", "exec"), {})
                summary = Path("summary.md").read_text(encoding="utf-8")
                self.assertEqual("999" in summary, receipt not in invalid)
                self.assertEqual("missing_current_run_receipt" in summary, receipt in invalid)

    def test_cache_dependencies_include_claim_ownership_revision_and_evidence(self):
        payload = {"roles": self.roles, "claims": list(self.claims.values())}
        with tempfile.TemporaryDirectory() as directory:
            provider = teams.Provider(directory)
            with patch.object(provider, "post", return_value=response({"edges": []})) as post:
                provider.json(teams.ADJUDICATE, payload)
                provider.json(teams.ADJUDICATE, payload)
                for field, value in (("revision", 2), ("researcher_id", "corrected-owner"),
                                     ("material_hash", "amended"), ("evidence", "Corrected synthetic evidence")):
                    amended = copy.deepcopy(payload)
                    amended["claims"][0][field] = value
                    provider.json(teams.ADJUDICATE, amended)
            self.assertEqual(post.call_count, 5)

    def test_outage_persists_source_and_researcher_withholding_and_preserves_compatible_team(self):
        registry = load_registry()
        model = json.loads(Path("config/opportunity_team_model.json").read_text(encoding="utf-8"))
        baseline_scopes = teams.scopes()
        baseline = teams.source_fingerprints(model, baseline_scopes)
        healthy = [r for r in model["opportunities"] if r.get("review_state") != "needs_revalidation" and r.get("generator_version") and r["id"] in baseline]
        source = healthy[0]
        changed = next(r for r in healthy[1:] if r["members"][0]["faculty_id"] not in {m["faculty_id"] for m in source["members"]})
        person_id = changed["members"][0]["faculty_id"]
        retained = next(r for r in healthy[1:] if r["id"] != changed["id"] and person_id not in
                        {ref["researcher_id"] for role in r["roles"] for ref in role["claim_refs"]})
        originals = {r["id"]: copy.deepcopy(r) for r in (source, changed, retained)}
        model["opportunities"] = list(originals.values())
        person = next(p for p in registry["researchers"] if p["researcher_id"] == person_id)
        person["status"] = "inactive"
        baseline[source["id"]] = "amended-source"
        candidates = [s for s in baseline_scopes if s["id"] in originals]
        with tempfile.TemporaryDirectory() as directory, chdir(directory), redirect_stdout(io.StringIO()):
            Path("config").mkdir()
            Path("config/opportunity_team_model.json").write_text(json.dumps(model), encoding="utf-8")
            with patch("sys.argv", ["teams", "--generate", "--write"]), patch.object(teams, "load_registry", return_value=registry), patch.object(teams, "scopes", return_value=candidates), patch.object(teams, "source_fingerprints", return_value=baseline), patch.object(teams.Provider, "embed", side_effect=teams.ProviderUnavailable("synthetic outage")), patch.object(teams, "update_version_target"), patch.object(teams, "write_outputs") as write:
                self.assertEqual(teams.main(), 1)
            published = {r["id"]: r for r in write.call_args.args[0]["opportunities"]}
            self.assertEqual(published[source["id"]]["review_state"], "needs_revalidation")
            self.assertEqual(published[changed["id"]]["review_state"], "needs_revalidation")
            self.assertEqual(published[retained["id"]]["review_state"], originals[retained["id"]]["review_state"])
            self.assertEqual(published[retained["id"]]["members"], originals[retained["id"]]["members"])
            receipt = json.loads(Path("evaluation/opportunity_team_generation.json").read_text())
            self.assertEqual(receipt["processing_failure"]["reason_code"], "provider_unavailable")
            self.assertGreater(receipt["pending_after"], 0)
            self.assertEqual(receipt["assessed_scopes"], 0)


if __name__ == "__main__":
    unittest.main()
