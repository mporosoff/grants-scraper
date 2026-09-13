import copy
import io
import zipfile
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from tools import contextual_team_token_preflight as sizing
from tools.contextual_team_executor import RecoveryRequired


class Response:
    status_code=200
    def __init__(self,value):self.value=value
    def iter_content(self,chunk_size):yield json.dumps(self.value).encode()
    def close(self):pass


class TokenSizing(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture','GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40})
        env.start();self.addCleanup(env.stop)

    def state(self,directory):
        state=Path(directory)/'state';state.mkdir()
        (state/'ledger.json').write_bytes((sizing.existing.CONFIG/'initial-ledger.json').read_bytes())
        sizing.existing.checkpoint(state)
        return state

    def archive(self,state):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for p in state.rglob('*'):
                if p.is_file():archive.writestr(p.relative_to(state).as_posix(),p.read_bytes())
        return buffer.getvalue()

    def test_inventory_is_fixed_public_data_and_no_inference(self):
        items=sizing.inventory()
        self.assertEqual(len(items),167)
        self.assertEqual(len([x for x in items if x['id'].startswith('profile:')]),155)
        self.assertTrue(all(x['body']['model']=='claude-sonnet-5' for x in items))
        self.assertTrue(all('max_tokens' not in x['body'] for x in items))
        self.assertEqual(sizing.identity(items),sizing.identity(sizing.inventory()))
        self.assertEqual(len([x for x in items if x['id'].endswith(':judge-evidence')]),3)
        retained=[x for x in items if not x['id'].endswith(':judge-evidence')]
        self.assertEqual(sizing.identity(retained),'0ba9d748d10e4a03b9476bb8a0884284f88c0d48d71792c1f6ec3e2992e4ce78')

    def test_complete_count_cached_without_ledger_or_message_dispatch(self):
        calls=[]
        def post(url,**kw):calls.append((url,kw));return Response({'input_tokens':456})
        item={'id':'fixture','body':sizing.count_body('Fixture only, not scientific evidence.')}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
            state=self.state(d);before=(state/'ledger.json').read_bytes();counter=sizing.Counter(state,post)
            self.assertEqual(counter.count(item),456)
            for _ in range(3):self.assertEqual(sizing.Counter(state,post).count(copy.deepcopy(item)),456)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],sizing.ENDPOINT)
            self.assertFalse(calls[0][1]['allow_redirects'])
            self.assertEqual((state/'ledger.json').read_bytes(),before)

    def test_unknown_counter_outcome_not_automatically_repeated(self):
        calls=[]
        def post(*a,**k):calls.append(1);raise TimeoutError('fixture')
        item={'id':'fixture','body':sizing.count_body('fixture')}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
            state=self.state(d)
            with self.assertRaises(TimeoutError):sizing.Counter(state,post).count(item)
            for _ in range(3):
                with self.assertRaises(RecoveryRequired):sizing.Counter(state,post).count(item)
            self.assertEqual(len(calls),1)

    def test_complete_and_interrupted_counts_survive_actual_archive_restore(self):
        e=sizing.existing
        for interrupted in (False,True):
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture','GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40}):
                root=Path(d);state=self.state(d)
                before=(state/'ledger.json').read_bytes();calls=[]
                def post(*a,**k):
                    calls.append(1)
                    if interrupted:raise TimeoutError('fixture crash')
                    return Response({'input_tokens':123})
                item={'id':'fixture','body':sizing.count_body('fixture')}
                try:sizing.Counter(state,post).count(item)
                except TimeoutError:pass
                buffer=io.BytesIO()
                with zipfile.ZipFile(buffer,'w') as archive:
                    for p in state.rglob('*.json'):archive.writestr(p.relative_to(state).as_posix(),p.read_bytes())
                for n in range(3):
                    target=root/str(n);e.unpack_state(buffer.getvalue(),target)
                    self.assertEqual((target/'ledger.json').read_bytes(),before)
                    counter=sizing.Counter(target,post)
                    if interrupted:
                        with self.assertRaises(RecoveryRequired):counter.count(item)
                    else:self.assertEqual(counter.count(item),123)
                self.assertEqual(len(calls),1)

    def test_rejects_wrong_model_tools_or_executable_network_configuration(self):
        for field,value in [('model','claude-opus-5'),('tools',[{}]),('endpoint','https://elsewhere.invalid'),('cache_control',{})]:
            body=sizing.count_body('fixture')|{field:value}
            with self.assertRaises(sizing.ConfigurationFailure):sizing.count_projection(body)

    def test_invalid_counter_result_remains_unresolved(self):
        for value in ({'input_tokens':True},{'input_tokens':0},{'input_tokens':200001},{'input_tokens':2,'verdict':'yes'}):
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
                counter=sizing.Counter(self.state(d),lambda *a,**k:Response(value));item={'id':'fixture','body':sizing.count_body('fixture')}
                with self.assertRaises(ValueError):counter.count(item)
                with self.assertRaises(RecoveryRequired):counter.count(item)

    def test_real_process_kill_at_every_counter_commit_boundary(self):
        script=r'''
import os,sys,json
from pathlib import Path
from tools import contextual_team_token_preflight as s
from tools import offline_spend
state=Path(sys.argv[1]);boundary=sys.argv[2];marker=state.parent/'fixture-dispatches'
replace=offline_spend.os.replace;number=0
def abrupt_replace(source,target):
 global number
 if Path(target)!=state/'checkpoint.json':
  if boundary=='during_staging':os._exit(73)
  return replace(source,target)
 number+=1
 if boundary==f'before_replace_{number}':os._exit(73)
 replace(source,target)
 if boundary==f'after_replace_{number}':os._exit(73)
offline_spend.os.replace=abrupt_replace
class Response:
 status_code=200
 def iter_content(self,chunk_size):yield b'{"input_tokens":123}'
 def close(self):pass
def post(*a,**kw):
 marker.write_text(marker.read_text()+'1' if marker.exists() else '1')
 if boundary=='during_http':os._exit(73)
 return Response()
s.Counter(state,post).count({'id':'fixture','body':s.count_body('fixture')})
'''
        for boundary in ('during_staging','before_replace_1','after_replace_1','during_http','before_replace_2','after_replace_2'):
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as d:
                root=Path(d);state=self.state(d);ledger=(state/'ledger.json').read_bytes()
                result=subprocess.run([sys.executable,'-c',script,str(state),boundary],capture_output=True)
                self.assertEqual(result.returncode,73,result.stderr)
                raw=self.archive(state);marker=root/'fixture-dispatches'
                before=len(marker.read_text()) if marker.exists() else 0
                resumed=[]
                def post(*a,**k):resumed.append(1);return Response({'input_tokens':123})
                item={'id':'fixture','body':sizing.count_body('fixture')}
                for n in range(3):
                    target=root/str(n);sizing.existing.unpack_state(raw,target)
                    self.assertEqual((target/'ledger.json').read_bytes(),ledger)
                    if boundary in ('during_staging','before_replace_1','after_replace_2'):
                        self.assertEqual(sizing.Counter(target,post).count(item),123)
                    else:
                        with self.assertRaises(RecoveryRequired):sizing.Counter(target,post).count(item)
                    # The normal prepare/finalize checkpoint must retain the rows.
                    sizing.existing.checkpoint(target);raw=self.archive(target)
                self.assertLessEqual(before+len(resumed),1)
                self.assertEqual(len(resumed),1 if boundary in ('during_staging','before_replace_1') else 0)

    def test_concurrent_callers_share_one_exact_measurement(self):
        with tempfile.TemporaryDirectory() as d:
            state=self.state(d);calls=[]
            def post(*a,**k):calls.append(1);return Response({'input_tokens':123})
            item={'id':'fixture','body':sizing.count_body('fixture')}
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:sizing.Counter(state,post).count(item),range(2)))
            self.assertEqual(results,[123,123]);self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
