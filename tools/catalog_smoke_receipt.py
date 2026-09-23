"""Checkpoint-owned smoke aggregation and read-only authenticated reuse.

No paid dispatch, provider credential, ledger amendment or earlier-owner fallback.
The only new public request is the exact unknown-corpus rejection control.
"""
import argparse
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

import requests

from tools import team_recommender_executor as existing
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'search-worker-successful-smoke-v1'
CONTEXT_VERSION = 'catalog-correction-smoke-context-v1'
CONTEXT_PREFIX = 'catalog-correction-smoke-context-'
REFRESH = '.github/workflows/refresh-opportunities.yml'
NAMES = ('smoke-embed', 'smoke-current-rerank', 'smoke-previous-rerank')
WORKER = 'https://funding-finder-voyage-search.urochestercheme.workers.dev'


def require(ok, reason):
    if not ok:
        raise ConfigurationFailure('catalog_smoke_' + reason)


def json_value(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def node(action, value):
    executable = shutil.which('node')
    require(executable is not None, 'node_runtime_required')
    result = subprocess.run([executable, str(ROOT/'tools/catalog_smoke_receipt.mjs'), action],
        input=encoded(value), capture_output=True, cwd=ROOT, timeout=360, check=False)
    require(result.returncode == 0, 'node_' + action + '_rejected')
    lines = [json_value(line) for line in result.stdout.splitlines() if line.strip()]
    require(len(lines) == 1 and set(lines[0]) == {'result'}, 'node_result')
    return lines[0]['result']


def artifacts(api=existing.api):
    result = []
    for page in range(1, 101):
        rows = json_value(api(f'actions/artifacts?per_page=100&page={page}'))['artifacts']
        require(isinstance(rows, list), 'artifact_inventory')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ConfigurationFailure('catalog_smoke_artifact_inventory_bound')


def trusted_run(run_id, workflow, *, terminal=True, allow_failed=False, attempt=None, api=existing.api):
    require(type(run_id) is int and run_id > 0, 'run_id')
    run = json_value(api(f'actions/runs/{run_id}'))
    if attempt is not None:
        require(type(attempt) is int and attempt > 0, 'run_attempt')
        if run.get('run_attempt') != attempt:
            run = json_value(api(f'actions/runs/{run_id}/attempts/{attempt}'))
        require(run.get('run_attempt') == attempt, 'exact_run_attempt')
    require(run.get('id') == run_id and type(run.get('run_attempt')) is int and run['run_attempt'] > 0
        and run.get('path') == workflow and run.get('head_branch') == 'main'
        and run.get('event') == 'workflow_dispatch' and re.fullmatch('[a-f0-9]{40}', run.get('head_sha', '')),
        'trusted_manual_main_run')
    require((run.get('status') == 'completed' and run.get('conclusion') in
        ({'success', 'failure', 'cancelled', 'timed_out'} if allow_failed else {'success'})) if terminal else
        (run.get('status') == 'in_progress' or (run.get('status') == 'completed' and run.get('conclusion') in
            ({'success', 'failure', 'cancelled', 'timed_out'} if allow_failed else {'success'}))),
        'run_not_successful_or_waiting')
    return run


def authenticated_zip(artifact_id, name, run, digest=None, *, api=existing.api):
    require(type(artifact_id) is int and artifact_id > 0, 'artifact_id')
    meta = json_value(api(f'actions/artifacts/{artifact_id}'))
    require(meta.get('id') == artifact_id and meta.get('name') == name and meta.get('expired') is False
        and meta.get('workflow_run', {}).get('id') == run['id']
        and meta['workflow_run'].get('head_sha') == run['head_sha']
        and re.fullmatch('sha256:[a-f0-9]{64}', meta.get('digest', ''))
        and (digest is None or meta['digest'] == digest), 'artifact_metadata')
    raw = api(f'actions/artifacts/{artifact_id}/zip')
    require(len(raw) <= existing.STATE_LIMIT and 'sha256:' + existing.sha(raw) == meta['digest'], 'raw_artifact_digest')
    return raw, meta


def unpack_public(raw, destination, *, context=False):
    destination = Path(destination)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        require(len(entries) <= (1 if context else 500) and sum(e.file_size for e in entries) <= 100*1024*1024,
            'public_archive_bound')
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            require(entry.filename not in seen and not path.is_absolute() and '\\' not in entry.filename
                and path.as_posix() == entry.filename
                and not any(p in ('', '.', '..') or ':' in p for p in path.parts)
                and not stat.S_ISLNK(entry.external_attr >> 16)
                and (not context or entry.filename == 'context.json'), 'unsafe_public_archive')
            seen.add(entry.filename)
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))
        require(bool(entries), 'empty_public_archive')


def load_context(state, inputs, *, api=existing.api, node_call=node):
    """Authenticate the refresh context and every referenced candidate/export ZIP.

    The source module validates the candidate's complete release manifest,
    original-source lineage and all seven vector row/cache/receipt bindings.
    """
    from tools import catalog_source_correction as source
    source.verify_inputs(inputs)
    candidates = [a for a in artifacts(api) if a.get('name', '').startswith(CONTEXT_PREFIX)]
    require(bool(candidates), 'context_missing')
    from tools.team_recommender_checkpoint import latest_reservation
    selected = latest_reservation(candidates)
    context_attempt = re.fullmatch(CONTEXT_PREFIX+'[a-f0-9]{64}-([1-9][0-9]*)-([1-9][0-9]*)', selected['name'])
    require(context_attempt is not None and int(context_attempt[1]) == selected['workflow_run']['id'], 'context_owner_attempt')
    run = trusted_run(selected['workflow_run']['id'], REFRESH, terminal=False, allow_failed=True,
        attempt=int(context_attempt[2]), api=api)
    raw, meta = authenticated_zip(selected['id'], selected['name'], run, selected.get('digest'), api=api)
    with tempfile.TemporaryDirectory(prefix='catalog-smoke-context-') as temporary:
        root = Path(temporary); unpack_public(raw, root/'context', context=True)
        context = json_value((root/'context/context.json').read_bytes())
        require(set(context) == {'version', 'source_plan_sha256', 'refresh', 'candidate', 'correction_export', 'generations', 'serving_proof'}
            and context['version'] == CONTEXT_VERSION
            and encoded(context['refresh']) == encoded({'run_id': run['id'], 'run_attempt': run['run_attempt'], 'head_sha': run['head_sha']}),
            'exact_context')
        candidate, export = context['candidate'], context['correction_export']
        require(meta['name'] == f"{CONTEXT_PREFIX}{candidate['candidate_id']}-{run['id']}-{run['run_attempt']}", 'context_artifact_name')
        candidate_run = trusted_run(candidate['artifact_run'], REFRESH, terminal=False, allow_failed=True, api=api)
        candidate_raw, _ = authenticated_zip(candidate['artifact_id'], 'candidate-'+candidate['candidate_id'], candidate_run,
            candidate['artifact_digest'], api=api)
        export_meta = json_value(api(f"actions/artifacts/{export['artifact_id']}"))
        export_attempt = re.fullmatch('catalog-correction-export-'+str(export['owner_run'])+'-([1-9][0-9]*)', export_meta.get('name', ''))
        require(export_attempt is not None, 'export_owner_attempt')
        export_run = trusted_run(export['owner_run'], existing.WORKFLOW, attempt=int(export_attempt[1]), api=api)
        export_raw, _ = authenticated_zip(export['artifact_id'], f"catalog-correction-export-{export_run['id']}-{export_run['run_attempt']}",
            export_run, export['artifact_digest'], api=api)
        unpack_public(candidate_raw, root/'candidate'); unpack_public(export_raw, root/'export')
        projection = source.validate_context_packet(context, root/'candidate', root/'export', Path(state), Path(inputs))
        require(set(projection) == {'expected', 'candidate_inputs'}, 'source_context_projection')
        original = context['serving_proof']
        require(encoded(original.get('candidate')) == encoded({'candidate_id': candidate['candidate_id'],
            'artifact_id': candidate['artifact_id'], 'artifact_digest': candidate['artifact_digest'],
            'manifest_sha256': candidate['manifest_sha256'], 'code_sha': run['head_sha']})
            and original['checkpoint']['baseSha'] == run['head_sha'], 'candidate_proof_lineage')
        fresh = node_call('proof', {'proof': original, 'candidate_inputs': projection['candidate_inputs']})
        require(fresh['fingerprint'] == projection['expected']['worker_input_fingerprint'], 'candidate_worker_fingerprint')
        return {'context': context, 'expected': projection['expected'], 'serving_proof': fresh,
            'candidate_inputs': projection['candidate_inputs'],
            'external_bodies': {n: json_value(o['public_body_text']) for n, o in zip(NAMES, projection['expected']['operations'], strict=True)}}


def receipt_path():
    from tools import catalog_correction_policy as policy
    return 'cache/' + identity({'version': VERSION, 'plan_sha256': policy.PLAN_SHA}) + '.json'


def validate_checkpoint(state):
    state = Path(state); cp = json_value((state/'checkpoint.json').read_bytes())
    files = {p.relative_to(state).as_posix(): existing.sha(p.read_bytes())
        for p in state.rglob('*.json') if p.name != 'checkpoint.json'}
    require(cp.get('authorization_id') == existing.AUTHORIZATION_ID and files == cp.get('files'), 'complete_local_checkpoint')
    return cp


def accepted_operations(state, inputs, expected, *, serving_proof=None, node_call=node, runner=None, allow_partial=False):
    from tools import catalog_correction_executor as executor, catalog_correction_policy as policy
    state = Path(state); runner = runner or executor.CatalogRunner(state, inputs)
    ledger = runner.ledger.read(); policy.history(ledger); policy.counts(state)
    operations = []
    require(type(allow_partial) is bool and len(expected['operations']) == 3, 'three_exact_inputs')
    for name, requested in zip(NAMES, expected['operations'], strict=True):
        op = policy.operation(name)
        rows = [r for r in ledger['requests'] if r.get('purpose') == op['purpose']]
        if allow_partial and not rows:
            continue
        require(len(rows) == 1, 'unique_accepted_purpose')
        body = executor.input_body(inputs, name)
        runner.cached(name, body)
        row = rows[0]; cache = json_value((state/'cache'/(row['key']+'.json')).read_bytes())
        receipt = json_value((state/'receipts'/(row['id']+'.json')).read_bytes())
        raw = (Path(inputs)/op['body_file']).read_bytes()
        require(requested['purpose'] == op['purpose'] and requested['provider_body_text'].encode() == raw
            and requested['provider_body_sha256'] == existing.sha(raw)
            and receipt.get('version') == policy.VERSION and receipt.get('name') == name
            and receipt.get('purpose') == op['purpose'] and receipt.get('request_id') == row['id']
            and receipt.get('provider') == 'voyage' and receipt.get('model') == op['model']
            and receipt.get('key') == row['key'] and receipt.get('body_sha256') == op['body_sha256']
            and receipt.get('sent_body_sha256') == identity(json_value(requested['public_body_text']))
            and receipt.get('code_sha') == row.get('code_sha')
            and receipt.get('status') == 'valid' and type(receipt.get('http_status')) is int and receipt['http_status'] == 200
            and receipt.get('automatic_retries') == 0 and type(receipt.get('automatic_retries')) is int
            and receipt.get('public_body_text') == requested['public_body_text']
            and receipt.get('external_http_body_sha256') == requested['external_http_body_sha256']
            and receipt.get('response_sha256') == cache['response_sha256']
            and encoded(receipt.get('usage')) == encoded(row['usage'])
            and type(receipt.get('charged_microusd')) is int and receipt['charged_microusd'] == row['charged_microusd'],
            'complete_request_receipt_cache_lineage')
        if serving_proof is not None:
            node_call('same-proof', {'before': receipt.get('serving_proof'), 'after': serving_proof})
        operations.append({'purpose': op['purpose'], 'request_id': row['id'], 'key': row['key'], 'provider': 'voyage',
            'model': op['model'], 'provider_body_sha256': existing.sha(raw),
            'external_http_body_sha256': receipt['external_http_body_sha256'], 'status': 'valid', 'http_status': 200,
            'usage': row['usage'], 'charged_microusd': row['charged_microusd'],
            'response_text': cache['response_text'], 'response_sha256': cache['response_sha256']})
    require(bool(operations), 'accepted_smoke_required')
    return operations


def finalize_smoke(state, inputs, *, context_loader=load_context, node_call=node, post=requests.post,
        crash=lambda boundary: None, now=lambda: datetime.now(timezone.utc).isoformat()):
    existing.trusted_environment(); state = Path(state)
    require(encoded(json_value(os.environ.get('CONTEXTUAL_CHECK', '{}'))) == encoded({'catalog_correction': NAMES[-1]})
        and not any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT')), 'exact_last_smoke_selector')
    require(not any(os.environ.get(k) for k in ('VOYAGE_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY')),
        'no_provider_credentials')
    from tools.catalog_correction_executor import CatalogRunner
    runner = CatalogRunner(state, inputs); ledger = runner.ledger
    path = state/receipt_path(); diagnostic = state/'diagnostics'/(path.stem[:32]+'.json')
    # Read-only context authentication may construct a ledger reader. Complete
    # it before taking the non-reentrant cross-process owner lock, then compare
    # the whole checkpoint under that lock before acting on the projection.
    snapshot = (state/'checkpoint.json').read_bytes()
    context = context_loader(state, inputs)
    with ledger.locked():
        # The finalizer adds evidence only. All charges and original caches stay
        # byte-identical; an existing aggregate is never regenerated.
        before_ledger = ledger.path.read_bytes()
        if (state/'checkpoint.json').read_bytes() != snapshot:
            old = json_value(snapshot)['files']
            require(path.exists() and all((state/name).is_file() and existing.sha((state/name).read_bytes()) == value
                for name, value in old.items()), 'owner_changed_during_context')
        validate_checkpoint(state)
        expected = context['expected']; operations = accepted_operations(state, inputs, expected,
            serving_proof=context['serving_proof'], node_call=node_call, runner=runner)
        if path.exists():
            raw = path.read_bytes(); saved = json_value(raw)
            require(encoded(saved['operations']) == encoded(operations), 'saved_aggregate_lineage')
            node_call('validate', {'receipt_text': raw.decode(), 'expected': expected})
            existing.checkpoint(state)
            return {'receipt_path': path.relative_to(state).as_posix(), 'receipt_sha256': existing.sha(raw), 'cache_hit': True}
        validate_checkpoint(state)
        body = encoded({'query': expected['query'], 'corpus_sha256': 'f'*64, 'candidates': [expected['shared_passage']]})
        require('f'*64 not in (expected['current']['corpus_sha256'], expected['previous']['corpus_sha256']), 'unknown_corpus_identity')
        draft = {'version': VERSION, 'status': 'passed', 'completed_at': now(),
            'owner': {'authorization_id': existing.AUTHORIZATION_ID, 'run_id': int(os.environ['GITHUB_RUN_ID']),
                'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'code_sha': os.environ['GITHUB_SHA']},
            'inputs': expected, 'serving_before': context['serving_proof'], 'serving_after': context['serving_proof'],
            'operations': operations, 'unknown_corpus': {'http_status': 400, 'public_body_text': body.decode(),
                'external_http_body_sha256': existing.sha(body), 'response_text': '{"error":{"code":"invalid_candidates"}}',
                'response_sha256': existing.sha(b'{"error":{"code":"invalid_candidates"}}'), 'provider_calls': 0}}
        # This validates the exact complete inputs and responses before even the
        # nonpaid control. The placeholder response is not execution evidence.
        node_call('validate', {'receipt_text': encoded(draft).decode(), 'expected': expected})
        evidence = json_value(diagnostic.read_bytes()) if diagnostic.exists() else None
        retained = evidence is not None
        if retained:
            require(evidence.get('version') == VERSION and evidence.get('status') == 'nonpaid_probe_returned'
                and type(evidence.get('http_status')) is int and evidence['http_status'] == 400
                and evidence.get('public_body_text') == body.decode() and evidence.get('external_http_body_sha256') == existing.sha(body)
                and isinstance(evidence.get('response_text'), str)
                and evidence.get('response_sha256') == existing.sha(evidence['response_text'].encode())
                and encoded(json_value(evidence['response_text'])) == encoded({'error': {'code': 'invalid_candidates'}}),
                'prior_nonpaid_probe_requires_diagnosis')
            node_call('same-proof', {'before': evidence.get('serving_before'), 'after': context['serving_proof']})
            draft['serving_before'] = evidence['serving_before']
        else:
            evidence = {'version': VERSION, 'status': 'before_nonpaid_probe', 'serving_before': context['serving_proof'],
                'public_body_text': body.decode(), 'external_http_body_sha256': existing.sha(body)}
            atomic_json(diagnostic, evidence); existing.checkpoint(state); crash('before_probe')
        try:
            if not retained:
                response = post(WORKER+'/rerank', headers={'Origin': 'https://mporosoff.github.io', 'Content-Type': 'application/json',
                    'Accept': 'application/json', 'User-Agent': 'FundingFinder-CatalogSmokeReceipt/1.0 (+https://github.com/mporosoff/grants-scraper)'},
                    data=body, timeout=(10, 30), stream=True, allow_redirects=False)
                evidence['http_status'] = response.status_code
                atomic_json(diagnostic, evidence)
                try:
                    chunks = []; size = 0
                    for chunk in response.iter_content(8192):
                        size += len(chunk); require(size <= 65536, 'nonpaid_response_bound'); chunks.append(chunk)
                    raw = b''.join(chunks)
                finally:
                    response.close()
                try:
                    response_text = raw.decode('utf8')
                except UnicodeDecodeError:
                    evidence.update(response_base64=base64.b64encode(raw).decode('ascii'), response_sha256=existing.sha(raw), status='invalid_utf8')
                    atomic_json(diagnostic, evidence)
                    raise
                evidence.update(response_text=response_text, response_sha256=existing.sha(raw), status='nonpaid_probe_returned')
                atomic_json(diagnostic, evidence); existing.checkpoint(state); crash('after_probe')
            raw = evidence['response_text'].encode()
            require(type(evidence['http_status']) is int and evidence['http_status'] == 400
                and encoded(json_value(raw)) == encoded({'error': {'code': 'invalid_candidates'}}), 'nonpaid_control_rejection')
            fresh = node_call('proof', {'proof': context['serving_proof'], 'candidate_inputs': context['candidate_inputs']})
            draft.update(serving_after=fresh, completed_at=now())
            draft['unknown_corpus'].update(response_text=raw.decode(), response_sha256=existing.sha(raw))
            node_call('validate', {'receipt_text': encoded(draft).decode(), 'expected': expected})
            require(ledger.path.read_bytes() == before_ledger, 'owner_changed_during_finalization')
            atomic_json(path, draft); crash('after_cache')
            evidence['status'] = 'passed'; atomic_json(diagnostic, evidence); crash('before_checkpoint')
        finally:
            existing.checkpoint(state)
        crash('after_checkpoint')
        return {'receipt_path': path.relative_to(state).as_posix(), 'receipt_sha256': existing.sha(path.read_bytes()), 'cache_hit': False}


def authenticate_owner(inputs, *, api=existing.api, node_call=node, context_loader=load_context):
    """Read the newest paired owner only; never substitute an earlier artifact."""
    inventory = artifacts(api)
    from tools.team_recommender_checkpoint import latest_reservation
    reservations = [a for a in inventory if a.get('name', '').startswith(existing.PREFIX+'-reservation-')]
    require(bool(reservations), 'owner_missing')
    latest = latest_reservation(reservations)
    state_name = latest['name'].replace('-reservation-', '-state-')
    matches = [a for a in inventory if a.get('name') == state_name]
    require(len(matches) == 1, 'latest_owner_state_missing')
    run = trusted_run(latest['workflow_run']['id'], existing.WORKFLOW, api=api)
    require(latest['name'] == f"{existing.PREFIX}-reservation-{run['id']}-{run['run_attempt']}", 'latest_owner_attempt')
    active = json_value(api('actions/workflows/team-recommender-offline.yml/runs?branch=main&per_page=100'))['workflow_runs']
    require(not any(r.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested') for r in active), 'concurrent_owner')
    raw, meta = authenticated_zip(matches[0]['id'], state_name, run, matches[0].get('digest'), api=api)
    with tempfile.TemporaryDirectory(prefix='catalog-smoke-owner-') as temporary:
        state = Path(temporary); existing.unpack_state(raw, state); cp = validate_checkpoint(state)
        require(str(cp.get('run_id')) == str(run['id']) and str(cp.get('attempt')) == str(run['run_attempt'])
            and cp.get('code_sha') == run['head_sha'], 'checkpoint_run_owner')
        context = context_loader(state, inputs, api=api, node_call=node_call)
        path = state/receipt_path(); receipt_raw = path.read_bytes(); receipt = json_value(receipt_raw)
        current_owner = {'authorization_id': existing.AUTHORIZATION_ID,
            'run_id': run['id'], 'run_attempt': run['run_attempt'], 'code_sha': run['head_sha']}
        origin = None
        if encoded(receipt['owner']) != encoded(current_owner):
            prior_run = trusted_run(receipt['owner']['run_id'], existing.WORKFLOW, allow_failed=True,
                attempt=receipt['owner']['run_attempt'], api=api)
            require(encoded(receipt['owner']) == encoded({'authorization_id': existing.AUTHORIZATION_ID,
                'run_id': prior_run['id'], 'run_attempt': prior_run['run_attempt'], 'code_sha': prior_run['head_sha']}), 'original_aggregate_run')
            prior_name = f"{existing.PREFIX}-state-{prior_run['id']}-{prior_run['run_attempt']}"
            prior_matches = [a for a in inventory if a.get('name') == prior_name]
            require(len(prior_matches) == 1, 'original_aggregate_artifact_missing')
            prior_raw, prior_meta = authenticated_zip(prior_matches[0]['id'], prior_name, prior_run,
                prior_matches[0].get('digest'), api=api)
            with tempfile.TemporaryDirectory(prefix='catalog-smoke-origin-') as prior_temporary:
                prior_state = Path(prior_temporary); existing.unpack_state(prior_raw, prior_state)
                prior_cp = validate_checkpoint(prior_state)
                require(str(prior_cp['run_id']) == str(prior_run['id']) and str(prior_cp['attempt']) == str(prior_run['run_attempt'])
                    and prior_cp['code_sha'] == prior_run['head_sha'], 'original_checkpoint_run')
                require((prior_state/receipt_path()).read_bytes() == receipt_raw and all(name == 'ledger.json'
                    or ((state/name).is_file() and existing.sha((state/name).read_bytes()) == value)
                    for name, value in prior_cp['files'].items()), 'original_full_evidence_preserved')
                old_ledger = json_value((prior_state/'ledger.json').read_bytes()); latest_ledger = json_value((state/'ledger.json').read_bytes())
                for field in ('requests', 'events'):
                    require(encoded(old_ledger[field]) == encoded(latest_ledger[field][:len(old_ledger[field])]), 'original_history_prefix')
                from tools import catalog_correction_policy as policy
                require(encoded(policy.counts(prior_state)) == encoded(policy.counts(state)), 'original_native_counts')
                origin = {'run': {k: prior_run[k] for k in ('id', 'run_attempt', 'head_sha', 'head_branch', 'event', 'path', 'status', 'conclusion')},
                    'artifact': {'id': prior_meta['id'], 'name': prior_meta['name'], 'digest': prior_meta['digest'],
                        'run_id': prior_run['id'], 'head_sha': prior_run['head_sha']},
                    'ledger_sha256': existing.sha((prior_state/'ledger.json').read_bytes()),
                    'checkpoint_sha256': existing.sha((prior_state/'checkpoint.json').read_bytes())}
        operations = accepted_operations(state, inputs, context['expected'],
            serving_proof=context['serving_proof'], node_call=node_call)
        require(encoded(operations) == encoded(receipt['operations']), 'authenticated_aggregate_lineage')
        node_call('validate', {'receipt_text': receipt_raw.decode(), 'expected': context['expected']})
        anchor = {'repository': existing.REPOSITORY,
            'run': {k: run[k] for k in ('id', 'run_attempt', 'head_sha', 'head_branch', 'event', 'path', 'status', 'conclusion')},
            'artifact': {'id': meta['id'], 'name': meta['name'], 'digest': meta['digest'], 'run_id': run['id'], 'head_sha': run['head_sha']},
            'receipt_path': receipt_path(), 'receipt_sha256': existing.sha(receipt_raw),
            'ledger_sha256': existing.sha((state/'ledger.json').read_bytes()), 'checkpoint_sha256': existing.sha((state/'checkpoint.json').read_bytes())}
        if origin is not None:
            anchor['aggregate_origin'] = origin
        return {'receipt_text': receipt_raw.decode(), 'expected': context['expected'], 'anchor': anchor,
            'serving_proof': context['serving_proof'], 'candidate_inputs': context['candidate_inputs']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('finalize-smoke', 'authenticate-owner', 'reuse-smoke'))
    parser.add_argument('--state', type=Path); parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'finalize-smoke':
        require(args.state is not None, 'state_required'); value = finalize_smoke(args.state, args.inputs)
    else:
        value = authenticate_owner(args.inputs)
        if args.action == 'reuse-smoke':
            value = node('reuse', value)
    atomic_json(args.output, value)


if __name__ == '__main__':
    main()
