"""Authenticate zero-allowance runtime history without retiring source owners."""
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import zipfile

import yaml

from tests import test_release_candidate
from tools import release_candidate as c, release_attempt_history as history
from tools import runtime_assembly_history as runtime


ROOT = Path(__file__).resolve().parents[1]


def zip_bytes(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as packet:
        for name, raw in members.items():
            packet.writestr(name, raw)
    return output.getvalue()


class RuntimeAssemblyHistory(unittest.TestCase):
    def setUp(self):
        fixture = test_release_candidate.CandidateLifecycleTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root = fixture, fixture.root
        self.workflow = yaml.safe_load((ROOT / history.WORKFLOW).read_text(encoding='utf-8'))
        for name in (history.WORKFLOW, '.github/workflows/pages.yml'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        fixture.policy['dependency_groups'] = {
            group: {'patterns': patterns, 'excluded': []} for group, patterns in {
                'source': ['scripts/parser.py', 'config/source.json'], 'teams': ['scripts/teams.py'],
                'semantic': ['tools/vectors.mjs'], 'runtime': ['index.html'],
                'validation': ['tools/validator.py']}.items()}
        c.write_json(self.root / c.POLICY, fixture.policy)
        fixture.commit()
        self.event_sha = c.git(self.root, 'rev-parse', 'HEAD')
        parent = fixture.create()
        (self.root / 'index.html').write_text('<main>runtime C</main>', encoding='utf-8')
        fixture.commit()
        self.bundle = Path(fixture.temp.name) / 'runtime-candidate'
        self.native = c.create(self.root, self.bundle, parent=fixture.bundle, run_id='200', attempt='1')
        self.run = {'id': 200, 'run_attempt': 1, 'path': history.WORKFLOW, 'head_branch': 'main',
                    'head_sha': self.event_sha, 'event': 'workflow_dispatch',
                    'status': 'completed', 'conclusion': 'failure'}
        self.attempts = {1: deepcopy(self.run)}
        self.jobs = {1: self.job_rows(1)}
        self.payloads, self.artifacts = {}, []
        self.candidate_artifact = self.artifact(20, 'candidate-' + self.native['candidate_id'],
            zip_bytes({'candidate.json': c.encoded(self.native)} | {
                'files/' + name: (self.bundle / 'files' / name).read_bytes() for name in self.native['files']}))
        self.plan = {'stage': 'reuse', 'candidate_id': parent['candidate_id'], 'candidate_run': '123',
                     'release_sha': self.native['assembly_sha']}
        self.plan_artifact = self.artifact(21, 'release-plan-1', zip_bytes({'release-plan.json': c.encoded(self.plan)}))
        self.inventory = patch.object(history, 'run_artifacts', side_effect=lambda *a, **k: self.artifacts)
        self.inventory.start()
        self.addCleanup(self.inventory.stop)
        workflow_names = patch.object(history, 'workflow_job_names', return_value=frozenset(self.workflow['jobs']))
        workflow_names.start()
        self.addCleanup(workflow_names.stop)

    def artifact(self, identifier, name, raw):
        row = {'id': identifier, 'name': name, 'digest': 'sha256:' + c.digest(raw), 'expired': False,
               'workflow_run': {'id': self.run['id'], 'head_sha': self.event_sha, 'head_branch': 'main'}}
        self.artifacts.append(row)
        self.payloads[identifier] = raw
        return row

    def job_rows(self, attempt, *, downstream=False):
        rows = []
        for index, name in enumerate(self.workflow['jobs'], 1):
            if downstream and name not in history.DOWNSTREAM:
                continue
            conclusion = ('success' if name in ('plan', 'assemble', 'candidate', 'closeout') else
                          'failure' if name == 'validate' else 'skipped')
            row = {'id': attempt * 1000 + index, 'run_id': 200, 'run_attempt': attempt,
                   'name': name, 'head_sha': self.event_sha, 'head_branch': 'main',
                   'status': 'completed', 'conclusion': conclusion, 'steps': []}
            if name == 'assemble':
                for number, step in enumerate(self.workflow['jobs']['assemble']['steps'], 1):
                    guard = step.get('if', '')
                    guarded = "needs.plan.outputs.stage != 'reuse'" in guard or 'inputs.qualification_pilot' in guard
                    row['steps'].append({'name': step.get('name', 'Action ' + str(number)), 'number': number,
                        'status': 'completed', 'conclusion': 'skipped' if guarded else 'success'})
            rows.append(row)
        return rows

    def api(self, path):
        if match := re.fullmatch(r'actions/artifacts/([0-9]+)/zip', path):
            return self.payloads[int(match[1])]
        if match := re.fullmatch(r'actions/runs/200/attempts/([0-9]+)', path):
            return json.dumps(self.attempts[int(match[1])])
        if match := re.fullmatch(r'actions/runs/200/attempts/([0-9]+)/jobs\?per_page=100&page=1', path):
            rows = self.jobs[int(match[1])]
            return json.dumps({'jobs': rows, 'total_count': len(rows)})
        self.fail('Unexpected API request: ' + path)

    def retire(self):
        return runtime.no_generation_allowance(self.root, 'owner/repo', self.run, self.artifacts, api=self.api)

    def repack(self, value=None, *, extra=None):
        value = self.native if value is None else value
        value['candidate_id'] = c.digest(c.encoded({k: v for k, v in value.items() if k != 'candidate_id'}))
        members = {'candidate.json': c.encoded(value)} | {
            'files/' + name: (self.bundle / 'files' / name).read_bytes() for name in value['files']}
        members.update(extra or {})
        raw = zip_bytes(members)
        self.candidate_artifact['name'] = 'candidate-' + value['candidate_id']
        self.candidate_artifact['digest'] = 'sha256:' + c.digest(raw)
        self.payloads[self.candidate_artifact['id']] = raw

    def test_native_runtime_classification_preserves_event_assembly_and_science_identities(self):
        self.assertNotEqual(self.native['assembly_sha'], self.event_sha)
        self.assertNotEqual(self.native['generation_sha'], self.event_sha)
        self.assertTrue(self.retire())

    def test_later_different_science_cannot_create_an_allowance_in_this_unpaid_run(self):
        # This helper classifies R's own allowance; the independent source
        # producer still requires its existing accounting and publication proof.
        (self.root / 'data/opportunities.js').write_text('later source repair', encoding='utf-8')
        self.fixture.commit()
        self.assertTrue(self.retire())

    def test_paid_or_source_state_defers_to_existing_owner_proof(self):
        self.artifacts.append({'name': 'generation-spend-reservation-200-1'})
        self.assertFalse(self.retire())

    def test_missing_extra_or_tampered_native_bytes_cannot_retire(self):
        self.repack(extra={'files/private-provider-cache.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'complete candidate members'):
            self.retire()

    def test_generation_claim_must_match_actual_native_file_hash(self):
        value = deepcopy(self.native)
        value['generation_files']['data/opportunities.js'] = '0' * 64
        self.repack(value)
        with self.assertRaisesRegex(ValueError, 'generated member binding'):
            self.retire()

    def test_artifact_event_branch_and_digest_are_authenticated(self):
        for mutate in ('branch', 'digest'):
            with self.subTest(mutate=mutate):
                previous = deepcopy(self.candidate_artifact)
                if mutate == 'branch':
                    self.candidate_artifact['workflow_run']['head_branch'] = 'topic'
                else:
                    self.candidate_artifact['digest'] = 'sha256:' + '0' * 64
                with self.assertRaisesRegex(ValueError, 'artifact identity|artifact digest'):
                    self.retire()
                self.candidate_artifact.clear()
                self.candidate_artifact.update(previous)

    def test_paid_guard_running_missing_steps_and_extra_producers_do_not_retire(self):
        assemble = next(row for row in self.jobs[1] if row['name'] == 'assemble')
        paid = next(row for row in assemble['steps'] if row['name'] == 'Restore the logical spend checkpoint')
        paid['conclusion'] = 'success'
        with self.assertRaisesRegex(ValueError, 'provider, allowance, task or team step ran'):
            self.retire()
        paid['conclusion'] = 'skipped'
        missing = assemble['steps'].pop()
        with self.assertRaisesRegex(ValueError, 'provider, allowance, task or team step ran'):
            self.retire()
        assemble['steps'].append(missing)
        next(row for row in self.jobs[1] if row['name'] == 'catalog-reconcile')['conclusion'] = 'success'
        self.assertFalse(self.retire())

    def test_reuse_plan_binding_competing_candidates_and_unknown_vouchers_hold(self):
        self.plan['release_sha'] = '0' * 40
        raw = zip_bytes({'release-plan.json': c.encoded(self.plan)})
        self.payloads[self.plan_artifact['id']] = raw
        self.plan_artifact['digest'] = 'sha256:' + c.digest(raw)
        with self.assertRaisesRegex(ValueError, 'reuse plan binding'):
            self.retire()
        self.plan['release_sha'] = self.native['assembly_sha']
        raw = zip_bytes({'release-plan.json': c.encoded(self.plan)})
        self.payloads[self.plan_artifact['id']] = raw
        self.plan_artifact['digest'] = 'sha256:' + c.digest(raw)
        extra = self.artifact(22, 'catalog-candidate-recovery-200-2', b'untrusted voucher')
        with self.assertRaisesRegex(ValueError, 'unknown zero-spend artifact'):
            self.retire()
        self.artifacts.remove(extra)
        self.artifact(23, 'candidate-' + '0' * 64, b'competing candidate')
        with self.assertRaisesRegex(ValueError, 'competing or invalid candidate'):
            self.retire()

    def test_downstream_only_later_attempt_keeps_original_producer(self):
        self.run['run_attempt'] = 2
        self.attempts[2] = deepcopy(self.run)
        self.jobs[2] = self.job_rows(2, downstream=True)
        self.assertTrue(self.retire())
        self.jobs[2].append(next(row for row in self.job_rows(2) if row['name'] == 'assemble'))
        with self.assertRaisesRegex(ValueError, 'one complete native runtime producer'):
            self.retire()


if __name__ == '__main__':
    unittest.main()
