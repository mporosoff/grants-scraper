/* Local validation transport: real gzip bytes, immutable files, no writes. */
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import {gzipSync} from 'node:zlib';
const root=process.cwd(),base=path.join(root,'outputs/team-recommender-stage3'),receipt=JSON.parse(fs.readFileSync('docs/team-recommender/receipts/stage3-routing-packages-v3.json'));
const server=http.createServer((req,res)=>{try{
 if(!['GET','HEAD'].includes(req.method))return res.writeHead(405).end();
 const cohort=req.headers['x-stage3-cohort']||'legacy';if(!['legacy','rollout50','rollout150','holdout_effective'].includes(cohort))return res.writeHead(400).end();
 const p=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\//,'')||'match_explorer.html';
 if(p.split('/').some(x=>x==='..')||!(/^(assets|data)\//.test(p)||/^[a-z_-]+\.html$/.test(p)))return res.writeHead(403).end();
 let raw;
 if(cohort!=='legacy'&&p==='data/researcher_directory.js')raw=Buffer.from('globalThis.RESEARCHER_DIRECTORY='+fs.readFileSync(path.join(root,receipt.packages[cohort].input_directory||('outputs/team-recommender-stage3/assembled-'+cohort),'directory.json'),'utf8')+';');
 else if(cohort!=='legacy'&&(p.startsWith('data/team-recommender/')||p==='data/opportunity_team_index.js'))raw=fs.readFileSync(path.join(root,receipt.packages[cohort].package_directory||('outputs/team-recommender-stage3/package-'+cohort),p));
 else raw=fs.readFileSync(path.join(root,p));
 if(cohort!=='legacy'&&p==='match_explorer.html')raw=Buffer.from(raw.toString().replace(/(<meta name="opportunity-team-generation" content=")[a-f0-9]+/,`$1${receipt.packages[cohort].generation}`));
 const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.f32':'application/octet-stream','.svg':'image/svg+xml'}[path.extname(p)]||'application/octet-stream';
 const compressed=/gzip/.test(req.headers['accept-encoding']||''),body=compressed?gzipSync(raw):raw;
 res.writeHead(200,{'Content-Type':mime,'Content-Length':body.length,'Cache-Control':'no-store','Vary':'Accept-Encoding',...(compressed?{'Content-Encoding':'gzip'}:{})});res.end(req.method==='HEAD'?undefined:body);
 }catch{res.writeHead(404).end('Not found');}});
server.listen(8767,'127.0.0.1',()=>console.log('Stage 3 local gzip validation server ready'));
process.on('SIGTERM',()=>server.close());process.on('SIGINT',()=>server.close());
