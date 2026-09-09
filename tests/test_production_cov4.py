"""Zero-network qualification of the active extraction/publication contract."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import subtopic_cov4 as gate, subtopic_segmentation as seg, subtopic_records as records
from tests.test_sonnet_structured_transport import sonnet_response
from tools import evaluate_offline_ai as evaluation, run_budgeted_documents as documents
from tools.offline_ai import Client, Ledger, atomic_json, identity


class ProductionCov4(unittest.TestCase):
    def test_document_entrypoint_preserves_provenance_and_publication_requirements(self):
        from scripts import extract_document_evidence as extraction
        from tests.fixtures.minipdf import build_pdf, containers_from, heading, line
        from tests.test_subtopic_segmentation import topic_pages
        titles = ['Topic Area 1 Catalysis Science', 'Topic Area 2 Materials Discovery', 'Topic Area 3 Membrane Separations']
        pages = topic_pages(titles)
        content = build_pdf(pages, outline=[(title, index + 1, 0) for index, title in enumerate(titles)])
        parent = {'opportunity_id': 'synthetic-context', 'opportunity_number': 'SYN-001',
                  'title': 'Synthetic research notice', 'status': 'posted'}
        document = {'url': 'https://example.gov/notice.pdf', 'sha256': 'synthetic-source-hash',
                    'source_kind': 'primary_notice', 'content_type': 'application/pdf', 'name': 'notice.pdf'}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), \
                patch('requests.post', return_value=sonnet_response({'owned': 'yes', 'fundable': 'yes',
                    'reason': 'Synthetic source-declared research subject.'})) as post:
            root = Path(tmp)
            ledger = Ledger(root / 'ledger.json', 'synthetic', 2)
            classify = documents.instrument(ledger, root / 'cache', gate.classify_fundability)
            with patch.object(gate, 'classify_fundability', classify):
                fields = extraction.subtopic_fields(parent, content, containers_from(pages), document, '2026-09-09', True)
                self.assertEqual(fields['subtopic_cov4']['classifier_calls'], 3)
                self.assertEqual(len(fields['subtopics']), 3)
                self.assertNotIn('classifier_context', json.dumps(fields))
                for row in fields['subtopics']:
                    self.assertEqual(row['subtopic_source'], 'inferred')
                    self.assertEqual(row['confidence'], 'medium')
                    # Cov4 and source-confidence approval remain separate; an
                    # active verdict cannot silently promote inferred to native.
                    self.assertEqual(records.publication_eligibility(row)[0], records.REVIEW)
                    approval = {row['subtopic_id']: {'status': 'approve', 'document_sha256': row['source_document_hash']}}
                    self.assertEqual(records.publication_eligibility(row, approvals=approval)[0], records.PUBLISHABLE)
                    self.assertEqual(records.publication_eligibility(row | {'cov4_fundability': 'unresolved'}, approvals=approval)[0], records.REVIEW)
                replay = extraction.subtopic_fields(parent, content, containers_from(pages), document, '2026-09-09', True)
                self.assertEqual(replay['subtopics'], fields['subtopics'])
                self.assertEqual(replay['subtopic_cov4']['api_requests'], 0)
                self.assertEqual(post.call_count, 3)

    def test_enclosing_container_does_not_borrow_child_science(self):
        text = ('Office of Basic Energy Sciences\nThis office administers several programs.\n'
                'Catalysis Science\nResearch supported by the Office of Basic Energy Sciences '
                'studies catalytic reaction mechanisms.\nMaterials Science\nMaterials research.')
        containers = [{'page': 1, 'text': text}, {'page': 2, 'text': 'Other notice section.'},
                      {'page': 3, 'text': 'Appendix material.'}]
        flat = seg._flatten(containers)
        office = seg.OutlineNode(0, 'Office of Basic Energy Sciences', 1)
        catalysis = seg.OutlineNode(1, 'Catalysis Science', 1, (office.title,))
        materials = seg.OutlineNode(1, 'Materials Science', 1, (office.title,))
        nodes = [office, catalysis, materials]
        def candidate(node, ordinal):
            return seg._outline_context(seg._Candidate(str(ordinal), ordinal, 'numeric',
                node.title, text.index(node.title), 1, None), nodes, flat)
        # This is the demonstrated parent-container path, with its own children
        # omitted from selected siblings just as the organizational trap arose.
        parent_span = seg.build_subtopics([candidate(office, 1)], flat, containers)[0]
        self.assertEqual(parent_span.classifier_context['child_headings'], ['Catalysis Science', 'Materials Science'])
        self.assertEqual(parent_span.classifier_context['local_text'], text[:text.index('Catalysis Science')])
        self.assertNotIn('reaction mechanisms', parent_span.classifier_context['local_text'])
        subject_span = seg.build_subtopics([candidate(catalysis, 1), candidate(materials, 2)], flat, containers)[0]
        self.assertEqual(subject_span.classifier_context['enclosing_headings'], [office.title])
        self.assertIn('Office of Basic Energy Sciences', subject_span.classifier_context['local_text'])
        self.assertNotIn('Materials research', subject_span.classifier_context['local_text'])
        parent = {'opportunity_id': 'synthetic', 'opportunity_number': 'SYN-001', 'title': 'Synthetic notice', 'status': 'posted'}
        document = {'source_kind': 'primary_notice', 'url': 'https://example.gov/notice', 'sha256': 'synthetic'}
        built = records.build_records(parent, seg.SegmentationResult(subtopics=(parent_span, subject_span),
            method='outline', confidence='high', family='topic_area'), document=document, as_of='2026-09-09')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), \
                patch('requests.post', side_effect=[sonnet_response({'owned': 'yes', 'fundable': 'no', 'reason': 'Organizational mission container.'}),
                    sonnet_response({'owned': 'yes', 'fundable': 'yes', 'reason': 'A source-declared catalytic research subject.'})]) as post:
            root = Path(tmp)
            ledger = Ledger(root / 'ledger.json', 'synthetic', 2)
            classify = documents.instrument(ledger, root / 'cache', gate.classify_fundability)
            kept, diagnostics = gate.apply_gate(parent, built, document, classifier=classify)
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]['title'], 'Catalysis Science')
            self.assertEqual(kept[0]['subtopic_source'], 'inferred')
            self.assertEqual(kept[0]['cov4_prompt_version'], gate.ACTIVE_PROMPT_VERSION)
            self.assertNotIn('classifier_context', json.dumps(kept))
            # Even an accidentally ungated transient record cannot leak its
            # longer local body into public/review storage.
            transient = copy.deepcopy(built[0])
            transient['classifier_context']['local_text'] = 'PRIVATE_CONTEXT_SENTINEL'
            sidecar = records.sidecar_payload({'records': {'synthetic': {'subtopics': [transient]}}})
            self.assertNotIn('PRIVATE_CONTEXT_SENTINEL', json.dumps(sidecar))
            self.assertNotIn('classifier_context', json.dumps(sidecar))
            self.assertEqual(diagnostics['api_requests'], 2)
            self.assertEqual(diagnostics['dropped'], 1)
            self.assertTrue(all(call.kwargs['json']['output_config']['format']['type'] == 'json_schema' for call in post.call_args_list))
            prior = copy.deepcopy(ledger.read()['requests'])
            again, warm = gate.apply_gate(parent, built, document, classifier=classify)
            self.assertEqual(again, kept)
            self.assertEqual(warm['api_requests'], 0)
            self.assertEqual(ledger.read()['requests'], prior)
            self.assertEqual(post.call_count, 2)

    def test_missing_bounded_client_and_malformed_context_fail_closed(self):
        self.assertEqual(gate.classify_fundability({})['fundability'], gate.UNRESOLVED)
        with tempfile.TemporaryDirectory() as tmp, patch('requests.post', side_effect=AssertionError('No dispatch')):
            root = Path(tmp)
            client = Client(Ledger(root / 'ledger.json', 'synthetic', 2), root / 'cache')
            verdict = gate.classify_fundability({'classifier_context': ['invalid']}, offline_client=client)
            self.assertEqual(verdict['fundability'], gate.UNRESOLVED)
            self.assertFalse(verdict['api_request'])
            self.assertEqual(client.ledger.read()['requests'], [])

    def test_full_gate_and_zero_call_replay_preserve_exact_results(self):
        protocol, candidates = evaluation.production_cov4_cases('population')
        from tools import run_cov4_validation as harness
        expected = {}
        for candidate, parent, document, built in harness.generic_records(candidates):
            data = gate.active_contract(gate.candidate_from_record(parent, built[0], document))['inputs']
            expected[identity(data)] = {'owned': candidate['owned'],
                'fundable': 'yes' if candidate['fundable'] == 'yes' else 'no', 'reason': 'Synthetic response for wiring verification only.'}
        def response(*args, **kwargs):
            data = json.loads(kwargs['json']['messages'][0]['content'])
            return sonnet_response(expected[identity(data)])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), \
                patch('requests.Session.post', side_effect=response) as post, \
                patch('requests.post', side_effect=AssertionError('No unbounded transport')):
            root = Path(tmp)
            ledger = Ledger(root / 'ledger.json', 'synthetic', 2, 200)
            atomic_json(root / 'production-preflight-receipt.json', {
                'complete': True, 'contract': identity(evaluation.production_preflight_configuration())})
            with patch.object(evaluation, 'evaluation_ledger', return_value=ledger):
                first = evaluation.production_cov4(root, 'population')
                self.assertTrue(first['execution_complete'])
                self.assertTrue(first['numerical_gate_passed'])
                self.assertFalse(first['quality_gate_passed'])
                self.assertEqual(first['new_provider_requests'], 43)
                prior = ledger.read()
                second = evaluation.production_cov4(root, 'population', replay=True)
                self.assertEqual(second['new_provider_requests'], 0)
                self.assertEqual(second['result_hash'], first['result_hash'])
                self.assertEqual(ledger.read(), prior)
                self.assertEqual(post.call_count, 43)
                self.assertEqual(identity(evaluation.production_cov4(root, 'population')), identity(first))
                with patch.object(gate, 'ACTIVE_PROMPT', gate.ACTIVE_PROMPT + '\nChanged scientific rule.'):
                    with self.assertRaisesRegex(ValueError, 'contract changed'):
                        evaluation.production_cov4(root, 'population')
                self.assertEqual(post.call_count, 43)


if __name__ == '__main__':
    unittest.main()
