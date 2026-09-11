// Local-only validation transport, following the existing Stage 3 gzip server.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import {gzipSync} from 'node:zlib';
const types={'.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2','.xml':'application/xml; charset=utf-8'};
const root=process.cwd(),receipt=JSON.parse(fs.readFileSync('docs/team-recommender/post-audit/routing-inventory-v1.json'));
const server=http.createServer((req,res)=>{try{
 if(!['GET','HEAD'].includes(req.method))return res.writeHead(405).end();
 const cohort=req.headers['x-post-audit-cohort']||'static';if(!['static','legacy','rollout50','rollout150','rollback'].includes(cohort))return res.writeHead(400).end();
 const p=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\//,'')||'index.html';
 if(p.split('/').some(x=>x==='..')||!(/^(assets|data)\//.test(p)||/^[a-z_-]+\.html$/.test(p)||['workers/award-api/src/adapters/dod.js','workers/award-api/src/institutions.js','workers/award-api/src/ror.js','workers/award-api/src/snapshot.js','workers/award-api/src/http.js','workers/award-api/src/contract.js','workers/award-api/src/year-filter.js','config/award_institutions.json'].includes(p)))return res.writeHead(403).end();
 const packages=fs.existsSync('docs/team-recommender/post-audit/release-packages-v2.json')?'docs/team-recommender/post-audit/release-packages-v2.json':'docs/team-recommender/post-audit/release-packages-v1.json';
 if(cohort!=='static'&&fs.existsSync(packages)){const pkg=cohort==='rollback'?{bundle:'outputs/team-recommender-post-audit/rollback-published'}:JSON.parse(fs.readFileSync(packages)).packages[cohort];const file=path.resolve(root,pkg.bundle,'files',p);const raw=fs.readFileSync(file),body=/gzip/.test(req.headers['accept-encoding']||'')?gzipSync(raw):raw;res.writeHead(200,{'Content-Type':types[path.extname(p)]||'application/octet-stream','Content-Length':body.length,'Cache-Control':'no-store',...(body!==raw?{'Content-Encoding':'gzip'}:{})});return res.end(req.method==='HEAD'?undefined:body);}
 let raw;if(cohort!=='static'&&p==='data/opportunity_team_index.js')raw=Buffer.from('globalThis.OPPORTUNITY_TEAM_INDEX='+fs.readFileSync(receipt.packages[cohort].index_path,'utf8')+';');else raw=fs.readFileSync(path.join(root,p));
 if(cohort!=='static'&&p.endsWith('.html'))raw=Buffer.from(raw.toString().replace(/(<meta name="opportunity-team-generation" content=")[a-f0-9]+/,`$1${receipt.packages[cohort].generation}`));
 const mime=types[path.extname(p)]||'application/octet-stream';
 const compressed=/gzip/.test(req.headers['accept-encoding']||''),body=compressed?gzipSync(raw):raw;
 res.writeHead(200,{'Content-Type':mime,'Content-Length':body.length,'Cache-Control':'no-store','Vary':'Accept-Encoding, X-Post-Audit-Cohort',...(compressed?{'Content-Encoding':'gzip'}:{})});res.end(req.method==='HEAD'?undefined:body);
 }catch{res.writeHead(404).end('Not found');}});
server.listen(8771,'127.0.0.1',()=>console.log('Post-audit local gzip validation ready'));
function close(){server.closeAllConnections();server.close(()=>process.exit(0));}
process.on('SIGTERM',close);process.on('SIGINT',close);
