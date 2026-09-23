"""Separate Access-only AI continuation; immutable historical preview cohorts."""
import base64
from copy import deepcopy
import gzip
import json
import re
from pathlib import Path

from tools.offline_spend import atomic_json, encoded, identity
from tools.team_recommender_executor import sha

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = '/admin/contextual/iteration3-continuation/'


def build():
    old_path = ROOT/'workers/researcher-intake/config/contextual-iteration3-preview-v1.json'
    old_raw = old_path.read_bytes(); old = json.loads(old_raw)
    base_path = ROOT/'workers/researcher-intake/config/contextual-preview-v1.json'
    base_raw = base_path.read_bytes(); base = json.loads(base_raw)
    authority = json.loads((ROOT/'config/contextual_team/iteration3-continuation-v1.json').read_bytes())
    sources = json.loads((ROOT/'config/contextual_team/iteration3-source-inputs-v1.json').read_bytes())
    if (authority['release_id'] != identity({k:v for k,v in authority.items() if k!='release_id'})
            or authority.get('paid_builds_enabled') is not False or authority.get('public_activation') is not False):
        raise ValueError('continuation_preview_authority')
    files = deepcopy(old['files'])
    def original(name):return old['files'][name] if name in old['files'] else base['files'][name]
    def unpack(name):return gzip.decompress(base64.b64decode(original(name)['gzip_base64']))
    def add(name,raw,kind):
        zipped=gzip.compress(raw,mtime=0)
        files[name]={'bytes':len(raw),'gzip_bytes':len(zipped),'sha256':sha(raw),
            'gzip_base64':base64.b64encode(zipped).decode(),'content_type':kind}
    observer='assets/contextual-preview-observer.js'; text=unpack(observer).decode()
    needle="url.pathname.startsWith('/admin/contextual/iteration3/')||"
    if text.count(needle)!=1:raise ValueError('continuation_original_observer_allowlist')
    text=text.replace(needle,needle+"url.pathname.startsWith('/admin/contextual/iteration3-continuation/')||")
    add(observer,text.encode(),'text/javascript; charset=utf-8')
    app_config='assets/app-config.js'; text=unpack(app_config).decode()
    needle='proxyUrl: productionHybridProxy || localHybridProxy(),'
    if text.count(needle)!=1:raise ValueError('continuation_original_hybrid_proxy_config')
    text=text.replace(needle,'proxyUrl: "",')
    add(app_config,text.encode(),'text/javascript; charset=utf-8')
    raw=unpack('data/opportunity_team_index.js').decode()
    index=json.loads(raw[raw.index('{'):raw.rindex('}')+1]);index.pop('generation_id')
    if (index['release_id']!=old['release_id'] or index['registry_generation']!=sources['registry_generation']
            or index['roster_id']!=sources['roster_id'] or index['source_fields']!=sources['source_fields']
            or index['condition_fields']!=sources['condition_fields']):
        raise ValueError('continuation_exact_retained_registry_and_source')
    scopes=[s for s in index['scopes'] if s['id']=='363268']
    source=next(s for s in sources['scopes'] if s['id']=='363268')
    if len(scopes)!=1 or scopes[0]['source_id']!=source['source_id']:
        raise ValueError('continuation_exact_ai_scope')
    index.update(release_id=authority['release_id'],scopes=scopes)
    index['generation_id']=identity(index)
    add('data/opportunity_team_index.js',b'globalThis.OPPORTUNITY_TEAM_INDEX='+encoded(index)+b';\n','text/javascript; charset=utf-8')
    for name in ('match_explorer.html','team_match.html'):
        text=unpack(name).decode()
        if text.count('<base href="'+old['base_path']+'">')!=1 or old['index_generation'] not in text:
            raise ValueError('continuation_original_html_identity')
        text=text.replace('<base href="'+old['base_path']+'">','<base href="'+BASE_PATH+'">')
        text=text.replace(old['index_generation'],index['generation_id'])
        text=text.replace(old['files'][observer]['sha256'],files[observer]['sha256'])
        pattern=r'src="(?:\./)?assets/app-config\.js\?v=[^"\s]+"'
        if len(re.findall(pattern,text))!=1:raise ValueError('continuation_original_app_config_reference')
        text=re.sub(pattern,'src="./assets/app-config.js?v='+files[app_config]['sha256']+'"',text)
        add(name,text.encode(),'text/html; charset=utf-8')
    value={'version':'contextual-iteration3-continuation-preview-v1','base_path':BASE_PATH,
        'release_id':authority['release_id'],'index_generation':index['generation_id'],
        'registry_generation':sources['registry_generation'],'public_activation':False,'provider_results':0,
        'historical_iteration3_bundle_id':old['bundle_id'],'historical_base_bundle_id':base['bundle_id'],'files':files}
    value['bundle_id']=identity(value)
    if old_path.read_bytes()!=old_raw:raise ValueError('continuation_historical_bundle_changed')
    if base_path.read_bytes()!=base_raw:raise ValueError('continuation_historical_base_changed')
    atomic_json(ROOT/'workers/researcher-intake/config/contextual-iteration3-continuation-preview-v1.json',value)
    return {k:v for k,v in value.items() if k!='files'}


if __name__=='__main__':print(json.dumps(build(),sort_keys=True))
