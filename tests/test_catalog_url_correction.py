"""Authentication and replay boundaries for a URL-only child of a prior repair."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import catalog_url_correction as u
from tools import catalog_identity_correction as i
from tools import release_candidate as c
from tools import release_dependencies as d
from tools.offline_spend import ConfigurationFailure
from tests.test_catalog_identity_correction import AuthenticationFixture
from tests.test_catalog_source_recovery import archive, groups, changed_group


def parser_groups(parser_hash):
    value=groups()
    value['source']['files']['scripts/build_catalog.py']=parser_hash
    value['source']['fingerprint']=c.digest(c.encoded(value['source']['files']))
    return value


class URLFixture(AuthenticationFixture):
    def __init__(self):
        super().__init__()
        self.manifest['dependency_groups']=parser_groups(u.PARSER_BEFORE)
        self.manifest.update(generation_timestamp='2026-10-12T16:13:28+00:00',
                             team_identity={'generation_id':'unchanged'},semantic_identity={'corpus_sha256':'a'*64})
        self.manifest.pop('candidate_id')
        self.manifest['candidate_id']=c.digest(c.encoded(self.manifest))
        self.raw_manifest=c.encoded(self.manifest)
        (self.bundle/'candidate.json').write_bytes(self.raw_manifest)
        self.entries['candidate'][0]=('candidate.json',self.raw_manifest)
        self.refresh_archives()
        self.stack.enter_context(patch.object(i,'PARENT',self.manifest['candidate_id']))
        self.stack.enter_context(patch.object(i,'MANIFEST_SHA',c.digest(self.raw_manifest)))
        generated,self.spending=super().authenticate()
        self.receipt={'version':i.VERSION,'parent_candidate':i.PARENT,'spending':self.spending}
        self.child=deepcopy(generated)
        self.child.update(derived_from_candidate=i.PARENT,assembly_sha=u.EVENT_SHA,
            identity_correction=self.receipt | {'affected_generation':{
                'generation_sha':u.EVENT_SHA,'generation_run_id':str(u.RUN),'generation_run_attempt':'1'}},
            original_generation={k:generated[k] for k in ('generation_sha','generation_run_id','generation_timestamp')})
        self.child.pop('candidate_id')
        self.child['candidate_id']=c.digest(c.encoded(self.child))
        self.child_raw=c.encoded(self.child)
        self.url_bundle=self.root/'url-parent'
        for name,raw in self.payloads.items():
            path=self.url_bundle/'files'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (self.url_bundle/'candidate.json').write_bytes(self.child_raw)
        self.url_entries={'candidate':[('candidate.json',self.child_raw)]+[('files/'+n,b) for n,b in self.payloads.items()],
                          'receipt':[('receipt.json',c.encoded(self.receipt))]}
        self.url_run=dict(self.run,id=u.RUN,head_sha=u.EVENT_SHA)
        self.url_pins={role:(number,'url-'+role,'') for number,role in enumerate(self.url_entries,701)}
        self.refresh_url_archives()
        for name,value in [('PARENT',self.child['candidate_id']),('MANIFEST_SHA',c.digest(self.child_raw)),
                           ('IDENTITY_RECEIPT_SHA',c.digest(c.encoded(self.receipt))),('ARTIFACTS',self.url_pins)]:
            self.stack.enter_context(patch.object(u,name,value))
        self.superseded_receipt={'version':'catalog-url-correction-20261012-v1',
            'parent_candidate':u.PARENT,'parent_manifest_sha256':u.MANIFEST_SHA,'parent_run':u.RUN}
        self.superseded=deepcopy(self.child)
        self.superseded.update(derived_from_candidate=u.PARENT,assembly_sha='9'*40,
            url_correction=self.superseded_receipt | {'affected_generation':{
                'generation_sha':'9'*40,'generation_run_id':'800','generation_run_attempt':'1',
                'generation_timestamp':'2026-10-12T17:48:18+00:00'}})
        self.superseded.pop('candidate_id')
        self.superseded['candidate_id']=c.digest(c.encoded(self.superseded))
        self.superseded_entries={'candidate':[('candidate.json',c.encoded(self.superseded))]+
            [('files/'+n,b) for n,b in self.payloads.items()],
            'receipt':[('receipt.json',c.encoded(self.superseded_receipt))]}
        self.superseded_run=dict(self.run,id=800,head_sha='9'*40)
        self.superseded_latest=deepcopy(self.superseded_run)
        self.superseded_proof={'candidate_id':self.superseded['candidate_id'],
            'manifest_sha256':c.digest(c.encoded(self.superseded)),
            'producer':{'run_id':800,'run_attempt':1,'event_sha':'9'*40},
            'receipt_sha256':c.digest(c.encoded(self.superseded_receipt)),
            'artifacts':{'candidate':{'id':801},'receipt':{'id':802}}}
        self.refresh_superseded_archives()
        self.stack.enter_context(patch.object(u,'SUPERSEDED_URL_CORRECTION',self.superseded_proof))

    def refresh_superseded_archives(self):
        self.superseded_archives={role:archive(entries) for role,entries in self.superseded_entries.items()}
        self.superseded_metadata={}
        for role,pin in self.superseded_proof['artifacts'].items():
            digest=c.digest(self.superseded_archives[role]);pin['sha256']=digest
            name='candidate-'+self.superseded['candidate_id'] if role=='candidate' else 'url-correction-800-1'
            self.superseded_metadata[role]={'id':pin['id'],'name':name,'expired':False,
                'digest':'sha256:'+digest,'workflow_run':{'id':800,'head_sha':'9'*40}}

    def refresh_url_archives(self):
        self.url_archives={role:archive(entries) for role,entries in self.url_entries.items()}
        self.url_metadata={}
        for role,(identifier,name,_) in self.url_pins.items():
            digest=c.digest(self.url_archives[role]);self.url_pins[role]=(identifier,name,digest)
            self.url_metadata[role]={'id':identifier,'name':name,'expired':False,'digest':'sha256:'+digest,
                                    'workflow_run':{'id':u.RUN,'head_sha':u.EVENT_SHA}}

    def read_url_api(self,path):
        if path=='actions/runs/800/attempts/1':return c.encoded(self.superseded_run)
        if path=='actions/runs/800':return c.encoded(self.superseded_latest)
        for role,pin in self.superseded_proof['artifacts'].items():
            if path==f"actions/artifacts/{pin['id']}":return c.encoded(self.superseded_metadata[role])
            if path==f"actions/artifacts/{pin['id']}/zip":return self.superseded_archives[role]
        if path==f'actions/runs/{u.RUN}/attempts/1':return c.encoded(self.url_run)
        for role,(identifier,_,_) in self.url_pins.items():
            if path==f'actions/artifacts/{identifier}':return c.encoded(self.url_metadata[role])
            if path==f'actions/artifacts/{identifier}/zip':return self.url_archives[role]
        return self.read_api(path)

    def authenticate_url(self):
        return u.authenticate(self.url_bundle,api=self.read_url_api)


class URLAuthentication(unittest.TestCase):
    def setUp(self):
        self.f=URLFixture();self.addCleanup(self.f.close)

    def test_both_original_spending_and_prior_identity_receipt_are_authenticated(self):
        before=deepcopy(self.f.url_archives)
        manifest,spending=self.f.authenticate_url()
        self.assertEqual(manifest,self.f.child)
        self.assertEqual(spending['state_hashes'],self.f.spending['state_hashes'])
        self.assertEqual(spending['identity_parent']['candidate_id'],self.f.child['candidate_id'])
        self.assertEqual((spending['new_document_ai_requests'],spending['new_vector_requests'],spending['new_team_requests']),(0,0,0))
        self.assertEqual(self.f.url_archives,before)

    def test_wrong_run_and_artifact_owner_and_raw_bytes_fail_closed(self):
        for key,value in [('status','in_progress'),('head_sha','0'*40),('run_attempt',2),('conclusion','success')]:
            with self.subTest(key=key):
                saved=self.f.url_run[key];self.f.url_run[key]=value
                with self.assertRaisesRegex(ValueError,'original_run'):self.f.authenticate_url()
                self.f.url_run[key]=saved
        self.f.url_metadata['receipt']['workflow_run']['id']+=1
        with self.assertRaisesRegex(ConfigurationFailure,'artifact_metadata'):self.f.authenticate_url()
        self.f.url_metadata['receipt']['workflow_run']['id']=u.RUN
        self.f.url_archives['receipt']+=b'tampered'
        with self.assertRaisesRegex(ConfigurationFailure,'raw_artifact_digest'):self.f.authenticate_url()

    def test_extra_payload_and_mutated_prior_receipt_are_rejected(self):
        self.f.url_entries['candidate'].append(('files/extra.txt',b'unreviewed'))
        self.f.refresh_url_archives()
        with self.assertRaisesRegex(ValueError,'complete_parent'):self.f.authenticate_url()
        self.f.url_entries['candidate'].pop()
        self.f.url_entries['receipt'][0]=('receipt.json',c.encoded(self.f.receipt)+b' ')
        self.f.refresh_url_archives()
        with self.assertRaisesRegex(ValueError,'identity_receipt_pin'):self.f.authenticate_url()

    def test_superseded_run_must_remain_exact_terminal_attempt(self):
        for key,value in [('status','in_progress'),('head_sha','0'*40),('run_attempt',2),('conclusion','success')]:
            with self.subTest(key=key):
                saved=self.f.superseded_latest[key];self.f.superseded_latest[key]=value
                with self.assertRaisesRegex(ValueError,'superseded_latest_attempt'):self.f.authenticate_url()
                self.f.superseded_latest[key]=saved

    def test_superseded_artifacts_and_complete_manifest_remain_authenticated(self):
        self.f.superseded_metadata['receipt']['expired']=True
        with self.assertRaisesRegex(ConfigurationFailure,'artifact_metadata'):self.f.authenticate_url()
        self.f.superseded_metadata['receipt']['expired']=False
        self.f.superseded_archives['candidate']+=b'tampered'
        with self.assertRaisesRegex(ConfigurationFailure,'raw_artifact_digest'):self.f.authenticate_url()
        self.f.refresh_superseded_archives()
        self.f.superseded_entries['candidate'].append(('files/extra.txt',b'unreviewed'))
        self.f.refresh_superseded_archives()
        with self.assertRaisesRegex(ValueError,'complete_superseded'):self.f.authenticate_url()

    def test_superseded_receipt_and_manifest_pins_cannot_be_relabelled(self):
        self.f.superseded_entries['receipt'][0]=('receipt.json',c.encoded(self.f.superseded_receipt)+b' ')
        self.f.refresh_superseded_archives()
        with self.assertRaisesRegex(ValueError,'superseded_receipt_pin'):self.f.authenticate_url()
        self.f.superseded_entries['receipt'][0]=('receipt.json',c.encoded(self.f.superseded_receipt))
        self.f.refresh_superseded_archives()
        self.f.superseded_proof['manifest_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'superseded_manifest'):self.f.authenticate_url()

    def test_both_rejected_candidates_are_quarantined(self):
        for identifier in (u.PARENT,u.SUPERSEDED_URL_CORRECTION['candidate_id']):
            with self.assertRaisesRegex(ValueError,'rejected_candidate'):u.reject_quarantined({'candidate_id':identifier})
        u.reject_quarantined({'candidate_id':'a'*64})

    def test_original_allowance_cannot_be_replaced_after_parent_authentication(self):
        state=self.f.state['ledger.json']
        self.f.entries['state'][0]=('ledger.json',state+b' ')
        self.f.refresh_archives()
        with self.assertRaisesRegex(ValueError,'original_ledger'):self.f.authenticate_url()


class URLReplay(unittest.TestCase):
    def test_exact_parser_pair_and_validation_only_changes_pass(self):
        original={'dependency_groups':parser_groups(u.PARSER_BEFORE),'runtime_baseline':{}}
        after=parser_groups(u.PARSER_AFTER)
        for snapshot in (after,changed_group(after,'validation','tests/test_source_urls.py')):
            with patch.object(d,'snapshot',return_value=snapshot),patch.object(c,'git',return_value=''):
                u.dependency_scope(Path('.'),original)

    def test_only_reviewed_parser_transition_can_bless_retained_generation(self):
        original={'dependency_groups':parser_groups(u.PARSER_BEFORE),'runtime_baseline':{}}
        for after in (parser_groups('f'*64),parser_groups(u.PARSER_BEFORE),groups()):
            with self.subTest(after=after),patch.object(d,'snapshot',return_value=after):
                with self.assertRaisesRegex(ValueError,'exact_parser_transition'):
                    u.verify_source_scope(Path('.'),original)
        for before in (parser_groups('f'*64),parser_groups(u.PARSER_AFTER),groups()):
            with self.subTest(before=before),patch.object(d,'snapshot',return_value=parser_groups(u.PARSER_AFTER)):
                with self.assertRaisesRegex(ValueError,'exact_parser_transition'):
                    u.verify_source_scope(Path('.'),{'dependency_groups':before})

    def test_other_generation_changes_remain_blocked(self):
        original={'dependency_groups':parser_groups(u.PARSER_BEFORE),'runtime_baseline':{}}
        after=parser_groups(u.PARSER_AFTER)
        for group,name in [('source','scripts/sources/merge.py'),('source','@generation_invocations'),
                           ('teams','config/offline_ai.json'),('semantic','assets/search-hybrid.js')]:
            with self.subTest(group=group,name=name),patch.object(d,'snapshot',return_value=changed_group(after,group,name)):
                with self.assertRaisesRegex(ValueError,'bounded_dependency_changes'):u.verify_source_scope(Path('.'),original)

    def test_exact_protected_selector_only(self):
        env={'GITHUB_REPOSITORY':'mporosoff/grants-scraper','GITHUB_REF':'refs/heads/main',
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW_REF':
            'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_ID':u.PARENT,'CANDIDATE_RUN':str(u.RUN),'REQUESTED_STAGE':u.STAGE}
        with patch.object(c,'git',return_value='a'*40):
            self.assertEqual(u.plan(Path('.'),env)['openai'],'false')
            for key in env:
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'exact_protected_manual_selector'):
                    u.plan(Path('.'),env|{key:'wrong'})
            for key in ('RECEIPT_RUN','PUBLICATION_RUN','PUBLICATION_ATTEMPT','QUALIFICATION_PILOT'):
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'no_other_generation_or_recovery'):
                    u.plan(Path('.'),env|{key:'true'})

    def test_constructor_replay_rejects_science_tamper_and_receipt_relabeling(self):
        f=URLFixture();self.addCleanup(f.close)
        original,spending=f.authenticate_url();root=f.root/'materialized';root.mkdir();receipt_path=f.root/'receipt.json'
        outputs={'data/opportunities.js':b'URL correction'};proof={'no_science_changes':True};clock='2026-10-12T18:00:00+00:00'
        receipt=u.receipt_for(original,spending,outputs,proof,clock)
        for name,raw in f.payloads.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(outputs.get(name,raw))
        c.write_json(receipt_path,receipt)
        with patch.object(u,'authenticate',return_value=(original,spending)),patch.object(u,'derive',return_value=(outputs,proof)),patch.object(d,'snapshot',return_value=parser_groups(u.PARSER_AFTER)):
            retained=u.verify_inputs(root,original,f.url_bundle,receipt_path)
            self.assertIn('config/opportunity_team_model.json',retained)
            path=root/'config/opportunity_team_model.json';path.write_bytes(b'changed science')
            with self.assertRaisesRegex(ValueError,'Candidate bytes differ'):u.verify_inputs(root,original,f.url_bundle,receipt_path)
            path.write_bytes(f.payloads['config/opportunity_team_model.json'])
            altered=deepcopy(receipt);altered['spending']['prior_vector_requests']=0;c.write_json(receipt_path,altered)
            with self.assertRaisesRegex(ValueError,'deterministic_replay'):u.verify_inputs(root,original,f.url_bundle,receipt_path)

if __name__=='__main__':unittest.main()
