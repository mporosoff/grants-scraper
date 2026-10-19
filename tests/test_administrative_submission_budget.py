"""Typed cached-deadline continuations conserve accepted accounting and assets."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_modern_program_area_budget as fixtures
from tools import program_area_revalidation as p, catalog_reconcile_spend as spend, release_candidate as c
from tools.offline_spend import atomic_json, identity


class AdministrativeSubmissionBudget(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ModernProgramAreaBudget()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture

    @contextmanager
    def environment(self, *, current='456', changed=False):
        f = self.f
        outputs = {n: ('qualified deadlines ' + n).encode() for n in p.PROJECTION}
        packet = dict(f.packet, retained_asset_eligible=not changed)
        if changed:
            packet['corpus_sha256'] = '8' * 64
        with patch.dict('os.environ', GITHUB_RUN_ID=current, GITHUB_RUN_ATTEMPT='1',
                GITHUB_SHA=f.runs[(current, '1')]['head_sha']), \
                patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6' * 64}), \
                patch.object(p, 'modern_projection', return_value=(outputs, {'projection_kind': 'administrative_submission',
                    'source_requests': 0, 'document_ai_requests': 0, 'team_requests': 0})), \
                patch.object(p, 'vector_packet', return_value=packet):
            yield

    def prepare(self, state, *, current='456', changed=False, output=None):
        with self.environment(current=current, changed=changed):
            return p.prepare_modern(self.f.bundle, self.f.root / 'receipt.json', state, '123', self.f.cid,
                root=self.f.root, api=self.f.api, output=output, projection_kind='administrative_submission')

    def test_prepare_seals_kind_and_original_requests_without_new_paid_work(self):
        f = self.f
        state = f.root / 'admin-state'
        result = self.prepare(state)
        value = spend.context(state)
        self.assertEqual(result['vector_reused'], 'true')
        self.assertEqual(value['projection_kind'], 'administrative_submission')
        self.assertEqual(value['retained_requests'], p.retained_requests(f.original))
        self.assertEqual(p.read(result['reservation_path'])['projection_kind'], 'administrative_submission')
        self.assertEqual(p.read(f.root / 'receipt.json')['projection_kind'], 'administrative_submission')
        self.assertEqual(spend.ledger(state).read()['requests'], f.original['requests'])
        self.assertEqual({name: p.sha((f.root / name).read_bytes()) for name in p.VECTORS},
            {name: p.sha(f.raw[name]) for name in p.VECTORS})
        f.http.assert_not_called()

    def test_changed_corpus_cannot_open_a_new_task_reservation(self):
        state = self.f.root / 'changed-corpus'
        with self.assertRaisesRegex(ValueError, 'administrative_exact_retained_vectors'):
            self.prepare(state, changed=True)
        self.assertFalse((state / 'reservation.json').exists())
        self.assertEqual(spend.ledger(state).read()['requests'], self.f.original['requests'])
        self.f.http.assert_not_called()

    def test_unknown_kind_rejected_before_checkpoint_or_authentication(self):
        for kind in ('unknown', '', False):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'projection_kind'):
                p.prepare_modern(self.f.bundle, self.f.root / 'receipt.json', self.f.root / 'invalid',
                    '123', self.f.cid, root=self.f.root, api=lambda _: self.fail('must fail before API'),
                    projection_kind=kind)
        self.assertFalse((self.f.root / 'invalid').exists())

    def test_default_old_kind_keeps_old_operation_input_contract(self):
        self.assertEqual(p.projection_kind({}), 'program_area')
        for invalid in (None, False, '', 'future_projection'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'projection_kind'):
                p.projection_kind({'projection_kind': invalid})
        with patch.object(p, 'hashes', return_value={}) as hashed:
            p.modern_contract(self.f.root)
            self.assertEqual(hashed.call_args.args[1], p.MODERN_OPERATION_FILES)
            p.modern_contract(self.f.root, 'administrative_submission')
            self.assertEqual(set(hashed.call_args.args[1]) - set(p.MODERN_OPERATION_FILES),
                {'tools/administrative_submission_revalidation.py', 'scripts/submission_schedule.py',
                 'scripts/build_catalog.py', 'assets/submission-schedule.js'})

    def test_cold_checkpoint_rejects_other_projection_kind_before_projection(self):
        f = self.f; state = f.root / 'first'
        result = self.prepare(state)
        f.runs[('456', '1')]['status'] = 'completed'
        f.add_artifact(result['reservation_artifact'], '456',
            {'reservation.json': Path(result['reservation_path']).read_bytes()})
        f.add_artifact(result['state_artifact'], '456', f.state_files(state))
        with self.assertRaisesRegex(ValueError, 'projection_kind_mismatch'):
            p.modern_history(f.bundle, f.root / 'wrong-kind', f.root, 'owner/repo', '123', f.cid, f.api)
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        result2 = self.prepare(f.root / 'restored', current='789')
        self.assertEqual(result2['vector_reused'], 'true')
        self.assertEqual(spend.ledger(f.root / 'restored').read()['requests'], f.original['requests'])

    def test_checkpoint_rejects_mismatched_receipt_or_added_request(self):
        f = self.f; state = f.root / 'first'
        self.prepare(state)
        receipt_path = f.root / 'receipt.json'; receipt = p.read(receipt_path)
        wrong = deepcopy(receipt); wrong['projection_kind'] = 'program_area'; atomic_json(receipt_path, wrong)
        with self.environment(), self.assertRaisesRegex(ValueError, 'projection_kind_mismatch'):
            p.checkpoint_modern(receipt_path, state, root=f.root)
        atomic_json(receipt_path, receipt)
        spend.ledger(state).reserve('voyage', spend.MODEL, 'reconciled_vectors', 'bad', 100, 1)
        with self.environment(), self.assertRaisesRegex(ValueError, 'administrative_requests_unchanged'):
            p.checkpoint_modern(receipt_path, state, root=f.root)
        f.http.assert_not_called()

    def test_completed_child_reuses_exact_kind_receipt_and_no_second_reservation(self):
        f = self.f; state = f.root / 'first'; prepared = self.prepare(state)
        with self.environment():
            receipt = p.checkpoint_modern(f.root / 'receipt.json', state, root=f.root)
        child = deepcopy(f.manifest); child.pop('candidate_id')
        child['derived_from_candidate'] = f.cid
        child['program_area_revalidation'] = receipt | {'affected_generation': {
            'generation_run_id': '456', 'generation_run_attempt': '1', 'generation_sha': 'e' * 40}}
        child['candidate_id'] = c.digest(c.encoded(child))
        bundle = f.root / 'complete'
        (bundle / 'files').mkdir(parents=True)
        (bundle / 'candidate.json').write_bytes(c.encoded(child))
        for name, raw in f.raw.items():
            target = bundle / 'files' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        p.record_modern_candidate(state, bundle)
        f.add_artifact('candidate-' + child['candidate_id'], '456', {'candidate.json': c.encoded(child),
            **{'files/' + n: raw for n, raw in f.raw.items()}})
        f.add_artifact(prepared['reservation_artifact'], '456', {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        f.add_artifact(prepared['state_artifact'], '456', f.state_files(state))
        f.runs[('456', '1')]['status'] = 'completed'
        f.runs[('789', '1')] = f.run_meta('789', '1', '9' * 40, current=True)
        with patch.object(c, 'verify_dependencies'):
            result = self.prepare(f.root / 'cold', current='789', output=f.root / 'restored-child')
        self.assertEqual(result['candidate_id'], child['candidate_id'])
        self.assertEqual(result['artifact_run'], '456')
        self.assertEqual(result['upload_candidate'], 'false')
        self.assertFalse((f.root / 'cold-reservation').exists())
        self.assertEqual(spend.ledger(f.root / 'cold').read()['requests'], f.original['requests'])
        self.assertEqual((f.root / 'restored-child/candidate.json').read_bytes(), (bundle / 'candidate.json').read_bytes())

    def test_scope_allows_only_admin_selection_semantics(self):
        base = {group: {'files': {'unchanged': 'a'}, 'sha256': 'a'} for group in ('source', 'teams', 'semantic')}
        original = {'generation_sha': 'a' * 40, 'dependency_groups': base}
        selected = deepcopy(base)
        selected['source']['files']['scripts/submission_schedule.py'] = 'b'
        selected['semantic']['files']['assets/submission-schedule.js'] = 'b'
        with patch('tools.release_dependencies.snapshot', return_value=selected):
            p.modern_scope(self.f.root, original, 'administrative_submission')
            with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                p.modern_scope(self.f.root, original)
        for group, name in [('source', 'scripts/notice_schedule.py'), ('semantic', 'assets/search-hybrid.js'),
                            ('teams', 'scripts/build_opportunity_teams.py')]:
            changed = deepcopy(selected); changed[group]['files'][name] = 'b'
            with self.subTest(group=group), patch('tools.release_dependencies.snapshot', return_value=changed):
                with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                    p.modern_scope(self.f.root, original, 'administrative_submission')


if __name__ == '__main__':
    unittest.main()
