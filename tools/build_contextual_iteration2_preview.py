"""Build an Access-only overlay from existing UI and locked public source data.

No provider output, private result, credential or registry cutover enters this
artifact. Historical preview bytes remain independently addressable.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from tools.offline_spend import atomic_json, identity, encoded
from scripts.build_catalog import catalog_metadata, catalog_metadata_javascript_bytes

ROOT = Path(__file__).resolve().parents[1]


def assigned_json(raw, name):
    return json.loads(raw.decode().split('globalThis.'+name+'=', 1)[1].strip().removesuffix(';'))


def build():
    base = json.loads((ROOT/'workers/researcher-intake/config/contextual-preview-v1.json').read_bytes())
    authority = json.loads((ROOT/'config/contextual_team/iteration2-authority-v1.json').read_bytes())
    sources = json.loads((ROOT/'config/contextual_team/iteration2-source-inputs-v1.json').read_bytes())
    files = {}
    def add(name, raw, content_type):
        zipped = gzip.compress(raw, mtime=0)
        files[name] = {'bytes':len(raw), 'gzip_bytes':len(zipped), 'sha256':hashlib.sha256(raw).hexdigest(),
            'gzip_base64':base64.b64encode(zipped).decode(), 'content_type':content_type}
    for name in ('contextual-team-engine.js','contextual-team-client.js','contextual-preview-observer.js',
                 'opportunity-team.js','opportunity-team-panel.js'):
        add('assets/'+name, (ROOT/'workers/researcher-intake/iteration2-source/assets'/name).read_bytes().replace(b'\r\n',b'\n'), 'text/javascript; charset=utf-8')
    # The catalog and startup metadata form one published cohort. Refuse stale
    # product-worktree inputs instead of silently rebuilding another release.
    catalog_raw = (ROOT/'data/opportunities.js').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(catalog_raw).hexdigest() != sources['source_catalog']['raw_sha256']:
        raise ValueError('iteration2_locked_catalog_required')
    catalog = assigned_json(catalog_raw, 'GRANT_CATALOG')
    metadata_raw = (ROOT/'data/catalog-metadata.js').read_bytes().replace(b'\r\n',b'\n')
    if metadata_raw != catalog_metadata_javascript_bytes(catalog):
        raise ValueError('iteration2_catalog_metadata_cohort_mismatch')
    asset_version = catalog_metadata(catalog)['asset_version']
    old_metadata = assigned_json(gzip.decompress(base64.b64decode(
        base['files']['data/catalog-metadata.js']['gzip_base64'])), 'GRANT_CATALOG_METADATA')
    for name, raw in [('opportunities.js', catalog_raw), ('catalog-metadata.js', metadata_raw),
                      ('subtopics.js', (ROOT/'data/subtopics.js').read_bytes().replace(b'\r\n',b'\n'))]:
        add('data/'+name, raw, 'text/javascript; charset=utf-8')
    original = gzip.decompress(base64.b64decode(base['files']['data/opportunity_team_index.js']['gzip_base64'])).decode()
    index = json.loads(original[original.index('{'):original.rindex('}')+1])
    index.pop('generation_id');index.update(release_id=authority['release_id'], source_fields=sources['source_fields'],
        condition_fields=sources['condition_fields'], scopes=[{
            'id':s['id'],'parent_id':s['parent_id'],'source_id':s['source_id'],
            'catalog_source_id':s['catalog_source_id'],'currentness':s['currentness'],
            'scope_label':s['science']['title'], 'state':s['state'], 'engine':'contextual-v1',
            'record_type':'publishable_child' if s['kind']=='publishable_child' else 'specific_parent'} for s in sources['scopes']],
        runtime={'contextual_engine':files['assets/contextual-team-engine.js']['sha256'],
                 'contextual_client':files['assets/contextual-team-client.js']['sha256']})
    if index['registry_generation'] != sources['registry_generation'] or index['roster_id'] != sources['roster_id']:
        raise ValueError('iteration2_preview_registry_changed')
    index['generation_id'] = identity(index)
    add('data/opportunity_team_index.js', b'globalThis.OPPORTUNITY_TEAM_INDEX='+encoded(index)+b';\n', 'text/javascript; charset=utf-8')
    for name in ('match_explorer.html','team_match.html'):
        html = gzip.decompress(base64.b64decode(base['files'][name]['gzip_base64'])).decode()
        old_base = '<base href="'+base['base_path']+'">'
        if html.count(old_base) != 1 or base['index_generation'] not in html:
            raise ValueError('iteration2_original_preview_html_identity')
        html = html.replace(old_base, '<base href="/admin/contextual/iteration2/">')
        if old_metadata['asset_version'] not in html:
            raise ValueError('iteration2_original_catalog_version_reference')
        html = html.replace(old_metadata['asset_version'], asset_version)
        html = html.replace(base['index_generation'], index['generation_id'])
        for asset, file in files.items():
            if asset in base['files']:
                html = html.replace(base['files'][asset]['sha256'], file['sha256'])
        add(name, html.encode(), 'text/html; charset=utf-8')
    value={'version':'contextual-iteration2-preview-v1','base_path':'/admin/contextual/iteration2/',
        'base_bundle_id':base['bundle_id'],'release_id':authority['release_id'],'index_generation':index['generation_id'],
        'registry_generation':sources['registry_generation'],'public_activation':False,'provider_results':0,'files':files}
    value['bundle_id']=identity(value)
    atomic_json(ROOT/'workers/researcher-intake/config/contextual-iteration2-preview-v1.json',value)
    return {k:v for k,v in value.items() if k!='files'}


if __name__ == '__main__': print(json.dumps(build(),sort_keys=True))
