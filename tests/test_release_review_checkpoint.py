import base64
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml
from tools import prepare_release_publication as preparation
from tools import plan_release as planner
from tools import wait_release_review as reviews


class ReadyCheckpointResume(unittest.TestCase):
    """Retained identities from the automatic release's post-review failure."""
    candidate = '00e42353081aec581f736281838bca26b98c14f01a7aa9d118197521961fb3c4'
    candidate_run = '35948724690'
    base = '37bc8e64fc25b0c3d516ff995e92febb7db42073'
    head = 'f6aa336f2932723f592a03e93b37f0c579be1b8b'
    repository = 'mporosoff/grants-scraper'

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.validation = {'candidate_id': self.candidate, 'validation_sha': self.base,
                           'production_mutated': False,
                           'gates': {gate: 'passed' for gate in planner.c.GATES}}
        self.ready = {'schema_version': 1, 'candidate_id': self.candidate,
                      'base_sha': self.base, 'head_sha': self.head,
                      'pr_url': f'https://github.com/{self.repository}/pull/295',
                      'artifact_run': self.candidate_run,
                      'validation_receipt_sha256': planner.c.digest(planner.c.encoded(self.validation)),
                      'timestamp': '2026-09-24T03:01:14.574352+00:00'}
        self.artifact = {'id': 10787857258, 'name': 'publication-' + self.candidate + '-1',
                         'expired': False, 'workflow_run': {'id': int(self.candidate_run)}}
        self.pr = {'number': 295, 'user': {'login': 'github-actions[bot]'}, 'base': {'ref': 'main'},
                   'head': {'sha': self.head, 'ref': 'automation/release-' + self.candidate[:16] + '-35948724690-1',
                            'repo': {'full_name': self.repository}}}
        self.pointer = {'candidate_id': self.candidate, 'artifact_run': self.candidate_run}
        self.downloads = []
        self.extra_pending = False
        self.omit_validation = False
        self.fetch_head = self.base

    def fetch(self, repository, run, name, destination):
        self.downloads.append((str(run), name))
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if name.startswith('publication-'):
            planner.c.write_json(destination / 'review-ready.json', self.ready)
            if not self.omit_validation:
                planner.c.write_json(destination / 'validation.json', self.validation)
            if self.extra_pending:
                planner.c.write_json(destination / 'review-pending.json', {'status': 'awaiting_review'})
        return {'head_sha': self.fetch_head, 'event': 'push', 'head_branch': 'main',
                'path': '.github/workflows/refresh-opportunities.yml'}

    def api(self, path):
        if '/pulls?' in path:
            return [self.pr]
        return {'encoding': 'base64', 'size': 200,
                'content': base64.b64encode(json.dumps(self.pointer).encode()).decode()}

    def patches(self):
        from contextlib import ExitStack
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('tools.offline_ai_checkpoint.api',
                                 return_value=json.dumps({'artifacts': [self.artifact]}).encode()))
        stack.enter_context(patch('tools.fetch_release_artifact.fetch', side_effect=self.fetch))
        stack.enter_context(patch.object(reviews, 'api', side_effect=self.api))
        return stack

    def read(self, suffix='report'):
        return planner.latest_report(self.repository, self.candidate, 'review', self.root / suffix)

    def test_ready_receipt_selects_original_candidate_after_later_failure(self):
        stack = self.patches()
        stack.enter_context(patch.object(planner.c, 'ROOT', self.root))
        stack.enter_context(patch.object(planner.c, 'load', return_value={}))
        stack.enter_context(patch.object(planner, 'snapshot', return_value={}))
        stack.enter_context(patch.object(planner, 'candidate_groups', return_value={}))
        stack.enter_context(patch.object(planner, 'changed_groups', return_value={'validation': ['tools/plan_release.py']}))
        verify = stack.enter_context(patch.object(planner.c, 'verify_dependencies'))
        stack.enter_context(patch.object(planner.c, 'git', side_effect=lambda root, *args:
                                        self.base if args[0] == 'rev-list' else 'a' * 40))
        planner.c.write_json(self.root / 'release/candidate-source.json',
                             {'candidate_id': 'b' * 64, 'artifact_run': '35941161543'})
        planner.c.write_json(self.root / 'release/candidate.json', {'candidate_id': 'b' * 64})
        environment = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ID': '35950000000',
                       'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REPOSITORY': self.repository,
                       'RUNNER_TEMP': str(self.root), 'GITHUB_OUTPUT': str(self.root / 'output'),
                       'GITHUB_STEP_SUMMARY': str(self.root / 'summary')}
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        planner.main(automatic_paid_hold=True)
        plan = planner.c.read_json(self.root / 'release-plan.json')
        self.assertEqual(plan['stage'], 'publish')  # No assembly or generation.
        self.assertEqual((plan['candidate_run'], plan['candidate_id']), (self.candidate_run, self.candidate))
        self.assertEqual(plan['release_sha'], 'a' * 40)  # New validation code, old candidate.
        self.assertEqual((plan['openai'], plan['anthropic']), ('false', 'false'))
        self.assertNotIn('review_ready', plan)  # Prior review is not current approval.
        verify.assert_called_once()
        self.assertEqual(sum(name.startswith('candidate-') for _, name in self.downloads), 1)

    def test_latest_ready_requires_paired_unchanged_validation_and_run_head(self):
        self.patches()
        self.assertEqual(self.read()[1], self.ready)
        for field, value in (('validation_receipt_sha256', '0' * 64), ('candidate_id', 'c' * 64),
                             ('base_sha', 'd' * 40), ('head_sha', 'invalid')):
            with self.subTest(field=field):
                old = self.ready[field]
                self.ready[field] = value
                with self.assertRaisesRegex(ValueError, 'protected validation'):
                    self.read(field)
                self.ready[field] = old
        self.validation['gates']['python'] = 'failed'
        self.ready['validation_receipt_sha256'] = planner.c.digest(planner.c.encoded(self.validation))
        with self.assertRaisesRegex(ValueError, 'protected validation'):
            self.read('failed-gate')

    def test_conflicting_or_missing_newest_receipt_never_falls_back(self):
        self.patches()
        self.extra_pending = True
        with self.assertRaisesRegex(ValueError, 'Conflicting latest'):
            self.read()
        self.extra_pending = False
        self.omit_validation = True
        with self.assertRaises(FileNotFoundError):
            self.read('missing')

    def test_ready_selection_rejects_changed_pr_pointer_or_unprotected_base(self):
        stack = self.patches()
        stack.enter_context(patch.object(planner.c, 'git', return_value=self.base))
        for field, value in (('head_sha', 'c' * 40), ('pr_url', 'https://github.com/other/repo/pull/295'),
                             ('artifact_run', '35941161543')):
            with self.subTest(field=field):
                old = self.ready[field]
                self.ready[field] = value
                with self.assertRaisesRegex(ValueError, 'exact PR'):
                    planner.pending_publication(self.root, self.repository, self.root / field)
                self.ready[field] = old
        with patch.object(planner.c, 'git', return_value='e' * 40):
            with self.assertRaisesRegex(ValueError, 'protected first-parent'):
                planner.pending_publication(self.root, self.repository, self.root / 'unprotected')


class ReviewCheckpoint(unittest.TestCase):
    def test_only_pending_review_can_defer_and_never_produces_ready_receipt(self):
        with TemporaryDirectory() as d:
            root=Path(d);manifest={'candidate_id':'a'*64}
            with patch.object(preparation.c,'load',return_value=manifest), \
                 patch.dict(os.environ,{'GITHUB_OUTPUT':str(root/'outputs'),'GITHUB_STEP_SUMMARY':str(root/'summary')}):
                with patch.object(preparation,'prepare',side_effect=reviews.ReviewPending('owner/repo',10,'b'*40)):
                    result=preparation.prepare_or_defer('bundle','receipt',root,'123')
                self.assertEqual(result['status'],'awaiting_review')
                self.assertFalse(result['production_mutated'])
                self.assertFalse((root/'review-ready.json').exists())
                self.assertEqual((root/'outputs').read_text(),'review_ready=false\n')
                for failure in (ValueError('P1 finding'),RuntimeError('review service outage')):
                    with patch.object(preparation,'prepare',side_effect=failure):
                        with self.assertRaises(type(failure)):
                            preparation.prepare_or_defer('bundle','receipt',root,'123')
                self.assertEqual((root/'outputs').read_text(),'review_ready=false\n')
                with patch.object(preparation,'prepare',return_value={'head_sha':'b'*40}):
                    preparation.prepare_or_defer('bundle','receipt',root,'123')
                self.assertTrue((root/'outputs').read_text().endswith('review_ready=true\n'))

    def test_wait_exhaustion_is_pending_but_findings_and_outage_are_failures(self):
        with patch.object(reviews.time,'monotonic',side_effect=[0,1]):
            with self.assertRaises(reviews.ReviewPending):
                reviews.wait_for_review('owner/repo',10,'a'*40,timeout=0)
        with patch.object(reviews,'review_state',return_value=(True,[{'body':'P1'}])):
            with self.assertRaisesRegex(ValueError,'findings'):
                reviews.wait_for_review('owner/repo',10,'a'*40)
        with patch.object(reviews,'review_state',side_effect=OSError()),patch.object(reviews.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'unavailable'):
                reviews.wait_for_review('owner/repo',10,'a'*40)

    def test_daily_plan_selects_only_exact_compatible_pending_artifact(self):
        candidate='a'*64;head='b'*40
        pointer={'artifact_run':'123','candidate_id':candidate}
        pr={'number':10,'user':{'login':'github-actions[bot]'},'base':{'ref':'main'},
            'head':{'sha':head,'ref':'automation/release-'+candidate[:16]+'-123-1','repo':{'full_name':'owner/repo'}}}
        data={'encoding':'base64','size':200,'content':base64.b64encode(json.dumps(pointer).encode()).decode()}
        pending={'schema_version':1,'status':'awaiting_review','repository':'owner/repo','pr_number':10,
            'candidate_id':candidate,'artifact_run':'123','head_sha':head,'production_mutated':False}
        with TemporaryDirectory() as d,patch.object(reviews,'api',side_effect=lambda p:[pr] if '/pulls?' in p else data), \
             patch.object(planner,'latest_report',return_value=('123',pending)), \
             patch('tools.fetch_release_artifact.fetch') as fetch,patch.object(planner.c,'load',return_value={}), \
             patch.object(planner,'snapshot',return_value={}),patch.object(planner,'candidate_groups',return_value={}), \
             patch.object(planner,'changed_groups',return_value={}) as changed,patch.object(planner.c,'verify_dependencies') as verify:
            self.assertEqual(planner.pending_publication('.', 'owner/repo', d),
                {'REQUESTED_STAGE':'publish','CANDIDATE_RUN':'123','CANDIDATE_ID':candidate})
            fetch.assert_called_once();verify.assert_called_once()
            changed.return_value={'source':['parser.py']}
            self.assertIsNone(planner.pending_publication('.', 'owner/repo', d))
            changed.return_value={};pending['head_sha']='c'*40
            with self.assertRaisesRegex(ValueError,'exact PR'):
                planner.pending_publication('.', 'owner/repo', d)
            pr['user']['login']='someone-else';fetch.reset_mock()
            self.assertIsNone(planner.pending_publication('.', 'owner/repo', d));fetch.assert_not_called()

    def test_every_serving_step_and_pages_require_review_or_publication(self):
        workflow=yaml.safe_load(Path('.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8'))
        steps=workflow['jobs']['publish']['steps'];start=next(i for i,s in enumerate(steps) if s.get('id')=='review')
        for step in steps[start+1:]:
            if step.get('name','').startswith('Persist the publication'):continue
            condition=step.get('if','')
            self.assertTrue('steps.review.outputs.review_ready' in condition or
                "steps.worker-inputs.outputs.deploy_required == 'true'" in condition or
                'steps.worker-deploy.outcome' in condition,step)
        self.assertIn("needs.publish.outputs.merge_sha != ''",workflow['jobs']['pages']['if'])
        closeout=workflow['jobs']['closeout']['steps'][0]['with']['script']
        self.assertIn('awaiting_review',closeout)
        self.assertIn("needs.publish.outputs.merge_sha ? 'protected publication completed'",closeout)


if __name__=='__main__': unittest.main()
