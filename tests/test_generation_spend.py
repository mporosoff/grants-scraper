"""Generation-accounting boundaries and unchanged Cov4 semantics, offline."""
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import generation_spend_checkpoint as checkpoint
from tools.offline_ai import Ledger, error_diagnostics, request_body
from tools.run_budgeted_documents import instrument
from tools import run_budgeted_documents as wrapper
from scripts import subtopic_cov4 as gate


class GenerationSpend(unittest.TestCase):
    def test_document_entrypoint_registers_its_own_module_for_schedule_callbacks(self):
        # The production merge_document_entry callback passes sys.modules[__name__]
        # to notice_schedule, which requires the extractor's DATE_RE attribute.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'document_entry_fixture.py').write_text(
                'import re, sys\nDATE_RE = re.compile("date")\n'
                'assert sys.modules[__name__].DATE_RE.pattern == "date"\n', encoding='utf-8')
            original = wrapper.runpy.run_module
            def invoke(name, **kwargs):
                self.assertEqual(name, 'scripts.extract_document_evidence')
                return original('document_entry_fixture', **kwargs)
            with patch.object(sys, 'path', [str(root), *sys.path]), \
                    patch.dict('os.environ', {'OFFLINE_AI_STATE': str(root / 'state'), 'TEAM_MODE': 'pilot'}), \
                    patch.object(wrapper.runpy, 'run_module', side_effect=invoke), patch.object(gate, 'classify_fundability'):
                wrapper.main()
            self.assertTrue((root / 'state/usage-summary.json').exists())

    def test_confirmed_provider_pause_survives_into_replacement_without_requests(self):
        meta = {'path': '.github/workflows/refresh-opportunities.yml', 'head_branch': 'main'}
        def api(repo, path):
            return json.dumps({'artifacts': []} if 'artifacts?' in path else meta).encode()
        settings = checkpoint.config() | {'generation_provider_pauses': {'anthropic': {'reason': 'insufficient_credit'}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(checkpoint, 'api', side_effect=api), \
                patch.object(checkpoint, 'config', return_value=settings):
            root = Path(directory)
            checkpoint.prepare('owner/repo', '124', '1', root / 'offline-124', root / 'reservation.json', 'pilot')
            ledger = Ledger(root / 'offline-124/ledger.json', 'offline-124', 2)
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], 'insufficient_credit')
            with self.assertRaisesRegex(RuntimeError, 'insufficient_credit'):
                ledger.reserve('anthropic', gate.MODEL, 'decomposition', 'new', 1, 1)
            self.assertEqual(ledger.read()['requests'], [])

    def test_resumed_logical_generation_keeps_reserved_unknown_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / 'old' / 'ledger.json', 'offline-123', 2)
            ledger.reserve('anthropic', gate.MODEL, 'verification', 'key', 1900000, 1)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.write(ledger.path, 'ledger.json')
                archive.writestr('team-responses/completed.json', '{"safe":"derived response"}')
            meta = {'path': '.github/workflows/refresh-opportunities.yml', 'head_branch': 'main'}
            artifacts = {'artifacts': [{'id': 1, 'name': 'generation-spend-reservation-123-1', 'expired': False},
                {'id': 2, 'name': 'generation-spend-state-123-1', 'expired': False}]}
            def api(repo, path):
                if path.endswith('/zip'): return stream.getvalue()
                return json.dumps(artifacts if 'artifacts?' in path else meta).encode()
            with patch.object(checkpoint, 'api', side_effect=api):
                checkpoint.prepare('owner/repo', '123', '2', root / 'offline-123', root / 'reservation.json', 'pilot')
            restored = Ledger(root / 'offline-123/ledger.json', 'offline-123', 2)
            self.assertEqual(restored.summary()['charged_usd'], 1.9)
            self.assertTrue((root / 'offline-123/team-responses/completed.json').exists())
            with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
                restored.reserve('openai', 'gpt-5.6-luna', 'verification', 'other', 200000, 1)
            artifacts['artifacts'].pop()
            with patch.object(checkpoint, 'api', side_effect=api), self.assertRaisesRegex(ValueError, 'remaining allowance unavailable'):
                checkpoint.prepare('owner/repo', '123', '3', root / 'missing', root / 'reservation2.json', 'pilot')

    def test_cov4_wraps_the_same_prompt_and_reuses_only_valid_complete_decisions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', ANTHROPIC_API_KEY='synthetic'):
            root = Path(directory)
            ledger = Ledger(root / 'ledger.json', 'fixture', 2)
            payload = {'model': gate.MODEL, 'stop_reason': 'end_turn', 'usage': {'input_tokens': 100, 'output_tokens': 12},
                       'content': [{'type': 'text', 'text': '{"owned":"yes","fundable":"yes","reason":"Bounded scientific research"}'}]}
            session = Mock(post=Mock(return_value=Mock(status_code=200, json=lambda: payload)))
            candidate = {'parent_title': 'Actual bounded fixture', 'title': 'Catalytic science', 'excerpt': 'Research scope'}
            classify = instrument(ledger, root / 'cache', gate.classify_fundability)
            first = classify(candidate, api_key='synthetic', session=session)
            second = classify(candidate, api_key='synthetic', session=session)
            self.assertEqual((first['fundability'], second['fundability']), (gate.ACCEPT, gate.ACCEPT))
            self.assertEqual(session.post.call_count, 1)
            body = session.post.call_args.kwargs['json']
            active = gate.active_contract(candidate)
            self.assertEqual(body, request_body(active['route'], active['stage'], active['prompt'], active['inputs'], active['schema']))
            self.assertIn('output_config', body)
            self.assertFalse(second['api_request'])
            self.assertEqual(ledger.read()['requests'][0]['usage']['input_tokens'], 100)

    def test_cov4_configuration_and_safety_refusals_do_not_repeat_requests(self):
        for status, payload in [(400, {'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low'}}),
                                (200, {'model': gate.MODEL, 'stop_reason': 'refusal', 'content': [], 'usage': {'input_tokens': 10, 'output_tokens': 2}})]:
            with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', ANTHROPIC_API_KEY='synthetic'):
                root = Path(directory); ledger = Ledger(root / 'ledger.json', 'fixture', 2)
                session = Mock(post=Mock(return_value=Mock(status_code=status, json=lambda: payload)))
                classify = instrument(ledger, root / 'cache', gate.classify_fundability)
                for _ in range(2):
                    result = classify({'title': 'Scope'}, api_key='synthetic', session=session)
                    self.assertEqual(result['fundability'], gate.UNRESOLVED)
                self.assertEqual(session.post.call_count, 1)
                if status == 400:
                    row = ledger.read()['requests'][0]
                    self.assertEqual(row['diagnostics']['category'], 'insufficient_credit')
                    self.assertIsNone(ledger.summary()['by_provider_model_stage'][f'anthropic/{gate.MODEL}/cov4']['input_tokens'])
                    self.assertGreater(row['charged_microusd'], 0)

    def test_diagnostics_never_retain_provider_message_or_credentials(self):
        value = error_diagnostics(Mock(status_code=400, json=lambda: {'error': {
            'type': 'invalid_request_error', 'message': 'invalid model secret-key private prompt'}}))
        self.assertEqual(value['category'], 'model_unavailable')
        self.assertNotIn('secret-key', json.dumps(value))
        self.assertNotIn('private prompt', json.dumps(value))

    def test_provider_returned_model_must_match_the_declared_alias_or_snapshot(self):
        from tools.offline_ai import compatible_model
        self.assertTrue(compatible_model('gpt-5.6-luna', 'gpt-5.6-luna'))
        self.assertTrue(compatible_model('gpt-5.6-luna', 'gpt-5.6-luna-2026-09-08'))
        self.assertFalse(compatible_model('gpt-5.6-luna', 'gpt-5.4-mini'))
        self.assertFalse(compatible_model('gpt-5.6-luna', None))


if __name__ == '__main__':
    unittest.main()
