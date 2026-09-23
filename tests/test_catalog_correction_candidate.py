"""Synthetic local Git assembly contracts; no generation, providers, or live probes.

The optional retained-artifact check only reads an already downloaded public
candidate. Synthetic exports below are mechanism fixtures, never execution proof.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.sources.merge import CATALOG_GLOBAL
from tools import catalog_source_correction as source
from tools import catalog_correction_policy as spending
from tools import release_candidate as candidate
from tools import verify_release_live as live


ORIGINAL_FIELDS = (
    'generation_sha', 'generation_run_id', 'generation_run_attempt',
    'generation_timestamp', 'generation_dependencies', 'generation_baseline',
    'generation_files', 'semantic_identity',
)
FROZEN = (
    'config/opportunity_team_model.json', 'data/document_evidence.json',
    'data/opportunity_enrichment.json', 'data/subtopics.js',
    'data/researcher_directory.js', 'data/opportunity_teams.js',
    'data/opportunity_team_index.js', 'evaluation/opportunity_team_generation.json',
)


class SourceCandidateFixture:
    """Actual assembler/dependency code against a deliberately small fake repo."""

    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / 'r'
        self.root.mkdir()
        self.bundle = self.base / 'original'
        self.output = self.base / 'corrected'
        self.export = self.base / 'export'
        self.config = self.base / 'source-plan.json'
        self.serial = 0
        self.catalog = {
            'opportunities': [{'opportunity_id': 'synthetic-original', 'title': 'Original'}],
            'diagnostics': {'additional_sources': {'lifecycle': []}},
        }
        generated = sorted(source.VECTOR_FILES | set(FROZEN) | {
            'data/opportunities.js', 'data/catalog-metadata.js', 'data/source_records.json',
            'README.md', 'PROJECT.md', 'feeds/changes.json', 'evaluation/release_coverage.json',
        })
        self.policy = {
            'generation': ['scripts/parser.py', 'scripts/teams.py', 'tools/vectors.mjs'],
            'generation_excluded': [], 'generation_contract': {'python': '3.13', 'node': '22'},
            'generated': generated, 'package': ['data/search-v2-release.json'],
            'runtime': ['index.html', 'workers/search/src/index.js'],
            'worker': ['workers/search/src/index.js'], 'validation': ['tools/validator.py'],
            'team_outputs': list(FROZEN),
            'dependency_groups': {
                key: {'patterns': names, 'excluded': []}
                for key, names in {
                    'source': ['scripts/parser.py'], 'teams': ['scripts/teams.py'],
                    'semantic': ['tools/vectors.mjs'], 'runtime': ['index.html'],
                    'validation': ['tools/validator.py'],
                }.items()
            },
        }
        self.write(candidate.POLICY, self.policy)
        self.write('.github/workflows/refresh-opportunities.yml',
            'jobs:\n  generate:\n    steps:\n      - run: python -m scripts.parser\n'
            '      - run: node tools/build_search_v2_voyage_vectors.mjs\n')
        for name, raw in {
            'scripts/parser.py': 'VERSION = 1\n', 'scripts/teams.py': 'MODEL = "retained"\n',
            'tools/vectors.mjs': 'const model = "old";\n', 'tools/validator.py': 'VERSION = 1\n',
            'index.html': '<main>Original</main>', 'workers/search/src/index.js': 'export default {};',
            'README.md': 'Original count', 'PROJECT.md': 'Original status',
        }.items():
            self.write(name, raw)
        for name in FROZEN:
            self.write(name, {'generation_id': 'synthetic-team', 'retained': name})
        self.write_catalog(self.catalog)
        self.write('data/catalog-metadata.js', 'original metadata')
        self.write('data/source_records.json', {'sources': {'synthetic': {'records': ['old']}}})
        self.write('feeds/changes.json', {'changes': []})
        self.write('evaluation/release_coverage.json', {'retained_teams': True})
        self.write_vectors('old')
        self.write('data/search-v2-release.json', {'current_corpus_sha256': 'old'})
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for key, value in (('core.autocrlf', 'false'),
                           ('core.excludesFile', str(self.root / '.git/info/exclude')),
                           ('user.name', 'Synthetic contract'),
                           ('user.email', 'contract@example.test')):
            candidate.git(self.root, 'config', key, value)
        self.commit()
        self.original_sha = candidate.git(self.root, 'rev-parse', 'HEAD')
        with patch.object(candidate, 'timestamp', return_value='2026-09-01T00:00:00Z'):
            self.original = candidate.create(self.root, self.bundle,
                generation_sha=self.original_sha, run_id='123', attempt='2')
        self.original_bytes = (self.bundle / candidate.MANIFEST).read_bytes()
        self.write('scripts/parser.py', 'VERSION = 2\n')
        self.write('tools/vectors.mjs', 'const model = "corrected";\n')
        # Distinguish the later checked-in seed from both the old and generated cache.
        self.write('data/source_records.json', {'synthetic_current_git_seed': True})
        self.commit()
        self.current_sha = candidate.git(self.root, 'rev-parse', 'HEAD')
        self.corrected_catalog = deepcopy(self.catalog)
        self.corrected_catalog['opportunities'].append(
            {'opportunity_id': 'synthetic-restored', 'title': 'Restored exact source'})
        self.corrected_cache = {'sources': {'synthetic': {'records': ['old', 'restored']}}}
        self.write_catalog(self.corrected_catalog)
        self.write('data/source_records.json', self.corrected_cache)
        self.write('data/catalog-metadata.js', 'corrected metadata')
        self.write('README.md', 'Corrected count')
        self.write('PROJECT.md', 'Corrected status')
        self.write('feeds/changes.json', {'changes': ['restored']})
        self.write('evaluation/release_coverage.json', {'retained_teams': True, 'source_corrected': True})
        self.write_vectors('corrected')
        self.write('data/search-v2-release.json', {'current_corpus_sha256': 'corrected'})
        for name in source.VECTOR_FILES:
            self.write(name, (self.root / name).read_bytes(), root=self.export)
        self.write('corrected-catalog.json', self.corrected_catalog, root=self.export)
        self.write('corrected-source-cache.json', self.corrected_cache, root=self.export)
        self.plan = {
            'version': source.VERSION, 'candidate_id': self.original['candidate_id'],
            'prior_sha': self.original_sha, 'corpus_sha256': 'corrected',
            'maximum_attempts': 10, 'maximum_microusd': 34837, 'native_counts': 0, 'retries': 0,
            'prepared_pins': {name: candidate.digest((self.export / name).read_bytes())
                for name in ('corrected-catalog.json', 'corrected-source-cache.json')},
        }
        candidate.write_json(self.config, self.plan)
        self.exported = {
            'version': source.VERSION, 'source_plan_sha256': candidate.digest(self.config.read_bytes()),
            'spending_plan_sha256': spending.PLAN_SHA,
            'original_candidate_id': self.original['candidate_id'],
            'original_generation_sha': self.original_sha, 'corpus_sha256': 'corrected',
            'new_provider_requests_for_export': 0, 'new_native_counts_for_export': 0,
            'source_collection_requests': 0,
            'files': candidate.file_hashes(self.export, source.VECTOR_FILES | set(self.plan['prepared_pins'])),
        }
        self.write('export.json', self.exported, root=self.export)
        self.receipt = {
            'version': source.VERSION, 'source_plan_sha256': self.exported['source_plan_sha256'],
            'spending_plan_sha256': spending.PLAN_SHA,
            'export_sha256': candidate.digest((self.export / 'export.json').read_bytes()),
            'owner_run': 900, 'original_candidate_id': self.original['candidate_id'],
        }

    def write(self, name, value, *, root=None):
        path = (root or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else (
            value.encode('utf-8') if isinstance(value, str) else candidate.encoded(value))
        path.write_bytes(raw)

    def write_catalog(self, value):
        self.write('data/opportunities.js',
            'globalThis.' + CATALOG_GLOBAL + '=' + json.dumps(source.public_catalog(value)) + ';\n')

    def write_vectors(self, version):
        for name in source.VECTOR_FILES:
            self.write(name, {'model': 'synthetic', 'model_space_fingerprint': 'space-' + version,
                'corpus_sha256': version} if name.endswith('.json') else ('vectors-' + version).encode())

    def commit(self):
        candidate.git(self.root, 'add', '.')
        candidate.git(self.root, 'commit', '-qm', 'Synthetic fixture checkpoint')

    def create(self, **overrides):
        self.serial += 1
        output = self.output if self.serial == 1 else self.base / ('corrected-' + str(self.serial))
        with patch.object(source, 'CONFIG', self.config), \
                patch.dict(os.environ, {'GITHUB_RUN_ID': '900', 'GITHUB_RUN_ATTEMPT': '1'}), \
                patch.object(candidate, 'timestamp', return_value='2026-09-23T00:00:00Z'):
            return candidate.create_source_correction(self.root, output,
                overrides.get('parent', self.bundle), overrides.get('receipt', self.receipt),
                overrides.get('export', self.export))


class CatalogCorrectionCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='catalog-candidate-')
        self.addCleanup(temporary.cleanup)
        self.f = SourceCandidateFixture(temporary.name)
        for target in ('socket.socket.connect', 'tools.catalog_source_correction.gh',
                       'tools.verify_release_live.fetch'):
            guard = patch(target, side_effect=AssertionError('No external I/O in candidate contracts'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_corrected_active_generation_keeps_exact_original_provenance_and_science(self):
        f = self.f
        value = f.create()
        self.assertEqual(value['original_generation'], {k: f.original[k] for k in ORIGINAL_FIELDS})
        for key in ORIGINAL_FIELDS[:4]:
            self.assertEqual(value[key], f.original[key])
        self.assertEqual(value['team_identity'], f.original['team_identity'])
        for key in ('generation_dependencies', 'generation_baseline', 'generator_versions', 'semantic_identity',
                    'generation_files', 'dependency_groups', 'release_identity'):
            self.assertNotEqual(value[key], f.original[key], key)
        self.assertEqual(value['generation_dependencies'], candidate.generation_dependencies(f.root))
        for name, expected in value['generation_baseline'].items():
            raw = subprocess.check_output(['git', '-C', str(f.root), 'show', f.current_sha + ':' + name])
            self.assertEqual(expected, candidate.digest(raw))
        self.assertEqual(value['generation_files'],
            candidate.file_hashes(f.root, value['generation_files']))
        self.assertEqual(value['semantic_identity']['corpus_sha256'], 'corrected')
        self.assertEqual(value['source_correction']['affected_generation'], {
            'generation_sha': f.current_sha, 'generation_run_id': '900', 'generation_run_attempt': '1',
            'generation_timestamp': '2026-09-23T00:00:00Z'})
        self.assertEqual(value['assembly_sha'], f.current_sha)
        self.assertEqual(value['derived_from_candidate'], f.original['candidate_id'])
        retained = value['source_correction']['retained_output_hashes']
        for name in FROZEN:
            self.assertEqual(retained[name], f.original['files'][name])
            self.assertEqual((f.output / 'files' / name).read_bytes(), (f.bundle / 'files' / name).read_bytes())
        self.assertEqual(value['source_correction']['affected_output_hashes'], {
            n: h for n, h in value['generation_files'].items() if f.original['generation_files'].get(n) != h})
        self.assertEqual((f.bundle / candidate.MANIFEST).read_bytes(), f.original_bytes)
        self.assertEqual(candidate.load(f.bundle), f.original)
        self.assertEqual(candidate.load(f.output), value)

    def test_receipt_requires_exact_typed_lineage(self):
        f = self.f
        mutations = [
            ('version', 'other'), ('source_plan_sha256', '0' * 64),
            ('spending_plan_sha256', '0' * 64), ('export_sha256', '0' * 64),
            ('original_candidate_id', '0' * 64), ('owner_run', True), ('owner_run', 0),
            ('owner_run', '900'), ('unexpected', 'field'),
        ]
        for key, wrong in mutations:
            with self.subTest(key=key, wrong=wrong), self.assertRaisesRegex(ValueError, 'lineage'):
                f.create(receipt=dict(f.receipt) | {key: wrong})
        self.assertFalse(f.output.exists())
        # Even byte-only changes to the locked plan invalidate the raw source receipt.
        f.config.write_bytes(f.config.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'lineage'):
            f.create()

    def test_export_lineage_cannot_be_rehashed_to_hide_wrong_provenance_or_usage(self):
        f = self.f
        for key, value in (
            ('version', 'other'), ('source_plan_sha256', '0' * 64), ('spending_plan_sha256', '0' * 64),
            ('original_candidate_id', '0' * 64), ('original_generation_sha', '0' * 40),
            ('corpus_sha256', 'foreign'), ('new_provider_requests_for_export', 1),
            ('new_native_counts_for_export', False), ('source_collection_requests', 1),
        ):
            with self.subTest(key=key):
                f.write('export.json', dict(f.exported) | {key: value}, root=f.export)
                receipt = dict(f.receipt) | {'export_sha256': candidate.digest((f.export / 'export.json').read_bytes())}
                with self.assertRaisesRegex(ValueError, 'exact retained catalog correction'):
                    f.create(receipt=receipt)

    def test_export_and_applied_source_bytes_must_match_the_complete_locked_inventory(self):
        f = self.f
        for root, name in ((f.export, 'corrected-catalog.json'),
                           (f.export, 'data/search-v2-voyage-vectors.f16'),
                           (f.root, 'data/search-v2-voyage-vectors.f16'),
                           (f.root, 'data/source_records.json')):
            with self.subTest(root=root.name, name=name):
                path = root / name
                original = path.read_bytes()
                try:
                    f.write(name, {} if name.endswith('.json') else b'tampered', root=root)
                    with self.assertRaises(ValueError):
                        f.create()
                finally:
                    path.write_bytes(original)
        original = (f.root / 'data/opportunities.js').read_bytes()
        f.write_catalog(f.catalog)
        with self.assertRaisesRegex(ValueError, 'Corrected source bytes'):
            f.create()
        (f.root / 'data/opportunities.js').write_bytes(original)
        f.write('unlisted.json', {}, root=f.export)
        with self.assertRaisesRegex(ValueError, 'Unmanifested'):
            f.create()

    def test_rehashed_export_cannot_substitute_prepared_source_or_omit_a_vector(self):
        f = self.f
        for name in ('corrected-catalog.json', 'data/search-v2-voyage-vectors.f16'):
            with self.subTest(name=name):
                exported = deepcopy(f.exported)
                if name.endswith('.json'):
                    exported['files'][name] = '0' * 64
                else:
                    del exported['files'][name]
                f.write('export.json', exported, root=f.export)
                receipt = dict(f.receipt) | {'export_sha256': candidate.digest((f.export / 'export.json').read_bytes())}
                with self.assertRaisesRegex(ValueError, 'Unmanifested or altered'):
                    f.create(receipt=receipt)

    def test_every_retained_scientific_or_team_output_rejects_mutation(self):
        f = self.f
        for name in FROZEN:
            path = f.root / name
            original = path.read_bytes()
            with self.subTest(name=name):
                try:
                    f.write(name, {'altered': name})
                    with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
                        f.create()
                finally:
                    path.write_bytes(original)
        f.write('scripts/teams.py', 'MODEL = "unauthorized"\n')
        with self.assertRaisesRegex(ValueError, 'dependency mismatch'):
            f.create()

    def test_wrong_parent_missing_policy_and_mixed_team_update_fail_before_assembly(self):
        f = self.f
        changed = deepcopy(f.original)
        changed['generation_sha'] = '0' * 40
        with patch.object(source, 'CONFIG', f.config), self.assertRaisesRegex(ValueError, 'lineage'):
            candidate._source_correction_inputs(f.root, changed, f.receipt, f.export)
        without_groups = deepcopy(f.policy)
        del without_groups['dependency_groups']
        f.write(candidate.POLICY, without_groups)
        with self.assertRaisesRegex(ValueError, 'complete dependency policy'):
            f.create()
        f.write(candidate.POLICY, f.policy)
        for options in (
            {'source_correction': f.receipt, 'source_export': f.export},
            {'parent': f.bundle, 'source_correction': f.receipt},
            {'parent': f.bundle, 'team_update': True, 'source_correction': f.receipt, 'source_export': f.export},
        ):
            with self.subTest(options=sorted(options)), self.assertRaisesRegex(ValueError, 'original candidate and exact export only'):
                candidate.create(f.root, f.base / 'invalid', **options)
        self.assertFalse((f.base / 'invalid').exists())

    def test_ordinary_reuse_does_not_get_source_bypass_and_preserves_corrected_lineage(self):
        f = self.f
        with self.assertRaisesRegex(ValueError, 'dependency mismatch'):
            candidate.create(f.root, f.base / 'not-authorized', parent=f.bundle, run_id='901')
        corrected = f.create()
        candidate.verify_dependencies(f.root, corrected)
        f.write('index.html', '<main>Runtime update only</main>')
        f.commit()
        with self.assertRaisesRegex(ValueError, 'Release runtime changed'):
            candidate.materialize(f.root, f.output)
        derived = candidate.create(f.root, f.base / 'derived', parent=f.output, run_id='901')
        for key in ('source_correction', 'original_generation', 'generation_files',
                    'generation_dependencies', 'semantic_identity', 'team_identity'):
            self.assertEqual(derived[key], corrected[key], key)
        self.assertEqual(derived['derived_from_candidate'], corrected['candidate_id'])
        self.assertEqual(derived['generation_sha'], f.original_sha)
        self.assertNotEqual(derived['files']['index.html'], corrected['files']['index.html'])
        self.assertNotIn('team_generation', derived)
        candidate.verify_dependencies(f.root, derived)
        candidate.git(f.root, 'restore', '--source=HEAD', '--worktree', '--', *derived['files'])
        self.assertEqual(candidate.materialize(f.root, f.base / 'derived'), derived)
        candidate.verify_dependencies(f.root, derived)
        candidate.verify_files(f.root, derived['files'])

    def test_clean_current_checkout_materializes_corrected_candidate_with_distinct_git_seeds(self):
        f = self.f
        corrected = f.create()
        name = 'data/source_records.json'
        self.assertEqual(len({f.original['generation_baseline'][name],
            corrected['generation_baseline'][name], corrected['files'][name]}), 3)
        candidate.git(f.root, 'restore', '--source=HEAD', '--worktree', '--', *corrected['files'])
        self.assertEqual(candidate.git(f.root, 'status', '--porcelain'), '')
        self.assertEqual(candidate.digest((f.root / name).read_bytes()), corrected['generation_baseline'][name])
        candidate.verify_dependencies(f.root, corrected)
        self.assertEqual(candidate.materialize(f.root, f.output), corrected)
        candidate.verify_dependencies(f.root, corrected)
        candidate.verify_files(f.root, corrected['files'])
        self.assertEqual((f.bundle / candidate.MANIFEST).read_bytes(), f.original_bytes)

    def test_unrelated_generation_commit_is_rejected_even_with_consistent_lineage_fields(self):
        f = self.f
        tree = candidate.git(f.root, 'rev-parse', 'HEAD^{tree}')
        unrelated = candidate.git(f.root, 'commit-tree', tree, '-m', 'Unrelated synthetic root')
        original = deepcopy(f.original)
        original['generation_sha'] = unrelated
        plan = dict(f.plan) | {'prior_sha': unrelated}
        candidate.write_json(f.config, plan)
        receipt = dict(f.receipt) | {'source_plan_sha256': candidate.digest(f.config.read_bytes())}
        with patch.object(source, 'CONFIG', f.config), self.assertRaises(subprocess.CalledProcessError):
            candidate._source_correction_inputs(f.root, original, receipt, f.export)
        self.assertEqual(candidate.git(f.root, 'rev-parse', 'HEAD'), f.current_sha)

    def test_plain_candidate_remains_plain_without_fixed_correction_metadata(self):
        f = self.f
        self.assertNotIn('source_correction', f.original)
        self.assertNotIn('original_generation', f.original)
        self.assertNotIn('derived_from_candidate', f.original)
        self.assertEqual(f.original['generation_sha'], f.original_sha)
        self.assertEqual(f.original['generation_run_id'], '123')
        self.assertEqual(f.original['generation_files']['data/document_evidence.json'],
            candidate.digest((f.bundle / 'files/data/document_evidence.json').read_bytes()))

    def test_live_provenance_routes_only_exact_correction_version_to_fixed_adapter(self):
        f = self.f
        f.create()
        reports = f.base / 'reports'
        commands = []
        def execute(command, **kwargs):
            commands.append((command, kwargs))
            candidate.write_json(reports / 'worker-live.json', {'verified': True, 'synthetic': True})
            return subprocess.CompletedProcess(command, 0)
        with patch.object(source, 'CONFIG', f.config), \
                patch('tools.catalog_correction_release.correction_completion', return_value=None), \
                patch.object(live.subprocess, 'run', side_effect=execute):
            self.assertTrue(live.worker_provenance(f.output, reports)['verified'])
            self.assertTrue(live.worker_provenance(f.bundle, reports)['verified'])
        self.assertEqual(commands[0][0], ['python', '-m', 'tools.catalog_correction_release',
            'verify-worker', '--bundle', str(f.output), '--reports', str(reports)])
        self.assertEqual(commands[1][0], ['node', str(candidate.ROOT / 'tools/search_worker_checkpoint.mjs'),
            '--verify-live', str(f.bundle), str(reports / 'worker-after.json'), str(reports / 'worker-live.json')])
        self.assertEqual(commands[0][1], {'capture_output': True, 'text': True, 'timeout': 600})
        # A similar-looking unrecognized version cannot fall back to a paid route.
        manifest = candidate.load(f.output)
        manifest['source_correction']['version'] += '-other'
        manifest['candidate_id'] = candidate.digest(candidate.encoded({k: v for k, v in manifest.items() if k != 'candidate_id'}))
        candidate.write_json(f.output / candidate.MANIFEST, manifest)
        with patch.object(live.subprocess, 'run', side_effect=execute) as called:
            with self.assertRaisesRegex(RuntimeError, 'known_source_correction'):
                live.worker_provenance(f.output, reports)
            called.assert_not_called()
        # A proved ordinary successor uses the same shared routing decision.
        with patch('tools.catalog_correction_release.requires_owned_smoke', return_value=False), \
                patch.object(live.subprocess, 'run', side_effect=execute):
            live.worker_provenance(f.output, reports)
        self.assertEqual(commands[-1][0][0], 'node')

    def test_live_adapter_failure_cannot_be_hidden_by_an_old_success_receipt(self):
        f = self.f
        f.create()
        reports = f.base / 'reports'
        candidate.write_json(reports / 'worker-live.json', {'verified': True})
        with patch.object(source, 'CONFIG', f.config), \
                patch('tools.catalog_correction_release.correction_completion', return_value=None), \
                patch.object(live.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as call:
            with self.assertRaisesRegex(ValueError, 'Worker provenance verification failed'):
                live.worker_provenance(f.output, reports)
        self.assertEqual(call.call_count, 1)
        for value in ({}, {'verified': False}, {'verified': 1}):
            candidate.write_json(reports / 'worker-live.json', value)
            with patch.object(source, 'CONFIG', f.config), \
                    patch('tools.catalog_correction_release.correction_completion', return_value=None), \
                    patch.object(live.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaisesRegex(ValueError, 'Worker provenance verification failed'):
                    live.worker_provenance(f.output, reports)


class RetainedOriginalCandidate(unittest.TestCase):
    def test_downloaded_original_has_126_payload_files_plus_its_manifest_when_present(self):
        default = candidate.ROOT.parent / 'catalog-source-correction/outputs/prep-v4/original-candidate'
        bundle = Path(os.environ.get('CATALOG_ORIGINAL_CANDIDATE', default))
        if not bundle.is_dir():
            self.skipTest('Previously downloaded original public candidate is not present')
        before = (bundle / candidate.MANIFEST).read_bytes()
        plan = source.plan()
        value = candidate.load(bundle, plan['candidate_id'])
        self.assertEqual(value['candidate_id'], 'ccbef93b9c8ddc152704202858f371737c559ff2a46c7411f84bc5f17c38064a')
        self.assertEqual(value['generation_sha'], plan['prior_sha'])
        self.assertEqual(value['generation_run_id'], plan['candidate_run'])
        self.assertEqual(len(value['files']), 126)
        self.assertEqual(len(value['files']) + 1, 127)  # The archive includes candidate.json.
        self.assertNotIn('source_correction', value)
        for name in ('data/opportunities.js', 'data/source_records.json'):
            self.assertEqual(value['files'][name], plan['source_pins']['candidate/' + name])
        self.assertEqual((bundle / candidate.MANIFEST).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
