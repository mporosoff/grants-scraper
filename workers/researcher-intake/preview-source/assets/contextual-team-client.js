/* Restricted contextual graph loading. Only an explicit Build/Assess may POST. */
(function(g){
  'use strict';
  const VERSION='contextual-client-v1',ENDPOINT='https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual';
  const cache=new Map(),pending=new Map(),encoder=new TextEncoder();
  const incidental=new Set(['detail_checked_at','checked_at','retrieved_at','verified_on','reviewed_on','last_verified','first_seen','last_seen','updated_at']);
  const substantive=v=>Array.isArray(v)?v.map(substantive):v&&typeof v==='object'
    ?Object.fromEntries(Object.entries(v).filter(([k])=>!incidental.has(k)).map(([k,w])=>[k,substantive(w)])):v;
  const canonical=v=>g.ContextualTeamEngine.canonical(v);
  const hash=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(canonical(v))))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const assert=(v,message)=>{if(!v)throw Error(message);};
  const pick=(v,fields)=>Object.fromEntries(fields.filter(k=>v[k]!==undefined).map(k=>[k,v[k]]));
  function still(options){assert(!options.signal?.aborted,'contextual_cancelled');}
  async function read(url,options,fetcher){
    const response=await fetcher(url,{credentials:'include',redirect:'error',cache:'no-store',...options});
    if(response.status===401)throw Error('contextual_administrator_access_required');
    if(response.status===403){
      const raw=await response.arrayBuffer();assert(raw.byteLength<=200000,'contextual_response_too_large');
      let detail;try{detail=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}catch{}
      if(detail?.error==='phase2_expansion_not_authorized')throw Error('contextual_person_assessment_not_enabled');
      if(detail?.error==='outside_option1_paid_inventory')throw Error('contextual_operation_not_enabled');
      if(detail?.error==='contextual_new_paid_work_disabled')throw Error(detail.error);
      throw Error('contextual_administrator_access_required');
    }
    if(!response.ok)throw Error('contextual_service_'+response.status);
    const bytes=await response.arrayBuffer();assert(bytes.byteLength<=200000,'contextual_response_too_large');
    return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  }
  function unavailable(index,parent,reason){
    const scopes=index.scopes.filter(s=>s.parent_id===parent&&s.state!=='needs_scope_selection');
    return {schema_version:4,engine:{contextual:true,opportunityById:new Map(),facultyById:new Map(),
      scopesFor:id=>index.scopes.filter(s=>s.parent_id===id),resolveScope:()=>({ok:false,reason,scopes})}};
  }
  async function load(index,directory,options={}){
    assert(index.schema_version===4&&index.public_activation===false&&index.endpoint===ENDPOINT,'contextual_validation_manifest_required');
    const {generation_id,...body}=index;
    assert(await hash(body)===generation_id,'contextual_index_content_conflict');
    assert(directory.registry_generation===index.registry_generation,'contextual_registry_version_conflict');
    assert(await hash(directory)===index.directory_id,'contextual_directory_content_conflict');
    const parent=String(options.parentId||''),wanted=String(options.scopeId||parent);
    const scope=index.scopes.find(s=>s.id===wanted&&s.parent_id===parent);
    if(!scope)return unavailable(index,parent,'specific_scope_required');
    const permittedPeople=new Set(index.operations?.assess_person_ids||[]);
    const canAssessPerson=id=>permittedPeople.has(id)&&
      (index.operations?.assessment_scope_ids||[]).includes(scope.id);
    assert(!options.personId||canAssessPerson(options.personId),'contextual_person_assessment_not_enabled');
    if(scope.state==='needs_scope_selection')return unavailable(index,parent,'specific_scope_required');
    if(scope.state==='insufficient_source')return unavailable(index,parent,'contextual_insufficient_source');
    const original=options.record,child=scope.record_type==='publishable_child';
    const record=child?options.childCatalog?.opportunities.find(r=>String(r.opportunity_id)===scope.id&&String(r.parent_id)===parent):original;
    assert(original&&record,'contextual_canonical_scope_missing');
    const source={id:scope.id,parent_id:parent,kind:child?'publishable_child':'parent',
      science:pick(record,index.source_fields),conditions:pick(original,index.condition_fields)};
    // A reviewed official-source supplement has its own scientific identity.
    // Still bind the unchanged catalog bytes so later source edits invalidate it.
    assert(await hash(substantive(source))===(scope.catalog_source_id||scope.source_id),'contextual_source_version_conflict');
    const decisionClock=new Date(options.now||Date.now()),current=g.FUNDING_RETRIEVAL?.recordIsCurrent;
    const actionCurrent=(value,now)=>scope.currentness
      ? value===original&&!child
        ? current(scope.currentness.record,now)&&current(scope.currentness.parent,now)
        : current(value===original?scope.currentness.parent:scope.currentness.record,now)
      : current(value,now);
    assert(current&&actionCurrent(record,decisionClock)&&actionCurrent(original,decisionClock),'not_current');
    still(options);
    const person=options.personId||'',key=index.release_id+':'+scope.id+':'+person;
    const ids={release_id:index.release_id,scope_id:scope.id,person_id:person};
    let graph=cache.get(key);
    if(!graph){
      if(!pending.has(key)){
        const fetcher=options.fetcher||(index.transport==='access-window-v1'?g.ContextualTeamAccess?.fetch:g.fetch.bind(g));
        assert(typeof fetcher==='function','contextual_access_transport_unavailable');
        // The shared finite server job survives a detached panel. No AbortSignal
        // is placed on the cross-user workflow or on another panel's promise.
        const task=(async()=>{
          let value=await read(ENDPOINT+'/jobs?'+new URLSearchParams(ids),{},fetcher);
          if(value.state==='unassessed'&&options.deliberate===true){
            still(options);
            // A simple request keeps the existing Access login in charge; no
            // unauthenticated preflight bypass or credential export is needed.
            value=await read(ENDPOINT+'/jobs',{method:'POST',headers:{'Content-Type':'text/plain;charset=UTF-8'},body:JSON.stringify(ids)},fetcher);
          }
          for(let count=0;['dispatch_claimed','in_progress'].includes(value.state)&&count<168;count++){
            // Polls are reads only. A closed panel abandons display, not the
            // paid server job; a later visitor can retrieve its completion.
            if(options.signal?.aborted)throw Error('contextual_cancelled');
            options.onStatus?.(value.state);
            // One-second delivery checks during the 60-second proof window;
            // then back off. The previous ten-minute total wait remains bounded.
            await (options.wait||((ms)=>new Promise(resolve=>setTimeout(resolve,ms))))(count<60?1000:5000);
            value=await read(ENDPOINT+'/jobs?'+new URLSearchParams(ids),{},fetcher);
          }
          assert(value.release_id===index.release_id&&(!value.scope_id||value.scope_id===scope.id),'contextual_response_version_conflict');
          if(!['ready','ready_with_gaps','no_supported_group_in_assessed_set'].includes(value.state))
            return {unavailable:value.state};
          const result=value.result;
          const {graph_id,requests,...content}=result;
          assert(await hash(content)===graph_id,'contextual_graph_content_conflict');
          assert(result.source_id===scope.source_id&&result.roster_id===index.roster_id,'contextual_graph_dependencies_conflict');
          cache.set(key,result);if(cache.size>16)cache.delete(cache.keys().next().value);
          return result;
        })().finally(()=>pending.delete(key));
        pending.set(key,task);
      }
      graph=await pending.get(key);
    }
    still(options);
    assert(g.RESEARCHER_DIRECTORY===directory,'contextual_profile_pool_replaced');
    if(graph.unavailable)return unavailable(index,parent,'contextual_'+graph.unavailable);
    const engine=g.ContextualTeamEngine.create(graph,directory,{graph_id:graph.graph_id,snapshot_id:index.release_id,
      registry_generation:index.registry_generation,source_id:scope.source_id,roster_id:index.roster_id,
      scope_id:scope.id,parent_id:parent,directory_content:canonical(directory.researchers)},
      {record,parentRecord:original,currentness:actionCurrent,currentSnapshot:()=>({directory:g.RESEARCHER_DIRECTORY,
        parentRecord:(g.GRANT_CATALOG?.opportunities||[]).find(r=>String(r.opportunity_id)===parent),
        record:child?options.childCatalog?.opportunities.find(r=>String(r.opportunity_id)===scope.id):
          (g.GRANT_CATALOG?.opportunities||[]).find(r=>String(r.opportunity_id)===scope.id)})});
    return {schema_version:4,engine:Object.freeze({...engine,contextual:true,canAssessPerson}),graph_id:graph.graph_id};
  }
  g.ContextualTeamClient=Object.freeze({VERSION,load,statistics:()=>({cached_scopes:cache.size,pending:pending.size}),clearForTest:()=>{cache.clear();pending.clear();}});
})(globalThis);
