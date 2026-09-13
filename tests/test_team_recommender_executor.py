import copy
import concurrent.futures
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from tools import team_recommender_executor as e
from tools import team_recommender_budget as budget
from tools.offline_spend import Deferred, ConfigurationFailure, atomic_json, identity


class ExecutorContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"; self.state.mkdir()
        self.settings = e.policy()
        self.person = next(iter(self.settings["profile_claims"]))
        self.claim = self.settings["profile_claims"][self.person][0]
        self.scope = self.settings["development_ids"][0]
        (self.state / "ledger.json").write_bytes((e.CONFIG / "initial-ledger.json").read_bytes())
        self.env = patch.dict(os.environ, {"GITHUB_REPOSITORY": e.REPOSITORY, "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_REF": e.REPOSITORY+"/"+e.WORKFLOW+"@refs/heads/main",
            "GITHUB_SHA": "a"*40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "VOYAGE_API_KEY": "fixture-secret-not-real", "ANTHROPIC_API_KEY": "fixture-secret-not-real"})
        self.env.start(); self.addCleanup(self.env.stop)

    def embedding(self):
        return {"input_role": "document", "rows": [{"id": e.sha(self.claim["text"].encode()), "owner": self.person, "text": self.claim["text"]}]}

    def judge(self):
        original = "Original bounded optical research source fixture."
        return {"scope_id": self.scope, "purpose": "individual",
            "source_evidence": {"scope_id": self.scope, "limitations": "Fixture only; unknown broader restrictions.",
                "passages": [{"id": "s1", "text": original, "url": "https://www.grants.gov/example",
                    "locator": "Synopsis", "sha256": e.sha(original.encode())}]},
            "items": [{"item_id": "i01", "task_type": "individual", "profile_evidence": [
                {"id": "p1", "person_id": self.person, "claim_id": self.claim["claim_id"], "revision": self.claim["revision"],
                 "text": self.claim["text"], "source_url": self.claim["source_urls"][0]}], "candidates": [self.person]}]}

    def packet(self, operation="embeddings"):
        value = {"schema_version": 1, "authorization_id": e.AUTHORIZATION_ID,
            "registry_generation": self.settings["registry_generation"], "operation": operation,
            "requests": [self.embedding() if operation == "embeddings" else self.judge()]}
        path = self.root / "packet.json"; raw = json.dumps(value).encode(); path.write_bytes(raw)
        return path, e.sha(raw), value

    def response(self, payload, status=200):
        class Response:
            status_code = status
            def iter_content(self, size): yield json.dumps(payload).encode()
            def close(self): pass
        return Response()

    def test_protected_manual_environment(self):
        e.trusted_environment()
        for key, bad in [("GITHUB_REF", "refs/heads/feature"), ("GITHUB_EVENT_NAME", "pull_request"),
                         ("GITHUB_WORKFLOW_REF", "other/workflow"), ("GITHUB_REPOSITORY", "other/repo")]:
            with patch.dict(os.environ, {key: bad}), self.assertRaises(ConfigurationFailure):
                e.trusted_environment()

    def test_contextual_dispatch_is_exact_job_only_and_not_a_legacy_route(self):
        job={'release_id':'a'*64,'scope_id':'361207','person_id':'','job_id':'b'*64}
        event={'action':'contextual-team-validation','client_payload':{'contextual_job':json.dumps(job)}}
        path=self.root/'event.json';path.write_text(json.dumps(event))
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'repository_dispatch','GITHUB_EVENT_PATH':str(path)}):
            e.trusted_environment(contextual_job=job)
            with self.assertRaises(ConfigurationFailure):e.trusted_environment()
            for bad in [event|{'action':'researcher-registry-publish'},
                        event|{'client_payload':event['client_payload']|{'packet_commit':'a'*40}},
                        event|{'client_payload':{'contextual_job':job}},
                        event|{'client_payload':{'contextual_job':json.dumps(job|{'scope_id':'other'})}},
                        {'client_payload':{}},[]]:
                path.write_text(json.dumps(bad))
                with self.assertRaises(ConfigurationFailure):e.trusted_environment(contextual_job=job)
            path.write_text(json.dumps(event))
            for key,bad in [('GITHUB_REF','refs/heads/feature'),('GITHUB_REPOSITORY','other/repo'),
                            ('GITHUB_WORKFLOW_REF','other/workflow'),('GITHUB_SHA','bad')]:
                with patch.dict(os.environ,{key:bad}),self.assertRaises(ConfigurationFailure):
                    e.trusted_environment(contextual_job=job)

    def test_packet_cannot_select_code_endpoint_provider_or_stage(self):
        _, _, packet = self.packet()
        e.validate_packet(packet, self.settings)
        for key in ["endpoint", "shell", "model", "stage", "prompt", "import"]:
            bad = copy.deepcopy(packet); bad[key] = "untrusted"
            with self.assertRaises(ValueError): e.validate_packet(bad, self.settings)
        packet["operation"] = "holdout-judge"
        with self.assertRaises(ValueError): e.validate_packet(packet, self.settings)

    def test_profile_snapshot_and_source_allowlist(self):
        r = self.embedding(); r["rows"][0]["text"] = "Private unapproved text"
        r["rows"][0]["id"] = e.sha(r["rows"][0]["text"].encode())
        with self.assertRaises(ValueError): e.embedding_contract(r, self.settings)
        r = self.embedding(); r["input_role"] = "query"; r["rows"][0]["owner"] = "unapproved-scope"
        with self.assertRaises(ValueError): e.embedding_contract(r, self.settings)
        r = self.judge(); r["items"][0]["profile_evidence"][0]["revision"] += 1
        with self.assertRaises(ValueError): e.judge_contract(r, self.settings)
        r = self.judge(); r["scope_id"] = next(s for s in self.settings["preparation_ids"] if s not in self.settings["development_ids"])
        with self.assertRaises(ValueError): e.judge_contract(r, self.settings)

    def test_judge_original_evidence_blinding_and_output_bounds(self):
        r = self.judge(); body, bound, _, _, _ = e.judge_contract(r, self.settings)
        self.assertLessEqual(bound, 12000); self.assertEqual(body["max_tokens"], 512)
        r["items"][0]["algorithm"] = "expected-winner"
        with self.assertRaises(ValueError): e.judge_contract(r, self.settings)
        r = self.judge(); r["items"][0]["explanation"] = "Persuasive argument"
        with self.assertRaises(ValueError): e.judge_contract(r, self.settings)
        r = self.judge(); passage = r["source_evidence"]["passages"][0]
        passage.update(text="x"*12000, sha256=e.sha(("x"*12000).encode()))
        with self.assertRaises(Deferred): e.judge_contract(r, self.settings)

    def test_paid_dispatch_reserves_and_reuses_exact_result(self):
        path, digest, _ = self.packet()
        calls = []
        def post(url, **kwargs):
            ledger = e.ExperimentLedger(self.state/"ledger.json").read()
            self.assertEqual(ledger["requests"][-1]["status"], "reserved_unknown")
            self.assertGreater(ledger["requests"][-1]["charged_microusd"], 0)
            self.assertEqual(url, "https://api.voyageai.com/v1/embeddings")
            self.assertFalse(kwargs["allow_redirects"]); self.assertFalse(kwargs["json"]["truncation"])
            calls.append(url)
            return self.response({"model": "voyage-4-lite", "usage": {"total_tokens": 10},
                "data": [{"index": 0, "embedding": [1.0]+[0.0]*1023}]})
        e.execute(self.state, path, digest, post)
        e.execute(self.state, path, digest, lambda *a, **k: self.fail("cache must not dispatch"))
        ledger = e.ExperimentLedger(self.state/"ledger.json").read()
        self.assertEqual(len(calls), 1); self.assertEqual(len(ledger["requests"]), 1)
        self.assertEqual(ledger["requests"][0]["charged_microusd"], 1)
        self.assertNotIn("fixture-secret", (self.state/"ledger.json").read_text())
        self.assertTrue((self.state/"checkpoint.json").exists())

    def test_compact_judge_disables_default_thinking_and_binds_output_ids(self):
        body, _, _, _, schema = e.judge_contract(self.judge(), self.settings)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["max_tokens"], 512)
        props=schema["properties"]["verdicts"]["items"]["properties"]
        self.assertEqual(props["item_id"]["enum"], ["i01"])
        self.assertEqual(props["evidence_ref"]["enum"], ["p1", "s1"])
        self.assertEqual(set(props["verdict"]["enum"]), e.SCIENCE_LABELS)
        self.assertEqual(schema["properties"]["verdicts"]["minItems"], 1)

    def test_judge_contract_change_never_replays_old_reconciled_or_uncertain_request(self):
        path,digest,packet=self.packet("development-judge")
        key=e.legacy_judge_key(packet["requests"][0],self.settings)
        for status in ("valid", "failed", "reserved_unknown"):
            with self.subTest(status=status):
                (self.state/"ledger.json").write_bytes((e.CONFIG/"initial-ledger.json").read_bytes())
                ledger=e.ExperimentLedger(self.state/"ledger.json")
                token=ledger.reserve_experiment("anthropic",self.settings["judge_model"],2,key,10000,1,trusted_route=True,input_tokens=1000,output_tokens=512)
                if status!="reserved_unknown":ledger.reconcile(token,cost_usd="0.001",usage={"input_tokens":100,"output_tokens":80},status=status)
                for _ in range(3):
                    with self.assertRaisesRegex(Deferred,"requires_recovery_not_replay"):
                        e.execute(self.state,path,digest,lambda *a,**k:self.fail("old logical request replayed"))
                self.assertEqual(len(ledger.read()["requests"]),1)

    def test_compact_judge_exact_success_cache_survives_restoration(self):
        path,digest,_=self.packet("development-judge");calls=[]
        def post(url,**kwargs):
            calls.append(url)
            self.assertEqual(kwargs["json"]["thinking"],{"type":"disabled"})
            return self.response({"model":self.settings["judge_model"],"stop_reason":"end_turn",
                "usage":{"input_tokens":100,"output_tokens":40},"content":[{"type":"text","text":json.dumps({
                    "verdicts":[{"item_id":"i01","verdict":"plausible","evidence_ref":"p1"}],"note":"Fixture only."})}]})
        e.execute(self.state,path,digest,post)
        for _ in range(3):e.execute(self.state,path,digest,lambda *a,**k:self.fail("successful judge cache redispatched"))
        self.assertEqual(len(calls),1)
        self.assertEqual(len(e.ExperimentLedger(self.state/"ledger.json").read()["requests"]),1)

    def test_legacy_recovery_preflights_entire_mixed_packet_before_new_spend(self):
        path,_,packet=self.packet("development-judge")
        old=packet["requests"][0];fresh=copy.deepcopy(old)
        fresh["source_evidence"]["limitations"]="Distinct never-dispatched fixture request."
        for status in ("valid","failed","reserved_unknown"):
            for requests in ([fresh,old],[old,fresh]):
                with self.subTest(status=status,legacy_first=requests[0]==old):
                    (self.state/"ledger.json").write_bytes((e.CONFIG/"initial-ledger.json").read_bytes())
                    ledger=e.ExperimentLedger(self.state/"ledger.json")
                    token=ledger.reserve_experiment("anthropic",self.settings["judge_model"],2,e.legacy_judge_key(old,self.settings),10000,1,trusted_route=True,input_tokens=1000,output_tokens=512)
                    if status!="reserved_unknown":ledger.reconcile(token,cost_usd="0.001",usage={"input_tokens":100,"output_tokens":80},status=status)
                    packet["requests"]=requests;raw=json.dumps(packet).encode();path.write_bytes(raw);before=ledger.read()
                    for _ in range(3):
                        with self.assertRaisesRegex(Deferred,"requires_recovery_not_replay"):
                            e.execute(self.state,path,e.sha(raw),lambda *a,**k:self.fail("fresh request dispatched before recovery preflight"))
                    self.assertEqual(ledger.read(),before)

    def test_unknown_request_remains_reserved_and_is_not_redispatched(self):
        path, digest, _ = self.packet()
        def timeout(*a, **k): raise e.requests.Timeout("fixture")
        with self.assertRaises(e.requests.Timeout): e.execute(self.state, path, digest, timeout)
        row = e.ExperimentLedger(self.state/"ledger.json").read()["requests"][0]
        self.assertEqual(row["status"], "reserved_unknown")
        self.assertEqual(row["charged_microusd"], row["reserved_microusd"])
        with self.assertRaises(Deferred): e.execute(self.state, path, digest, lambda *a, **k: self.fail("uncertain redispatch"))

    def test_completed_usage_without_cache_never_repeats_paid_work(self):
        path, digest, _ = self.packet()
        original_write = e.atomic_json
        def interrupted_cache_write(target, value):
            if target.parent.name == "cache":
                raise OSError("simulated interrupted cache persistence")
            return original_write(target, value)
        payload = {"model": "voyage-4-lite", "usage": {"total_tokens": 10},
                   "data": [{"index": 0, "embedding": [1.0]+[0.0]*1023}]}
        with patch.object(e, "atomic_json", interrupted_cache_write), self.assertRaises(OSError):
            e.execute(self.state, path, digest, lambda *a, **k: self.response(payload))
        before = e.ExperimentLedger(self.state/"ledger.json").read()
        self.assertEqual(before["requests"][0]["status"], "valid")
        self.assertFalse((self.state/"cache").exists())
        self.assertTrue((self.state/"checkpoint.json").exists())
        with self.assertRaisesRegex(Deferred, "cacheless_completed"):
            e.execute(self.state, path, digest, lambda *a, **k: self.fail("completed request redispatched"))
        self.assertEqual(e.ExperimentLedger(self.state/"ledger.json").read(), before)

    def archive(self, state):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for p in state.rglob('*.json'):
                archive.writestr(p.relative_to(state).as_posix(), p.read_bytes())
        return buffer.getvalue()

    def restore_api(self, raw):
        def api(path):
            if path.startswith('actions/artifacts?'):
                return json.dumps({'artifacts': [
                    {'id': 10, 'name': e.PREFIX+'-reservation-123-1', 'expired': False},
                    {'id': 11, 'name': e.PREFIX+'-state-123-1', 'expired': False, 'workflow_run': {'id': 123}}]}).encode()
            if path == 'actions/runs/123':
                return json.dumps({'path': e.WORKFLOW, 'head_branch': 'main', 'event': 'workflow_dispatch'}).encode()
            if path == 'actions/artifacts/11/zip':
                return raw
            self.fail('unexpected restore API')
        return api

    def test_crash_boundaries_and_repeated_workflow_restoration_never_duplicate_dispatch(self):
        class Crash(BaseException): pass
        path, digest, _ = self.packet()
        payload = {'model': 'voyage-4-lite', 'usage': {'total_tokens': 10},
                   'data': [{'index': 0, 'embedding': [1.0]+[0.0]*1023}]}
        scenarios = {
            'valid': ['claim', 'reconcile', 'cache', 'receipt', 'checkpoint'],
            'invalid': ['reconcile', 'terminal', 'receipt', 'checkpoint'],
            'uncertain': ['terminal', 'receipt', 'checkpoint']}
        for outcome, boundaries in scenarios.items():
            for boundary in boundaries:
                for after in (False, True):
                    with self.subTest(outcome=outcome, boundary=boundary, after=after), tempfile.TemporaryDirectory() as temp:
                        state = Path(temp)/'state'; state.mkdir()
                        (state/'ledger.json').write_bytes((e.CONFIG/'initial-ledger.json').read_bytes())
                        e.checkpoint(state)
                        calls, injected = [], []
                        def post(*args, **kwargs):
                            calls.append(1)
                            if outcome == 'uncertain': raise e.requests.Timeout('fixture uncertain transport')
                            response = copy.deepcopy(payload)
                            if outcome == 'invalid': response['data'][0]['embedding'] = [0.0]*1024
                            return self.response(response)
                        def write(target, value):
                            kind = target.parent.name if target.parent.name in ('cache', 'receipts') else target.stem
                            if kind == 'receipts': kind = 'receipt'
                            if kind == 'ledger':
                                row = value['requests'][-1]
                                kind = 'terminal' if row.get('terminal') else 'claim' if row['status']=='reserved_unknown' else 'reconcile'
                            hit = kind == boundary and not injected
                            if hit:
                                injected.append(1)
                                if not after: raise Crash()
                            atomic_json(target, value)
                            if hit: raise Crash()
                        with patch.object(e, 'atomic_json', write), patch.object(budget, 'atomic_json', write):
                            with self.assertRaises(Crash): e.execute(state, path, digest, post)
                        self.assertEqual(len(injected), 1)
                        paid_before_resume = len(calls)
                        raw = self.archive(state)
                        # Restore the latest authoritative artifact three times,
                        # retaining any successful successor checkpoint each time.
                        for repetition in range(3):
                            restored = Path(temp)/('restored'+str(repetition)); restored.mkdir()
                            try:
                                e.restore(restored, self.settings, self.restore_api(raw))
                            except (ValueError, FileNotFoundError):
                                # Interrupted checkpoint sealing is recovery-required.
                                continue
                            try:
                                e.execute(restored, path, digest, post)
                            except (Deferred, ValueError, e.requests.Timeout):
                                pass
                            raw = self.archive(restored)
                        self.assertLessEqual(len(calls), 1)
                        if paid_before_resume:
                            self.assertEqual(len(calls), paid_before_resume)
                        rows = e.ExperimentLedger(state/'ledger.json').read()['requests']
                        if rows:
                            self.assertEqual(len(rows), 1)
                            self.assertGreater(rows[0]['charged_microusd'], 0)

    def test_concurrent_execution_only_one_provider_dispatch(self):
        path, digest, _ = self.packet()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def post(*args, **kwargs):
            calls.append(1); entered.set()
            self.assertTrue(release.wait(10))
            return self.response({'model': 'voyage-4-lite', 'usage': {'total_tokens': 10},
                'data': [{'index': 0, 'embedding': [1.0]+[0.0]*1023}]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(e.execute, self.state, path, digest, post)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(Deferred): e.execute(self.state, path, digest, post)
            finally:
                release.set()
            first.result(timeout=10)
        e.execute(self.state, path, digest, lambda *a, **k: self.fail('cached replay dispatched'))
        self.assertEqual(len(calls), 1)

    def test_corrupt_or_unlinked_cache_requires_recovery_without_dispatch(self):
        path, digest, _ = self.packet()
        e.execute(self.state, path, digest, lambda *a, **k: self.response({
            'model': 'voyage-4-lite', 'usage': {'total_tokens': 10},
            'data': [{'index': 0, 'embedding': [1.0]+[0.0]*1023}]}))
        cache = next((self.state/'cache').glob('*.json'))
        original = json.loads(cache.read_bytes())
        for defect in ('missing_value', 'zero_vector', 'unlinked_request'):
            value = copy.deepcopy(original)
            if defect == 'missing_value': value.pop('value')
            if defect == 'zero_vector': value['value']['rows'][0]['embedding'] = [0.0]*1024
            if defect == 'unlinked_request': value['request_id'] = '0'*32
            atomic_json(cache, value)
            with self.assertRaises((ValueError, Deferred)):
                e.execute(self.state, path, digest, lambda *a, **k: self.fail('invalid cache redispatch'))

    def test_unique_embedding_inventory_has_one_durable_limit(self):
        ledger = e.ExperimentLedger(self.state/"ledger.json")
        state = ledger.read()
        state["requests"].append({"key": "historical", "row_inputs": ["document:"+str(i) for i in range(3840)]})
        atomic_json(ledger.path, state)
        path, digest, _ = self.packet()
        with self.assertRaisesRegex(Deferred, "unique_embedding"):
            e.execute(self.state, path, digest, lambda *a, **k: self.fail("inventory overflow dispatch"))

    def test_bad_model_usage_count_or_vector_never_enters_cache(self):
        for defect in ["model", "shape", "usage", "index"]:
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                state = Path(temp); (state/"ledger.json").write_bytes((e.CONFIG/"initial-ledger.json").read_bytes())
                path, digest, _ = self.packet()
                payload = {"model": "voyage-4-lite", "usage": {"total_tokens": 10},
                    "data": [{"index": 0, "embedding": [1.0]+[0.0]*1023}]}
                if defect == "model": payload["model"] = "other"
                if defect == "shape": payload["data"][0]["embedding"] = [0]
                if defect == "usage": payload["usage"] = {}
                if defect == "index": payload["data"][0]["index"] = 3
                with self.assertRaises((ValueError, Deferred)): e.execute(state, path, digest, lambda *a, **k: self.response(payload))
                self.assertFalse((state/"cache").exists())

    def test_judge_response_exact_aliases_labels_and_references(self):
        r = self.judge(); contract = e.judge_contract(r, self.settings)
        value = {"verdicts": [{"item_id": "i01", "verdict": "plausible", "evidence_ref": "p1"}], "note": ""}
        payload = {"model": "claude-sonnet-5", "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}
        self.assertEqual(e.result_value("development-judge", payload, r, contract, self.settings), value)
        for field, invalid in [("item_id", "i02"), ("verdict", "faithful"), ("evidence_ref", "invented")]:
            bad = copy.deepcopy(value); bad["verdicts"][0][field] = invalid
            payload["content"][0]["text"] = json.dumps(bad)
            with self.assertRaises(ValueError): e.result_value("development-judge", payload, r, contract, self.settings)

    def test_restore_never_resets_missing_latest_state_or_prior_run(self):
        destination = self.root/"restore"
        rows = [{"id": 10, "name": e.PREFIX+"-reservation-12-1", "expired": False}]
        def api(path):
            if path.startswith("actions/artifacts?"): return json.dumps({"artifacts": rows}).encode()
            return json.dumps({"workflow_runs": [{"id": 12}]}).encode()
        with self.assertRaisesRegex(Deferred, "latest_authoritative"): e.restore(destination, self.settings, api)
        rows.clear()
        with self.assertRaisesRegex(Deferred, "prior_run"): e.restore(destination, self.settings, api)

    def test_exact_checkpoint_roundtrip_and_zip_path_rejection(self):
        e.checkpoint(self.state)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for p in self.state.rglob("*.json"): archive.writestr(p.relative_to(self.state).as_posix(), p.read_bytes())
        target = self.root/"restore"; target.mkdir()
        e.unpack_state(buffer.getvalue(), target)
        self.assertEqual((target/"ledger.json").read_bytes(), (self.state/"ledger.json").read_bytes())
        for name in ["../ledger.json", "/ledger.json", "tools/run.py", "cache/x.json"]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive: archive.writestr(name, "{}")
            with self.assertRaises(ValueError): e.unpack_state(buffer.getvalue(), self.root/"bad")

    def test_restore_contextual_dispatch_uses_same_checkpoint_and_rejects_untrusted_runs(self):
        e.checkpoint(self.state);raw=self.archive(self.state);base=self.restore_api(raw)
        for index,event in enumerate(['repository_dispatch','workflow_dispatch','pull_request','push']):
            def api(path):
                if path=='actions/runs/123':
                    return json.dumps({'path':e.WORKFLOW,'head_branch':'main','event':event}).encode()
                return base(path)
            destination=self.root/('restore-event-'+str(index))
            if event in {'repository_dispatch','workflow_dispatch'}:
                e.restore(destination,self.settings,api)
                self.assertEqual((destination/'ledger.json').read_bytes(),(self.state/'ledger.json').read_bytes())
            else:
                with self.assertRaisesRegex(ValueError,'untrusted_checkpoint_run'):e.restore(destination,self.settings,api)

    def test_workflow_only_main_manual_and_scoped_credentials(self):
        import yaml
        flow = yaml.safe_load((e.ROOT/e.WORKFLOW).read_text())
        trigger = flow.get("on", flow.get(True))
        self.assertEqual(set(trigger), {"workflow_dispatch", "repository_dispatch"})
        self.assertEqual(trigger['repository_dispatch'], {'types':['contextual-team-validation']})
        self.assertEqual(flow["permissions"], {"contents": "read", "actions": "read"})
        job = flow["jobs"]["prepare-evaluate"]; self.assertIn("refs/heads/main", job["if"])
        self.assertIn("github.event.action == 'contextual-team-validation'",job['if'])
        self.assertIn('github.event.client_payload.contextual_job',job['env']['CONTEXTUAL_JOB'])
        steps = job["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
        self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")
        self.assertFalse(checkout["with"]["persist-credentials"])
        credential_steps = [s for s in steps if any(k.endswith("_API_KEY") for k in s.get("env", {}))]
        self.assertEqual(len(credential_steps), 4)
        self.assertEqual([s["name"] for s in credential_steps[2:]], ["Execute the bounded contextual scientific job", "Execute the single bounded independent check"])
        for step in credential_steps:
            self.assertNotIn("GH_TOKEN", step["env"]); self.assertIn(" execute", step["run"])


if __name__ == "__main__":
    unittest.main()
