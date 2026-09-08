"""Reachable request, budget, retry, evidence and replay boundaries; no network."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import offline_ai as a
from tools.offline_team_contract import schemas
from tools import evaluate_offline_ai as e
from tools import offline_ai_checkpoint as checkpoint


def valid(value):
    if value != {"ready": True}:
        raise ValueError("bad shape")
    return value


def response(value=None, **extra):
    payload = {"model": "gpt-5.6-luna", "status": "completed",
        "usage": {"input_tokens": 80, "input_tokens_details": {"cached_tokens": 30},
                  "output_tokens": 40, "output_tokens_details": {"reasoning_tokens": 20}},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value or {"ready": True})}]}]}
    return Mock(status_code=200, json=Mock(return_value=payload | extra))


class OfflineAIContracts(unittest.TestCase):
    def test_complete_responses_contract_and_usage_before_parse(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY="test-only"):
            ledger = a.Ledger(Path(tmp) / "ledger.json", "test", 1)
            post = Mock(return_value=response({"not_ready": True}))
            client = a.Client(ledger, Path(tmp) / "cache", post=post)
            with self.assertRaises(ValueError):
                client.json(a.config()["routes"]["luna"], "preflight", "stable", {"ready": True}, schemas()["preflight"], valid)
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["reasoning"], {"effort": "low"})
            self.assertFalse(body["store"])
            self.assertEqual(body["text"]["verbosity"], "low")
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
            entry = ledger.read()["requests"][0]
            self.assertEqual(entry["usage"]["output_tokens"], 40)
            self.assertEqual(entry["status"], "ValueError")
            self.assertLess(entry["charged_microusd"], entry["reserved_microusd"])
            self.assertNotIn("test-only", ledger.path.read_text())

    def test_cache_warm_replay_and_concurrent_duplicate_suppression(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY="test-only"):
            ledger = a.Ledger(Path(tmp) / "ledger.json", "test", 1)
            post = Mock(return_value=response())
            client = a.Client(ledger, Path(tmp) / "cache", post=post)
            def request(_):
                return client.json(a.config()["routes"]["luna"], "preflight", "stable", {}, schemas()["preflight"], valid)
            with ThreadPoolExecutor(max_workers=3) as executor:
                self.assertEqual(list(executor.map(request, range(3))), [{"ready": True}] * 3)
            self.assertEqual(post.call_count, 1)
            post.side_effect = AssertionError("warm replay may not call provider")
            self.assertEqual(request(None), {"ready": True})
            self.assertEqual(len(ledger.read()["requests"]), 1)

    def test_atomic_reservations_and_logical_rerun_never_reset_allowance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = a.Ledger(path, "same-logical-run", 1)
            def reserve(_):
                try:
                    return ledger.reserve("openai", "gpt-5.6-luna", "verification", "x", 600000, 1)
                except a.Deferred:
                    return None
            with ThreadPoolExecutor(max_workers=3) as executor:
                self.assertEqual(sum(bool(r) for r in executor.map(reserve, range(3))), 1)
            restored = a.Ledger(path, "same-logical-run", 1)
            with self.assertRaises(a.Deferred):
                restored.reserve("openai", "gpt-5.6-luna", "verification", "y", 600000, 1)
            with self.assertRaises(ValueError):
                a.Ledger(path, "different-run", 1)

    def test_normalized_usage_does_not_double_count_cached_or_reasoning(self):
        openai = a.normalize_usage("openai", response().json())
        self.assertEqual(a.cost_microusd(openai, a.config()["prices_per_million"]["gpt-5.6-luna"]), 59)
        anthropic = a.normalize_usage("anthropic", {"usage": {"input_tokens": 10,
            "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30, "output_tokens": 40}})
        self.assertEqual(anthropic["input_tokens"], 60)
        self.assertEqual(a.cost_microusd(anthropic, a.config()["prices_per_million"]["claude-sonnet-5"]), 499)
        self.assertIsNone(a.normalize_usage("openai", {}))
        self.assertIsNone(a.normalize_usage("openai", {"usage": {"input_tokens": True, "output_tokens": 0}}))

    def test_configuration_and_refusal_are_not_retried_or_scientific_negative(self):
        for reply, error in [(Mock(status_code=401), a.ConfigurationFailure),
            (response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]), a.Refusal)]:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY="test-only"):
                ledger = a.Ledger(Path(tmp) / "ledger.json", "test", 1)
                post = Mock(return_value=reply)
                client = a.Client(ledger, Path(tmp) / "cache", post=post)
                with self.assertRaises(error):
                    client.json(a.config()["routes"]["luna"], "decomposition", "stable", {}, schemas()["preflight"], valid)
                self.assertEqual(post.call_count, 1)
                if error is a.Refusal:
                    self.assertEqual(len(list((Path(tmp) / "cache").glob("*.json"))), 1)
                    with self.assertRaises(a.Refusal):
                        client.json(a.config()["routes"]["luna"], "decomposition", "stable", {}, schemas()["preflight"], valid)
                    self.assertEqual(post.call_count, 1)
                else:
                    self.assertFalse(list((Path(tmp) / "cache").glob("*.json")))

    def test_frozen_population_and_holdouts_precede_model_results(self):
        frozen = json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())
        self.assertEqual(len(frozen["cases"]), 24)
        self.assertEqual(sum(c["holdout"] for c in frozen["cases"]), 6)
        self.assertEqual(len({c["scope"]["id"] for c in frozen["cases"]}), 24)
        self.assertTrue(frozen["acceptance"]["manual_source_annotation_review_required"])
        self.assertEqual(a.config()["production_route"], "sonnet")

    def test_cov4_runs_actual_ownership_and_zero_call_bypass(self):
        class FakeClient:
            def json(self, route, stage, prompt, data, schema, validate):
                return validate({"owned": "yes", "fundable": "no", "reason": "fixture"})
        with tempfile.TemporaryDirectory() as tmp:
            report = e.cov4(FakeClient(), Path(tmp))
            self.assertEqual(report["candidates_offered"], 43)
            self.assertEqual(report["bypass_classifier_calls"], 0)
            self.assertEqual(report["contaminants_published"], 0)
            self.assertGreater(report["genuine_children_lost"], 0)

    def test_missing_checkpoint_and_auth_failure_never_reset_spend(self):
        env = {"GITHUB_RUN_ID": "20", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env):
            for artifacts in ([{"id": 1, "name": checkpoint.PREFIX + "-reservation-10-1"}], []):
                def api(repo, path):
                    return json.dumps({"artifacts": artifacts} if "artifacts?" in path else
                                      {"workflow_runs": [{"id": 10}]}).encode()
                with patch.object(checkpoint, "api", side_effect=api), self.assertRaises(ValueError):
                    checkpoint.prepare("owner/repo", Path(tmp) / "state", Path(tmp) / "reservation.json")
                self.assertFalse((Path(tmp) / "reservation.json").exists())
            with patch.object(checkpoint, "api", side_effect=PermissionError("denied")), self.assertRaises(PermissionError):
                checkpoint.prepare("owner/repo", Path(tmp) / "state", Path(tmp) / "reservation.json")

    def test_unknown_usage_retains_full_reservation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY="test-only"):
            ledger = a.Ledger(Path(tmp) / "ledger.json", "test", 1)
            client = a.Client(ledger, Path(tmp) / "cache", post=Mock(return_value=response(usage=None)))
            e.preflight(client)
            row = ledger.read()["requests"][0]
            self.assertIsNone(row["usage"])
            self.assertEqual(row["reserved_microusd"], row["charged_microusd"])

    def test_added_actions_credential_resumes_only_missing_openai_stop_with_spend_intact(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY='synthetic'):
            ledger = a.Ledger(Path(tmp) / 'ledger.json', 'test', 1)
            ledger.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'retained', 88875, 1)
            ledger.block('anthropic', 'insufficient_credit')
            ledger.block('openai', 'missing_actions_step_credential')
            before = ledger.read()
            e.resume_preflight_credential(ledger)
            e.resume_preflight_credential(ledger)
            after = ledger.read()
            self.assertEqual(after['requests'], before['requests'])
            self.assertEqual(after['limit_microusd'], before['limit_microusd'])
            self.assertEqual(after['blocked_providers'], {'anthropic': 'insufficient_credit'})
            self.assertEqual(len(after['events']), 1)
            post = Mock(return_value=response())
            self.assertEqual(e.preflight(a.Client(ledger, Path(tmp) / 'cache', post=post)), {'ready': True})
            self.assertEqual(post.call_count, 1)
            self.assertEqual(ledger.read()['requests'][0], before['requests'][0])

    def test_preflight_does_not_clear_missing_or_denied_credentials(self):
        for key, reason in (('', 'missing_actions_step_credential'), ('synthetic', 'openai_configuration_http_401'),
                            ('synthetic', 'openai_configuration_http_403')):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY=key):
                ledger = a.Ledger(Path(tmp) / 'ledger.json', 'test', 1)
                ledger.block('openai', reason)
                ledger.block('anthropic', 'insufficient_credit')
                before = ledger.read()
                e.resume_preflight_credential(ledger)
                self.assertEqual(ledger.read(), before)

    def test_preflight_entrypoint_preserves_failed_marker_history_and_tests_new_key_once(self):
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY='synthetic'):
            state = Path(tmp)
            ledger = a.Ledger(state / 'ledger.json', e.TASK, a.config()['budgets_usd']['evaluation'], a.config()['max_requests'])
            ledger.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'retained', 88875, 1)
            ledger.block('anthropic', 'insufficient_credit')
            ledger.block('openai', 'missing_actions_step_credential')
            previous_request = ledger.read()['requests'][0]
            failed = {'complete': True, 'evaluation_contract': 'historical-contract',
                'result': {'phase': 'preflight', 'status': 'unavailable_or_invalid', 'error_type': 'ConfigurationFailure'}}
            a.atomic_json(state / 'preflight-completed.json', failed)
            with patch('sys.argv', ['evaluate', 'preflight', '--state', str(state)]), \
                    patch.object(e.requests, 'post', return_value=response()) as post, redirect_stdout(io.StringIO()):
                e.main()
                e.main()
            self.assertEqual(post.call_count, 1)
            self.assertEqual(json.loads(next((state / 'history').glob('preflight-*.json')).read_bytes()), failed)
            self.assertEqual(json.loads((state / 'preflight-completed.json').read_bytes())['result']['status'], 'supported')
            self.assertEqual(ledger.read()['requests'][0], previous_request)
            self.assertEqual(ledger.read()['blocked_providers'], {'anthropic': 'insufficient_credit'})
            self.assertFalse(e.phase_complete('preflight', failed['result']))

    def test_cov4_checkpoint_covers_prompt_population_and_frozen_manifest(self):
        from scripts import subtopic_cov4 as gate
        from tools import run_cov4_ownership
        original = e.evaluation_contract("cov4")
        team_original = e.evaluation_contract("teams-luna")
        with patch.object(gate, "PROMPT", gate.PROMPT + "\nchanged"):
            self.assertNotEqual(original, e.evaluation_contract("cov4"))
            self.assertEqual(team_original, e.evaluation_contract("teams-luna"))
        cases = run_cov4_ownership.load_candidates()
        with patch.object(run_cov4_ownership, "load_candidates", return_value=cases[:-1]):
            self.assertNotEqual(original, e.evaluation_contract("cov4"))
            self.assertEqual(team_original, e.evaluation_contract("teams-luna"))
        read = Path.read_bytes
        def changed(path):
            value = read(path)
            if path.name == "offline_cov4_frozen.json":
                return json.dumps(json.loads(value) | {"version": "new"}).encode()
            return value
        with patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(original, e.evaluation_contract("cov4"))
            self.assertEqual(team_original, e.evaluation_contract("teams-luna"))
        def altered_adapter(client, destination):
            return {"changed_output_translation": True}
        with patch.object(e, "cov4", altered_adapter):
            self.assertNotEqual(original, e.evaluation_contract("cov4"))
            self.assertEqual(team_original, e.evaluation_contract("teams-luna"))
        def altered_request(self, *args, **kwargs):
            return {"changed_response_validation": True}
        with patch.object(a.Client, "json", altered_request):
            self.assertNotEqual(original, e.evaluation_contract("cov4"))
            self.assertNotEqual(team_original, e.evaluation_contract("teams-luna"))

    def test_cov4_resume_reuses_refusals_without_another_request(self):
        refused = response(output=[{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY="test-only"):
            ledger = a.Ledger(Path(tmp) / "ledger.json", "test", 1)
            post = Mock(return_value=refused)
            client = a.Client(ledger, Path(tmp) / "cache", post=post)
            first = e.cov4(client, Path(tmp))
            count = post.call_count
            self.assertGreater(count, 0)
            second = e.cov4(client, Path(tmp))
            self.assertEqual(post.call_count, count)
            self.assertFalse(e.phase_complete("cov4", first))
            self.assertFalse(e.phase_complete("cov4", second))

    def test_changed_bypass_fixture_invalidates_cov4_but_keeps_team_evidence(self):
        from tools import run_cov4_validation as harness
        cov4_before = e.evaluation_contract("cov4")
        team_before = e.evaluation_contract("teams-luna")
        inputs_before = harness.bypassed_records()
        original_read = Path.read_text
        for suffix, text in (("roses/table3.html", "TROPICS"), ("army_tdac/topics.html", "Assistive Automation")):
            def changed(path, *args, **kwargs):
                value = original_read(path, *args, **kwargs)
                return value.replace(text, "Changed " + text) if path.as_posix().endswith(suffix) else value
            with self.subTest(fixture=suffix), patch.object(Path, "read_text", changed):
                self.assertNotEqual(inputs_before, harness.bypassed_records())
                self.assertNotEqual(cov4_before, e.evaluation_contract("cov4"))
                self.assertEqual(team_before, e.evaluation_contract("teams-luna"))

    def test_nonterminal_phase_resumes_only_incomplete_case_and_retains_refusal(self):
        frozen = json.loads(Path("evaluation/offline_team_frozen.json").read_bytes())
        deferred_id = frozen["cases"][0]["scope"]["id"]
        calls = []
        def assess(client, route, case):
            key = case["scope"]["id"]
            calls.append(key)
            return {"scope_id": key, "state": "deferred" if key == deferred_id and calls.count(key) == 1 else "not_specific"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, "team_case", side_effect=assess), patch.object(e, "evaluation_contract", return_value="fixture-contract"):
            first = e.teams(None, Path(tmp), "luna")
            self.assertFalse(e.phase_complete("teams-luna", first))
            second = e.teams(None, Path(tmp), "luna")
            self.assertTrue(e.phase_complete("teams-luna", second))
            self.assertEqual(len(calls), 25)
            self.assertEqual(calls.count(deferred_id), 2)
        with tempfile.TemporaryDirectory() as tmp, patch.object(e, "team_case", return_value={"state": "provider_refusal"}) as assess, patch.object(e, "evaluation_contract", return_value="fixture-contract"):
            for _ in range(2):
                e.load_or_assess(None, Path(tmp), "luna", frozen["cases"][0])
            self.assertEqual(assess.call_count, 1)
        self.assertFalse(e.phase_complete("cov4", {"api_errors": {"timeout": 1}}))


if __name__ == "__main__":
    unittest.main()
