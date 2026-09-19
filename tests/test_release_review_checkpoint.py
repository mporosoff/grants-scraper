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
