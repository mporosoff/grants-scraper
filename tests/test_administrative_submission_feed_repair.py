"""Repair a serialized current snapshot without changing the saved catalog."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.build_catalog import build_search_index, write_catalog
from scripts.build_changes import _snapshot, render_change_feed
from scripts.submission_schedule import project
from tests.test_build_changes import rec
from tools import administrative_submission_revalidation as replay
from tools.catalog_publication_evidence import change_snapshot_findings


SOURCE = '2026-11-18T18:56:51.080828Z'
EVIDENCE = '2026-11-18T18:58:27.135615Z'
AUDIT = '2026-11-18T21:50:00Z'
TITLE = 'DOJ FY 2026 Invited to Apply \u2013 Model Cities Initiative (MCI)'


class AdministrativeSnapshotRepair(unittest.TestCase):
    def parent(self, root):
        row = project(rec('364275', title=TITLE, close_date='2026-11-30',
            deadlines=[{'kind': 'application', 'date': '2026-11-30',
                'source_field': 'CloseDate', 'confidence': 'official_structured',
                'invitation_required': True, 'prerequisite': 'invitation',
                'invitation_evidence': {'source_field': 'title', 'quote': TITLE,
                    'source_url': 'https://www.grants.gov/search-results-detail/364275'}}]), date(2026, 11, 18))
        catalog = {'schema_version': 3, 'generated_at': SOURCE,
            'document_evidence_generated_at': EVIDENCE, 'record_count': 1,
            'opportunities': [row], 'search_index': build_search_index([row])}
        event = {'id': 'ea1602cf180474dde010', 'type': 'new', 'label': 'New opportunity',
            'changed_at': SOURCE, 'opportunity_id': '364275',
            'detail': 'First appeared in the public catalog', 'record': _snapshot(row)}
        damaged = json.loads(json.dumps(event, ensure_ascii=False).replace('\u2013', '-'))
        historical = deepcopy(damaged)
        historical.update(id='historical', changed_at='2026-11-17T18:56:51Z')
        closed = deepcopy(damaged)
        closed.update(id='closed', type='closed_or_removed', detail='Retained closure record')
        feed = {'schema_version': 1, 'generated_at': '2026-11-18T18:59:00Z',
            'retention_days': 90, 'events': [damaged, historical, closed]}
        write_catalog(catalog, root / 'data/opportunities.js')
        cache = b'{"schema_version":1,"records":{}}\n'
        (root / 'data/document_evidence.json').write_bytes(cache)
        (root / 'feeds').mkdir()
        for name, raw in render_change_feed(feed).items():
            (root / 'feeds' / name).write_bytes(raw)
        return catalog, cache, feed

    def test_feed_only_repair_preserves_catalog_cache_history_closures_and_event_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before, cache, feed = self.parent(root)
            original = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('tools.verify_notice_publication.verify', return_value={'publication_ready': True}), \
                    patch('scripts.subtopic_records.read_cache', return_value={}), \
                    patch('scripts.extract_document_evidence.download_document', side_effect=AssertionError('No source request')):
                outputs, report = replay.projection(root, AUDIT, 'a' * 64)
            after = json.loads(outputs['data/opportunities.js'].decode().split('=', 1)[1].strip().removesuffix(';'))
            fixed = json.loads(outputs['feeds/changes.json'])
            self.assertEqual(after['opportunities'], before['opportunities'])
            self.assertEqual(after['search_index'], before['search_index'])
            self.assertEqual(after['generated_at'], SOURCE)
            self.assertEqual(after['document_evidence_generated_at'], EVIDENCE)
            self.assertEqual(outputs['data/document_evidence.json'], cache)
            self.assertEqual(report['affected_catalog_ids'], [])
            self.assertEqual(report['refreshed_change_event_ids'], ['ea1602cf180474dde010'])
            self.assertEqual(fixed['events'][0]['record']['next_submission']['event']['invitation_evidence']['quote'], TITLE)
            self.assertEqual(fixed['events'][1:], feed['events'][1:])
            self.assertEqual({k: v for k, v in fixed['events'][0].items() if k != 'record'},
                {k: v for k, v in feed['events'][0].items() if k != 'record'})
            self.assertEqual(fixed['generated_at'], feed['generated_at'])
            self.assertEqual(change_snapshot_findings(after, fixed), [])
            self.assertEqual(original, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_serialized_snapshot_gate_rejects_a_renderer_that_alters_official_quotes(self):
        def corrupt(feed):
            outputs = render_change_feed(feed)
            outputs['changes.json'] = outputs['changes.json'].replace('\u2013'.encode(), b'-')
            return outputs
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.parent(root)
            with patch('tools.verify_notice_publication.verify', return_value={'publication_ready': True}), \
                    patch('scripts.subtopic_records.read_cache', return_value={}), \
                    patch('scripts.build_changes.render_change_feed', side_effect=corrupt), \
                    self.assertRaisesRegex(ValueError, 'serialized_change_snapshot_gate'):
                replay.projection(root, AUDIT, 'a' * 64)


if __name__ == '__main__':
    unittest.main()
