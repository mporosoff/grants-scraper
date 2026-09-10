"""Read-only retained-cache metadata inventory; never exports response bodies."""
import hashlib
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'economical-release'
DOC=ROOT/'docs/team-recommender'

def main():
    snapshots=[]
    for path in sorted((OLD/'.offline-evaluation').glob('*/ledger.json')):
        try: data=json.loads(path.read_bytes())
        except (ValueError,OSError): continue
        snapshots.append({'snapshot':path.parent.name,'logical_id':data.get('logical_id'),
            'requests':len(data.get('requests',[])),'charged_microusd':sum(r.get('charged_microusd',0) for r in data.get('requests',[])),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    latest=OLD/'.offline-evaluation/34402343578'
    cache=list((latest/'cache').glob('*.json')) if (latest/'cache').exists() else []
    cache_keys=set(); returned=Counter(); approved_receipts=0
    for path in cache:
        try: data=json.loads(path.read_bytes())
        except (ValueError,OSError): continue
        cache_keys.add(data.get('key',path.stem)); returned[str(data.get('returned_model','unknown'))]+=1
        approved_receipts+=data.get('kind')=='source-span-validation-v1'
    candidates=list(OLD.glob('.cache/**/*.vectors.json'))
    new_task=[s for s in snapshots if s['logical_id']=='on-demand-team-offline-v2-20260909']
    report={'observed_at':datetime.now(timezone.utc).isoformat(),'read_only':True,
      'inspection_roots':['economical-release/.offline-evaluation/*/ledger.json','economical-release/.offline-evaluation/34402343578/cache','economical-release/.cache'],
      'ledger_snapshots':snapshots,'snapshots_are_overlapping_not_additive':True,
      'existing_experiment_ledger_matches':new_task,'historical_reused_spending_credit_usd':0,
      'latest_historical_cache_files':len(cache),'unique_exact_cache_keys':len(cache_keys),'returned_model_counts':dict(returned),
      'v2_source_receipts':approved_receipts,'compatible_claim_aspect_vector_cache_files':len(candidates),
      'cache_values_reused_for_judging_or_publication':0,
      'old_judgment_compatibility':'Different prompt/schema/scientific event; retained model results are exposed historical development evidence, not E1 labels or source-validation receipts. No result values exported or used.',
      'raw_provider_responses_exported':False,'actual_experiment_spend_reconciled_usd':0,
      'limitations':'No provider account-wide invoice read; no provider requests by this experiment. Local historical snapshots overlap and are never summed or credited. Absence at inspected authorized roots is not proof about remote private stores.'}
    (DOC/'receipts/stage2-reuse-metadata.json').write_bytes((json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in report.items() if k!='ledger_snapshots'}))
if __name__=='__main__':main()
