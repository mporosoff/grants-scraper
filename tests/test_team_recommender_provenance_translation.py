import copy
import json
import unittest
from tools.team_recommender_source import translate_official_export,digest

class RetainedOfficialProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.r={'opportunity_id':'340828','opportunity_number':'22-600','agency_code':'NSF','source':'Grants.gov','title':'Mathematical biology','description':'Fundamental mathematics for biological questions.','funding_opportunity_url':'https://www.nsf.gov/publications/pub_summ.jsp?ods_key=nsf22600'}
        self.data={'generated_at':'2026-09-09T13:58:17Z','source':{'extract_file':'GrantsDBExtract20260909v2.zip'},'opportunities':[self.r]}
        self.raw=json.dumps(self.data).encode()
        self.args={'artifact_bytes':self.raw,'record':self.r,'scope_id':'340828','parent_id':'340828','excerpts':[{'locator':'description','text':self.r['description'],'offset':0,'sha256':digest(self.r['description'])}], 'snapshot_at':self.data['generated_at'],'source_url':'https://www.grants.gov/search-results-detail/340828','export_identity':self.data['source']['extract_file']}
    def test_preserves_observation_without_invented_retrieval_or_document_hash(self):
        r=translate_official_export(**self.args)
        self.assertIsNone(r['retrieved_at']);self.assertFalse(r['new_retrieval'])
        self.assertEqual(r['observed_at'],self.data['generated_at'])
        self.assertEqual(r['document_sha256'],digest(self.raw))
        self.assertIn('not a newly retrieved notice',r['limitations'])
    def test_exact_nsf_solicitation_alias_and_no_sibling_or_url_aliases(self):
        sid='nsf-funding:https://www.nsf.gov/funding/opportunities/mathematical-biology/nsf22-600'
        self.assertEqual(translate_official_export(**{**self.args,'scope_id':sid,'parent_id':sid})['scope_id'],sid)
        for bad in [sid+'?alias=1',sid.replace('www.nsf.gov','evil.example'),sid.replace('22-600','22-601'),'340828:child']:
            with self.assertRaises(ValueError):translate_official_export(**{**self.args,'scope_id':bad,'parent_id':bad})
    def test_rejects_changed_text_record_time_or_fabricated_source(self):
        variants=[{'snapshot_at':'2026-09-10T00:00:00Z'},{'source_url':'https://example.org/source'},{'record':{**self.r,'description':'Fabricated'}},{'record':{**self.r,'description_source':'AI synopsis'}}]
        e=copy.deepcopy(self.args['excerpts']);e[0]['text']='Fabricated';e[0]['sha256']=digest('Fabricated');variants.append({'excerpts':e})
        for delta in variants:
            with self.assertRaises(ValueError):translate_official_export(**{**self.args,**delta})

if __name__=='__main__':unittest.main()
