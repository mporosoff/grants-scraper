"""Fixed, no-provider derivation of the retained VPR catalog correction.

The original refresh artifact remains authoritative. This module never collects
sources or treats a cache as a release candidate. Provider execution belongs to
the existing serialized catalog executor and its single durable ledger.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch
import zipfile

from tools import release_candidate as release

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/catalog_vpr_correction_v1.json'
VERSION = 'catalog-vpr-source-correction-v1'
_smoke_dispatch = None


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_source_correction_' + reason)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def plan():
    value = json.loads(CONFIG.read_bytes())
    require(value['version'] == VERSION and value['maximum_attempts'] == 10
            and value['maximum_microusd'] == 34837 and value['native_counts'] == 0
            and value['retries'] == 0, 'fixed_scope')
    return value


def gh(path):
    return subprocess.check_output(['gh', 'api', 'repos/' + plan()['repository'] + '/' + path], timeout=60)


def fetch_candidate(destination, *, api=gh):
    """Read the named original public artifact, including its authenticated ZIP digest."""
    p = plan()
    meta = json.loads(api('actions/runs/' + p['candidate_run']))
    require(meta['id'] == int(p['candidate_run']) and meta['head_sha'] == p['prior_sha']
            and meta['head_branch'] == 'main' and meta['path'] == '.github/workflows/refresh-opportunities.yml'
            and meta['event'] in ('push', 'schedule', 'workflow_dispatch') and meta['status'] == 'completed', 'original_refresh_run')
    artifact = json.loads(api('actions/artifacts/' + str(p['candidate_artifact_id'])))
    require(artifact['id'] == p['candidate_artifact_id'] and artifact['digest'] == p['candidate_artifact_digest']
            and artifact['name'] == 'candidate-' + p['candidate_id'] and artifact['expired'] is False
            and artifact['workflow_run']['id'] == meta['id']
            and artifact['workflow_run']['head_sha'] == p['prior_sha'], 'original_artifact')
    raw = api('actions/artifacts/' + str(p['candidate_artifact_id']) + '/zip')
    require('sha256:' + sha(raw) == p['candidate_artifact_digest'], 'original_zip_digest')
    destination = Path(destination)
    require(not destination.exists(), 'new_artifact_destination')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = [i for i in archive.infolist() if not i.is_dir()]
        require(len(entries) <= 200 and len({i.filename for i in entries}) == len(entries)
                and sum(i.file_size for i in entries) <= 100 * 1024 * 1024, 'bounded_public_artifact')
        for item in entries:
            require((item.external_attr >> 16) & 0o170000 != 0o120000, 'artifact_symlink')
            target = release.checked_path(destination, item.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    release.load(destination, p['candidate_id'])
    return {'run': meta['id'], 'artifact_id': artifact['id'], 'artifact_digest': artifact['digest']}


def prior_inputs(destination):
    p = plan()
    for name in ('data/opportunities.js', 'data/source_records.json'):
        raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', p['prior_sha'] + ':' + name])
        require(sha(raw) == p['source_pins']['prior/' + name], 'prior_git_bytes')
        target = Path(destination) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def derive_sources(candidate, prior):
    """Apply the corrected incremental-window resolver to exact retained observations."""
    from scripts.sources.merge import load_catalog, resolve_live_records, rebuild_catalog, _resolve_identity_before_selection
    from scripts.sources.registry import AdapterResult
    from scripts.build_changes import diff_catalogs
    p = plan(); candidate, prior = Path(candidate), Path(prior)
    manifest = release.load(candidate, p['candidate_id'])
    for label, root in (('candidate', candidate / 'files'), ('prior', prior)):
        for name in ('data/opportunities.js', 'data/source_records.json'):
            require(sha((root / name).read_bytes()) == p['source_pins'][label + '/' + name], 'source_bytes')
    old = load_catalog(prior / 'data/opportunities.js')
    new = load_catalog(candidate / 'files/data/opportunities.js')
    oldcache = json.loads((prior / 'data/source_records.json').read_bytes())
    newcache = json.loads((candidate / 'files/data/source_records.json').read_bytes())
    fresh = newcache['sources']['vpr-email']
    observed = AdapterResult(slug='vpr-email', display_name=fresh['source'], source_type='Internal', ok=True,
        records=copy.deepcopy(fresh['records']), record_count=len(fresh['records']),
        diagnostics=copy.deepcopy(fresh['diagnostics']), min_records=1, max_records=500, snapshot_complete=False)
    source_cache = copy.deepcopy(oldcache)
    _resolve_identity_before_selection([observed], source_cache, date.fromisoformat(p['as_of']), allow_fetch=False)
    with patch('scripts.sources.merge.iso_utc', return_value=fresh['fetched_at']):
        live, updated, lifecycle = resolve_live_records([observed], source_cache, date.fromisoformat(p['as_of']))
    live_by_id = {r['opportunity_id']: r for r in live}
    candidate_by_id = {r['opportunity_id']: r for r in new['opportunities']}
    old_by_id = {r['opportunity_id']: r for r in old['opportunities']}
    restored = sorted(set(lifecycle[0]['retained_outside_window_ids']) - set(candidate_by_id))
    require(restored == p['restored_ids'], 'exact_four_restored_rows')
    withheld = set(lifecycle[0]['identity_collision_ids'])
    require(withheld == set(p['withheld_ids']), 'exact_identity_collisions')
    rows = [copy.deepcopy(r) for r in new['opportunities'] if r['opportunity_id'] not in withheld]
    rows += [copy.deepcopy(old_by_id[i]) for i in restored]
    for row in rows:
        observation = live_by_id.get(row['opportunity_id'])
        if observation:
            for field in ('source_last_seen_date', 'source_observation'):
                row[field] = observation[field]
    temporary = rebuild_catalog(new, rows, [observed], lifecycle)
    corrected = copy.deepcopy(new)
    for key in ('opportunities', 'record_count', 'status_counts', 'facets', 'search_index'):
        corrected[key] = temporary[key]
    corrected['diagnostics']['quality'] = temporary['diagnostics']['quality']
    diagnostics = corrected['diagnostics']['additional_sources']
    diagnostics['source_record_counts'] = temporary['diagnostics']['additional_sources']['source_record_counts']
    diagnostics['lifecycle'] = [lifecycle[0] if r['slug'] == 'vpr-email' else r for r in diagnostics['lifecycle']]
    for row in diagnostics['adapters']:
        if row['slug'] == 'vpr-email':
            row['snapshot_complete'] = False
    cache = copy.deepcopy(newcache)
    cache['sources']['vpr-email'] = updated['sources']['vpr-email']
    corrected_by_id = {r['opportunity_id']: r for r in corrected['opportunities']}
    for ident, original in {**candidate_by_id, **{i: old_by_id[i] for i in restored}}.items():
        if ident in withheld:
            continue
        preserved = {k: v for k, v in corrected_by_id[ident].items() if k not in ('source_last_seen_date', 'source_observation')}
        require(preserved == original, 'complete_original_fields')
    changes = diff_catalogs(old, corrected, as_of=date.fromisoformat(p['as_of']))
    require(not any(e['type'] == 'closed_or_removed' and e['opportunity_id'] in restored for e in changes), 'false_closure')
    require(all(cache['sources'][k] == v for k, v in newcache['sources'].items() if k != 'vpr-email'), 'other_source_snapshots')
    outputs = {'corrected-catalog.json': corrected, 'corrected-source-cache.json': cache}
    require({name: sha(release.encoded(value)) for name, value in outputs.items()} == p['prepared_pins'], 'frozen_derivation')
    return outputs, {'version': VERSION, 'basis_candidate_id': manifest['candidate_id'],
        'original_generation_sha': manifest['generation_sha'], 'original_generation_run': manifest['generation_run_id'],
        'restored_ids': restored, 'withheld_ids': sorted(withheld), 'catalog_record_count': len(rows), 'source_requests': 0,
        'scientific_requests': 0, 'provider_requests': 0, 'native_count_calls': 0}


def verify_inputs(root):
    root = Path(root); p = plan()
    release.load(root / 'original-candidate', p['candidate_id'])
    pins = p['prepared_pins'] | {'corpus.json': p['corpus_file_sha256']}
    pins.update({row['body_file']: row['body_sha256'] for row in p['embedding_requests'] + p['smoke_requests']})
    release.verify_files(root, pins)
    manifest = json.loads((root / 'inputs.json').read_bytes())
    require(manifest['version'] == VERSION and manifest['plan_sha256'] == sha(CONFIG.read_bytes())
            and manifest['files'] == pins, 'input_manifest')
    return {'root': root, 'manifest': manifest, 'candidate_root': root / 'original-candidate'}


def prepare_inputs(destination):
    """Materialize only pinned public sources/bodies. Does not reserve or spend."""
    destination = Path(destination)
    if destination.exists():
        return verify_inputs(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='catalog-correction-', dir=destination.parent) as temp:
        work = Path(temp); candidate = work / 'original-candidate'; prior = work / 'prior'
        anchor = fetch_candidate(candidate)
        prior_inputs(prior)
        values, derivation = derive_sources(candidate, prior)
        for name, value in values.items():
            release.write_json(work / name, value)
        subprocess.run(['node', str(ROOT / 'tools/catalog_correction_bodies.mjs'), str(work)], cwd=ROOT, check=True, timeout=60)
        p = plan(); pins = p['prepared_pins'] | {'corpus.json': p['corpus_file_sha256']}
        pins.update({r['body_file']: r['body_sha256'] for r in p['embedding_requests'] + p['smoke_requests']})
        release.verify_files(work, pins)
        release.write_json(work / 'inputs.json', {'version': VERSION, 'plan_sha256': sha(CONFIG.read_bytes()),
            'original_artifact': anchor, 'derivation': derivation, 'files': pins})
        # These are fixed public Git blobs, retained for reproducible provenance.
        work.rename(destination)
    return verify_inputs(destination)


def accepted_vector_packet(state, inputs):
    """Revalidate all seven immutable ledger/cache/receipt triples, never dispatch."""
    from tools.catalog_correction_executor import CatalogRunner, input_body
    from tools import catalog_correction_policy as authority
    verified = verify_inputs(inputs)
    runner = CatalogRunner(state, verified['root'])
    ledger = runner.ledger.read(); authority.history(ledger); authority.counts(state)
    responses, lineage, dates = [], [], []
    for index in range(1, 8):
        name = f'embedding-{index}'; body = input_body(inputs, name)
        payload = runner.cached(name, body)
        key = authority.logical_key(name)
        rows = [r for r in ledger['requests'] if r['key'] == key]
        require(len(rows) == 1 and rows[0]['status'] == 'valid', 'complete_accepted_vector_owner')
        row = rows[0]
        cache_path = Path(state) / 'cache' / (key + '.json')
        receipt_path = Path(state) / 'receipts' / (row['id'] + '.json')
        raw_cache, raw_receipt = cache_path.read_bytes(), receipt_path.read_bytes()
        cached, receipt = json.loads(raw_cache), json.loads(raw_receipt)
        require(receipt['status'] == 'valid' and receipt['http_status'] == 200
                and receipt['request_id'] == row['id'] and receipt['key'] == key
                and receipt['body_sha256'] == row['body_sha256'] and receipt['code_sha'] == row['code_sha']
                and receipt['usage'] == row['usage'] and receipt['charged_microusd'] == row['charged_microusd']
                and receipt['response_sha256'] == cached['response_sha256'], 'complete_terminal_vector_receipt')
        completed = datetime.fromisoformat(receipt['completed_at'].replace('Z', '+00:00'))
        require(completed.tzinfo is not None, 'actual_completion_time')
        dates.append((completed, receipt['completed_at']))
        responses.append({'body': body, 'payload': payload, 'request_id': row['id'],
            'wire_bytes': len((Path(inputs) / authority.operation(name)['body_file']).read_bytes()),
            'response_bytes': len(cached['response_text'].encode('utf8')), 'elapsed_seconds': receipt['elapsed_seconds']})
        lineage.append({'name': name, 'purpose': row['purpose'], 'key': key, 'request_id': row['id'],
            'code_sha': row['code_sha'], 'body_sha256': row['body_sha256'],
            'cache_sha256': sha(raw_cache), 'receipt_sha256': sha(raw_receipt),
            'response_sha256': cached['response_sha256'], 'usage': row['usage'],
            'charged_microusd': row['charged_microusd'], 'completed_at': receipt['completed_at']})
    require(runner.ledger.read() == ledger, 'owner_changed_during_export')
    p = plan()
    return {'responses': responses, 'generatedAt': max(dates)[1], 'preprocessingSha': p['hybrid_sha256'],
        'sourceHashes': {'assets/search-hybrid.js': p['hybrid_sha256'],
            'corrected-catalog.json': p['prepared_pins']['corrected-catalog.json'],
            'data/subtopics.js': verified['manifest']['derivation'].get('subtopics_sha256') or
                sha((verified['candidate_root'] / 'files/data/subtopics.js').read_bytes())}}, lineage


def validate_vector_prefix(state, inputs, name, payload):
    """Apply the existing production gates before accepting the next paid batch."""
    from tools.catalog_correction_executor import CatalogRunner, input_body
    require(name in {f'embedding-{i}' for i in range(1, 8)}, 'named_embedding_prefix')
    verify_inputs(inputs)
    runner = CatalogRunner(state, inputs)
    count = int(name.removeprefix('embedding-'))
    responses = []
    for index in range(1, count + 1):
        prior = f'embedding-{index}'; body = input_body(inputs, prior)
        responses.append({'body': body, 'payload': payload if index == count else runner.cached(prior, body)})
    with tempfile.TemporaryDirectory(prefix='catalog-prefix-', dir=Path(inputs).parent) as temp:
        path = Path(temp) / 'prefix.json'
        release.write_json(path, {'responses': responses, 'preprocessingSha': plan()['hybrid_sha256']})
        raw = subprocess.check_output(['node', str(ROOT / 'tools/catalog_correction_vectors.mjs'),
            str(Path(inputs).resolve()), str(path.resolve()), '--validate-prefix'], cwd=ROOT, timeout=120)
    result = json.loads(raw)
    require(result == {'accepted_prefix': count, 'complete': count == 7, 'provider_requests': 0}, 'complete_prefix_gates')
    return result


def export_vectors(state, inputs, destination):
    """Emit only safe derived assets. The complete provider responses stay in the owner."""
    packet, lineage = accepted_vector_packet(state, inputs)
    destination = Path(destination)
    require(not destination.exists(), 'immutable_export_destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='catalog-vector-export-', dir=destination.parent) as temp:
        work = Path(temp); public = work / 'safe-export'; public.mkdir()
        release.write_json(work / 'accepted-responses.json', packet)
        subprocess.run(['node', str(ROOT / 'tools/catalog_correction_vectors.mjs'), str(Path(inputs).resolve()),
            str(work / 'accepted-responses.json'), str(public)], cwd=ROOT, check=True, timeout=120)
        for name in plan()['prepared_pins']:
            shutil.copyfile(Path(inputs) / name, public / name)
        files = {p.relative_to(public).as_posix(): sha(p.read_bytes()) for p in public.rglob('*') if p.is_file()}
        from tools.catalog_correction_policy import PLAN_SHA
        manifest = {'version': VERSION, 'source_plan_sha256': sha(CONFIG.read_bytes()), 'spending_plan_sha256': PLAN_SHA,
            'original_candidate_id': plan()['candidate_id'], 'original_generation_sha': plan()['prior_sha'],
            'corpus_sha256': plan()['corpus_sha256'], 'generated_at': packet['generatedAt'],
            'operations': lineage, 'files': files, 'new_provider_requests_for_export': 0,
            'new_native_counts_for_export': 0, 'source_collection_requests': 0}
        for name in files:
            release.privacy_check(public / name)
        release.write_json(public / 'export.json', manifest)
        public.rename(destination)
    return manifest


VECTOR_FILES = {'data/search-v2-voyage-vectors.f16', 'data/search-v2-voyage-canaries.json',
    'data/search-v2-voyage-manifest.json', 'evaluation/search_v2_hybrid_vector_build.json'}


def public_catalog(value):
    from scripts.sources.merge import OPERATIONAL_SOURCE_EVIDENCE_KEYS
    value = copy.deepcopy(value)
    lifecycle = value['diagnostics']['additional_sources']['lifecycle']
    value['diagnostics']['additional_sources']['lifecycle'] = [
        {k: v for k, v in row.items() if k not in OPERATIONAL_SOURCE_EVIDENCE_KEYS} for row in lifecycle]
    return value


def verify_export(export_root, state, inputs):
    from tools.catalog_correction_policy import PLAN_SHA
    export_root = Path(export_root)
    _, lineage = accepted_vector_packet(state, inputs)
    value = json.loads((export_root / 'export.json').read_bytes())
    require(value['version'] == VERSION and value['source_plan_sha256'] == sha(CONFIG.read_bytes())
            and value['spending_plan_sha256'] == PLAN_SHA
            and value['original_candidate_id'] == plan()['candidate_id']
            and value['original_generation_sha'] == plan()['prior_sha']
            and value['corpus_sha256'] == plan()['corpus_sha256']
            and value['operations'] == lineage, 'exact_export_lineage')
    require(set(value['files']) == VECTOR_FILES | set(plan()['prepared_pins']), 'safe_export_inventory')
    require({p.relative_to(export_root).as_posix() for p in export_root.rglob('*') if p.is_file()}
            == set(value['files']) | {'export.json'}, 'no_unmanifested_export_material')
    release.verify_files(export_root, value['files'])
    require(all(value['files'][k] == v for k, v in plan()['prepared_pins'].items()), 'export_source_bytes')
    return value


def validate_context_packet(context, candidate_root, export_root, state, inputs):
    """Pure binding after the caller authenticates all three workflow artifacts."""
    from scripts.sources.merge import load_catalog
    from tools.offline_spend import encoded
    candidate_root, export_root, inputs = Path(candidate_root), Path(export_root), Path(inputs)
    prepared = verify_inputs(inputs); p = plan()
    exported = verify_export(export_root, state, inputs)
    candidate = release.load(candidate_root, context['candidate']['candidate_id'])
    require(context['version'] == 'catalog-correction-smoke-context-v1'
            and context['source_plan_sha256'] == sha(CONFIG.read_bytes())
            and context['candidate']['manifest_sha256'] == sha((candidate_root / 'candidate.json').read_bytes())
            and context['correction_export']['export_sha256'] == sha((export_root / 'export.json').read_bytes()), 'authenticated_context_files')
    lineage = candidate.get('source_correction')
    require(isinstance(lineage, dict) and lineage['version'] == VERSION
            and lineage['source_plan_sha256'] == context['source_plan_sha256']
            and lineage['spending_plan_sha256'] == exported['spending_plan_sha256']
            and lineage['export_sha256'] == context['correction_export']['export_sha256']
            and lineage['owner_run'] == context['correction_export']['owner_run']
            and lineage['original_candidate_id'] == p['candidate_id']
            and candidate['generation_sha'] == p['prior_sha'], 'candidate_affected_generation_lineage')
    original = release.load(prepared['candidate_root'], p['candidate_id'])
    require(candidate['original_generation'] == {k: original[k] for k in (
        'generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
        'generation_dependencies', 'generation_baseline', 'generation_files', 'semantic_identity')}, 'original_generation_preserved')
    changed_generated = {k for k, v in original['generation_files'].items() if candidate['files'].get(k) != v}
    allowed = VECTOR_FILES | {'data/opportunities.js', 'data/catalog-metadata.js', 'data/source_records.json',
        'README.md', 'PROJECT.md', 'evaluation/release_coverage.json'} | {k for k in original['files'] if k.startswith('feeds/')}
    require(changed_generated <= allowed, 'unaffected_generation_retained')
    require(all(candidate['files'][name] == exported['files'][name] for name in VECTOR_FILES), 'exact_owned_vector_export')
    files = candidate_root / 'files'
    require(load_catalog(files / 'data/opportunities.js') == public_catalog(json.loads((inputs / 'corrected-catalog.json').read_bytes()))
            and json.loads((files / 'data/source_records.json').read_bytes()) == json.loads((inputs / 'corrected-source-cache.json').read_bytes()), 'complete_corrected_public_sources')
    allowlist = json.loads((files / 'workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())
    require(context['generations'] == {'current': allowlist['current'], 'previous': allowlist['previous']}
            and allowlist['current']['corpus_sha256'] == p['corpus_sha256']
            and allowlist['previous'] == json.loads((prepared['candidate_root'] / 'files/workers/search-voyage-proxy/generated/corpus-allowlist.json').read_bytes())['previous'], 'full_current_and_previous_generation')
    vector_manifest = json.loads((files / 'data/search-v2-voyage-manifest.json').read_bytes())
    require(allowlist['current']['model_space_fingerprint'] == vector_manifest['model_space_fingerprint'], 'actual_owned_model_space')
    corpus = json.loads((inputs / 'corpus.json').read_bytes())
    shared_rows = [r for r in corpus if r['passage_id'] == p['smoke_passage_id']]
    require(len(shared_rows) == 1 and sha(shared_rows[0]['text'].encode('utf8')) == p['smoke_passage_sha256'], 'smoke_owned_passage')
    shared = {'passage_id': p['smoke_passage_id'], 'text_sha256': p['smoke_passage_sha256'], 'text': shared_rows[0]['text']}
    expected = {'version': 'search-worker-smoke-inputs-v1',
        'worker_origin': 'https://funding-finder-voyage-search.urochestercheme.workers.dev',
        'worker_input_fingerprint': candidate['worker_fingerprint'], 'query': 'catalysis', 'shared_passage': shared,
        **{key: {field: allowlist[key][field] for field in ('corpus_sha256', 'model_space_fingerprint')} for key in ('current', 'previous')},
        'operations': []}
    for i, name in enumerate(('embed', 'current-rerank', 'previous-rerank')):
        body = {'query': 'catalysis'} if i == 0 else {'query': 'catalysis',
            **expected['current' if i == 1 else 'previous'], 'candidates': [shared]}
        public = encoded(body).decode('utf8'); provider = (inputs / ('smoke-' + name + '-provider.json')).read_bytes().decode('utf8')
        expected['operations'].append({'purpose': 'cb-fc-cat-smoke-' + name,
            'path': '/embed-query' if i == 0 else '/rerank', 'public_body_text': public,
            'provider_body_text': provider, 'provider_body_sha256': sha(provider.encode('utf8')),
            'external_http_body_sha256': sha(public.encode('utf8'))})
    # Two candidate-generated inputs may differ before publication. Every code
    # module still has to be the protected refresh checkout's exact Git bytes.
    overrides = {'workers/search-voyage-proxy/generated/corpus-allowlist.json', 'workers/search-voyage-proxy/wrangler.jsonc'}
    for name in candidate['files']:
        if name.startswith('workers/search-voyage-proxy/') and name not in overrides:
            raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', context['refresh']['head_sha'] + ':' + name])
            require(sha(raw) == candidate['files'][name], 'protected_worker_runtime')
    return {'expected': expected, 'candidate_inputs': {name: (files / name).read_bytes().decode('utf8') for name in sorted(overrides)}}


def smoke_dispatch_inputs(state, inputs, name):
    """Authenticate one named wrapper; caller JSON alone cannot authorize it."""
    from tools.catalog_smoke_receipt import load_context
    global _smoke_dispatch
    _smoke_dispatch = None
    require(name in ('smoke-embed', 'smoke-current-rerank', 'smoke-previous-rerank'), 'fixed_smoke_name')
    context = load_context(state, inputs)
    operations = [o for o in context['expected']['operations'] if o['purpose'] == 'cb-fc-cat-' + name]
    require(len(operations) == 1, 'single_authenticated_smoke_body')
    operation = operations[0]
    external = context['external_bodies'][name]
    require(external == json.loads(operation['public_body_text']), 'authenticated_public_wrapper')
    proof = context['serving_proof']
    _smoke_dispatch = {'name': name, 'proof': proof, 'proof_sha256': sha(release.encoded(proof)),
        'body': copy.deepcopy(external), 'provider_body': json.loads(operation['provider_body_text']),
        'authenticated_at': time.monotonic()}
    return {'external_body': external, 'serving_proof': proof}


def verify_smoke_dispatch(name, provider_body, external_body, serving_proof):
    """Recheck the fresh authenticated context immediately before reservation."""
    value = _smoke_dispatch
    require(value is not None and value['name'] == name and serving_proof is value['proof'],
        'smoke_context_must_be_authenticated_in_this_process')
    require(0 <= time.monotonic() - value['authenticated_at'] <= 300,
        'fresh_smoke_dispatch_proof')
    require(sha(release.encoded(serving_proof)) == value['proof_sha256']
        and external_body == value['body'] and provider_body == value['provider_body'],
        'unchanged_authenticated_smoke_dispatch')
    return copy.deepcopy(value['body'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'export-vectors'])
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--inputs', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare_inputs(args.destination)
        print(json.dumps({'root': str(result['root']), 'manifest': result['manifest']}))
    else:
        require(args.state is not None and args.inputs is not None, 'owned_export_arguments')
        print(json.dumps(export_vectors(args.state, args.inputs, args.destination)))


if __name__ == '__main__':
    main()
