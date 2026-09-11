"""Continue ONLY untouched frozen requests; never replay or rebatch paid work."""
import argparse,json
from tools.team_recommender_real_prep import ROOT,DOC,sha,write
from tools.team_recommender_executor import policy,judge_contract,validate_packet
from tools.team_recommender_items import preflight,claimed_judge_items
from tools.team_recommender_budget import ExperimentLedger
from tools.offline_spend import identity

def main():
    parser=argparse.ArgumentParser();parser.add_argument('cloud');args=parser.parse_args();cloud=ROOT/args.cloud
    read=lambda p:json.loads(p.read_bytes());cp=read(cloud/'checkpoint.json')
    assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    original=read(ROOT/'outputs/team-recommender-stage3/judge-packet-v1.json');ledger=read(cloud/'ledger.json');paid={r['key']:r for r in ledger['requests']};used={k for r in ledger['requests'] for k in claimed_judge_items(r)}
    settings=policy();remaining=[];skipped=[]
    for r in original['requests']:
        key=identity([settings['authorization_id'],'development-judge',judge_contract(r,settings)[0]])
        if key in paid:skipped.append({'key':key,'status':paid[key]['status']});continue
        from tools.team_recommender_stage3_executor import judge_items
        assert not used.intersection(judge_items(r));remaining.append(r)
    packet={**original,'requests':remaining};assert remaining;validate_packet(packet,settings);preflight(packet,settings,ExperimentLedger(cloud/'ledger.json'))
    h=write(DOC/'packets'/('remaining-'+cp['run_id']+'.json'),packet)
    p=DOC/'packets'/('remaining-'+cp['run_id']+'.json');p.rename(DOC/'packets'/(h+'.json'))
    receipt={'previous_run':cp['run_id'],'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'packet_sha256':h,'remaining_requests':len(remaining),'already_attempted':skipped,'failed_replayed':0,'request_body_or_batch_changes':0,'new_question_selection':False,'cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'cumulative_requests':len(ledger['requests'])}
    write(DOC/'receipts'/('stage3-remaining-after-'+cp['run_id']+'.json'),receipt);print(json.dumps({k:v for k,v in receipt.items() if k!='already_attempted'}))
if __name__=='__main__':main()
