"""Retained source-topic correction preserves scientific evidence and accounting."""
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_catalog
from scripts.build_changes import _snapshot, render_change_feed
from tests.test_build_changes import rec
from tools import topic_area_revalidation as replay, program_area_revalidation as common


SOURCE = '2026-11-23T18:04:37.711431Z'
EVIDENCE = '2026-11-23T18:07:22.662506Z'
AUDIT = '2026-11-23T19:00:00Z'


def original_rules():
    values = dict(build_catalog.COMPILED_TOPIC_RULES)
    values['Infectious disease'] = re.compile(r'\binfectious\b', re.I)
    values['Public health'] = re.compile(r'\bpublic health\b', re.I)
    return values


class TopicProjection(unittest.TestCase):
    def catalog(self, receipt=False):
        row = rec('361815', title='HIV/AIDS Clinical Trials Network Leadership and Operations Centers',
            description='Cancer research with HIV clinical trials.', topic_areas=['Adapter-owned topic'],
            funding_categories=[], close_date='2026-12-30')
        if receipt:
            row['document_evidence'] = {'facts': [{'id': 'retained-fact', 'value': 'unchanged'}],
                'checked_at': EVIDENCE, 'source_fields': {'topic_areas': {
                    'present': True, 'value': ['Adapter-owned topic']},
                    'limited_submission': {'present': True, 'value': False}}}
        return {'schema_version': 3, 'generated_at': SOURCE, 'document_evidence_generated_at': EVIDENCE,
            'record_count': 1, 'opportunities': [row], 'search_index': build_catalog.build_search_index([row])}

    def test_only_new_classifier_labels_join_existing_adapter_topics(self):
        before = self.catalog()
        after, changed, receipts = replay.project_catalog(before, original_rules())
        self.assertEqual(changed, ['361815'])
        self.assertEqual(receipts, [])
        self.assertEqual(after['opportunities'][0]['topic_areas'],
            ['Adapter-owned topic', 'Infectious disease', 'Public health'])
        # Cancer was already recognized by the old source rules. A retained
        # adapter's deliberate classification is not broadened by replay.
        self.assertNotIn('Cancer', after['opportunities'][0]['topic_areas'])
        self.assertEqual(after['generated_at'], SOURCE)
        self.assertEqual(after['document_evidence_generated_at'], EVIDENCE)
        old, new = before['opportunities'][0], after['opportunities'][0]
        self.assertEqual({k: v for k, v in old.items() if k != 'topic_areas'},
                         {k: v for k, v in new.items() if k != 'topic_areas'})

    def test_bound_source_topic_receipt_changes_only_its_topic_value(self):
        before = self.catalog(receipt=True)
        after, changed, receipts = replay.project_catalog(before, original_rules())
        self.assertEqual(receipts, changed)
        old, new = before['opportunities'][0], after['opportunities'][0]
        expected = deepcopy(old)
        expected['topic_areas'] += ['Infectious disease', 'Public health']
        expected['document_evidence']['source_fields']['topic_areas']['value'] = expected['topic_areas']
        self.assertEqual(new, expected)
        for field, value in [('title', 'changed source'), ('description', 'changed scientific text')]:
            corrupted = deepcopy(new); corrupted[field] = value
            with self.assertRaisesRegex(ValueError, 'only_additive_topics'):
                replay.record_firewall(old, corrupted, ['Infectious disease', 'Public health'])
        corrupted = deepcopy(new)
        corrupted['document_evidence']['facts'][0]['value'] = 'changed evidence'
        with self.assertRaisesRegex(ValueError, 'only_additive_topics'):
            replay.record_firewall(old, corrupted, ['Infectious disease', 'Public health'])

    def test_unbound_receipt_or_classifier_removal_stops_projection(self):
        before = self.catalog(receipt=True)
        before['opportunities'][0]['document_evidence']['source_fields']['topic_areas']['value'] = ['other']
        with self.assertRaisesRegex(ValueError, 'bound_original_source_topics'):
            replay.project_catalog(before, original_rules())
        rules = original_rules() | {'Removed label': re.compile('HIV')}
        with self.assertRaisesRegex(ValueError, 'classifier_removes_original_topic'):
            replay.project_catalog(self.catalog(), rules)

    def test_serialized_catalog_firewall_rejects_changed_source_text(self):
        before = self.catalog(receipt=True)
        after, _, _ = replay.project_catalog(before, original_rules())
        raw = build_catalog.catalog_javascript_bytes(after)
        replay.verify_serialized_catalog(before, raw, original_rules())
        changed = raw.replace(b'Cancer research with HIV clinical trials.', b'Altered official source description.')
        with self.assertRaisesRegex(ValueError, 'only_additive_topics'):
            replay.verify_serialized_catalog(before, changed, original_rules())

    def test_original_rules_are_literal_protected_inputs_without_module_execution(self):
        source = "TOPIC_RULES = {'Original': r'\\bword\\b'}\nraise AssertionError('must not execute')\n"
        with patch.object(common.candidate, 'git', side_effect=['', source]) as git:
            rules = replay.prior_rules('a' * 40)
        self.assertTrue(rules['Original'].search('word'))
        self.assertEqual(git.call_args.args[-1], 'a' * 40 + ':scripts/build_catalog.py')
        with patch.object(common.candidate, 'git', side_effect=['', "TOPIC_RULES = make_rules()"]), \
                self.assertRaisesRegex(ValueError, 'literal_original_topic_rules'):
            replay.prior_rules('a' * 40)

    def test_current_snapshots_and_topic_feeds_refresh_but_history_and_cache_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = self.catalog()
            build_catalog.write_catalog(before, root / 'data/opportunities.js')
            cache = b'{"schema_version":1,"records":{}}\n'
            (root / 'data/document_evidence.json').write_bytes(cache)
            event = {'id': 'current', 'type': 'new', 'label': 'New opportunity', 'changed_at': SOURCE,
                'opportunity_id': '361815', 'detail': 'Retained detail', 'record': _snapshot(before['opportunities'][0])}
            historical = deepcopy(event); historical.update(id='historical', changed_at='2026-11-22T18:00:00Z')
            closed = deepcopy(event); closed.update(id='closed', type='closed_or_removed')
            feed = {'schema_version': 1, 'generated_at': SOURCE, 'retention_days': 90,
                'events': [event, historical, closed]}
            (root / 'feeds').mkdir()
            for name, raw in render_change_feed(feed).items():
                (root / 'feeds' / name).write_bytes(raw)
            saved = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(common.candidate, 'load', return_value={'generation_sha': 'a' * 40}), \
                    patch.object(replay, 'prior_rules', return_value=original_rules()), \
                    patch('tools.verify_notice_publication.verify', return_value={'publication_ready': True}), \
                    patch('scripts.subtopic_records.read_cache', return_value={}), \
                    patch('requests.sessions.Session.request', side_effect=AssertionError('No network')):
                outputs, report = replay.projection(root, AUDIT, 'b' * 64)
            after = json.loads(outputs['data/opportunities.js'].decode().split('=', 1)[1].strip().removesuffix(';'))
            updated = json.loads(outputs['feeds/changes.json'])
            self.assertEqual(updated['events'][0]['record']['topic_areas'], after['opportunities'][0]['topic_areas'])
            self.assertEqual(updated['events'][1:], feed['events'][1:])
            self.assertEqual({k: v for k, v in updated['events'][0].items() if k != 'record'},
                             {k: v for k, v in event.items() if k != 'record'})
            self.assertEqual(report['refreshed_change_event_ids'], ['current'])
            self.assertEqual(outputs['data/document_evidence.json'], cache)
            self.assertIn('feeds/topic/infectious-disease.xml', outputs)
            self.assertIn('feeds/topic/public-health.xml', outputs)
            self.assertEqual(saved, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_topic_kind_admits_only_lexical_source_change_and_no_extra_requests(self):
        groups = {name: {'files': {}, 'fingerprint': name} for name in ('source', 'teams', 'semantic')}
        original = {'generation_sha': 'a' * 40, 'dependency_groups': groups}
        for source in ('scripts/build_catalog.py', 'scripts/extract_document_evidence.py'):
            changed = deepcopy(groups); changed['source']['files'][source] = 'new'
            changed['source']['fingerprint'] = 'changed'
            with patch('tools.release_dependencies.snapshot', return_value=changed), patch.object(common.candidate, 'git'):
                if source == 'scripts/build_catalog.py':
                    common.modern_scope(Path('.'), original, 'topic_area')
                else:
                    with self.assertRaisesRegex(ValueError, 'extractor_only_change'):
                        common.modern_scope(Path('.'), original, 'topic_area')
        book = {'logical_id': 'offline-123', 'limit_microusd': 2_000_000, 'max_requests': 300, 'requests': []}
        value = {'projection_kind': 'topic_area', 'parent_run': '123',
            'retained_requests': common.retained_requests(book)}
        common.require_administrative_budget(value, book)
        book['requests'].append({'provider': 'voyage', 'model': 'voyage-4-lite', 'stage': 'reconciled_vectors',
            'id': 'a' * 32, 'key': 'b' * 64, 'charged_microusd': 1, 'reserved_microusd': 1, 'status': 'valid'})
        with self.assertRaisesRegex(ValueError, 'topic_area_zero_new_requests'):
            common.require_administrative_budget(value, book)

    def test_corpus_mismatch_stops_before_a_topic_vector_dispatch_can_be_reserved(self):
        import tests.test_modern_program_area_budget as fixture
        f = fixture.ModernProgramAreaBudget()
        f.setUp(); self.addCleanup(f.doCleanups)
        state = f.root / 'topic-state'
        outputs = {name: ('retained projection ' + name).encode() for name in common.PROJECTION}
        packet = dict(f.packet, retained_asset_eligible=True)
        with patch.dict('os.environ', GITHUB_RUN_ID='456', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='e' * 40), \
                patch.object(common, 'modern_scope'), \
                patch.object(common, 'modern_contract', return_value={'scripts/build_catalog.py': '6' * 64}), \
                patch.object(common, 'modern_projection', return_value=(outputs, {'projection_kind': 'topic_area'})), \
                patch.object(common, 'vector_packet', return_value=packet), \
                patch.object(common, 'modern_native_vectors', return_value=(False, {})), \
                self.assertRaisesRegex(ValueError, 'topic_area_exact_native_vectors_required'):
            common.prepare_modern(f.bundle, f.root / 'topic-receipt.json', state, '123', f.cid,
                root=f.root, api=f.api, projection_kind='topic_area')
        self.assertFalse((state / 'reservation.json').exists())
        self.assertFalse((f.root / 'topic-receipt.json').exists())
        self.assertEqual(common.read(state / 'ledger.json')['requests'], f.original['requests'])
        f.http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
