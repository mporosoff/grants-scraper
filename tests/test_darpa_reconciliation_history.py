"""DARPA repair publication retires only its exact, source-bound budget owner."""
from copy import deepcopy
import io
import json
import unittest
import zipfile

import test_scheduled_reconciliation as owner_fixture
import test_scheduled_reconciliation_rerun_integration as history_fixture
from tools import release_candidate as candidate, scheduled_catalog as scheduled
from tools.offline_spend import identity


class DarpaReconciliationHistory(unittest.TestCase):
    def owner(self, source):
        fixture = owner_fixture.CorrectedOwner()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.child['source_reconciliation']['source_slug'] = source
        return fixture

    def history(self, *, source='darpa-iarpa', context_source='darpa-iarpa'):
        fixture = history_fixture.PublishedReconciliationHistory()
        fixture.setUpClass()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.fixture(producer_attempt=1, consumed=False)
        if context_source is not None:
            fixture.context['source_slug'] = context_source
        fixture.context.pop('operation_sha256')
        fixture.context['operation_sha256'] = identity(fixture.context)
        fixture.child['source_reconciliation'].update(fixture.context, source_slug=source)
        fixture.child.pop('candidate_id')
        fixture.child['candidate_id'] = candidate.digest(candidate.encoded(fixture.child))
        fixture.pointer['candidate_id'] = fixture.child['candidate_id']
        fixture.own_marker['operation_sha256'] = fixture.context['operation_sha256']
        fixture.artifacts.clear()
        fixture.payloads.clear()
        family = 'offline-ai-reconcile-' + fixture.PARENT
        fixture.own_reservation = fixture.artifact(220, family + '-reservation-220-1',
            {'reservation.json': fixture.own_marker})
        fixture.own_state = fixture.artifact(220, family + '-state-220-1', {
            'ledger.json': fixture.ledger, 'reservation.json': fixture.own_marker,
            'reconciliation.json': fixture.context | {'completed_candidate_id': fixture.child['candidate_id']},
            'complete-candidates/' + fixture.child['candidate_id'] + '/candidate.json': fixture.child})
        fixture.own_candidate = fixture.artifact(220, 'candidate-' + fixture.child['candidate_id'],
            {'candidate.json': fixture.child})
        return fixture

    @staticmethod
    def transport(fixture):
        fixture.metadata[220, 1]['conclusion'] = 'failure'
        for job in fixture.job_rows[220, 1]:
            if job['name'] == 'catalog-reconcile':
                job['conclusion'] = 'failure'
        fixture.artifacts[220] = [row for row in fixture.artifacts[220]
                                 if row['id'] != fixture.own_candidate['id']]
        fixture.meta(250, 1)
        for job in fixture.job_rows[250, 1]:
            if job['name'] == 'catalog-reconcile':
                job['steps'] = fixture.completed_restore_steps(native_upload=True)
        with zipfile.ZipFile(io.BytesIO(fixture.payloads[fixture.own_state['id']])) as archive:
            state = {name: json.loads(archive.read(name)) for name in archive.namelist()}
        fixture.transport_state = fixture.artifact(250,
            'offline-ai-reconcile-' + fixture.PARENT + '-state-250-1', state)
        fixture.artifact(250, 'candidate-' + fixture.child['candidate_id'], {'candidate.json': fixture.child})
        fixture.pointer['artifact_run'] = '250'

    def test_supported_sources_retire_exact_original_and_consumed_owners(self):
        for source in ('sam-gov', 'darpa-iarpa'):
            with self.subTest(source=source):
                fixture = self.owner(source)
                self.assertTrue(fixture.check())
                fixture.consumed(candidate=True)
                self.assertTrue(fixture.check_consumed())

    def test_unknown_or_missing_receipt_source_never_retires_an_owner(self):
        for source in ('unknown-source', None):
            with self.subTest(source=source):
                fixture = self.owner(source)
                with self.assertRaises(scheduled.Hold):
                    fixture.check()
                fixture.consumed(candidate=True)
                with self.assertRaises(scheduled.Hold):
                    fixture.check_consumed()

    def test_darpa_producer_retains_original_generation_and_accounting(self):
        fixture = self.history()
        before = deepcopy(fixture.ledger)
        self.assertIsNone(fixture.select())
        self.assertEqual(fixture.child['generation_run_id'], '100')
        self.assertEqual(fixture.ledger, before)
        fixture.assert_read_own_proof()

    def test_legacy_sam_context_without_source_remains_valid(self):
        fixture = self.history(source='sam-gov', context_source=None)
        self.assertNotIn('source_slug', fixture.context)
        self.assertIsNone(fixture.select())
        fixture.assert_read_own_proof()

    def test_darpa_receipt_cannot_claim_a_sam_or_unknown_producer_context(self):
        for source in (None, 'sam-gov', 'unknown-source'):
            with self.subTest(context_source=source):
                fixture = self.history(context_source=source)
                with self.assertRaisesRegex(scheduled.Hold, 'producing checkpoint'):
                    fixture.select()
                fixture.doCleanups()

    def test_darpa_completed_restore_keeps_original_budget_and_source(self):
        fixture = self.history()
        before = deepcopy(fixture.ledger)
        fixture.completed_restore_retry()
        self.assertIsNone(fixture.select())
        self.assertEqual(fixture.ledger, before)
        self.assertIn(f'actions/artifacts/{fixture.restore_state["id"]}/zip', fixture.api_calls)
        fixture.assert_read_own_proof()

    def test_darpa_transport_authenticates_original_source_without_new_allowance(self):
        fixture = self.history()
        self.transport(fixture)
        self.assertIsNone(fixture.select())
        self.assertEqual(fixture.pointer['artifact_run'], '250')
        self.assertEqual(fixture.child['source_reconciliation']['affected_generation']['generation_run_id'], '220')
        self.assertIn(f'actions/artifacts/{fixture.transport_state["id"]}/zip', fixture.api_calls)
        fixture.http.assert_not_called()
        fixture.provider_http.assert_not_called()

    def test_darpa_transport_cannot_use_an_unbound_legacy_sam_context(self):
        fixture = self.history(context_source=None)
        self.transport(fixture)
        with self.assertRaisesRegex(scheduled.Hold, 'restoring checkpoint'):
            fixture.select()


if __name__ == '__main__':
    unittest.main()
