"""Access-projection constructor contracts using isolated Git and no providers."""
from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from tests import test_release_candidate as fixtures
from tools import release_candidate as c


class AccessCandidateTests(unittest.TestCase):
    def setUp(self):
        # Reuse repository setup only, never the unrelated manual-browser tests.
        self.fixture = fixtures.CandidateLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.policy = deepcopy(self.fixture.policy)
        self.policy['generation_contract'].update(python='3.13', node='22')
        self.policy['dependency_groups'] = {
            'source': {'patterns': ['scripts/parser.py', 'config/source.json'], 'excluded': []},
            'teams': {'patterns': ['scripts/teams.py'], 'excluded': []},
            'semantic': {'patterns': ['tools/vectors.mjs'], 'excluded': []},
            'runtime': {'patterns': self.policy['runtime'], 'excluded': []},
            'validation': {'patterns': self.policy['validation'] + [c.POLICY], 'excluded': []},
        }
        c.write_json(self.root / c.POLICY, self.policy)
        (self.root / '.github/workflows/refresh-opportunities.yml').write_text(
            'jobs:\n  generate:\n    steps:\n'
            '      - run: python -m scripts.parser\n'
            '      - run: node tools/build_search_v2_voyage_vectors.mjs --production --write\n', encoding='utf8')
        self.fixture.commit()
        self.fixture.source_sha = c.git(self.root, 'rev-parse', 'HEAD')
        first = self.fixture.create()
        self.parent = deepcopy(first)
        self.parent['original_generation'] = {key: deepcopy(first[key]) for key in (
            'generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
            'generation_dependencies', 'generation_baseline', 'generation_files', 'semantic_identity')}
        # The original pre-withdrawal catalog is distinct from this retained child.
        self.parent['original_generation']['generation_files']['data/opportunities.js'] = 'a' * 64
        self.parent['source_recovery'] = {'version': 'source-recovery-fixture',
            'parent_candidate': 'b' * 64, 'spending': {'original_logical_id': 'offline-123',
                'limit_microusd': 2_000_000, 'max_requests': 300,
                'requests_used': 66, 'charged_microusd': 441023, 'new_team_requests': 0}}
        self.parent.pop('candidate_id')
        self.parent['candidate_id'] = c.digest(c.encoded(self.parent))
        c.write_json(self.fixture.bundle / c.MANIFEST, self.parent)
        self.parent_bytes = (self.fixture.bundle / c.MANIFEST).read_bytes()
        self.receipt = Path(self.fixture.temp.name) / 'access-receipt.json'
        self.receipt_value = {'version': 'access-correction-fixture',
            'parent_candidate_id': self.parent['candidate_id'], 'provider_requests': 0,
            'source_requests': 0, 'ledger_writes': 0}
        c.write_json(self.receipt, self.receipt_value)
        self.retained = {name: value for name, value in self.parent['generation_files'].items()
                         if name != 'data/opportunities.js'}
        # Authentication itself has separate tests; this seam exercises the real
        # constructor and proves it delegates before accepting any changed bytes.
        self.helper = ModuleType('tools.catalog_access_correction')
        self.helper.verify_inputs = Mock(side_effect=self.verified_inputs)
        self.helper.reject_quarantined = Mock()
        self.modules = patch.dict(sys.modules, {'tools.catalog_access_correction': self.helper})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def verified_inputs(self, root, original, parent_bundle, receipt_path):
        self.assertEqual(Path(root), self.root)
        self.assertEqual(original, self.parent)
        self.assertEqual(Path(parent_bundle), self.fixture.bundle)
        self.assertEqual(Path(receipt_path), self.receipt)
        if c.read_json(receipt_path) != self.receipt_value:
            raise ValueError('Exact access receipt required')
        return self.retained

    def update_source(self):
        (self.root / 'scripts/parser.py').write_text('VERSION = 2\n', encoding='utf8')
        self.fixture.commit()
        self.sha = c.git(self.root, 'rev-parse', 'HEAD')
        (self.root / 'data/opportunities.js').write_text('invitation-qualified-catalog', encoding='utf8')

    def corrected(self, name='corrected'):
        bundle = Path(self.fixture.temp.name) / name
        value = c.create(self.root, bundle, parent=self.fixture.bundle,
                         access_correction=self.receipt, run_id='456', attempt='1')
        return bundle, value

    def test_preserves_original_science_owner_prior_proof_and_teams(self):
        self.update_source()
        bundle, value = self.corrected()
        self.helper.verify_inputs.assert_called_once_with(self.root, self.parent, self.fixture.bundle, self.receipt)
        for key in ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
                    'team_identity', 'semantic_identity', 'release_identity', 'worker_fingerprint',
                    'source_recovery', 'original_generation'):
            self.assertEqual(value[key], self.parent[key], key)
        self.assertEqual(value['derived_from_candidate'], self.parent['candidate_id'])
        self.assertEqual(value['assembly_sha'], self.sha)
        self.assertEqual(value['generation_dependencies'], c.generation_dependencies(self.root))
        self.assertNotEqual(value['dependency_groups']['source'], self.parent['dependency_groups']['source'])
        for group in ('teams', 'semantic', 'runtime'):
            self.assertEqual(value['dependency_groups'][group], self.parent['dependency_groups'][group], group)
        self.assertEqual(value['generation_files']['data/opportunities.js'], c.digest(b'invitation-qualified-catalog'))
        proof = value['access_correction']
        self.assertEqual(proof['parent_candidate_id'], self.parent['candidate_id'])
        self.assertEqual(proof['retained_output_hashes'], self.retained)
        self.assertEqual(proof['affected_generation']['generation_sha'], self.sha)
        self.assertEqual(proof['affected_generation']['generation_run_id'], '456')
        self.assertEqual(proof['affected_output_hashes'],
                         {'data/opportunities.js': c.digest(b'invitation-qualified-catalog')})
        self.assertEqual((self.fixture.bundle / c.MANIFEST).read_bytes(), self.parent_bytes)
        self.assertEqual(c.load(bundle), value)
        c.verify_dependencies(self.root, value)
        self.helper.reject_quarantined.assert_called_once_with(value)

    def test_runtime_descendant_carries_complete_access_and_original_lineage(self):
        self.update_source()
        bundle, corrected = self.corrected()
        (self.root / 'assets/app.css').write_text('main { color: blue; }', encoding='utf8')
        child = c.create(self.root, Path(self.fixture.temp.name) / 'runtime-child',
                         parent=bundle, run_id='789', attempt='1')
        for key in ('access_correction', 'source_recovery', 'original_generation', 'generation_files',
                    'generation_dependencies', 'generation_sha', 'generation_run_id', 'generation_run_attempt',
                    'generation_timestamp', 'team_identity', 'semantic_identity'):
            self.assertEqual(child[key], corrected[key], key)
        self.assertEqual(child['derived_from_candidate'], corrected['candidate_id'])
        self.assertNotEqual(child['files']['assets/app.css'], corrected['files']['assets/app.css'])
        c.verify_dependencies(self.root, child)

    def test_missing_parent_or_other_generation_modes_are_rejected_before_verifier(self):
        options = [{}, {'parent': self.fixture.bundle, 'team_update': True},
                   {'parent': self.fixture.bundle, 'source_correction': {}},
                   {'parent': self.fixture.bundle, 'source_export': self.receipt},
                   {'parent': self.fixture.bundle, 'source_recovery': self.receipt},
                   {'parent': self.fixture.bundle, 'identity_correction': self.receipt},
                   {'parent': self.fixture.bundle, 'program_area_revalidation': self.receipt}]
        for index, kwargs in enumerate(options):
            with self.subTest(options=kwargs), self.assertRaisesRegex(ValueError, '(?:Access|Identity) correction requires its exact parent'):
                c.create(self.root, Path(self.fixture.temp.name) / f'invalid-{index}',
                         access_correction=self.receipt, **kwargs)
        self.helper.verify_inputs.assert_not_called()

    def test_invalid_receipt_and_changed_retained_science_fail_closed(self):
        self.update_source()
        c.write_json(self.receipt, self.receipt_value | {'parent_candidate_id': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'Exact access receipt required'):
            self.corrected('invalid-receipt')
        c.write_json(self.receipt, self.receipt_value)
        for index, name in enumerate(self.retained):
            with self.subTest(path=name):
                target = self.root / name
                original = target.read_bytes()
                target.write_bytes(b'changed-retained-science')
                with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
                    self.corrected(f'invalid-retained-{index}')
                target.write_bytes(original)

    def test_ordinary_reuse_still_rejects_changed_source_or_generated_bytes(self):
        (self.root / 'scripts/parser.py').write_text('VERSION = 2\n', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'dependency mismatch'):
            c.create(self.root, Path(self.fixture.temp.name) / 'ordinary-source', parent=self.fixture.bundle)
        (self.root / 'scripts/parser.py').write_text('VERSION = 1\n', encoding='utf8')
        (self.root / 'data/opportunities.js').write_text('unapproved-output', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'Generation data input changed'):
            c.create(self.root, Path(self.fixture.temp.name) / 'ordinary-data', parent=self.fixture.bundle)
        self.helper.verify_inputs.assert_not_called()

    def test_quarantine_applies_to_dependency_reader_materialization_and_ordinary_reuse(self):
        self.helper.reject_quarantined.side_effect = ValueError('Rejected access parent')
        calls = [lambda: c.verify_dependencies(self.root, self.parent),
                 lambda: c.materialize(self.root, self.fixture.bundle),
                 lambda: c.create(self.root, Path(self.fixture.temp.name) / 'quarantined', parent=self.fixture.bundle)]
        for call in calls:
            with self.assertRaisesRegex(ValueError, 'Rejected access parent'):
                call()
        self.assertEqual(self.helper.reject_quarantined.call_count, 3)
        self.helper.verify_inputs.assert_not_called()


if __name__ == '__main__':
    unittest.main()
