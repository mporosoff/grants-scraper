"""Authenticated finite-job handshakes. No provider credentials or dispatch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import requests
from tools.contextual_team_executor import HOST, resolve_job
from tools.contextual_team_option1 import configuration_for_job
from tools.team_recommender_executor import trusted_environment, bounded_response
from tools.offline_spend import atomic_json, encoded, ConfigurationFailure, Deferred

ITERATION2_CALLBACK_BYTES = 524288
ITERATION3_CALLBACK_BYTES = 524288


def send(path,value):
    secret=os.environ.get('REGISTRY_WORKFLOW_TOKEN')
    if not secret:raise ConfigurationFailure('contextual_workflow_authentication_missing')
    from tools.contextual_team_iteration2_policy import plan
    from tools.contextual_team_iteration3_policy import plan as iteration3_plan
    headers={'Authorization':'Bearer '+secret,'User-Agent':'FundingFinder-ContextualValidation/1.0'}
    payload={'json':value}
    i3=value.get('release_id')==iteration3_plan()['release_id']
    if value.get('release_id')==plan()['release_id'] or i3:
        # Bound the exact UTF-8 envelope, not just its graph. Retained scientific
        # bytes are sent unchanged; requests' ASCII escaping cannot inflate it.
        wire=encoded(value)
        if len(wire)>(ITERATION3_CALLBACK_BYTES if i3 else ITERATION2_CALLBACK_BYTES):
            raise ConfigurationFailure(('iteration3' if i3 else 'iteration2')+'_complete_callback_bound_no_truncation')
        headers['Content-Type']='application/json; charset=utf-8'
        payload={'data':wire}
    response=requests.post(HOST+'/internal/contextual/'+path,headers=headers,
        **payload,timeout=45,stream=True,allow_redirects=False)
    return json.loads(bounded_response(response,200000))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','finish'])
    p.add_argument('--job',type=Path,required=True);p.add_argument('--result',type=Path);p.add_argument('--state',type=Path)
    args=p.parse_args()
    job=json.loads(os.environ['CONTEXTUAL_JOB']) if args.action=='start' else json.loads(args.job.read_bytes())
    resolve_job(configuration_for_job(job),job)
    trusted_environment(contextual_job=job)
    stamp={k:job[k] for k in ('job_id','release_id')}|{'run_id':os.environ['GITHUB_RUN_ID'],'code_sha':os.environ['GITHUB_SHA']}
    if args.action=='start':
        if os.environ.get('PACKET_COMMIT') or os.environ.get('PACKET_HASH'):
            raise ValueError('contextual_and_legacy_inputs_are_exclusive')
        answer=send('start',stamp)
        if any(answer.get(k)!=job[k] for k in job):raise ValueError('contextual_job_owner_mismatch')
        atomic_json(args.job,job)
        current=json.loads(subprocess.check_output(['node','tools/contextual_currentness.mjs',str(args.job)],timeout=30))
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            stream.write('action_current='+str(current['action_current']).lower()+'\n')
        print(json.dumps(current));return
    if args.result.exists():value=json.loads(args.result.read_bytes())
    else:
        ledger=json.loads((args.state/'ledger.json').read_bytes())
        value=stamp|{'result':{'scope_id':job['scope_id'],'state':'recovery_required','reason':'workflow_interrupted; no automatic paid replay'},
            'charged_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'attempts':len(ledger['requests'])}
    if any(value.get(k)!=v for k,v in stamp.items()):raise ValueError('contextual_result_run_identity')
    if value['result'].get('state')=='stage_complete':
        # A published intermediate stage is retained evidence, not a UI graph.
        # If a later artifact/barrier failed, finish the finite job without
        # dispatching again. Historical acknowledged holds do not create a new
        # uncertainty; any new inference or native-count uncertainty keeps it.
        from tools import contextual_team_iteration3_policy as iteration3
        if job['release_id']!=iteration3.plan()['release_id']:
            raise ValueError('contextual_intermediate_result_release')
        ledger=json.loads((args.state/'ledger.json').read_bytes())
        state='failed'
        try:
            iteration3.history(ledger);iteration3.check_counts(args.state)
        except (Deferred,ValueError,KeyError,TypeError,OSError):
            state='recovery_required'
        value=stamp|{'result':{'scope_id':job['scope_id'],'state':state,
            'reason':'iteration3_stopped_between_durable_stages; no automatic paid replay'},
            'charged_microusd':sum(r['charged_microusd'] for r in ledger['requests']),
            'attempts':len(ledger['requests'])}
    send('result',value)
    print(json.dumps({'status':'stored','job_id':job['job_id'],'state':value['result']['state']}))


if __name__=='__main__':main()
