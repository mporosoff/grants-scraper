/* Bounded D2 ablation of the existing optimizer, no new search architecture. */
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
export function ruleEngine() {
 let code=execFileSync('git',['show','ec9c717cf1943ac68be4b1a4ba453bbb29dbd931:assets/team-recommender.js'],{encoding:'utf8'});
 const replace=(before,after)=>{if(code.split(before).length!==2)throw Error('D1 prototype seam changed');code=code.replace(before,after);};
 replace('m.admitted.filter(r => !excluded.has(r.id))','m.admitted.filter(r => !excluded.has(r.id) && r.automatic_quality >= settings.memberFloor)');
 replace('const strength = id => Math.max(0, ...m.byId.get(id).edges.filter(e => e.admitted).map(e => e.score));','const strength = id => m.byId.get(id).automatic_quality;');
 replace('quantize(value) >= quantize(PARAMETERS.group)','Number.isFinite(value)');
 replace('const candidates = new Map();',`const qualityCompare = (a,b) => { const x=quality(a.ids), y=quality(b.ids);
      return quantize(y[0])-quantize(x[0]) || quantize(y[1])-quantize(x[1]) || compare(a,b); };
    const candidates = new Map();`);
 replace('const first = all.find(t => t.ids.length === size && quantize(t.score) >= quantize(PARAMETERS.envelope * maximum));',
  'const first = all.filter(t => t.ids.length === size && quantize(t.score) >= quantize(PARAMETERS.envelope * maximum)).sort(qualityCompare)[0];');
 replace('const near = all.filter(t => quantize(t.score) >= quantize(PARAMETERS.envelope * bySize.get(t.ids.length)) && minimal(t));',
  `const nearCoverage = all.filter(t => quantize(t.score) >= quantize(PARAMETERS.envelope * bySize.get(t.ids.length)) && minimal(t));
    const bestMinimum = new Map([2,3,4].map(k=>[k,Math.max(0,...nearCoverage.filter(t=>t.ids.length===k).map(t=>quality(t.ids)[0]))]));
    const near = nearCoverage.filter(t=>quantize(quality(t.ids)[0])>=quantize(settings.rho*bestMinimum.get(t.ids.length)));`);
 replace('quantize(b.value) - quantize(a.value) || compare(a.team,b.team)','qualityCompare(a.team,b.team)');
 const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);return ctx.TeamRecommender;
}
