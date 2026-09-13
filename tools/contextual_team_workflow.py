"""Authenticated finite-job handshakes. No provider credentials or dispatch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import requests
from tools.contextual_team_executor import HOST, resolve_job
from tools.contextual_team_policy import inputs
from tools.team_recommender_executor import trusted_environment, bounded_response
from tools.offline_spend import atomic_json, ConfigurationFailure


def send(path,value):
    secret=os.environ.get('REGISTRY_WORKFLOW_TOKEN')
    if not secret:raise ConfigurationFailure('contextual_workflow_authentication_missing')
    response=requests.post(HOST+'/internal/contextual/'+path,headers={'Authorization':'Bearer '+secret,
        'User-Agent':'FundingFinder-ContextualValidation/1.0'},json=value,timeout=45,stream=True,allow_redirects=False)
    return json.loads(bounded_response(response,200000))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','finish'])
    p.add_argument('--job',type=Path,required=True);p.add_argument('--result',type=Path);p.add_argument('--state',type=Path)
    args=p.parse_args();trusted_environment()
    job=json.loads(os.environ['CONTEXTUAL_JOB']) if args.action=='start' else json.loads(args.job.read_bytes())
    resolve_job(inputs(),job)
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
    send('result',value)
    print(json.dumps({'status':'stored','job_id':job['job_id'],'state':value['result']['state']}))


if __name__=='__main__':main()
