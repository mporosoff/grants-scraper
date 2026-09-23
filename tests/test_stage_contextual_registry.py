import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import researcher_registry as legacy
from tools import contextual_team_audited_registry as audited
from tools import stage_contextual_registry as stage
from tests.test_contextual_team_audited_registry import observation, registry_fixture

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
WINDOWS_NODE = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
if WINDOWS_NODE.is_file(): NODE = str(WINDOWS_NODE)


class StageModelTests(unittest.TestCase):
    def test_invalid_pinned_evidence_fails_before_output_or_package_work(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for location in ('summary', 'claim'):
                with self.subTest(location=location):
                    registry = registry_fixture()
                    person = registry['researchers'][0]
                    records = person['summary_evidence'] if location == 'summary' else person['claims'][0]['evidence_records']
                    records[0]['retrieved_at'] = '2026-09-22T12:00:00Ztrailing'
                    for claim in person['claims']:
                        claim['material_hash'] = audited.material_claim_hash(claim)
                    registry['registry_generation'] = legacy.registry_generation(registry)
                    source = base/(location + '.json')
                    stage._write(source, registry)
                    original = source.read_bytes()
                    output = base/('output-' + location)
                    with patch.object(stage, '_node', side_effect=AssertionError('No package validation')), \
                            patch.object(stage, '_forward', side_effect=AssertionError('No matching')):
                        with self.assertRaisesRegex(ValueError, 'invalid retrieval timestamp'):
                            stage.assemble(base/'public', source, stage.digest(original), 'a' * 64,
                                           'b' * 64, output, '2026-09-22')
                    self.assertEqual(source.read_bytes(), original)
                    self.assertFalse(output.exists())

    def test_unavailable_model_preserves_all_original_scientific_fields(self):
        registry = registry_fixture()
        model = {'opportunities': [{'id': 'scope-1', 'review_state': 'proposed',
                                  'members': ['unchanged'], 'source_fingerprint': 'historical',
                                  'roles': [{'claim_refs': [{'revision': 1, 'reason': 'Original scientific judgment.'}]}]}]}
        model['generation_id'] = stage.identity(model)
        before = copy.deepcopy(model)
        result = stage.unavailable_model(model, registry, {'original_model_sha256': 'c' * 64})
        self.assertEqual(model, before)
        expected = dict(before['opportunities'][0], review_state='needs_revalidation')
        self.assertEqual(result['opportunities'], [expected])
        self.assertEqual(result['local_staging']['original_generation'], before['generation_id'])
        model['opportunities'][0]['roles'][0]['claim_refs'][0]['reason'] = 'Tampered'
        with self.assertRaisesRegex(ValueError, 'generation'): stage.unavailable_model(model, registry, {})

    def test_safe_paths_and_duplicate_json_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('../outside', 'C:/outside', '/outside', 'data\\outside'):
                with self.subTest(name=name), self.assertRaises(ValueError): stage._safe(Path(folder), name)
            path = Path(folder)/'data.json'; path.write_text('{"a":1,"a":2}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate'): stage._json(path)

    def test_node_process_receives_no_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = subprocess.CompletedProcess([], 0, '{}', '')
            with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'synthetic', 'GITHUB_TOKEN': 'synthetic', 'NODE_OPTIONS': 'synthetic'}), patch.object(stage.subprocess, 'run', return_value=fake) as run:
                stage._node('node', Path(folder), 'tools/check.mjs')
            self.assertFalse({'ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'NODE_OPTIONS'} & set(run.call_args.kwargs['env']))


@unittest.skipUnless(NODE, 'Node runtime required for the actual local package contract')
class LocalPackageTests(unittest.TestCase):
    """Real public corpus/builder and browser modules; synthetic audited amendments."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.public = cls.base/'public'; cls.public.mkdir()
        release = stage._json(ROOT/'data/search-v2-release.json')
        names = set(release['source_hashes']) | set(stage.EXTRA_FILES)
        for name in names: stage._copy(ROOT/name, cls.public/name)
        registry = stage._json(ROOT/'config/researcher_registry.json')
        person = next(person for person in registry['researchers'] if person['status'] == 'active' and person['pool_visibility'] == 'department' and person['claims'])
        record = observation(person['source_urls'][0])
        person['summary_evidence'] = [record]
        person['claims'][0]['evidence_records'] = [copy.deepcopy(record)]
        person['claims'][0]['material_hash'] = audited.material_claim_hash(person['claims'][0])
        registry['registry_generation'] = legacy.registry_generation(registry)
        cls.registry = cls.base/'audited.json'; stage._write(cls.registry, registry)
        cls.registry_sha = stage.digest(cls.registry.read_bytes())
        projected = b'/* Generated by scripts/researcher_registry.py. Do not edit. */\nglobalThis.RESEARCHER_DIRECTORY=' + stage.encoded(audited.directory(registry)) + b';\n'
        cls.directory_sha = stage.digest(projected)
        cls.release_sha = stage.digest((cls.public/'data/search-v2-release.json').read_bytes())
        cls.as_of = date.fromisoformat(release['generated_at'][:10])
        cls.original_hashes = {name: stage.digest((cls.public/name).read_bytes()) for name in names}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def assemble(self, name, **kwargs):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('No network')), patch('scripts.researcher_registry.build_outputs', side_effect=AssertionError('No ordinary rebuild')), patch('scripts.researcher_registry.synchronize_opportunity_team_model', side_effect=AssertionError('No maintenance')):
            return stage.assemble(self.public, self.registry, self.registry_sha, self.directory_sha,
                                  self.release_sha, self.base/name, self.as_of, node=NODE, **kwargs)

    def test_actual_package_and_duplicate_execution_preserve_source_and_legacy_bytes(self):
        result = self.assemble('first')
        repeat = self.assemble('second')
        self.assertEqual(result, repeat)
        self.assertFalse(result['official_candidate'])
        self.assertIsNone(result['generation_run_id'])
        self.assertEqual(result['checks']['browser']['withheld'], len(result['original_rows']))
        self.assertEqual(result['checks']['browser']['available'], 0)
        self.assertEqual(result['search_identity']['passage_count'], stage._json(self.public/'data/search-v2-release.json')['passage_count'])
        self.assertEqual(result['local_package']['sha256'], repeat['local_package']['sha256'])
        with zipfile.ZipFile(self.base/'first/rollback.zip') as archive:
            self.assertEqual(archive.read('config/opportunity_team_model.json'), (self.public/'config/opportunity_team_model.json').read_bytes())
            for name, pin in self.original_hashes.items(): self.assertEqual(stage.digest(archive.read(name)), pin)
        for name, pin in self.original_hashes.items(): self.assertEqual(stage.digest((self.public/name).read_bytes()), pin)
        matches = stage._assignment(self.base/'first/package/data/faculty_matches.js', 'FACULTY_MATCHES')
        self.assertTrue(all('claims' in person and 'summary_evidence' in person for person in matches['faculty'].values()))
        with self.assertRaisesRegex(ValueError, 'isolated'): self.assemble('first')

    def test_input_and_projection_pin_fail_before_output_creation(self):
        for field in ('registry', 'directory', 'release'):
            with self.subTest(field=field):
                pins = [self.registry_sha, self.directory_sha, self.release_sha]
                pins[('registry', 'directory', 'release').index(field)] = 'f' * 64
                target = self.base/('bad-' + field)
                with self.assertRaises(ValueError): stage.assemble(self.public, self.registry, *pins, target, self.as_of, node=NODE)
                self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, 'isolated'):
            stage.assemble(self.public, self.registry, self.registry_sha, self.directory_sha, self.release_sha, self.public/'outputs/stage', self.as_of, node=NODE)

    def test_lost_validation_keeps_failure_and_never_emits_completion_receipt(self):
        with patch.object(stage, '_node', side_effect=ValueError('synthetic stopped validator')):
            with self.assertRaises(ValueError): self.assemble('failed')
        self.assertTrue((self.base/'failed/FAILED.json').is_file())
        self.assertTrue((self.base/'failed/INCOMPLETE.json').is_file())
        self.assertFalse((self.base/'failed/LOCAL-STAGE.json').exists())
        with self.assertRaisesRegex(ValueError, 'isolated'): self.assemble('failed')

    def test_source_change_after_copy_is_rejected_without_a_completion_marker(self):
        changed = self.public/'data/catalog-metadata.js'
        original = changed.read_bytes()
        actual_node = stage._node
        calls = []
        def change_after_first_check(*args, **kwargs):
            value = actual_node(*args, **kwargs)
            calls.append(args)
            if len(calls) == 1: changed.write_bytes(original + b'\n')
            return value
        try:
            with patch.object(stage, '_node', side_effect=change_after_first_check):
                with self.assertRaisesRegex(ValueError, 'pin_mismatch'): self.assemble('changed-source')
            self.assertTrue((self.base/'changed-source/FAILED.json').is_file())
            self.assertFalse((self.base/'changed-source/LOCAL-STAGE.json').exists())
        finally:
            changed.write_bytes(original)

    def test_pinned_release_cannot_hide_a_rekeyed_original_model(self):
        path = self.public/'config/opportunity_team_model.json'
        original = path.read_bytes()
        model = json.loads(original)
        model['opportunities'][0]['objective'] = 'Synthetic changed original judgment'
        model['generation_id'] = stage.identity({k: v for k, v in model.items() if k != 'generation_id'})
        try:
            stage._write(path, model)
            with self.assertRaisesRegex(ValueError, 'model_projection_conflict'): self.assemble('changed-model')
            self.assertFalse((self.base/'changed-model').exists())
        finally:
            path.write_bytes(original)

    def test_concurrent_same_destination_has_one_complete_owner(self):
        def attempt(_):
            try:
                return stage.assemble(self.public, self.registry, self.registry_sha, self.directory_sha,
                                      self.release_sha, self.base/'concurrent', self.as_of, node=NODE)
            except (ValueError, FileExistsError): return None
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        self.assertTrue((self.base/'concurrent/LOCAL-STAGE.json').is_file())
        self.assertFalse((self.base/'concurrent/FAILED.json').exists())


if __name__ == '__main__': unittest.main()
