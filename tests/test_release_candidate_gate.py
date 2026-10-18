"""Evaluate the release owner's actual conditions across producer/resume paths."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOWNSTREAM = ('candidate', 'validate', 'publish', 'pages', 'verify-live')
RESUME_STAGE_GUARD = ("(needs.plan.outputs.stage == 'validate' || needs.plan.outputs.stage == 'publish' || "
                      "needs.plan.outputs.stage == 'verify')")
PRODUCER_STAGES = {
    'generate': 'generate', 'reuse': 'assemble', 'teams': 'assemble', 'backfill': 'assemble',
    'catalog-reconcile': 'catalog-reconcile', 'catalog-correction': 'catalog-correction',
    'catalog-projection': 'catalog-correction', 'program-area-revalidation': 'program-area-revalidation',
    'catalog-source-recovery': 'catalog-source-recovery', 'catalog-access-correction': 'catalog-access-correction',
    'catalog-identity-correction': 'catalog-identity-correction', 'catalog-url-correction': 'catalog-url-correction',
}


@lru_cache(maxsize=1)
def _parsed_workflow(raw):
    return yaml.safe_load(raw)['jobs']


def workflow_jobs():
    return deepcopy(_parsed_workflow((ROOT / '.github/workflows/refresh-opportunities.yml').read_text()))


def skipped_needs(stage='generate'):
    needs = {name: {'result': 'skipped', 'outputs': {}} for name in workflow_jobs()}
    needs['plan'] = {'result': 'success', 'outputs': {'stage': stage,
        'candidate_id': 'a' * 64, 'candidate_run': '123', 'release_sha': 'b' * 40}}
    return needs


def evaluate_condition(expression, needs, *, cancelled=False):
    """Evaluate only the small expression vocabulary used by these actual gates."""
    expression = expression.strip()
    if expression.startswith('${{') and expression.endswith('}}'):
        expression = expression[3:-2].strip()
    def reference(match):
        value = needs.get(match[1], {})
        for part in match[2].split('.'):
            value = value.get(part, '') if isinstance(value, dict) else ''
        return repr(value)
    expression = re.sub(r'needs\.([A-Za-z0-9_-]+)\.(result|outputs\.[A-Za-z0-9_-]+)', reference, expression)
    expression = expression.replace('always()', 'True').replace('cancelled()', repr(cancelled))
    expression = expression.replace('success()', repr(all(value['result'] == 'success' for value in needs.values())))
    expression = expression.replace('failure()', repr(any(value['result'] == 'failure' for value in needs.values())))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    return bool(eval(expression.strip(), {'__builtins__': {}, 'fromJSON': json.loads,
                                         'contains': lambda values, value: value in values}))


def evaluate_job_condition(job, needs, *, cancelled=False):
    dependencies = job.get('needs', [])
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    selected = {name: needs[name] for name in dependencies}
    expression = job.get('if', 'success()')
    # Actions implicitly adds success() unless a status-check function is
    # explicit. A stage match alone cannot bypass a failed source preflight.
    if not re.search(r'\b(always|success|failure|cancelled)\s*\(', expression):
        if not all(value['result'] == 'success' for value in selected.values()):
            return False
    return evaluate_condition(expression, selected, cancelled=cancelled)


def evaluate_downstream(needs, *, jobs=None, outcomes=None):
    jobs = workflow_jobs() if jobs is None else jobs
    outcomes = {} if outcomes is None else outcomes
    result = deepcopy(needs)
    for name in DOWNSTREAM:
        allowed = evaluate_job_condition(jobs[name], result)
        result[name]['result'] = outcomes.get(name, 'success') if allowed else 'skipped'
        if name == 'publish' and result[name]['result'] == 'success':
            result[name]['outputs']['merge_sha'] = 'c' * 40
    return result


class CandidateStageGates(unittest.TestCase):
    def conclusions(self, needs, **options):
        result = evaluate_downstream(needs, **options)
        return {name: result[name]['result'] for name in DOWNSTREAM}

    def test_failed_preflight_cannot_select_or_publish_the_old_protected_candidate(self):
        jobs = workflow_jobs()
        needs = skipped_needs()
        self.assertTrue(evaluate_job_condition(jobs['sam-preflight'], needs))
        needs['sam-preflight']['result'] = 'failure'
        for producer in jobs['candidate']['needs']:
            if producer != 'plan':
                self.assertFalse(evaluate_job_condition(jobs[producer], needs), producer)
        self.assertEqual(self.conclusions(needs), {name: 'skipped' for name in DOWNSTREAM})

    def test_every_successful_supported_producer_reaches_normal_downstream_gates(self):
        for stage, producer in PRODUCER_STAGES.items():
            with self.subTest(stage=stage):
                needs = skipped_needs(stage)
                needs[producer] = {'result': 'success', 'outputs': {'candidate_id': 'd' * 64}}
                self.assertEqual(self.conclusions(needs), {name: 'success' for name in DOWNSTREAM})

    def test_skipped_failed_or_cancelled_producer_cannot_fall_back_to_prior_catalog(self):
        for stage, producer in PRODUCER_STAGES.items():
            for outcome in ('skipped', 'failure', 'cancelled'):
                with self.subTest(stage=stage, outcome=outcome):
                    needs = skipped_needs(stage); needs[producer]['result'] = outcome
                    self.assertEqual(self.conclusions(needs), {name: 'skipped' for name in DOWNSTREAM})

    def test_only_named_resume_stages_can_run_without_a_producer(self):
        expected = {'validate': {'candidate', 'validate'},
                    'publish': set(DOWNSTREAM), 'verify': {'candidate', 'validate', 'verify-live'}}
        for stage, allowed in expected.items():
            with self.subTest(stage=stage):
                result = self.conclusions(skipped_needs(stage))
                self.assertEqual({name for name, conclusion in result.items() if conclusion == 'success'}, allowed)
        for stage in ('noop', 'auto', 'unknown', ''):
            with self.subTest(stage=stage):
                self.assertEqual(self.conclusions(skipped_needs(stage)), {name: 'skipped' for name in DOWNSTREAM})

    def test_resume_fallback_still_rejects_a_failed_or_cancelled_producer_or_plan(self):
        for stage in ('validate', 'publish', 'verify'):
            for failed in ('plan', *set(PRODUCER_STAGES.values())):
                for outcome in ('failure', 'cancelled'):
                    with self.subTest(stage=stage, failed=failed, outcome=outcome):
                        needs = skipped_needs(stage); needs[failed]['result'] = outcome
                        self.assertEqual(self.conclusions(needs), {name: 'skipped' for name in DOWNSTREAM})

    def test_validation_publication_and_pages_failures_stop_their_dependent_stages(self):
        for stage in ('generate', 'publish'):
            needs = skipped_needs(stage)
            if stage == 'generate':
                needs['generate']['result'] = 'success'
            for failed, blocked in (('candidate', set(DOWNSTREAM[1:])),
                                    ('validate', {'publish', 'pages', 'verify-live'}),
                                    ('publish', {'pages', 'verify-live'}),
                                    ('pages', {'verify-live'})):
                with self.subTest(stage=stage, failed=failed):
                    result = self.conclusions(needs, outcomes={failed: 'failure'})
                    self.assertEqual(result[failed], 'failure')
                    self.assertTrue(all(result[name] == 'skipped' for name in blocked))


if __name__ == '__main__':
    unittest.main()
