"""A daily-success timestamp is released only after complete live verification."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_release_live as live


class CatalogLiveFreshness(unittest.TestCase):
    def test_complete_verification_retains_source_time_not_completion_time(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            path = reports / 'live-verification.json'
            path.write_text(json.dumps({'verified': True, 'candidate_id': 'candidate'}))
            with patch.object(live, 'worker_provenance', return_value={'verified': True}), \
                 patch.object(live.c, 'load', return_value={'candidate_id': 'candidate'}), \
                 patch('tools.scheduled_catalog.catalog_generated_at', return_value='2026-09-27T16:17:14Z'):
                report = live.complete_live(reports / 'bundle', reports, 'success', 'success')
            self.assertTrue(report['verified'])
            self.assertEqual(report['catalog_generated_at'], '2026-09-27T16:17:14Z')
            self.assertEqual(json.loads(path.read_text())['catalog_generated_at'], report['catalog_generated_at'])

    def test_missing_or_changed_source_metadata_invalidates_daily_success(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            path = reports / 'live-verification.json'
            path.write_text(json.dumps({'verified': True, 'candidate_id': 'candidate'}))
            with patch.object(live, 'worker_provenance', return_value={'verified': True}), \
                 patch.object(live.c, 'load', return_value={'candidate_id': 'candidate'}), \
                 patch('tools.scheduled_catalog.catalog_generated_at', side_effect=ValueError('metadata hash mismatch')):
                with self.assertRaisesRegex(ValueError, 'Complete live verification failed'):
                    live.complete_live(reports / 'bundle', reports, 'success', 'success')
            self.assertFalse(json.loads(path.read_text())['verified'])

    def test_failed_provider_check_cannot_release_a_freshness_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            path = reports / 'live-verification.json'
            path.write_text(json.dumps({'verified': True, 'candidate_id': 'candidate'}))
            with patch('tools.scheduled_catalog.catalog_generated_at') as source:
                with self.assertRaisesRegex(ValueError, 'Complete live verification failed'):
                    live.complete_live(reports / 'bundle', reports, 'success', 'failure')
            source.assert_not_called()
            self.assertFalse(json.loads(path.read_text())['verified'])


if __name__ == '__main__':
    unittest.main()
