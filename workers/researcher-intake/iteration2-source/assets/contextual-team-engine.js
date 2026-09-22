/* Local composition of validated contextual relationships. No provider or network paths. */
(function(g){
  'use strict';
  const VERSION='contextual-composition-v4',cmp=(a,b)=>a<b?-1:a>b?1:0;
  const check=(ok,reason)=>{if(!ok)throw Error(reason);};
  const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'
    ?'{'+Object.keys(v).sort(cmp).map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
  const clone=v=>JSON.parse(JSON.stringify(v));
  function freeze(v){if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;}
  const eligible=p=>p.status==='active'&&p.auto_proposable===true&&['main','standby'].includes(p.pool_state)
    &&!['hidden','reference_only'].includes(p.pool_visibility);
  const useful=e=>e.coverage==='direct'||e.coverage==='method_transfer';
  const integrityGraph=graph=>graph.version==='contextual-audited-graph-v4';
  const typed=graph=>['contextual-audited-graph-v2','contextual-audited-graph-v3','contextual-audited-graph-v4'].includes(graph.version);
  const needed=(graph,r)=>!typed(graph)||(r.kind!=='optional_direction'&&r.applicability==='applies');
  const safeUrl=v=>{try{const u=new URL(v);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch{return '';}};

  function candidateGroups(graph,eligibleIds){
    const allowed=new Set(eligibleIds),byPerson=new Map(graph.people.filter(p=>allowed.has(p.person_id))
      .map(p=>[p.person_id,graph.edges.filter(e=>e.person_id===p.person_id&&useful(e))]));
    const pool=[...byPerson].filter(([,edges])=>edges.length).map(([id])=>id).sort(cmp),teams=[];
    const roles=ids=>new Set(ids.flatMap(id=>byPerson.get(id).map(e=>e.role_id)));
    function visit(ids,start){
      if(ids.length>=2&&ids.some(id=>byPerson.get(id).some(e=>e.central))){
        const texts=ids.map(id=>byPerson.get(id).map(e=>e.evidence_quote).sort(cmp).join('\n')),coverage=roles(ids).size;
        if(new Set(texts).size===ids.length&&(ids.length===2||ids.filter(id=>roles(ids.filter(x=>x!==id)).size<coverage).length>=ids.length-2))
          teams.push({ids:ids.slice(),coverage,key:ids.join('+')});
      }
      if(ids.length===4)return;
      for(let i=start;i<pool.length;i++)visit([...ids,pool[i]],i+1);
    }
    visit([],0);
    const best=Math.max(0,...teams.map(t=>t.coverage)),smallest=Math.min(4,...teams.filter(t=>t.coverage===best).map(t=>t.ids.length));
    return teams.filter(t=>t.coverage===best&&t.ids.length===smallest).sort((a,b)=>cmp(a.key,b.key)).slice(0,8).map(t=>t.ids);
  }

  function validateIntegrity(graph,directory,roles){
    const x=graph.integrity,hex=v=>/^[a-f0-9]{64}$/.test(v||'');
    check(x&&x.version==='contextual-production-integrity-v1'&&x.selection_version==='contextual-integrity-candidates-v1'
      &&x.independent_evaluation===false&&x.human_labels_added===0,'integrity_provenance');
    for(const key of ['input_sha256','contract_sha256','base_graph_id','base_graph_sha256','source_sha256','approach_id','candidate_list_sha256'])
      check(hex(x[key]),'integrity_provenance');
    check(x.base_graph_id===graph.base_graph_id&&x.base_graph_sha256===graph.base_graph_sha256&&x.source_sha256===graph.source_id
      &&graph.provenance.integrity_version===x.version&&hex(graph.provenance.integrity_sha256),'integrity_provenance');
    const eligibleIds=directory.researchers.filter(eligible).map(p=>p.id).sort(cmp);
    check(canonical(x.eligible_ids)===canonical(eligibleIds),'integrity_eligible_pool');
    const expected=candidateGroups(graph,eligibleIds).map((ids,i)=>({candidate_id:'g'+String(i+1).padStart(2,'0'),member_ids:ids}));
    check(canonical(x.candidate_groups)===canonical(expected),'integrity_candidate_equality');
    const edges=graph.edges.filter(e=>eligibleIds.includes(e.person_id)).slice().sort((a,b)=>cmp(a.person_id,b.person_id)||cmp(a.role_id,b.role_id));
    const supports=edges.map((e,i)=>({support_id:'s'+String(i+1).padStart(2,'0'),person_id:e.person_id,role_id:e.role_id,
      source_ref:roles.get(e.role_id).source_ref,retained_claim_refs:e.supporting_claims.map(c=>c.claim_id+'@'+c.revision)}));
    check(canonical(x.supports)===canonical(supports),'integrity_support_equality');
    const bySupport=new Map(supports.map(s=>[s.support_id,s])),byGroup=new Map((x.groups||[]).map(row=>[row.candidate_id,row]));
    check(Array.isArray(x.groups)&&x.groups.length===expected.length&&byGroup.size===expected.length,'integrity_complete_groups');
    const refs=new Set(graph.roles.map(r=>r.source_ref)),text=(v,min,max)=>typeof v==='string'&&v.trim().length>=min&&v.length<=max;
    for(const row of expected){
      const answer=byGroup.get(row.candidate_id);
      check(answer&&['supported','unsupported','insufficient_information'].includes(answer.status)
        &&text(answer.common_operation,0,600)&&text(answer.coordination,15,600)&&text(answer.limitations,15,400),'integrity_group_decision');
      check(Array.isArray(answer.source_refs)&&answer.source_refs.length<=6&&new Set(answer.source_refs).size===answer.source_refs.length
        &&answer.source_refs.every(ref=>refs.has(ref)),'integrity_group_source');
      check(Array.isArray(answer.members)&&canonical(answer.members.map(m=>m.person_id))===canonical(row.member_ids),'integrity_group_members');
      if(answer.status==='supported')check(answer.common_operation.trim().length>=15&&answer.source_refs.length,'integrity_common_operation');
      for(const member of answer.members){
        check(Array.isArray(member.support_ids)&&member.support_ids.length<=6&&new Set(member.support_ids).size===member.support_ids.length
          &&member.support_ids.every(id=>bySupport.get(id)?.person_id===member.person_id)
          &&text(member.contribution,15,350)&&text(member.limits,15,300),'integrity_member_support');
        if(answer.status==='supported')check(member.support_ids.length>0&&member.support_ids.every(id=>answer.source_refs.includes(bySupport.get(id).source_ref)),'integrity_member_support');
      }
    }
    const people=[...new Set(expected.flatMap(c=>c.member_ids))].sort(cmp);
    check(Array.isArray(x.explanations)&&x.explanations.length===people.length,'integrity_complete_explanations');
    for(let i=0;i<people.length;i++){
      const pid=people[i],edge=edges.filter(e=>e.person_id===pid).sort((a,b)=>Number(b.central)-Number(a.central)||cmp(a.role_id,b.role_id)||cmp(a.claim_id,b.claim_id))[0];
      const s=supports.find(s=>s.person_id===pid&&s.role_id===edge.role_id),e=x.explanations[i];
      check(e.presentation_id==='e'+String(i+1).padStart(2,'0')&&e.person_id===pid&&e.role_id===edge.role_id&&e.support_id===s.support_id
        &&canonical(e.documented_claims)===canonical(edge.supporting_claims)
        &&text(e.potential_project_relevance,15,350)&&text(e.unconfirmed_operation_or_limit,15,350),'integrity_exact_explanation');
    }
    check(x.disposition===(expected.length?'complete':'not_applicable_no_candidates'),'integrity_disposition');
    check((graph.state==='no_supported_group_in_checked_candidates')===(expected.length>0&&!x.groups.some(g=>g.status==='supported')),'integrity_group_state');
  }

  function validateGraph(graph,directory,expected){
    check(['contextual-audited-graph-v1','contextual-audited-graph-v2','contextual-audited-graph-v3','contextual-audited-graph-v4'].includes(graph.version),'graph_version_conflict');
    check(/^[a-f0-9]{64}$/.test(graph.graph_id||'')&&graph.graph_id===expected.graph_id,'graph_identity_conflict');
    for(const key of ['snapshot_id','registry_generation','source_id','roster_id'])
      check(/^[a-f0-9]{64}$/.test(graph[key]||'')&&graph[key]===expected[key],'version_conflict');
    check(graph.registry_generation===directory.registry_generation,'registry_version_conflict');
    check(['ready','ready_with_gaps','no_supported_group_in_assessed_set',...(integrityGraph(graph)?['no_supported_group_in_checked_candidates']:[])].includes(graph.state),'graph_not_ready');
    check(graph.scope.id===expected.scope_id&&graph.scope.parent_id===expected.parent_id,'scope_ownership_conflict');
    check(Array.isArray(graph.roles)&&graph.roles.length>=1&&graph.roles.length<=6,'invalid_contributions');
    const roles=new Map(graph.roles.map(r=>[r.id,r]));check(roles.size===graph.roles.length,'duplicate_contribution');
    if(typed(graph)){
      check(graph.requirement_policy==='contextual-selected-approach-v2'&&typeof graph.approach==='string'&&graph.approach.trim(),'selected_approach_conflict');
      for(const r of graph.roles){
        check(['sponsor_requirement','approach_necessary','optional_direction'].includes(r.kind)&&
          ['applies','does_not_apply','unknown'].includes(r.applicability)&&typeof r.condition==='string','contribution_kind_conflict');
        check(r.required===needed(graph,r)&&(!r.central||r.required),'derived_requirement_conflict');
        check(r.applicability==='applies'||r.condition.trim(),'conditional_disposition_missing');
      }
      check(graph.roles.some(r=>needed(graph,r)&&r.central),'active_scientific_anchor_missing');
    }
    // Initial shortlist plus the one explicitly bounded trial extension.
    check(Array.isArray(graph.people)&&graph.people.length<=13&&new Set(graph.people.map(p=>p.person_id)).size===graph.people.length,'invalid_assessed_set');
    const complete=['contextual-audited-graph-v3','contextual-audited-graph-v4'].includes(graph.version);
    check(Array.isArray(graph.edges)&&graph.edges.length<=(complete?72:30),'invalid_relationships');
    const faculty=new Map(directory.researchers.map(p=>[p.id,p])),assessed=new Set(graph.people.map(p=>p.person_id)),seen=new Set();
    for(const id of assessed)check(faculty.has(id),'unknown_assessed_person');
    for(const e of graph.edges){
      const p=faculty.get(e.person_id),r=roles.get(e.role_id),c=p?.claims.find(c=>c.claim_id===e.claim_id&&c.status==='active');
      const key=canonical([e.role_id,e.person_id,e.claim_id,e.claim_revision]);
      check(!seen.has(key)&&assessed.has(e.person_id)&&!!r&&!!c,'invalid_relationship_identity');seen.add(key);
      check(needed(graph,r),'inactive_direction_has_relationship');
      check(c.revision===e.claim_revision&&typeof e.evidence_quote==='string'&&e.evidence_quote.length>=8&&c.evidence.includes(e.evidence_quote),'retired_or_changed_evidence');
      check(['direct','method_transfer','adjacent'].includes(e.coverage)&&typeof e.central==='boolean'&&(!e.central||r.central),'invalid_assessed_category');
      check(typeof e.reason==='string'&&typeof e.gap==='string','invalid_explanation');
    }
    if(complete){
      check(graph.people.length<=12&&graph.provenance?.all_pair_decisions_retained===true&&
        graph.provenance?.independent_checker_used_for_admission===false,'complete_pair_provenance');
      for(const key of ['input_sha256','active_input_sha256','pair_input_sha256','assessment_sha256','verification_sha256'])
        check(/^[a-f0-9]{64}$/.test(graph.provenance[key]||''),'complete_pair_provenance');
      check(Array.isArray(graph.pair_decisions)&&graph.pair_decisions.length===assessed.size,'complete_pair_people');
      const pairPeople=new Set(),pairs=new Map(),outcomes=['insufficient_information','adjacent','credible_transfer','supported'];
      const strength={insufficient_information:0,adjacent:1,method_transfer:2,direct:3};
      for(const p of graph.pair_decisions){
        check(assessed.has(p.person_id)&&!pairPeople.has(p.person_id),'complete_pair_people');pairPeople.add(p.person_id);
        check(Array.isArray(p.decisions)&&p.decisions.length===roles.size,'complete_pair_questions');
        let strongest=0;
        for(const d of p.decisions){
          const key=canonical([p.person_id,d.role_id]),role=roles.get(d.role_id);
          check(role&&!pairs.has(key)&&Object.hasOwn(strength,d.coverage),'complete_pair_questions');
          check(typeof d.central==='boolean'&&(!d.central||(role.central&&useful(d))),'complete_pair_central');
          check(Array.isArray(d.claims)&&d.claims.length<=3&&(!useful(d)||d.claims.length>0),'complete_pair_claims');
          const refs=new Set();
          for(const claim of d.claims){
            const original=faculty.get(p.person_id).claims.find(c=>c.status==='active'&&c.claim_id===claim.claim_id);
            const ref=claim.claim_id+'@'+claim.revision;
            check(original&&original.revision===claim.revision&&original.evidence===claim.evidence&&!refs.has(ref),'complete_pair_claim_owner');refs.add(ref);
          }
          pairs.set(key,d);strongest=Math.max(strongest,strength[d.coverage]);
        }
        check(p.outcome===outcomes[strongest]&&graph.people.find(x=>x.person_id===p.person_id).outcome===p.outcome,'complete_pair_outcome');
      }
      const expectedEdges=[...pairs.values()].filter(useful).length;
      check(graph.edges.length===expectedEdges,'complete_pair_edge_equality');
      const seenPairs=new Set();
      for(const e of graph.edges){
        const key=canonical([e.person_id,e.role_id]),d=pairs.get(key);
        check(d&&useful(d)&&!seenPairs.has(key),'complete_pair_edge_equality');seenPairs.add(key);
        check(e.coverage===d.coverage&&e.central===d.central&&e.reason===d.reason&&e.gap===d.gap&&
          canonical(e.supporting_claims)===canonical(d.claims)&&e.claim_id===d.claims[0].claim_id&&
          e.claim_revision===d.claims[0].revision&&e.evidence_quote===d.claims[0].evidence,'complete_pair_edge_equality');
      }
    }
    if(integrityGraph(graph))validateIntegrity(graph,directory,roles);
    return graph;
  }

  function create(rawGraph,directory,expected,{record,parentRecord,currentness,clock=()=>new Date(),
    currentSnapshot=()=>({directory,record,parentRecord})}={}){
    check(typeof currentness==='function'&&record&&parentRecord,'authoritative_currentness_required');
    validateGraph(rawGraph,directory,expected);
    check(canonical(directory.researchers)===expected.directory_content,'profile_pool_changed');
    // Adopt immutable inputs once. A refreshed generation must replace the snapshot,
    // including changes to researchers that were never in this graph's shortlist.
    freeze(directory);freeze(record);freeze(parentRecord);
    const graph=freeze(clone(rawGraph)),facultyById=new Map(directory.researchers.map(p=>[p.id,freeze(clone(p))]));
    const requiredRoles=graph.roles.filter(r=>needed(graph,r));
    const eligibleIds=new Set([...facultyById.values()].filter(eligible).map(p=>p.id));
    const assessed=new Set(graph.people.map(p=>p.person_id));
    const byPerson=new Map([...assessed].map(id=>[id,graph.edges.filter(e=>e.person_id===id&&useful(e)&&eligibleIds.has(id))]));
    const pool=[...byPerson].filter(([,edges])=>edges.length).map(([id])=>id).sort(cmp);
    const scope=freeze({...graph.scope,scope_label:graph.scope.title,
      record_type:graph.scope.id===graph.scope.parent_id?'specific_parent':'publishable_child',engine:integrityGraph(graph)?VERSION:'contextual-composition-v3'}),optionCache=new Map();
    let actionClock=null;
    const counts={optimizations:0,cache_hits:0,provider_calls:0};
    const roleSet=ids=>new Set(ids.flatMap(id=>(byPerson.get(id)||[]).map(e=>e.role_id)));
    const central=ids=>ids.some(id=>(byPerson.get(id)||[]).some(e=>e.central));
    const signature=ids=>ids.slice().sort(cmp).join('+');
    function validAutomatic(ids){
      if(ids.length<2||ids.length>4||!central(ids)||!ids.every(id=>pool.includes(id)))return false;
      if(integrityGraph(graph))return graph.integrity.groups.some(g=>g.status==='supported'&&
        signature(graph.integrity.candidate_groups.find(c=>c.candidate_id===g.candidate_id).member_ids)===signature(ids));
      // Identical evidence cannot manufacture two independently useful people.
      const texts=ids.map(id=>(byPerson.get(id)||[]).map(e=>facultyById.get(id).claims.find(c=>c.claim_id===e.claim_id).evidence).sort(cmp).join('\n'));
      if(new Set(texts).size!==texts.length)return false;
      if(ids.length===2)return true;
      const covered=roleSet(ids).size;
      return ids.filter(id=>roleSet(ids.filter(x=>x!==id)).size<covered).length>=ids.length-2;
    }
    function checkAction(state){
      const now=new Date(actionClock??clock());check(Number.isFinite(+now),'invalid_action_clock');
      check(currentness(record,now)&&currentness(parentRecord,now),'not_current');
      check(directory.registry_generation===graph.registry_generation,'version_conflict');
      const current=currentSnapshot();
      check(current.directory===directory&&current.record===record&&current.parentRecord===parentRecord,'source_or_profile_pool_changed');
      if(state){
        check(state.generation===graph.graph_id&&state.opportunityId===scope.id,'stale_selection');
        check(Array.isArray(state.selectedIds)&&state.selectedIds.length<=4&&new Set(state.selectedIds).size===state.selectedIds.length,'invalid_selection');
        check(state.selectedIds.every(id=>facultyById.has(id))&&Array.isArray(state.excludedIds)&&state.excludedIds.every(id=>facultyById.has(id)),'unknown_selection');
      }
    }
    const stateFor=(ids,excluded=[])=>freeze({opportunityId:scope.id,generation:graph.graph_id,selectedIds:ids.slice(),excludedIds:excluded.slice()});
    function options(excluded=[]){
      const key=signature(excluded);if(optionCache.has(key)){counts.cache_hits++;return optionCache.get(key);}
      if(integrityGraph(graph)){
        const accepted=new Set(graph.integrity.groups.filter(g=>g.status==='supported').map(g=>g.candidate_id));
        const result=freeze(graph.integrity.candidate_groups.filter(c=>accepted.has(c.candidate_id)&&c.member_ids.every(id=>!excluded.includes(id)))
          .map(c=>({ids:c.member_ids.slice(),coverage:roleSet(c.member_ids).size,key:signature(c.member_ids)})));
        counts.optimizations++;optionCache.set(key,result);if(optionCache.size>32)optionCache.delete(optionCache.keys().next().value);return result;
      }
      const available=pool.filter(id=>!excluded.includes(id)),teams=[];
      function visit(ids,start){
        if(validAutomatic(ids))teams.push({ids:ids.slice(),coverage:roleSet(ids).size,key:signature(ids)});
        if(ids.length===4)return;
        for(let i=start;i<available.length;i++)visit([...ids,available[i]],i+1);
      }
      visit([],0);counts.optimizations++;
      // At most 1,093 subsets for the 13-person trial graph. No timeout-selected results.
      const best=Math.max(0,...teams.map(t=>t.coverage));
      const smallest=Math.min(4,...teams.filter(t=>t.coverage===best).map(t=>t.ids.length));
      const result=freeze(teams.filter(t=>t.coverage===best&&t.ids.length===smallest).sort((a,b)=>cmp(a.key,b.key)).slice(0,8));
      optionCache.set(key,result);if(optionCache.size>32)optionCache.delete(optionCache.keys().next().value);return result;
    }
    function resolveScope(input={}){
      checkAction();
      if(String(input.parentId||'')!==scope.parent_id||input.scopeId&&input.scopeId!==scope.id)
        return {ok:false,reason:'specific_scope_required',scopes:[scope]};
      return {ok:true,opportunity:scope,scopes:[scope],readiness:graph.state};
    }
    function proposal(){checkAction();return stateFor(options()[0]?.ids||[]);}
    function proposalOptions(state){checkAction(state);return options(state.excludedIds).map(t=>({id:graph.graph_id+':'+t.key,state:stateFor(t.ids,state.excludedIds),label:t.ids.map(id=>facultyById.get(id).name).join(' + ')}));}
    function proposalView(state){
      checkAction(state);
      const selected=state.selectedIds.map(id=>{
        const profile=facultyById.get(id),edge=(byPerson.get(id)||[]).slice().sort((a,b)=>Number(b.central)-Number(a.central)||cmp(a.role_id,b.role_id)||cmp(a.claim_id,b.claim_id))[0];
        const claim=edge?profile.claims.find(c=>c.claim_id===edge.claim_id):null;
        let evidence={faculty_id:id,contribution:edge?.reason||'Manual selection; contextual contribution unconfirmed.',
          evidence_term:claim?.label||'',evidence_phrase:edge?.evidence_quote||'',source_url:safeUrl(claim?.source_urls?.[0]||profile.source_url),
          why_person:edge?'Model-assessed '+(edge.coverage==='method_transfer'?'possible transfer':'contribution')+': '+edge.reason+
            ' Retained profile evidence: “'+edge.evidence_quote+'”. '+(edge.gap?'Limitation: '+edge.gap+' ':'')+'This is not a capability certificate.'
            :assessed.has(id)?'The assessment did not establish a supported contribution; retained as your manual selection.':'This person has not been contextually assessed for this scope; retained as your manual selection.'};
        if(integrityGraph(graph)){
          const e=graph.integrity.explanations.find(e=>e.person_id===id);
          evidence=e?{faculty_id:id,contribution:'Potential project relevance (inferred): '+e.potential_project_relevance,
            evidence_term:e.documented_claims.map(c=>c.label).join('; '),evidence_phrase:e.documented_claims.map(c=>c.evidence).join(' | '),
            source_url:safeUrl(claim?.source_urls?.[0]||profile.source_url),
            why_person:'Retained profile activity (audited evidence): '+e.documented_claims.map(c=>c.evidence).join(' ')+
              ' Potential project relevance (inferred): '+e.potential_project_relevance+
              ' Unconfirmed operation or limit: '+e.unconfirmed_operation_or_limit+' This is not a capability certificate.'}
            :{faculty_id:id,contribution:'Manual selection; contextual contribution unconfirmed.',evidence_term:'',evidence_phrase:'',
              source_url:safeUrl(profile.source_url),why_person:'This manual selection has no checked presentation or approved group membership.'};
        }
        return {profile,evidence,roles:[],relevantTerms:claim?[claim]:[]};
      });
      const covered=roleSet(state.selectedIds);
      const roles=requiredRoles.map(r=>({id:r.id,label:r.label,required:r.required,rationale:typed(graph)
        ?r.kind==='sponsor_requirement'?'Model-interpreted scientific source constraint; applicability and coverage remain unconfirmed.'
          :'Planning contribution for the selected approach, not a sponsor-mandated role; coverage remains unconfirmed.'
        :'Model-assessed planning contribution; coverage remains unconfirmed.',
        coverage:'adjacent',filled:false,directEvidence:false,selected_candidate_ids:[],
        selected_alternative_ids:state.selectedIds.filter(id=>(byPerson.get(id)||[]).some(e=>e.role_id===r.id)),source_url:safeUrl(scope.source_url)}));
      selected.forEach(p=>{p.roles=roles.filter(r=>r.selected_alternative_ids.includes(p.profile.id));});
      const replacements=[...facultyById.values()].filter(p=>p.status==='active'&&p.pool_visibility!=='hidden'&&!state.selectedIds.includes(p.id))
        .map(profile=>({profile,roles:[],reviewed:false,previouslySelected:state.excludedIds.includes(profile.id),
          assessment_state:assessed.has(profile.id)?byPerson.get(profile.id)?.length?'assessed_useful':'assessed_uncertain':'unassessed',
          marginal:roleSet([...state.selectedIds,profile.id]).size-covered.size}))
        .sort((a,b)=>Number(pool.includes(b.profile.id))-Number(pool.includes(a.profile.id))||b.marginal-a.marginal||cmp(a.profile.id,b.profile.id));
      const approved=integrityGraph(graph)?graph.integrity.groups.find(group=>group.status==='supported'&&
        signature(group.members.map(m=>m.person_id))===signature(state.selectedIds)):null;
      const joint=approved?'Checked common operation (model inference): '+approved.common_operation+
        ' Proposed coordination: '+approved.coordination+' Group limitation: '+approved.limitations+' ':'';
      return {opportunity:{...scope,objective:graph.objective,roles,members:selected.map(m=>m.evidence),gate_state:validAutomatic(state.selectedIds)?'conditional':'fail',
          why_team:(typed(graph)?'Selected scientific approach: '+graph.approach+'. '+(graph.limitations||[]).map(s=>'Scope limitation: '+s).join(' ')+' ':'')+joint+selected.map(m=>m.evidence.why_person).join(' '),
          missing_skills:requiredRoles.filter(r=>!covered.has(r.id)).map(r=>r.label)},
        selected,selectedIds:state.selectedIds.slice(),excludedIds:state.excludedIds.slice(),roles,
        unfilledRoles:roles.filter(r=>!covered.has(r.id)),complete:false,replacements,prepared:true,
        matched_people_count:pool.length,assessed_people_count:assessed.size,unassessed_people_count:eligibleIds.size-[...assessed].filter(id=>eligibleIds.has(id)).length,
        feasible_team_count:options(state.excludedIds).length};
    }
    function removeMember(state,id){checkAction(state);check(facultyById.has(id),'unknown_member');return stateFor(state.selectedIds.filter(x=>x!==id),[...new Set([...state.excludedIds,id])]);}
    function addReplacement(state,id){checkAction(state);const p=facultyById.get(id);check(state.selectedIds.length<4&&!state.selectedIds.includes(id)&&p?.status==='active'&&p.pool_visibility!=='hidden','invalid_addition');return stateFor([...state.selectedIds,id],state.excludedIds.filter(x=>x!==id));}
    function runAction(input,callback){check(actionClock===null,'nested_action');actionClock=new Date(input.now??clock());try{return callback(resolveScope(input));}finally{actionClock=null;}}
    return Object.freeze({data:{schema_version:4,generation_id:graph.graph_id,faculty:[...facultyById.values()]},facultyById,
      opportunityById:new Map([[scope.id,scope]]),scopesFor:id=>id===scope.parent_id?[scope]:[],resolveScope,proposal,proposalOptions,
      proposalView,removeMember,addReplacement,runAction,statistics:()=>({...counts,cached_options:optionCache.size}),
      unassessedIds:()=>[...eligibleIds].filter(id=>!assessed.has(id))});
  }
  g.ContextualTeamEngine=Object.freeze({VERSION,canonical,eligible,validateGraph,create,candidateGroups});
})(globalThis);
