// Restricted package startup/query contract; no browser, provider or external network.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash,webcrypto} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {previewResponse} from '../../workers/researcher-intake/src/contextual-preview.js';

const read=name=>JSON.parse(fs.readFileSync('workers/researcher-intake/config/'+name));
const base=read('contextual-preview-v1.json');
const old=read('contextual-iteration3-preview-v1.json');
const next=read('contextual-iteration3-continuation-preview-v1.json');
const file=(bundle,name)=>bundle.files[name]||base.files[name];
const code=(bundle,name)=>gunzipSync(Buffer.from(file(bundle,name).gzip_base64,'base64')).toString();
const plain=value=>JSON.parse(JSON.stringify(value));
const hash=raw=>createHash('sha256').update(raw).digest('hex');

async function boot(bundle){
  const location=new URL('https://example.test'+bundle.base_path+'match_explorer.html?q=Artificial+Intelligence');
  const scripts=[],calls=[],timers=new Map();let timer=0,context;
  const html=code(bundle,'match_explorer.html');
  const metadata=html.match(/<script src="([^"\n]*data\/catalog-metadata\.js\?v=[^"\n]+)"/)[1];
  const document={readyState:'loading',hidden:false,currentScript:null,
    scripts:[{src:new URL(metadata,location).href}],addEventListener(){},querySelectorAll:()=>[],
    createElement(tag){const events=new Map();return {tagName:tag,dataset:{},
      addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:(name,fn)=>{if(events.get(name)===fn)events.delete(name);},
      remove(){},emit:name=>events.get(name)?.()};},
    head:{append(script){scripts.push(script.src);queueMicrotask(()=>{
      const url=new URL(script.src),name=url.pathname.slice(bundle.base_path.length);
      assert.equal(url.origin,location.origin);assert(url.pathname.startsWith(bundle.base_path));
      assert.equal(name,'data/opportunities.js');document.currentScript=script;
      try{vm.runInContext(code(bundle,name),context,{filename:name});}finally{document.currentScript=null;}
      script.emit('load');
    });}}};
  // Freeze only the source-currentness clock; no latency claims come from this fixture.
  class SourceDate extends Date{constructor(...args){super(...(args.length?args:['2026-09-23T17:00:00Z']));}static now(){return +new Date('2026-09-23T17:00:00Z');}}
  context=vm.createContext({URL,URLSearchParams,Date:SourceDate,console,document,location,navigator:{},
    TextEncoder,AbortController,Response,crypto:webcrypto,setTimeout,clearTimeout,
    performance:{now:()=>0,getEntriesByName:()=>[],mark(){}},
    fetch:async(url,options={})=>{calls.push({url:String(url),method:options.method||'GET'});throw Error('Fixture forbids network');},
    FUNDING_FINDER_SCRIPT_CLOCK:{setTimeout(fn,ms){const id=++timer;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)}});
  for(const name of ['assets/app-config.js','assets/search-query.js','assets/search-retrieval.js',
    'assets/search-v2-config.js','assets/search-hybrid.js','data/subtopics.js','data/catalog-metadata.js','assets/catalog-loader.js'])
    vm.runInContext(code(bundle,name),context,{filename:name});
  const app=code(bundle,'assets/app.js');
  const start=app.indexOf('  function validateCatalog(value) {'),end=app.indexOf('  function markPerformance(',start);
  assert(start>=0&&end>start);
  vm.runInContext(app.slice(start,end)+'globalThis.validate=validateCatalog;',context);
  let initialized=0;
  context.FUNDING_CATALOG_LOADER.configure({validate:context.validate,initialize:()=>{initialized++;}});
  const catalog=await context.FUNDING_CATALOG_LOADER.ensureCatalogReady();
  const config=context.FUNDING_FINDER_APP;
  const child=context.FUNDING_RETRIEVAL.createChildCatalog(context.SUBTOPIC_CATALOG);
  const engineOptions={searchV2:config.flags.searchV2,searchV2Config:context.FUNDING_SEARCH_V2_CONFIG};
  const parentEngine=context.FUNDING_RETRIEVAL.create(catalog,context.FUNDING_SEARCH_QUERY,{...engineOptions,catalogRole:'parent'});
  const childEngine=context.FUNDING_RETRIEVAL.create(child,context.FUNDING_SEARCH_QUERY,{...engineOptions,catalogRole:'child'});
  const client=context.FUNDING_HYBRID_SEARCH.createClient({parentCatalog:catalog,childCatalog:child,parentEngine,childEngine,
    proxyUrl:config.hybridSearch.proxyUrl,manifestUrl:config.hybridSearch.manifestUrl,vectorUrl:config.hybridSearch.vectorUrl});
  Object.assign(context,{APP_CONFIG:config,hybridSearchClient:client,state:{query:'Artificial Intelligence',hybrid:{}},
    // Reaching these means the application tried the prohibited generation path.
    hybridRequestSignature(){throw Error('Unexpected hybrid signature');},eligibleHybridParentIds(){throw Error('Unexpected hybrid eligibility');},
    launchHybridSearch(){throw Error('Unexpected semantic launch');}});
  for(const [first,last] of [['  function hybridCanRun(', '  function hybridFailureCategory('],
    ['  function scheduleHybridSearch(', '  function currentWorkflowMatches(']]){
    const a=app.indexOf(first),b=app.indexOf(last,a);assert(a>=0&&b>a);vm.runInContext(app.slice(a,b),context);
  }
  return {context,config,catalog,parentEngine,childEngine,client,calls,scripts,timers,initialized};
}

test('new restricted startup retains real catalog/search and does not initiate unavailable hybrid traffic',async()=>{
  const before=await boot(old),after=await boot(next);
  assert.equal(before.client.configured,true,'historical/public inherited configuration remains unchanged');
  assert.equal(after.client.configured,false);
  assert.equal(after.context.hybridCanRun(),false);
  assert.equal(after.context.scheduleHybridSearch('Artificial Intelligence'),undefined);
  assert.deepEqual(after.calls,[],'no manifest GET, embedding POST, or other fetch is attempted');
  assert.equal(after.initialized,1);assert.equal(after.scripts.length,1);assert.equal(after.timers.size,0);
  assert.equal(after.context.FUNDING_CATALOG_LOADER.getSnapshot().state,'ready');
  assert.deepEqual(plain(after.config.flags),plain(before.config.flags));
  assert.equal(after.config.flags.searchV2,true);assert.equal(after.config.flags.subtopics,true);
  assert.deepEqual(plain(after.catalog),plain(before.catalog));
  for(const query of ['Artificial Intelligence','quantum','electrochemistry']){
    const a=before.parentEngine.score(query,{evidence:true,semantic:false});
    const b=after.parentEngine.score(query,{evidence:true,semantic:false});
    assert.deepEqual(plain(b),plain(a),'actual lexical results remain identical for '+query);
    if(query==='Artificial Intelligence') assert(Array.from(b.discoveryScores).some(value=>value>0),
      'the continuation query retains local candidate discovery');
    assert.deepEqual(plain(after.childEngine.score(query,{evidence:true,semantic:false})),
      plain(before.childEngine.score(query,{evidence:true,semantic:false})));
  }
});

test('derived config is served from its own package identity and historical paths keep original bytes',async()=>{
  assert(Object.hasOwn(next.files,'assets/app-config.js'));
  assert(!Object.hasOwn(old.files,'assets/app-config.js'));
  const expected=file(next,'assets/app-config.js');
  for(const page of ['match_explorer.html','team_match.html']){
    const html=code(next,page),src=html.match(/<script[^>]*src="([^"]*assets\/app-config\.js\?v=[^"]+)"/)[1];
    assert.equal(new URL(src,'https://example.test'+next.base_path).searchParams.get('v'),expected.sha256);
  }
  for(const bundle of [next,old,base]){
    const response=previewResponse(bundle.base_path+'assets/app-config.js');
    assert.equal(response.status,200);assert.equal(response.headers.get('X-Contextual-Preview'),bundle.bundle_id);
    const raw=gunzipSync(Buffer.from(await response.arrayBuffer()));
    assert.equal(hash(raw),file(bundle,'assets/app-config.js').sha256);
    assert.equal(response.headers.get('X-Content-SHA256'),hash(raw));
  }
  assert.equal(previewResponse(next.base_path+'data/search-v2-voyage-manifest.json').status,404,
    'restricted serving boundary is not expanded to unrelated semantic assets');
});
