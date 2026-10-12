"""Real constructor contracts for a URL-only child of an identity-corrected parent."""
from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
from tests import test_catalog_identity_candidate as fixtures
from tools import release_candidate as c


class UrlCandidateTests(unittest.TestCase):
    def setUp(self):
        # Reuse only isolated repository setup, not another class's test methods.
        self.base = fixtures.IdentityCandidateTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        b = self.base
        b.parent['identity_correction'] = {'version': 'prior-identity-proof', 'parent_candidate': 'e' * 64,
                                           'spending': {'requests_used': 0, 'prior_vector_requests': 6}}
        b.parent.pop('candidate_id')
        b.parent['candidate_id'] = c.digest(c.encoded(b.parent))
        c.write_json(b.fixture.bundle / c.MANIFEST, b.parent)
        b.parent_bytes = (b.fixture.bundle / c.MANIFEST).read_bytes()
        b.receipt_value = {'version': 'url-correction-fixture', 'parent_candidate_id': b.parent['candidate_id'],
                           'source_requests': 0, 'provider_requests': 0}
        c.write_json(b.receipt, b.receipt_value)
        self.helper = ModuleType('tools.catalog_url_correction')
        self.helper.verify_inputs = Mock(side_effect=b.verified_inputs)
        self.helper.reject_quarantined = Mock()
        modules = patch.dict(sys.modules, {'tools.catalog_url_correction': self.helper})
        modules.start(); self.addCleanup(modules.stop)

    def corrected(self, name='url-child'):
        b = self.base
        bundle = Path(b.fixture.temp.name) / name
        return bundle, c.create(b.root, bundle, parent=b.fixture.bundle, url_correction=b.receipt,
                                run_id='url-run', attempt='1')

    def test_preserves_identity_receipt_original_science_and_paid_accounting(self):
        b = self.base; b.update_source()
        bundle, child = self.corrected()
        for key in ('identity_correction', 'source_recovery', 'access_correction', 'original_generation',
                    'generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
                    'team_identity', 'semantic_identity', 'release_identity'):
            self.assertEqual(child[key], b.parent[key], key)
        self.assertEqual(child['derived_from_candidate'], b.parent['candidate_id'])
        self.assertEqual(child['url_correction']['parent_candidate_id'], b.parent['candidate_id'])
        self.assertEqual(child['url_correction']['retained_output_hashes'], b.retained)
        self.helper.verify_inputs.assert_called_once()
        self.assertEqual(c.load(bundle), child)
        self.assertEqual((b.fixture.bundle / c.MANIFEST).read_bytes(), b.parent_bytes)
        c.verify_dependencies(b.root, child)
        self.helper.reject_quarantined.assert_called_once_with(child)

    def test_runtime_descendant_keeps_both_receipts_and_original_lineage(self):
        b = self.base; b.update_source(); bundle, child = self.corrected()
        (b.root / 'assets/app.css').write_text('body {color:blue}', encoding='utf8')
        descendant = c.create(b.root, Path(b.fixture.temp.name) / 'runtime', parent=bundle,
                              run_id='runtime-run', attempt='1')
        for key in ('identity_correction', 'url_correction', 'original_generation', 'source_recovery',
                    'generation_files', 'generation_dependencies', 'team_identity', 'semantic_identity'):
            self.assertEqual(descendant[key], child[key], key)
        c.verify_dependencies(b.root, descendant)

    def test_url_mode_cannot_mix_generation_or_skip_parent_authentication(self):
        b = self.base
        options = [{}, {'parent': b.fixture.bundle, 'team_update': True}]
        for key in ('identity_correction', 'access_correction', 'source_recovery', 'source_correction',
                    'source_export', 'program_area_revalidation'):
            options.append({'parent': b.fixture.bundle, key: b.receipt})
        for i, kwargs in enumerate(options):
            with self.assertRaisesRegex(ValueError, 'URL correction requires its exact parent'):
                c.create(b.root, Path(b.fixture.temp.name) / f'invalid-{i}', url_correction=b.receipt, **kwargs)
        self.helper.verify_inputs.assert_not_called()

    def test_quarantine_blocks_dependency_reader_materialization_and_ordinary_reuse(self):
        b = self.base
        self.helper.reject_quarantined.side_effect = ValueError('Rejected URL parent')
        calls = [lambda: c.verify_dependencies(b.root, b.parent),
                 lambda: c.materialize(b.root, b.fixture.bundle),
                 lambda: c.create(b.root, Path(b.fixture.temp.name) / 'quarantined', parent=b.fixture.bundle)]
        for call in calls:
            with self.assertRaisesRegex(ValueError, 'Rejected URL parent'):
                call()
        self.assertEqual(self.helper.reject_quarantined.call_count, 3)
        self.helper.verify_inputs.assert_not_called()

    def test_invalid_receipt_and_retained_science_drift_fail_closed(self):
        b = self.base; b.update_source()
        c.write_json(b.receipt, b.receipt_value | {'parent_candidate_id': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'Exact identity receipt required'):
            self.corrected('invalid-receipt')
        c.write_json(b.receipt, b.receipt_value)
        path = b.root / next(iter(b.retained)); path.write_bytes(b'changed-science')
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
            self.corrected('invalid-science')


if __name__ == '__main__':
    unittest.main()
