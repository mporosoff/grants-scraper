/* Pure requested-scope arithmetic. No transport, storage, or provider clients. */
(function (global) {
  "use strict";
  const VERSION = "coverage-v2.4";
  const PARAMETERS = Object.freeze({ topic: .4, core: .3, method: .5, context: .5,
    anchor: .4, memberQuality: .5, alternativeQuality: .9, redundancy: .9, envelope: .95, maxOptions: 8,
    maxPeople: 200, maxAspects: 8, maxPassages: 16, workLimit: 300000, exactPool: 12, swapStartsPerSize: 8,
    aspectWeight: .5, coreWeight: .3, lexicalWeight: .2, mmr: 0 });
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const quantize = value => Math.round(value * 1e6);
  const bounded = value => Math.max(0, Math.min(1, value));
  const signature = ids => ids.slice().sort(cmp).join("|");
  const generic = new Set("a an and are as at be by for from in into is it of on or the to with research study studies scientific science method methods approach approaches analysis development data general interdisciplinary collaborative innovative novel using use interest interests expertise".split(" "));
  function tokens(text) {
    return new Set(String(text).normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu)?.filter(t => t.length > 2 && !generic.has(t)) || []);
  }
  function overlap(a, b) {
    const left = tokens(a), right = tokens(b);
    return left.size ? [...left].filter(t => right.has(t)).length / left.size : 0;
  }
  function dot(a, b) {
    if (!a || !b || a.length !== b.length) throw new Error("Vector shape mismatch.");
    let value = 0;
    for (let k = 0; k < a.length; k++) value += a[k] * b[k];
    if (!Number.isFinite(value)) throw new Error("Nonfinite similarity.");
    return bounded(value);
  }
  class LRU {
    constructor(limit) { this.limit = limit; this.values = new Map(); }
    get(key) { if (!this.values.has(key)) return undefined; const value = this.values.get(key); this.values.delete(key); this.values.set(key, value); return value; }
    set(key, value) { this.values.delete(key); this.values.set(key, value); while (this.values.size > this.limit) this.values.delete(this.values.keys().next().value); return value; }
  }
  function edge(aspect, core, passage, vectors) {
    const contextual = dot(vectors[aspect.vector], vectors[passage.vector]);
    const central = dot(vectors[core.vector], vectors[passage.vector]);
    const lexical = overlap(aspect.text, passage.text);
    const operation = aspect.operation && passage.operation ? overlap(aspect.operation, passage.operation) : 0;
    const context = aspect.context && passage.context ? overlap(aspect.context, passage.context) : 0;
    const specific = tokens(aspect.text).size > 0 && tokens(passage.text).size > 0;
    const topic = specific && contextual >= PARAMETERS.topic && central >= PARAMETERS.core;
    const method = specific && Boolean(aspect.operation && passage.operation && aspect.context && passage.context)
      && operation >= PARAMETERS.method && context >= PARAMETERS.context;
    const admitted = topic || method;
    return { score: admitted ? bounded(PARAMETERS.aspectWeight * contextual + PARAMETERS.coreWeight * central + PARAMETERS.lexicalWeight * lexical) : 0,
      admitted, route: topic ? "topic" : method ? "method" : "unrelated-or-insufficient",
      core: central, passage, features: [contextual, central, operation, context, lexical,
        Number(!aspect.operation || !passage.operation), Number(!aspect.context || !passage.context), Number(!specific)] };
  }
  function matrix(scope, people, vectors, rowCache) {
    const aspects = scope.aspects.slice().sort((a, b) => cmp(a.id, b.id));
    const rows = people.slice().sort((a, b) => cmp(a.id, b.id)).map(person => {
      const key = JSON.stringify([VERSION, scope.semantic_key, person.semantic_key]);
      let row = rowCache?.get(key);
      if (!row) {
        const passages = person.passages.slice().sort((a, b) => cmp(a.id, b.id));
        const allEdges = aspects.map(aspect => passages.map(p => edge(aspect, scope.core, p, vectors)));
        const edges = allEdges.map(edges => edges.slice()
          .sort((a, b) => quantize(b.score) - quantize(a.score) || cmp(a.passage.id, b.passage.id))[0] || {score: 0, admitted: false, core: 0});
        row = { id: person.id, edges, core: Math.max(0, ...passages.map(p => dot(vectors[scope.core.vector], vectors[p.vector]))),
          baseline: Math.max(0, ...passages.map(p => dot(vectors[scope.whole_call.vector], vectors[p.vector]))) };
        // A separate absolute call-person rule, never an expertise probability.
        // Original evidence admission continues to govern the accessible pool.
        const scientificWhole = Math.max(0, ...passages.filter(p => tokens(p.text).size).map(p => dot(vectors[scope.whole_call.vector], vectors[p.vector])));
        row.automatic_quality = .7 * Math.max(0, ...allEdges.flat().filter(e => !e.features[7]).map(e => e.features[0])) + .3 * scientificWhole;
        rowCache?.set(key, row);
      }
      return row;
    });
    return { aspects, rows, admitted: rows.filter(row => row.edges.some(e => e.admitted && e.score > 0)),
      weights: aspects.map(a => a.weight), key: JSON.stringify([VERSION, scope.semantic_key, people.map(p => p.semantic_key).sort(cmp)]) };
  }
  function coverage(matrix, ids) {
    const selected = ids.map(id => matrix.byId ? matrix.byId.get(id) : matrix.rows.find(r => r.id === id)).filter(Boolean);
    let value = 0;
    for (let i = 0; i < matrix.weights.length; i++) {
      let best = 0;
      for (const row of selected) { const score = row.edges[i].score; if (score > best) best = score; }
      value += matrix.weights[i] * best;
    }
    return value;
  }
  function scopedEvidence(row) {
    return [...new Set(row.edges.filter(e => e.admitted && e.score > 0 && e.passage?.text)
      .map(e => [...tokens(e.passage.text)].sort(cmp).join(" ")))].filter(Boolean);
  }
  function redundantEvidence(left, right) {
    const a = scopedEvidence(left), b = scopedEvidence(right);
    const same = (x, y) => { const p = new Set(x.split(" ")), q = new Set(y.split(" "));
      const intersection = [...p].filter(t => q.has(t)).length;
      return intersection / (p.size + q.size - intersection) >= PARAMETERS.redundancy; };
    // Scoped retained passages only. No whole-person or disciplinary distance.
    return Boolean(a.length && b.length) && a.every(x => b.some(y => same(x, y))) && b.every(y => a.some(x => same(x, y)));
  }
  function optimize(input, excludedIds = [], settings = {}) {
    const m = {...input, byId: new Map(input.rows.map(r => [r.id, r]))};
    const excluded = new Set(excludedIds);
    const people = m.admitted.filter(r => !excluded.has(r.id) && r.automatic_quality >= PARAMETERS.memberQuality).map(r => r.id).sort(cmp);
    if (people.length > PARAMETERS.maxPeople || m.weights.length > PARAMETERS.maxAspects) throw new Error("Recommendation resource limit exceeded.");
    let work = 0;
    const score = ids => { if (++work > PARAMETERS.workLimit) throw new Error("Recommendation work limit exceeded."); return coverage(m, ids); };
    const anchor = ids => ids.some(id => m.byId.get(id).edges.some(e => e.admitted && e.core >= PARAMETERS.anchor));
    const strength = id => m.byId.get(id).automatic_quality;
    const quality = ids => { const values = ids.map(strength); return [Math.min(...values), values.reduce((a,b) => a+b,0)/values.length]; };
    const compare = (a,b) => { const x = quality(a.ids), y = quality(b.ids);
      return quantize(b.score)-quantize(a.score) || quantize(y[0])-quantize(x[0]) || quantize(y[1])-quantize(x[1]) || cmp(a.key,b.key); };
    const qualityCompare = (a,b) => { const x=quality(a.ids), y=quality(b.ids);
      return quantize(y[0])-quantize(x[0]) || quantize(y[1])-quantize(x[1]) || compare(a,b); };
    const candidates = new Map();
    function feasible(ids, value) {
      return ids.length >= 2 && ids.length <= 4 && anchor(ids) && Number.isFinite(value)
        && ids.every(id => strength(id) > 0)
        && ids.every((id,i) => ids.slice(i+1).every(other => !redundantEvidence(m.byId.get(id),m.byId.get(other))));
    }
    function offer(ids) {
      const key = signature(ids);
      if (candidates.has(key)) return;
      const value = score(ids);
      if (feasible(ids, value)) candidates.set(key, {ids: ids.slice().sort(cmp), score: value, key});
    }
    if (people.length <= PARAMETERS.exactPool || settings.exact === true) {
      if (people.length > PARAMETERS.exactPool) throw new Error("Exact enumeration is bounded to small pools.");
      function visit(ids, start) {
        if (ids.length >= 2) offer(ids);
        if (ids.length === 4) return;
        for (let i = start; i < people.length; i++) visit(ids.concat(people[i]), i + 1);
      }
      visit([], 0);
    } else {
      // Greedy starts can miss a feasible pair when their best single addition
      // makes the seed redundant. Enumerate bounded pairs before larger starts;
      // admission of another reasonable candidate must not hide existing pairs.
      for (let i = 0; i < people.length; i++) for (let j = i + 1; j < people.length; j++) offer([people[i], people[j]]);
      const starts = new Map();
      // Every admitted person gets a start; nonanchors first receive their best anchor.
      for (const seed of people) {
        let ids = [seed];
        while (ids.length < 4) {
          const choices = people.filter(id => !ids.includes(id) && (anchor(ids) || anchor([id])))
            .map(id => ({id, value: score(ids.concat(id))})).sort((a, b) => quantize(b.value) - quantize(a.value) || quantize(strength(b.id))-quantize(strength(a.id)) || cmp(a.id, b.id));
          if (!choices.length) break;
          if (ids.length >= 2 && quantize(choices[0].value) <= quantize(score(ids))) break;
          ids = ids.concat(choices[0].id);
          offer(ids);
          starts.set(signature(ids), {ids, value: score(ids), key: signature(ids)});
        }
      }
      // Full-directory greedy starts precede pruning of improvement work only.
      // Every admitted person remains reachable, including those absent from these starts.
      for (const size of [2, 3, 4]) {
        const bestStarts = [...starts.values()].filter(s => s.ids.length === size)
          .sort((a, b) => quantize(b.value) - quantize(a.value) || cmp(a.key, b.key)).slice(0, PARAMETERS.swapStartsPerSize);
        for (const start of bestStarts) {
          let improved = start;
          for (const removed of start.ids) for (const added of people) {
            if (start.ids.includes(added)) continue;
            const trial = start.ids.filter(id => id !== removed).concat(added);
            const value = score(trial), key = signature(trial);
            if ((quantize(value) > quantize(improved.value) || quantize(value) === quantize(improved.value) && cmp(key, improved.key) < 0)
                && feasible(trial, value)) improved = {ids: trial, value, key};
          }
          offer(improved.ids);
        }
      }
    }
    const all = [...candidates.values()].sort(compare);
    const maximum = all[0]?.score || 0;
    const size = [2, 3, 4].find(k => all.some(t => t.ids.length === k && quantize(t.score) >= quantize(PARAMETERS.envelope * maximum)));
    const first = all.filter(t => t.ids.length === size && quantize(t.score) >= quantize(PARAMETERS.envelope * maximum)).sort(qualityCompare)[0];
    const bySize = new Map([2, 3, 4].map(k => [k, all.find(t => t.ids.length === k)?.score || 0]));
    // Do not use extra slots when a smaller feasible subset is already adequate.
    // Marginal coverage prefers useful additions; it is not universal admission.
    const minimal = t => t.ids.length === 2 || !t.ids.some(id => {
      const ids=t.ids.filter(j=>j!==id), value=score(ids);
      return quantize(value)>=quantize(PARAMETERS.envelope*t.score) && feasible(ids,value);
    });
    const nearCoverage = all.filter(t => quantize(t.score) >= quantize(PARAMETERS.envelope * bySize.get(t.ids.length)) && minimal(t));
    const bestMinimum = new Map([2,3,4].map(k=>[k,Math.max(0,...nearCoverage.filter(t=>t.ids.length===k).map(t=>quality(t.ids)[0]))]));
    const near = nearCoverage.filter(t=>quantize(quality(t.ids)[0])>=quantize(PARAMETERS.alternativeQuality*bestMinimum.get(t.ids.length)));
    const options = first ? [first] : [];
    while (options.length < PARAMETERS.maxOptions) {
      const remaining = near.filter(t => !options.includes(t)).map(t => ({team: t})).sort((a, b) => qualityCompare(a.team,b.team));
      if (!remaining.length) break;
      options.push(remaining[0].team);
    }
    return {options, feasibleCount: all.length, examinedCoverage: work, maximum, defaultIds: first?.ids || []};
  }
  function baseline(m, size, excluded = [], floors = {topic: .3, core: .25}) {
    // The comparison arm must not inherit the coverage arm's aspect admission.
    return m.rows.filter(r => !excluded.includes(r.id) && r.baseline >= floors.topic
      && (r.core ?? Math.max(0, ...r.edges.map(e => e.core))) >= floors.core)
      .slice().sort((a, b) => quantize(b.baseline) - quantize(a.baseline) || cmp(a.id, b.id)).slice(0, size).map(r => r.id);
  }
  global.TeamRecommender = Object.freeze({VERSION, PARAMETERS, cmp, quantize, signature, tokens, overlap, dot, LRU, edge, matrix, coverage, scopedEvidence, redundantEvidence, optimize, baseline});
})(globalThis);
