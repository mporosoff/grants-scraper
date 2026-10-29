"""A cancelled setup is not a generation owner; uncertain work still is.

The fixture is a bounded projection of native run 40964672496 and its protected
workflow. Only immutable Git/API transports are substituted: the attempt,
pagination, inventory, dependency and native-step proof run normally.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tools import release_attempt_history as history
from tools import scheduled_catalog as scheduled


FIXTURE = Path(__file__).parent / 'fixtures/release_history/cancelled_before_plan_40964672496.json'
REPOSITORY = 'mporosoff/grants-scraper'
PRODUCERS = {
    'generate', 'assemble', 'catalog-correction', 'catalog-reconcile',
    'program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction',
    'catalog-identity-correction', 'catalog-url-correction',
}


class CancelledReleaseOwner(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.run = deepcopy(self.fixture['run'])
        self.attempt = deepcopy(self.run)
        self.latest = deepcopy(self.run)
        self.jobs = deepcopy(self.fixture['jobs_response']['jobs'])
        self.workflow = deepcopy(self.fixture['workflow'])
        self.pages_workflow = deepcopy(self.fixture['pages_workflow'])
        self.artifacts = []
        self.native_artifacts = []
        self.repository_artifacts = []
        self.job_pages = None
        self.artifact_response = None
        self.calls = []
        git = patch.object(history.candidate, 'git', side_effect=self.git)
        git.start(); self.addCleanup(git.stop)

    def git(self, _root, *args):
        # Never depend on the CI checkout retaining this historical commit.
        self.assertEqual(args[0], 'show')
        head = self.fixture['run']['head_sha']
        if args[1] == head + ':' + history.WORKFLOW:
            return json.dumps(self.workflow)
        if args[1] == head + ':.github/workflows/pages.yml':
            return json.dumps(self.pages_workflow)
        self.fail('Unexpected Git read: ' + repr(args))

    def api(self, path):
        self.calls.append(path)
        parsed = urlsplit(path)
        page = int(parse_qs(parsed.query).get('page', ['1'])[0])
        prefix = 'actions/runs/' + str(self.fixture['run']['id'])
        if parsed.path == prefix:
            return json.dumps(self.latest)
        if parsed.path == prefix + '/attempts/1':
            return json.dumps(self.attempt)
        if parsed.path == prefix + '/attempts/1/jobs':
            if self.job_pages is not None:
                return json.dumps(self.job_pages[page])
            return json.dumps({'total_count': len(self.jobs), 'jobs': self.jobs if page == 1 else []})
        if parsed.path == prefix + '/artifacts':
            return json.dumps(self.artifact_response if self.artifact_response is not None else {
                'total_count': len(self.native_artifacts), 'artifacts': self.native_artifacts if page == 1 else []})
        if parsed.path == 'actions/artifacts':
            return json.dumps({'total_count': len(self.repository_artifacts),
                               'artifacts': self.repository_artifacts if page == 1 else []})
        self.fail('Unexpected or unbound history read: ' + path)

    def prove(self):
        return history.require_cancelled_before_planning(REPOSITORY, self.run, self.artifacts, api=self.api)

    def job(self, name):
        return next(row for row in self.jobs if row['name'] == name)

    def resolver(self):
        return next(row for row in self.job('plan')['steps'] if row['name'] == 'Resolve explicit lifecycle checkpoint')

    def artifact(self, name):
        return {'id': 12938015535, 'name': name, 'digest': 'sha256:' + 'a' * 64,
                'expired': False, 'workflow_run': {'id': self.run['id'], 'head_sha': self.run['head_sha']}}

    def owner(self):
        boundary = {'id': 40930462049}
        with patch.object(scheduled, '_release_history', return_value=[[self.run, boundary]]), \
                patch.object(scheduled, '_published', return_value=set()), \
                patch.object(scheduled, '_published_reconciliation_consumes', return_value=False), \
                patch('tools.program_area_history.published_consumes', return_value=False), \
                patch.object(scheduled, 'api', side_effect=lambda repository, path: self.api(path)):
            return scheduled.prior_generation(Path('unused'),
                {'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_RUN_ID': '40964800770'},
                {'generation_run_id': str(boundary['id'])})

    def test_actual_setup_cancellation_retires_no_allowance_and_releases_planner(self):
        self.assertEqual(len(self.jobs), 17)
        actual = [row for row in self.jobs if row['name'] in PRODUCERS]
        self.assertEqual({row['name'] for row in actual}, PRODUCERS)
        self.assertTrue(all(row['steps'] == [] and row['conclusion'] == 'cancelled' for row in actual))
        # Native placeholders genuinely have these odd timestamps; they do not
        # establish started work and must not become a new false hold.
        self.assertTrue(all(row['completed_at'] < row['started_at'] for row in actual))
        proof = self.prove()
        self.assertEqual(proof['kind'], 'plan-setup')
        self.assertEqual(str(proof['run_id']), str(self.run['id']))
        self.assertEqual(proof['run_attempt'], 1)
        self.assertEqual(proof['head_sha'], self.run['head_sha'])
        self.assertIs(proof['prior_allowance_reserved'], False)
        self.assertIs(proof['prior_provider_dispatch'], False)
        self.assertIsNone(self.owner())
        self.assertTrue(any('/attempts/1/jobs?' in call for call in self.calls))
        self.assertFalse(any('/runs/' + str(self.run['id']) + '/jobs?' in call for call in self.calls))

    def test_concurrency_queued_first_attempt_without_jobs_is_also_proven(self):
        self.jobs = []
        proof = self.prove()
        self.assertEqual(proof['kind'], 'queued')
        self.assertIs(proof['prior_allowance_reserved'], False)
        self.assertIs(proof['prior_provider_dispatch'], False)
        self.assertIsNone(self.owner())
        self.assertTrue(any(call.endswith('/attempts/1') for call in self.calls))

    def test_later_or_ambiguous_attempt_cannot_hide_earlier_generation(self):
        for attempt in (2, 3, '1', None):
            with self.subTest(attempt=attempt):
                self.run['run_attempt'] = attempt
                with self.assertRaises(ValueError):
                    self.prove()
        self.run = deepcopy(self.fixture['run'])
        del self.run['run_attempt']
        with self.assertRaises(ValueError):
            self.prove()

    def test_run_and_authenticated_attempt_must_share_protected_identity(self):
        original = deepcopy(self.attempt)
        for key, value in (('id', self.run['id'] + 1), ('run_attempt', 2), ('head_sha', 'f' * 40),
                           ('head_branch', 'feature'), ('event', 'pull_request'), ('path', 'other.yml'),
                           ('status', 'in_progress'), ('conclusion', 'success')):
            with self.subTest(field=key):
                self.attempt = original | {key: value}
                with self.assertRaises(ValueError):
                    self.prove()

    def test_only_terminal_cancellation_can_establish_the_exception(self):
        original = deepcopy(self.run)
        for change in ({'status': 'in_progress'}, {'conclusion': 'success'}, {'conclusion': 'failure'},
                       {'event': 'pull_request'}, {'head_branch': 'feature'}, {'head_sha': 'unknown'}):
            with self.subTest(change=change):
                self.run = original | change
                with self.assertRaises(ValueError):
                    self.prove()

    def test_job_identity_is_bound_to_run_attempt_head_and_unique_native_id(self):
        original = deepcopy(self.jobs)
        for key, value in (('run_id', self.run['id'] + 1), ('run_attempt', 2), ('head_sha', 'f' * 40),
                           ('head_branch', 'feature'), ('id', original[1]['id']), ('status', 'in_progress')):
            with self.subTest(field=key):
                self.jobs = deepcopy(original)
                self.jobs[0][key] = value
                with self.assertRaises(ValueError):
                    self.prove()

    def test_unknown_duplicate_or_missing_declared_jobs_do_not_prove_no_start(self):
        original = deepcopy(self.jobs)
        for rows in ([row for row in original if row['name'] != 'generate'],
                     original + [original[0]],
                     original + [original[0] | {'id': 99999, 'name': 'unknown-provider-job'}]):
            with self.subTest(names=[row['name'] for row in rows]):
                self.jobs = deepcopy(rows)
                with self.assertRaises(ValueError):
                    self.prove()

    def test_short_missing_and_inconsistent_job_pages_remain_unknown(self):
        actual = deepcopy(self.jobs)
        cases = [
            {1: {'total_count': 18, 'jobs': actual}, 2: {'total_count': 18, 'jobs': []}},
            {1: {'jobs': []}},
            {1: {'total_count': 18, 'jobs': actual}, 2: {'total_count': 17, 'jobs': []}},
            {1: {'total_count': 34, 'jobs': actual}, 2: {'total_count': 34, 'jobs': actual}},
        ]
        for pages in cases:
            with self.subTest(pages=pages.keys()):
                self.job_pages = pages
                with self.assertRaises(ValueError):
                    self.prove()

    def test_any_retained_artifact_preserves_the_recovery_owner(self):
        run = str(self.run['id'])
        for name in ('generation-spend-reservation-' + run + '-1', 'generation-spend-state-' + run + '-1',
                     'offline-ai-reconcile-' + 'a' * 64 + '-reservation-' + run + '-1',
                     'candidate-' + 'b' * 64, 'release-plan-1', 'unknown-durable-output'):
            with self.subTest(artifact=name):
                self.artifacts = [self.artifact(name)]
                self.native_artifacts = deepcopy(self.artifacts)
                with self.assertRaises(ValueError):
                    self.prove()

    def test_newly_appeared_or_incompletely_listed_artifacts_cannot_prove_empty(self):
        self.native_artifacts = [self.artifact('generation-spend-reservation-' + str(self.run['id']) + '-1')]
        with self.assertRaises(ValueError):
            self.prove()
        self.native_artifacts = []
        self.artifact_response = {'total_count': 1, 'artifacts': []}
        with self.assertRaises(ValueError):
            self.prove()
        self.artifact_response = {'artifacts': []}
        with self.assertRaises(ValueError):
            self.prove()

    def test_authenticated_archived_reservation_is_not_lost_when_native_list_is_empty(self):
        preserved = self.artifact('generation-spend-reservation-' + str(self.run['id']) + '-1')
        with patch('tools.release_checkpoint_archive.preserved_artifacts', return_value=[preserved]):
            with self.assertRaises(ValueError):
                self.prove()

    def test_existing_independent_archive_even_expired_prevents_empty_history_claim(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                archived = self.artifact('originalrun-' + str(self.run['id']) + '-attempt-1')
                archived['expired'] = expired
                self.repository_artifacts = [archived]
                with self.assertRaises(ValueError):
                    self.prove()
        self.assertFalse(any(path.endswith('/zip') for path in self.calls))

    def test_every_started_producer_including_catalog_correction_stays_held(self):
        original = deepcopy(self.jobs)
        for name in sorted(PRODUCERS):
            with self.subTest(producer=name):
                self.jobs = deepcopy(original)
                for row in self.jobs:
                    if row['name'] not in ('plan', 'closeout'):
                        row['conclusion'] = 'skipped'
                producer = self.job(name)
                producer['conclusion'] = 'cancelled'
                producer['steps'] = [{'name': 'Set up job', 'number': 1,
                                      'status': 'completed', 'conclusion': 'success'}]
                with self.assertRaises(ValueError):
                    self.prove()
                with self.assertRaises(scheduled.Hold):
                    self.owner()

    def test_missing_step_evidence_is_not_an_empty_native_placeholder(self):
        del self.job('generate')['steps']
        with self.assertRaises(ValueError):
            self.prove()

    def test_started_or_unaccounted_plan_resolver_cannot_release_an_allowance(self):
        for conclusion in ('success', 'failure', 'cancelled'):
            with self.subTest(conclusion=conclusion):
                self.resolver()['conclusion'] = conclusion
                with self.assertRaises(ValueError):
                    self.prove()
        self.jobs = deepcopy(self.fixture['jobs_response']['jobs'])
        self.job('plan')['steps'] = [step for step in self.job('plan')['steps']
                                    if step['name'] != 'Resolve explicit lifecycle checkpoint']
        with self.assertRaises(ValueError):
            self.prove()

    def test_published_plan_artifact_step_or_unrelated_plan_work_refuses(self):
        upload = next(step for step in self.job('plan')['steps'] if step['name'] == 'Run actions/upload-artifact@v4')
        upload['conclusion'] = 'success'
        with self.assertRaises(ValueError):
            self.prove()
        self.jobs = deepcopy(self.fixture['jobs_response']['jobs'])
        self.workflow['jobs']['plan']['steps'].insert(0, {'run': 'python -m scripts.enrich_catalog'})
        with self.assertRaises(ValueError):
            self.prove()

    def test_producer_independent_of_plan_is_outside_this_no_start_proof(self):
        self.workflow['jobs']['catalog-correction']['needs'] = []
        with self.assertRaises(ValueError):
            self.prove()

    def test_closeout_is_only_the_known_reporting_job(self):
        self.workflow['jobs']['closeout']['steps'].append({'run': 'python -m scripts.enrich_catalog'})
        with self.assertRaises(ValueError):
            self.prove()


if __name__ == '__main__':
    unittest.main()
