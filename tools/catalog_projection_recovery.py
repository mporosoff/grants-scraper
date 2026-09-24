"""Exactly repair the retained catalog's companion evidence and public references.

This creates a derived candidate from one authenticated complete parent. It never
collects sources, assembles vectors, regenerates teams, or changes the spend owner.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile

from scripts import extract_document_evidence as evidence
from scripts.build_catalog import catalog_javascript_bytes, catalog_metadata_javascript_bytes, compact_catalog_payload
from scripts.enrich_catalog import read_catalog
from scripts.import_opportunity_team_model import update_version_target
from scripts.notice_structure_cache import StructureCache
from scripts.subtopic_records import read_cache
from tools import catalog_smoke_receipt as smoke
from tools import release_candidate as release
from tools.offline_spend import atomic_json
from tools.verify_notice_publication import verify as verify_notice

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/catalog_projection_recovery_20260924.json'
VERSION = 'catalog-projection-coherence-recovery-20260924-v1'
HTML = ('match_explorer.html', 'team_match.html')
DATA = ('data/document_evidence.json', 'data/opportunities.js')
PACKAGE = 'data/search-v2-release.json'
CHANGED = frozenset((*HTML, *DATA, PACKAGE))
FIELDS = {'version', 'parent', 'prior_cache', 'projection_clock', 'team_generation_id',
          'restored_entries', 'changed_files', 'expected_files', 'candidate_id', 'manifest_sha256'}
PARENT_FIELDS = {'run_id', 'run_attempt', 'head_sha', 'artifact_id', 'artifact_sha256',
                 'candidate_id', 'manifest_sha256', 'canonical_manifest_sha256',
                 'derived_from_candidate', 'receipt_artifact_id', 'receipt_artifact_sha256', 'receipt_sha256'}


def require(ok, reason):
    smoke.require(ok, 'projection_recovery_' + reason)


def plan():
    value = smoke.json_value(CONFIG.read_bytes())
    require(isinstance(value, dict) and set(value) == FIELDS and value['version'] == VERSION, 'strict_plan')
    require(all(isinstance(value[k], dict) for k in ('parent', 'prior_cache', 'changed_files', 'expected_files', 'restored_entries')),
            'plan_objects')
    parent, prior = value['parent'], value['prior_cache']
    require(set(parent) == PARENT_FIELDS and set(prior) == {'commit', 'sha256'}
            and all(type(parent[k]) is int and parent[k] > 0 for k in ('run_id', 'run_attempt', 'artifact_id', 'receipt_artifact_id'))
            and parent['run_attempt'] == 1, 'exact_parent_selectors')
    def hash64(text):
        return isinstance(text, str) and re.fullmatch('[a-f0-9]{64}', text)
    require(all(isinstance(v, str) and re.fullmatch('[a-f0-9]{40}', v) for v in (parent['head_sha'], prior['commit']))
            and all(hash64(v) for k, v in parent.items() if k.endswith('_sha256') or k in ('candidate_id', 'derived_from_candidate'))
            and all(hash64(v) for v in (prior['sha256'], value['candidate_id'], value['manifest_sha256'], value['team_generation_id'])),
            'complete_plan_identities')
    require(set(value['changed_files']) == CHANGED and CHANGED <= set(value['expected_files'])
            and len(value['expected_files']) == 126 and len(value['restored_entries']) == 4, 'fixed_scope')
    require(all(hash64(v) for v in value['expected_files'].values())
            and all(isinstance(v, dict) and set(v) == {'before', 'after'} and all(hash64(h) for h in v.values())
                    and v['before'] != v['after'] for v in value['changed_files'].values()), 'file_hashes')
    require(all(isinstance(k, str) and 0 < len(k) <= 200 and isinstance(v, dict)
                and set(v) == {'entry_sha256', 'document_sha256'} and all(hash64(h) for h in v.values())
                for k, v in value['restored_entries'].items()), 'entry_pins')
    try:
        clock = datetime.fromisoformat(value['projection_clock'].replace('Z', '+00:00'))
    except (TypeError, AttributeError, ValueError):
        require(False, 'projection_clock')
    require(clock.tzinfo is not None and clock.utcoffset().total_seconds() == 0, 'projection_clock')
    require(all(value['expected_files'][name] == hashes['after'] for name, hashes in value['changed_files'].items()),
            'expected_changed_files')
    for name in value['expected_files']:
        release.checked_path(ROOT / 'unused-projection-inventory', name)
    return value


def derivation(spec):
    p = spec['parent']
    return {'version': VERSION, 'parent_candidate_id': p['candidate_id'],
            'parent_manifest_sha256': p['manifest_sha256'], 'parent_run_id': p['run_id'],
            'parent_run_attempt': p['run_attempt'], 'parent_run_head': p['head_sha'],
            'parent_artifact_id': p['artifact_id'], 'parent_artifact_sha256': p['artifact_sha256'],
            'paired_recovery_receipt_sha256': p['receipt_sha256'],
            'prior_cache': spec['prior_cache'], 'restored_entries': spec['restored_entries'],
            'projection_clock': spec['projection_clock'], 'changed_files': spec['changed_files'],
            'retained_payload_files': len(spec['expected_files']) - len(CHANGED),
            'provider_requests': 0, 'source_requests': 0, 'native_counts': 0, 'ledger_writes': 0}


def parent_manifest(manifest, spec):
    """Undo only this declared derivation and recover the complete parent's identity."""
    parent = deepcopy(manifest)
    parent.pop('candidate_id', None)
    require(parent.pop('projection_recovery', None) == derivation(spec), 'derivation_metadata')
    require(parent.get('derived_from_candidate') == spec['parent']['candidate_id'], 'parent_pointer')
    parent['derived_from_candidate'] = spec['parent']['derived_from_candidate']
    for name, hashes in spec['changed_files'].items():
        require(parent['files'][name] == hashes['after'], 'derived_payload_identity')
        parent['files'][name] = hashes['before']
    for name in DATA:
        require(parent['generation_files'][name] == spec['changed_files'][name]['after'], 'derived_generation_files')
        parent['generation_files'][name] = spec['changed_files'][name]['before']
    parent['candidate_id'] = release.digest(release.encoded(parent))
    require(parent['candidate_id'] == spec['parent']['candidate_id'], 'full_parent_identity')
    return parent


def _exact_inventory(bundle, manifest):
    actual = {p.relative_to(bundle).as_posix() for p in Path(bundle).rglob('*') if p.is_file()}
    require(actual == {release.MANIFEST} | {'files/' + p for p in manifest['files']}, 'complete_safe_inventory')


def verify_manifest(manifest):
    """Verify the one pinned manifest without claiming its payload files exist."""
    spec = plan()
    require(isinstance(manifest, dict)
            and release.digest(release.encoded(manifest)) == spec['manifest_sha256'], 'derived_manifest_identity')
    require(manifest.get('candidate_id') == spec['candidate_id']
            == release.digest(release.encoded({key: value for key, value in manifest.items() if key != 'candidate_id'}))
            and manifest.get('schema_version') == 1 and manifest.get('candidate_format') == release.VERSION,
            'canonical_candidate_identity')
    require(manifest['files'] == spec['expected_files'], 'all_expected_payloads')
    parent = parent_manifest(manifest, spec)
    require(release.digest(release.encoded(parent)) == spec['parent']['canonical_manifest_sha256'],
            'parent_manifest_reconstructed')
    return {'candidate_id': manifest['candidate_id'], 'parent_candidate_id': parent['candidate_id'],
            'manifest': manifest, 'parent_manifest': parent, 'derivation': manifest['projection_recovery']}


def verify_candidate(bundle, *, root=ROOT):
    """Verify fixed manifest identity and every actual candidate payload byte."""
    spec = plan(); bundle = Path(bundle)
    raw = (bundle / release.MANIFEST).read_bytes()
    require(release.digest(raw) == spec['manifest_sha256'], 'derived_manifest_bytes')
    manifest = release.load(bundle, spec['candidate_id'])
    _exact_inventory(bundle, manifest)
    return verify_manifest(manifest)


def _prior_cache(root, spec):
    prior = spec['prior_cache']
    for commit in (prior['commit'], spec['parent']['head_sha']):
        result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', commit, 'HEAD'],
                                capture_output=True, timeout=30)
        require(result.returncode == 0, 'protected_ancestor')
    raw = subprocess.check_output(['git', '-C', str(root), 'show', prior['commit'] + ':data/document_evidence.json'], timeout=30)
    require(release.digest(raw) == prior['sha256'], 'protected_prior_cache')
    return smoke.json_value(raw)


def _payloads(bundle, spec, *, root=ROOT):
    """Transform only the five declared files in a private working copy."""
    files = Path(bundle) / 'files'
    before = read_catalog(files / DATA[1]); cache = smoke.json_value((files / DATA[0]).read_bytes())
    require(before.get('document_evidence_generated_at') == spec['projection_clock'], 'original_projection_clock')
    prior = _prior_cache(root, spec)
    selected = set(spec['restored_entries'])
    rows = {row['opportunity_id']: row for row in before['opportunities']}
    require(selected <= set(rows), 'all_restored_rows')
    augmented = deepcopy(cache)
    for identifier, pin in spec['restored_entries'].items():
        require(identifier not in cache['records'] and identifier not in cache.get('subtopic_only', {}), 'missing_companion_only')
        entry = prior['records'][identifier]; row = rows[identifier]
        require(release.digest(release.encoded(entry)) == pin['entry_sha256']
                and entry.get('status') == 'current' and not entry.get('last_error'), 'exact_current_entry')
        source = evidence.source_for_record(row)
        require(source is not None and evidence.source_signature(row, source) == entry['source_signature']
                and row['document_evidence']['document']['sha256'] == entry['document']['sha256'] == pin['document_sha256'],
                'owned_source_and_document')
        augmented['records'][identifier] = deepcopy(entry)
    narrow = deepcopy(before)
    narrow['opportunities'] = [deepcopy(row) for row in before['opportunities'] if row['opportunity_id'] in selected]
    narrow_cache = {'schema_version': cache['schema_version'], 'records':
                    {key: deepcopy(augmented['records'][key]) for key in selected}}
    def no_fetch(*args, **kwargs):
        raise AssertionError('Projection recovery cannot retrieve sources')
    with tempfile.TemporaryDirectory(prefix='catalog-projection-structure-') as temp:
        projected, _ = evidence.enrich_document_evidence(narrow, narrow_cache,
            now=datetime.fromisoformat(spec['projection_clock'].replace('Z', '+00:00')),
            max_documents=0, max_subtopic_documents=0, request_delay=0, fetcher=no_fetch,
            structure_cache=StructureCache(temp))
    published = compact_catalog_payload(projected)['opportunities']
    projected_rows = {row['opportunity_id']: row for row in published}
    after = deepcopy(before)
    for index, old in enumerate(before['opportunities']):
        if old['opportunity_id'] not in selected:
            continue
        replacement = projected_rows[old['opportunity_id']]
        require({key: value for key, value in old.items() if key != 'next_submission'}
                == {key: value for key, value in replacement.items() if key != 'next_submission'}, 'only_schedule_projection')
        after['opportunities'][index] = replacement
    # Preserve every other catalog/cache field, including unrelated retained
    # failure evidence and quarantined parents. Never adopt the writer's cache.
    strict = verify_notice(after, augmented, read_cache(files / 'data/subtopics.js'), candidate_id=spec['parent']['candidate_id'])
    require(strict['publication_ready'] and strict['changed_records'] == 0, 'strict_notice_gate')
    require(catalog_metadata_javascript_bytes(after) == (files / 'data/catalog-metadata.js').read_bytes(), 'unchanged_catalog_metadata')
    release.write_json(files / DATA[0], augmented)
    (files / DATA[1]).write_bytes(catalog_javascript_bytes(after))
    for name in HTML:
        update_version_target(files / name, spec['team_generation_id'])
    package = smoke.json_value((files / PACKAGE).read_bytes())
    for name in (*HTML, DATA[1]):
        package['source_hashes'][name] = release.digest((files / name).read_bytes())
    # Match the existing package JSON writer without rerunning its assembler.
    (files / PACKAGE).write_bytes((json.dumps(package, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    return strict


def repair(bundle, reports, *, root=ROOT, api=smoke.existing.api):
    """Authenticate the retained parent and create exactly one derived package."""
    spec = plan(); bundle, reports = Path(bundle), Path(reports); p = spec['parent']
    require(not bundle.exists() and not (reports / 'recovery.json').exists(), 'new_destination')
    run = smoke.trusted_run(p['run_id'], smoke.REFRESH, attempt=p['run_attempt'], allow_failed=True, api=api)
    require(run['head_sha'] == p['head_sha'] and run['conclusion'] == 'failure', 'exact_failed_parent_run')
    raw, artifact = smoke.authenticated_zip(p['artifact_id'], 'candidate-' + p['candidate_id'], run,
                                          'sha256:' + p['artifact_sha256'], api=api)
    receipt_zip, receipt_artifact = smoke.authenticated_zip(p['receipt_artifact_id'],
        f"catalog-candidate-recovery-{p['run_id']}-{p['run_attempt']}", run,
        'sha256:' + p['receipt_artifact_sha256'], api=api)
    require(datetime.fromisoformat(receipt_artifact['created_at'].replace('Z', '+00:00'))
            <= datetime.fromisoformat(artifact['created_at'].replace('Z', '+00:00')), 'paired_receipt_precedes_candidate')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='catalog-projection-repair-', dir=bundle.parent) as temp:
        working = Path(temp) / 'candidate'; receipt_root = Path(temp) / 'parent-receipt'
        smoke.unpack_public(raw, working); smoke.unpack_public(receipt_zip, receipt_root)
        require({x.relative_to(receipt_root).as_posix() for x in receipt_root.rglob('*') if x.is_file()} == {'recovery.json'}, 'only_paired_receipt')
        receipt_raw = (receipt_root / 'recovery.json').read_bytes()
        require(release.digest(receipt_raw) == p['receipt_sha256'], 'exact_paired_receipt')
        original_raw = (working / release.MANIFEST).read_bytes()
        require(release.digest(original_raw) == p['manifest_sha256'], 'exact_parent_manifest')
        parent = release.load(working, p['candidate_id']); _exact_inventory(working, parent)
        require(parent['files'] == {name: spec['changed_files'][name]['before'] if name in CHANGED else digest
                                   for name, digest in spec['expected_files'].items()}, 'all_parent_payloads')
        strict = _payloads(working, spec, root=root)
        derived = deepcopy(parent)
        derived['files'] = dict(spec['expected_files'])
        for name in DATA:
            derived['generation_files'][name] = spec['expected_files'][name]
        derived['derived_from_candidate'] = p['candidate_id']
        derived['projection_recovery'] = derivation(spec)
        derived.pop('candidate_id')
        derived['candidate_id'] = release.digest(release.encoded(derived))
        release.write_json(working / release.MANIFEST, derived)
        verified = verify_candidate(working, root=root)
        receipt = {'version': VERSION, 'recovered_at': datetime.now(timezone.utc).isoformat(),
                   'configuration_sha256': release.digest(CONFIG.read_bytes()),
                   'candidate_id': verified['candidate_id'], 'manifest_sha256': spec['manifest_sha256'],
                   'derivation': derivation(spec), 'strict_notice_gate': strict,
                   'requires_new_complete_candidate_artifact_and_validation': True}
        working.rename(bundle)
        # A failed destination move must never leave a success receipt. The
        # workflow uploads this receipt before admitting the candidate artifact.
        atomic_json(reports / 'recovery.json', receipt)
    return derived
