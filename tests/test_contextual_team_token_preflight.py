import copy
import json
import os
from pathlib import Path
import tempfile
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
    def test_inventory_is_fixed_public_data_and_no_inference(self):
        items=sizing.inventory()
        self.assertEqual(len(items),164)
        self.assertEqual(len([x for x in items if x['id'].startswith('profile:')]),155)
        self.assertTrue(all(x['body']['model']=='claude-sonnet-5' for x in items))
        self.assertTrue(all('max_tokens' not in x['body'] for x in items))
        self.assertEqual(sizing.identity(items),sizing.identity(sizing.inventory()))

    def test_complete_count_cached_without_ledger_or_message_dispatch(self):
        calls=[]
        def post(url,**kw):calls.append((url,kw));return Response({'input_tokens':456})
        item={'id':'fixture','body':sizing.count_body('Fixture only, not scientific evidence.')}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
            counter=sizing.Counter(d,post)
            self.assertEqual(counter.count(item),456)
            for _ in range(3):self.assertEqual(sizing.Counter(d,post).count(copy.deepcopy(item)),456)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],sizing.ENDPOINT)
            self.assertFalse(calls[0][1]['allow_redirects'])
            self.assertFalse((Path(d)/'ledger.json').exists())

    def test_unknown_counter_outcome_not_automatically_repeated(self):
        calls=[]
        def post(*a,**k):calls.append(1);raise TimeoutError('fixture')
        item={'id':'fixture','body':sizing.count_body('fixture')}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
            with self.assertRaises(TimeoutError):sizing.Counter(d,post).count(item)
            for _ in range(3):
                with self.assertRaises(RecoveryRequired):sizing.Counter(d,post).count(item)
            self.assertEqual(len(calls),1)

    def test_rejects_wrong_model_tools_or_executable_network_configuration(self):
        for field,value in [('model','claude-opus-5'),('tools',[{}]),('endpoint','https://elsewhere.invalid'),('cache_control',{})]:
            body=sizing.count_body('fixture')|{field:value}
            with self.assertRaises(sizing.ConfigurationFailure):sizing.count_projection(body)

    def test_invalid_counter_result_remains_unresolved(self):
        for value in ({'input_tokens':True},{'input_tokens':0},{'input_tokens':200001},{'input_tokens':2,'verdict':'yes'}):
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture'}):
                counter=sizing.Counter(d,lambda *a,**k:Response(value));item={'id':'fixture','body':sizing.count_body('fixture')}
                with self.assertRaises(ValueError):counter.count(item)
                with self.assertRaises(RecoveryRequired):counter.count(item)


if __name__=='__main__':unittest.main()
