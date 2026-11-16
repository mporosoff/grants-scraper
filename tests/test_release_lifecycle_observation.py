"""Shadow observation binds exact attempts and never runs release operations."""

from copy import deepcopy
import base64
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_release_checkpoint_archive import ATTEMPT, REPOSITORY, RUN, SHA, artifact, packed, run_metadata
from tools import release_candidate as candidate
from tools import release_checkpoint_archive as archive
from tools import release_lifecycle_observation as observer


class ReleaseLifecycleObservation(unittest.TestCase):
    def test_pending_review_cannot_omit_pr_number(self):
        identifier = 'b' * 64
        report = {'schema_version': 1, 'repository': REPOSITORY, 'candidate_id': identifier,
                  'status': 'awaiting_review', 'production_mutated': False,
                  'artifact_run': RUN, 'head_sha': SHA}
        with self.assertRaisesRegex(ValueError, 'Invalid lifecycle review PR'):
            observer.observe_review('review-pending.json', report, REPOSITORY, identifier)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'archive'
        self.artifacts = []
        self.attempt = ATTEMPT
        job = {'name': 'publish', 'id': 8, 'run_id': int(RUN), 'run_attempt': ATTEMPT,
               'head_sha': SHA, 'head_branch': 'main', 'status': 'completed', 'conclusion': 'failure'}
        self.jobs = f'actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100&page=1'
        self.inventory = f'actions/runs/{RUN}/artifacts?per_page=100&page=1'
        self.values = {
            f'actions/runs/{RUN}': run_metadata(),
            f'actions/runs/{RUN}/attempts/{ATTEMPT}': run_metadata(),
            self.jobs: {'jobs': [job], 'total_count': 1},
            self.inventory: {'artifacts': self.artifacts, 'total_count': 0},
        }
        self.manifest = {'generation_run_id': '42', 'generation_run_attempt': '1',
                         'generation_sha': 'b' * 40, 'derived_from_candidate': 'c' * 64,
                         'source_recovery': {'superseded_recovery_candidate': 'd' * 64,
                                             'superseded_recovery_run': '55'}}
        self.identifier = candidate.digest(candidate.encoded(self.manifest))
        self.manifest['candidate_id'] = self.identifier

    def read(self, path):
        value = self.values[path]
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def add(self, name, **files):
        identifier = len(self.artifacts) + 11
        raw = packed({key: json.dumps(value).encode() for key, value in files.items()})
        self.artifacts.append(artifact(identifier, name, raw))
        self.values[self.inventory]['total_count'] = len(self.artifacts)
        self.values[f'actions/artifacts/{identifier}/zip'] = raw

    def capture(self):
        archive.capture(REPOSITORY, RUN, self.attempt, self.directory, api=self.read)

    def observe(self):
        return observer.observe(REPOSITORY, RUN, self.attempt, self.directory, api=self.read)

    def record_jobs(self, attempt, **stages):
        metadata = run_metadata() | {'run_attempt': attempt}
        self.values[f'actions/runs/{RUN}/attempts/{attempt}'] = metadata
        if attempt == self.attempt:
            self.values[f'actions/runs/{RUN}'] = metadata
        path = f'actions/runs/{RUN}/attempts/{attempt}/jobs?per_page=100&page=1'
        jobs = {row['name']: row for row in self.values.get(path, {}).get('jobs', [])}
        first_id = max([100 * attempt] + [job['id'] for job in jobs.values()]) + 1
        for identifier, (name, conclusion) in enumerate(stages.items(), start=first_id):
            jobs[name] = {'name': name, 'id': identifier, 'run_id': int(RUN),
                          'run_attempt': attempt, 'head_sha': SHA, 'head_branch': 'main',
                          'status': 'completed', 'conclusion': conclusion}
        self.values[path] = {'jobs': list(jobs.values()), 'total_count': len(jobs)}

    def add_review(self, status, **overrides):
        report = {'schema_version': 1, 'status': status, 'candidate_id': self.identifier, 'artifact_run': RUN,
                  'repository': REPOSITORY, 'head_sha': SHA, 'pr_number': 38, 'production_mutated': False,
                  'unpublished_details': 'must not appear in observation'} | overrides
        name = 'review-blocked.json' if status == 'review_findings' else 'review-pending.json'
        self.add(f'publication-{self.identifier}-{ATTEMPT}', **{name: report})

    def add_protected_resume(self, *, publication_sha=None, plan_attempt=None, validation_attempt=None,
                             consumed_validation=None, **overrides):
        plan_attempt = plan_attempt or self.attempt
        validation_attempt = validation_attempt or self.attempt
        self.record_jobs(plan_attempt, plan='success')
        self.record_jobs(validation_attempt, validate='success')
        self.add(f'release-plan-{plan_attempt}', **{'release-plan.json': {
            'release_sha': SHA, 'stage': 'publish', 'candidate_id': self.identifier, 'candidate_run': '77'}})
        validation = {'candidate_id': self.identifier, 'validation_sha': 'b' * 40}
        self.add(f'validation-{self.identifier}-{validation_attempt}', **{'validation.json': validation})
        ready = {'schema_version': 1, 'candidate_id': self.identifier, 'artifact_run': '77', 'head_sha': SHA,
                 'base_sha': SHA, 'pr_url': None,
                 'validation_receipt_sha256': candidate.digest(candidate.encoded(validation))} | overrides
        reports = {'review-ready.json': ready, 'validation.json': consumed_validation or validation}
        if publication_sha:
            publication = {'candidate_id': self.identifier, 'publication_sha': publication_sha}
            reports['publication.json'] = publication
            self.add(f'live-{self.identifier}-{self.attempt}',
                     **{'live-verification.json': publication | {'verified': True}})
        self.add(f'publication-{self.identifier}-{self.attempt}', **reports)
        path = 'release/candidate.json'
        content = candidate.encoded(self.manifest)
        self.values[f'contents/{path}?ref={SHA}'] = {
            'path': path, 'encoding': 'base64', 'size': len(content), 'content': base64.encodebytes(content).decode()}

    def test_exact_review_failure_retains_candidate_lineage_without_report_text(self):
        self.add(f'candidate-{self.identifier}', **{'candidate.json': self.manifest})
        self.add(f'release-plan-{ATTEMPT}', **{'release-plan.json': {
            'release_sha': SHA, 'stage': 'generate', 'reason': 'private diagnostic'}})
        self.add(f'generation-spend-reservation-{RUN}-{ATTEMPT}', **{'reservation.json': {'secret': 'irrelevant'}})
        self.add_review('review_failed')
        self.capture()
        receipt = self.observe()
        identity = receipt.pop('receipt_sha256')
        self.assertEqual(identity, candidate.digest(candidate.encoded(receipt)))
        self.assertEqual(receipt['mode'], 'shadow')
        self.assertEqual(receipt['stages']['publish'], {'job_id': 8, 'conclusion': 'failure'})
        self.assertEqual(receipt['checkpoints']['review'], {
            'status': 'review_failed', 'artifact_run': RUN, 'head_sha': SHA, 'pr_number': '38',
            'candidate_id': self.identifier,
        })
        self.assertEqual(receipt['checkpoints']['persisted_candidate']['generation_run_id'], '42')
        self.assertEqual(receipt['checkpoints']['persisted_candidate']['rejected_sibling_artifact_run'], '55')
        self.assertEqual(len(receipt['artifact_references']), 4)
        rendered = json.dumps(receipt)
        for forbidden in ('private diagnostic', 'must not appear', 'secret'):
            self.assertNotIn(forbidden, rendered)

    def test_prior_attempt_report_is_not_current_review_and_findings_are_distinct(self):
        self.add(f'publication-{self.identifier}-1', **{'review-pending.json': {'arbitrary': 'prior'}})
        self.add_review('review_findings')
        self.capture()
        receipt = self.observe()
        self.assertEqual(receipt['checkpoints']['review']['status'], 'review_findings')
        self.assertEqual(len(receipt['artifact_references']), 2)

    def test_pending_review_binds_to_selected_run_on_downstream_retry(self):
        self.add(f'release-plan-{ATTEMPT}', **{'release-plan.json': {
            'release_sha': SHA, 'stage': 'publish', 'candidate_id': self.identifier, 'candidate_run': '77'}})
        self.add_review('awaiting_review', artifact_run='77')
        self.capture()
        self.assertEqual(self.observe()['checkpoints']['review']['artifact_run'], '77')

    def test_review_validation_publication_and_live_are_distinct_evidence(self):
        ready = {'schema_version': 1, 'candidate_id': self.identifier, 'artifact_run': RUN,
                 'head_sha': SHA, 'pr_url': f'https://github.com/{REPOSITORY}/pull/38'}
        publication = {'candidate_id': self.identifier, 'publication_sha': 'd' * 40}
        self.add(f'validation-{self.identifier}-{ATTEMPT}',
                 **{'validation.json': {'candidate_id': self.identifier, 'validation_sha': SHA}})
        self.add(f'publication-{self.identifier}-{ATTEMPT}',
                 **{'review-ready.json': ready, 'publication.json': publication})
        self.add(f'live-{self.identifier}-{ATTEMPT}',
                 **{'live-verification.json': publication | {'verified': True}})
        self.capture()
        checkpoints = self.observe()['checkpoints']
        self.assertEqual(checkpoints['review']['status'], 'review_ready')
        self.assertEqual(checkpoints['validation']['validation_sha'], SHA)
        self.assertEqual(checkpoints['publication'], publication)
        self.assertEqual(checkpoints['live'], publication)

    def test_protected_publication_resume_verifies_without_a_new_review_pr(self):
        self.add_protected_resume(publication_sha=SHA)
        self.capture()
        checkpoints = self.observe()['checkpoints']
        self.assertEqual(checkpoints['review'], {'status': 'protected_publication_resume',
                         'candidate_id': self.identifier, 'artifact_run': '77', 'head_sha': SHA})
        self.assertEqual(checkpoints['live'], checkpoints['publication'])

    def test_protected_resume_readiness_can_precede_a_publication_or_live_receipt(self):
        self.add_protected_resume()
        self.capture()
        checkpoints = self.observe()['checkpoints']
        self.assertEqual(checkpoints['review']['status'], 'protected_publication_resume')
        self.assertNotIn('publication', checkpoints)
        self.assertNotIn('live', checkpoints)

    def test_failed_jobs_rerun_binds_prior_plan_and_latest_validation_producers(self):
        self.attempt = 3
        self.record_jobs(self.attempt, publish='success', **{'verify-live': 'success'})
        self.record_jobs(1, validate='success', publish='failure')
        self.record_jobs(2, publish='failure')
        self.add(f'validation-{self.identifier}-1', **{'validation.json': {
            'candidate_id': self.identifier, 'validation_sha': 'c' * 40}})
        self.add_protected_resume(plan_attempt=1, validation_attempt=2, publication_sha=SHA)
        self.capture()
        receipt = self.observe()
        self.assertEqual(receipt['checkpoints']['review']['status'], 'protected_publication_resume')
        self.assertEqual(receipt['checkpoints']['plan']['producer_attempt'], 1)
        self.assertEqual(receipt['checkpoints']['validation']['producer_attempt'], 2)
        self.assertEqual(receipt['checkpoints']['validation']['validation_sha'], 'b' * 40)
        self.assertEqual(set(receipt['stages']), {'publish', 'verify-live'})

    def test_current_or_intervening_failed_validation_supersedes_old_success(self):
        self.attempt = 3
        self.record_jobs(self.attempt, publish='failure')
        self.record_jobs(2, validate='failure')
        self.add_protected_resume(plan_attempt=1, validation_attempt=1)
        self.capture()
        with self.assertRaisesRegex(ValueError, 'latest successful validate producer'):
            self.observe()
        self.record_jobs(2, publish='failure', validate='skipped')
        self.record_jobs(self.attempt, validate='failure')
        with self.assertRaisesRegex(ValueError, 'latest successful validate producer'):
            self.observe()

    def test_protected_resume_does_not_substitute_older_passing_validation_for_latest_report(self):
        self.add_protected_resume(plan_attempt=1, validation_attempt=1)
        self.record_jobs(ATTEMPT, validate='failure')
        self.add(f'validation-{self.identifier}-{ATTEMPT}', **{'validation-report.json': {'failed': True}})
        self.capture()
        with self.assertRaisesRegex(ValueError, 'latest successful validate producer'):
            self.observe()

    def test_protected_resume_rejects_future_plan_or_validation_artifact(self):
        self.add_protected_resume(plan_attempt=1, validation_attempt=1)
        self.add('release-plan-3', **{'release-plan.json': {'candidate_id': self.identifier}})
        self.capture()
        with self.assertRaisesRegex(ValueError, 'Future lifecycle checkpoint'):
            self.observe()

    def test_protected_resume_rejects_prior_attempt_from_another_protected_event(self):
        self.add_protected_resume(plan_attempt=1, validation_attempt=1)
        self.values[f'actions/runs/{RUN}/attempts/1']['event'] = 'push'
        self.capture()
        with self.assertRaisesRegex(ValueError, 'different protected run'):
            self.observe()

    def test_protected_resume_rejects_the_receipt_from_an_unrelated_validation(self):
        self.add_protected_resume(plan_attempt=1, validation_attempt=1, consumed_validation={
            'candidate_id': 'e' * 64, 'validation_sha': SHA})
        self.capture()
        with self.assertRaisesRegex(ValueError, 'did not consume the retained validation receipt'):
            self.observe()

    def test_pages_and_live_retry_does_not_relabel_the_prior_publication(self):
        self.record_jobs(ATTEMPT, pages='success', **{'verify-live': 'success'})
        publication = {'candidate_id': self.identifier, 'publication_sha': SHA}
        self.add(f'publication-{self.identifier}-1', **{'publication.json': publication})
        self.add(f'live-{self.identifier}-{ATTEMPT}', **{'publication.json': publication,
                     'live-verification.json': publication | {'verified': True}})
        self.capture()
        checkpoints = self.observe()['checkpoints']
        self.assertEqual(checkpoints, {'live': publication})

    def test_protected_resume_is_not_inferred_when_the_path_is_not_explicitly_null(self):
        report = {'schema_version': 1, 'candidate_id': self.identifier, 'head_sha': SHA,
                  'artifact_run': '77'}
        for url in ({}, {'pr_url': ''}, {'pr_url': 'https://github.com/other/repository/pull/1'}):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Untrusted lifecycle review PR'):
                observer.observe_review('review-ready.json', report | url, REPOSITORY, self.identifier)

    def test_protected_resume_rejects_a_different_candidate_run(self):
        self.add_protected_resume(artifact_run='999')
        self.capture()
        with self.assertRaisesRegex(ValueError, 'different candidate artifact run'):
            self.observe()

    def test_protected_resume_rejects_a_wrong_validation_digest(self):
        self.add_protected_resume(validation_receipt_sha256='c' * 64)
        self.capture()
        with self.assertRaisesRegex(ValueError, 'disagrees with the plan or validation receipt'):
            self.observe()

    def test_protected_resume_rejects_a_different_head(self):
        self.add_protected_resume(head_sha='c' * 40)
        self.capture()
        with self.assertRaisesRegex(ValueError, 'disagrees with the plan or validation receipt'):
            self.observe()

    def test_protected_resume_rejects_a_base_outside_the_pinned_plan(self):
        self.add_protected_resume(head_sha='c' * 40, base_sha='c' * 40)
        self.capture()
        with self.assertRaisesRegex(ValueError, 'disagrees with the plan or validation receipt'):
            self.observe()

    def test_protected_resume_rejects_a_different_published_sha(self):
        self.add_protected_resume(publication_sha='c' * 40)
        self.capture()
        with self.assertRaisesRegex(ValueError, 'changed publication SHA'):
            self.observe()

    def test_protected_resume_rejects_marker_for_different_candidate(self):
        self.add_protected_resume()
        self.capture()
        raw = candidate.encoded(self.manifest | {'candidate_id': 'f' * 64})
        self.values[f'contents/release/candidate.json?ref={SHA}'].update(
            size=len(raw), content=base64.b64encode(raw).decode())
        with self.assertRaisesRegex(ValueError, 'candidate manifest has conflicting identity'):
            self.observe()

    def test_changed_artifact_is_rejected(self):
        self.add_review('awaiting_review')
        self.capture()
        (self.directory / 'artifacts/11.zip').write_bytes(b'replaced')
        with self.assertRaisesRegex(ValueError, 'retained digest'):
            self.observe()

    def test_attempt_and_review_head_must_authenticate(self):
        self.add_review('awaiting_review', head_sha='abbrev')
        self.capture()
        with self.assertRaisesRegex(ValueError, 'review head'):
            self.observe()
        expected = deepcopy(self.values[f'actions/runs/{RUN}'])
        self.values[f'actions/runs/{RUN}/attempts/{ATTEMPT}'] = expected | {'path': 'untrusted.yml'}
        with self.assertRaisesRegex(ValueError, 'workflow origin'):
            self.observe()

    def test_missing_jobs_and_conflicting_native_labels_fail_closed(self):
        self.add_review('awaiting_review')
        self.add_review('review_failed')
        self.capture()
        self.values[self.jobs]['total_count'] = 2
        with self.assertRaisesRegex(ValueError, 'Incomplete checkpoint artifact inventory'):
            self.observe()
        self.values[self.jobs]['total_count'] = 1
        with self.assertRaisesRegex(ValueError, 'Conflicting lifecycle artifact labels'):
            self.observe()

    def test_empty_first_attempt_can_be_observed_only_for_native_cancellation(self):
        cancelled = run_metadata() | {'run_attempt': 1, 'conclusion': 'cancelled'}
        self.values[f'actions/runs/{RUN}'] = cancelled
        self.values[f'actions/runs/{RUN}/attempts/1'] = cancelled
        self.values[f'actions/runs/{RUN}/attempts/1/jobs?per_page=100&page=1'] = {'jobs': [], 'total_count': 0}
        result = observer.observe(REPOSITORY, RUN, 1, self.directory, api=self.read)
        self.assertEqual(result['source_conclusion'], 'cancelled')
        self.assertEqual(result['stages'], {})
        self.assertEqual(result['artifact_references'], [])

    def test_failed_attempt_can_expose_jobs_even_without_a_candidate_archive(self):
        result = self.observe()
        self.assertEqual(result['stages']['publish']['conclusion'], 'failure')
        self.assertEqual(result['artifact_visibility'], 'no_visible_artifacts')
        self.assertEqual(result['checkpoints'], {})


if __name__ == '__main__':
    unittest.main()
