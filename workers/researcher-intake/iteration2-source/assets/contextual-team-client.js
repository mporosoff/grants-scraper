/* Restricted contextual graph loading. Only an explicit Build/Assess may POST. */
(function(g){
  'use strict';
  const VERSION='contextual-client-v4',ENDPOINT='https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual';
  const cache=new Map(),pending=new Map(),encoder=new TextEncoder();
  let directories=new WeakMap(),hydrated=null;
  const counts={hydrations:0,hydration_hits:0,directory_checks:0,directory_hits:0};
  const incidental=new Set(['detail_checked_at','checked_at','retrieved_at','verified_on','reviewed_on','last_verified','first_seen','last_seen','updated_at']);
  const substantive=v=>Array.isArray(v)?v.map(substantive):v&&typeof v==='object'
    ?Object.fromEntries(Object.entries(v).filter(([k])=>!incidental.has(k)).map(([k,w])=>[k,substantive(w)])):v;
  const canonical=v=>g.ContextualTeamEngine.canonical(v);
  const hash=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(canonical(v))))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const assert=(v,message)=>{if(!v)throw Error(message);};
  const pick=(v,fields)=>Object.fromEntries(fields.filter(k=>v[k]!==undefined).map(k=>[k,v[k]]));
  function freeze(v){if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;}
  function phase(options,name,detail={}){
    if(options.signal?.aborted)return;
    try{options.onPhase?.(name,detail);}catch{} // Diagnostics cannot change admission or cancellation.
  }
  function sharedPhase(entry,name,detail){for(const waiter of entry.waiters)phase(waiter.options,name,detail);}
  function publicEngine(engine,canAssessPerson){
    // Frozen objects do not make Maps immutable. Never expose the private
    // hydrated engine's Maps or its data array to a display subscriber.
    return Object.freeze({...engine,data:{...engine.data,faculty:engine.data.faculty.slice()},
      facultyById:new Map(engine.facultyById),opportunityById:new Map(engine.opportunityById),
      contextual:true,canAssessPerson});
  }
  function still(options){assert(!options.signal?.aborted,'contextual_cancelled');}
  function currentInputs(options,index,directory,factory){
    still(options);
    assert(g.RESEARCHER_DIRECTORY===directory,'contextual_profile_pool_replaced');
    assert(g.OPPORTUNITY_TEAM_INDEX===index,'contextual_manifest_replaced');
    assert(g.ContextualTeamEngine===factory,'contextual_runtime_replaced');
  }
  function subscribe(entry,options){
    return new Promise((resolve,reject)=>{
      let settled=false;
      const finish=(callback,value)=>{
        if(settled)return;
        settled=true;entry.waiters.delete(waiter);
        options.signal?.removeEventListener('abort',abort);
        callback(value);
      };
      const abort=()=>finish(reject,Error('contextual_cancelled'));
      const waiter={options,fail:error=>finish(reject,error)};
      entry.waiters.add(waiter);
      options.signal?.addEventListener('abort',abort,{once:true});
      entry.promise.then(value=>finish(resolve,value),error=>finish(reject,error));
      if(options.signal?.aborted)abort();
    });
  }
  function notify(entry,state){
    for(const waiter of Array.from(entry.waiters)){
      if(waiter.options.signal?.aborted)continue;
      try{waiter.options.onStatus?.(state);}catch(error){waiter.fail(error);}
    }
  }
  async function read(url,options,fetcher){
    const response=await fetcher(url,{credentials:'include',redirect:'error',cache:'no-store',...options});
    if(response.status===401)throw Error('contextual_administrator_access_required');
    if(response.status===403){
      const raw=await response.arrayBuffer();assert(raw.byteLength<=524288,'contextual_response_too_large');
      let detail;try{detail=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}catch{}
      if(detail?.error==='phase2_expansion_not_authorized')throw Error('contextual_person_assessment_not_enabled');
      if(detail?.error==='outside_option1_paid_inventory')throw Error('contextual_operation_not_enabled');
      if(detail?.error==='contextual_new_paid_work_disabled')throw Error(detail.error);
      throw Error('contextual_administrator_access_required');
    }
    if(!response.ok)throw Error('contextual_service_'+response.status);
    const bytes=await response.arrayBuffer();assert(bytes.byteLength<=524288,'contextual_response_too_large');
    return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  }
  function unavailable(index,parent,reason){
    const scopes=index.scopes.filter(s=>s.parent_id===parent&&s.state!=='needs_scope_selection');
    return {schema_version:4,engine:{contextual:true,opportunityById:new Map(),facultyById:new Map(),
      scopesFor:id=>index.scopes.filter(s=>s.parent_id===id),resolveScope:()=>({ok:false,reason,scopes})}};
  }
  async function load(index,directory,options={}){
    phase(options,'load_start');
    const factory=g.ContextualTeamEngine;
    assert(index.schema_version===4&&index.public_activation===false&&index.endpoint===ENDPOINT,'contextual_validation_manifest_required');
    // Adopt immutable JSON snapshots before asynchronous hashing. Refreshes
    // replace these objects; in-place changes cannot race a verified digest.
    freeze(index);
    const {generation_id,...body}=index;
    assert(await hash(body)===generation_id,'contextual_index_content_conflict');
    phase(options,'index_valid');
    assert(directory.registry_generation===index.registry_generation,'contextual_registry_version_conflict');
    const checked=directories.get(directory);
    if(checked?.id===index.directory_id&&checked.registry===index.registry_generation&&checked.factory===factory){
      counts.directory_hits++;phase(options,'directory_reused');
    }else{
      freeze(directory);counts.directory_checks++;
      assert(await hash(directory)===index.directory_id,'contextual_directory_content_conflict');
      directories.set(directory,{id:index.directory_id,registry:index.registry_generation,factory});
      phase(options,'directory_valid');
    }
    const parent=String(options.parentId||''),wanted=String(options.scopeId||parent);
    const scope=index.scopes.find(s=>s.id===wanted&&s.parent_id===parent);
    if(!scope)return unavailable(index,parent,'specific_scope_required');
    const permittedPeople=new Set(index.operations?.assess_person_ids||[]);
    const canAssessPerson=id=>permittedPeople.has(id)&&
      (index.operations?.assessment_scope_ids||[]).includes(scope.id);
    assert(!options.personId||canAssessPerson(options.personId),'contextual_person_assessment_not_enabled');
    if(scope.state==='needs_scope_selection')return unavailable(index,parent,'specific_scope_required');
    if(scope.state==='insufficient_source')return unavailable(index,parent,'contextual_insufficient_source');
    if(scope.state==='action_blocked')return unavailable(index,parent,'contextual_action_blocked');
    const original=options.record,child=scope.record_type==='publishable_child',childCatalog=options.childCatalog;
    const record=child?childCatalog?.opportunities.find(r=>String(r.opportunity_id)===scope.id&&String(r.parent_id)===parent):original;
    assert(original&&record,'contextual_canonical_scope_missing');
    freeze(original);freeze(record);
    const source={id:scope.id,parent_id:parent,kind:child?'publishable_child':'parent',
      science:pick(record,index.source_fields),conditions:pick(original,index.condition_fields)};
    // A reviewed official-source supplement has its own scientific identity.
    // Still bind the unchanged catalog bytes so later source edits invalidate it.
    assert(await hash(substantive(source))===(scope.catalog_source_id||scope.source_id),'contextual_source_version_conflict');
    const decisionClock=new Date(options.now||Date.now()),current=g.FUNDING_RETRIEVAL?.recordIsCurrent;
    const actionCurrent=(value,now)=>{
      const cutoff=scope.currentness?.not_after;
      if(cutoff!==undefined&&!(typeof cutoff==='string'&&Number.isFinite(+new Date(cutoff))&&+now<+new Date(cutoff)))return false;
      return scope.currentness
        ? value===original&&!child
          ? current(scope.currentness.record,now)&&current(scope.currentness.parent,now)
          : current(value===original?scope.currentness.parent:scope.currentness.record,now)
        : current(value,now);
    };
    assert(current&&actionCurrent(record,decisionClock)&&actionCurrent(original,decisionClock),'not_current');
    phase(options,'source_current');
    still(options);
    const person=options.personId||'',key=index.release_id+':'+scope.id+':'+person;
    const ids={release_id:index.release_id,scope_id:scope.id,person_id:person};
    let graph=cache.get(key);
    if(!graph){
      let entry=pending.get(key);
      if(!entry){
        const fetcher=options.fetcher||(index.transport==='access-window-v1'?g.ContextualTeamAccess?.fetch:g.fetch.bind(g));
        assert(typeof fetcher==='function','contextual_access_transport_unavailable');
        // One finite task is independent of its display subscribers. Closing a
        // panel cancels only that subscriber, never another viewer or the job.
        entry={waiters:new Set(),promise:null};
        entry.promise=Promise.resolve().then(async()=>{
          let ordinal=0;
          const request=async(url,init)=>{
            const request_id=++ordinal;sharedPhase(entry,'service_start',{request:request_id});
            try{return await read(url,init,fetcher);}
            finally{sharedPhase(entry,'service_end',{request:request_id});}
          };
          let value=await request(ENDPOINT+'/jobs?'+new URLSearchParams(ids),{});
          if(value.state==='unassessed'&&Array.from(entry.waiters).some(
            waiter=>waiter.options.deliberate===true&&!waiter.options.signal?.aborted)){
            // A simple request keeps the existing Access login in charge; no
            // unauthenticated preflight bypass or credential export is needed.
            value=await request(ENDPOINT+'/jobs',{method:'POST',headers:{'Content-Type':'text/plain;charset=UTF-8'},body:JSON.stringify(ids)});
          }
          for(let count=0;['dispatch_claimed','in_progress'].includes(value.state)&&count<168;count++){
            // Continue bounded reads after dispatch, including while detached.
            // A reopening viewer joins this task and receives its own updates.
            notify(entry,value.state);
            // One-second delivery checks during the 60-second proof window;
            // then back off. The previous ten-minute total wait remains bounded.
            sharedPhase(entry,'poll_wait_start',{request:ordinal});
            await (options.wait||((ms)=>new Promise(resolve=>setTimeout(resolve,ms))))(count<60?1000:5000);
            sharedPhase(entry,'poll_wait_end',{request:ordinal});
            value=await request(ENDPOINT+'/jobs?'+new URLSearchParams(ids),{});
          }
          assert(value.release_id===index.release_id&&(!value.scope_id||value.scope_id===scope.id),'contextual_response_version_conflict');
          const checkedAbstention=value.state==='no_supported_group_in_checked_candidates'&&
            value.result?.version==='contextual-audited-graph-v4'&&value.result.state===value.state;
          if(!['ready','ready_with_gaps','no_supported_group_in_assessed_set'].includes(value.state)&&!checkedAbstention)
            return {unavailable:value.state};
          const result=value.result;
          assert(encoder.encode(canonical(result)).byteLength<=393216,'contextual_graph_too_large');
          const {graph_id,requests,...content}=result;
          assert(await hash(content)===graph_id,'contextual_graph_content_conflict');
          assert(result.source_id===scope.source_id&&result.roster_id===index.roster_id,'contextual_graph_dependencies_conflict');
          cache.set(key,result);if(cache.size>16)cache.delete(cache.keys().next().value);
          return result;
        }).finally(()=>{if(pending.get(key)===entry)pending.delete(key);});
        pending.set(key,entry);
      }else phase(options,'shared_join');
      graph=await subscribe(entry,options);
    }else phase(options,'graph_cache_hit');
    currentInputs(options,index,directory,factory);
    if(graph.unavailable)return unavailable(index,parent,'contextual_'+graph.unavailable);
    phase(options,'graph_accepted');
    const snapshot=[factory,index,generation_id,directory,index.directory_id,graph,key,scope,original,record,childCatalog,current];
    if(hydrated&&snapshot.every((value,i)=>value===hydrated.snapshot[i])){
      // The private engine rechecks current global records and the fresh clock
      // when the panel resolves or mutates its own selection.
      counts.hydration_hits++;phase(options,'engine_reused');
      currentInputs(options,index,directory,factory);
      return {schema_version:4,engine:publicEngine(hydrated.engine,canAssessPerson),graph_id:graph.graph_id};
    }
    phase(options,'engine_start');
    currentInputs(options,index,directory,factory);
    const engine=factory.create(graph,directory,{graph_id:graph.graph_id,snapshot_id:index.release_id,
      registry_generation:index.registry_generation,source_id:scope.source_id,roster_id:index.roster_id,
      scope_id:scope.id,parent_id:parent,directory_content:canonical(directory.researchers)},
      {record,parentRecord:original,currentness:actionCurrent,currentSnapshot:()=>({directory:g.RESEARCHER_DIRECTORY,
        parentRecord:(g.GRANT_CATALOG?.opportunities||[]).find(r=>String(r.opportunity_id)===parent),
        record:child?childCatalog?.opportunities.find(r=>String(r.opportunity_id)===scope.id):
          (g.GRANT_CATALOG?.opportunities||[]).find(r=>String(r.opportunity_id)===scope.id)})});
    phase(options,'engine_ready');currentInputs(options,index,directory,factory);
    counts.hydrations++;hydrated={snapshot,engine};
    return {schema_version:4,engine:publicEngine(engine,canAssessPerson),graph_id:graph.graph_id};
  }
  g.ContextualTeamClient=Object.freeze({VERSION,load,statistics:()=>({cached_scopes:cache.size,pending:pending.size,
    ...counts,hydrated_scopes:hydrated?1:0}),clearForTest:()=>{cache.clear();pending.clear();directories=new WeakMap();hydrated=null;for(const key of Object.keys(counts))counts[key]=0;}});
})(globalThis);
