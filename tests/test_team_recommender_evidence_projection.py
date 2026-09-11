import copy
import hashlib
import json
import unittest
from pathlib import Path
from tools.team_recommender_evidence_projection import person_document, project_item, request_body, pack, remap_winner, encoded


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.registry = {p['id']:p for p in json.loads(Path('docs/team-recommender/prepared/d1/directory.json').read_bytes())['researchers']}
        self.ids = list(self.registry)[:3]
        self.source = {'scope_id':'local-fixture', 'limitations':'retained', 'passages':[{'id':'s1','text':'Scientific purpose. Do not omit the condition.', 'sha256':hashlib.sha256(b'Scientific purpose. Do not omit the condition.').hexdigest()}]}
        self.aspects = [{'id':'a0','text':'Scientific purpose','source_ref':'s1'}]
    def item(self, ids=None, kind='call_person'):
        return project_item({'task_type':kind,'candidates':ids or [self.ids[0]],'score':99,'arm':'E2','prior_verdict':'strong'},self.registry)
    def test_all_155_profiles_complete_and_retired_excluded(self):
        people=[p for p in self.registry.values() if p['status']=='active' and p['auto_proposable'] and p['pool_state'] in {'main','standby'}]
        self.assertEqual(len(people),155)
        for p in people:
            d=person_document(p);self.assertEqual(d['research_summary'],p['research_summary'])
            self.assertEqual({s['text'] for s in d['statements']},{c['evidence'] for c in p['claims'] if c['status']=='active'})
            self.assertEqual({c['claim_id'] for s in d['statements'] for c in s['claims']},{c['claim_id'] for c in p['claims'] if c['status']=='active'})
    def test_compare_union_and_blinding(self):
        item=self.item({'A':self.ids[:2],'B':self.ids[1:]},'comparison')
        self.assertEqual([p['person_id'] for p in item['profile_documents']],sorted(self.ids))
        self.assertFalse({'score','arm','prior_verdict'} & item.keys())
        swapped=self.item({'B':self.ids[:2],'A':self.ids[1:]},'comparison')
        self.assertEqual(item['profile_documents'],swapped['profile_documents'])
    def test_same_documents_once_per_packet(self):
        item=self.item();body=request_body(self.source,self.aspects,[item,item],'fixed rubric')
        data=json.loads(body['messages'][0]['content']);self.assertEqual(len(data['profile_documents']),1)
        self.assertEqual(len(data['items']),2)
        doc=data['profile_documents'][0];self.assertEqual(doc['research_summary'],self.registry[self.ids[0]]['research_summary'])
        self.assertEqual([s['text'] for s in doc['statements']],[s['text'] for s in item['profile_documents'][0]['statements']])
    def test_source_condition_and_hash(self):
        body=request_body(self.source,self.aspects,[self.item()],'fixed rubric');self.assertIn('Do not omit the condition.',body['messages'][0]['content'])
        bad=copy.deepcopy(self.source);bad['passages'][0]['text']='Changed'
        with self.assertRaisesRegex(ValueError,'source_hash'):request_body(bad,self.aspects,[self.item()],'fixed rubric')
    def test_sibling_aspect_rejected(self):
        with self.assertRaisesRegex(ValueError,'aspect_source'):request_body(self.source,[{'id':'a0','text':'Sibling purpose','source_ref':'s1'}],[self.item()],'fixed rubric')
    def test_split_no_crop_and_oversize_is_unresolved(self):
        item=self.item();item['profile_documents'][0]['research_summary']='Complete scientific statement. '*1000
        batches,over=pack(self.source,self.aspects,[('large',item),('small',self.item())],'fixed rubric')
        self.assertEqual(over[0]['key'],'large');self.assertEqual(batches[0]['keys'],['small']);self.assertEqual(item['profile_documents'][0]['research_summary'].count('Complete scientific statement.'),1000)
        batches,over=pack(self.source,self.aspects,[(str(i),self.item()) for i in range(7)],'fixed rubric')
        self.assertEqual([len(p['keys']) for p in batches],[3,3,1]);self.assertTrue(all(len(encoded(p['body']))+1024<=12000 for p in batches))
    def test_remapping_ties_and_unresolved(self):
        self.assertEqual([remap_winner(v,True) for v in ['A','B','tie','unresolved']],['B','A','tie','unresolved'])
    def test_mixed_person_document_rejected(self):
        a=self.item();b=copy.deepcopy(a);b['profile_documents'][0]['research_summary']='Other snapshot'
        with self.assertRaisesRegex(ValueError,'inconsistent_person'):request_body(self.source,self.aspects,[a,b],'fixed rubric')
    def test_duplicate_evidence_keeps_distinct_labels_and_revision(self):
        p=copy.deepcopy(self.registry[self.ids[0]])
        c=copy.deepcopy(p['claims'][0]);c['claim_id']='fixture-distinct-claim';c['label']='Existing distinct label';c['type']='Method';c['revision']=2;p['claims'].append(c)
        d=person_document(p);same=[s for s in d['statements'] if s['text']==c['evidence']]
        self.assertEqual(len(same),1);self.assertIn({'claim_id':c['claim_id'],'label':c['label'],'claim_type':c['type'],'revision':2,'evidence_level':c['evidence_level'],'source_urls':sorted(c['source_urls'])},same[0]['claims'])
    def test_explanation_separate_and_duplicates_rejected(self):
        with self.assertRaisesRegex(ValueError,'persuasive'):project_item({'task_type':'call_person','candidates':[self.ids[0]],'explanation':'persuasive'},self.registry)
        with self.assertRaisesRegex(ValueError,'duplicate_candidate'):self.item([self.ids[0]]*2,'group_usefulness')


if __name__=='__main__':unittest.main()
