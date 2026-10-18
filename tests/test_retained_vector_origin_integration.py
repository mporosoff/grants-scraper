"""Protected whole-vector reuse across generation recovery and reconciliation.

The four public assets and their protected release receipts are real checked-in
bytes. Git's read-only object transport is supplied by a self-contained fixture;
the asset authenticator, durable completion and history importer all run normally.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import catalog_reconcile_spend as spend
from tools import release_candidate as candidate
from tools.offline_spend import Ledger, atomic_json, identity


class RetainedVectorOriginIntegration(unittest.TestCase):
    RUN = '123'
    PROTECTED_REF = 'a' * 40
    VALIDATOR_DESCENDANT = 'b' * 40
    UNRELATED = 'c' * 40
    EVENT_SHA = 'd' * 40
    WORKFLOW = '.github/workflows/refresh-opportunities.yml'

    @classmethod
    def setUpClass(cls):
        repository = Path(__file__).resolve().parents[1]
        cls.public_bytes = {name: (repository / name).read_bytes() for name in spend.VECTOR_OUTPUTS}
        cls.public_metadata = {name: (repository / name).read_bytes() for name in (
            'release/candidate.json', 'release/candidate-source.json', 'release/validation.json')}
        cls.public_manifest = json.loads(cls.public_metadata['release/candidate.json'])
        cls.public_vectors = json.loads(cls.public_bytes[spend.VECTOR_OUTPUTS[0]])
        cls.semantic = cls.public_manifest['dependency_groups']['semantic']

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'tools').mkdir()
        (self.root / 'tools/clock.py').write_bytes(b'public_input = True\n')
        self.raw = dict(self.public_bytes)
        self.protected = dict(self.public_metadata) | self.raw
        self.hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in self.raw.items()}
        self.assertEqual(self.hashes, {name: self.public_manifest['files'][name] for name in spend.VECTOR_OUTPUTS})
        self.write_outputs(self.raw)
        self.head = self.PROTECTED_REF
        self.git_calls = []
        self.state = self.root / ('offline-' + self.RUN)
        self.book = Ledger(self.state / 'ledger.json', 'offline-' + self.RUN, 2, 300)
        token = self.book.reserve('anthropic', 'prior-model', 'documents', 'prior-document', 30, 1)
        self.book.complete(token, status='complete', charged_microusd=25)
        self.original = deepcopy(self.book.read())
        self.original_hash = identity(self.original)
        self.packet = {key: self.public_vectors[key] for key in
            ('corpus_sha256', 'configuration_sha256', 'passage_count')}
        self.packet.update(run_id=self.RUN, mode='maintenance', retained_asset_eligible=True,
            source_hashes={'tools/clock.py': hashlib.sha256((self.root / 'tools/clock.py').read_bytes()).hexdigest()})
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(spend, '__file__', str(self.root / 'tools/catalog_reconcile_spend.py')))
        self.stack.enter_context(patch.object(candidate, 'ROOT', self.root))
        self.stack.enter_context(patch.object(spend, 'GENERATION_INPUTS', ('tools/clock.py',)))
        self.stack.enter_context(patch.object(spend, 'production_ledger', return_value=self.book))
        self.stack.enter_context(patch.dict('os.environ', GITHUB_RUN_ID=self.RUN))
        self.stack.enter_context(patch.object(spend.subprocess, 'check_output', side_effect=self.git_read))
        self.stack.enter_context(patch('tools.release_dependencies.snapshot', side_effect=self.snapshot))
        self.http = self.stack.enter_context(patch('urllib.request.OpenerDirector.open',
            side_effect=AssertionError('retained whole asset must not use HTTP')))
        self.provider_http = self.stack.enter_context(patch('requests.sessions.Session.request',
            side_effect=AssertionError('retained whole asset must not call providers')))
        self.reserve = self.stack.enter_context(patch.object(spend, 'reserve',
            side_effect=AssertionError('retained whole asset must not reserve vector requests')))

    def snapshot(self, root, revision=None):
        self.assertEqual(Path(root), self.root)
        self.assertIn(revision, (None, self.PROTECTED_REF))
        return {'semantic': deepcopy(self.semantic)}

    def git_read(self, command, **options):
        self.assertEqual(command[:3], ['git', '-C', str(self.root)])
        args = tuple(command[3:]); self.git_calls.append(args)
        if args == ('rev-parse', 'HEAD'):
            raw = (self.head + '\n').encode()
        elif args[:2] == ('merge-base', '--is-ancestor'):
            ancestor, descendant = args[2:]
            target = self.head if descendant == 'HEAD' else descendant
            if ancestor != self.PROTECTED_REF or target not in (self.PROTECTED_REF, self.VALIDATOR_DESCENDANT):
                raise subprocess.CalledProcessError(1, command)
            raw = b''
        elif args[0] == 'show':
            revision, name = args[1].split(':', 1)
            if revision == self.EVENT_SHA and name == self.WORKFLOW:
                raw = b'jobs:\n  generate:\n    steps:\n      - id: semantic-vectors\n        run: node tools/run_budgeted_vectors.mjs --production --write\n'
            else:
                self.assertEqual(revision, self.PROTECTED_REF)
                raw = self.protected[name]
        else:
            self.fail('unexpected Git read: ' + repr(args))
        return raw.decode() if options.get('text') else raw

    def write_outputs(self, outputs):
        for name, raw in outputs.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def prepared(self):
        result = spend.prepare(self.state, self.packet, generation=True)
        self.assertEqual(result['status'], 'complete')
        self.completion_path = self.state / 'vector-completions' / (result['operation_sha256'] + '.json')
        self.completion = json.loads(self.completion_path.read_bytes())
        self.assertEqual(self.completion['accounting_origin']['kind'], 'retained')
        self.assertEqual(self.completion['accounting_origin']['new_requests'], 0)
        self.assertEqual(self.completion['accounting_origin']['protected_candidate_id'], self.public_manifest['candidate_id'])
        self.assertEqual(self.book.read(), self.original)
        return result

    def capture_parent(self, generation_sha=None):
        """The next daily parent owns its run, while retaining the older four bytes."""
        generation_sha = generation_sha or self.head
        self.parent = self.root / 'daily-parent'
        manifest = {'schema_version': 1, 'generation_run_id': self.RUN, 'generation_run_attempt': '1',
            'generation_sha': generation_sha, 'files': self.hashes,
            'dependency_groups': {'semantic': self.semantic}}
        manifest['candidate_id'] = candidate.digest(candidate.encoded(manifest))
        parent_raw = candidate.encoded(manifest)
        self.parent.mkdir(exist_ok=True); (self.parent / 'candidate.json').write_bytes(parent_raw)
        for name in spend.VECTOR_OUTPUTS:
            path = self.parent / 'files' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / name).read_bytes())
        value = {'parent_run': self.RUN, 'parent_candidate_id': manifest['candidate_id'],
            'parent_generation_sha': generation_sha,
            'parent_manifest_sha256': hashlib.sha256(parent_raw).hexdigest(),
            'parent_producer': {'run_id': self.RUN, 'run_attempt': '1', 'head_sha': self.EVENT_SHA,
                'event': 'schedule', 'path': self.WORKFLOW},
            'original_spend': {'ledger_sha256': self.original_hash},
            'operation_contract': {'reviewed-source': 'e' * 64}}
        value['operation_sha256'] = identity(value)
        atomic_json(self.state / 'reconciliation.json', value)
        return manifest

    def assert_no_new_spend(self):
        value = self.book.read()
        self.assertEqual(value['requests'], self.original['requests'])
        self.assertEqual(sum(row['charged_microusd'] for row in value['requests']), 25)
        self.assertEqual(value['events'][:len(self.original['events'])], self.original['events'])
        self.http.assert_not_called(); self.provider_http.assert_not_called(); self.reserve.assert_not_called()

    def test_sealed_origin_survives_stage_crash_cold_restore_and_parent_history_import(self):
        write_json = spend.atomic_json
        def interrupt_stage(path, value):
            if Path(path).name == 'vector-stage.json':
                raise OSError('crash after sealed completion before diagnostic stage')
            return write_json(path, value)
        with patch.object(spend, 'atomic_json', side_effect=interrupt_stage):
            with self.assertRaisesRegex(OSError, 'crash after sealed completion'):
                spend.prepare(self.state, self.packet, generation=True)
        self.assertFalse((self.state / 'vector-stage.json').exists())
        prepared = self.prepared()
        self.assertFalse((self.state / 'vector-stage.json').exists(), 'the immutable completion is sufficient')
        origin = deepcopy(self.completion['accounting_origin'])
        private = self.root / 'private-checkpoint'; shutil.copytree(self.state, private)
        shutil.rmtree(self.state); shutil.copytree(private, self.state)
        self.write_outputs({name: b'cold checkout predecessor' for name in spend.VECTOR_OUTPUTS})
        restored = spend.prepare(self.state, self.packet, generation=True)
        self.assertEqual(restored['status'], 'restore'); self.assertEqual(restored['outputs'], self.hashes)
        self.assertEqual(restored['accounting_origin'], origin)
        self.assertEqual({name: Path(path).read_bytes() for name, path in restored['blobs'].items()}, self.raw)
        self.write_outputs({name: Path(path).read_bytes() for name, path in restored['blobs'].items()})
        spend.checkpoint(self.state, {'operation_sha256': prepared['operation_sha256'],
            'outputs': self.hashes, 'restored': True}, generation=True)
        self.assertEqual(json.loads(self.completion_path.read_bytes())['accounting_origin'], origin)
        self.assertEqual(json.loads((self.state / 'vector-stage.json').read_bytes())['accounting_origin'], origin)
        self.assertEqual(self.book.read(), self.original)
        parent = self.capture_parent()
        self.assertNotEqual(parent['candidate_id'], origin['protected_candidate_id'])
        self.assertGreater(json.loads(self.raw[spend.VECTOR_OUTPUTS[-1]])['API_request_count'], 0)
        spend.import_history(self.state, self.parent, self.original_hash)
        first = deepcopy(self.book.read())
        spend.import_history(self.state, self.parent, self.original_hash)
        self.assertEqual(self.book.read(), first)
        marker = first['events'][-1]
        self.assertEqual(marker['classification'], 'retained'); self.assertEqual(marker['requests'], [])
        self.assertEqual(marker['accounting_origin'], origin)
        self.assert_no_new_spend()

    def test_validator_only_descendant_keeps_original_asset_and_generation_identities(self):
        self.prepared()
        origin = self.completion['accounting_origin']
        self.head = self.VALIDATOR_DESCENDANT
        self.assertEqual(spend.prepare(self.state, self.packet, generation=True)['status'], 'complete')
        parent = self.capture_parent()
        self.assertNotEqual(self.public_manifest['generation_sha'], self.PROTECTED_REF)
        self.assertNotEqual(self.public_manifest['generation_sha'], parent['generation_sha'])
        self.assertNotEqual(origin['protected_ref'], parent['generation_sha'])
        spend.import_history(self.state, self.parent, self.original_hash)
        self.assertIn(('merge-base', '--is-ancestor', self.PROTECTED_REF, self.VALIDATOR_DESCENDANT), self.git_calls)
        self.assertIn(('show', self.EVENT_SHA + ':' + self.WORKFLOW), self.git_calls)
        self.assertEqual(self.book.read()['events'][-1]['accounting_origin'], origin)
        self.assert_no_new_spend()

    def test_tampered_or_missing_origin_cannot_fall_back_to_stage_or_legacy_history(self):
        self.prepared(); self.capture_parent()
        valid = deepcopy(self.completion)
        changes = (
            lambda value: value.pop('accounting_origin'),
            lambda value: value['accounting_origin'].update(protected_candidate_id='f' * 64),
            lambda value: value['accounting_origin'].update(report_sha256='f' * 64),
            lambda value: value['accounting_origin'].update(semantic_fingerprint='f' * 64),
            lambda value: value['accounting_origin'].update(protected_ref='not-a-commit'),
            lambda value: value['accounting_origin'].update(new_requests=1),
            lambda value: value['accounting_origin']['outputs'].update({spend.VECTOR_OUTPUTS[0]: 'f' * 64}),
        )
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                wrong = deepcopy(valid); change(wrong); atomic_json(self.completion_path, wrong)
                with self.assertRaises(ValueError): spend.prepare(self.state, self.packet, generation=True)
                with self.assertRaises(ValueError): spend.import_history(self.state, self.parent, self.original_hash)
                self.assertEqual(self.book.read(), self.original)
                self.assertEqual({name: (self.root / name).read_bytes() for name in spend.VECTOR_OUTPUTS}, self.raw)
        atomic_json(self.completion_path, valid)
        self.completion_path.unlink()
        with self.assertRaises(FileNotFoundError): spend.import_history(self.state, self.parent, self.original_hash)
        self.assert_no_new_spend()

    def test_protected_gates_output_hashes_and_ancestry_are_rechecked_before_import(self):
        self.prepared(); self.capture_parent()
        original = dict(self.protected)
        receipt = json.loads(original['release/validation.json']); receipt['gates']['scoring'] = 'failed'
        self.protected['release/validation.json'] = candidate.encoded(receipt)
        with self.assertRaisesRegex(ValueError, 'protected_vector_provenance'):
            spend.import_history(self.state, self.parent, self.original_hash)
        self.protected = dict(original)
        self.protected[spend.VECTOR_OUTPUTS[1]] = b'changed protected vector bytes'
        with self.assertRaisesRegex(ValueError, 'protected_vector_outputs'):
            spend.import_history(self.state, self.parent, self.original_hash)
        self.protected = dict(original)
        self.capture_parent(self.UNRELATED)
        with self.assertRaises(subprocess.CalledProcessError):
            spend.import_history(self.state, self.parent, self.original_hash)
        self.assertEqual(self.book.read(), self.original)
        self.assert_no_new_spend()


if __name__ == '__main__':
    unittest.main()
