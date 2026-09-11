/* On-demand composition over the existing Team Match admission contract. */
(function (g) {
  "use strict";
  const VERSION = "shared-team-v3", snapshots = new WeakMap();
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const canonical = v => Array.isArray(v) ? "[" + v.map(canonical).join(",") + "]" : v && typeof v === "object"
    ? "{" + Object.keys(v).sort(cmp).map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}" : JSON.stringify(v);
  const clone = v => JSON.parse(JSON.stringify(v));
  const frozen = new WeakSet();
  const freeze = v => {
    if (v && typeof v === "object" && !frozen.has(v)) {
      if (Array.isArray(v)) { for (const item of v) freeze(item); }
      else { for (const key of Object.keys(v)) freeze(v[key]); }
      Object.freeze(v); frozen.add(v);
    }
    return v;
  };
  // Two bounded walks write exactly the previous canonical JSON bytes. Avoid
  // recursive map/join strings (and their large intermediate arrays) for the
  // already-resident catalog. No integrity field is omitted or moved upstream.
  function canonicalBytes(value) {
    function walk(v, write) {
      if (Array.isArray(v)) { write('['); for (let i=0;i<v.length;i++) { if(i)write(','); walk(v[i],write); } write(']'); }
      else if(v && typeof v === 'object') { write('{'); let first=true; for(const k of Object.keys(v).sort(cmp)) { if(!first)write(','); first=false;write(JSON.stringify(k));write(':');walk(v[k],write); } write('}'); }
      else write(JSON.stringify(v));
    }
    function utf8Length(text) {
      let size=0;for(let i=0;i<text.length;i++) { const c=text.charCodeAt(i);size+=c<128?1:c<2048?2:3;
        if(c>=0xd800&&c<=0xdbff&&i+1<text.length&&text.charCodeAt(i+1)>=0xdc00&&text.charCodeAt(i+1)<=0xdfff){size++;i++;} }
      return size;
    }
    let length=0;walk(value,text=>{length+=utf8Length(text);});
    const bytes=new Uint8Array(length);let offset=0;
    walk(value,text=>{for(let i=0;i<text.length;i++) {
      let c=text.charCodeAt(i);
      if(c<128) bytes[offset++]=c;
      else if(c<2048) {bytes[offset++]=192|(c>>6);bytes[offset++]=128|(c&63);}
      else if(c>=0xd800&&c<=0xdbff&&i+1<text.length&&text.charCodeAt(i+1)>=0xdc00&&text.charCodeAt(i+1)<=0xdfff) {
        c=0x10000+((c-0xd800)<<10)+(text.charCodeAt(++i)-0xdc00);
        bytes[offset++]=240|(c>>18);bytes[offset++]=128|((c>>12)&63);bytes[offset++]=128|((c>>6)&63);bytes[offset++]=128|(c&63);
      } else {bytes[offset++]=224|(c>>12);bytes[offset++]=128|((c>>6)&63);bytes[offset++]=128|(c&63);}
    }});
    check(offset===length,'Canonical encoding length mismatch.');return bytes;
  }
  function check(ok, message) { if (!ok) throw new Error(message); }
  async function hash(value) {
    return [...new Uint8Array(await g.crypto.subtle.digest("SHA-256", canonicalBytes(value)))].map(b => b.toString(16).padStart(2, "0")).join("");
  }
  const eligible = p => p.status === "active" && p.auto_proposable === true && ["main", "standby"].includes(p.pool_state) && !["hidden", "reference_only"].includes(p.pool_visibility);
  const idOf = r => String(r?.opportunity_id || r?.opportunity_number || r?.title || "");
  async function hydrate(packet, index, directory, catalog, sidecar) {
    check(g.FUNDING_TEAM_MATCHER?.normalizeProfile && g.FUNDING_SEARCH_QUERY?.tokenize && g.FUNDING_RETRIEVAL?.createChildCatalog, "Shared matching dependencies unavailable.");
    check(packet.version === VERSION && packet.schema_version === 3 && index.schema_version === 3, "Shared engine version mismatch.");
    check(await hash(packet) === index.generation_id && packet.registry_generation === directory.registry_generation
      && await hash(directory) === packet.directory_sha256 && await hash(catalog) === packet.catalog_sha256
      && await hash(sidecar) === packet.sidecar_sha256, "Mixed or stale shared input snapshot.");
    check(canonical(index.scopes) === canonical(packet.scopes) && packet.scopes.length <= 2000, "Scope routing mismatch.");
    const children = g.FUNDING_RETRIEVAL.createChildCatalog(sidecar);
    const parents = new Map(catalog.opportunities.map(r => [idOf(r), r]));
    const byChild = new Map(children.opportunities.map(r => [idOf(r), r]));
    const ids = new Set();
    for (const s of packet.scopes) {
      check(!ids.has(s.id) && parents.has(s.parent_id) && s.engine === VERSION, "Invalid shared scope identity."); ids.add(s.id);
      check(s.record_type === "specific_parent" ? s.id === s.parent_id : s.record_type === "publishable_child"
        && byChild.get(s.id)?.parent_id === s.parent_id, "Invalid child ownership.");
    }
    const faculty = directory.researchers.map(p => ({...p, terms: p.claims.filter(c => c.status === "active").map(c => ({...c, claim_revision: c.revision}))}));
    const data = freeze({schema_version: 3, generation_id: index.generation_id, faculty, opportunities: clone(packet.scopes)});
    // Search indexes are already owned by Search and are not matcher inputs.
    // Bind their original package above, but do not duplicate them in team memory.
    // Adopt immutable source objects once. A source refresh replaces its object;
    // in-place edits cannot silently change adopted scientific evidence.
    freeze(directory); freeze(catalog.opportunities); freeze(sidecar); freeze(children);
    snapshots.set(data, {packet: freeze(clone(packet)), directory, catalog: {opportunities: catalog.opportunities}, children,
      handles: {catalog, directory, sidecar}, boundGlobals: {
        catalog: g.GRANT_CATALOG === catalog, directory: g.RESEARCHER_DIRECTORY === directory, sidecar: g.SUBTOPIC_CATALOG === sidecar}});
    return data;
  }
  async function loadData(index, directory) {
    const d = index.shared;
    check(d && /^data\/team_ingredients\/shared-[a-f0-9]{64}\.json$/.test(d.path) && Number.isInteger(d.bytes) && d.bytes > 0 && d.bytes <= 2 * 1024 * 1024, "Invalid shared asset descriptor.");
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(d.path, {credentials: "omit", redirect: "error", signal: controller.signal});
      check(response.ok && response.body, "Shared asset unavailable.");
      const reader = response.body.getReader(), chunks = []; let length = 0;
      while (true) { const r = await reader.read(); if (r.done) break; length += r.value.length; if (length > d.bytes) { await reader.cancel(); throw new Error("Shared asset exceeds bound."); } chunks.push(r.value); }
      check(length === d.bytes, "Truncated shared asset."); const bytes = new Uint8Array(length); let offset = 0;
      chunks.forEach(c => { bytes.set(c, offset); offset += c.length; });
      const digest = [...new Uint8Array(await g.crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
      check(digest === d.sha256, "Corrupt shared asset.");
      const packet = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
      const sidecar = await g.FUNDING_SUBTOPICS.loadSidecar();
      return hydrate(packet, index, directory, g.GRANT_CATALOG, sidecar);
    } finally { clearTimeout(timer); }
  }
  function create(data, settings = {}) {
    const snap = snapshots.get(data); check(snap, "Shared inputs were not validated.");
    const facultyById = new Map(data.faculty.map(p => [p.id, p]));
    data.faculty.forEach(p => (p.legacy_ids || []).forEach(id => facultyById.set(id, p)));
    const profiles = data.faculty.filter(eligible).map(p => ({id: p.id, profile: freeze(g.FUNDING_TEAM_MATCHER.normalizeProfile(p))}));
    const opportunityById = new Map(data.opportunities.map(s => [s.id, s]));
    const parents = new Map(snap.catalog.opportunities.map(r => [idOf(r), r]));
    let decision = null, preparedAt = "", parentMatcher, childMatcher, actionClock = null;
    const fitCache = new Map();
    const checkedChildren = new WeakSet();
    const counts = {actions: 0, fits: 0, optimizations: 0};
    const scopesFor = parent => data.opportunities.filter(s => s.parent_id === String(parent));
    function assertSnapshot() {
      check((!snap.boundGlobals.directory && !g.RESEARCHER_DIRECTORY || g.RESEARCHER_DIRECTORY === snap.handles.directory), "Researcher pool changed; reopen the panel.");
      check((!snap.boundGlobals.catalog && !g.GRANT_CATALOG || g.GRANT_CATALOG === snap.handles.catalog)
        && snap.handles.catalog.opportunities === snap.catalog.opportunities, "Catalog changed; reopen the panel.");
      check(!snap.boundGlobals.sidecar && !g.SUBTOPIC_CATALOG || g.SUBTOPIC_CATALOG === snap.handles.sidecar, "Child source changed; reopen the panel.");
    }
    function resolveScope(input = {}) {
      decision = null;
      const now = new Date(actionClock ?? input.now ?? (settings.clock ? settings.clock() : Date.now()));
      check(Number.isFinite(+now), "Invalid comparison clock.");
      assertSnapshot();
      const parent = String(input.parentId || idOf(input.record)), scopes = scopesFor(parent), parentRecord = parents.get(parent);
      if (!parentRecord || !g.FUNDING_RETRIEVAL.recordIsCurrent(parentRecord, now)) return {ok: false, reason: "not_current", scopes};
      // Caller records may have renderer-only decorations; science is always taken from the canonical catalog.
      if (input.record && input.record !== parentRecord && (idOf(input.record) !== parent || Object.keys(parentRecord).some(k => canonical(input.record[k]) !== canonical(parentRecord[k])))) return {ok: false, reason: "unsupported_scope", scopes};
      const scope = input.scopeId ? opportunityById.get(input.scopeId) : (scopes.length === 1 && scopes[0].record_type === "specific_parent" ? scopes[0] : null);
      if (!scope || scope.parent_id !== parent) return {ok: false, reason: scopes.length ? "specific_scope_required" : "unsupported_scope", scopes};
      if (scope.record_type === "specific_parent" && input.isBroad) return {ok: false, reason: "broad_parent_rejected", scopes};
      if (input.childCatalog && !checkedChildren.has(input.childCatalog)) {
        if (canonical(input.childCatalog.opportunities) !== canonical(snap.children.opportunities)) return {ok: false, reason: "child_not_publication_eligible", scopes};
        freeze(input.childCatalog); checkedChildren.add(input.childCatalog);
      }
      if (preparedAt !== now.toISOString().slice(0, 10)) {
        parentMatcher = g.FUNDING_TEAM_MATCHER.create(snap.catalog, snap.packet.config, g.FUNDING_SEARCH_QUERY, {now, sourceCacheLimit: 8});
        childMatcher = null; preparedAt = now.toISOString().slice(0, 10); fitCache.clear();
      }
      let matcher = parentMatcher;
      if (scope.record_type === "publishable_child") matcher = childMatcher ||= g.FUNDING_TEAM_MATCHER.create(snap.children, snap.packet.config, g.FUNDING_SEARCH_QUERY, {now, sourceCacheLimit: 8});
      const prepared = matcher.records.find(r => r.id === scope.id);
      if (!prepared || !g.FUNDING_RETRIEVAL.recordIsCurrent(prepared.record, now)) return {ok: false, reason: "not_current", scopes};
      if (scope.record_type === "specific_parent" && prepared.isBroad) return {ok: false, reason: "broad_parent_rejected", scopes};
      let cached = fitCache.get(scope.id);
      if (!cached) {
        cached = {rows: profiles.map(p => ({...p, fit: matcher.scoreProfile(p.profile, prepared)})).filter(r => r.fit), options: new Map()};
        counts.fits += profiles.length;
      } else fitCache.delete(scope.id);
      fitCache.set(scope.id, cached); if (fitCache.size > 8) fitCache.delete(fitCache.keys().next().value);
      counts.actions++;
      decision = {input: {...input, now}, scope, matcher, prepared, ...cached};
      return {ok: true, opportunity: scope, scopes, readiness: "shared-catalog"};
    }
    function checked(state) {
      check(decision && decision.scope.id === state.opportunityId && state.generation === data.generation_id, "Stale or unresolved selection.");
      const now = new Date(actionClock ?? (settings.clock ? settings.clock() : Date.now()));
      check(g.FUNDING_RETRIEVAL.recordIsCurrent(parents.get(decision.scope.parent_id), now)
        && g.FUNDING_RETRIEVAL.recordIsCurrent(decision.prepared.record, now), "Opportunity expired between actions.");
      assertSnapshot();
      if (preparedAt !== now.toISOString().slice(0, 10)) check(resolveScope({...decision.input, now}).ok, "Opportunity changed between actions.");
      check(Array.isArray(state.selectedIds) && state.selectedIds.length <= 4 && new Set(state.selectedIds).size === state.selectedIds.length
        && Array.isArray(state.excludedIds) && state.excludedIds.length <= profiles.length && state.excludedIds.every(id => facultyById.has(id)), "Invalid selection.");
      check(state.selectedIds.every(id => decision.rows.some(r => r.id === id)), "Cached member no longer passes shared fit.");
      return decision;
    }
    // Coverage units are complete shared scientific relationships, not tokens or claim counts.
    const contributionCache = new WeakMap();
    function contributions(row) {
      if (contributionCache.has(row)) return contributionCache.get(row);
      const values = new Map();
      for (const c of row.fit.supportedConnections || []) values.set(c.relationship_id, Math.max(values.get(c.relationship_id) || 0, c.score));
      contributionCache.set(row, values); return values;
    }
    function combined(rows) { const values = new Map(); rows.forEach(r => contributions(r).forEach((v, k) => values.set(k, Math.max(values.get(k) || 0, v)))); return values; }
    function coverage(rows) { return [...combined(rows).values()].reduce((a, b) => a + b, 0); }
    function gain(values, row) { let sum = 0; contributions(row).forEach((v, k) => { sum += Math.max(0, v - (values.get(k) || 0)); }); return sum; }
    const evidenceCache = new WeakMap();
    function claimEvidence(row) {
      if (!evidenceCache.has(row)) evidenceCache.set(row, new Set((row.fit.supportedConnections || []).map(c => c.relationship_id)));
      return evidenceCache.get(row);
    }
    function independentEvidence(row, others) {
      // Two people can independently support the same relationship. This does
      // not earn extra coverage or a claim of distinct scientific strategy.
      // Exact duplicated profile evidence cannot manufacture a second member.
      const evidence = r => (r.fit.supportedConnections || []).map(c => g.FUNDING_SEARCH_QUERY.tokenize(c.profile_excerpt).join(' ')).sort(cmp).join('|');
      return row.fit.automaticEligible && claimEvidence(row).size > 0
        && !others.some(r => evidence(r) === evidence(row));
    }
    function justified(row, team) {
      const others = team.filter(r => r !== row);
      return row.fit.automaticEligible && (coverage(team) - coverage(others) > 1e-9 || independentEvidence(row, others));
    }
    function optimize(d, excluded) {
      const key = [...excluded].sort(cmp).join("|"); if (d.options.has(key)) return d.options.get(key);
      const pool = d.rows.filter(r => r.fit.automaticEligible && !excluded.includes(r.id)).sort((a, b) => b.fit.score - a.fit.score || cmp(a.id, b.id)), teams = new Map();
      for (const seed of pool) {
        let team = [seed];
        while (team.length < 4) {
          const base = combined(team);
          const next = pool.filter(r => !team.includes(r)).map(r => ({r, gain: gain(base, r)}))
            .sort((a, b) => b.gain - a.gain || b.r.fit.score - a.r.fit.score || cmp(a.r.id, b.r.id))[0];
          if (!next) break;
          // A minimum group may contain independently evidenced overlapping
          // contributions. Zero removal marginal is not proof of irrelevance.
          // Beyond that minimum, another person must add coverage; no slot padding.
          const choice = next.gain > 1e-9 ? next.r : team.length === 1
            ? pool.find(r => !team.includes(r) && independentEvidence(r, team) && independentEvidence(team[0], [r])) : null;
          if (!choice) break;
          team.push(choice);
          team = team.filter(r => justified(r, team));
          if (team.length >= 2 && team.some(r => r.fit.strong)) {
            const ids = team.map(r => r.id).sort(cmp), id = ids.join("+");
            teams.set(id, {ids, key: id, coverage: coverage(team), relevance: team.reduce((s, r) => s + r.fit.score, 0)});
          }
          if (team.length < 2) break;
        }
      }
      const candidates = [...teams.values()], best = Math.max(0,...candidates.map(t=>t.coverage));
      const result = candidates.filter(t=>t.coverage>=best*.95).sort((a, b) => a.ids.length-b.ids.length || b.coverage-a.coverage || b.relevance-a.relevance || cmp(a.key,b.key)).slice(0,8);
      counts.optimizations++; d.options.set(key, result); if (d.options.size > 32) d.options.delete(d.options.keys().next().value); return result;
    }
    const stateFor = (scope, ids, excluded = []) => freeze({opportunityId: scope.id, generation: data.generation_id, selectedIds: [...ids], excludedIds: [...excluded]});
    function proposal(scope) { const empty = stateFor(scope, []), d = checked(empty); return stateFor(scope, optimize(d, [])[0]?.ids || []); }
    function proposalOptions(state) { const d = checked(state); return optimize(d, state.excludedIds).map(t => ({id: d.scope.id + ":" + t.key, state: stateFor(d.scope, t.ids, state.excludedIds), label: t.ids.map(id => facultyById.get(id).name).join(" + ")})); }
    function proposalView(state) {
      const d = checked(state), rows = state.selectedIds.map(id => d.rows.find(r => r.id === id));
      const selected = rows.map(row => {
        const connection = (row.fit.supportedConnections || []).filter(c => c.claims.length || c.summary).sort((a, b) => b.score - a.score || cmp(a.label, b.label))[0];
        const claim = connection?.claims[0], profile = facultyById.get(row.id);
        const excerpt = connection?.profile_excerpt;
        const evidence = connection ? {faculty_id: row.id, contribution: connection.label, evidence_term: connection.label,
          evidence_phrase: excerpt, source_url: claim?.source_urls?.[0] || profile.summary_evidence?.[0]?.url || profile.source_url,
          why_person: "The retained profile statement “" + excerpt + "” suggests a connection to “" + connection.source_excerpt + "” (" + connection.field + ", " + connection.source_unit + "). The contribution remains unconfirmed."}
          : {faculty_id: row.id, contribution: row.fit.scopeLabel || row.fit.researchReasons.join(", "), evidence_term: "", evidence_phrase: "", source_url: profile.source_url,
            why_person: row.fit.scopeLabel ? "Broad sponsor-scope lead: " + row.fit.scopeLabel + ". Specific scientific coverage remains unconfirmed." : "Shared theme match: " + row.fit.researchReasons.join(", ") + ". Specific contribution remains unconfirmed."};
        return {profile, evidence, roles: [], relevantTerms: claim ? [claim] : []};
      });
      // No person-to-role certificate is manufactured by a match score.
      const roles = selected.map(m => ({id: m.profile.id, label: m.evidence.contribution, rationale: m.evidence.why_person,
        source_url: m.evidence.source_url, required: false, coverage: "adjacent", filled: false, directEvidence: false,
        selected_candidate_ids: [], selected_alternative_ids: [m.profile.id]}));
      selected.forEach(m => { m.roles = roles.filter(r => r.id === m.profile.id); });
      const replacements = d.rows.filter(r => !state.selectedIds.includes(r.id)).map(r => ({profile: facultyById.get(r.id), roles: [], reviewed: false,
        previouslySelected: state.excludedIds.includes(r.id), marginal: coverage([...rows, r]) - coverage(rows)}))
        .sort((a, b) => b.marginal - a.marginal || cmp(a.profile.id, b.profile.id));
      const opportunity = {...d.scope, objective: d.prepared.record.description || d.prepared.record.title, roles,
        members: selected.map(m => m.evidence), gate_state: selected.length >= 2 ? "conditional" : "fail",
        why_team: selected.map(m => m.evidence.why_person).join(" "), missing_skills: []};
      return {opportunity, selected, selectedIds: [...state.selectedIds], excludedIds: [...state.excludedIds], roles, unfilledRoles: [], complete: false,
        replacements, prepared: true, matched_people_count: d.rows.length, feasible_team_count: optimize(d, state.excludedIds).length};
    }
    function removeMember(state, id) { const d = checked(state), canonicalId = facultyById.get(id)?.id; check(canonicalId, "Unknown member."); return stateFor(d.scope, state.selectedIds.filter(x => x !== canonicalId), [...new Set([...state.excludedIds, canonicalId])]); }
    function addReplacement(state, id) { const d = checked(state), canonicalId = facultyById.get(id)?.id; check(state.selectedIds.length < 4 && !state.selectedIds.includes(canonicalId) && d.rows.some(r => r.id === canonicalId), "Replacement does not pass shared fit."); return stateFor(d.scope, [...state.selectedIds, canonicalId], state.excludedIds.filter(x => x !== canonicalId)); }
    function diagnoseScope() {
      check(decision, "Scope not resolved.");
      const teams = optimize(decision, []), pool = decision.rows, automatic = pool.filter(r=>r.fit.automaticEligible);
      return {admitted: pool.length, strong: pool.filter(r => r.fit.strong).length,
        automatic: automatic.length,
        independent_strong_evidence: pool.filter(r => claimEvidence(r).size).length,
        boundary: teams.length ? "group_produced" : !pool.length ? "no_admitted_person" : !automatic.length ? "no_supported_member" : automatic.length === 1 ? "only_one_supported_member"
          : !pool.some(r => r.fit.strong) ? "absent_scientific_anchor" : "redundancy_contribution_restriction",
        primary: (teams[0]?.ids || []).map(id => { const team = teams[0].ids.map(id => pool.find(r => r.id === id)), row = pool.find(r => r.id === id);
          return {id, removal_marginal: coverage(team) - coverage(team.filter(r => r.id !== id)), independent_strong_evidence: independentEvidence(row, team.filter(r => r.id !== id))}; })};
    }
    function runAction(input, callback) {
      check(actionClock === null, "Nested team action.");
      actionClock = new Date(input.now ?? (settings.clock ? settings.clock() : Date.now()));
      try { return callback(resolveScope({...input, now: actionClock})); }
      finally { actionClock = null; }
    }
    return Object.freeze({data, facultyById: new Map(facultyById), opportunityById: new Map(opportunityById), scopesFor, resolveScope, proposal, proposalOptions, proposalView, removeMember, addReplacement,
      runAction, diagnoseScope, statistics: () => ({...counts, cachedScopes: fitCache.size}), admittedFits: () => decision?.rows.map(r => ({id: r.id, fit: clone(r.fit)})) || []});
  }
  g.SharedTeamEngine = Object.freeze({VERSION, canonical, canonicalBytes, hash, hydrate, loadData, create, eligible});
})(globalThis);
