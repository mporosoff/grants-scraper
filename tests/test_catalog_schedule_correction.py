"""Finite parent, accounting, routing and no-regeneration recovery contracts."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import catalog_access_correction as router
from tools import catalog_schedule_correction as recovery
from tools import release_candidate as c, release_dependencies as dependencies
from tools import release_checkpoint_archive as transport, scheduled_catalog
from tests.test_catalog_source_recovery import archive, groups, changed_group


class Fixture:
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.bundle = self.root/'parent'; self.bundle.mkdir()
        self.payloads = {'data/document_evidence.json': b'public retained cache', 'data/subtopics.js': b'unchanged scientific children'}
        hashes = {n: c.digest(b) for n, b in self.payloads.items()}
        self.manifest = {'schema_version': 1, 'candidate_format': c.VERSION, 'generation_sha': recovery.GENERATION_SHA,
            'generation_run_id': str(recovery.RUN), 'generation_run_attempt': '2', 'files': hashes,
            'generation_files': hashes, 'dependency_groups': groups(), 'runtime_baseline': {}}
        self.manifest['candidate_id'] = c.digest(c.encoded(self.manifest)); self.raw = c.encoded(self.manifest)
        (self.bundle/'candidate.json').write_bytes(self.raw)
        for n, b in self.payloads.items():
            p = self.bundle/'files'/n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)
        self.prior = {'version': 1, 'logical_id': f'offline-{recovery.RUN}', 'limit_microusd': 2000000,
            'max_requests': 300, 'requests': [], 'events': [{'kind': 'service_stop', 'service': 'teams'}], 'blocked_providers': {}}
        self.ledger = deepcopy(self.prior)
        self.ledger['requests'] = [{'id': str(i), 'status': 'valid', 'charged_microusd': 50463 if i == 0 else 1} for i in range(12)]
        self.state = {'ledger.json': c.encoded(self.ledger), 'document-checkpoint/checkpoint.json': c.encoded({
            'run_id': str(recovery.RUN), 'run_attempt': '2', 'generation_sha': recovery.GENERATION_SHA, 'files': hashes}),
            **{'document-checkpoint/blobs/' + h: self.payloads[n] for n, h in hashes.items()},
            **{f'cov4-cache/{i}.json': c.encoded({'safe_verdict': True}) for i in range(12)}}
        reservation = {'attempt': '2', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': recovery.identity(self.prior), 'run_id': str(recovery.RUN)}
        validation = {'candidate_id': self.manifest['candidate_id'], 'generation_sha': recovery.GENERATION_SHA,
            'validation_sha': recovery.GENERATION_SHA, 'production_mutated': False,
            'identity': {'candidate_hashes': hashes}, 'gates': {gate: 'passed' for gate in c.GATES}}
        self.entries = {'candidate': [('candidate.json', self.raw)] + [('files/' + n, b) for n, b in self.payloads.items()],
            'state': list(self.state.items()), 'prior_state': [('ledger.json', c.encoded(self.prior))],
            'reservation': [('spend-reservation.json', c.encoded(reservation))],
            'validation': [('validation.json', c.encoded(validation))], 'plan': [('release-plan.json', c.encoded({
                'release_sha': recovery.GENERATION_SHA, 'stage': 'generate', 'team_mode': 'maintenance'}))]}
        self.refresh()
        self.run = {'id': recovery.RUN, 'run_attempt': 2, 'head_sha': recovery.EVENT_SHA, 'head_branch': 'main',
            'path': recovery.auth.REFRESH, 'event': 'push', 'status': 'completed', 'conclusion': 'failure'}
        for name, value in [('PARENT', self.manifest['candidate_id']), ('MANIFEST_SHA', c.digest(self.raw)),
            ('LEDGER_SHA', c.digest(self.state['ledger.json'])), ('ARTIFACTS', self.pins), ('ARCHIVED_IDS', set(self.by_id))]:
            self.stack.enter_context(patch.object(recovery, name, value))
        self.stack.enter_context(patch.object(transport, 'preserved_artifacts', side_effect=lambda *a, **k: self.records))
        self.stack.enter_context(patch.object(transport, 'read_preserved_artifact', side_effect=lambda repo, run, a, **k: self.by_id[a['id']]))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('No source/provider requests')))
        self.api = Mock(side_effect=self.read)

    def refresh(self):
        self.zips = {role: archive(entries) for role, entries in self.entries.items()}
        self.pins = {role: (i, role, c.digest(raw)) for i, (role, raw) in enumerate(self.zips.items(), 401)}
        self.by_id = {self.pins[role][0]: raw for role, raw in self.zips.items()}
        self.records = [{'id': i, 'name': name, 'digest': 'sha256:' + digest} for i, name, digest in self.pins.values()]

    def read(self, path):
        if path in (f'actions/runs/{recovery.RUN}', f'actions/runs/{recovery.RUN}/attempts/2'):
            return c.encoded(self.run)
        if path == f'actions/artifacts/{recovery.ARCHIVE_ID}':
            return c.encoded({'id': recovery.ARCHIVE_ID, 'digest': 'sha256:' + recovery.ARCHIVE_SHA})
        raise AssertionError(path)

    def authenticate(self):
        return recovery.authenticate(self.bundle, api=self.api)


class Authentication(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.addCleanup(self.f.stack.close)

    def test_complete_parent_state_validation_and_prior_ledger_preserve_exact_allowance(self):
        before = {p: p.read_bytes() for p in self.f.bundle.rglob('*') if p.is_file()}
        original, spending = self.f.authenticate()
        self.assertEqual(original, self.f.manifest)
        self.assertEqual((spending['requests_used'], spending['charged_microusd'], spending['limit_microusd'], spending['max_requests']),
                         (12, 50474, 2000000, 300))
        self.assertTrue(all(spending[key] == 0 for key in ('new_source_requests', 'new_document_ai_requests',
            'new_team_requests', 'new_vector_requests', 'new_allowance_microusd', 'ledger_writes')))
        self.assertEqual(spending['state_hashes'], {n: c.digest(b) for n, b in self.f.state.items()})
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_actual_event_and_selected_generation_are_distinct_pins_and_no_later_attempt_is_accepted(self):
        for key, value in [('run_attempt', 3), ('head_sha', recovery.GENERATION_SHA), ('event', 'workflow_dispatch'),
                           ('status', 'in_progress'), ('conclusion', 'success')]:
            with self.subTest(key=key):
                original = self.f.run[key]; self.f.run[key] = value
                with self.assertRaisesRegex(ValueError, 'original_terminal_attempt'):
                    self.f.authenticate()
                self.f.run[key] = original

    def test_archive_inventory_digest_and_parent_bytes_fail_closed(self):
        self.f.records.append({'id': 999, 'name': 'extra', 'digest': 'sha256:' + 'a'*64})
        with self.assertRaisesRegex(ValueError, 'complete_archive_inventory'):
            self.f.authenticate()
        self.f.records.pop(); self.f.by_id[401] += b'tamper'
        with self.assertRaisesRegex(ValueError, 'original_raw_zip'):
            self.f.authenticate()
        self.f.by_id[401] = self.f.zips['candidate']
        (self.f.bundle/'files/data/subtopics.js').write_bytes(b'changed science')
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
            self.f.authenticate()

    def test_newer_allowance_or_passing_validation_cannot_replace_pinned_receipts(self):
        self.f.pins['state'] = self.f.pins['state'][:2] + ('0'*64,)
        with self.assertRaisesRegex(ValueError, 'original_artifact_pins'):
            self.f.authenticate()


class RoutingAndBoundaries(unittest.TestCase):
    def env(self):
        return {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF':
            'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_ID': recovery.PARENT, 'CANDIDATE_RUN': str(recovery.RUN), 'REQUESTED_STAGE': recovery.STAGE}

    def test_exact_new_manual_selector_and_legacy_selector_route_independently(self):
        with patch.object(c, 'git', return_value='a'*40):
            result = router.plan(Path('.'), self.env())
            self.assertEqual((result['candidate_id'], result['openai'], result['anthropic']), (recovery.PARENT, 'false', 'false'))
            legacy = router.plan(Path('.'), self.env() | {'CANDIDATE_ID': router.PARENT, 'CANDIDATE_RUN': str(router.RUN)})
            self.assertEqual(legacy['candidate_id'], router.PARENT)
            for key in self.env():
                with self.subTest(key=key), self.assertRaises(ValueError):
                    router.plan(Path('.'), self.env() | {key: 'other'})
            for key in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT', 'QUALIFICATION_PILOT'):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'no_other_generation_or_recovery'):
                    recovery.plan(Path('.'), self.env() | {key: 'true'})

    def test_no_unrelated_source_semantic_team_or_budget_change_is_accepted(self):
        original = {'dependency_groups': groups(), 'runtime_baseline': {}}
        with patch.object(dependencies, 'snapshot', return_value=changed_group(groups(), 'source', 'scripts/notice_schedule.py')), \
                patch.object(c, 'git', return_value=''):
            recovery.dependency_scope(Path('.'), original)
        for group, name in [('source', 'scripts/pull_grants.py'), ('source', '@document_spend_config'),
                            ('teams', 'config/offline_ai.json'), ('semantic', 'assets/search-hybrid.js')]:
            with self.subTest(group=group), patch.object(dependencies, 'snapshot', return_value=changed_group(groups(), group, name)), \
                    self.assertRaisesRegex(ValueError, 'bounded_dependency_changes'):
                recovery.dependency_scope(Path('.'), original)

    def test_receipt_version_routes_before_historical_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'receipt.json'; c.write_json(path, {'version': recovery.VERSION})
            with patch.object(recovery, 'verify_inputs', return_value={'unchanged': 'hash'}) as verify, \
                    patch.object(router, 'authenticate', side_effect=AssertionError('Historical route must not run')):
                self.assertEqual(router.verify_inputs(Path('.'), {}, Path('.'), path), {'unchanged': 'hash'})
                verify.assert_called_once()

    def test_original_rejected_candidate_cannot_reenter_ordinary_dependencies(self):
        with patch.object(c, 'git', side_effect=AssertionError('Quarantine first')):
            with self.assertRaisesRegex(ValueError, 'rejected_parent_requires_named_schedule_correction'):
                c.verify_dependencies(Path('.'), {'candidate_id': recovery.PARENT})

    def test_deterministic_receipt_rejects_changed_accounting_and_unrelated_science(self):
        fixture = Fixture(); self.addCleanup(fixture.stack.close)
        root = fixture.root/'materialized'; root.mkdir()
        outputs = {'data/document_evidence.json': b'corrected public interpretation'}
        spending = {'charged_microusd': 50474, 'new_document_ai_requests': 0}
        proof = {'strict_notice_gate': {'publication_ready': True}, 'package': {'new_provider_requests': 0}}
        clock = '2026-10-16T18:00:00+00:00'
        receipt = recovery.receipt_for(fixture.manifest, spending, outputs, proof, clock)
        for name, raw in fixture.payloads.items():
            target = root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(outputs.get(name, raw))
        path = fixture.root/'receipt.json'; c.write_json(path, receipt)
        with patch.object(recovery, 'authenticate', return_value=(fixture.manifest, spending)), \
                patch.object(recovery, 'derive', return_value=(outputs, proof)), \
                patch.object(recovery, 'dependency_scope'), patch.object(c, 'facet_feed_names', return_value=set()):
            self.assertEqual(recovery.verify_inputs(root, fixture.manifest, fixture.bundle, path),
                             {'data/subtopics.js': fixture.manifest['files']['data/subtopics.js']})
            (root/'data/subtopics.js').write_bytes(b'changed scientific children')
            with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
                recovery.verify_inputs(root, fixture.manifest, fixture.bundle, path)
            (root/'data/subtopics.js').write_bytes(fixture.payloads['data/subtopics.js'])
            forged = deepcopy(receipt); forged['spending']['charged_microusd'] = 0; c.write_json(path, forged)
            with self.assertRaisesRegex(ValueError, 'deterministic_replay'):
                recovery.verify_inputs(root, fixture.manifest, fixture.bundle, path)

    def test_automatic_main_push_holds_original_candidate_before_new_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); current = {'generation_run_id': '38757294301'}
            current['candidate_id'] = c.digest(c.encoded(current)); c.write_json(root/'release/candidate.json', current)
            environment = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_RUN_ID': '40000000000'}
            runs = [{'id': recovery.RUN, 'path': scheduled_catalog.WORKFLOW, 'head_branch': 'main', 'event': 'push'},
                    {'id': 38757294301}]
            # This minimal source-owner fixture is not a native runtime bundle.
            # Complete native ZIP/history proofs have their own integration tests.
            with patch.object(scheduled_catalog, '_published', return_value=set()), \
                    patch.object(scheduled_catalog, '_published_reconciliation_supersedes', return_value=False), \
                    patch('tools.runtime_assembly_history.no_generation_allowance', return_value=False) as runtime_proof, \
                    patch.object(scheduled_catalog, '_pages', return_value=iter([runs])), \
                    patch.object(scheduled_catalog, 'run_artifacts', return_value=[{'id': 1, 'name': 'candidate-' + recovery.PARENT, 'expired': False}]), \
                    patch.object(scheduled_catalog, 'api', side_effect=AssertionError('No unexpected GitHub reads in routing fixture')) as github:
                value = scheduled_catalog.hold_competing_generation(root, environment, {'stage': 'generate'})
            runtime_proof.assert_called_once()
            github.assert_not_called()
            self.assertEqual(value['stage'], 'noop')
            self.assertEqual(value['held_stage'], 'generate')
            self.assertEqual(value['recovery_run'], str(recovery.RUN))


if __name__ == '__main__':
    unittest.main()
