"""Incomplete document work cannot be persisted or pass publication validation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.document_work_budget import require_document_publication
from scripts.enrich_catalog import CATALOG_GLOBAL
from tools import release_candidate as candidate
from tools.verify_notice_publication import verify


class DocumentPublicationBlock(unittest.TestCase):
    def test_only_explicit_completed_marker_or_legacy_catalog_is_accepted(self):
        require_document_publication({})
        require_document_publication({'diagnostics': {'document_work': {'publication_safe': True}}})
        for work in (None, {}, [], False, {'publication_safe': False}, {'publication_safe': 'true'}, {'publication_safe': 1}):
            with self.subTest(work=work), self.assertRaisesRegex(ValueError, 'incomplete'):
                require_document_publication({'diagnostics': {'document_work': work}})

    def test_candidate_cli_blocks_before_creating_immutable_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            catalog = {'opportunities': [], 'record_count': 0,
                       'diagnostics': {'document_work': {'publication_safe': False, 'phase': 'outer_phase_timeout'}}}
            path = root / 'data/opportunities.js'
            path.write_text('globalThis.' + CATALOG_GLOBAL + '=' + json.dumps(catalog) + ';', encoding='utf-8')
            before = path.read_bytes()
            bundle = root / 'candidate'
            with patch('sys.argv', ['release_candidate', 'create', '--bundle', str(bundle), '--root', str(root)]), \
                    patch.object(candidate, 'create') as create, self.assertRaisesRegex(ValueError, 'incomplete'):
                candidate.main()
            create.assert_not_called()
            self.assertFalse(bundle.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_independent_publication_gate_rejects_incomplete_candidate_without_reparsing(self):
        catalog = {'diagnostics': {'document_work': {'publication_safe': False}}}
        with patch('tools.verify_notice_publication.evidence.enrich_document_evidence') as projection, \
                self.assertRaisesRegex(ValueError, 'incomplete'):
            verify(catalog, {})
        projection.assert_not_called()


if __name__ == '__main__':
    unittest.main()
