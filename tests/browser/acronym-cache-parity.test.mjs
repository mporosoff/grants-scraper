import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const load=p=>{const c=vm.createContext({});vm.runInContext(fs.readFileSync(new URL('../../'+p,import.meta.url),'utf8'),c);return c.FUNDING_SEARCH_QUERY;};
const old=load('tests/fixtures/frozen/post-audit-search-query.js'),current=load('assets/search-query.js');
const plain=x=>JSON.parse(JSON.stringify(x));
test('cached sentence scan preserves exact old phrase order, words and occurrence counts',()=>{
 const phrases=['Atomic force microscopy (AFM). Atomic-force microscopy; atomic force measurements.',
  'Carbon dioxide conversion; cold dense clouds. Carbon dioxide conversion (CDC).',
  "High-temperature materials science; a high temperature materials system. H.T.M.S.",
  'Pulsed Joule heating\nplasma jet hydrodynamics. PJH!',
  'Molecular dynamics simulation: molecular dynamics spectroscopy (MDS).',
  'alpha alpha alpha alpha alpha; beta beta beta beta beta.',
  'Ａｔｏｍｉｃ force microscopy. measured-in-place force micrographs.',
  'Optical and physical measurements. '+('bounded source text. '.repeat(700))+'Atomic force microscopy.'];
 let comparisons=0;
 for(const text of phrases)for(const acronym of ['AFM','afm','CDC','HTMS','PJH','MDS','aaa','bbb','OPM','a','123','LONGACRONYM']){
  assert.deepEqual(plain(current.scanAcronymPhrases(text,acronym)),plain(old.scanAcronymPhrases(text,acronym)));comparisons++;
 }
 assert.equal(comparisons,96);
});
test('resolver caching preserves catalog/context decisions and changed uncached source rows',()=>{
 const records=[{title:'Atomic force microscopy (AFM)',description:'Atomic force measurements and optical physics.'},
  {title:'Molecular dynamics simulation (MDS)',description:'Molecular dynamics spectroscopy and molecular dynamics simulation.'},
  {title:'Molecular dynamics simulation',description:'Pulsed Joule heating (PJH). Carbon dioxide conversion (CDC).'}];
 const reference=old.createAcronymResolver(records),actual=current.createAcronymResolver(records);
 const check=()=>{for(const acronym of ['AFM','MDS','PJH','CDC','abc','HPM'])for(const uppercase of [false,true])for(const context of ['', 'My research uses atomic force microscopy.', 'Molecular dynamics spectroscopy examines proteins.']){
  assert.deepEqual(plain(actual.resolve(acronym,{uppercase,context})),plain(reference.resolve(acronym,{uppercase,context})));
 }};
 check();check();
 records[0].description='High power magnetism (HPM). Quantum optical metrology (QOM).';
 // Existing already-cached questions preserve the original resolver contract;
 // newly requested acronyms read the changed source, not old prepared sentences.
 check();assert.deepEqual(plain(actual.resolve('QOM',{uppercase:true})),plain(reference.resolve('QOM',{uppercase:true})));
});
