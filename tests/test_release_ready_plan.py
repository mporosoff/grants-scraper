"""Authenticate publication code through its retained protected-run plan."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import plan_release as planner


class ReleaseReadyPlan(unittest.TestCase):
    repository = 'owner/repo'
    run_id = '222'
    original_head = 'a' * 40
    release_sha = 'b' * 40
    candidate_id = 'c' * 64

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifacts = [self.artifact(2)]
        self.plans = {'release-plan-2': {'release_sha': self.release_sha}}
        self.validation = {'candidate_id': self.candidate_id, 'validation_sha': self.release_sha,
                           'production_mutated': False, 'gates': {gate: 'passed' for gate in planner.c.GATES}}
        self.ready = {'schema_version': 1, 'candidate_id': self.candidate_id,
                      'base_sha': self.release_sha, 'head_sha': 'd' * 40,
                      'pr_url': 'https://github.com/owner/repo/pull/1', 'artifact_run': '111',
                      'validation_receipt_sha256': planner.c.digest(planner.c.encoded(self.validation)),
                      'timestamp': '2026-09-28T20:00:00Z'}
        self.publication = {'id': 99, 'name': 'publication-' + self.candidate_id + '-2',
                            'expired': False, 'workflow_run': {'id': int(self.run_id)}}
        api = patch('tools.offline_ai_checkpoint.api', side_effect=self.api)
        fetch = patch('tools.fetch_release_artifact.fetch', side_effect=self.fetch)
        self.api_call, self.fetch_call = api.start(), fetch.start()
        self.addCleanup(api.stop)
        self.addCleanup(fetch.stop)

    @staticmethod
    def artifact(attempt, **values):
        return {'id': attempt, 'name': f'release-plan-{attempt}', 'expired': False} | values

    def api(self, repository, path):
        self.assertEqual(repository, self.repository)
        if path.startswith('actions/artifacts?'):
            return json.dumps({'artifacts': [self.publication]})
        self.assertTrue(path.startswith(f'actions/runs/{self.run_id}/artifacts?'), path)
        page = int(path.rsplit('page=', 1)[1])
        return json.dumps({'artifacts': self.artifacts[(page - 1) * 100:page * 100]})

    def fetch(self, repository, run, name, destination):
        self.assertEqual((repository, run), (self.repository, self.run_id))
        destination = Path(destination)
        if name.startswith('publication-'):
            planner.c.write_json(destination / 'review-ready.json', self.ready)
            planner.c.write_json(destination / 'validation.json', self.validation)
        else:
            value = self.plans[name]
            if isinstance(value, bytes):
                destination.mkdir(parents=True, exist_ok=True)
                (destination / 'release-plan.json').write_bytes(value)
            else:
                planner.c.write_json(destination / 'release-plan.json', value)
        return {'head_sha': self.original_head, 'head_branch': 'main', 'event': 'schedule',
                'path': '.github/workflows/refresh-opportunities.yml'}

    def read_plan(self, attempt=2, suffix='plan'):
        return planner.release_plan_sha(self.repository, self.run_id, attempt, self.root / suffix)

    def read_ready(self, suffix='ready'):
        return planner.latest_report(self.repository, self.candidate_id, 'review', self.root / suffix)

    def test_updated_main_rerun_uses_authenticated_plan_not_original_event_sha(self):
        run, ready = self.read_ready()
        self.assertEqual((run, ready), (self.run_id, self.ready))
        self.assertNotEqual(ready['base_sha'], self.original_head)
        self.assertEqual(self.fetch_call.call_args_list[-1].args[:3],
                         (self.repository, self.run_id, 'release-plan-2'))
        self.assertNotEqual(self.run_id, ready['artifact_run'], 'Plan belongs to publisher, not candidate owner')

    def test_failed_job_retry_inherits_latest_earlier_successful_plan(self):
        self.publication['name'] = 'publication-' + self.candidate_id + '-3'
        self.assertEqual(self.read_ready()[1], self.ready)
        self.assertEqual(self.fetch_call.call_args_list[-1].args[2], 'release-plan-2')

    def test_latest_plan_is_selected_by_numeric_attempt_not_artifact_id_or_order(self):
        self.artifacts = [self.artifact(2, id=90), self.artifact(10, id=3), self.artifact(9, id=100)]
        self.plans['release-plan-10'] = {'release_sha': self.release_sha}
        self.assertEqual(self.read_plan(attempt=12), self.release_sha)
        self.assertEqual(self.fetch_call.call_args.args[2], 'release-plan-10')

    def test_later_plan_cannot_supply_or_replace_earlier_publication_proof(self):
        self.artifacts.append(self.artifact(3, expired=True))
        self.assertEqual(self.read_plan(), self.release_sha)
        self.artifacts = [self.artifact(3)]
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.read_plan(suffix='later-only')

    def test_missing_plan_does_not_fall_back_to_original_event_head(self):
        self.artifacts = []
        self.original_head = self.release_sha
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.read_ready()
        self.assertEqual(self.fetch_call.call_count, 1, 'Only the publication was fetched')

    def test_expired_or_duplicate_newest_plan_cannot_fall_back_to_older_pass(self):
        for selected in ([self.artifact(2, expired=True)], [self.artifact(2), self.artifact(2, id=20)]):
            with self.subTest(selected=selected):
                self.artifacts = [self.artifact(1)] + selected
                with self.assertRaisesRegex(ValueError, 'ambiguous or expired'):
                    self.read_plan()
        self.fetch_call.assert_not_called()

    def test_missing_expiration_state_is_not_trusted(self):
        del self.artifacts[0]['expired']
        with self.assertRaisesRegex(ValueError, 'ambiguous or expired'):
            self.read_plan()

    def test_malformed_newest_plan_cannot_fall_back_to_older_pass(self):
        self.artifacts.insert(0, self.artifact(1))
        for index, value in enumerate(({}, [], None, {'release_sha': None}, {'release_sha': 123},
                                       {'release_sha': 'b' * 39}, {'release_sha': 'B' * 40},
                                       {'release_sha': 'not-a-sha'}, b'{broken-json')):
            with self.subTest(value=value):
                self.plans['release-plan-2'] = value
                with self.assertRaises(ValueError):
                    self.read_plan(suffix=str(index))
        self.assertTrue(all(call.args[2] == 'release-plan-2' for call in self.fetch_call.call_args_list))

    def test_missing_plan_file_or_rejected_trusted_origin_fail_closed(self):
        self.fetch_call.side_effect = lambda *args: None
        with self.assertRaises(FileNotFoundError):
            self.read_plan()
        self.fetch_call.side_effect = ValueError('Candidate evidence must originate in the protected release workflow on main')
        with self.assertRaisesRegex(ValueError, 'protected release workflow'):
            self.read_plan()

    def test_plan_lookup_reads_later_pages_before_selecting(self):
        self.artifacts = [{'id': i, 'name': f'unrelated-{i}', 'expired': False} for i in range(100)]
        self.artifacts.append(self.artifact(2))
        self.assertEqual(self.read_plan(), self.release_sha)
        self.assertEqual(self.api_call.call_count, 2)

    def test_duplicate_across_pages_and_unbounded_lookup_fail_closed(self):
        self.artifacts = [self.artifact(2)] + [
            {'id': i, 'name': f'unrelated-{i}', 'expired': False} for i in range(99)] + [self.artifact(2, id=999)]
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.read_plan()
        self.api_call.reset_mock()
        self.api_call.side_effect = lambda *args: json.dumps({'artifacts': self.artifacts[:100]})
        with self.assertRaisesRegex(ValueError, 'bounded lookup'):
            self.read_plan(suffix='unbounded')
        self.assertEqual(self.api_call.call_count, 100)
        self.fetch_call.assert_not_called()

    def test_invalid_publication_attempt_cannot_choose_a_plan(self):
        for attempt in (0, -1, None, True, '2-invalid'):
            with self.subTest(attempt=attempt), self.assertRaisesRegex(ValueError, 'Invalid publication attempt'):
                self.read_plan(attempt=attempt)
        self.api_call.assert_not_called()

    def test_newest_plan_mismatch_cannot_select_matching_older_plan(self):
        self.artifacts.insert(0, self.artifact(1))
        self.plans['release-plan-1'] = {'release_sha': self.release_sha}
        self.plans['release-plan-2'] = {'release_sha': 'e' * 40}
        with self.assertRaisesRegex(ValueError, 'protected validation'):
            self.read_ready()
        self.assertEqual(self.fetch_call.call_args_list[-1].args[2], 'release-plan-2')

    def test_paired_validation_still_must_bind_plan_base_hash_and_passing_gates(self):
        for index, override in enumerate(({'validation_sha': 'e' * 40}, {'production_mutated': True},
                                          {'candidate_id': 'f' * 64}, {'gates': {'python': 'failed'}})):
            with self.subTest(override=override):
                old = self.validation
                self.validation = old | override
                self.ready['validation_receipt_sha256'] = planner.c.digest(planner.c.encoded(self.validation))
                with self.assertRaisesRegex(ValueError, 'protected validation'):
                    self.read_ready(suffix=str(index))
                self.validation = old
        self.ready['validation_receipt_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'protected validation'):
            self.read_ready(suffix='receipt-hash')


if __name__ == '__main__':
    unittest.main()
