"""Build an opt-in, unavailable LOCAL registry package; never publish or generate science.

Inputs are explicit pinned snapshots. Ordinary registry/build/maintenance entry
points and their defaults are not changed or invoked by this tool.
"""
import argparse
import copy
from datetime import date
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

from scripts import faculty_match, researcher_registry as legacy
from scripts.currentness import record_is_current
from scripts import import_opportunity_team_model as team
from tools import contextual_team_audited_registry as audited

VERSION = 'contextual-registry-local-unavailable-stage-v1'
ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT_BYTES = 50_000_000
EXTRA_FILES = (
    'config/researcher_registry.json', 'config/opportunity_team_model.json',
    'data/search-v2-release.json', 'faculty_interests.html',
    'assets/search-v2-config.js', 'assets/search-query.js', 'assets/match-explain.js',
    'assets/submission-schedule.js', 'assets/team-match.css', 'assets/subtopic-runtime.js',
    'assets/team-hybrid.js', 'assets/team-matcher.js', 'assets/team-researchers.js',
    'workers/search-voyage-proxy/generated/corpus-allowlist.json',
)
BUILDER_FILES = ('tools/build_search_release_package.mjs', 'tools/embedding_contract.mjs',
                 'tools/run_search_diagnosis.mjs')
IMPLEMENTATION_FILES = (*BUILDER_FILES, 'tools/contextual_team_audited_registry.py',
                        'tools/stage_contextual_registry.py', 'scripts/researcher_registry.py',
                        'scripts/faculty_match.py', 'scripts/currentness.py',
                        'scripts/import_opportunity_team_model.py')
UNCHANGED = ('data/opportunities.js', 'data/subtopics.js', 'data/catalog-metadata.js',
             'data/search-v2-voyage-manifest.json', 'data/search-v2-voyage-vectors.f16',
             'data/search-v2-voyage-canaries.json',
             'workers/search-voyage-proxy/generated/corpus-allowlist.json',
             'workers/search-voyage-proxy/src/index.js', 'workers/search-voyage-proxy/wrangler.jsonc')
RELEASE_IDENTITIES = ('current_corpus_sha256', 'previous_corpus_sha256', 'vector_sha256',
                      'model', 'dimension', 'model_space_fingerprint', 'passage_count',
                      'worker_allowlist_sha256')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value):
    return sha256(value).hexdigest()


def identity(value):
    return digest(encoded(value))


def _bytes(path):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError('stage_input_exceeds_bound')
    return path.read_bytes()


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('stage_duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _json(path):
    return _decode(_bytes(path))


def _pinned_json(path, expected):
    raw = _bytes(path)
    if not re.fullmatch(r'[a-f0-9]{64}', expected or '') or digest(raw) != expected:
        raise ValueError('stage_input_pin_mismatch')
    return _decode(raw)


def _assignment(path, global_name):
    source = _bytes(path).decode('utf-8')
    match = re.fullmatch(r'\s*(?:/\*[\s\S]*?\*/\s*)?globalThis\.' + re.escape(global_name)
                         + r'\s*=\s*([\s\S]+);\s*', source)
    if not match:
        raise ValueError('stage_original_projection_shape')
    return _decode(match[1])


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value) + b'\n')


def _safe(root, name):
    rel = PurePosixPath(name)
    if (not isinstance(name, str) or '\\' in name or ':' in name or rel.is_absolute()
            or '..' in rel.parts or not rel.parts):
        raise ValueError('stage_unsafe_input_path')
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('stage_input_escapes_root')
    return path


def _pin(path, expected):
    if not re.fullmatch(r'[a-f0-9]{64}', expected or '') or digest(_bytes(path)) != expected:
        raise ValueError('stage_input_pin_mismatch')


def _copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _verify_inputs(root, files):
    for name, pin in files.items():
        _pin(_safe(root, name), pin)


def _archive(path, root, files):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(files):
            raw = _bytes(_safe(root, name))
            if digest(raw) != files[name]:
                raise ValueError('stage_archive_input_changed')
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(files):
            raise ValueError('stage_archive_members')
        for name, pin in files.items():
            if digest(archive.read(name)) != pin:
                raise ValueError('stage_archive_hash')
    return {'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size,
            'files_sha256': identity(files), 'file_count': len(files)}


def unavailable_model(original, registry, lineage):
    """Only explicitly declare old rows unavailable; never prune or select evidence."""
    if (not isinstance(original, dict) or not isinstance(original.get('opportunities'), list)
            or not 1 <= len(original['opportunities']) <= 2000):
        raise ValueError('stage_legacy_model_shape')
    if original.get('generation_id') != identity({k: v for k, v in original.items() if k != 'generation_id'}):
        raise ValueError('stage_legacy_model_generation')
    ids = [row.get('id') for row in original['opportunities']]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('stage_legacy_scope_identity')
    model = copy.deepcopy(original)
    for row in model['opportunities']:
        row['review_state'] = 'needs_revalidation'
    counts = audited.counts(registry)
    model['source_roster_counts'] = {key: counts[key] for key in ('total', 'rankable', 'unrankable')}
    model['pool_counts'] = counts['pool_counts']
    model['researcher_registry_generation'] = registry['registry_generation']
    model['faculty'] = audited.faculty(registry)
    model['local_staging'] = {'version': VERSION, 'registry_contract': audited.VERSION,
                              'status': 'unavailable_unqualified_not_for_publication',
                              'original_generation': original['generation_id'], **lineage}
    model.pop('generation_id')
    model['generation_id'] = identity(model)
    for before, after in zip(original['opportunities'], model['opportunities']):
        if ({k: v for k, v in before.items() if k != 'review_state'}
                != {k: v for k, v in after.items() if k != 'review_state'}):
            raise ValueError('stage_scientific_row_mutated')
    return model


def _forward(registry, catalog, output, as_of):
    # A private module instance supplies the explicit clock without changing the
    # ordinary matcher or its globals for other callers in the same process.
    spec = importlib.util.spec_from_file_location('_local_stage_faculty_match', ROOT/'scripts/faculty_match.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.record_is_current = lambda record: record_is_current(record, as_of)
    profiles = audited.matching_profiles(registry)
    matches = module.match_to_catalog(profiles, str(catalog), str(output),
                                       registry_generation=registry['registry_generation'])
    full = audited.preserve_forward_evidence(matches, profiles)
    output.write_bytes(b'/* Local staged forward matches; not scientific team verification. */\n'
                       b'globalThis.FACULTY_MATCHES=' + encoded(full) + b';\n')
    return full


def _node(node, package, script, *args):
    env = {key: value for key, value in os.environ.items()
           if not re.search(r'(?i)(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|NODE_OPTIONS)', key)}
    result = subprocess.run([str(node), '--import', (package/'tools/stage-local-only.mjs').as_uri(),
                             str(package/script), *args], cwd=package, env=env,
                            capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        # Keep bounded diagnostics locally; no source text is included in the manifest.
        raise ValueError('stage_node_validation_failed: ' + result.stderr[-1500:])
    return json.loads(result.stdout)


def _guard_script(as_of):
    return """import http from 'node:http'; import https from 'node:https'; import net from 'node:net';
import vm from 'node:vm'; import {syncBuiltinESMExports} from 'node:module';
const deny=()=>{throw Error('Local staging forbids network');};
globalThis.fetch=deny; http.request=http.get=https.request=https.get=net.connect=net.createConnection=deny;
const OriginalDate=Date, instant=OriginalDate.parse(%s);
class SnapshotDate extends OriginalDate {constructor(...args){super(...(args.length?args:[instant]));} static now(){return instant;}}
const original=vm.runInNewContext; vm.runInNewContext=function(code,context={},...args){context.Date=SnapshotDate;return original.call(this,code,context,...args);};
syncBuiltinESMExports();
""" % json.dumps(as_of.isoformat() + 'T12:00:00Z')


BROWSER_CHECK = """import fs from 'node:fs'; import vm from 'node:vm'; import assert from 'node:assert/strict';
const html=fs.readFileSync('team_match.html','utf8');
const generation=html.match(/<meta name="opportunity-team-generation" content="([a-f0-9]{64})"/)[1];
const context={document:{querySelector(selector){assert.equal(selector,'meta[name="opportunity-team-generation"]');return {getAttribute(name){assert.equal(name,'content');return generation;}};}}};
vm.createContext(context);
for(const name of ['data/researcher_directory.js','data/opportunity_team_index.js','data/opportunity_teams.js','data/faculty_matches.js','assets/opportunity-team.js'])vm.runInContext(fs.readFileSync(name,'utf8'),context);
const api=context.OpportunityTeam, data=context.OPPORTUNITY_TEAM_DATA, index=context.OPPORTUNITY_TEAM_INDEX;
api.validateIndex(index,generation);api.validateData(data,generation);
const engine=api.create(data);assert.equal(index.scopes.length,data.opportunities.length);assert.equal(api.availableScopes().length,0);
for(const row of data.opportunities){assert.equal(row.review_state,'needs_revalidation');const result=engine.resolveScope({parentId:row.parent_id,scopeId:row.id});assert.equal(result.ok,false);assert.equal(result.reason,'needs_revalidation');assert.throws(()=>engine.proposal(row));}
assert.equal(context.FACULTY_MATCHES.registry_generation,context.RESEARCHER_DIRECTORY.registry_generation);
for(const page of ['match_explorer.html','team_match.html']){const text=fs.readFileSync(page,'utf8');assert.ok(text.includes('<meta name="opportunity-team-generation" content="'+generation+'"'));assert.ok(text.includes('data/opportunity_team_index.js?v='+generation));assert.ok(text.includes('data/researcher_directory.js?v='+generation));}
console.log(JSON.stringify({validated:true,withheld:data.opportunities.length,available:0,registry_generation:context.RESEARCHER_DIRECTORY.registry_generation,team_generation:generation}));
"""


def assemble(public_root, audited_registry_path, expected_registry_sha256,
             expected_directory_sha256, expected_public_release_sha256, output, as_of, *, node=None):
    root, registry_path, output = Path(public_root).resolve(), Path(audited_registry_path).resolve(), Path(output).resolve()
    as_of = date.fromisoformat(str(as_of))
    if (output.exists() or output.is_relative_to(root) or root.is_relative_to(output)
            or output.is_relative_to(ROOT) or ROOT.is_relative_to(output)
            or registry_path.is_relative_to(output)):
        raise ValueError('stage_requires_new_isolated_output')
    registry = audited.validate(_pinned_json(registry_path, expected_registry_sha256))
    release = _pinned_json(root/'data/search-v2-release.json', expected_public_release_sha256)
    if release.get('schema_version') != 1 or not isinstance(release.get('source_hashes'), dict):
        raise ValueError('stage_public_release_shape')
    inputs = dict(release['source_hashes'])
    _verify_inputs(root, inputs)
    for name in EXTRA_FILES:
        inputs[name] = digest(_bytes(_safe(root, name)))
    for name in UNCHANGED:
        if name not in inputs:
            raise ValueError('stage_missing_source_dependency')
    implementation = {name: digest(_bytes(ROOT/name)) for name in IMPLEMENTATION_FILES}
    original = _pinned_json(root/'config/opportunity_team_model.json', inputs['config/opportunity_team_model.json'])
    if (team.browser_projection(original) != _assignment(root/'data/opportunity_teams.js', 'OPPORTUNITY_TEAM_DATA')
            or team.availability_projection(original) != _assignment(root/'data/opportunity_team_index.js', 'OPPORTUNITY_TEAM_INDEX')):
        raise ValueError('stage_original_model_projection_conflict')
    directory = audited.directory(registry)
    directory_bytes = (b'/* Generated by scripts/researcher_registry.py. Do not edit. */\n'
                       b'globalThis.RESEARCHER_DIRECTORY=' + encoded(directory) + b';\n')
    if digest(directory_bytes) != expected_directory_sha256:
        raise ValueError('stage_audited_projection_pin_mismatch')
    model = unavailable_model(original, registry, {
        'original_model_sha256': inputs['config/opportunity_team_model.json'],
        'public_release_sha256': expected_public_release_sha256,
        'audited_registry_sha256': expected_registry_sha256,
    })
    node = node or shutil.which('node')
    if not node:
        raise ValueError('stage_node_runtime_unavailable')
    # mkdir is the sole claim on the destination; a second process cannot share it.
    output.mkdir(parents=True, exist_ok=False)
    package = output/'package'
    try:
        _write(output/'INCOMPLETE.json', {'version': VERSION, 'state': 'assembling_local_unavailable_package'})
        for name in inputs:
            _copy(_safe(root, name), package/name)
        for name in BUILDER_FILES:
            _copy(ROOT/name, package/name)
        _copy(registry_path, package/'config/researcher_registry.json')
        (package/'data/researcher_directory.js').write_bytes(directory_bytes)
        _write(package/'data/researcher_registry_manifest.json', {
            'schema_version': 1, 'registry_generation': registry['registry_generation'],
            'counts': directory['counts'], 'researcher_ids': [person['id'] for person in directory['researchers']],
        })
        team.write_outputs(model, package/'config/opportunity_team_model.json',
                           package/'data/opportunity_teams.js', package/'data/opportunity_team_index.js')
        forward = _forward(registry, package/'data/opportunities.js', package/'data/faculty_matches.js', as_of)
        for name in ('match_explorer.html', 'team_match.html'):
            team.update_version_target(package/name, model['generation_id'])
        faculty_match.update_version_target(package/'team_match.html', package/'data/faculty_matches.js')
        legacy._update_directory_version_target(package/'faculty_interests.html', digest(directory_bytes))
        (package/'tools/stage-local-only.mjs').write_text(_guard_script(as_of), encoding='utf-8', newline='\n')
        written = _node(node, package, 'tools/build_search_release_package.mjs', '--write')
        checked = _node(node, package, 'tools/build_search_release_package.mjs', '--check')
        current = _json(package/'data/search-v2-release.json')
        if any(current.get(key) != release.get(key) for key in RELEASE_IDENTITIES):
            raise ValueError('stage_search_identity_changed')
        for name in UNCHANGED:
            _pin(package/name, inputs[name])
        (package/'tools/stage-browser-check.mjs').write_text(BROWSER_CHECK, encoding='utf-8', newline='\n')
        browser = _node(node, package, 'tools/stage-browser-check.mjs')
        if browser.get('withheld') != len(original['opportunities']) or browser.get('available') != 0:
            raise ValueError('stage_unavailable_contract')
        files = dict(current['source_hashes'])
        for name in EXTRA_FILES:
            files[name] = digest(_bytes(package/name))
        _verify_inputs(package, files)
        _verify_inputs(root, inputs)
        _pin(root/'data/search-v2-release.json', expected_public_release_sha256)
        _pin(registry_path, expected_registry_sha256)
        _verify_inputs(ROOT, implementation)
        rollback = _archive(output/'rollback.zip', root, inputs)
        staged = _archive(output/'local-unavailable.zip', package, files)
        manifest = {
            'version': VERSION, 'registry_contract': audited.VERSION,
            'status': 'local_unavailable_unqualified_not_for_publication', 'as_of': as_of.isoformat(),
            'public_input_files': inputs, 'implementation_files': implementation,
            'audited_registry_sha256': expected_registry_sha256,
            'audited_directory_sha256': expected_directory_sha256,
            'original_rows': [{'id': row['id'], 'sha256': identity(row)} for row in original['opportunities']],
            'permitted_row_change': 'review_state=needs_revalidation; all other original fields retained',
            'rollback': rollback, 'local_package': staged, 'files': files,
            'search_identity': {key: current[key] for key in RELEASE_IDENTITIES},
            'registry_generation': registry['registry_generation'], 'team_generation': model['generation_id'],
            'checks': {'search_write': written, 'search_check': checked, 'browser': browser},
            'forward_match_people': len(forward['faculty']),
            'forward_provenance': 'complete active claims and summary evidence; deterministic heuristic matches only',
            'scientific_revalidation': 0, 'source_calls': 0, 'provider_calls': 0, 'native_calls': 0,
            'public_mutated': False, 'ledger_mutated': False, 'ordinary_maintenance_invoked': False,
            'official_candidate': False, 'generation_run_id': None, 'publication_receipt': None,
        }
        manifest['stage_id'] = identity(manifest)
        # This is the only completion marker. Archives/partial files are never receipts.
        _write(output/'LOCAL-STAGE.json', manifest)
        (output/'INCOMPLETE.json').unlink()
        return manifest
    except Exception as error:
        _write(output/'FAILED.json', {'version': VERSION, 'state': 'failed_local_assembly',
                                      'error_type': type(error).__name__, 'detail': str(error)[:1800]})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-root', type=Path, required=True)
    parser.add_argument('--audited-registry', type=Path, required=True)
    parser.add_argument('--registry-sha256', required=True)
    parser.add_argument('--directory-sha256', required=True)
    parser.add_argument('--public-release-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='Explicit local snapshot date, YYYY-MM-DD')
    parser.add_argument('--node', type=Path)
    args = parser.parse_args()
    result = assemble(args.public_root, args.audited_registry, args.registry_sha256, args.directory_sha256,
                      args.public_release_sha256, args.output, args.as_of, node=args.node)
    print(json.dumps({'stage_id': result['stage_id'], 'status': result['status'],
                      'withheld': result['checks']['browser']['withheld'], 'available': 0}))


if __name__ == '__main__':
    main()
