"""Protected administrative continuations retire only their exact unpaid replay."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tests import test_program_area_history as fixtures
from tools import program_area_revalidation as p, program_area_history as h, scheduled_catalog as daily
from tools.offline_spend import identity


class AdministrativeSubmissionHistory(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ModernHistory(methodName='runTest')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        f = self.f
        f.context.update(projection_kind='administrative_submission', retained_requests=p.retained_requests(f.ledger))
        f.context['operation_sha256'] = identity({k: v for k, v in f.context.items()
            if k not in {'operation_sha256', 'completed_candidate_id'}})
        f.receipt.update(projection_kind='administrative_submission', retained_requests=f.context['retained_requests'],
            operation_sha256=f.context['operation_sha256'])
        f.voucher.update(projection_kind='administrative_submission', operation_sha256=f.context['operation_sha256'])
        f.child.pop('candidate_id')
        f.child['candidate_id'] = daily.c.digest(daily.c.encoded(f.child))
        f.context['completed_candidate_id'] = f.child['candidate_id']
        f.pointer['candidate_id'] = f.child['candidate_id']
        for name in list(f.state):
            if name.startswith('complete-candidates/'):
                f.state.pop(name)
        f.state['complete-candidates/' + f.child['candidate_id'] + '/candidate.json'] = f.child
        f.artifacts[-1]['name'] = 'candidate-' + f.child['candidate_id']
        f.native_artifacts[:] = deepcopy(f.artifacts)

    def test_exact_typed_native_checkpoint_and_later_state_only_restore_retire(self):
        self.assertTrue(self.f.retire())
        self.f.state_only_restorer()
        with patch.object(h, 'completed_restore') as restored:
            self.assertTrue(self.f.retire())
            restored.assert_called_once()

    def test_absent_or_other_voucher_kind_cannot_claim_admin_receipt(self):
        for kind in (None, 'program_area', 'future_projection'):
            with self.subTest(kind=kind):
                if kind is None:
                    self.f.voucher.pop('projection_kind', None)
                else:
                    self.f.voucher['projection_kind'] = kind
                with self.assertRaisesRegex(daily.Hold, 'projection_kind'):
                    self.f.retire()

    def test_unknown_protected_receipt_kind_remains_held(self):
        self.f.receipt['projection_kind'] = 'future_projection'
        self.f.child.pop('candidate_id')
        self.f.child['candidate_id'] = daily.c.digest(daily.c.encoded(self.f.child))
        self.f.pointer['candidate_id'] = self.f.child['candidate_id']
        with self.assertRaises(daily.Hold):
            self.f.retire()

    def test_added_private_request_cannot_be_retired_even_if_receipt_ledger_hash_matches(self):
        self.f.ledger['requests'].append({'id': 'new-paid', 'charged_microusd': 1})
        self.f.receipt['ledger_sha256'] = identity(self.f.ledger)
        with self.assertRaises(daily.Hold):
            self.f.retire()


if __name__ == '__main__':
    unittest.main()
