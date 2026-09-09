// Hand-declared numerical examples only. No learned/semantic quality claims.
import assert from 'node:assert/strict';import test from 'node:test';
const gate = x => Boolean(!x.excluded && ((x.topic>=.5 && x.core>=.35) || (x.sourceOperation && x.profileOperation && x.method>=.75 && x.context>=.5 && !x.genericOnly)));
const score=(w,m,ids)=>w.reduce((f,wi,i)=>f+wi*Math.max(0,...ids.map(j=>m[i][j])),0);
function feasible(w,m,ids){const f=score(w,m,ids);return ids.length>=2&&ids.length<=4&&f>=.55&&ids.some(j=>m[0][j]>=.5)&&ids.every(j=>f-score(w,m,ids.filter(x=>x!==j))>=.03);}
test('declared method transfer can pass despite weak topic similarity, but missing context cannot',()=>{
 const x={topic:.2,core:.2,sourceOperation:true,profileOperation:true,method:.8,context:.7,genericOnly:false};assert.equal(gate(x),true);assert.equal(gate({...x,context:0}),false);assert.equal(gate({...x,sourceOperation:false}),false);
});
test('synthetic tourism-only outsider is excluded from an optical measurement fixture',()=>{
 assert.equal(gate({topic:.1,core:.1,method:0,context:0,genericOnly:true}),false);
 assert.equal(gate({topic:.95,core:.95,excluded:true}),false,'explicit exclusion dominates similarity');
});
test('best of a uniformly poor pool is no group; one excellent person cannot fabricate a pair',()=>{
 assert.equal(feasible([.7,.3],[[.1,.1],[.1,.1]],[0,1]),false);
 assert.equal(feasible([.7,.3],[[.9],[.9]],[0]),false);
});
test('complementary two-person group beats redundancy; aspect split preserves weight budget',()=>{
 const w=[.7,.3],m=[[.9,.1,.89],[.1,.9,.1]];assert.equal(feasible(w,m,[0,1]),true);assert.equal(feasible(w,m,[0,1,2]),false);
 assert.equal(score(w,m,[0,1]),score([.35,.35,.3],[m[0],m[0],m[1]],[0,1]));
});
