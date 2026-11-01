"""Prove document recovery does not repeat acquisition or trust partial outputs."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import primary_document_revalidation as recovery


class PrimaryDocumentCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = b'%PDF-1.4\npublic pinned test document\n'
        self.expected = {'attachment_id': 355417,
            'url': 'https://grants.gov/grantsws/rest/opportunity/att/download/355417',
            'name': 'FundOpp_DE-FOA-0003641.pdf', 'sha256': recovery.digest(self.raw),
            'bytes': len(self.raw), 'content_type': 'application/pdf'}
        self.response = {'status_code': 200, 'content': self.raw,
            'url': self.expected['url'].replace('https://grants.gov/', 'https://apply07.grants.gov:443/'),
            'content_type': 'application/octet-stream', 'etag': None, 'last_modified': None}
        self.row = {'opportunity_id': '364174', 'source': 'Grants.gov',
            'primary_document_url': self.expected['url'], 'primary_document_name': self.expected['name']}
        self.previous = {'subtopics': [], 'subtopic_method': 'deterministic',
            'subtopic_attempts': [{'source': self.expected['name'], 'outcome': 'no_layer_accepted', 'subtopics': 0}]}
        self.spec = {'selected_document': self.expected}
        self.entry = {'status': 'current', 'document': {'sha256': self.expected['sha256']}, 'facts': []}

    def build(self, row, source, response, previous, now, **kwargs):
        self.assertFalse(kwargs['enable_subtopics'])
        self.assertIsNone(kwargs['structure_cache'])
        return deepcopy(self.entry), True

    def safe(self, variant='v1', *, acquire=True):
        return recovery.safe_entry(self.row, self.previous, self.spec,
            self.root / variant, variant, '2026-11-01T22:00:00+00:00',
            acquire=acquire, acquisition_directory=self.root / 'pdf')

    def test_completed_safe_entry_reuses_without_acquisition_or_extraction(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response) as fetch, \
                patch.object(recovery.evidence, 'build_document_entry', side_effect=self.build) as parse:
            first = self.safe()
            self.assertEqual(first, self.safe(acquire=False))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(first['subtopic_attempts'], self.previous['subtopic_attempts'])

    def test_completed_pdf_survives_parser_failure(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response) as fetch:
            with patch.object(recovery.evidence, 'build_document_entry', side_effect=RuntimeError('parse interrupted')):
                with self.assertRaisesRegex(RuntimeError, 'parse interrupted'):
                    self.safe()
            with patch.object(recovery.evidence, 'build_document_entry', side_effect=self.build):
                self.safe()
            self.assertEqual(fetch.call_count, 1)

    def test_new_recipe_reinterprets_same_pdf_without_new_acquisition(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response) as fetch, \
                patch.object(recovery.evidence, 'build_document_entry', side_effect=self.build) as parse:
            first = self.safe('v1'); second = self.safe('v2')
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(parse.call_count, 2)
            self.assertTrue((self.root / 'v1/entry.json').exists())
            self.assertTrue((self.root / 'v2/entry.json').exists())
            self.assertEqual(first['checked_at'], second['checked_at'])
            self.assertEqual(first['document']['first_seen_at'], second['document']['first_seen_at'])

    def test_failure_of_second_document_keeps_first_complete(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response) as fetch, \
                patch.object(recovery.evidence, 'build_document_entry', side_effect=self.build) as parse:
            first = self.safe()
            with patch.object(recovery.evidence, 'download_document', side_effect=RuntimeError('second unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'second unavailable'):
                    recovery.acquire_pdf(self.root / 'second', self.expected, acquire=True)
            self.assertEqual(first, self.safe(acquire=False))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(parse.call_count, 1)

    def test_constructor_cannot_start_missing_work(self):
        with patch.object(recovery.evidence, 'download_document') as fetch, \
                patch.object(recovery.evidence, 'build_document_entry') as parse:
            with self.assertRaisesRegex(ValueError, 'extraction_not_permitted'):
                self.safe(acquire=False)
            fetch.assert_not_called(); parse.assert_not_called()

    def test_wrong_document_bytes_are_not_checkpointed(self):
        response = self.response | {'content': b'%PDF-wrong'}
        with patch.object(recovery.evidence, 'download_document', return_value=response):
            with self.assertRaisesRegex(ValueError, 'exact_pdf_bytes'):
                recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
        self.assertFalse((self.root / 'pdf/acquisition.json').exists())

    def test_correct_bytes_from_unowned_route_are_rejected(self):
        response = self.response | {'url': 'https://example.org/document.pdf'}
        with self.assertRaisesRegex(ValueError, 'official_pdf_route'):
            recovery.response_identity(response, self.expected)

    def test_tampered_saved_pdf_fails_without_retrieval(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response):
            recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
        path = self.root / 'pdf/acquisition.json'
        saved = json.loads(path.read_text()); saved['content_base64'] = base64.b64encode(b'%PDF-corrupt').decode()
        path.write_text(json.dumps(saved))
        with patch.object(recovery.evidence, 'download_document') as fetch:
            with self.assertRaisesRegex(ValueError, 'exact_pdf_bytes'):
                recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
            fetch.assert_not_called()

    def test_tampered_safe_projection_fails_without_reparsing(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response), \
                patch.object(recovery.evidence, 'build_document_entry', side_effect=self.build):
            self.safe()
        path = self.root / 'v1/entry.json'
        saved = json.loads(path.read_text()); saved['entry']['facts'] = [{'value': 'changed'}]
        path.write_text(json.dumps(saved))
        with patch.object(recovery.evidence, 'build_document_entry') as parse:
            with self.assertRaisesRegex(ValueError, 'safe_entry_checkpoint'):
                self.safe(acquire=False)
            parse.assert_not_called()

    def test_changed_input_cannot_reuse_old_pdf_checkpoint(self):
        with patch.object(recovery.evidence, 'download_document', return_value=self.response):
            recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
        changed = self.expected | {'name': 'another.pdf'}
        with self.assertRaisesRegex(ValueError, 'acquisition_checkpoint'):
            recovery.acquire_pdf(self.root / 'pdf', changed, acquire=False)

    def test_failed_acquisitions_have_a_durable_bound(self):
        with patch.object(recovery.evidence, 'download_document', side_effect=RuntimeError('unavailable')) as fetch:
            for _ in range(3):
                with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                    recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
            with self.assertRaisesRegex(ValueError, 'bounded_acquisition_attempts'):
                recovery.acquire_pdf(self.root / 'pdf', self.expected, acquire=True)
            self.assertEqual(fetch.call_count, 3)
        saved = json.loads((self.root / 'pdf/attempts.json').read_text())
        self.assertEqual(saved['count'], 3)
        self.assertEqual(saved['last_error_type'], 'RuntimeError')


if __name__ == '__main__':
    unittest.main()
