"""Synthetic cache authentication/wiring tests, never provider qualification."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import subtopic_cov4 as gate
from tools import replay_cov4_processing as replay
from tools import run_budgeted_documents as documents, run_cov4_validation as harness
from tools.offline_ai import identity


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')


def synthetic_state(root):
    """Build fake paid markers solely to exercise authentication failure modes.

    These labels-derived responses have no provider provenance and never leave
    the temporary test directory or become production qualification evidence.
    """
    state = root / 'history'
    state.mkdir()
    source = json.loads(replay.DEFAULT_EVIDENCE.read_bytes())
    trusted = source['qualification']
    current = {name: replay._current(name) for name in ('controls', 'population')}
    native = replay.evaluation.production_preflight_configuration()
    preflight = {'complete': True, 'result': {'ready': True}, 'contract': identity(native),
                 'transport': 'anthropic-structured-json-1'}
    write(state / 'production-preflight-receipt.json', preflight)
    request_key = identity({'route': native['route'], 'stage': 'preflight',
        'config': native['stage'] | {'preflight_contract': preflight['contract']},
        'prompt': 'Return exactly the requested readiness object.', 'schema': native['schema'],
        'inputs': {'ready': True}})
    write(state / 'cache' / (request_key + '.json'), {'key': request_key,
        'returned_model': 'claude-sonnet-5', 'transport_version': preflight['transport'],
        'value': {'ready': True}})
    ledger = {'requests': [{'key': request_key, 'stage': 'preflight', 'provider': 'anthropic',
                            'status': 'valid', 'model': 'claude-sonnet-5', 'id': 'preflight',
                            'http_status': 200, 'charged_microusd': 1}], 'events': [], 'blocked_providers': {}}
    hashes = {}
    for (candidate, *_), selected in zip(current['population']['generic_records'], current['population']['active_requests']):
        key = replay._key(selected)
        extra = current['population']['protocol']['additional_subject_controls'].get(candidate['candidate_id'])
        fundable = ('yes' if extra['fundability'] == 'accept' else 'no') if extra else ('yes' if candidate['fundable'] == 'yes' else 'no')
        value = {'owned': candidate['owned'], 'fundable': fundable,
                 'reason': 'Synthetic labels-derived wiring response; not qualification.'}
        cached = {'key': key, 'returned_model': 'claude-sonnet-5', 'transport_version': preflight['transport'], 'value': value}
        hashes[key] = identity(cached)
        write(state / 'cov4-production-cache' / (key + '.json'), cached)
        ledger['requests'].append({'key': key, 'stage': 'cov4', 'provider': 'anthropic',
            'model': 'claude-sonnet-5', 'status': 'valid', 'http_status': 200, 'id': key, 'charged_microusd': 1})
    write(state / 'ledger.json', ledger)
    classify = documents.instrument(replay.ReadOnlyLedger(ledger), state / 'cov4-production-cache', gate.classify_fundability, replay=True)
    receipts = {}
    for population, data in current.items():
        destination = state / data['protocol']['version'] / population
        destination.mkdir(parents=True)
        with patch.object(gate, 'classify_fundability', classify), redirect_stdout(io.StringIO()):
            metrics = harness.run(destination / 'results.jsonl', live=False, candidates=data['population'])
        metrics.pop('raw', None); metrics.pop('live', None)
        receipt = deepcopy(trusted)
        receipt['configuration'].update(data)
        receipt['configuration']['preflight_contract'] = preflight['contract']
        receipt.update(evaluation_contract=identity(receipt['configuration']), population=population,
            metrics=metrics, execution_complete=True, numerical_gate_passed=True,
            result_hash=identity(replay._rows(destination / 'results.jsonl')),
            response_hashes={replay._key(selected): hashes[replay._key(selected)] for selected in data['active_requests']})
        write(destination / 'qualification-receipt.json', receipt)
        receipts[population] = receipt
    source['qualification'] = receipts['population']
    source['accounting'] = {'cumulative_requests': len(ledger['requests']),
                            'cumulative_estimated_usd': len(ledger['requests']) / 1_000_000}
    evidence = root / 'synthetic-reviewed-evidence.json'
    write(evidence, source)
    return state, evidence


class ProcessingReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.fixture.name)
        cls.fixture_state, cls.fixture_evidence = synthetic_state(cls.fixture_root)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'history'
        shutil.copytree(self.fixture_state, self.state)
        self.evidence = self.root / 'synthetic-reviewed-evidence.json'
        shutil.copyfile(self.fixture_evidence, self.evidence)
        self.output = self.root / 'new-processing'

    def authenticate(self):
        return replay.authenticate(self.state, evidence=self.evidence)

    def run_replay(self):
        return replay.replay_processing(self.state, self.output, evidence=self.evidence)

    def test_exact_synthetic_cache_replays_controls_population_and_bypasses_without_writes_or_calls(self):
        before = {str(path.relative_to(self.state)): path.read_bytes() for path in self.state.rglob('*') if path.is_file()}
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'MUST_NOT_BE_USED'}):
            receipt = self.run_replay()
        self.assertEqual(receipt['responses']['count'], 43)
        self.assertEqual(receipt['new_provider_requests'], 0)
        self.assertTrue(receipt['ledger_byte_identical'])
        self.assertFalse(receipt['quality_gate_passed'])
        self.assertFalse(receipt['production_enabled'])
        self.assertEqual(receipt['source_review'], 'required')
        self.assertEqual(receipt['populations']['controls']['metrics']['classifier_calls'], 5)
        self.assertEqual(receipt['populations']['population']['metrics']['classifier_calls'], 43)
        for item in receipt['populations'].values():
            self.assertEqual(item['metrics']['candidates_bypassed_by_provenance'], {'native': 5, 'referenced': 14})
            self.assertEqual(item['metrics']['bypass_classifier_calls'], 0)
        self.assertEqual(before, {str(path.relative_to(self.state)): path.read_bytes()
                                 for path in self.state.rglob('*') if path.is_file()})
        self.assertTrue((self.output / 'processing-receipt.json').is_file())
        self.assertNotIn('MUST_NOT_BE_USED', json.dumps(receipt))

    def test_copied_state_and_custom_evidence_have_identical_portable_receipts(self):
        first = self.run_replay()
        copied = self.root / 'different-workstation-layout'
        copied.mkdir()
        state = copied / 'retained-evaluation'
        shutil.copytree(self.state, state)
        evidence = copied / 'private-operator-filename.json'
        shutil.copyfile(self.evidence, evidence)
        output = copied / 'replayed-processing'
        second = replay.replay_processing(state, output, evidence=evidence)
        self.assertEqual(first, second)
        self.assertEqual((self.output / 'processing-receipt.json').read_bytes(),
                         (output / 'processing-receipt.json').read_bytes())
        self.assertEqual(first['historical_evidence']['namespace'], 'evidence')
        self.assertEqual(first['historical_evidence']['path'], 'reviewed-qualification.json')
        self.assertEqual(len(first['historical_files_sha256']), 51)
        encoded = json.dumps(first)
        for private in (str(self.root), self.root.as_posix(), self.root.name, 'different-workstation-layout',
                        'private-operator-filename', 'retained-evaluation'):
            self.assertNotIn(private, encoded)
        self.assertTrue(all(name.startswith(('state:', 'evidence:'))
                            for name in first['historical_files_sha256']))

    def test_repository_evidence_uses_checkout_relative_namespace_and_preserves_filename_collisions(self):
        checkout = self.root / 'checkout'
        evidence = checkout / 'evaluation/qualification-receipt.json'
        evidence.parent.mkdir(parents=True)
        shutil.copyfile(self.evidence, evidence)
        authenticated = replay.authenticate(self.state, evidence=evidence)
        with patch.object(replay, 'ROOT', checkout):
            reference, files = replay._portable_references(authenticated)
        self.assertEqual(reference, {'namespace': 'repository', 'path': 'evaluation/qualification-receipt.json'})
        self.assertEqual(files['repository:evaluation/qualification-receipt.json'], replay._sha(evidence))
        for population in ('controls', 'population'):
            name = f'sonnet-production-cov4-2/{population}/qualification-receipt.json'
            self.assertEqual(files['state:' + name], replay._sha(self.state / name))
        self.assertEqual(len(files), len(authenticated['files']))
        self.assertFalse(any(chr(92) in name or name.startswith('/') for name in files))
        self.assertNotIn(str(checkout), json.dumps((reference, files)))

    def test_external_evidence_named_like_a_state_file_remains_distinct(self):
        evidence = self.root / 'ledger.json'
        shutil.copyfile(self.evidence, evidence)
        authenticated = replay.authenticate(self.state, evidence=evidence)
        reference, files = replay._portable_references(authenticated)
        self.assertEqual(reference, {'namespace': 'evidence', 'path': 'reviewed-qualification.json'})
        self.assertEqual(files['evidence:reviewed-qualification.json'], replay._sha(evidence))
        self.assertEqual(files['state:ledger.json'], replay._sha(self.state / 'ledger.json'))
        self.assertNotEqual(files['evidence:reviewed-qualification.json'], files['state:ledger.json'])
        self.assertEqual(len(files), len(authenticated['files']))
        # Portable serialization must not change the absolute paths used to
        # detect tampering during a replay.
        (self.state / 'ledger.json').write_bytes((self.state / 'ledger.json').read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            replay._check_unchanged(authenticated)

    def test_changed_cached_decision_is_rejected_before_replay(self):
        path = next((self.state / 'cov4-production-cache').glob('*.json'))
        cached = json.loads(path.read_bytes())
        cached['value']['fundable'] = 'no' if cached['value']['fundable'] == 'yes' else 'yes'
        write(path, cached)
        with self.assertRaisesRegex(ValueError, 'cache provenance mismatch'):
            self.run_replay()
        self.assertFalse(self.output.exists())

    def test_missing_response_or_wrong_model_is_not_a_replayable_population(self):
        path = next((self.state / 'cov4-production-cache').glob('*.json'))
        cached = json.loads(path.read_bytes())
        path.unlink()
        with self.assertRaises(OSError):
            self.authenticate()
        cached['returned_model'] = 'different-model'
        write(path, cached)
        with self.assertRaisesRegex(ValueError, 'cache provenance mismatch'):
            self.authenticate()

    def test_missing_or_duplicate_paid_ledger_row_is_rejected(self):
        path = self.state / 'ledger.json'
        ledger = json.loads(path.read_bytes())
        original = deepcopy(ledger)
        ledger['requests'].pop()
        write(path, ledger)
        with self.assertRaisesRegex(ValueError, 'paid Cov4 ledger response'):
            self.authenticate()
        original['requests'].append(deepcopy(original['requests'][-1]))
        write(path, original)
        with self.assertRaisesRegex(ValueError, 'paid Cov4 ledger response'):
            self.authenticate()

    def test_changed_preflight_is_rejected(self):
        path = self.state / 'production-preflight-receipt.json'
        value = json.loads(path.read_bytes())
        value['contract'] = 'changed'
        write(path, value)
        with self.assertRaisesRegex(ValueError, 'transport preflight'):
            self.authenticate()

    def test_changed_prompt_population_generic_or_bypass_inputs_require_new_qualification(self):
        original = replay._current
        for field in ('active_requests', 'population', 'generic_records', 'bypasses'):
            def changed(population):
                value = original(population)
                value[field] = ['changed-input']
                return value
            with self.subTest(field=field), patch.object(replay, '_current', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'requires a separate qualification'):
                    self.authenticate()

    def test_changed_historical_result_is_rejected(self):
        path = self.state / 'sonnet-production-cov4-2/population/results.jsonl'
        rows = replay._rows(path)
        rows[0]['published'] = not rows[0]['published']
        path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'result digest mismatch'):
            self.authenticate()

    def test_processing_change_that_alters_metrics_cannot_receive_a_success_receipt(self):
        original = harness.run
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            result['contaminants_published'] += 1
            return result
        with patch.object(harness, 'run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'metrics differ'):
                self.run_replay()
        self.assertFalse((self.output / 'processing-receipt.json').exists())

    def test_accounting_mutation_during_processing_cannot_receive_a_success_receipt(self):
        original = harness.run
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.state / 'ledger.json'
            path.write_bytes(path.read_bytes() + b' ')
            return result
        with patch.object(harness, 'run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                self.run_replay()
        self.assertFalse((self.output / 'processing-receipt.json').exists())

    def test_output_cannot_overwrite_or_contain_historical_evidence(self):
        for path in (self.state, self.state / 'new-processing', self.root):
            with self.subTest(path=path), self.assertRaises(ValueError):
                replay.replay_processing(self.state, path, evidence=self.evidence)
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_replay()


if __name__ == '__main__':
    unittest.main()
