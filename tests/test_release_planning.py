"""Supported release-selection and incremental team contracts; no provider calls."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import plan_release as planner, team_maintenance as maintenance
from tools import release_dependencies as dependencies
from tools.offline_ai import Ledger, config
from scripts import build_opportunity_teams as teams


class ReleasePlanning(unittest.TestCase):
    def test_newest_failed_validation_is_not_hidden_by_an_older_pass(self):
        candidate = 'a' * 64
        rows = {'artifacts': [{'id': index, 'name': f'validation-{candidate}-1', 'expired': False,
                              'workflow_run': {'id': index}} for index in (2, 1)]}
        def fetch(repository, run, name, target):
            target.mkdir(parents=True)
            (target / 'validation-report.json').write_text(json.dumps({'candidate_id': candidate, 'failures': ['notice_projection']}))
        with tempfile.TemporaryDirectory() as directory, patch('tools.offline_ai_checkpoint.api', return_value=json.dumps(rows)), \
                patch('tools.fetch_release_artifact.fetch', side_effect=fetch) as download:
            run, result = planner.latest_report('owner/repo', candidate, 'validation', directory)
        self.assertEqual(run, '2')
        self.assertEqual(result['failures'], ['notice_projection'])
        self.assertEqual(download.call_count, 1)

    def test_workflow_pins_jobs_and_limits_generation_credentials_and_pilot(self):
        import yaml
        workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / '.github/workflows/refresh-opportunities.yml').read_text(encoding='utf-8'))
        jobs = workflow['jobs']
        for name, job in jobs.items():
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/checkout') and name != 'plan':
                    self.assertEqual(step['with']['ref'], '${{ needs.plan.outputs.release_sha }}')
                for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
                    if key in step.get('env', {}):
                        self.assertIn(name, ('generate', 'assemble'))
                        self.assertTrue('build_opportunity_teams' in step.get('run', '') or 'run_budgeted_documents' in step.get('run', ''))
        for step in jobs['assemble']['steps']:
            if '--generate' in step.get('run', ''):
                self.assertIn("needs.plan.outputs.stage != 'reuse'", step['if'])
        self.assertEqual(config()['pilot_max_scopes'], 5)
        self.assertEqual(config()['budgets_usd']['pilot'], 2)

    def test_coverage_distinguishes_unknown_age_and_overlap_from_unique_records(self):
        from tools import release_coverage as coverage
        records = [{'opportunity_id': 'a', 'document_evidence_status': 'pending'},
                   {'opportunity_id': 'b', 'document_evidence_status': 'current'}]
        evidence = {'records': {'a': {'parser_pending': {'reason': 'source_required', 'changed_families': ['amount', 'deadline'],
                                                        'withheld_count': 2}, 'structure_identity': 'identity'}}}
        with patch.object(coverage, '_load_catalog', return_value=records), \
                patch.object(coverage.c, 'read_json', side_effect=[evidence, {'queue_counts': {'maintenance': 0, 'backfill': 12}}]):
            result = coverage.report(Path('unused'), {'source_states': {'a': 'pending', 'b': 'current'}})
        self.assertEqual(result['unique_affected_records'], 1)
        self.assertEqual(sum(result['overlapping_field_categories'].values()), 2)
        self.assertEqual(result['source_transitions'], {})
        self.assertIsNone(result['oldest_pending_age_days'])
        self.assertIsNone(result['safe_reparseable_from_available_structure'])

    def test_least_cost_and_exact_resume(self):
        base = dict(event='push', verified=True, receipt_current=True)
        self.assertEqual(planner.decide({}, **base), 'noop')
        self.assertEqual(planner.decide({'validation': ['tests/example.py']}, **(base | {'receipt_current': False})), 'validate')
        self.assertEqual(planner.decide({'runtime': ['index.html']}, runtime_changed=True, **base), 'reuse')
        self.assertEqual(planner.decide({'teams': ['config/offline_ai.json']}, **base), 'teams')
        for group in ('source', 'semantic'):
            self.assertEqual(planner.decide({group: ['changed']}, **base), 'generate')
            for requested in ('validate', 'publish', 'verify'):
                self.assertEqual(planner.decide({group: ['changed']}, requested=requested, **base), requested)
        self.assertEqual(planner.decide({}, **(base | {'event': 'schedule'})), 'generate')
        self.assertEqual(planner.decide({}, **(base | {'verified': False})), 'publish')
        self.assertEqual(planner.decide({}, published=True, **(base | {'verified': False})), 'verify')
        self.assertEqual(planner.decide({}, published=True, **(base | {'verified': False, 'receipt_current': False})), 'verify')
        self.assertEqual(planner.decide({}, published=False, **(base | {'verified': False})), 'publish')

    def test_group_inventory_is_root_scoped_and_comments_are_not_semantics(self):
        self.assertTrue(dependencies.matches('scripts/sources/adapters/nasa.py', 'scripts/sources/**/*.py'))
        self.assertTrue(dependencies.matches('scripts/sources/merge.py', 'scripts/sources/**/*.py'))
        self.assertFalse(dependencies.matches('feeds/index.html', '*.html'))
        self.assertEqual(dependencies.semantic_bytes('x.py', b'"""old"""\nx = 1 # comment\n'),
                         dependencies.semantic_bytes('x.py', b'"""new"""\nx = 1\n'))
        self.assertNotEqual(dependencies.semantic_bytes('x.py', b'x = 1'), dependencies.semantic_bytes('x.py', b'x = 2'))

    def test_actual_git_main_advancement_and_dependency_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = {'generated': [], 'package': [], 'dependency_groups': {
                key: {'patterns': [name], 'excluded': []} for key, name in
                [('source', 'parser.py'), ('teams', 'team.py'), ('semantic', 'vectors.py'),
                 ('runtime', 'index.html'), ('validation', 'validator.py')]}}
            policy['dependency_groups']['source']['patterns'] += ['tools/run_budgeted_documents.py', 'tools/offline_spend.py']
            policy['dependency_groups']['teams']['patterns'] += ['tools/offline_ai.py', 'config/offline_ai.json']
            files = {'config/release_dependencies.json': json.dumps(policy), 'parser.py': 'x=1', 'team.py': 'x=1',
                     'vectors.py': 'x=1', 'index.html': 'a', 'validator.py': 'x=1',
                     'tools/run_budgeted_documents.py': 'x=1', 'tools/offline_spend.py': 'x=1', 'tools/offline_ai.py': 'x=1',
                     'config/offline_ai.json': json.dumps({'budgets_usd': {'maintenance': 2}, 'max_requests': 300,
                                                         'prices_per_million': {}, 'production_route': 'sonnet'}),
                     '.github/workflows/refresh-opportunities.yml': 'jobs:\n  generate:\n    steps:\n      - run: python -m scripts.build_catalog --min-records 1000\n'}
            for name, content in files.items():
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
            git('add', '--', *files); git('commit', '-m', 'baseline')
            sha = git('rev-parse', 'HEAD')
            baseline = dependencies.snapshot(root, sha)
            for name, group in [('validator.py', 'validation'), ('index.html', 'runtime'), ('team.py', 'teams'),
                                ('parser.py', 'source'), ('vectors.py', 'semantic'),
                                ('tools/run_budgeted_documents.py', 'source'), ('tools/offline_spend.py', 'source'),
                                ('tools/offline_ai.py', 'teams')]:
                (root / name).write_text('x=2')
                changes = dependencies.changed_groups(baseline, dependencies.snapshot(root))
                self.assertEqual(set(changes), {group})
                (root / name).write_text(files[name])
            settings = json.loads(files['config/offline_ai.json'])
            (root / 'config/offline_ai.json').write_text(json.dumps(settings | {'production_route': 'luna'}))
            self.assertEqual(set(dependencies.changed_groups(baseline, dependencies.snapshot(root))), {'teams'})
            (root / 'config/offline_ai.json').write_text(json.dumps(settings | {'max_requests': 200}))
            self.assertEqual(set(dependencies.changed_groups(baseline, dependencies.snapshot(root))), {'source', 'teams'})
            (root / 'config/offline_ai.json').write_text(files['config/offline_ai.json'])
            (root / 'AGENTS.md').write_text('Changed operating prose')
            self.assertEqual(dependencies.changed_groups(baseline, dependencies.snapshot(root)), {})
            (root / '.github/workflows/refresh-opportunities.yml').write_text(files['.github/workflows/refresh-opportunities.yml'].replace('1000', '900'))
            self.assertEqual(set(dependencies.changed_groups(baseline, dependencies.snapshot(root))), {'source'})

    def test_pages_checkpoint_is_bound_to_publication_artifact_attempt(self):
        candidate = 'a' * 64
        artifact = {'id': 9, 'name': f'publication-{candidate}-2', 'expired': False, 'workflow_run': {'id': 123}}
        def download(repository, run, name, target):
            target.mkdir(parents=True)
            for filename in ('publication.json', 'validation.json'):
                (target / filename).write_text('{}')
        for conclusion, expected in [('success', True), ('failure', False)]:
            def api(repository, path):
                if path.startswith('actions/artifacts?'):
                    return json.dumps({'artifacts': [artifact]})
                self.assertIn('actions/runs/123/attempts/2/jobs?', path)
                return json.dumps({'jobs': [{'name': 'pages / deploy', 'conclusion': conclusion}]})
            with tempfile.TemporaryDirectory() as directory, patch('tools.offline_ai_checkpoint.api', side_effect=api), \
                    patch('tools.fetch_release_artifact.fetch', side_effect=download):
                run, evidence = planner.latest_report('owner/repo', candidate, 'publication', directory)
            self.assertEqual((run, evidence['attempt'], evidence['pages_complete']), ('123', '2', expected))

    def test_provider_switch_preserves_proven_negative_and_original_provenance(self):
        scope = {'id': 'supported', 'source_fingerprint': 'source'}
        legacy = config()['legacy_team_contracts'][0]
        old_key = teams.content_hash([legacy['pipeline_hash'], 'source', 'claims', None])
        model = {'opportunities': [], 'generation_attempts': {'supported': {'key': old_key, 'state': 'not_specific',
                 'response_contract': teams.RESPONSE_VERSION}}}
        maintenance.migrate_legacy(model, [scope], 'claims', {'claim': 'revision1'})
        attempt = model['generation_attempts']['supported']
        self.assertEqual(attempt['legacy_provenance']['key'], old_key)
        with patch('tools.team_provider.routes', return_value={'decomposition': {'model': 'different'}}):
            self.assertEqual(attempt['key'], maintenance.decision_key(scope, attempt, {'unrelated': 'changed'}))
        self.assertNotEqual(attempt['key'], maintenance.decision_key(scope | {'source_fingerprint': 'amended'}, attempt, {}))

    def test_unrelated_claim_revision_does_not_repeat_negative_assessment(self):
        scope = {'id': 'scope', 'source_fingerprint': 'source'}
        attempt = {'state': 'insufficient_evidence', 'claim_dependencies': ['relevant']}
        before = maintenance.decision_key(scope, attempt, {'relevant': 'r1', 'other': 'r1'})
        self.assertEqual(before, maintenance.decision_key(scope, attempt, {'relevant': 'r1', 'other': 'r2'}))
        self.assertNotEqual(before, maintenance.decision_key(scope, attempt, {'relevant': 'r2', 'other': 'r1'}))
        self.assertNotEqual(before, maintenance.decision_key(scope, attempt, {'relevant': 'r1', 'other': 'r1', 'new': 'r1'}))

    def test_maintenance_never_silently_consumes_historical_backfill(self):
        old = {'id': 'old', 'source_fingerprint': 'a'}
        new = {'id': 'new', 'source_fingerprint': 'b'}
        previous = {'scopes': {'old': 'a'}, 'claims': {}}
        due, backfill, reasons = maintenance.queues([old, new], {}, {}, previous, {})
        self.assertEqual([x['id'] for x in due], ['new'])

        self.assertEqual([x['id'] for x in backfill], ['old'])
        deferred = {'new': {'mode': 'pilot', 'state': 'deferred'}}
        previous['scopes']['new'] = 'b'
        due, _, _ = maintenance.queues([old, new], {}, deferred, previous, {})
        self.assertEqual([x['id'] for x in due], ['new'])

    def test_real_terminal_review_abbreviation_requires_authenticated_full_commit(self):
        from tools import wait_release_review as review
        head = 'f0b801d0d33fb16030d9dfee52ad84889e19ce39'
        body = "Codex Review: Didn't find any major issues.\n\n**Reviewed commit:** `f0b801d0d3`"
        with patch.object(review, 'api', return_value={'sha': head}) as api:
            self.assertTrue(review.reviewed_head('owner/repo', body, head))
            api.assert_called_once_with('repos/owner/repo/commits/f0b801d0d3')
        with patch.object(review, 'api', return_value={'sha': '0' * 40}):
            self.assertFalse(review.reviewed_head('owner/repo', body, head))

    def test_legacy_failed_maintenance_survives_snapshot_advancement_without_reassessment(self):
        scope = {'id': '347026', 'source_fingerprint': 'changed'}
        historical = {'id': 'historical', 'source_fingerprint': 'unchanged'}
        previous = {'scopes': {'347026': 'old', 'historical': 'unchanged'}}
        current = {'scopes': {'347026': 'changed', 'historical': 'unchanged'}}
        original = {'state': 'rejected_evidence', 'key': 'original-input', 'stage': 'decomposition',
                    'retry_after': 9999999999, 'response_contract': teams.RESPONSE_VERSION}
        attempts = {'347026': dict(original)}
        due, backfill, reasons = maintenance.queues([scope, historical], {}, attempts, previous, current)
        self.assertEqual(due, [scope])
        self.assertEqual(backfill, [historical])
        maintenance.preserve_deferred(attempts, due, [], reasons, 'maintenance', 'science', lambda s: 'new-input')
        self.assertEqual({key: attempts['347026'][key] for key in original}, original)
        due, backfill, _ = maintenance.queues([scope, historical], {}, attempts, current, current)
        self.assertEqual(due, [scope])
        self.assertEqual(backfill, [historical])

    def test_exact_completed_report_recovers_maintenance_but_not_historical_work(self):
        report = {'status': 'completed', 'generation_requested': True, 'mode': 'pilot',
                  'input_generation': 'pinned', 'response_contract': teams.RESPONSE_VERSION,
                  'queue_reasons': {'347026': 'source_changed', 'old': 'historical_unassessed_backfill'}}
        scope = {'id': '347026', 'source_fingerprint': 'current'}
        old = {'id': 'old', 'source_fingerprint': 'old'}
        current = {'scopes': {'347026': 'current', 'old': 'old'}}
        reasons = maintenance.retained_queue_reasons(report, 'pinned', teams.RESPONSE_VERSION)
        self.assertEqual(reasons, {'347026': 'source_changed'})
        due, backfill, _ = maintenance.queues([scope, old], {}, {}, current, current, reasons)
        self.assertEqual((due, backfill), ([scope], [old]))
        for changed in ({'status': 'starting'}, {'generation_requested': False}, {'mode': 'backfill'},
                        {'input_generation': 'different'}, {'response_contract': 'different'}):
            self.assertEqual(maintenance.retained_queue_reasons(report | changed, 'pinned', teams.RESPONSE_VERSION), {})

    def test_queue_retention_preserves_refusal_and_actual_backfill_attempt_provenance(self):
        scope = {'id': 'scope', 'source_fingerprint': 'same'}
        original = {'state': 'provider_refusal', 'mode': 'backfill', 'key': 'refused-input',
                    'next_action': 'human_provider_configuration', 'retry_after': 9999999999}
        attempts = {'scope': dict(original)}
        maintenance.preserve_deferred(attempts, [scope], [], {'scope': 'source_changed'},
                                      'maintenance', 'science', lambda s: 'different')
        self.assertEqual({key: attempts['scope'][key] for key in original}, original)
        self.assertEqual(attempts['scope']['maintenance_pending']['next_action'], 'human_provider_configuration')


if __name__ == '__main__':
    unittest.main()
