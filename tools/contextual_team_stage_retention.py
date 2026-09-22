"""Durable I3 stage barriers in the existing serialized trusted workflow.

These archives preserve evidence; they do not create another spending owner or
automatically authorize rollback to an older state after an uncertain tail.
"""
import argparse
import json
import io
import os
from pathlib import Path
import re
import zipfile

from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure

VERSION = 'contextual-iteration3-durable-stage-v1'
STAGES = ('assess', 'verify', 'integrity')


def stage_path(state, job, stage):
    return Path(state)/'cache'/(identity([VERSION, job['job_id'], os.environ['GITHUB_RUN_ID'],
        os.environ['GITHUB_RUN_ATTEMPT'], stage])+'.json')


def complete(state, job, stage, result):
    progress={'state':'stage_complete','stage':stage,'scope_id':job['scope_id']}
    graph=(isinstance(result,dict) and re.fullmatch('[a-f0-9]{64}',result.get('graph_id',''))
        and result.get('scope',{}).get('id')==job['scope_id'])
    terminal=graph and ((stage=='verify' and result.get('state') in ('unsuitable','insufficient_source','needs_scope_selection')
        and result.get('version')=='contextual-audited-graph-v3') or (stage=='integrity' and result.get('state') in
        ('ready','ready_with_gaps','no_supported_group_in_assessed_set','no_supported_group_in_checked_candidates')
        and result.get('version')=='contextual-audited-graph-v4'))
    if stage not in STAGES or not ((stage in ('assess','verify') and encoded(result)==encoded(progress)) or terminal):
        raise ConfigurationFailure('iteration3_stage_not_completed')
    row={'version':VERSION,'job_id':job['job_id'],'release_id':job['release_id'],'scope_id':job['scope_id'],
        'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha':os.environ['GITHUB_SHA'],'stage':stage,'result_sha256':identity(result),'result_state':result['state']}
    path=stage_path(state,job,stage)
    if path.exists() and path.read_bytes()!=encoded(row)+b'\n':
        raise ConfigurationFailure('iteration3_stage_first_result_conflict')
    atomic_json(path,row);existing.checkpoint(Path(state))
    return row


def _local(state):
    state=Path(state);raw=(state/'checkpoint.json').read_bytes();cp=json.loads(raw)
    files={f.relative_to(state).as_posix():existing.sha(f.read_bytes()) for f in state.rglob('*.json') if f.name!='checkpoint.json'}
    if (cp.get('files')!=files or cp.get('run_id')!=os.environ['GITHUB_RUN_ID']
        or cp.get('attempt')!=os.environ['GITHUB_RUN_ATTEMPT'] or cp.get('code_sha')!=os.environ['GITHUB_SHA']
        or cp.get('authorization_id')!=existing.AUTHORIZATION_ID or len(files)>existing.STATE_FILE_LIMIT):
        raise ConfigurationFailure('iteration3_prior_stage_local_checkpoint_changed')
    return cp,raw


def _prior(state,job,stage):
    if stage not in ('verify','integrity'):raise ConfigurationFailure('iteration3_unknown_prior_stage')
    prior=STAGES[STAGES.index(stage)-1]
    expected={'version':VERSION,'job_id':job['job_id'],'release_id':job['release_id'],'scope_id':job['scope_id'],
        'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha':os.environ['GITHUB_SHA'],'stage':prior,'result_state':'stage_complete',
        'result_sha256':identity({'state':'stage_complete','stage':prior,'scope_id':job['scope_id']})}
    raw=stage_path(state,job,prior).read_bytes()
    if raw!=encoded(expected)+b'\n':raise ConfigurationFailure('iteration3_prior_stage_complete_receipt_required')
    return prior,existing.sha(raw)


def seal_path(state,job,stage):
    return Path(state).parent/'i3-stage-barriers'/(identity([VERSION,job['job_id'],os.environ['GITHUB_RUN_ID'],
        os.environ['GITHUB_RUN_ATTEMPT'],stage])+'.json')


def seal(state, job, stage, api_call=None):
    # This credential-only step never changes the spending checkpoint. The
    # bounded local acknowledgement is passed to the provider step by its hash.
    if any(value for key,value in os.environ.items() if key.endswith('_API_KEY')):
        raise ConfigurationFailure('iteration3_stage_barrier_provider_credentials_forbidden')
    if stage not in STAGES:raise ConfigurationFailure('iteration3_unknown_stage')
    prior,receipt_sha=_prior(state,job,stage)
    artifact_id=os.environ.get('I3_PRIOR_ARTIFACT_ID','');digest=os.environ.get('I3_PRIOR_ARTIFACT_DIGEST','')
    if not re.fullmatch('[1-9][0-9]*',artifact_id) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise ConfigurationFailure('iteration3_prior_stage_durable_artifact_required')
    api_call=api_call or existing.api
    a=json.loads(api_call('actions/artifacts/'+artifact_id))
    name=f'{existing.AUTHORIZATION_ID}-stage-{prior}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
    if (type(a.get('id')) is not int or str(a['id'])!=artifact_id or a.get('name')!=name or a.get('digest')!='sha256:'+digest
            or a.get('expired') is not False or type(a.get('workflow_run',{}).get('id')) is not int
            or a['workflow_run']['id']!=int(os.environ['GITHUB_RUN_ID'])
            or a.get('workflow_run',{}).get('head_sha')!=os.environ['GITHUB_SHA']):
        raise ConfigurationFailure('iteration3_prior_stage_artifact_identity')
    state=Path(state);cp,cp_raw=_local(state);files=cp['files']
    raw=api_call('actions/artifacts/'+artifact_id+'/zip')
    if len(raw)>existing.STATE_LIMIT or existing.sha(raw)!=digest:
        raise ConfigurationFailure('iteration3_prior_stage_archive_digest')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=[i for i in archive.infolist() if not i.is_dir()]
        names=[i.filename for i in infos]
        if (len(names)!=len(set(names)) or len(names)>existing.STATE_FILE_LIMIT
                or sum(i.file_size for i in infos)>existing.STATE_LIMIT or set(names)!=set(files)|{'checkpoint.json'}):
            raise ConfigurationFailure('iteration3_prior_stage_archive_shape')
        if any(existing.sha(archive.read(name))!=digest for name,digest in files.items()) or archive.read('checkpoint.json')!=(state/'checkpoint.json').read_bytes():
            raise ConfigurationFailure('iteration3_prior_stage_archive_not_exact_local_state')
    row={'version':VERSION,'job_id':job['job_id'],'release_id':job['release_id'],'scope_id':job['scope_id'],
        'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha':os.environ['GITHUB_SHA'],'stage':stage,'prior_stage':prior,'prior_receipt_sha256':receipt_sha,
        'checkpoint_sha256':existing.sha(cp_raw),'artifact_id':artifact_id,'artifact_name':name,'artifact_digest':digest}
    path=seal_path(state,job,stage)
    if path.exists() and path.read_bytes()!=encoded(row)+b'\n':
        raise ConfigurationFailure('iteration3_prior_stage_first_seal_conflict')
    if not path.exists():atomic_json(path,row)
    return existing.sha(path.read_bytes())


def require_prior(state,job,stage):
    """Provider step: no GitHub call, no rollback, and no changed local file."""
    if stage not in STAGES:raise ConfigurationFailure('iteration3_unknown_stage')
    if stage=='assess':return
    bound=os.environ.get('I3_PRIOR_SEAL_SHA256','')
    if not re.fullmatch('[a-f0-9]{64}',bound):raise ConfigurationFailure('iteration3_prior_stage_authenticated_seal_required')
    raw=seal_path(state,job,stage).read_bytes()
    if existing.sha(raw)!=bound:raise ConfigurationFailure('iteration3_prior_stage_seal_changed')
    row=json.loads(raw);_,cp_raw=_local(state);prior,receipt_sha=_prior(state,job,stage)
    name=f'{existing.AUTHORIZATION_ID}-stage-{prior}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
    expected={'version':VERSION,'job_id':job['job_id'],'release_id':job['release_id'],'scope_id':job['scope_id'],
        'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha':os.environ['GITHUB_SHA'],'stage':stage,'prior_stage':prior,'prior_receipt_sha256':receipt_sha,
        'checkpoint_sha256':existing.sha(cp_raw),'artifact_id':row.get('artifact_id'),
        'artifact_name':name,'artifact_digest':row.get('artifact_digest')}
    if (raw!=encoded(expected)+b'\n' or not isinstance(row.get('artifact_id'),str)
            or not re.fullmatch('[1-9][0-9]*',row['artifact_id']) or not isinstance(row.get('artifact_digest'),str)
            or not re.fullmatch('[a-f0-9]{64}',row['artifact_digest'])):
        raise ConfigurationFailure('iteration3_prior_stage_seal_identity_changed')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal'])
    p.add_argument('--state',type=Path,required=True);p.add_argument('--job',type=Path,required=True)
    p.add_argument('--stage',choices=['verify','integrity'],required=True);args=p.parse_args()
    from tools.contextual_team_option1 import configuration_for_job
    from tools.contextual_team_executor import resolve_job
    job=json.loads(args.job.read_bytes());config=configuration_for_job(job);resolve_job(config,job)
    existing.trusted_environment(contextual_job=job)
    if not config.get('iteration3'):raise ConfigurationFailure('iteration3_stage_barrier_release_required')
    bound=seal(args.state,job,args.stage)
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('prior_seal_sha256='+bound+'\n')
    print(json.dumps({'stage':args.stage,'prior_seal_sha256':bound,'provider_calls':0}))


if __name__=='__main__':main()
