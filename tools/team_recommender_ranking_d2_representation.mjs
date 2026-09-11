/* One predeclared R1 ablation of D1 arithmetic; no provider or source access. */
import vm from 'node:vm';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
export function representationCode(){
 // Exact historical D1 bytes, available in shallow CI without fetching history.
 const raw=fs.readFileSync(new URL('../tests/fixtures/frozen/d1-team-recommender.js',import.meta.url));
 if(createHash('sha256').update(raw).digest('hex')!=='4db90706d6ce347877dd77dd99d453b8cb7bca9d30a2b6730d828603fde6c1ce')throw Error('Frozen D1 representation hash mismatch');
 let code=raw.toString('utf8');
 const replace=(a,b)=>{if(code.split(a).length!==2)throw Error('D1 representation seam changed');code=code.replace(a,b);};
 replace('function edge(aspect, core, passage, vectors) {',`function contextualDot(query, passage, vectors, summaryVector) {
    const evidence=dot(vectors[query.vector],vectors[passage.vector]);
    if (!Number.isInteger(passage.context_vector)) return evidence;
    const claim=dot(vectors[query.vector],vectors[passage.context_vector]);
    const value=Number.isInteger(summaryVector) ? .7*evidence+.2*claim+.1*dot(vectors[query.vector],vectors[summaryVector]) : (.7*evidence+.2*claim)/.9;
    return Math.min(evidence+.05,value);
  }
  function edge(aspect, core, passage, vectors, summaryVector) {`);
 replace('const contextual = dot(vectors[aspect.vector], vectors[passage.vector]);','const originalAspect = dot(vectors[aspect.vector], vectors[passage.vector]);\n    const contextual = contextualDot(aspect, passage, vectors, summaryVector);');
 replace('const central = dot(vectors[core.vector], vectors[passage.vector]);','const originalCore = dot(vectors[core.vector], vectors[passage.vector]);\n    const central = contextualDot(core, passage, vectors, summaryVector);');
 replace('contextual >= PARAMETERS.topic && central >= PARAMETERS.core','originalAspect >= PARAMETERS.topic && originalCore >= PARAMETERS.core');
 replace('core: central, passage, features:','core: originalCore, passage, features:');
 replace('edge(aspect, scope.core, p, vectors)','edge(aspect, scope.core, p, vectors, person.summary_vector)');
 replace('LRU, edge, matrix,','LRU, contextualDot, edge, matrix,');
 return code;
}
export function representationEngine(){const c={};vm.createContext(c);vm.runInContext(representationCode(),c);return c.TeamRecommender;}
