"""Offline archive, spending and dependency contracts for identity-only recovery."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from tools import catalog_identity_correction as correction
from tools import release_candidate as candidate
from tools import release_dependencies as dependencies
from tools.offline_spend import ConfigurationFailure
from tests.test_catalog_source_recovery import archive, groups, changed_group

class AuthenticationFixture:
    """Real ZIP/digest/manifest authentication with synthetic immutable pins."""
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='source-recovery-contract-')))
        self.bundle = self.root/'parent'
        self.payloads = {
            'data/opportunities.js': b'original public catalog',
            'config/opportunity_team_model.json': b'original team evidence',
            'data/search-v2-voyage-canaries.json': b'original canaries',
            'evaluation/search_v2_hybrid_vector_build.json': candidate.encoded({
                'API_request_count': 6, 'usage_total_tokens': 300499,
                'estimated_cost_at_published_paid_pricing_usd': .006010}),
        }
        hashes = {name: candidate.digest(raw) for name, raw in self.payloads.items()}
        self.manifest = {'schema_version': 1, 'candidate_format': candidate.VERSION,
            'files': hashes, 'generation_files': hashes,
            'generation_sha': correction.GENERATION_SHA, 'generation_run_id': str(correction.RUN),
            'generation_run_attempt': str(correction.ATTEMPT), 'dependency_groups': groups(),
            'runtime_baseline': {}}
        self.manifest['candidate_id'] = candidate.digest(candidate.encoded(self.manifest))
        self.raw_manifest = candidate.encoded(self.manifest)
        for name, raw in self.payloads.items():
            path = self.bundle/'files'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        (self.bundle/'candidate.json').write_bytes(self.raw_manifest)
        ledger = {'logical_id': 'offline-' + str(correction.RUN), 'limit_microusd': 2_000_000,
            'max_requests': 300, 'requests': [], 'events': [{'kind':'service_stop','reason':'quality_gate_pending','service':'teams'}]}
        self.state = {'ledger.json': candidate.encoded(ledger), 'team-progress.json': b'{"unchanged":true}\n'}
        reservation = {'attempt': '1', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': '52d9934aedd0dde3266c52e648012bf6b218e5c434361b5a4a360ccfd41fa4ca',
            'run_id': str(correction.RUN)}
        self.entries = {'candidate': [('candidate.json', self.raw_manifest)] + [('files/' + n, b) for n, b in self.payloads.items()],
            'state': list(self.state.items()), 'reservation': [('spend-reservation.json', candidate.encoded(reservation))]}
        self.run = {'id': correction.RUN, 'run_attempt': correction.ATTEMPT, 'head_sha': correction.EVENT_SHA,
            'head_branch': 'main', 'path': correction.auth.REFRESH, 'event': 'workflow_dispatch',
            'status': 'completed', 'conclusion': 'failure'}
        self.pins = {role: (number, 'synthetic-' + role, '') for number, role in enumerate(self.entries, 301)}
        self.refresh_archives()
        for name, value in [('PARENT', self.manifest['candidate_id']), ('MANIFEST_SHA', candidate.digest(self.raw_manifest)),
            ('LEDGER_SHA', candidate.digest(self.state['ledger.json'])), ('ARTIFACTS', self.pins)]:
            self.stack.enter_context(patch.object(correction, name, value))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')))
        self.api = Mock(side_effect=self.read_api)
        self.stack.enter_context(patch.object(correction, 'authenticate_previous', return_value={'authenticated': True}))

    def refresh_archives(self):
        self.archives = {role: archive(entries) for role, entries in self.entries.items()}
        self.metadata = {}
        for role, (identifier, name, _) in list(self.pins.items()):
            sha = candidate.digest(self.archives[role]); self.pins[role] = (identifier, name, sha)
            self.metadata[role] = {'id': identifier, 'name': name, 'expired': False, 'digest': 'sha256:' + sha,
                'workflow_run': {'id': correction.RUN, 'head_sha': correction.EVENT_SHA}}

    def read_api(self, path):
        if path == f'actions/runs/{correction.RUN}/attempts/{correction.ATTEMPT}':
            return candidate.encoded(self.run)
        for role, (identifier, _, _) in self.pins.items():
            if path == f'actions/artifacts/{identifier}': return candidate.encoded(self.metadata[role])
            if path == f'actions/artifacts/{identifier}/zip': return self.archives[role]
        raise AssertionError('Unexpected authentication route: ' + path)

    def authenticate(self):
        return correction.authenticate(self.bundle, api=self.api)

    def close(self):
        self.stack.close()


class AuthenticationContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = AuthenticationFixture(); self.addCleanup(self.fixture.close)

    def test_exact_archives_authenticate_without_rewriting_spend_or_original_payloads(self):
        fixture = self.fixture
        archived = deepcopy(fixture.archives)
        manifest, spending = fixture.authenticate()
        self.assertEqual(manifest, fixture.manifest)
        self.assertEqual(spending['requests_used'], 0)
        self.assertEqual(spending['charged_microusd'], 0)
        self.assertEqual(spending['prior_vector_requests'], 6)
        self.assertEqual(spending['prior_vector_tokens'], 300499)
        self.assertEqual([spending[name] for name in ('new_document_ai_requests', 'new_vector_requests', 'new_team_requests')], [0, 0, 0])
        self.assertEqual(spending['state_hashes'], {n: candidate.digest(raw) for n, raw in fixture.state.items()})
        self.assertEqual(fixture.archives, archived)
        self.assertEqual((fixture.bundle/'candidate.json').read_bytes(), fixture.raw_manifest)
        self.assertEqual(fixture.api.call_count, 7)

    def test_run_attempt_branch_event_sha_and_terminal_state_are_bound(self):
        fixture = self.fixture
        for key, invalid in [('run_attempt', 3), ('head_sha', '0' * 40), ('head_branch', 'feature'),
            ('event', 'schedule'), ('status', 'in_progress'), ('conclusion', 'success')]:
            with self.subTest(key=key):
                before = fixture.run[key]; fixture.run[key] = invalid
                with self.assertRaisesRegex(ValueError, 'original_run'): fixture.authenticate()
                fixture.run[key] = before

    def test_artifact_owner_digest_and_expiry_cannot_be_substituted(self):
        fixture = self.fixture
        for mutate in [lambda meta: meta.update(expired=True), lambda meta: meta.update(digest='sha256:' + '0' * 64),
            lambda meta: meta['workflow_run'].update(id=correction.RUN + 1),
            lambda meta: meta['workflow_run'].update(head_sha='0' * 40)]:
            with self.subTest(mutation=mutate):
                before = deepcopy(fixture.metadata['state']); mutate(fixture.metadata['state'])
                with self.assertRaisesRegex(ConfigurationFailure, 'artifact_metadata'): fixture.authenticate()
                fixture.metadata['state'] = before
        fixture.archives['state'] += b'changed'
        with self.assertRaisesRegex(ConfigurationFailure, 'raw_artifact_digest'): fixture.authenticate()

    def test_local_parent_tamper_and_extra_authenticated_archive_payload_fail(self):
        fixture = self.fixture
        path = fixture.bundle/'files/config/opportunity_team_model.json'; original = path.read_bytes()
        path.write_bytes(b'altered team')
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'): fixture.authenticate()
        path.write_bytes(original)
        fixture.entries['candidate'].append(('files/extra.json', b'{}'))
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'complete_parent'): fixture.authenticate()

    def test_ledger_and_reservation_are_independently_pinned_after_archive_authentication(self):
        fixture = self.fixture
        fixture.entries['state'][0] = ('ledger.json', fixture.state['ledger.json'] + b' ')
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'original_ledger'): fixture.authenticate()
        fixture.entries['state'] = list(fixture.state.items())
        reservation = json.loads(fixture.entries['reservation'][0][1]); reservation['maximum_logical_spend_usd'] = 3
        fixture.entries['reservation'] = [('spend-reservation.json', candidate.encoded(reservation))]
        fixture.refresh_archives()
        with self.assertRaisesRegex(ValueError, 'original_reservation'): fixture.authenticate()



class SelectorAndReplay(unittest.TestCase):
    def test_exact_manual_selector_and_no_competing_allowance(self):
        env={'GITHUB_REPOSITORY':'mporosoff/grants-scraper','GITHUB_REF':'refs/heads/main',
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW_REF':
            'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'CANDIDATE_ID':correction.PARENT,'CANDIDATE_RUN':str(correction.RUN),'REQUESTED_STAGE':correction.STAGE}
        with patch.object(candidate,'git',return_value='a'*40):
            result=correction.plan(Path('.'),env)
            self.assertEqual((result['openai'],result['anthropic']),('false','false'))
            for key in env:
                with self.subTest(key=key), self.assertRaisesRegex(ValueError,'exact_protected_manual_selector'):
                    correction.plan(Path('.'),env|{key:'wrong'})
            for key in ('RECEIPT_RUN','PUBLICATION_RUN','PUBLICATION_ATTEMPT','QUALIFICATION_PILOT'):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError,'no_other_generation_or_recovery'):
                    correction.plan(Path('.'),env|{key:'true'})

    def test_dependency_boundary_excludes_paid_inputs_and_other_sources(self):
        original={'dependency_groups':groups(),'runtime_baseline':{}}
        for name in correction.SOURCE_REPAIR_FILES - {'@generation_invocations'}:
            with patch.object(dependencies,'snapshot',return_value=changed_group(original['dependency_groups'],'source',name)),patch.object(candidate,'git',return_value=''):
                correction.dependency_scope(Path('.'),original)
        for group,name in [('source','scripts/pull_grants.py'),('source','@document_spend_config'),
                           ('teams','config/offline_ai.json'),('semantic','assets/search-hybrid.js')]:
            with self.subTest(group=group,name=name),patch.object(dependencies,'snapshot',return_value=changed_group(original['dependency_groups'],group,name)):
                with self.assertRaisesRegex(ValueError,'bounded_dependency_changes'):
                    correction.dependency_scope(Path('.'),original)

    def test_only_exact_previous_catalog_invocation_transition_is_allowed(self):
        original={'dependency_groups':groups(),'runtime_baseline':{}}
        before=changed_group(original['dependency_groups'],'source','@generation_invocations')
        before['source']['files']['@generation_invocations']=correction.INVOCATIONS_BEFORE
        original['dependency_groups']=before
        after=deepcopy(before);after['source']['files']['@generation_invocations']=correction.INVOCATIONS_AFTER
        after['source']['fingerprint']=candidate.digest(candidate.encoded(after['source']['files']))
        with patch.object(dependencies,'snapshot',return_value=after):
            correction.verify_source_scope(Path('.'),original)
            after['source']['files']['@generation_invocations']='0'*64
            with self.assertRaisesRegex(ValueError,'exact_previous_catalog_invocation'):
                correction.verify_source_scope(Path('.'),original)

    def test_replay_rejects_unrelated_science_tamper_and_changed_accounting(self):
        f=AuthenticationFixture();self.addCleanup(f.close)
        original,spending=f.authenticate()
        root=f.root/'materialized';root.mkdir();path=f.root/'receipt.json'
        outputs={'data/opportunities.js':b'identity correction'};proof={'no_science_changes':True};clock='2026-10-12T17:00:00+00:00'
        receipt=correction.receipt_for(original,spending,outputs,proof,clock)
        for name,raw in f.payloads.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(outputs.get(name,raw))
        candidate.write_json(path,receipt)
        with patch.object(correction,'authenticate',return_value=(original,spending)),patch.object(correction,'derive',return_value=(outputs,proof)),patch.object(dependencies,'snapshot',return_value=original['dependency_groups']):
            kept=correction.verify_inputs(root,original,f.bundle,path)
            self.assertIn('config/opportunity_team_model.json',kept)
            target=root/'config/opportunity_team_model.json';target.write_bytes(b'changed scientific teams')
            with self.assertRaisesRegex(ValueError,'Candidate bytes differ'):correction.verify_inputs(root,original,f.bundle,path)
            target.write_bytes(f.payloads['config/opportunity_team_model.json'])
            altered=deepcopy(receipt);altered['spending']['prior_vector_requests']=0;candidate.write_json(path,altered)
            with self.assertRaisesRegex(ValueError,'deterministic_replay'):correction.verify_inputs(root,original,f.bundle,path)


class PreviousIdentityAuthentication(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        native={'opportunity_id':'nasa-roses:25-B.8-c9ad18a888','opportunity_number':'NNH25ZDA001N-SSF',
            'source':'NASA ROSES','detail_page':'https://solicitation.nasaprs.com/NNH25ZDA001N-SSF',
            'funding_opportunity_url':'https://solicitation.nasaprs.com/NNH25ZDA001N-SSF'}
        prior={'opportunity_id':'363829','source':'Grants.gov','source_aliases':[{'opportunity_id':'vpr-a3ddeff815d159a4','source':'VPR'}]}
        self.records={row['opportunity_id']:row for row in (native,prior)}
        value_hash=lambda v:candidate.digest(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
        raw=b'window.CATALOG = '+candidate.encoded({'opportunities':[native,prior]})+b';'
        manifest={'schema_version':1,'candidate_format':candidate.VERSION,'files':{'data/opportunities.js':candidate.digest(raw)}}
        manifest['candidate_id']=candidate.digest(candidate.encoded(manifest))
        manifest_raw=candidate.encoded(manifest)
        self.packet={'candidate.json':manifest_raw,'files/data/opportunities.js':raw}
        self.policy={'previous_candidate_id':manifest['candidate_id'],'previous_manifest_sha256':candidate.digest(manifest_raw),
            'previous_record_hashes':{key:value_hash(row) for key,row in self.records.items()},
            'corrections':[{'opportunity_id':'364039','previous_opportunity_id':native['opportunity_id'],'source_aliases':[native.copy()]},
                           {'opportunity_id':'363829','previous_opportunity_id':'363829','source_aliases':deepcopy(prior['source_aliases'])}]}
        self.run={'id':correction.PREVIOUS_RUN,'run_attempt':1,'head_sha':correction.PREVIOUS_SHA,
            'head_branch':'main','path':correction.auth.REFRESH,'event':'workflow_dispatch','status':'completed','conclusion':'success'}
        self.raw=archive(list(self.packet.items()));self.identifier=991
        self.metadata={'id':self.identifier,'name':'previous-synthetic','digest':'sha256:'+candidate.digest(self.raw),'expired':False,
            'workflow_run':{'id':correction.PREVIOUS_RUN,'head_sha':correction.PREVIOUS_SHA}}
        self.stack.enter_context(patch.object(correction,'PREVIOUS',manifest['candidate_id']))
        self.stack.enter_context(patch.object(correction,'PREVIOUS_MANIFEST_SHA',candidate.digest(manifest_raw)))
        self.stack.enter_context(patch.object(correction,'PREVIOUS_ARTIFACT',(self.identifier,'previous-synthetic',candidate.digest(self.raw))))
        self.stack.enter_context(patch.dict('sys.modules',{'tools.catalog_identity_projection':SimpleNamespace(policy=lambda:self.policy,value_hash=value_hash)}))
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('No network')))

    def api(self,path):
        if path==f'actions/runs/{correction.PREVIOUS_RUN}/attempts/1':return candidate.encoded(self.run)
        if path==f'actions/artifacts/{self.identifier}':return candidate.encoded(self.metadata)
        if path==f'actions/artifacts/{self.identifier}/zip':return self.raw
        raise AssertionError(path)

    def test_previous_publication_authenticates_every_payload_and_exact_alias_values(self):
        result=correction.authenticate_previous(api=self.api)
        self.assertEqual(result['record_hashes'],self.policy['previous_record_hashes'])
        self.assertEqual(result['artifact_sha256'],candidate.digest(self.raw))

    def test_cannot_attach_an_invented_alias_to_authentic_previous_records(self):
        self.policy['corrections'][0]['source_aliases'][0]['opportunity_id']='wrong-source-id'
        with self.assertRaisesRegex(ValueError,'previous_alias_values'):correction.authenticate_previous(api=self.api)

    def test_cannot_drop_identity_evidence_or_substitute_different_previous_record(self):
        self.policy['previous_record_hashes']['363829']='0'*64
        with self.assertRaisesRegex(ValueError,'previous_identity_evidence'):correction.authenticate_previous(api=self.api)

    def test_prior_run_must_have_successfully_completed(self):
        self.run['conclusion']='failure'
        with self.assertRaisesRegex(ValueError,'original_run'):correction.authenticate_previous(api=self.api)

    def test_raw_prior_archive_must_match_authenticated_metadata(self):
        self.raw+=b'tamper'
        with self.assertRaisesRegex(ConfigurationFailure,'raw_artifact_digest'):correction.authenticate_previous(api=self.api)

if __name__=='__main__':unittest.main()
