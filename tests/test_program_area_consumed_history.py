"""Published corrections retire only retained prefix work and conserved science."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from tests import test_program_area_history as fixtures
from tools import program_area_history as h, scheduled_catalog as daily
from tools.catalog_reconcile import request_identity
from tools.offline_spend import identity


class ConsumedProgramAreaHistory(unittest.TestCase):
    def setUp(self):
        # Borrow data/transports without inheriting and rerunning its tests.
        self.fixture = fixtures.ModernHistory(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.previous = dict(self.fixture.run, id=180, head_sha='9' * 40)
        self.runs = {180: self.previous, 200: self.fixture.run}
        self.inventories = {200: self.fixture.artifacts}
        self.documents_by_id = {}
        self.fixture.docs.side_effect = self.documents
        self.api = patch.object(daily, 'api', side_effect=self.metadata).start()
        self.inventory = patch.object(daily, 'run_artifacts', side_effect=self.artifacts).start()

    @staticmethod
    def request(identifier, *, status='completed', charged=25):
        return {'id': identifier * 32, 'provider': 'voyage', 'model': 'voyage-4-lite',
            'stage': 'reconciled_vectors', 'key': identifier * 64, 'attempt': 1,
            'reserved_microusd': 40, 'charged_microusd': charged, 'status': status}

    def metadata(self, repository, path):
        if path.startswith('actions/runs/'):
            return json.dumps(self.runs[int(path.rsplit('/', 1)[1])]).encode()
        raise AssertionError('Unexpected API ' + path)

    def artifacts(self, run, api, *, repository):
        return deepcopy(self.inventories[int(run)])

    def documents(self, repository, run, artifact, names, **kwargs):
        fixture = self.fixture
        source = self.documents_by_id.get(artifact['id'])
        if source is None:
            source = ({'candidate.json': fixture.child} if artifact['name'].startswith('candidate-')
                      else {'reservation.json': fixture.voucher} if '-reservation-' in artifact['name']
                      else fixture.state)
        selected = {name: deepcopy(source[name]) for name in names}
        if kwargs.get('complete_source'):
            identifier = selected['reconciliation.json']['completed_candidate_id']
            name = 'complete-candidates/' + identifier + '/candidate.json'
            selected[name] = deepcopy(source[name])
        return selected

    def reseal_source(self):
        fixture = self.fixture
        fixture.receipt['ledger_sha256'] = identity(fixture.ledger)
        fixture.child.pop('candidate_id', None)
        fixture.child['candidate_id'] = daily.c.digest(daily.c.encoded(fixture.child))
        fixture.pointer['candidate_id'] = fixture.child['candidate_id']
        fixture.context['completed_candidate_id'] = fixture.child['candidate_id']
        for name in list(fixture.state):
            if name.startswith('complete-candidates/'):
                fixture.state.pop(name)
        fixture.state['complete-candidates/' + fixture.child['candidate_id'] + '/candidate.json'] = fixture.child
        fixture.artifacts[2]['name'] = 'candidate-' + fixture.child['candidate_id']

    def consumed_prefix(self):
        fixture = self.fixture
        # A completed response may settle a conservative unknown charge down;
        # immutable reservation identity must remain at the beginning.
        prior = dict(fixture.ledger, requests=[self.request('1', status='unknown', charged=40)])
        fixture.ledger['requests'] = [self.request('1'), self.request('2', charged=17)]
        context = {k: deepcopy(v) for k, v in fixture.context.items()
                   if k not in {'operation_sha256', 'completed_candidate_id'}}
        context.update(audit_at='2026-10-18T23:00:00Z', operation_contract={'extractor': '1' * 64})
        context['operation_sha256'] = identity(context)
        voucher = fixture.voucher | {'producer_run': '180', 'operation_sha256': context['operation_sha256']}
        family = h.prefix(fixture.receipt['parent_candidate_id'])
        rows = [{'id': ident, 'name': f'{family}-{role}-180-1',
            'digest': 'sha256:' + str(ident) * 64, 'expired': False,
            'workflow_run': {'id': 180, 'head_sha': self.previous['head_sha'], 'head_branch': 'main'}}
            for ident, role in ((4, 'reservation'), (5, 'state'))]
        self.inventories[180] = rows
        self.documents_by_id[4] = {'reservation.json': voucher}
        self.documents_by_id[5] = {'reservation.json': voucher, 'ledger.json': prior,
                                   'reconciliation.json': context}
        link = {'producer': h.producer(self.previous), 'reservation': h.pin(rows[0]), 'state': h.pin(rows[1]),
            'ledger_sha256': identity(prior), 'request_count': len(prior['requests']),
            'request_prefix_sha256': identity(prior['requests']),
            'request_identity_prefix_sha256': request_identity(prior['requests']),
            'charged_microusd': 40}
        fixture.receipt['consumed_checkpoints'] = [link]
        self.reseal_source()
        return link, prior

    def retire_previous(self):
        return h.published_consumes('.', self.previous, self.inventories[180], repository='owner/repo')

    def test_real_ledger_prefix_and_settled_unknown_charge_retire_consumed_checkpoint(self):
        self.consumed_prefix()
        before = deepcopy(self.fixture.ledger)
        self.assertTrue(self.retire_previous())
        self.assertEqual(self.fixture.ledger, before)
        call = self.fixture.history.call_args
        self.assertEqual(call.args[2], [h.producer(self.previous)])
        self.assertEqual(call.args[3], [])

    def test_changed_final_request_identity_does_not_cover_prior_paid_work(self):
        self.consumed_prefix()
        self.fixture.ledger['requests'][0]['key'] = '9' * 64
        self.reseal_source()
        with self.assertRaisesRegex(daily.Hold, 'consumed work missing from final ledger'):
            self.retire_previous()

    def test_missing_final_prefix_does_not_cover_prior_paid_work(self):
        self.consumed_prefix()
        self.fixture.ledger['requests'].pop(0)
        self.reseal_source()
        with self.assertRaisesRegex(daily.Hold, 'consumed work missing from final ledger'):
            self.retire_previous()

    def test_final_charge_cannot_grow_beyond_consumed_conservative_charge(self):
        self.consumed_prefix()
        self.fixture.ledger['requests'][0]['charged_microusd'] = 41
        self.reseal_source()
        with self.assertRaisesRegex(daily.Hold, 'consumed work missing from final ledger'):
            self.retire_previous()

    def test_changed_state_or_reservation_pins_hold(self):
        self.consumed_prefix()
        for row in self.inventories[180]:
            original = row['digest']
            row['digest'] = 'sha256:' + '8' * 64
            with self.subTest(artifact=row['name']), self.assertRaisesRegex(daily.Hold, 'pinned artifact changed'):
                self.retire_previous()
            row['digest'] = original

    def test_consumed_state_ledger_must_match_its_exact_link(self):
        self.consumed_prefix()
        self.documents_by_id[5]['ledger.json']['requests'][0]['reserved_microusd'] = 39
        with self.assertRaisesRegex(daily.Hold, 'consumed checkpoint ledger'):
            self.retire_previous()

    def test_missing_or_uncovered_prior_checkpoint_cannot_retire(self):
        self.consumed_prefix()
        removed = self.inventories[180].pop()
        with self.assertRaisesRegex(daily.Hold, 'unique .*state'):
            self.retire_previous()
        self.inventories[180].append(removed)
        self.inventories[180].append(dict(removed, id=6,
            name=removed['name'].replace('-state-', '-reservation-').replace('-180-1', '-180-2')))
        with self.assertRaisesRegex(daily.Hold, 'unacknowledged allowance'):
            self.retire_previous()

    def restored_transport(self):
        link, ledger = self.consumed_prefix()
        self.original_owner = dict(self.previous, id=170, head_sha='6' * 40)
        self.runs[170] = self.original_owner
        state = self.documents_by_id[5]
        voucher = state['reservation.json']
        voucher['producer_run'] = '170'
        prior_receipt = {key: deepcopy(value) for key, value in state['reconciliation.json'].items()
                         if key != 'completed_candidate_id'}
        prior_receipt.update(ledger_sha256=identity(ledger), consumed_checkpoints=[],
            affected_generation={'generation_run_id': '170', 'generation_run_attempt': '1',
                                 'generation_sha': self.original_owner['head_sha']})
        source = {'generation_sha': 'c' * 40, 'generation_run_id': '100',
            'assembly_sha': self.original_owner['head_sha'], 'derived_from_candidate': 'b' * 64,
            h.FIELD: prior_receipt}
        source['candidate_id'] = daily.c.digest(daily.c.encoded(source))
        state['reconciliation.json']['completed_candidate_id'] = source['candidate_id']
        state['complete-candidates/' + source['candidate_id'] + '/candidate.json'] = source
        reservation = self.inventories[180].pop(0)
        reservation['name'] = reservation['name'].replace('-180-1', '-170-1')
        reservation['workflow_run'] = {'id': 170, 'head_sha': self.original_owner['head_sha'], 'head_branch': 'main'}
        self.inventories[170] = [reservation]
        self.documents_by_id[4] = {'reservation.json': voucher}
        link.update(restored=True, reservation=h.pin(reservation))
        candidate = {'id': 6, 'name': 'candidate-' + source['candidate_id'], 'expired': False,
            'digest': 'sha256:' + '6' * 64,
            'workflow_run': {'id': 180, 'head_sha': self.previous['head_sha'], 'head_branch': 'main'}}
        self.inventories[180].append(candidate)
        self.documents_by_id[6] = {'candidate.json': source}
        link['candidate'] = {'candidate_id': source['candidate_id'], 'producer': h.producer(self.previous),
            'manifest_sha256': daily.c.digest(daily.c.encoded(source)), 'artifact': h.pin(candidate)}
        self.reseal_source()

    def test_consumed_restored_transport_authenticates_separate_original_voucher(self):
        self.restored_transport()
        before = deepcopy(self.fixture.ledger)
        with patch.object(h, 'completed_restore') as restore:
            self.assertTrue(self.retire_previous())
            restore.assert_called_once_with('owner/repo', self.previous, self.previous)
        self.assertEqual(self.fixture.ledger, before)
        self.assertTrue(any(call.args[0] == 170 for call in self.inventory.call_args_list))

    def test_consumed_restored_transport_rejects_changed_original_voucher_pin(self):
        self.restored_transport()
        self.inventories[170][0]['digest'] = 'sha256:' + '8' * 64
        with patch.object(h, 'completed_restore'), self.assertRaisesRegex(daily.Hold, 'pinned artifact changed'):
            self.retire_previous()

    def runtime_publication(self):
        fixture = self.fixture
        self.generated = {'data/opportunities.js': b'public scientific catalog\n',
                          'data/search-v2-voyage-vectors.f16': b'\x00\xff\x80\x00',
                          'config/opportunity_team_model.json': b'{"generation_id":"old"}\n'}
        hashes = {name: daily.c.digest(raw) for name, raw in self.generated.items()}
        fixture.child.update(generation_run_attempt='1', generation_timestamp='2026-10-19T00:00:00Z',
            generation_dependencies={'files': {'extractor': '1' * 64}}, generator_versions={'source': '1'},
            generation_baseline={'data/opportunities.js': '1' * 64}, generation_files=hashes,
            team_identity={'generation_id': '2' * 64}, semantic_identity={'corpus_sha256': '3' * 64},
            original_generation={'generation_run_id': '100', 'generation_sha': 'c' * 40},
            dependency_groups={name: {'files': {'code': str(index) * 64}, 'fingerprint': str(index) * 64}
                for index, name in enumerate(('source', 'teams', 'semantic', 'runtime', 'validation'), 1)},
            files=hashes | {'team_match.html': daily.c.digest(b'old runtime')})
        self.reseal_source()
        self.published = deepcopy(fixture.child)
        self.published.update(derived_from_candidate=fixture.child['candidate_id'], assembly_sha='8' * 40)
        self.published['files']['team_match.html'] = daily.c.digest(b'new runtime')
        self.published['dependency_groups']['runtime']['fingerprint'] = '8' * 64
        self.seal_published()
        patch.object(daily.c, 'git', side_effect=self.published_git).start()
        self.binary_reads = patch.object(h.subprocess, 'check_output', side_effect=self.git_bytes).start()

    def seal_published(self):
        self.published.pop('candidate_id', None)
        self.published['candidate_id'] = daily.c.digest(daily.c.encoded(self.published))
        self.fixture.pointer = {'candidate_id': self.published['candidate_id'], 'artifact_run': '250'}

    def published_git(self, root, *args):
        if hasattr(self, 'publications'):
            if args[0] == 'log':
                return '\n'.join(self.publications)
            document, pointer = self.publications[args[-1].split(':', 1)[0]]
            return json.dumps(pointer if args[-1].endswith('candidate-source.json') else document)
        if args[0] == 'log':
            return 'f' * 40
        return json.dumps(self.fixture.pointer if args[-1].endswith('candidate-source.json') else self.published)

    def git_bytes(self, command, **kwargs):
        expected = ['git', '-C', '.', 'show']
        if command[:4] != expected or not command[4].startswith('f' * 40 + ':'):
            raise AssertionError('Unexpected binary transport ' + repr(command))
        return self.generated[command[4].split(':', 1)[1]]

    def test_published_runtime_package_retires_exact_private_source_and_ledger(self):
        self.runtime_publication()
        self.assertTrue(self.fixture.retire())
        self.assertEqual(self.binary_reads.call_count, len(self.generated))
        self.assertEqual(self.fixture.history.call_args.args[2], [h.producer(self.fixture.run)])

    def test_runtime_package_does_not_cover_altered_scientific_bytes(self):
        self.runtime_publication()
        self.generated['data/search-v2-voyage-vectors.f16'] = b'\x01\xff\x80\x00'
        with self.assertRaisesRegex(daily.Hold, 'published generated bytes changed'):
            self.fixture.retire()

    def test_runtime_package_does_not_cover_changed_source_receipt(self):
        self.runtime_publication()
        self.published[h.FIELD]['audit_at'] = '2026-10-20T00:00:00Z'
        self.seal_published()
        with self.assertRaisesRegex(daily.Hold, 'runtime assembly changed generated identity'):
            self.fixture.retire()

    def test_runtime_package_does_not_cover_changed_original_ledger(self):
        self.runtime_publication()
        self.fixture.ledger['requests'].append(self.request('1'))
        with self.assertRaisesRegex(daily.Hold, 'exact completed child and ledger'):
            self.fixture.retire()

    def later_team_publication(self):
        self.runtime_publication()
        first, pointer = deepcopy(self.published), deepcopy(self.fixture.pointer)
        self.published.update(derived_from_candidate=first['candidate_id'], assembly_sha='7' * 40,
            team_identity={'generation_id': '7' * 64},
            team_generation={'sha': '7' * 40, 'run_id': '300', 'run_attempt': '1'})
        self.published['generation_files']['config/opportunity_team_model.json'] = '7' * 64
        self.published['files']['config/opportunity_team_model.json'] = '7' * 64
        self.published['dependency_groups']['teams']['fingerprint'] = '7' * 64
        self.seal_published()
        self.fixture.pointer['artifact_run'] = '300'
        self.publications = {'7' * 40: (self.published, self.fixture.pointer), 'f' * 40: (first, pointer)}

    def test_later_team_publication_follows_authenticated_parent_to_original_boundary(self):
        self.later_team_publication()
        self.assertTrue(self.fixture.retire())
        self.assertEqual(self.binary_reads.call_count, len(self.generated))
        self.assertTrue(all(call.args[0][4].startswith('f' * 40 + ':')
                            for call in self.binary_reads.call_args_list))

    def test_later_team_changed_receipt_cannot_skip_to_older_publication(self):
        self.later_team_publication()
        self.published[h.FIELD]['audit_at'] = '2026-10-20T00:00:00Z'
        self.seal_published()
        self.publications['7' * 40] = (self.published, self.fixture.pointer)
        with self.assertRaisesRegex(daily.Hold, 'runtime assembly changed generated identity'):
            self.fixture.retire()

    def test_later_team_canonical_and_pointer_tampering_hold(self):
        self.later_team_publication()
        original = self.publications['7' * 40]
        for document, pointer in ((dict(original[0], assembly_sha='9' * 40), original[1]),
                                  (original[0], dict(original[1], candidate_id='9' * 64))):
            with self.subTest(document=document['candidate_id'], pointer=pointer['candidate_id']):
                self.publications['7' * 40] = (document, pointer)
                with self.assertRaisesRegex(daily.Hold, 'protected descendant pointer'):
                    self.fixture.retire()
        self.publications['7' * 40] = original
        prior, pointer = self.publications['f' * 40]
        self.publications['f' * 40] = (prior, dict(pointer, candidate_id='9' * 64))
        with self.assertRaisesRegex(daily.Hold, 'runtime assembly changed generated identity'):
            self.fixture.retire()

    def test_later_team_still_requires_earlier_private_ledger_proof(self):
        self.later_team_publication()
        self.fixture.ledger['requests'].append(self.request('1'))
        with self.assertRaisesRegex(daily.Hold, 'exact completed child and ledger'):
            self.fixture.retire()


if __name__ == '__main__':
    unittest.main()
