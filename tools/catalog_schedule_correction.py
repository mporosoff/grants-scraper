"""Finite, zero-request schedule repair of release 343's retained candidate.

The failed parent's immutable bytes remain evidence. Only source-bound cached
quotes are reinterpreted; source clocks, spending, science, teams and vectors
are preserved. The existing access-correction job owns this named derivation.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from tools import catalog_smoke_receipt as auth
from tools import release_candidate as c
from tools.offline_spend import identity

VERSION = 'catalog-schedule-correction-20261016-v1'
PARENT = '484141e95d4f2ffd8e6d96f6eabf953b69e587934fc133497df691fa9510bb49'
RUN, ATTEMPT = 38927032149, 2
EVENT_SHA = '2fb95b02e646e5cd02108c845451021b2d582f4e'
GENERATION_SHA = '6ca8396cb5c3a879439312a06f9a85103b480792'
MANIFEST_SHA = 'dd9a25060b325801dbf1f59c5d2a2638171571ae6d63f3fa8ec8c3a174fa9b0c'
LEDGER_SHA = 'c2a91f320b4bef0f185dab2cea9fd0e9c35a284212c54973322be25303de2ac4'
ARCHIVE_ID = 12061543199
ARCHIVE_SHA = '9d6fc3fd1beb78badda2c001da409231e6592a09027b43ace8d38cfd82c1e7f7'
ARTIFACTS = {
    'candidate': (12061710743, 'candidate-' + PARENT, 'ae329a1f6ecff3c672ce5787a4119348ec90e0276b0f248350ff8102e08addd8'),
    'state': (12061426734, f'generation-spend-state-{RUN}-2', 'f65238309bda541f5bd7b0d980cc8dda3474441985495622ca52d7cde6a6740b'),
    'reservation': (12061036617, f'generation-spend-reservation-{RUN}-2', '00b5e1c14f25a83e22260ec4855e26652a8877a3de4c1db47ac629cfb6e12946'),
    'validation': (12060329629, f'validation-{PARENT}-2', 'e163034190b3f3e23f2ad59cd2066c91eef02b53b1ffd72947bc770a82bc7a0f'),
    'prior_state': (12058095540, f'generation-spend-state-{RUN}-1', '9692de304d881007208c5fa88ea70321f32e46d7deb5b23582e634587d127439'),
    'plan': (12060552023, 'release-plan-2', '8333d7e73da6cad9071d8306992cca39407b00ee51a788f87016cc93a69d442d'),
}
ARCHIVED_IDS = {12056814203, 12057940211, 12058015415, 12058095540, 12060104681,
                12060329629, 12060552023, 12061036617, 12061408333, 12061426734, 12061710743}
STAGE = 'catalog-access-correction'
SOURCE_REPAIR_FILES = {'scripts/extract_document_evidence.py', 'scripts/notice_schedule.py'}
CHANGED = frozenset({'arpa-h:surpass', 'arpa-h:unique', '364024'})
QUOTE_REPAIRS = CHANGED - {'364024'}
PUBLIC_FIELDS = frozenset({'deadlines', 'submission_requirements', 'next_submission', 'document_evidence',
    'document_search_text', 'has_preliminary_stage', 'preliminary_stage_type', 'preliminary_required'})
PACKAGE = 'data/search-v2-release.json'


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_schedule_correction_' + reason)


def value_hash(value):
    return c.digest(c.encoded(value))


def reject_quarantined(manifest):
    require(manifest.get('candidate_id') != PARENT, 'rejected_parent_requires_named_schedule_correction')


def plan(root, environment):
    expected = {'GITHUB_REPOSITORY': 'mporosoff/grants-scraper', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF':
        'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
        'CANDIDATE_ID': PARENT, 'CANDIDATE_RUN': str(RUN), 'REQUESTED_STAGE': STAGE}
    require(all(environment.get(k) == v for k, v in expected.items()), 'exact_protected_manual_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
        and environment.get('QUALIFICATION_PILOT') != 'true'
        and environment.get('FINAL_INTEGRATION_REQUIRED') != 'true', 'no_other_generation_or_recovery')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'), 'candidate_id': PARENT,
        'candidate_run': str(RUN), 'openai': 'false', 'anthropic': 'false', 'team_mode': 'maintenance',
        'reason': 'Named retained schedule interpretation; identical science, teams and vectors; no new allowance'}


def archive_files(raw):
    with tempfile.TemporaryDirectory(prefix='schedule-auth-') as temporary:
        auth.unpack_public(raw, temporary)
        base = Path(temporary)
        return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob('*') if p.is_file()}


def authenticate(parent_bundle, *, api=auth.existing.api):
    from tools.release_checkpoint_archive import preserved_artifacts, read_preserved_artifact
    cached = {}
    def read(path):
        if path not in cached:
            cached[path] = api(path)
        return cached[path]
    run = auth.json_value(read(f'actions/runs/{RUN}/attempts/{ATTEMPT}'))
    latest = auth.json_value(read(f'actions/runs/{RUN}'))
    expected = {'id': RUN, 'run_attempt': ATTEMPT, 'head_sha': EVENT_SHA, 'head_branch': 'main',
        'path': auth.REFRESH, 'event': 'push', 'status': 'completed', 'conclusion': 'failure'}
    require(all(run.get(k) == latest.get(k) == v for k, v in expected.items()), 'original_terminal_attempt')
    outer = auth.json_value(read(f'actions/artifacts/{ARCHIVE_ID}'))
    require(outer.get('id') == ARCHIVE_ID and outer.get('digest') == 'sha256:' + ARCHIVE_SHA,
            'independent_archive_pin')
    records = preserved_artifacts('mporosoff/grants-scraper', RUN, inventory=[outer], api=read)
    indexed = {row['id']: row for row in records}
    require(len(indexed) == len(records) and set(indexed) == ARCHIVED_IDS, 'complete_archive_inventory')
    packets = {}
    for role, (identifier, name, digest) in ARTIFACTS.items():
        metadata = indexed[identifier]
        require(metadata['name'] == name and metadata['digest'] == 'sha256:' + digest, 'original_artifact_pins')
        raw = read_preserved_artifact('mporosoff/grants-scraper', RUN, metadata, api=read)
        require(c.digest(raw) == digest, 'original_raw_zip')
        packets[role] = archive_files(raw)
    bundle = Path(parent_bundle)
    require(c.digest((bundle/'candidate.json').read_bytes()) == MANIFEST_SHA, 'parent_manifest_pin')
    original = c.load(bundle, PARENT)
    require(packets['candidate'] == {'candidate.json': (bundle/'candidate.json').read_bytes(),
        **{'files/' + n: (bundle/'files'/n).read_bytes() for n in original['files']}}, 'complete_parent')
    require(original['generation_sha'] == GENERATION_SHA and original['generation_run_id'] == str(RUN)
        and original['generation_run_attempt'] == str(ATTEMPT), 'original_generation')
    selected = auth.json_value(packets['plan']['release-plan.json'])
    require(selected['release_sha'] == GENERATION_SHA and selected['stage'] == 'generate'
        and selected['team_mode'] == 'maintenance', 'selected_protected_plan')
    validation = auth.json_value(packets['validation']['validation.json'])
    require(validation['candidate_id'] == PARENT and validation['generation_sha'] == GENERATION_SHA
        and validation['validation_sha'] == GENERATION_SHA and validation['production_mutated'] is False
        and validation['identity']['candidate_hashes'] == original['files']
        and validation['gates'] == {gate: 'passed' for gate in c.GATES}, 'parent_validation')
    state = packets['state']; prior = auth.json_value(packets['prior_state']['ledger.json'])
    ledger = auth.json_value(state['ledger.json']); reservation = auth.json_value(packets['reservation']['spend-reservation.json'])
    require(c.digest(state['ledger.json']) == LEDGER_SHA and ledger['logical_id'] == prior['logical_id'] == f'offline-{RUN}'
        and ledger['limit_microusd'] == prior['limit_microusd'] == 2_000_000
        and ledger['max_requests'] == prior['max_requests'] == 300 and prior['requests'] == []
        and ledger['events'][:len(prior['events'])] == prior['events']
        and len(ledger['requests']) == 12 and all(r['status'] == 'valid' for r in ledger['requests'])
        and sum(r['charged_microusd'] for r in ledger['requests']) == 50_474
        and reservation == {'attempt': '2', 'maximum_logical_spend_usd': 2, 'mode': 'maintenance',
            'prior_ledger_hash': identity(prior), 'run_id': str(RUN)}, 'original_allowance')
    require(len([name for name in state if name.startswith('cov4-cache/')]) == 12, 'completed_verdict_inventory')
    cp = auth.json_value(state['document-checkpoint/checkpoint.json'])
    require(cp['run_id'] == str(RUN) and cp['run_attempt'] == '2' and cp['generation_sha'] == GENERATION_SHA,
            'document_checkpoint_owner')
    for name, digest in cp['files'].items():
        raw = state['document-checkpoint/blobs/' + digest]
        require(c.digest(raw) == digest and raw == packets['candidate']['files/' + name], 'document_checkpoint_bytes')
    spending = {'original_logical_id': ledger['logical_id'], 'limit_microusd': ledger['limit_microusd'],
        'max_requests': ledger['max_requests'], 'requests_used': 12, 'charged_microusd': 50_474,
        'state_hashes': {n: c.digest(raw) for n, raw in sorted(state.items())},
        'independent_archive_id': ARCHIVE_ID, 'independent_archive_sha256': ARCHIVE_SHA,
        'new_source_requests': 0, 'new_document_ai_requests': 0, 'new_team_requests': 0,
        'new_vector_requests': 0, 'new_allowance_microusd': 0, 'ledger_writes': 0}
    return original, spending


def dependency_scope(root, original, *, materialized=False):
    from tools.release_dependencies import changed_groups, snapshot
    changes = changed_groups(original['dependency_groups'], snapshot(root))
    require(set(changes.get('source', [])) <= SOURCE_REPAIR_FILES and not changes.get('teams')
        and not changes.get('semantic'), 'bounded_dependency_changes')
    c.git(root, 'merge-base', '--is-ancestor', GENERATION_SHA, 'HEAD')
    if not materialized:
        c.verify_files(root, original['runtime_baseline'])


def projection(parent_root, audit_at):
    from scripts import extract_document_evidence as e
    from scripts.build_catalog import compact_catalog_payload, catalog_javascript_bytes, catalog_metadata_javascript_bytes
    from scripts.enrich_catalog import read_catalog
    from scripts.notice_structure_cache import StructureCache
    from scripts.submission_schedule import project
    from scripts.subtopic_records import read_cache
    from tools.verify_notice_publication import verify
    parent = Path(parent_root); before = read_catalog(parent/'data/opportunities.js')
    cache = c.read_json(parent/'data/document_evidence.json'); updated = deepcopy(cache); after = deepcopy(before)
    stamp = before['document_evidence_generated_at']; clock = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    audit = datetime.fromisoformat(audit_at.replace('Z', '+00:00'))
    require(audit.tzinfo is not None and clock.tzinfo is not None and audit >= clock, 'audit_clock')
    proof = {}; changed = set()
    with tempfile.TemporaryDirectory(prefix='schedule-empty-structure-') as temporary:
        structure = StructureCache(temporary)
        for index, record in enumerate(before['opportunities']):
            identifier = str(record['opportunity_id'])
            if identifier not in CHANGED:
                continue
            entry = updated['records'][identifier]; original = cache['records'][identifier]
            source = e.source_for_record(record)
            require(source is not None and entry['status'] == 'current' and not entry.get('last_error')
                and entry['source_signature'] == e.source_signature(record, source), 'owned_current_evidence')
            for fact in entry['facts']:
                if fact.get('type') == 'deadline':
                    citation = fact.get('citation') or {}
                    require(citation.get('sha256') == entry['document']['sha256']
                        and citation.get('document_url') == entry['document']['url'] and bool(citation.get('quote')),
                        'source_bound_quote')
            if identifier in QUOTE_REPAIRS:
                e.quarantine_legacy_facts(record, source, entry, structure)
            replacement = project(e.merge_document_entry(record, entry), clock.date())
            replacement = compact_catalog_payload({'opportunities': [replacement]})['opportunities'][0]
            fields = {key for key in record.keys() | replacement.keys()
                      if record.get(key) != replacement.get(key) or (key in record) != (key in replacement)}
            require(fields and fields <= PUBLIC_FIELDS, 'only_schedule_fields')
            require(all(entry.get(key) == original.get(key) for key in ('document', 'source_signature', 'source_url',
                'checked_at', 'status', 'last_error', 'version_history', 'subtopics', 'subtopic_cov4')),
                'original_source_and_classification_receipts')
            after['opportunities'][index] = replacement; changed.add(identifier)
            proof[identifier] = {'before_sha256': value_hash(record), 'after_sha256': value_hash(replacement),
                'cache_before_sha256': value_hash(original), 'cache_after_sha256': value_hash(entry),
                'changed_fields': sorted(fields), 'source_checked_at': original['checked_at'],
                'document_sha256': original['document']['sha256'], 'interpretation_basis': 'retained_source_bound_quotes'}
    require(changed == CHANGED, 'complete_finite_correction')
    require(all(a == b for a, b in zip(before['opportunities'], after['opportunities'], strict=True)
                if str(a['opportunity_id']) not in CHANGED), 'unchanged_other_records')
    require(all(entry == updated['records'][key] for key, entry in cache['records'].items() if key not in QUOTE_REPAIRS)
        and cache.get('subtopic_only') == updated.get('subtopic_only') and cache['generated_at'] == updated['generated_at'],
        'unchanged_other_evidence')
    gate = verify(after, updated, read_cache(parent/'data/subtopics.js'), candidate_id=PARENT)
    require(gate['publication_ready'], 'strict_notice_projection')
    outputs = {'data/opportunities.js': catalog_javascript_bytes(after),
        'data/catalog-metadata.js': catalog_metadata_javascript_bytes(after),
        'data/document_evidence.json': (json.dumps(updated, ensure_ascii=False, separators=(',', ':')) + '\n').encode()}
    return outputs, {'records': proof, 'original_source_at': before['generated_at'], 'original_evidence_at': stamp,
        'retained_other_records': len(before['opportunities']) - len(CHANGED), 'strict_notice_gate': gate,
        'unchanged_source_cache_sha256': c.digest((parent/'data/source_records.json').read_bytes()),
        'source_requests': 0, 'provider_requests': 0}


def derive(parent_bundle, audit_at):
    from scripts.update_catalog_docs import load_catalog, render_docs, catalog_stats, update_catalog_asset_reference
    from scripts.build_feeds import build_feeds
    from scripts.build_changes import build_atom, _snapshot, _event_id, EVENT_LABELS
    parent = Path(parent_bundle)/'files'; outputs, proof = projection(parent, audit_at)
    with tempfile.TemporaryDirectory(prefix='schedule-projection-') as temporary:
        target = Path(temporary)/'workspace'; shutil.copytree(parent, target)
        for name, raw in outputs.items():
            c.checked_path(target, name).write_bytes(raw)
        catalog = load_catalog(target/'data/opportunities.js'); rows = {str(r['opportunity_id']): r for r in catalog['opportunities']}
        prior = c.read_json(parent/'feeds/changes.json'); changes = deepcopy(prior)
        for event in changes['events']:
            if str(event.get('opportunity_id')) in CHANGED and event.get('changed_at') == catalog['generated_at']:
                event['record'] = _snapshot(rows[str(event['opportunity_id'])])
        for identifier in sorted(CHANGED):
            detail = 'Retained official notice submission-stage interpretation corrected; source observation unchanged.'
            changes['events'].append({'id': _event_id('source_correction', rows[identifier], audit_at, detail),
                'type': 'source_correction', 'label': EVENT_LABELS['source_correction'], 'changed_at': audit_at,
                'opportunity_id': identifier, 'detail': detail, 'record': _snapshot(rows[identifier])})
        changes['events'].sort(key=lambda row: (row.get('changed_at', ''), row['id']), reverse=True)
        changes['generated_at'] = audit_at
        c.write_json(target/'feeds/changes.json', changes)
        (target/'feeds/changes.xml').write_text(build_atom(changes['events'], datetime.fromisoformat(audit_at)), encoding='utf-8', newline='\n')
        build_feeds(catalog, target/'feeds', as_of=datetime.fromisoformat(catalog['generated_at'].replace('Z', '+00:00')).date())
        outputs.update({p.relative_to(target).as_posix(): p.read_bytes() for p in (target/'feeds').rglob('*') if p.is_file()})
        rendered = render_docs((parent/'README.md').read_text(encoding='utf-8'), (parent/'PROJECT.md').read_text(encoding='utf-8'), catalog_stats(catalog))
        outputs.update(dict(zip(('README.md', 'PROJECT.md'), (text.encode() for text in rendered), strict=True)))
        for name in ('match_explorer.html', 'team_match.html'):
            outputs[name] = update_catalog_asset_reference((parent/name).read_text(encoding='utf-8'), catalog).encode()
        for name, raw in outputs.items():
            path = c.checked_path(target, name); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        package_receipt = Path(temporary)/'package.json'
        subprocess.run([shutil.which('node') or 'node', str(c.ROOT/'tools/catalog_schedule_package.mjs'),
            '--parent', str(parent), '--root', str(target), '--receipt', str(package_receipt)],
            check=True, timeout=120, capture_output=True)
        outputs[PACKAGE] = (target/PACKAGE).read_bytes(); proof['package'] = c.read_json(package_receipt)
    return outputs, proof


def receipt_for(original, spending, outputs, proof, audit_at):
    return {'version': VERSION, 'parent_candidate': PARENT, 'parent_manifest_sha256': MANIFEST_SHA,
        'parent_run': RUN, 'parent_attempt': ATTEMPT, 'audit_at': audit_at, 'spending': spending,
        'projection': proof, 'output_hashes': {n: c.digest(raw) for n, raw in sorted(outputs.items())},
        'retained_hashes': {n: h for n, h in original['files'].items() if n not in outputs}}


def verify_inputs(root, original, parent_bundle, receipt_path):
    receipt = c.read_json(receipt_path); authenticated, spending = authenticate(parent_bundle)
    require(original == authenticated, 'constructor_parent'); dependency_scope(root, original, materialized=True)
    outputs, proof = derive(parent_bundle, receipt['audit_at'])
    require(receipt == receipt_for(original, spending, outputs, proof, receipt['audit_at']), 'deterministic_replay')
    c.verify_files(root, receipt['output_hashes'] | receipt['retained_hashes'])
    require(c.facet_feed_names(root) == {n for n in original['files'] if c.FACET_FEED_NAME.fullmatch(n)}, 'complete_feed_inventory')
    return {n: h for n, h in receipt['retained_hashes'].items() if n in original['generation_files']}


def recover(root, parent_bundle, output, receipt_path):
    root = Path(root); plan(root, dict(os.environ)); original, spending = authenticate(parent_bundle)
    dependency_scope(root, original)
    require(not Path(output).exists() and not Path(receipt_path).exists(), 'new_destinations')
    audit_at = datetime.now(timezone.utc).isoformat(); outputs, proof = derive(parent_bundle, audit_at)
    receipt = receipt_for(original, spending, outputs, proof, audit_at)
    c.write_json(receipt_path, receipt)
    for name in original['files']:
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(parent_bundle)/'files'/name, destination)
    for name, raw in outputs.items():
        destination = c.checked_path(root, name); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)
    return c.create(root, output, parent=parent_bundle, access_correction=receipt_path)
