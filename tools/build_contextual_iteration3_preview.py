"""Separate Access-only I3 overlay; retain the historical I2 bundle exactly."""
import base64
from copy import deepcopy
import gzip
import json
from pathlib import Path

from tools.offline_spend import atomic_json, encoded, identity
from tools.team_recommender_executor import sha

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = '/admin/contextual/iteration3/'
ASSETS = ('contextual-team-engine.js', 'contextual-team-client.js', 'contextual-preview-observer.js',
    'opportunity-team.js', 'opportunity-team-panel.js')


def build():
    old_path = ROOT/'workers/researcher-intake/config/contextual-iteration2-preview-v1.json'
    old_raw = old_path.read_bytes(); old = json.loads(old_raw)
    authority = json.loads((ROOT/'config/contextual_team/iteration3-authority-v1.json').read_bytes())
    sources = json.loads((ROOT/'config/contextual_team/iteration3-source-inputs-v1.json').read_bytes())
    files = deepcopy(old['files'])
    def unpack(name): return gzip.decompress(base64.b64decode(old['files'][name]['gzip_base64']))
    def add(name, raw, kind):
        zipped = gzip.compress(raw, mtime=0)
        files[name] = {'bytes':len(raw),'gzip_bytes':len(zipped),'sha256':sha(raw),
            'gzip_base64':base64.b64encode(zipped).decode(),'content_type':kind}
    for name in ASSETS:
        raw=(ROOT/'workers/researcher-intake/iteration2-source/assets'/name).read_bytes().replace(b'\r\n',b'\n')
        add('assets/'+name,raw,'text/javascript; charset=utf-8')
    raw=unpack('data/opportunity_team_index.js').decode()
    index=json.loads(raw[raw.index('{'):raw.rindex('}')+1]);index.pop('generation_id')
    if (index['registry_generation'] != sources['registry_generation'] or index['roster_id'] != sources['roster_id']
            or sources['source_fields'] != index['source_fields'] or sources['condition_fields'] != index['condition_fields']):
        raise ValueError('iteration3_exact_compatible_source_and_registry_fields')
    scopes=sources['scopes']
    if {s['id'] for s in scopes} != {'332894','345241:tdac-baa-004','363268'} or len(scopes)!=3:
        raise ValueError('iteration3_finite_production_scope_inventory')
    index.update(release_id=authority['release_id'],scopes=[{
        'id':s['id'],'parent_id':s['parent_id'],'source_id':s['source_id'],
        'catalog_source_id':s['catalog_source_id'],'currentness':s['currentness'],
        'scope_label':s['science']['title'],'state':s['state'],'engine':'contextual-v1',
        'record_type':'publishable_child' if s['kind']=='publishable_child' else 'specific_parent'} for s in scopes],
        runtime={'contextual_engine':files['assets/contextual-team-engine.js']['sha256'],
            'contextual_client':files['assets/contextual-team-client.js']['sha256']})
    index['generation_id']=identity(index)
    add('data/opportunity_team_index.js',b'globalThis.OPPORTUNITY_TEAM_INDEX='+encoded(index)+b';\n','text/javascript; charset=utf-8')
    for name in ('match_explorer.html','team_match.html'):
        text=unpack(name).decode()
        if text.count('<base href="'+old['base_path']+'">')!=1 or old['index_generation'] not in text:
            raise ValueError('iteration3_original_overlay_html_identity')
        text=text.replace('<base href="'+old['base_path']+'">','<base href="'+BASE_PATH+'">')
        text=text.replace(old['index_generation'],index['generation_id'])
        for asset in ASSETS:
            key='assets/'+asset;text=text.replace(old['files'][key]['sha256'],files[key]['sha256'])
        add(name,text.encode(),'text/html; charset=utf-8')
    value={'version':'contextual-iteration3-preview-v1','base_path':BASE_PATH,
        'release_id':authority['release_id'],'index_generation':index['generation_id'],
        'registry_generation':sources['registry_generation'],'public_activation':False,
        'provider_results':0,'historical_iteration2_bundle_id':old['bundle_id'],'files':files}
    value['bundle_id']=identity(value)
    if old_path.read_bytes()!=old_raw: raise ValueError('iteration3_historical_bundle_changed')
    atomic_json(ROOT/'workers/researcher-intake/config/contextual-iteration3-preview-v1.json',value)
    return {k:v for k,v in value.items() if k!='files'}


if __name__=='__main__': print(json.dumps(build(),sort_keys=True))
