"""Recover an owned annual application field from the same saved candidate."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from scripts import extract_document_evidence as evidence
from scripts.build_catalog import build_search_index, write_catalog
from scripts.build_changes import _snapshot, render_change_feed
from tests.test_application_cycles import retained_record, STAMP
from tools import administrative_submission_revalidation as replay
from tools import program_area_revalidation as common
from tools import release_candidate as candidate, release_dependencies as dependencies


GENERATED = '2026-11-17T20:01:41.830673Z'
EVIDENCE_AT = '2026-11-17T20:05:00Z'
AUDIT_AT = '2026-11-18T14:00:00Z'


class AdministrativeApplicationCycleReplay(unittest.TestCase):
    def inputs(self):
        row = retained_record()
        other = {'opportunity_id': 'expired-other', 'title': 'Unchanged expired opportunity',
            'source': 'Grants.gov', 'source_type': 'Federal', 'status': 'posted',
            'close_date': '2026-11-17', 'deadlines': []}
        rows = [row, other]
        catalog = {'schema_version': 3, 'generated_at': GENERATED,
            'document_evidence_generated_at': EVIDENCE_AT, 'opportunities': rows,
            'record_count': len(rows), 'search_index': build_search_index(rows)}
        cache = {'schema_version': 1, 'generated_at': EVIDENCE_AT,
            'records': {'364271': {'status': 'current', 'checked_at': STAMP,
                'document': deepcopy(row['document_evidence']['document']),
                'facts': deepcopy(row['document_evidence']['facts'])}}}
        return catalog, cache

    def test_annual_cycle_projection_preserves_source_cache_and_every_unrelated_field(self):
        catalog, cache = self.inputs()
        original = deepcopy((catalog, cache))
        with patch.object(evidence, 'download_document', side_effect=AssertionError('source retrieval')), \
                patch.object(evidence, 'build_document_entry', side_effect=AssertionError('document acquisition')):
            after, retained, changed = replay.project_catalog(catalog, cache)
        self.assertEqual((catalog, cache), original)
        self.assertEqual(retained, cache)
        self.assertEqual(changed, ['364271'])
        self.assertEqual(after['opportunities'][1], catalog['opportunities'][1])
        old, new = catalog['opportunities'][0], after['opportunities'][0]
        self.assertEqual(new['close_date'], old['close_date'])
        self.assertEqual(new['archive_date'], old['archive_date'])
        self.assertEqual(new['document_evidence_checked_at'], old['document_evidence_checked_at'])
        self.assertEqual(new['document_evidence']['facts'][0]['id'], old['document_evidence']['facts'][0]['id'])
        self.assertEqual([fact['date'] for fact in new['document_evidence']['facts']],
            ['2027-03-15', '2028-03-15'])
        self.assertEqual(new['document_evidence']['facts'][1]['citation']['quote'],
            old['document_evidence']['facts'][0]['citation']['quote'])
        self.assertEqual(after['generated_at'], GENERATED)
        self.assertEqual(after['document_evidence_generated_at'], EVIDENCE_AT)
        self.assertEqual(after['search_index'], build_search_index(after['opportunities']))
        second, again, changed_again = replay.project_catalog(after, cache)
        self.assertEqual((second, again, changed_again), (after, cache, []))

    def test_recovery_firewall_rejects_changes_beyond_the_reproduced_annual_field(self):
        catalog, cache = self.inputs()
        after, _, _ = replay.project_catalog(catalog, cache)
        before = catalog['opportunities'][0]
        for fault in ('source-close', 'source-clock', 'other-fact', 'new-date', 'new-citation'):
            row = deepcopy(after['opportunities'][0])
            if fault == 'source-close':
                row['close_date'] = '2028-03-15'
            elif fault == 'source-clock':
                row['document_evidence_checked_at'] = AUDIT_AT
            elif fault == 'other-fact':
                row['document_evidence']['facts'].append({'id': 'injected', 'type': 'eligibility'})
            elif fault == 'new-date':
                row['document_evidence']['facts'][1]['date'] = '2029-03-15'
            else:
                row['document_evidence']['facts'][1]['citation']['quote'] = 'A different notice.'
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                replay.record_firewall(before, row)

    def test_delayed_unpublished_feed_uses_audit_date_and_only_refreshes_matching_event(self):
        catalog, cache = self.inputs()
        event = {'id': 'new-364271', 'type': 'new', 'label': 'New opportunity',
            'changed_at': GENERATED, 'opportunity_id': '364271',
            'detail': 'First appeared in the public catalog', 'record': _snapshot(catalog['opportunities'][0])}
        historical = deepcopy(event)
        historical.update(id='historical-364271', changed_at='2026-11-16T20:01:41.830673Z')
        feed = {'schema_version': 1, 'generated_at': '2026-11-17T20:06:00Z',
            'retention_days': 90, 'events': [event, historical]}
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / 'data').mkdir()
            (parent / 'feeds').mkdir()
            write_catalog(catalog, parent / common.PROJECTION[0])
            cache_bytes = (json.dumps(cache, separators=(',', ':')) + '\n').encode()
            (parent / common.PROJECTION[2]).write_bytes(cache_bytes)
            for name, raw in render_change_feed(feed).items():
                (parent / 'feeds' / name).write_bytes(raw)
            with patch('tools.verify_notice_publication.verify', return_value={'publication_ready': True}), \
                    patch('scripts.subtopic_records.read_cache', return_value={}):
                outputs, report = replay.projection(parent, AUDIT_AT, 'a' * 64)
        projected = json.loads(outputs['feeds/changes.json'])
        self.assertEqual(report['refreshed_change_event_ids'], ['new-364271'])
        self.assertEqual(projected['events'][1], historical)
        self.assertEqual({key: value for key, value in projected['events'][0].items() if key != 'record'},
            {key: value for key, value in event.items() if key != 'record'})
        self.assertEqual(projected['generated_at'], feed['generated_at'])
        self.assertEqual([row['date'] for row in projected['events'][0]['record']['deadlines']],
            ['2027-03-15', '2028-03-15'])
        self.assertNotIn(b'Unchanged expired opportunity', outputs['feeds/all.xml'])
        self.assertIn(b'Research Facilities Act Program', outputs['feeds/all.xml'])
        self.assertEqual(outputs[common.PROJECTION[2]], cache_bytes)
        projected_catalog = json.loads(outputs[common.PROJECTION[0]].decode().split('=', 1)[1].strip().removesuffix(';'))
        self.assertEqual(projected_catalog['generated_at'], GENERATED)
        self.assertEqual(projected_catalog['document_evidence_generated_at'], EVIDENCE_AT)
        self.assertEqual(projected_catalog['catalog_audit_generated_at'], AUDIT_AT)

    def test_new_snapshot_output_paths_keep_existing_receipts_compatible(self):
        hashes = {name: 'a' * 64 for name in common.PROJECTION}
        old = {'projection_kind': 'administrative_submission', 'projection_hashes': hashes}
        self.assertEqual(set(common.projection_names(old)), set(common.PROJECTION))
        extended = deepcopy(old)
        extended['projection_hashes'].update({name: 'b' * 64 for name in common.ADMINISTRATIVE_OUTPUTS})
        self.assertEqual(set(common.projection_names(extended)), set(common.PROJECTION + common.ADMINISTRATIVE_OUTPUTS))
        extended['projection_hashes']['data/source_records.json'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'projection_paths_and_hashes'):
            common.projection_names(extended)


class AdministrativeInvocationScope(unittest.TestCase):
    argument = ' --retained-catalog "$RUNNER_TEMP/opportunities.previous.js"'

    def original_workflow(self):
        return {'jobs': {'generate': {'steps': [
            {'run': 'python -m scripts.build_catalog\n --output data/opportunities.js --min-records 1000',
             'env': {'CATALOG_MODE': 'production', 'OFFLINE_AI_STATE': '/tmp/run',
                     'API_KEY': '${{ secrets.API_KEY }}'}},
            {'run': 'python -m tools.run_budgeted_documents --max-documents 45'},
            {'run': 'python -m scripts.build_opportunity_teams --maintenance'},
            {'run': 'node tools/run_budgeted_vectors.mjs --production --write',
             'env': {'VECTOR_MODE': 'production', 'VOYAGE_API_KEY': '${{ secrets.VOYAGE_API_KEY }}'}},
        ]}}}

    def scope(self, workflow):
        prior = dependencies.generation_invocations(self.original_workflow())
        current = dependencies.generation_invocations(workflow)
        before = {group: {'files': {}} for group in ('source', 'teams', 'semantic')}
        before['source']['files']['@generation_invocations'] = candidate.digest(candidate.encoded(prior['source']))
        selected = deepcopy(before)
        selected['source']['files']['@generation_invocations'] = candidate.digest(candidate.encoded(current['source']))
        original = {'generation_sha': 'a' * 40, 'dependency_groups': before}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / '.github/workflows/refresh-opportunities.yml'
            target.parent.mkdir(parents=True)
            target.write_text(yaml.safe_dump(workflow), encoding='utf-8')
            with patch.object(dependencies, 'snapshot', return_value=selected), patch.object(candidate, 'git'):
                common.modern_scope(root, original, 'administrative_submission')

    def test_invocation_fingerprints_keep_existing_normalization_and_public_environment(self):
        self.assertEqual(dependencies.generation_invocations(self.original_workflow()), {
            'source': [
                {'command': 'python -m scripts.build_catalog --output data/opportunities.js --min-records 1000',
                 'environment': {'CATALOG_MODE': 'production'}},
                {'command': 'python -m scripts.extract_document_evidence --max-documents 45', 'environment': {}},
            ],
            'semantic': [{'command': 'node tools/build_search_v2_voyage_vectors.mjs --production --write',
                          'environment': {'VECTOR_MODE': 'production'}}],
        })

    def test_scope_accepts_only_the_exact_retained_catalog_argument(self):
        workflow = self.original_workflow()
        workflow['jobs']['generate']['steps'][0]['run'] += self.argument
        self.scope(workflow)
        for fault in ('other-output', 'document-limit', 'public-environment', 'other-source',
                      'different-retained-path', 'duplicate-argument', 'duplicate-builder'):
            changed = deepcopy(workflow)
            steps = changed['jobs']['generate']['steps']
            if fault == 'other-output':
                steps[0]['run'] = steps[0]['run'].replace('data/opportunities.js', 'data/different.js')
            elif fault == 'document-limit':
                steps[1]['run'] = steps[1]['run'].replace('45', '46')
            elif fault == 'public-environment':
                steps[0]['env']['CATALOG_MODE'] = 'different'
            elif fault == 'other-source':
                steps.append({'run': 'python -m scripts.different_source'})
            elif fault == 'different-retained-path':
                steps[0]['run'] = steps[0]['run'].replace('opportunities.previous.js', 'different.js')
            elif fault == 'duplicate-argument':
                steps[0]['run'] += self.argument
            else:
                steps.append(deepcopy(steps[0]))
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, 'administrative_'):
                self.scope(changed)


if __name__ == '__main__':
    unittest.main()
