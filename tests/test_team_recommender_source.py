import copy
import unittest
from tools.team_recommender_source import digest, validate_source

class OriginalSourceContract(unittest.TestCase):
    def setUp(self):
        self.raw=b'Original optical spectroscopy source.'
        self.text=self.raw.decode()
        self.scope={'id':'parent:child','parent_id':'parent','approach_id':'one'}
        self.source={'document_sha256':digest(self.raw),'source_url':'https://example.org/call',
            'excerpts':[{'offset':9,'text':'optical spectroscopy','sha256':digest('optical spectroscopy')}],
            'receipt':{'checked_at':'2026-09-01T00:00:00Z','approach_id':'one'}}
        self.receipt={'scope_id':'parent:child','parent_id':'parent','document_sha256':digest(self.raw),
            'text_sha256':digest(self.text),'method':'retained-document-extraction','extraction_code_sha256':'a'*64,
            'source_url':self.source['source_url'],'retrieved_at':'2026-09-01T00:00:00Z','coherent_scope':True,'conditions_preserved':True}
    def run_check(self):
        return validate_source(self.source,self.scope,original_bytes=self.raw,extracted_text=self.text,extraction_receipt=self.receipt)
    def test_reuses_valid_receipt_without_new_retrieval(self):
        self.assertEqual(self.run_check()['new_retrieval'],False)
    def test_changed_document_or_sibling_is_rejected(self):
        self.receipt['scope_id']='parent:sibling'
        with self.assertRaisesRegex(ValueError,'ownership'): self.run_check()
    def test_plausible_quote_is_not_original_span(self):
        self.source['excerpts'][0]['offset']=0
        with self.assertRaisesRegex(ValueError,'span_mismatch'): self.run_check()
    def test_model_approval_and_missing_conditions_not_source_receipt(self):
        self.receipt['method']='cached-model-approval'
        with self.assertRaisesRegex(ValueError,'not_source_validation'): self.run_check()
        self.receipt['method']='native-source-structure';self.receipt['conditions_preserved']=False
        with self.assertRaisesRegex(ValueError,'not_validated'): self.run_check()
    def test_old_retrieval_keeps_original_date(self):
        self.source['receipt']['checked_at']='2026-09-09T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'misrepresented'): self.run_check()
