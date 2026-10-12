"""Offline authentication and replay contracts for the fixed access correction."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import catalog_access_correction as correction
from tools import release_candidate as c
from tools import release_dependencies as dependencies
from tools.offline_spend import ConfigurationFailure
from tests.test_catalog_source_recovery import archive, groups, changed_group


class Fixture:
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.bundle = self.root/'parent'; self.bundle.mkdir()
        self.payloads = {'data/opportunities.js': b'catalog', 'data/opportunity_teams.js': b'paid teams'}
        generation = {'generation_sha': correction.GENERATION_SHA, 'generation_run_id': '36896442720',
                      'generation_run_attempt': '4', 'generation_timestamp': '2026-10-08T19:10:26+00:00'}
        self.spending = {'original_logical_id': 'offline-36896442720', 'limit_microusd': 2000000,
            'max_requests': 300, 'requests_used': 66, 'charged_microusd': 441023,
            'state_hashes': {str(i): 'd'*64 for i in range(69)},
            'new_document_ai_requests': 0, 'new_vector_requests': 0, 'new_team_requests': 0}
        self.receipt = {'version': 'prior-source-proof', 'spending': self.spending}
        hashes = {n:c.digest(b) for n,b in self.payloads.items()}
        self.manifest = {'schema_version': 1, 'candidate_format': c.VERSION, **generation,
            'files': hashes, 'generation_files': hashes, 'dependency_groups': groups(), 'runtime_baseline': {},
            'source_recovery': self.receipt | {'retained_output_hashes': {}}, 'original_generation': generation.copy()}
        self.manifest['candidate_id'] = c.digest(c.encoded(self.manifest))
        self.raw = c.encoded(self.manifest); (self.bundle/'candidate.json').write_bytes(self.raw)
        for n,b in self.payloads.items():
            p=self.bundle/'files'/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b)
        self.entries = {'candidate': [('candidate.json',self.raw)]+[('files/'+n,b) for n,b in self.payloads.items()],
                        'receipt': [('receipt.json',c.encoded(self.receipt))]}
        self.run = {'id':correction.RUN,'run_attempt':correction.ATTEMPT,'head_sha':correction.EVENT_SHA,
            'head_branch':'main','path':correction.auth.REFRESH,'event':'workflow_dispatch',
            'status':'completed','conclusion':'failure'}
        self.pins = {role:(i,'synthetic-'+role,'') for i,role in enumerate(self.entries,400)}
        self.refresh()
        for key,value in [('PARENT',self.manifest['candidate_id']),('MANIFEST_SHA',c.digest(self.raw)),
                          ('RECEIPT_SHA',c.digest(c.encoded(self.receipt))),('ARTIFACTS',self.pins)]:
            self.stack.enter_context(patch.object(correction,key,value))
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('No network')))
        self.api=Mock(side_effect=self.read_api)

    def refresh(self):
        self.archives={role:archive(entries) for role,entries in self.entries.items()}
        self.metadata={}
        for role,(i,name,_) in list(self.pins.items()):
            sha=c.digest(self.archives[role]); self.pins[role]=(i,name,sha)
            self.metadata[role]={'id':i,'name':name,'digest':'sha256:'+sha,'expired':False,
                'workflow_run':{'id':correction.RUN,'head_sha':correction.EVENT_SHA}}

    def read_api(self,path):
        if path==f'actions/runs/{correction.RUN}/attempts/{correction.ATTEMPT}':return c.encoded(self.run)
        for role,(i,_,_) in self.pins.items():
            if path==f'actions/artifacts/{i}':return c.encoded(self.metadata[role])
            if path==f'actions/artifacts/{i}/zip':return self.archives[role]
        raise AssertionError(path)

    def authenticate(self):return correction.authenticate(self.bundle,api=self.api)


class Authentication(unittest.TestCase):
    def setUp(self):
        self.f=Fixture(); self.addCleanup(self.f.stack.close)

    def test_complete_parent_and_paired_receipt_preserve_original_allowance(self):
        original=deepcopy(self.f.archives)
        manifest,spending=self.f.authenticate()
        self.assertEqual(manifest,self.f.manifest);self.assertEqual(spending,self.f.spending)
        self.assertEqual(self.f.archives,original);self.assertEqual(self.f.api.call_count,5)

    def test_exact_run_attempt_event_branch_sha_and_terminal_state_required(self):
        for key,value in [('id',1),('run_attempt',2),('head_sha','0'*40),('head_branch','other'),
                          ('event','schedule'),('status','in_progress'),('conclusion','success')]:
            with self.subTest(key=key):
                before=self.f.run[key];self.f.run[key]=value
                with self.assertRaisesRegex(ValueError,'original_run'):self.f.authenticate()
                self.f.run[key]=before

    def test_expired_wrong_owner_or_raw_archive_tamper_fails(self):
        for mutate in [lambda m:m.update(expired=True),lambda m:m['workflow_run'].update(id=7),
                       lambda m:m.update(digest='sha256:'+'0'*64)]:
            original=deepcopy(self.f.metadata['receipt']);mutate(self.f.metadata['receipt'])
            with self.assertRaisesRegex(ConfigurationFailure,'artifact_metadata'):self.f.authenticate()
            self.f.metadata['receipt']=original
        self.f.archives['candidate']+=b'changed'
        with self.assertRaisesRegex(ConfigurationFailure,'raw_artifact_digest'):self.f.authenticate()

    def test_local_paid_team_tamper_and_extra_archive_payload_rejected(self):
        target=self.f.bundle/'files/data/opportunity_teams.js';target.write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError,'Candidate bytes differ'):self.f.authenticate()
        target.write_bytes(self.f.payloads['data/opportunity_teams.js'])
        self.f.entries['candidate'].append(('files/unmanifested',b'x'));self.f.refresh()
        with self.assertRaisesRegex(ValueError,'complete_parent'):self.f.authenticate()

    def test_paired_receipt_cannot_be_substituted_even_with_valid_archive(self):
        self.f.entries['receipt']=[('receipt.json',c.encoded({'spending':{'limit_microusd':3000000}}))]
        self.f.refresh()
        with self.assertRaisesRegex(ValueError,'prior_receipt_pin'):self.f.authenticate()


class Boundaries(unittest.TestCase):
    def test_exact_manual_selector_is_required_without_any_additional_allowance(self):
        env = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF':
            'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_ID': correction.PARENT, 'CANDIDATE_RUN': str(correction.RUN),
            'REQUESTED_STAGE': correction.STAGE}
        with patch.object(c, 'git', return_value='a' * 40):
            result = correction.plan(Path('.'), env)
            self.assertEqual((result['openai'], result['anthropic'], result['team_mode']),
                             ('false', 'false', 'maintenance'))
            for key in env:
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'exact_protected_manual_selector'):
                    correction.plan(Path('.'), env | {key: 'other'})
            for key in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT', 'QUALIFICATION_PILOT'):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'no_other_generation_or_recovery'):
                    correction.plan(Path('.'), env | {key: 'true'})

    def test_only_schedule_interpretation_changes_are_authorized(self):
        original={'dependency_groups':groups(),'runtime_baseline':{}}
        allowed=changed_group(original['dependency_groups'],'source','scripts/submission_schedule.py')
        with patch.object(dependencies,'snapshot',return_value=allowed),patch.object(c,'git',return_value=''):
            correction.dependency_scope(Path('.'),original)
        for group,name in [('source','scripts/pull_grants.py'),('source','@document_spend_config'),
                           ('teams','config/offline_ai.json'),('semantic','assets/search-hybrid.js')]:
            with self.subTest(group=group),patch.object(dependencies,'snapshot',return_value=changed_group(original['dependency_groups'],group,name)):
                with self.assertRaisesRegex(ValueError,'bounded_dependency_changes'):
                    correction.dependency_scope(Path('.'),original)

    def test_receipt_replay_rejects_changed_output_or_unrelated_paid_result(self):
        f=Fixture();self.addCleanup(f.stack.close)
        root=f.root/'materialized';root.mkdir();path=f.root/'receipt.json'
        outputs={'data/opportunities.js':b'corrected'};proof={'unchanged_corpus':True};clock='2026-10-12T15:00:00+00:00'
        receipt=correction.receipt_for(f.manifest,f.spending,outputs,proof,clock)
        for n,b in f.payloads.items():
            p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(outputs.get(n,b))
        c.write_json(path,receipt)
        with patch.object(correction,'authenticate',return_value=(f.manifest,f.spending)), \
             patch.object(correction,'derive',return_value=(outputs,proof)), \
             patch.object(dependencies,'snapshot',return_value=f.manifest['dependency_groups']):
            self.assertEqual(correction.verify_inputs(root,f.manifest,f.bundle,path),
                             {'data/opportunity_teams.js':f.manifest['files']['data/opportunity_teams.js']})
            (root/'data/opportunity_teams.js').write_bytes(b'altered teams')
            with self.assertRaisesRegex(ValueError,'Candidate bytes differ'):
                correction.verify_inputs(root,f.manifest,f.bundle,path)
            (root/'data/opportunity_teams.js').write_bytes(f.payloads['data/opportunity_teams.js'])
            receipt['spending']['charged_microusd']=0;c.write_json(path,receipt)
            # Use independent authenticated accounting, not the mutated fixture alias.
            spending=deepcopy(f.spending);spending['charged_microusd']=441023
            with patch.object(correction,'authenticate',return_value=(f.manifest,spending)):
                with self.assertRaisesRegex(ValueError,'deterministic_replay'):
                    correction.verify_inputs(root,f.manifest,f.bundle,path)

    def test_unchanged_rejected_parent_cannot_enter_dependency_readers(self):
        with patch.object(c,'git',side_effect=AssertionError('Quarantine first')):
            with self.assertRaisesRegex(ValueError,'rejected_candidate_requires_exact_access_correction'):
                c.verify_dependencies(Path('.'),{'candidate_id':correction.PARENT})


if __name__=='__main__':unittest.main()
