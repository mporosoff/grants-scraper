"""Portable accounting fixtures; no paid or native provider calls."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import zipfile

from tools import contextual_team_completion_policy as policy
from tools import contextual_team_token_preflight as tokens
from tools import team_recommender_executor as executor
from tools.contextual_team_executor import RecoveryRequired
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred
from tools.team_recommender_budget import ExperimentLedger


class CompletionBudget(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)/'state'; self.state.mkdir()
        self.bind(patch('socket.socket.connect', side_effect=AssertionError('no_live_provider')))
        self.bind(patch.dict(os.environ, {'GITHUB_RUN_ID': '999', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_SHA': 'a'*40, 'ANTHROPIC_API_KEY': 'fixture-only'}))
        fixture = Path(__file__).parent/'fixtures/completion-check-evidence'
        state = ExperimentLedger(self.state/'ledger.json', initialize=True).read()
        state['requests'] = [{'id': f'{i:032x}', 'key': f'{i:064x}', 'provider': 'anthropic',
            'stage': 2, 'status': 'valid', 'charged_microusd': 0} for i in range(687)]
        state['requests'][0]['charged_microusd'] = 7346880
        for i, rid, amount in ((682, 'fc618603458249348c6834d258264520', 146074),
            (684, 'd24a0654d72e486793519bead019b064', 205254),
            (685, '6a6e93add95848dcb02f9ccaf158a2eb', 263282)):
            state['requests'][i].update(id=rid, status='reserved_unknown', usage=None, charged_microusd=amount)
        state['requests'][-1] = json.loads((fixture/'request.json').read_bytes())
        state['events'] = [{'kind': 'preserved_history', 'sequence': i} for i in range(19)]
        atomic_json(self.state/'ledger.json', state)
        for folder in ('receipts', 'diagnostics'):
            (self.state/folder).mkdir()
            shutil.copyfile(fixture/(folder+'.json'), self.state/folder/(policy.FAILED+'.json'))
        self.counts = json.loads((fixture/'native-counts.json').read_bytes())['rows']
        executor.checkpoint(self.state, token_preflight={'version': tokens.VERSION,
            'source_sha256': tokens.SOURCE_SHA, 'rows': self.counts})
        self.original = copy.deepcopy(state)
        self.p = policy.plan(); start = self.p['starting_checkpoint']
        start.update(requests_sha256=identity(state['requests']), events_sha256=identity(state['events']),
            ledger_sha256=executor.sha((self.state/'ledger.json').read_bytes()),
            checkpoint_sha256=executor.sha((self.state/'checkpoint.json').read_bytes()))
        self.bind(patch.object(policy, 'plan', return_value=self.p))
        self.active = []; self.terminal = 'completed'; self.native_calls = 0

    def bind(self, p):
        result = p.start(); self.addCleanup(p.stop); return result

    def api(self, path):
        return encoded({'workflow_runs': self.active} if '?status=' in path else
            self.p['terminal_run'] | {'status': self.terminal})

    def install(self):
        return policy.install_authority(self.state, self.api)

    def restored(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for p in self.state.rglob('*.json'):
                archive.write(p, p.relative_to(self.state).as_posix())
        destination = self.state.parent/(self.state.name+'-restored')
        executor.unpack_state(raw.getvalue(), destination)
        self.state = destination

    def test_exact_amendment_preserves_history_holds_and_idempotent_restore(self):
        old = ExperimentLedger(self.state/'ledger.json')
        self.assertEqual((old.limit, old.max_requests), (10000000, 690))
        for _ in range(3):
            ledger = self.install(); state = ledger.read()
            self.assertEqual(state['requests'], self.original['requests'])
            self.assertEqual(state['events'][:19], self.original['events'])
            self.assertEqual(state['events'][19:], policy.events())
            self.assertEqual(sum(r['charged_microusd'] for r in state['requests']), 8161490)
            self.assertEqual((ledger.limit, ledger.max_requests), (60000000, 1290))
            self.restored()
        self.assertEqual(len(json.loads((self.state/'checkpoint.json').read_bytes())['phase2_token_preflight']['rows']), 188)

    def test_wrong_checkpoint_history_or_terminal_owner_cannot_amend(self):
        self.active = [{'id': 1000}]
        with self.assertRaises(RecoveryRequired): self.install()
        self.active = []; self.terminal = 'in_progress'
        with self.assertRaises(RecoveryRequired): self.install()
        self.terminal = 'completed'
        (self.state/'receipts'/(policy.FAILED+'.json')).write_text('{}')
        with self.assertRaises(ConfigurationFailure): self.install()
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read(), self.original)

    def test_each_historical_row_event_and_native_prefix_is_bound(self):
        self.install(); valid = ExperimentLedger(self.state/'ledger.json').read()
        for collection, index, key in (('requests', 0, 'charged_microusd'), ('events', 0, 'sequence')):
            changed = copy.deepcopy(valid); changed[collection][index][key] += 1
            with self.assertRaises(ConfigurationFailure): policy.history(changed)
        saved = {'rows': copy.deepcopy(self.counts)}; saved['rows'][0]['input_tokens'] += 1
        with self.assertRaises(ConfigurationFailure):
            policy.check_count_budget(valid, saved, {'id': 'cb-fc-check'})

    def test_partial_or_unrecorded_cap_change_fails_closed(self):
        for amended in (False, True):
            state = copy.deepcopy(self.original)
            if amended: state['events'].extend(policy.events())
            for caps in ((60000000, 690), (10000000, 1290), (60000000, 1290) if not amended else (10000000, 690)):
                state.update(limit_microusd=caps[0], max_requests=caps[1]); atomic_json(self.state/'ledger.json', state)
                with self.assertRaises((ValueError, ConfigurationFailure)):
                    ExperimentLedger(self.state/'ledger.json')

    def test_pooled_limits_preserve_contingency_not_iteration_micro_budget(self):
        state = self.install().read()
        policy.check_pool(state, 6000000, 1)  # Iteration allocation is a guide.
        policy.check_pool(state, 45000000, 600)
        with self.assertRaises(Deferred): policy.check_pool(state, 45000001, 1)
        with self.assertRaises(Deferred): policy.check_pool(state, 1, 601)
        changed = copy.deepcopy(state)
        changed['requests'].append({'charged_microusd': 44000000, 'purpose': 'unrelated'})
        policy.check_pool(changed, 1000000, 1)
        with self.assertRaises(Deferred): policy.check_pool(changed, 1000001, 1)
        # Lifetime and historical reserves independently constrain the pool.
        for dimension, value in (('microusd', 10000000), ('attempts', 690)):
            with self.subTest(dimension=dimension):
                p = copy.deepcopy(self.p); p['lifetime'][dimension] = value
                with patch.object(policy, 'plan', return_value=p):
                    changed = copy.deepcopy(state); changed['events'][19:] = policy.events()
                    changed.update(limit_microusd=p['lifetime']['microusd'], max_requests=p['lifetime']['attempts'])
                    with self.assertRaises(Deferred): policy.check_pool(changed, 2000000, 2)

    def test_native_lifetime_incremental_limits_and_uncertain_rows_count(self):
        state = self.install().read(); saved = {'rows': copy.deepcopy(self.counts)}
        for i in range(299): saved['rows'].append({'id': 'cb-fc-'+str(i), 'status': 'dispatched_or_uncertain'})
        policy.check_count_budget(state, saved, {'id': 'cb-fc-check'})
        saved['rows'].append({'id': 'cb-fc-last', 'status': 'complete'})
        with self.assertRaises(Deferred): policy.check_count_budget(state, saved, {'id': 'cb-fc-check'})
        with self.assertRaises(ConfigurationFailure): policy.check_count_budget(state, {'rows': self.counts}, {'id': 'legacy'})
        p = copy.deepcopy(self.p); p['lifetime']['native_counts'] = 188
        with patch.object(policy, 'plan', return_value=p):
            state['events'][19:] = policy.events()
            with self.assertRaises(Deferred):
                policy.check_count_budget(state, {'rows': self.counts}, {'id': 'cb-fc-check'})

    def test_native_amendment_required_and_old_routes_keep_original_ceiling(self):
        item = {'id': 'cb-fc-check', 'body': tokens.count_body('fixture text')}
        def forbidden(*a, **kw): raise AssertionError('must stop before provider')
        with self.assertRaises(ConfigurationFailure): tokens.Counter(self.state, post=forbidden).count(item)
        self.install()
        saved = json.loads((self.state/'checkpoint.json').read_bytes())['phase2_token_preflight']
        saved['rows'].extend([{'id': 'cb-fc-a', 'key': 'a', 'status': 'dispatched_or_uncertain'},
            {'id': 'cb-fc-b', 'key': 'b', 'status': 'dispatched_or_uncertain'}])
        executor.checkpoint(self.state, token_preflight=saved)
        with self.assertRaisesRegex(ValueError, 'counter_finite_http_limit'):
            tokens.Counter(self.state, post=forbidden).count(item | {'id': 'legacy-count'})

    def test_atomic_install_before_and_after_write_failures_recover_once(self):
        source = self.state
        for after in (False, True):
            self.state = source.parent/('after' if after else 'before'); shutil.copytree(source, self.state)
            def fail(path, value):
                if after: atomic_json(path, value)
                raise OSError('fixture persistence failure')
            with patch.object(policy, 'atomic_json', side_effect=fail):
                with self.assertRaises(OSError): self.install()
            self.install(); self.restored(); state = self.install().read()
            self.assertEqual(state['requests'], self.original['requests'])
            self.assertEqual(state['events'][19:], policy.events())
        self.state = source

    def test_concurrent_authority_install_is_single_atomic_amendment(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.install(), range(2)))
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read()['events'][19:], policy.events())

    def test_native_counter_new_allowance_concurrency_and_no_replay(self):
        self.install()
        item = {'id': 'cb-fc-native-check', 'body': tokens.count_body('fixture text')}
        class Response:
            status_code = 200
            def iter_content(self, _): yield encoded({'input_tokens': 30})
            def close(self): pass
        def post(*a, **kw):
            self.native_calls += 1; return Response()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: tokens.Counter(self.state, post=post).count(item), range(2)))
        self.assertEqual(results, [30, 30]); self.assertEqual(self.native_calls, 1)
        self.restored(); self.assertEqual(tokens.Counter(self.state, post=post).count(item), 30)
        broken = {'id': 'cb-fc-uncertain', 'body': tokens.count_body('different fixture text')}
        def fail(*a, **kw): self.native_calls += 1; raise OSError('uncertain')
        with self.assertRaises(OSError): tokens.Counter(self.state, post=fail).count(broken)
        self.restored()
        with self.assertRaises(RecoveryRequired): tokens.Counter(self.state, post=post).count(broken)
        self.assertEqual(self.native_calls, 2)


if __name__ == '__main__':
    unittest.main()
