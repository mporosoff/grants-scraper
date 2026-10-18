"""Reconcile only reviewed SAM against one authenticated retained candidate.

This explicit maintenance stage has no new allowance. Its artifact family uses
the existing task-aware independent checkpoint transport so a retry cannot
silently restore an earlier original ledger after a later repair spent money.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from tools import release_candidate as c
from tools.fetch_release_artifact import fetch, repository_artifacts, artifact_bytes, run_artifacts
from tools.offline_ai_checkpoint import api
from tools.offline_spend import atomic_json, identity
from tools import release_checkpoint_archive as archive

VERSION = 'catalog-source-reconciliation-1'
STAGE = 'catalog-reconcile'
SLUG = 'sam-gov'
SOURCE_INPUTS = {'config/sam_gov.json', 'scripts/sources/sam_reviewed.py',
    'scripts/sources/sam_public.py', 'scripts/sources/adapters/sam_gov.py',
    'scripts/sources/sam_preflight.py', 'tools/sam_refresh_preflight.py', 'tools/require_sam_refresh.py'}
SEMANTIC_INPUTS = {'assets/search-hybrid.js', 'assets/search-retrieval.js',
    'tools/build_search_v2_voyage_vectors.mjs', 'tools/corpus_clock.mjs',
    'tools/run_budgeted_vectors.mjs', 'tools/catalog_reconcile_vectors.mjs',
    'tools/catalog_reconcile_spend.py', 'tools/offline_spend.py',
    'scripts/import_opportunity_team_model.py'}
OPERATION_FILES = SOURCE_INPUTS | SEMANTIC_INPUTS | {
    'tools/catalog_reconcile.py', 'tools/catalog_reconcile_spend.py',
    'tools/catalog_reconcile_vectors.mjs', 'tools/release_candidate.py',
    'tools/embedding_contract.mjs', 'tools/offline_spend.py', 'tools/build_search_release_package.mjs',
    'scripts/faculty_match.py', 'scripts/build_changes.py', 'scripts/build_feeds.py',
    'scripts/extract_document_evidence.py', 'scripts/submission_schedule.py',
    'scripts/update_catalog_docs.py', '.github/workflows/refresh-opportunities.yml'}
VECTOR_FILES = {'data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
    'data/search-v2-voyage-canaries.json', 'evaluation/search_v2_hybrid_vector_build.json'}
DERIVED_FILES = VECTOR_FILES | {'data/opportunities.js', 'data/source_records.json',
    'data/document_evidence.json', 'data/faculty_matches.js', 'data/catalog-metadata.js', 'data/search-v2-release.json',
    'workers/search-voyage-proxy/generated/corpus-allowlist.json',
    'README.md', 'PROJECT.md', 'evaluation/release_coverage.json'}


def require(ok, reason):
    if not ok:
        raise ValueError('catalog_reconcile_' + reason)


def operation_contract(root):
    return c.file_hashes(Path(root), sorted(OPERATION_FILES))


def source_operation_changed(before, after):
    return any(before.get(name) != after.get(name) for name in SOURCE_INPUTS | SEMANTIC_INPUTS)


def plan(root, environment):
    require(environment.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and environment.get('GITHUB_REF') == 'refs/heads/main'
            and environment.get('GITHUB_REPOSITORY') == 'mporosoff/grants-scraper'
            and environment.get('GITHUB_WORKFLOW_REF') ==
            'mporosoff/grants-scraper/.github/workflows/refresh-opportunities.yml@refs/heads/main',
            'protected_manual_stage')
    run, candidate = environment.get('CANDIDATE_RUN', ''), environment.get('CANDIDATE_ID', '')
    require(re.fullmatch('[1-9][0-9]*', run) and re.fullmatch('[a-f0-9]{64}', candidate), 'exact_parent_selector')
    require(not any(environment.get(k) for k in ('RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT'))
            and environment.get('QUALIFICATION_PILOT') != 'true', 'no_other_modes')
    return {'stage': STAGE, 'release_sha': c.git(root, 'rev-parse', 'HEAD'),
        'candidate_run': run, 'candidate_id': candidate, 'team_mode': 'maintenance',
        'openai': 'false', 'anthropic': 'false',
        'reason': 'Exact retained candidate; reviewed SAM only, original logical budget, no document/team generation'}


def prefix(candidate):
    return 'offline-ai-reconcile-' + candidate


def request_identity(rows):
    return identity([{k: row.get(k) for k in
        ('id', 'provider', 'model', 'stage', 'key', 'attempt', 'reserved_microusd')} for row in rows])


def unpack(raw, destination):
    destination = Path(destination)
    with archive._members(raw) as packet:
        for item in packet.infolist():
            target = c.checked_path(destination, item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(packet.read(item))


def original_state(repository, run, manifest, destination, *, root=None):
    read = lambda path: api(repository, path)
    meta = json.loads(read(f'actions/runs/{run}/attempts/{manifest["generation_run_attempt"]}'))
    require(meta.get('id') == int(run)
            and meta.get('run_attempt') == int(manifest['generation_run_attempt'])
            and isinstance(meta.get('head_sha'), str) and re.fullmatch('[a-f0-9]{40}', meta['head_sha'])
            and meta.get('head_branch') == 'main' and meta.get('path') == archive.SOURCE_WORKFLOW
            and meta.get('event') in {'push', 'schedule', 'workflow_dispatch'}
            and meta.get('status') == 'completed', 'original_generation_origin')
    # The event SHA is fixed when Actions creates the run. The protected plan
    # independently pins the main checkout used by generation, including when
    # all jobs are rerun after main advances or a failed job inherits its plan.
    from tools.plan_release import release_plan_sha
    planned = release_plan_sha(repository, run, manifest['generation_run_attempt'],
                               Path(destination) / 'original-plan')
    require(planned == manifest['generation_sha'], 'original_generation_plan')
    c.git(Path(root) if root is not None else c.ROOT, 'merge-base', '--is-ancestor', planned, 'HEAD')
    rows = run_artifacts(run, read, repository=repository)
    suffix = f'{run}-{manifest["generation_run_attempt"]}'
    selected = {}
    for role in ('reservation', 'state'):
        found = [r for r in rows if r['name'] == f'generation-spend-{role}-{suffix}']
        require(len(found) == 1 and found[0].get('expired') is False, 'original_spend_' + role)
        row = found[0]; raw = artifact_bytes(repository, run, row, read)
        require(c.digest(raw) == row['digest'].removeprefix('sha256:'), 'original_spend_digest')
        selected[role] = {'artifact_id': row['id'], 'zip_sha256': c.digest(raw)}
        unpack(raw, destination if role == 'state' else Path(destination) / 'original-reservation')
    value = c.read_json(Path(destination) / 'ledger.json')
    reservation = c.read_json(Path(destination) / 'original-reservation/spend-reservation.json')
    require(value['logical_id'] == 'offline-' + str(run) and value['limit_microusd'] == 2_000_000
            and value['max_requests'] == 300 and reservation['run_id'] == str(run)
            and reservation['attempt'] == manifest['generation_run_attempt']
            and reservation['mode'] == 'maintenance' and reservation['maximum_logical_spend_usd'] == 2,
            'original_budget_identity')
    return selected | {'ledger_sha256': identity(value)}


def restore(root, parent, state, output):
    """Newest paired private checkpoint wins across all runs of this parent."""
    root, parent, state, output = map(Path, (root, parent, state, output))
    environment = os.environ; repository = environment['GITHUB_REPOSITORY']
    manifest = c.load(parent, environment['CANDIDATE_ID'])
    require(manifest['generation_run_id'] == environment['CANDIDATE_RUN'], 'original_parent_run')
    parent_rows = run_artifacts(environment['CANDIDATE_RUN'], lambda path: api(repository, path), repository=repository)
    parent_artifacts = [r for r in parent_rows if r['name'] == 'candidate-' + manifest['candidate_id']]
    require(len(parent_artifacts) == 1 and parent_artifacts[0].get('expired') is False, 'parent_artifact_identity')
    parent_artifact = parent_artifacts[0]
    producer = json.loads(api(repository, f'actions/runs/{environment["CANDIDATE_RUN"]}/attempts/{manifest["generation_run_attempt"]}'))
    parent_producer = {'run_id': str(producer['id']), 'run_attempt': str(producer['run_attempt']),
        'head_sha': producer['head_sha'], 'event': producer['event'], 'path': producer['path']}
    require(producer['head_branch'] == 'main' and producer['path'] == archive.SOURCE_WORKFLOW
            and producer['event'] in {'push', 'schedule', 'workflow_dispatch'}, 'parent_producer')
    family = prefix(manifest['candidate_id'])
    rows = repository_artifacts(repository, lambda path: api(repository, path), task_prefix=family)
    reservations = [r for r in rows if r['name'].startswith(family + '-reservation-')]
    if reservations:
        latest = max(reservations, key=lambda r: r['id'])
        expected = latest['name'].replace('-reservation-', '-state-')
        matches = [r for r in rows if r['name'] == expected]
        require(len(matches) == 1 and matches[0].get('expired') is False, 'newest_repair_state_unavailable')
        selected = matches[0]; producer = selected['workflow_run']['id']
        _, checkpoint_run, checkpoint_attempt = latest['name'].rsplit('-', 2)
        require(checkpoint_run == str(producer) and latest['workflow_run'] == selected['workflow_run'],
                'paired_repair_producer')
        meta = json.loads(api(repository, f'actions/runs/{producer}/attempts/{checkpoint_attempt}'))
        require(meta.get('path') == archive.SOURCE_WORKFLOW and meta.get('head_branch') == 'main'
                and meta.get('event') == 'workflow_dispatch', 'repair_checkpoint_origin')
        raw = artifact_bytes(repository, str(producer), selected, lambda path: api(repository, path))
        require(c.digest(raw) == selected['digest'].removeprefix('sha256:'), 'repair_checkpoint_digest')
        unpack(raw, state)
        context = c.read_json(state / 'reconciliation.json')
        require(context['parent_candidate_id'] == manifest['candidate_id']
                and context['parent_manifest_sha256'] == c.digest((parent / 'candidate.json').read_bytes()),
                'repair_checkpoint_parent')
        prior_ledger = c.read_json(state / 'ledger.json')
        link = {'producer': {'run_id': str(producer), 'run_attempt': checkpoint_attempt,
                'head_sha': meta['head_sha'], 'event': meta['event'], 'path': meta['path']},
            'reservation': {'id': latest['id'], 'name': latest['name'],
                            'sha256': latest['digest'].removeprefix('sha256:')},
            'state': {'id': selected['id'], 'name': selected['name'],
                      'sha256': selected['digest'].removeprefix('sha256:')},
            'ledger_sha256': identity(prior_ledger), 'request_count': len(prior_ledger['requests']),
            'request_prefix_sha256': identity(prior_ledger['requests']),
            'request_identity_prefix_sha256': request_identity(prior_ledger['requests']),
            'charged_microusd': sum(r['charged_microusd'] for r in prior_ledger['requests'])}
        lineage_path = state / 'consumed-checkpoints.json'
        lineage = c.read_json(lineage_path) if lineage_path.exists() else []
        if link not in lineage:
            lineage.append(link)
        atomic_json(lineage_path, lineage)
        if context.get('completed_candidate_id'):
            child = context['completed_candidate_id']
            existing = run_artifacts(str(producer), lambda path: api(repository, path), repository=repository)
            available = [r for r in existing if r['name'] == 'candidate-' + child and r.get('expired') is False]
            require(len(available) <= 1, 'completed_child_artifact_ambiguity')
            complete = state / 'complete-candidates' / child
            if available:
                authenticated = state / 'authenticated-children' / child
                if not authenticated.exists():
                    fetch(repository, str(producer), 'candidate-' + child, authenticated)
                loaded = c.load(authenticated, child)
                if complete.exists():
                    require((complete / 'candidate.json').read_bytes() == (authenticated / 'candidate.json').read_bytes(),
                            'completed_child_manifest_bytes')
                complete = authenticated
                link['candidate'] = {'candidate_id': child,
                    'manifest_sha256': c.digest((authenticated / 'candidate.json').read_bytes()),
                    'producer': link['producer'],
                    'artifact': {'id': available[0]['id'], 'name': available[0]['name'],
                                 'sha256': available[0]['digest'].removeprefix('sha256:')}}
                lineage = [r for r in lineage if r['state']['id'] != link['state']['id']] + [link]
                atomic_json(lineage_path, lineage)
            else:
                loaded = c.load(complete, child)
            require(loaded.get('derived_from_candidate') == manifest['candidate_id']
                    and loaded.get('source_reconciliation', {}).get('version') == VERSION, 'completed_child')
            try:
                c.verify_dependencies(root, loaded)
            except ValueError:
                verify_source_delta(root, manifest)
                require(str(producer) != environment['GITHUB_RUN_ID'], 'changed_completed_child_requires_new_dispatch')
                require(source_operation_changed(context['operation_contract'], operation_contract(root)),
                        'completed_child_requires_named_runtime_assembly_or_validation')
                # A new bounded repair round consumes this exact prior child;
                # preserve its budget and complete bytes, never restore origin.
                context = {k: v for k, v in context.items() if k not in ('operation_sha256', 'completed_candidate_id')}
                context['operation_contract'] = operation_contract(root)
                context['operation_sha256'] = identity(context)
                atomic_json(state / 'reconciliation.json', context)
            else:
                # Old complete children remain immutable evidence. Never reuse
                # one whose SAM cache still includes withdrawn/replaced IDs;
                # that needs an explicit migration, not repeated paid work.
                from scripts.sources.merge import load_catalog
                require_sam_cache_membership(load_catalog(complete / 'files/data/opportunities.js'),
                    c.read_json(complete / 'files/data/document_evidence.json'),
                    'completed_child_sam_cache_membership_requires_migration')
                shutil.copytree(complete, output)
                emit(candidate_id=child, artifact_run=str(producer) if available else environment['GITHUB_RUN_ID'],
                     needs_persist='false' if available else 'true')
                return True
        if source_operation_changed(context['operation_contract'], operation_contract(root)):
            verify_source_delta(root, manifest)
            context = {k: v for k, v in context.items() if k not in ('operation_sha256', 'completed_candidate_id')}
            context['operation_contract'] = operation_contract(root)
            context['operation_sha256'] = identity(context)
            atomic_json(state / 'reconciliation.json', context)
    else:
        require(environment.get('GITHUB_RUN_ATTEMPT', '1') == '1', 'missing_prior_repair_accounting')
        provenance = original_state(repository, environment['CANDIDATE_RUN'], manifest, state, root=root)
        context = {'version': VERSION, 'parent_candidate_id': manifest['candidate_id'],
            'parent_run': environment['CANDIDATE_RUN'], 'parent_attempt': manifest['generation_run_attempt'],
            'parent_manifest_sha256': c.digest((parent / 'candidate.json').read_bytes()),
            'parent_generation_sha': manifest['generation_sha'], 'original_spend': provenance,
            'parent_producer': parent_producer,
            'parent_artifact': {'id': parent_artifact['id'], 'name': parent_artifact['name'],
                                'sha256': parent_artifact['digest'].removeprefix('sha256:')},
            'operation_contract': operation_contract(root)}
        context['operation_sha256'] = identity(context)
        atomic_json(state / 'reconciliation.json', context)
        atomic_json(state / 'consumed-checkpoints.json', [])
    from tools.catalog_reconcile_spend import import_history
    import_history(state, parent, context['original_spend']['ledger_sha256'])
    marker = {'version': VERSION, 'parent_candidate_id': manifest['candidate_id'],
        'operation_sha256': context['operation_sha256'], 'producer_run': environment['GITHUB_RUN_ID'],
        'producer_attempt': environment['GITHUB_RUN_ATTEMPT'],
        'prior_ledger_sha256': identity(c.read_json(state / 'ledger.json'))}
    atomic_json(state / 'reservation.json', marker)
    return False


def verify_source_delta(root, original):
    current = c.generation_dependencies(root)
    previous = original['generation_dependencies']
    require(current['contract'] == previous['contract'], 'generation_contract_changed')
    # These hashes use the established dependency canonicalization (including
    # Python AST hashing), rather than comparing raw bytes to AST digests.
    for name in set(current['files']) | set(previous['files']):
        if current['files'].get(name) != previous['files'].get(name):
            require(name in SOURCE_INPUTS | SEMANTIC_INPUTS, 'unrelated_generation_input_' + name)


def sam_record(row):
    return str(row.get('opportunity_id', '')).startswith(SLUG + ':')


def require_sam_cache_membership(catalog, evidence, reason):
    current = {str(row['opportunity_id']) for row in catalog['opportunities'] if sam_record(row)}
    for key in ('records', 'subtopic_only'):
        require(not any(identifier.startswith(SLUG + ':') and identifier not in current
                        for identifier in evidence.get(key, {})), reason)


def project_sam(catalog, evidence, state):
    """Normal zero-request projection, limited to this adapter's records/cache."""
    from scripts.extract_document_evidence import enrich_document_evidence
    from scripts.notice_structure_cache import StructureCache
    selected = copy.deepcopy(catalog)
    selected['opportunities'] = [r for r in selected['opportunities'] if sam_record(r)]
    subset = copy.deepcopy(evidence)
    for key in ('records', 'subtopic_only'):
        subset[key] = {k: v for k, v in subset.get(key, {}).items() if k.startswith(SLUG + ':')}
    stamp = catalog.get('document_evidence_generated_at') or catalog['generated_at']
    def forbidden_fetch(*_):
        raise AssertionError('SAM reconciliation cannot extract or fetch documents')
    projected, updated = enrich_document_evidence(selected, subset, max_documents=0,
        max_subtopic_documents=0, request_delay=0, fetcher=forbidden_fetch,
        now=datetime.fromisoformat(stamp.replace('Z', '+00:00')),
        structure_cache=StructureCache(Path(state) / 'empty-structure-cache'))
    rows = {r['opportunity_id']: r for r in projected['opportunities']}
    result = copy.deepcopy(catalog)
    result['opportunities'] = [rows[r['opportunity_id']] if sam_record(r) else r for r in result['opportunities']]
    output_cache = copy.deepcopy(evidence)
    for key in ('records', 'subtopic_only'):
        output_cache[key] = {identifier: entry for identifier, entry in output_cache.get(key, {}).items()
                             if not identifier.startswith(SLUG + ':')}
        output_cache[key].update(updated.get(key, {}))
    return result, output_cache


def reconcile(root, parent, state):
    from scripts.sources.merge import load_catalog, load_source_cache, resolve_live_records, rebuild_catalog, save_catalog, save_source_cache, merge_records
    from scripts.sources.registry import collect
    from scripts.sources.adapters.sam_gov import SamGovAdapter, load_config
    from scripts.build_catalog import validate_catalog
    from tools.require_sam_refresh import require_complete_refresh
    root, parent, state = map(Path, (root, parent, state))
    original = c.load(parent)
    verify_source_delta(root, original)
    # Restore generated inputs only; protected runtime and adapter code stay at
    # the reviewed repair SHA. No document extraction or team engine is invoked.
    for name in original['generation_files']:
        target = c.checked_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parent / 'files' / name, target)
    catalog = load_catalog(root / 'data/opportunities.js')
    cache = load_source_cache(root / 'data/source_records.json')
    before_catalog, before_cache = copy.deepcopy(catalog), copy.deepcopy(cache)
    checkpoint = state / ('source-' + c.read_json(state / 'reconciliation.json')['operation_sha256'])
    if (checkpoint / 'summary.json').exists():
        summary = c.read_json(checkpoint / 'summary.json')
        require(summary['operation_sha256'] == c.read_json(state / 'reconciliation.json')['operation_sha256'], 'source_checkpoint_contract')
        for name, expected in summary['files'].items():
            raw = c.checked_path(checkpoint, name).read_bytes()
            require(c.digest(raw) == expected, 'source_checkpoint_bytes')
            c.checked_path(root, name).write_bytes(raw)
    else:
        adapter = SamGovAdapter()
        _, results = collect(adapters=[adapter], context={'catalog_records': catalog['opportunities'],
            'as_of': datetime.now(timezone.utc).date(),
            'source_snapshots': {SLUG: cache.get('sources', {}).get(SLUG, {}).get('records', [])}})
        require(len(results) == 1 and results[0].ok, 'reviewed_sam_collection_failed')
        external, cache, lifecycle = resolve_live_records(results, cache, datetime.now(timezone.utc).date())
        combined, merge_summary = merge_records(
            [r for r in catalog['opportunities'] if not sam_record(r)], external)
        validate_catalog(combined, len(combined), len(combined))
        summary = {'sources': lifecycle, 'written': True, 'validation': {'ok': True}, 'merge': merge_summary}
        require_complete_refresh(load_config(), summary)
        # Only this adapter's records are replaced. Other source histories and
        # the catalog-wide freshness timestamp remain their original evidence.
        prior_additional = catalog.get('diagnostics', {}).get('additional_sources', {})
        catalog = rebuild_catalog(catalog, combined, results, lifecycle)
        additional = catalog['diagnostics']['additional_sources']
        for key in ('adapters', 'lifecycle'):
            def source_id(r): return r.get('slug') or r.get('adapter') or r.get('source_slug')
            additional[key] = [r for r in prior_additional.get(key, []) if source_id(r) != SLUG] + additional[key]
        evidence_path = root / 'data/document_evidence.json'
        if evidence_path.exists():
            catalog, evidence = project_sam(catalog, c.read_json(evidence_path), state)
            # Rebuild indexes/facets after the normal public notice projection.
            from scripts.build_catalog import build_search_index, facet_counts
            catalog['search_index'] = build_search_index(catalog['opportunities'])
            catalog['facets'] = facet_counts(catalog['opportunities'])
            atomic_json(evidence_path, evidence)
        save_catalog(catalog, root / 'data/opportunities.js')
        save_source_cache(cache, root / 'data/source_records.json')
        summary['operation_sha256'] = c.read_json(state / 'reconciliation.json')['operation_sha256']
        summary['files'] = {}
        for name in ('data/opportunities.js', 'data/source_records.json', 'data/document_evidence.json'):
            raw = (root / name).read_bytes(); target = checkpoint / name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            summary['files'][name] = c.digest(raw)
        atomic_json(checkpoint / 'summary.json', summary)
    current = load_catalog(root / 'data/opportunities.js')
    current_cache = load_source_cache(root / 'data/source_records.json')
    require([r for r in current['opportunities'] if not sam_record(r)] ==
            [r for r in before_catalog['opportunities'] if not sam_record(r)], 'non_sam_records_unchanged')
    require({k: v for k, v in current_cache['sources'].items() if k != SLUG} ==
            {k: v for k, v in before_cache['sources'].items() if k != SLUG}, 'non_sam_source_cache_unchanged')
    require(current.get('generated_at') == before_catalog.get('generated_at'), 'catalog_freshness_not_relabelled')
    # This supported stage preserves all scientific team decisions. A SAM scope
    # with an existing paid decision needs its own explicit team repair rather
    # than silently retaining or regenerating that decision here.
    model = c.read_json(root / 'config/opportunity_team_model.json')
    old_sam = {r['opportunity_id']: r for r in before_catalog['opportunities'] if sam_record(r)}
    new_sam = {r['opportunity_id']: r for r in current['opportunities'] if sam_record(r)}
    changed = {key for key in set(old_sam) | set(new_sam) if old_sam.get(key) != new_sam.get(key)}
    require(not any(str(row.get('id', '')).split(':', 2)[:2] == key.split(':', 2)[:2]
                    for row in model.get('opportunities', []) for key in changed),
            'changed_sam_scope_has_existing_team_decision')
    return summary


def verify_inputs(root, original, parent, receipt):
    value = c.read_json(receipt) if isinstance(receipt, (str, Path)) else receipt
    require(value['version'] == VERSION and value['source_slug'] == SLUG
            and value['parent_candidate_id'] == original['candidate_id']
            and value['parent_manifest_sha256'] == c.digest((Path(parent) / 'candidate.json').read_bytes())
            and value['operation_contract'] == operation_contract(root), 'derived_receipt_contract')
    verify_source_delta(root, original)
    from scripts.sources.merge import load_catalog
    old = load_catalog(Path(parent) / 'files/data/opportunities.js')
    new = load_catalog(Path(root) / 'data/opportunities.js')
    require([r for r in old['opportunities'] if not sam_record(r)] ==
            [r for r in new['opportunities'] if not sam_record(r)], 'derived_non_sam_records')
    require(old.get('generated_at') == new.get('generated_at'), 'derived_original_freshness')
    old_cache = c.read_json(Path(parent) / 'files/data/source_records.json')
    new_cache = c.read_json(Path(root) / 'data/source_records.json')
    require({k: v for k, v in old_cache['sources'].items() if k != SLUG} ==
            {k: v for k, v in new_cache['sources'].items() if k != SLUG}, 'derived_non_sam_source_cache')
    old_evidence = c.read_json(Path(parent) / 'files/data/document_evidence.json')
    new_evidence = c.read_json(Path(root) / 'data/document_evidence.json')
    for key in ('records', 'subtopic_only'):
        require({k: v for k, v in old_evidence.get(key, {}).items() if not k.startswith(SLUG + ':')} ==
                {k: v for k, v in new_evidence.get(key, {}).items() if not k.startswith(SLUG + ':')},
                'derived_non_sam_document_cache')
    require(old_evidence.get('generated_at') == new_evidence.get('generated_at'), 'derived_evidence_freshness')
    retained = {n: h for n, h in original['generation_files'].items()
                if n not in DERIVED_FILES and not n.startswith('feeds/')}
    c.verify_files(root, retained)
    require(value['retained_output_hashes'] == retained, 'derived_retained_outputs')
    return retained


def finish(root, parent, state, output, receipt):
    root, parent, state, output, receipt = map(Path, (root, parent, state, output, receipt))
    original = c.load(parent); context = c.read_json(state / 'reconciliation.json')
    ledger = c.read_json(state / 'ledger.json')
    consumed = c.read_json(state / 'consumed-checkpoints.json')
    for link in consumed:
        count = link['request_count']
        require(count <= len(ledger['requests'])
                and request_identity(ledger['requests'][:count]) == link['request_identity_prefix_sha256']
                and sum(r['charged_microusd'] for r in ledger['requests'][:count]) <= link['charged_microusd'],
                'consumed_checkpoint_request_prefix')
    checkpoint = state / ('source-' + context['operation_sha256'])
    value = context | {'source_slug': SLUG, 'consumed_checkpoints': consumed,
        'operation_contract': operation_contract(root),
        'cache_operation_contract': context['operation_contract'],
        'source_summary_sha256': c.digest((checkpoint / 'summary.json').read_bytes()),
        'ledger_sha256': identity(ledger),
        'new_document_requests': 0, 'new_team_requests': 0,
        'retained_output_hashes': {n: h for n, h in original['generation_files'].items()
            if n not in DERIVED_FILES and not n.startswith('feeds/')}}
    atomic_json(receipt, value)
    child = c.create(root, output, parent=parent, source_reconciliation=receipt)
    # An interrupted artifact upload must still retain the complete child,
    # including its original construction timestamp, in the private checkpoint.
    complete = state / 'complete-candidates' / child['candidate_id']
    shutil.copytree(output, complete)
    c.load(complete, child['candidate_id'])
    context['completed_candidate_id'] = child['candidate_id']
    atomic_json(state / 'reconciliation.json', context)
    emit(candidate_id=child['candidate_id'], artifact_run=os.environ['GITHUB_RUN_ID'])
    return child


def emit(**values):
    print(json.dumps(values))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            for key, value in values.items():
                handle.write(f'{key}={value}\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('restore', 'sources', 'finish'))
    for name in ('parent', 'state', 'output', 'receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'restore':
        restore(c.ROOT, args.parent, args.state, args.output)
    elif args.action == 'sources':
        reconcile(c.ROOT, args.parent, args.state)
    else:
        finish(c.ROOT, args.parent, args.state, args.output, args.receipt)


if __name__ == '__main__':
    main()
