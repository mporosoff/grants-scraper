"""Opaque-ID inversions cannot roll back authoritative release evidence."""
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import artifact_chronology as chronology
from tools import alerts_release_handoff as handoff, plan_release as planner
from tools.fetch_release_artifact import merge_artifacts


class ArtifactChronology(unittest.TestCase):
    def setUp(self):
        self.old = {'id': 14847076039, 'name': 'evidence-1', 'expired': False,
                    'created_at': '2026-11-23T17:33:19Z', 'workflow_run': {'id': 44593967977}}
        self.new = {'id': 14846939717, 'name': 'evidence-2', 'expired': False,
                    'created_at': '2026-11-23T18:04:36Z', 'workflow_run': {'id': 44593967977}}

    def test_native_inverted_ids_use_original_creation_and_legacy_alias(self):
        self.assertEqual(chronology.latest([self.new, self.old]), self.new)
        self.assertEqual(chronology.ordered([self.new, self.old]), [self.old, self.new])
        legacy = {'createdAt': '2026-11-23T13:04:36-05:00'}
        self.assertEqual(chronology.created(legacy), chronology.created(self.new))
        self.assertEqual(chronology.created(legacy).tzinfo, timezone.utc)

    def test_missing_naive_conflicting_or_tied_times_have_no_id_fallback(self):
        for value in ({}, {'created_at': '2026-11-23T18:04:36'},
                      {'created_at': 'invalid'}, {'created_at': False},
                      self.new | {'createdAt': self.old['created_at']}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                chronology.created(value)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            chronology.latest([self.new, self.old | {'created_at': self.new['created_at']}])

    def test_native_archive_identity_cannot_disagree_on_original_time(self):
        for row in (self.old, self.new):
            row['digest'] = 'sha256:' + 'a' * 64
        native = self.new | {'expired': True}
        backup = self.new | {'_checkpoint_archive': {'outer_created_at': '2026-11-24T00:00:00Z'}}
        self.assertEqual(merge_artifacts([native], [backup]), [backup])
        with self.assertRaisesRegex(ValueError, 'creation times disagree'):
            merge_artifacts([native], [backup | {'created_at': self.old['created_at']}])
        legacy = deepcopy(backup)
        legacy['createdAt'] = legacy.pop('created_at')
        self.assertEqual(merge_artifacts([native], [legacy]), [legacy])

    def test_latest_failed_validation_supersedes_old_pass_despite_lower_id(self):
        candidate = 'c' * 64
        rows = [self.old | {'name': f'validation-{candidate}-1'},
                self.new | {'name': f'validation-{candidate}-2'}]
        def fetch(repository, run, name, destination):
            destination.mkdir(parents=True)
            (destination / 'validation-report.json').write_text(
                '{"status":"failed"}' if name.endswith('-2') else '{"status":"passed"}', encoding='utf-8')
        with TemporaryDirectory() as directory, \
                patch('tools.fetch_release_artifact.repository_artifacts', return_value=rows), \
                patch('tools.fetch_release_artifact.fetch', side_effect=fetch):
            run, result = planner.latest_report('owner/repo', candidate, 'validation', Path(directory))
        self.assertEqual(result, {'status': 'failed'})

    def test_expired_latest_receipt_does_not_fall_back_to_old_pass(self):
        candidate = 'c' * 64
        rows = [self.old | {'name': f'validation-{candidate}-1'},
                self.new | {'name': f'validation-{candidate}-2', 'expired': True}]
        with TemporaryDirectory() as directory, \
                patch('tools.fetch_release_artifact.repository_artifacts', return_value=rows), \
                patch('tools.fetch_release_artifact.fetch') as fetch:
            _, result = planner.latest_report('owner/repo', candidate, 'validation', Path(directory))
        self.assertIsNone(result)
        fetch.assert_not_called()

    def test_worker_handoff_selects_exact_newest_and_refuses_expired_or_ambiguous(self):
        candidate = 'c' * 64
        rows = [self.old | {'name': f'live-{candidate}-1'}, self.new | {'name': f'live-{candidate}-2'}]
        self.assertEqual(handoff.latest_receipt_artifact(rows, candidate, 'live'), rows[1])
        with self.assertRaises(ValueError):
            handoff.latest_receipt_artifact([rows[0], rows[1] | {'expired': True}], candidate, 'live')
        with self.assertRaises(ValueError):
            handoff.latest_receipt_artifact([rows[0] | {'created_at': rows[1]['created_at']}, rows[1]], candidate, 'live')
