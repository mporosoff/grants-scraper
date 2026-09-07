"""Source-annotated development acceptance and integrity of its evidence gate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.validate_parsing_fixtures import validate


MANIFEST = Path(__file__).parent / 'fixtures/parsing/manifest.json'


class ParsingAcceptanceTests(unittest.TestCase):
    def test_development_source_contracts_pass_without_source_or_provider_calls(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Acceptance must stay offline')):
            report = validate(MANIFEST, split='development')
        self.assertTrue(report['passed'], report)
        self.assertGreater(report['counts']['valid_information_retained_or_recovered'], 0)
        self.assertGreater(report['counts']['incorrect_assertion_absent'], 0)

    def test_held_out_source_contracts_pass_without_changing_expected_values(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Holdouts must stay offline')):
            report = validate(MANIFEST, split='holdout')
        self.assertEqual(report['counts']['notices'], 8)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['counts']['valid_information_retained_or_recovered'], 27)
        self.assertEqual(report['counts']['incorrect_assertion_absent'], 8)

    def test_pending_source_annotation_is_not_a_passing_empty_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps({'schema_version': 1, 'notices': [
                {'opportunity_id': 'synthetic-pending', 'split': 'development', 'fixtures': []}]}))
            report = validate(path)
        self.assertFalse(report['passed'])
        self.assertEqual(report['notices'][0]['status'], 'pending_source_annotation')

    def test_fixture_hash_and_path_are_verified_before_interpretation(self):
        template = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = template['notices'][0]
            fixture = row['fixtures'][0]
            (root / fixture['path']).write_bytes(b'{}')
            path = root / 'manifest.json'
            path.write_text(json.dumps({'schema_version': 1, 'notices': [row]}))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                validate(path)
            fixture['path'] = '../outside.json'
            path.write_text(json.dumps({'schema_version': 1, 'notices': [row]}))
            with self.assertRaisesRegex(ValueError, 'within the acceptance directory'):
                validate(path)


if __name__ == '__main__':
    unittest.main()
