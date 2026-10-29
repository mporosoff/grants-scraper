"""Workflow compilation stays inside the existing required Python check."""
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'


class WorkflowCompilationContracts(unittest.TestCase):
    def test_job_environment_does_not_reference_runner_only_context(self):
        # Runner context exists only after job allocation; using it here makes
        # GitHub reject the entire workflow before creating any jobs.
        for path in sorted(WORKFLOWS.glob('*.yml')):
            workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
            for name, job in workflow.get('jobs', {}).items():
                with self.subTest(workflow=path.name, job=name):
                    for value in job.get('env', {}).values():
                        expressions = re.findall(r'\$\{\{(.*?)\}\}', str(value), re.S)
                        self.assertFalse(any(re.search(r'\brunner\s*\.', expression)
                                             for expression in expressions))

    def test_reconciliation_state_is_initialized_before_every_consumer(self):
        workflow = yaml.safe_load((WORKFLOWS / 'refresh-opportunities.yml').read_text(encoding='utf-8'))
        job = workflow['jobs']['catalog-reconcile']
        self.assertNotIn('CATALOG_RECONCILE_STATE', job.get('env', {}))
        setup = [step for step in job['steps'] if
                 'CATALOG_RECONCILE_STATE=$RUNNER_TEMP/reconcile-state' in step.get('run', '')]
        self.assertEqual(len(setup), 1)
        self.assertEqual(setup[0]['shell'], 'bash')
        self.assertIn('>> "$GITHUB_ENV"', setup[0]['run'])
        self.assertNotIn('if', setup[0])
        consumers = [step for step in job['steps'] if '$CATALOG_RECONCILE_STATE' in step.get('run', '')]
        self.assertTrue(consumers)
        for consumer in consumers:
            self.assertLess(job['steps'].index(setup[0]), job['steps'].index(consumer))

    def test_required_python_check_verifies_pinned_linter_before_execution(self):
        workflow = yaml.safe_load((WORKFLOWS / 'tests.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['python']['steps']
        lint = next(step for step in steps if step.get('name') == 'Validate GitHub Actions workflows')
        self.assertNotIn('if', lint)
        self.assertNotIn('continue-on-error', lint)
        self.assertEqual(lint['shell'], 'bash')
        command = lint['run']
        self.assertIn('set -euo pipefail', command)
        self.assertIn('https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz', command)
        self.assertIn('8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8', command)
        self.assertIn('--max-time 60', command)
        self.assertIn('--retry-max-time 120', command)
        self.assertLess(command.index('sha256sum --check'), command.index('tar -xzf'))
        self.assertLess(command.index('tar -xzf'), command.index('/actionlint" -shellcheck= -pyflakes='))
        validation = next(step for step in steps if 'tools.run_refresh_validation' in step.get('run', ''))
        self.assertLess(steps.index(lint), steps.index(validation))

    def test_source_repair_selector_is_identical_in_plan_and_execution(self):
        workflow = yaml.safe_load((WORKFLOWS / 'refresh-opportunities.yml').read_text(encoding='utf-8'))
        selector = workflow[True]['workflow_dispatch']['inputs']['reconcile_source']
        self.assertEqual(selector['default'], 'sam-gov')
        self.assertEqual(set(selector['options']), {'sam-gov', 'darpa-iarpa'})
        plan = next(step for step in workflow['jobs']['plan']['steps'] if step.get('id') == 'plan')
        repair = workflow['jobs']['catalog-reconcile']
        expected = "${{ inputs.reconcile_source || 'sam-gov' }}"
        self.assertEqual(plan['env']['CATALOG_RECONCILE_SOURCE'], expected)
        self.assertEqual(repair['env']['CATALOG_RECONCILE_SOURCE'], expected)
        self.assertEqual(repair['if'], "needs.plan.outputs.stage == 'catalog-reconcile'")
        for name, job in workflow['jobs'].items():
            if name != 'catalog-reconcile':
                self.assertNotIn('CATALOG_RECONCILE_SOURCE', job.get('env', {}))


if __name__ == '__main__':
    unittest.main()
