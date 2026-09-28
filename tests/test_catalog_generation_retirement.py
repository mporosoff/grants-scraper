"""Exact canceled-owner disposition: authenticated zero spend, no broad exemptions."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import catalog_generation_retirement as retirement
from tools import generation_spend_checkpoint as spend, scheduled_catalog as scheduled
from tools import release_candidate as c, release_dependencies as dependencies
from tools.offline_ai import identity


class CatalogGenerationRetirement(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.reset()

    def reset(self):
        self.plan = c.read_json(c.ROOT / retirement.POLICY)
        self.run = deepcopy(self.plan['run'])
        self.artifacts = deepcopy(self.plan['artifacts'])
        for artifact in self.artifacts:
            artifact['expired'] = False
        self.jobs = [job | {'run_attempt': 1, 'head_sha': self.run['head_sha'], 'status': 'completed', 'steps': []}
                     for job in deepcopy(self.plan['jobs'])]
        self.generation = next(job for job in self.jobs if job['name'] == 'generate')
        self.generation['steps'] = [{'name': name, 'status': 'completed', 'conclusion': 'skipped'} for name in retirement.PAID_STEPS]
        self.archives = {}
        self.ledger = {'blocked_providers': {}, 'events': [], 'limit_microusd': 2000000,
                       'logical_id': 'offline-' + retirement.RETIRED_RUN, 'max_requests': 300, 'requests': [], 'version': 1}
        self.reservation = {'run_id': retirement.RETIRED_RUN, 'attempt': '1', 'mode': 'maintenance',
                            'maximum_logical_spend_usd': 2, 'prior_ledger_hash': identity(self.ledger)}
        self.replace_archive('generation-spend-state-', 'ledger.json', self.ledger)
        self.replace_archive('generation-spend-reservation-', 'spend-reservation.json', self.reservation)
        self.replace_archive('release-plan-', 'release-plan.json', {'release_sha': self.run['head_sha'],
                             'stage': 'generate', 'team_mode': 'maintenance', 'team_generation_ready': False})
        self.published = {(retirement.REPLACEMENT_RUN, 'a' * 64)}
        self.api = Mock(side_effect=self.response)

    def replace_archive(self, prefix, member, payload):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member, json.dumps(payload))
        raw = stream.getvalue()
        artifact = next(a for a in self.artifacts if a['name'].startswith(prefix))
        artifact.update(digest='sha256:' + c.digest(raw), size_in_bytes=len(raw))
        pinned = next(a for a in self.plan['artifacts'] if a['id'] == artifact['id'])
        pinned.update(digest=artifact['digest'], size_in_bytes=len(raw))
        self.archives[artifact['id']] = raw
        c.write_json(self.root / retirement.POLICY, self.plan)

    def response(self, path):
        if path.endswith('/zip'):
            return self.archives[int(path.split('/')[2])]
        if '/artifacts?' in path:
            return json.dumps({'total_count': len(self.artifacts), 'artifacts': self.artifacts})
        if '/jobs?' in path:
            return json.dumps({'total_count': len(self.jobs), 'jobs': self.jobs})
        if path.startswith('actions/workflows/'):
            return json.dumps({'workflow_runs': [self.run, {'id': int(retirement.REPLACEMENT_RUN)}]})
        self.assertEqual(path, 'actions/runs/' + retirement.RETIRED_RUN)
        return json.dumps(self.run)

    def check(self):
        return retirement.allows_skip(self.root, self.plan['repository'], self.run,
                                      self.artifacts, self.published, self.api)

    def test_only_protected_replacement_publication_supersedes_this_owner(self):
        self.published = {('111', 'b' * 64)}
        self.assertFalse(self.check())
        self.published.add((retirement.REPLACEMENT_RUN, 'a' * 64))
        self.assertTrue(self.check(), 'Later publications must retain the original protected replacement proof')
        untouched = Mock()
        self.assertFalse(retirement.allows_skip(self.root, 'other/repo', {'id': 123}, [], set(), untouched))
        untouched.assert_not_called()

    def test_scheduler_holds_until_replacement_then_releases_same_history(self):
        environment = {'GITHUB_REPOSITORY': self.plan['repository'], 'GITHUB_RUN_ID': str(int(retirement.RETIRED_RUN) + 1000)}
        with patch.object(scheduled, 'api', side_effect=lambda repo, path: self.response(path)), \
                patch.object(scheduled, '_published', side_effect=lambda root: self.published):
            self.published = set()
            with self.assertRaisesRegex(scheduled.Hold, 'no complete candidate'):
                scheduled.prior_generation(self.root, environment, {'generation_run_id': retirement.REPLACEMENT_RUN})
            self.published.add((retirement.REPLACEMENT_RUN, 'a' * 64))
            self.assertIsNone(scheduled.prior_generation(self.root, environment, {'generation_run_id': retirement.REPLACEMENT_RUN}))

    def test_replayed_or_changed_run_cannot_be_ignored(self):
        for changes in ({'run_attempt': 2}, {'status': 'in_progress'}, {'conclusion': 'success'},
                        {'head_sha': 'b' * 40}, {'event': 'workflow_dispatch'}, {'head_branch': 'other'}):
            with self.subTest(changes=changes):
                self.reset()
                self.run.update(changes)
                with self.assertRaisesRegex(retirement.RetirementHold, 'replayed or changed'):
                    self.check()

    def test_new_missing_expired_or_changed_artifact_holds(self):
        mutations = [lambda: self.artifacts.append({'id': 999, 'name': 'unexpected'}),
                     lambda: self.artifacts.pop(), lambda: self.artifacts[0].update(expired=True),
                     lambda: self.artifacts[0].update(digest='sha256:' + '0' * 64),
                     lambda: self.artifacts[0]['workflow_run'].update(head_branch='other')]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                self.reset()
                mutate()
                with self.assertRaises(retirement.RetirementHold):
                    self.check()
        self.reset()
        self.archives[next(iter(self.archives))] = b'changed bytes'
        with self.assertRaisesRegex(retirement.RetirementHold, 'archive identity'):
            self.check()

    def test_zero_ledger_and_bound_reservation_are_required_even_with_valid_archives(self):
        for changes in ({'requests': [{'charged_microusd': 1}]}, {'events': [{'kind': 'reservation'}]},
                        {'logical_id': 'other'}, {'limit_microusd': 3000000}, {'max_requests': 301}):
            with self.subTest(changes=changes):
                self.reset()
                self.replace_archive('generation-spend-state-', 'ledger.json', self.ledger | changes)
                with self.assertRaisesRegex(retirement.RetirementHold, 'accounting'):
                    self.check()
        self.reset()
        self.replace_archive('generation-spend-reservation-', 'spend-reservation.json', self.reservation | {'prior_ledger_hash': '0' * 64})
        with self.assertRaisesRegex(retirement.RetirementHold, 'reservation'):
            self.check()

    def test_every_paid_stage_must_be_uniquely_skipped_and_jobs_complete(self):
        for name in retirement.PAID_STEPS:
            for conclusion in ('success', 'failure', 'cancelled', None):
                with self.subTest(name=name, conclusion=conclusion):
                    self.reset()
                    next(step for step in self.generation['steps'] if step['name'] == name)['conclusion'] = conclusion
                    with self.assertRaisesRegex(retirement.RetirementHold, 'paid stage'):
                        self.check()
        for change in ('missing', 'duplicate', 'attempt', 'new_job'):
            with self.subTest(change=change):
                self.reset()
                if change == 'missing': self.generation['steps'].pop()
                if change == 'duplicate': self.generation['steps'].append(deepcopy(self.generation['steps'][0]))
                if change == 'attempt': self.generation['run_attempt'] = 2
                if change == 'new_job': self.jobs.append(deepcopy(self.jobs[0]))
                with self.assertRaises(retirement.RetirementHold):
                    self.check()

    def test_retired_owner_cannot_restore_or_create_any_state(self):
        destination = self.root / 'offline-state'
        reservation = self.root / 'reservation.json'
        with patch.object(spend, 'api') as api, patch.object(spend, 'Ledger') as ledger:
            with self.assertRaisesRegex(retirement.RetirementHold, 'permanently retired'):
                spend.prepare(self.plan['repository'], retirement.RETIRED_RUN, '2', destination, reservation, 'maintenance')
        api.assert_not_called()
        ledger.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertFalse(reservation.exists())

    def test_disposition_changes_only_validation_dependencies(self):
        policy = c.read_json(c.ROOT / c.POLICY)
        names = [retirement.POLICY, 'tools/catalog_generation_retirement.py', 'tools/scheduled_catalog.py',
                 'tools/generation_spend_checkpoint.py']
        for name in names:
            groups = {group for group, rule in policy['dependency_groups'].items()
                      if any(dependencies.matches(name, pattern) for pattern in rule['patterns']) and name not in rule['excluded']}
            self.assertEqual(groups, {'validation'}, name)


if __name__ == '__main__':
    unittest.main()
