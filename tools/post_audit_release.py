"""Assemble experimental cohorts with existing immutable release tooling.

Validation copies have no .git file and own no branch. Git access only reads the
existing experiment object store to preserve the exact input commit provenance.
"""
import io,json,os,subprocess,tarfile
from pathlib import Path
from tools import release_candidate as c
from scripts.import_opportunity_team_model import update_version_target
ROOT=Path(__file__).resolve().parents[1]
def main():
 sha=c.git(ROOT,'rev-parse','HEAD');store=c.git(ROOT,'rev-parse','--absolute-git-dir')
 manifest=c.read_json(ROOT/'docs/team-recommender/post-audit/routing-inventory-v1.json');result={}
 for cohort in ['legacy','rollout50','rollout150']:
  folder=ROOT.parents[1]/'outputs'/('post-audit-'+sha[:12])/cohort;stage=folder/'input';bundle=folder/'candidate'
  if folder.exists():raise ValueError('Immutable assembly already exists')
  stage.mkdir(parents=True)
  archive=subprocess.check_output(['git','-C',str(ROOT),'archive',sha])
  with tarfile.open(fileobj=io.BytesIO(archive)) as t:
   t.extractall(stage,members=[m for m in t if not m.name.startswith('docs/') or m.name.startswith('docs/team-recommender/post-audit/')],filter='data')
  selected=manifest['packages'][cohort];index=c.read_json(stage/selected['index_path'])
  (stage/'data/opportunity_team_index.js').write_text('globalThis.OPPORTUNITY_TEAM_INDEX = '+json.dumps(index,ensure_ascii=False,indent=2)+';\n',encoding='utf8',newline='\n')
  for name in ['match_explorer.html','team_match.html']:update_version_target(stage/name,index['generation_id'])
  # Only the selected content-addressed scope binding packet belongs to this
  # cohort. These are public ingredients, not calculated teams or judge outputs.
  for path in (stage/'data/team_ingredients').glob('shared-*.json'):
   if path.name!=Path(selected['packet']['path']).name:path.unlink()
  env=dict(os.environ,GIT_DIR=store,GIT_WORK_TREE=str(stage));subprocess.run(['node','tools/build_search_release_package.mjs','--write'],cwd=stage,env=env,check=True,stdout=subprocess.DEVNULL)
  old={k:os.environ.get(k) for k in ['GIT_DIR','GIT_WORK_TREE']}
  try:
   os.environ.update(GIT_DIR=store,GIT_WORK_TREE=str(stage))
   built=c.create(stage,bundle,generation_sha=sha,run_id='local-post-audit-assembly',attempt='1')
  finally:
   for k,v in old.items():
    if v is None:os.environ.pop(k,None)
    else:os.environ[k]=v
  assert selected['packet']['path'] in built['files']
  result[cohort]={'candidate_id':built['candidate_id'],'assembly_sha':sha,'bundle':str(bundle).replace('\\','/'),'files':len(built['files']),'scope_generation':index['generation_id'],'scopes':len(index['scopes']),'activated':False,'new_generation_calls':0}
 c.write_json(ROOT/'docs/team-recommender/post-audit/release-packages-v1.json',{'version':'post-audit-local-assembly-v1','assembly_sha':sha,'packages':result,'provenance':'No new source/profile/embedding generation. Exact committed corrected registry and retained source/vector bytes; cohort index and HTML dependency metadata assembled locally. No branch is checked out in the validation copies.','published':False})
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
