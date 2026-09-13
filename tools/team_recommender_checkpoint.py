"""Fail-closed checkpoint ordering and one exact, reviewed historical repair.

No provider calls, new ledger or general-purpose cache merge. Artifact IDs are
opaque; their observed order is not creation order.
"""
from datetime import datetime
import json
from pathlib import Path
import re
import tempfile
from tools.offline_spend import Deferred, identity, atomic_json


def created(artifact):
    value=artifact.get('created_at')
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value):
        raise Deferred('checkpoint_creation_time_unavailable')
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as error:raise Deferred('checkpoint_creation_time_invalid') from error


def latest_reservation(reservations):
    ordered=sorted(reservations,key=created)
    if len(ordered)>1 and created(ordered[-1])==created(ordered[-2]):
        raise Deferred('checkpoint_creation_order_ambiguous')
    return ordered[-1]


def recover_known_charge(destination,latest,artifacts,api_call,executor):
    plan=json.loads((executor.CONFIG/'checkpoint-recovery-v1.json').read_bytes())
    if created(latest)<created({'created_at':plan['required_after']}):return
    if plan['authorization_id']!=executor.AUTHORIZATION_ID:raise ValueError('recovery_authorization_conflict')
    ledger=executor.ExperimentLedger(destination/'ledger.json').read()
    row_matches=[r for r in ledger['requests'] if r['id']==plan['request_id'] or r['key']==plan['request_key']]
    receipt=destination/'receipts'/(plan['request_id']+'.json')
    if row_matches:
        if len(row_matches)!=1 or identity(row_matches[0])!=plan['request_sha256']:
            raise Deferred('recovery_request_conflict')
        if receipt.exists() and executor.sha(receipt.read_bytes())==plan['receipt_sha256']:
            executor.checkpoint(destination)
            return
        if receipt.exists():raise Deferred('recovery_receipt_conflict')
    if (destination/'cache'/(plan['request_key']+'.json')).exists():raise Deferred('recovery_failed_request_has_cache')
    matches=[a for a in artifacts if a['id']==plan['source_state_artifact']]
    if len(matches)!=1 or matches[0]['expired']:raise Deferred('recovery_source_artifact_unavailable')
    artifact=matches[0]
    if (artifact['name']!=executor.PREFIX+'-state-'+str(plan['source_run'])+'-'+plan['source_attempt']
        or artifact['workflow_run']['id']!=plan['source_run']):raise ValueError('recovery_source_artifact_identity')
    run=json.loads(api_call('actions/runs/'+str(plan['source_run'])))
    if (run['path']!=executor.WORKFLOW or run['head_branch']!='main' or run['event']!='repository_dispatch'
        or run['head_sha']!=plan['source_code_sha']):raise ValueError('recovery_source_run_untrusted')
    raw=api_call('actions/artifacts/'+str(plan['source_state_artifact'])+'/zip')
    if len(raw)>executor.STATE_LIMIT:raise ValueError('checkpoint_archive_too_large')
    with tempfile.TemporaryDirectory(prefix='team-charge-recovery-') as temp:
        source=Path(temp);executor.unpack_state(raw,source)
        if (executor.sha((source/'checkpoint.json').read_bytes())!=plan['source_checkpoint_sha256']
            or executor.sha((source/'ledger.json').read_bytes())!=plan['source_ledger_sha256']):raise ValueError('recovery_source_hash_conflict')
        prior=executor.ExperimentLedger(source/'ledger.json').read()
        current={r['id']:r for r in ledger['requests']}
        # Every other original charge must already be present byte-for-byte.
        # This is deliberately not an arbitrary historical merge or reconciliation.
        for row in prior['requests']:
            if row['id']!=plan['request_id'] and current.get(row['id'])!=row:
                raise Deferred('recovery_other_history_conflict')
        rows=[r for r in prior['requests'] if r['id']==plan['request_id']]
        if (len(rows)!=1 or identity(rows[0])!=plan['request_sha256'] or rows[0]['status']!='failed'
            or rows[0]['charged_microusd']!=plan['charged_microusd']):raise ValueError('recovery_original_request_conflict')
        raw_receipt=(source/'receipts'/(plan['request_id']+'.json')).read_bytes()
        if executor.sha(raw_receipt)!=plan['receipt_sha256']:raise ValueError('recovery_original_receipt_conflict')
        if receipt.exists() and receipt.read_bytes()!=raw_receipt:raise Deferred('recovery_receipt_conflict')
        # An interruption can leave this exact receipt ahead of its ledger row;
        # the next restoration repeats this idempotent repair before any dispatch.
        atomic_json(receipt,json.loads(raw_receipt))
        if not row_matches:
            ledger['requests'].append(rows[0])
            ledger['events'].append({'kind':'exact_historical_charge_recovered','key':plan['request_key'],
                'source_run':plan['source_run'],'source_ledger_sha256':plan['source_ledger_sha256']})
            atomic_json(destination/'ledger.json',ledger)
        executor.ExperimentLedger(destination/'ledger.json').read()
        executor.checkpoint(destination)
