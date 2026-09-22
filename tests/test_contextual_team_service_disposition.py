"""Real SQLite disposition CAS; synthetic external evidence, no network calls."""
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_contextual_team_checkpoint_recovery as recovery_fixture
from tools import contextual_team_service_disposition as service
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity


class Database:
    def __init__(self, path):
        self.path = path
        self.writes = 0

    def query(self, sql):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            # Exactly one INSERT remains one SQLite statement, with all trigger
            # effects committed together. The SELECT inventory is read-only.
            if sql.startswith('INSERT'):
                db.execute(sql); self.writes += 1
                return [[]]
            return [[dict(r) for r in db.execute(s)] for s in sql.split(';') if s.strip()]

    def snapshot(self):
        return self.query(service.snapshot_sql())


class ServiceDisposition(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'service.sqlite'
        self.store = Database(self.path); self.p = service.plan()
        self.evidence = {'version': service.VERSION, 'plan_sha256': identity(self.p),
            'original_row_identity': self.p['original_row_identity'], 'proof': 'synthetic authenticated proof'}
        with closing(sqlite3.connect(self.path)) as db, db:
            for filename in ('0005_contextual_validation_jobs.sql', '0006_contextual_trial_controls.sql'):
                db.executescript((service.MIGRATION.parent/filename).read_text())
            row = self.p['original_row']
            db.execute('INSERT INTO contextual_validation_jobs (' + ','.join(row) + ') VALUES ('
                + ','.join('?' for _ in row) + ')', tuple(row.values()))
            db.execute('INSERT INTO contextual_trial_controls VALUES (?,1,0,?)', (row['release_id'], 'synthetic control time'))
            # Installing the migration itself must not modify an existing job.
            db.executescript(service.MIGRATION.read_text())
        self.before = self.store.snapshot()
        self.assertEqual(self.before[0], [self.p['original_row']])
        self.network = patch('socket.socket.connect', side_effect=AssertionError('no_network'))
        self.network.start(); self.addCleanup(self.network.stop)

    def sql(self, sql, values=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql, values)

    def test_default_only_prepares_and_explicit_execute_preserves_exact_original(self):
        result = service.execute_prepared(self.evidence, self.store)
        self.assertEqual(result['status'], 'prepared_only'); self.assertEqual(self.store.writes, 0)
        self.assertEqual(self.store.snapshot(), self.before)
        calls = []
        result = service.execute_prepared(self.evidence, self.store, execute=True, revalidate=lambda: calls.append('fresh'))
        self.assertEqual(calls, ['fresh']); self.assertEqual(result['status'], 'disposed')
        after = self.store.snapshot()
        self.assertEqual(after[0], [service.released_row()]); self.assertEqual(after[1], self.before[1])
        self.assertEqual(json.loads(after[3][0]['original_row_json']), self.p['original_row'])
        self.assertEqual(json.loads(after[3][0]['evidence_json']), self.evidence)
        self.assertEqual(after[3][0]['evidence_sha256'], identity(self.evidence))
        self.assertEqual(after[2], [])

    def test_identical_reexecution_is_noop_and_conflicting_evidence_fails(self):
        service.execute_prepared(self.evidence, self.store, execute=True)
        original = self.store.snapshot()
        result = service.execute_prepared(self.evidence, self.store, execute=True)
        self.assertEqual(result['status'], 'already_disposed'); self.assertEqual(self.store.writes, 1)
        self.assertEqual(self.store.snapshot(), original)
        changed = dict(self.evidence, proof='different proof')
        with self.assertRaisesRegex(ConfigurationFailure, 'conflict'):
            service.execute_prepared(changed, self.store, execute=True)
        self.assertEqual(self.store.snapshot(), original)

    def test_every_original_identity_and_null_result_are_bound_by_atomic_trigger(self):
        changes = {'release_id': 'foreign', 'scope_id': 'foreign', 'person_id': 'person',
            'state': 'complete', 'active_slot': None, 'run_id': '999', 'code_sha': 'a'*40,
            'result_json': '{}', 'created_at': 'changed', 'updated_at': 'changed'}
        for column, value in changes.items():
            with self.subTest(column=column):
                self.sql('UPDATE contextual_validation_jobs SET '+column+'=?', (value,))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.store.query(service.disposition_sql(self.evidence))
                self.assertEqual(self.store.snapshot()[3], [])  # No half-installed archive.
                self.sql('UPDATE contextual_validation_jobs SET '+column+'=?', (self.p['original_row'][column],))

    def test_paid_control_reenabled_between_read_and_write_rolls_back_whole_statement(self):
        def race():
            self.sql('UPDATE contextual_trial_controls SET new_paid_enabled=1')
        with self.assertRaises(sqlite3.IntegrityError):
            service.execute_prepared(self.evidence, self.store, execute=True, revalidate=race)
        after = self.store.snapshot()
        self.assertEqual(after[0], self.before[0]); self.assertEqual(after[3], [])

    def test_result_arriving_between_read_and_cas_preserves_result_and_rejects_disposition(self):
        def callback():
            self.sql("UPDATE contextual_validation_jobs SET state='complete',active_slot=NULL,result_json='{}'")
        with self.assertRaises(sqlite3.IntegrityError):
            service.execute_prepared(self.evidence, self.store, execute=True, revalidate=callback)
        after = self.store.snapshot()
        self.assertEqual(after[0][0]['result_json'], '{}'); self.assertEqual(after[3], [])

    def test_unrelated_unknown_slot_and_history_are_not_released(self):
        self.sql('UPDATE contextual_validation_jobs SET active_slot=NULL')
        row = dict(self.p['original_row'], job_id='a'*64, scope_id='other', active_slot=1, state='recovery_required')
        self.sql('INSERT INTO contextual_validation_jobs (' + ','.join(row) + ') VALUES ('
                 + ','.join('?' for _ in row) + ')', tuple(row.values()))
        with self.assertRaises(ConfigurationFailure): service.execute_prepared(self.evidence, self.store, execute=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT active_slot FROM contextual_validation_jobs WHERE job_id=?', ('a'*64,)).fetchone(), (1,))
            self.assertEqual(db.execute('SELECT count(*) FROM contextual_service_dispositions').fetchone(), (0,))

    def test_tombstone_is_immutable_and_malformed_insert_cannot_release_slot(self):
        sql = service.disposition_sql(self.evidence)
        with self.assertRaises(sqlite3.IntegrityError): self.store.query(sql.replace(self.p['original_row']['job_id'], 'a'*64))
        self.assertEqual(self.store.snapshot(), self.before)
        service.execute_prepared(self.evidence, self.store, execute=True)
        for mutation in ('DELETE FROM contextual_service_dispositions', "UPDATE contextual_service_dispositions SET evidence_sha256='"+'a'*64+"'"):
            with self.assertRaises(sqlite3.IntegrityError): self.sql(mutation)
        self.assertTrue(service.check_snapshot(self.store.snapshot(), self.evidence))

    def test_concurrent_same_disposition_is_single_archive_and_cannot_reopen(self):
        sql = service.disposition_sql(self.evidence)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: Database(self.path).query(sql), range(2)))
        self.assertTrue(service.check_snapshot(self.store.snapshot(), self.evidence))
        self.assertEqual(len(self.store.snapshot()[3]), 1)
        # Released Math remains in the finite inventory. Another job can claim
        # exactly the one free global slot; a second concurrent active row fails.
        row = dict(self.p['original_row'], job_id='b'*64, scope_id='next')
        self.sql('INSERT INTO contextual_validation_jobs ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))
        row['job_id'] = 'c'*64
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql('INSERT INTO contextual_validation_jobs ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))

    def test_fresh_provenance_failure_never_submits_write(self):
        def fail(): raise ConfigurationFailure('changed owner')
        with self.assertRaises(ConfigurationFailure):
            service.execute_prepared(self.evidence, self.store, execute=True, revalidate=fail)
        self.assertEqual(self.store.writes, 0); self.assertEqual(self.store.snapshot(), self.before)

    def test_schema_inventory_contains_exact_cas_and_immutable_triggers(self):
        self.assertEqual(self.store.query(service.schema_sql()), [service.expected_schema()])
        self.sql('DROP TRIGGER contextual_service_disposition_install')
        self.assertNotEqual(self.store.query(service.schema_sql()), [service.expected_schema()])


class ProofBoundaries(unittest.TestCase):
    def test_wrangler_uses_direct_bounded_query_argument_never_bulk_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            cli = Path(temporary)/'wrangler.js'; cli.write_text('// synthetic existing CLI')
            with patch.object(service.shutil, 'which', return_value='node'):
                client = service.Wrangler(cli)
            with patch.object(service.subprocess, 'check_output', return_value=encoded([{'success':True,'results':[{'n':1}]}])) as run:
                self.assertEqual(client.query('SELECT 1 AS n;'), [[{'n':1}]])
                command = run.call_args.args[0]
                self.assertIn('--command', command); self.assertNotIn('--file', command)
                self.assertEqual(command[command.index('--command')+1], 'SELECT 1 AS n;')
                with self.assertRaises(ConfigurationFailure): client.query('x'*20001)
                self.assertEqual(run.call_count, 1)

    def test_checkout_requires_current_protected_head_clean_tree_and_guard_source(self):
        head = 'a'*40
        api = lambda path: encoded({'object': {'sha': head}} if path.startswith('git/')
            else {'protected': True, 'commit': {'sha': head}})
        git = lambda args: head if args[0] == 'rev-parse' else ''
        self.assertEqual(service.protected_checkout(api, git), head)
        for response in (' M tools/contextual_team_service_disposition.py', 'ahead'):
            with self.assertRaises(ConfigurationFailure):
                service.protected_checkout(api, lambda args: head if args[0] == 'rev-parse' else response)
        with self.assertRaises(ConfigurationFailure):
            service.protected_checkout(lambda path: encoded({'object': {'sha': head}}) if path.startswith('git/')
                else encoded({'protected': False, 'commit': {'sha': head}}), git)
        p = service.plan(); p['callback_guard_source_sha256'] = '0'*64
        with patch.object(service, 'plan', return_value=p), self.assertRaises(ConfigurationFailure):
            service.protected_checkout(api, git)

    def test_active_queued_or_unfinished_latest_owner_blocks(self):
        for blocked in ('queued', 'in_progress', 'waiting', 'pending', 'requested'):
            def api(path):
                if 'status='+blocked+'&' in path: return encoded({'total_count': 1, 'workflow_runs': [{'id': 1}]})
                return encoded({'total_count': 0, 'workflow_runs': []})
            with self.subTest(blocked=blocked), self.assertRaises(ConfigurationFailure): service.owner_inventory(api)
        def missing(path):
            if '?status=' in path: return encoded({'total_count': 0, 'workflow_runs': []})
            return encoded({'artifacts': [{'name': service.existing.PREFIX+'-reservation-123-1',
                'created_at': '2026-09-22T14:00:00Z'}]})
        with self.assertRaisesRegex(ConfigurationFailure, 'latest_complete'): service.owner_inventory(missing)

    def test_artifact_owner_digest_and_terminal_run_fail_closed(self):
        run = service.plan()['accounting_run']; artifact = service.plan()['accounting_state_artifact']
        metadata = dict(artifact, expired=False, workflow_run={'id': run['id'], 'head_sha': run['head_sha']})
        for mutate in (lambda x: x.update(expired=True), lambda x: x['workflow_run'].update(id=1),
                       lambda x: x.update(digest='sha256:'+'0'*64)):
            changed = copy.deepcopy(metadata); mutate(changed)
            with self.assertRaises(ConfigurationFailure): service.download(lambda path: encoded(changed), artifact, run)
        with self.assertRaisesRegex(ConfigurationFailure, 'digest'):
            service.download(lambda path: b'wrong archive' if path.endswith('/zip') else encoded(metadata), artifact, run)
        for field, value in (('status','in_progress'), ('head_branch','other'), ('path','other'), ('head_sha','a'*40)):
            changed = dict(run); changed[field] = value
            with self.assertRaises(ConfigurationFailure): service.trusted_run(lambda path: encoded(changed), run['id'], expected=run)

    def test_live_proof_rejects_wrong_modules_config_routes_and_mixed_traffic(self):
        deployment = {'deployments': [{'id': 'deployment', 'created_on':'2026-09-22T14:00:00Z',
            'versions': [{'version_id':'version','percentage':100}]}]}
        # Preserve the authentic JS localeCompare order, which differs from
        # Python's code-point order for these real binding names.
        config = {'runtime': {'exports': {}}, 'bindings': [
            {'name':'SUBMISSION_RATE_LIMITER','type':'ratelimit'}, {'name':'SUBMISSIONS_DB','type':'d1','id':'db'}]}
        proof = {'deployment_id':'deployment','version_id':'version','configuration_sha256':identity(config),
            'module_hashes': {'index.js':service.existing.sha(b'exact')},
            'routing':{'workers_dev':True,'previews_enabled':True,'crons':[],'routes':[],'domains':[]}}
        responses = {
            '/deployments':deployment,'/versions/version':{'resources':{'script_runtime':{},'bindings':list(reversed(config['bindings']))}},
            '?include=modules':{'id':'version','modules':[{'name':'index.js','content_type':'application/javascript+module',
                'content_base64':base64.b64encode(b'exact').decode()}]},
            '/subdomain':{'enabled':True,'previews_enabled':True}, '/schedules':{'schedules':[]},
            'routes?show_zonename=true':[], 'environment=production':[]}
        def api(path): return copy.deepcopy(next(value for suffix,value in responses.items() if path.endswith(suffix)))
        service.live_serving(api, proof, config)
        for key, value in (('/subdomain', {'enabled':False,'previews_enabled':True}),
            ('/versions/version', {'resources':{'script_runtime':{'changed':True},'bindings':[]}}),
            ('routes?show_zonename=true', [{'pattern':'foreign'}]),
            ('?include=modules', {'id':'version','modules':[]})):
            old = responses[key]; responses[key] = value
            with self.assertRaises(ConfigurationFailure): service.live_serving(api, proof, config)
            responses[key] = old
        mixed = copy.deepcopy(deployment); mixed['deployments'][0]['versions'][0]['percentage'] = 50
        with self.assertRaises(ConfigurationFailure): service.active_deployment(mixed)

    def test_authenticated_descendant_preserves_history_files_hold_and_rejects_new_uncertainty(self):
        p = service.plan()
        fixture = recovery_fixture.Fixture('runTest'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.restore(); baseline = fixture.destination
        current = fixture.root/'service-descendant'
        service.existing.unpack_state(recovery_fixture.state_archive(baseline), current)
        p.update(baseline_ledger_sha256=service.existing.sha((baseline/'ledger.json').read_bytes()),
            baseline_checkpoint_sha256=service.existing.sha((baseline/'checkpoint.json').read_bytes()),
            accounting_receipt_sha256=service.existing.sha(service.recovery.receipt_path(baseline).read_bytes()))
        def counts(path): return json.loads((path/'checkpoint.json').read_bytes())['phase2_token_preflight']['rows']
        with patch.object(service, 'plan', return_value=p), patch.object(service.iteration2, 'history'), \
                patch.object(service.iteration2, 'check_counts', side_effect=counts):
            value = service.validate_descendant(baseline, current)
            self.assertEqual(value['permanent_hold'], {'microusd':713400,'attempts':4,'native_counts':1})
            original = json.loads((current/'ledger.json').read_bytes())
            later = copy.deepcopy(original)
            later['requests'].append({'purpose':'cb-fc-new-synthetic','status':'failed','usage':{'input_tokens':1},
                'charged_microusd':1,'key':'new','id':'new'})
            atomic_json(current/'ledger.json', later); service.existing.checkpoint(current)
            self.assertEqual(service.validate_descendant(baseline, current)['requests'], len(later['requests']))
            later['requests'][-1]['status'] = 'reserved_unknown'; atomic_json(current/'ledger.json', later)
            service.existing.checkpoint(current)
            with self.assertRaisesRegex(ConfigurationFailure, 'new_unknown'): service.validate_descendant(baseline, current)
            later['requests'][-1]['status'] = 'failed'; later['requests'][0]['charged_microusd'] += 1
            atomic_json(current/'ledger.json', later); service.existing.checkpoint(current)
            with self.assertRaisesRegex(ConfigurationFailure, 'history'): service.validate_descendant(baseline, current)
            atomic_json(current/'ledger.json', original)
            file = next((current/'diagnostics').glob('*.json')); file.write_bytes(b'{}')
            service.existing.checkpoint(current)
            with self.assertRaisesRegex(ConfigurationFailure, 'baseline_file'): service.validate_descendant(baseline, current)


if __name__ == '__main__':
    unittest.main()
