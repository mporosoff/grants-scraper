import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import {webcrypto, createHash} from 'node:crypto';
import {shellDom} from '../helpers/shell-dom.mjs';
import {fixture} from '../helpers/shared-team-inputs.mjs';
const read = p => fs.readFileSync(p, 'utf8'), tick = () => new Promise(r => setTimeout(r, 0));
async function panel({corrupt = false, delay = false} = {}) {
  const f = await fixture(), dom = shellDom(read('match_explorer.html')), clock = {now: Date.parse(f.clock.now)}, requests = [], pending = [];
  class DecisionDate extends Date { constructor(value) {super(value ?? clock.now);} static now() {return clock.now;} }
  const c = dom.context; Object.assign(c, {URL, location: {href: 'https://example.org/match_explorer.html'}, Date: DecisionDate, TextEncoder, TextDecoder, Uint8Array, AbortController, clearTimeout, crypto: webcrypto, btoa,
    OPPORTUNITY_TEAM_INDEX: f.pack.index, RESEARCHER_DIRECTORY: f.directory, GRANT_CATALOG: f.catalog,
    XMLHttpRequest: class {constructor() {throw Error('Forbidden XHR');}}, WebSocket: class {constructor() {throw Error('Forbidden socket');}},
    FUNDING_SUBTOPICS: {loadSidecar: async () => f.sidecar}, FUNDING_FINDER_APP: {boundedScripts: {sidecar: {setTimeout: cb => setTimeout(cb, 1000), clearTimeout}}}});
  dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content', f.pack.index.generation_id);
  dom.document.getElementById('results').innerHTML = '<article class="result-card"><button id="open-shared" data-opportunity-team="call">Build team</button></article>';
  c.fetch = async url => {requests.push(url); assert.equal(url, f.pack.path); if (delay) await new Promise(r => pending.push(r)); return new Response(corrupt ? f.pack.bytes.slice(1) : f.pack.bytes);};
  dom.document.head = dom.document.querySelector('head');
  dom.document.head.appendChild = script => {
    requests.push(script.src); const name = script.src.split('?')[0]; assert(['assets/team-matcher.js', 'assets/shared-team-engine.js'].includes(name));
    const bytes = fs.readFileSync(name); assert.equal(script.integrity, 'sha256-' + createHash('sha256').update(bytes).digest('base64'));
    vm.runInContext(bytes.toString(), c); queueMicrotask(() => dom.dispatch('load', script));
  };
  vm.createContext(c); for (const p of ['site-shell', 'submission-schedule', 'search-query', 'search-retrieval', 'opportunity-team', 'opportunity-team-panel']) vm.runInContext(read('assets/' + p + '.js'), c);
  const drawer = dom.document.getElementById('team-builder');
  return {f, c, dom, drawer, requests, pending, clock, open: () => dom.dispatch('click', dom.document.getElementById('open-shared')), async ready() {
    for (let i = 0; i < 50; i++) {await tick(); if (drawer.querySelector('.opportunity-team-next') || drawer.querySelector('[data-opportunity-team-retry]')) return;} throw Error('Panel did not settle');
  }};
}
test('actual current lazy adapter and unchanged renderer: eight options, evidence, edits, handoff and zero paid boundary', async () => {
  const p = await panel(); assert.equal(p.requests.length, 0); await p.c.OpportunityTeam.loadDirectory(); assert.equal(p.requests.length, 0);
  p.open(); await p.ready(); assert.equal(p.requests.length, 3); assert.equal(p.drawer.querySelectorAll('[data-opportunity-team-variant]').length, 8);
  assert.match(p.drawer.textContent, /Coverage unconfirmed/); assert.doesNotMatch(p.drawer.textContent, /Direct evidence/);
  p.dom.dispatch('click', p.drawer.querySelectorAll('[data-opportunity-team-variant]')[7]);
  p.dom.dispatch('click', p.drawer.querySelector('[data-opportunity-team-remove]'));
  const select = p.drawer.querySelector('[data-opportunity-team-replacement]'); select.value = select.querySelectorAll('option')[1].getAttribute('value'); p.dom.dispatch('change', select);
  p.dom.dispatch('click', p.drawer.querySelector('[data-opportunity-team-add-replacement]'));
  assert.match(p.drawer.querySelector('.opportunity-team-next a').getAttribute('href'), /proposed=/);
  assert.equal(p.requests.length, 3);
  p.clock.now = Date.parse('2026-09-13T00:00:00Z'); p.dom.dispatch('click', p.drawer.querySelector('[data-opportunity-team-remove]'));
  assert.match(p.drawer.textContent, /no longer current/); assert.equal(p.requests.length, 3);
});
test('cold corrupt, retry, closed late response and stale generation never reach a provider', async () => {
  const p = await panel({corrupt: true}); p.open(); await p.ready(); assert.match(p.drawer.textContent, /temporarily unavailable/);
  p.dom.dispatch('click', p.drawer.querySelector('[data-opportunity-team-retry]')); await p.ready(); assert(p.requests.every(url => /^(assets\/(team-matcher|shared-team-engine)|data\/team_ingredients\/shared-)/.test(url)));
  const late = await panel({delay: true}); late.open(); await tick(); late.drawer.close();
  for (let i = 0; i < 6; i++) {late.pending.splice(0).forEach(r => r()); await tick();} assert.equal(late.drawer.querySelectorAll('.opportunity-team-panel').length, 0);
  const stale = await panel(); stale.open(); await stale.ready(); stale.dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content', 'f'.repeat(64));
  stale.dom.dispatch('click', stale.drawer.querySelector('[data-opportunity-team-remove]')); assert.match(stale.drawer.textContent, /temporarily unavailable/);
});
