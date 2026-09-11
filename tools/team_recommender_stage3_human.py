"""Create only the twenty preselected final audit items; hide machine verdicts."""
import json
from tools.team_recommender_real_prep import ROOT,DOC,write,sha
OUT=ROOT/'outputs/team-recommender-stage3'
def read(p):return json.loads(p.read_bytes())
def main():
    manifest=read(DOC/'manifests/human-final-source-overlay-c2.json');config=read(ROOT/'config/team_recommender_executor/inputs-stage3.json');outputs=read(OUT/'heldout-outputs-v1.json');rows={r['id']:r for r in outputs['rows']};directory={p['id']:p for p in read(OUT/'assembled-holdout_effective/directory.json')['researchers']}
    lines=['# Final audit: frozen E2 validation','', 'Marc: this is the reserved final packet. It contains 20 preselected slots, including unavailable slots; there are no replacement items and no new development review. Give only one assessment per available item. You may answer “unable to assess.” Model verdicts and algorithm identities are hidden. These are suggestions worth discussing, not certification of expertise, facilities or eligibility.','', 'For an individual: strong / plausible / unrelated / insufficient information / unable to assess. For a comparison: A / B / tie / unresolved / unable to assess. A brief reason is optional. Do not assess each member separately.','', 'Read the evidence before recording your answer. All researcher text is unchanged retained registry information, not newly verified faculty-page quotation. Every source condition remains applicable; unknown information is not competence or incompetence.','']
    requested=[];mappings={}
    for item in manifest['items']:
        sid=item['scope_id'];r=rows[sid];ctx=config['contexts'][sid];entry={**item,'requested':True,'judgment':None};people=[];groups=None
        lines+=['## '+item['item_id'],'',f"Source: **{sid}** — {r['source_disposition'].get('title',r['source_disposition'].get('scope_label',sid))}",'']
        if item['task_type']=='individual':
            rank=item['position_if_individual'];people=r.get('B5',[])[rank-1:rank];entry['candidate_ids']=people;entry['available']=bool(people)
        else:
            A=r.get('A',{}).get('ids',[]);B=r.get('B',{}).get('ids',[]);swapped=bool(int(sha('stage3-e2-AB-v1|'+sid),16)&1)
            groups={'A':B if swapped else A,'B':A if swapped else B};people=sorted(set(A+B));entry['available']=bool(A and B);entry['candidate_groups']=groups;mappings[item['item_id']]={'A':'E2' if swapped else 'A-E2','B':'A-E2' if swapped else 'E2'}
        if not entry['available']:
            lines+=['This preselected slot has no complete recommendation at the reserved position, or one arm abstained / the source was unprepared. It is retained as **unavailable**, not replaced with an easier example. No recommendation assessment is requested for this slot.',''];requested.append(entry);continue
        lines+=['<details open><summary>Official source evidence and conditions</summary>','']
        for p in ctx['source_evidence']['passages']:lines += [f"[{p['locator']}]({p['url']})",'', '> '+p['text'].replace('\n','\n> '),'']
        lines += [ctx['source_evidence']['limitations'],'','</details>','']
        for pid in people:
            p=config['profile_documents'][pid];lines += ['**'+directory[pid]['name']+'**','',p['research_summary'] or '(No stored research summary.)','']
            for s in p['statements']:
                labels='; '.join(c['label']+' ['+c['claim_type']+']' for c in s['claims']);lines+=['- '+s['text']+' — '+labels]
            lines+=['']
        if groups:
            lines += ['Group A: '+', '.join(directory[p]['name'] for p in groups['A']), '', 'Group B: '+', '.join(directory[p]['name'] for p in groups['B']), '', '**One assessment:** Which group is more worth a scientific conversation for this source? A / B / tie / unresolved / unable to assess.','']
        else:lines+=['**One assessment:** Is this person worth discussing for a useful contribution to this source? Strong / plausible / unrelated / insufficient information / unable to assess.','']
        lines+=['Your assessment: __________',''];requested.append(entry)
    assert len(requested)==20
    dest=DOC/'human-review/final-audit-stage3.md';dest.write_bytes(('\n'.join(lines)+'\n').encode())
    receipt={'version':'S3-human-final-packet-v1','selector_manifest_sha256':sha((DOC/'manifests/human-final-source-overlay-c2.json').read_bytes()),'packet_sha256':sha(dest.read_bytes()),'requested_slots':20,'available_compact_items':sum(x['available'] for x in requested),'unavailable_slots':sum(not x['available'] for x in requested),'returned':0,'total_development_requested':20,'total_human_requested':40,'remaining_allowance':0,'model_verdicts_hidden':True,'sampling_changed':False,'items':requested}
    write(DOC/'receipts/stage3-human-final-packet-v1.json',receipt);write(OUT/'human-audit-blind-map.json',mappings);print(json.dumps({k:v for k,v in receipt.items() if k!='items'}))
if __name__=='__main__':main()
