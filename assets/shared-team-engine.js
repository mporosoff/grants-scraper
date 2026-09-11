/* On-demand composition over the existing Team Match admission contract. */
(function (g) {
  "use strict";
  const VERSION = "shared-team-v1", snapshots = new WeakMap();
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const canonical = v => Array.isArray(v) ? "[" + v.map(canonical).join(",") + "]" : v && typeof v === "object"
    ? "{" + Object.keys(v).sort(cmp).map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}" : JSON.stringify(v);
  const clone = v => JSON.parse(JSON.stringify(v));
  const freeze = v => { if (v && typeof v === "object") { Object.values(v).forEach(freeze); Object.freeze(v); } return v; };
  function check(ok, message) { if (!ok) throw new Error(message); }
  async function hash(value) {
    return [...new Uint8Array(await g.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value))))].map(b => b.toString(16).padStart(2, "0")).join("");
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
    snapshots.set(data, freeze({packet: clone(packet), directory: clone(directory), catalog: {opportunities: clone(catalog.opportunities)}, children: {opportunities: clone(children.opportunities)}}));
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
    const profiles = data.faculty.filter(eligible).map(p => ({id: p.id, profile: g.FUNDING_TEAM_MATCHER.normalizeProfile(p)}));
    const opportunityById = new Map(data.opportunities.map(s => [s.id, s]));
    const parents = new Map(snap.catalog.opportunities.map(r => [idOf(r), r]));
    let decision = null, preparedAt = "", parentMatcher, childMatcher;
    const fitCache = new Map();
    const counts = {actions: 0, fits: 0, optimizations: 0};
    const scopesFor = parent => data.opportunities.filter(s => s.parent_id === String(parent));
    function resolveScope(input = {}) {
      decision = null;
      const now = new Date(input.now ?? (settings.clock ? settings.clock() : Date.now()));
      check(Number.isFinite(+now), "Invalid comparison clock.");
      if (g.RESEARCHER_DIRECTORY) check(canonical(g.RESEARCHER_DIRECTORY) === canonical(snap.directory), "Researcher pool changed; reopen the panel.");
      if (g.GRANT_CATALOG) check(canonical(g.GRANT_CATALOG.opportunities) === canonical(snap.catalog.opportunities), "Catalog changed; reopen the panel.");
      const parent = String(input.parentId || idOf(input.record)), scopes = scopesFor(parent), parentRecord = parents.get(parent);
      if (!parentRecord || !g.FUNDING_RETRIEVAL.recordIsCurrent(parentRecord, now)) return {ok: false, reason: "not_current", scopes};
      // Caller records may have renderer-only decorations; science is always taken from the canonical catalog.
      if (input.record && (idOf(input.record) !== parent || Object.keys(parentRecord).some(k => canonical(input.record[k]) !== canonical(parentRecord[k])))) return {ok: false, reason: "unsupported_scope", scopes};
      const scope = input.scopeId ? opportunityById.get(input.scopeId) : (scopes.length === 1 && scopes[0].record_type === "specific_parent" ? scopes[0] : null);
      if (!scope || scope.parent_id !== parent) return {ok: false, reason: scopes.length ? "specific_scope_required" : "unsupported_scope", scopes};
      if (scope.record_type === "specific_parent" && input.isBroad) return {ok: false, reason: "broad_parent_rejected", scopes};
      if (input.childCatalog && canonical(input.childCatalog.opportunities) !== canonical(snap.children.opportunities)) return {ok: false, reason: "child_not_publication_eligible", scopes};
      if (preparedAt !== now.toISOString().slice(0, 10)) {
        parentMatcher = g.FUNDING_TEAM_MATCHER.create(snap.catalog, snap.packet.config, g.FUNDING_SEARCH_QUERY, {now});
        childMatcher = null; preparedAt = now.toISOString().slice(0, 10); fitCache.clear();
      }
      let matcher = parentMatcher;
      if (scope.record_type === "publishable_child") matcher = childMatcher ||= g.FUNDING_TEAM_MATCHER.create(snap.children, snap.packet.config, g.FUNDING_SEARCH_QUERY, {now});
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
      const now = new Date(settings.clock ? settings.clock() : Date.now());
      check(g.FUNDING_RETRIEVAL.recordIsCurrent(parents.get(decision.scope.parent_id), now)
        && g.FUNDING_RETRIEVAL.recordIsCurrent(decision.prepared.record, now), "Opportunity expired between actions.");
      if (g.RESEARCHER_DIRECTORY) check(canonical(g.RESEARCHER_DIRECTORY) === canonical(snap.directory), "Researcher pool changed; reopen the panel.");
      if (g.GRANT_CATALOG) check(canonical(g.GRANT_CATALOG.opportunities) === canonical(snap.catalog.opportunities), "Catalog changed; reopen the panel.");
      if (preparedAt !== now.toISOString().slice(0, 10)) check(resolveScope({...decision.input, now}).ok, "Opportunity changed between actions.");
      check(Array.isArray(state.selectedIds) && state.selectedIds.length <= 4 && new Set(state.selectedIds).size === state.selectedIds.length
        && Array.isArray(state.excludedIds) && state.excludedIds.length <= profiles.length && state.excludedIds.every(id => facultyById.has(id)), "Invalid selection.");
      check(state.selectedIds.every(id => decision.rows.some(r => r.id === id)), "Cached member no longer passes shared fit.");
      return decision;
    }
    // Contributions are existing matched scientific tokens, not invented sponsor roles.
    const contributionCache = new WeakMap();
    function contributions(row) {
      if (contributionCache.has(row)) return contributionCache.get(row);
      const values = new Map();
      for (const c of row.fit.connections) for (const term of c.matchedTerms) values.set(term, Math.max(values.get(term) || 0, c.score));
      contributionCache.set(row, values); return values;
    }
    function combined(rows) { const values = new Map(); rows.forEach(r => contributions(r).forEach((v, k) => values.set(k, Math.max(values.get(k) || 0, v)))); return values; }
    function coverage(rows) { return [...combined(rows).values()].reduce((a, b) => a + b, 0); }
    function gain(values, row) { let sum = 0; contributions(row).forEach((v, k) => { sum += Math.max(0, v - (values.get(k) || 0)); }); return sum; }
    function optimize(d, excluded) {
      const key = [...excluded].sort(cmp).join("|"); if (d.options.has(key)) return d.options.get(key);
      const pool = d.rows.filter(r => !excluded.includes(r.id)).sort((a, b) => b.fit.score - a.fit.score || cmp(a.id, b.id)), teams = new Map();
      for (const seed of pool) {
        let team = [seed];
        while (team.length < 4) {
          const base = combined(team);
          const next = pool.filter(r => !team.includes(r)).map(r => ({r, gain: gain(base, r)}))
            .sort((a, b) => b.gain - a.gain || b.r.fit.score - a.r.fit.score || cmp(a.r.id, b.r.id))[0];
          if (!next || next.gain <= 1e-9) break;
          team.push(next.r);
          // A new member can supersede the seed. Every retained member must contribute.
          team = team.filter(r => coverage(team) - coverage(team.filter(x => x !== r)) > 1e-9);
          if (team.length >= 2 && team.some(r => r.fit.strong)) {
            const ids = team.map(r => r.id).sort(cmp), id = ids.join("+");
            teams.set(id, {ids, key: id, coverage: coverage(team), relevance: team.reduce((s, r) => s + r.fit.score, 0)});
          }
          if (team.length < 2) break;
        }
      }
      const result = [...teams.values()].sort((a, b) => b.coverage - a.coverage || a.ids.length - b.ids.length || b.relevance - a.relevance || cmp(a.key, b.key)).slice(0, 8);
      counts.optimizations++; d.options.set(key, result); if (d.options.size > 32) d.options.delete(d.options.keys().next().value); return result;
    }
    const stateFor = (scope, ids, excluded = []) => freeze({opportunityId: scope.id, generation: data.generation_id, selectedIds: [...ids], excludedIds: [...excluded]});
    function proposal(scope) { const empty = stateFor(scope, []), d = checked(empty); return stateFor(scope, optimize(d, [])[0]?.ids || []); }
    function proposalOptions(state) { const d = checked(state); return optimize(d, state.excludedIds).map(t => ({id: d.scope.id + ":" + t.key, state: stateFor(d.scope, t.ids, state.excludedIds), label: t.ids.map(id => facultyById.get(id).name).join(" + ")})); }
    function proposalView(state) {
      const d = checked(state), rows = state.selectedIds.map(id => d.rows.find(r => r.id === id));
      const selected = rows.map(row => {
        const connection = row.fit.connections.filter(c => c.claims.length).sort((a, b) => b.score - a.score || cmp(a.label, b.label))[0];
        const claim = connection?.claims[0], profile = facultyById.get(row.id);
        const evidence = claim ? {faculty_id: row.id, contribution: claim.label, evidence_term: claim.label,
          evidence_phrase: claim.evidence, source_url: claim.source_urls?.[0] || profile.source_url,
          why_person: "The retained profile statement “" + claim.evidence + "” connects to the call through “" + connection.matchedTerms.join(", ") + "”. The contribution remains unconfirmed."}
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
    return Object.freeze({data, facultyById: new Map(facultyById), opportunityById: new Map(opportunityById), scopesFor, resolveScope, proposal, proposalOptions, proposalView, removeMember, addReplacement,
      statistics: () => ({...counts, cachedScopes: fitCache.size}), admittedFits: () => decision?.rows.map(r => ({id: r.id, fit: clone(r.fit)})) || []});
  }
  g.SharedTeamEngine = Object.freeze({VERSION, canonical, hash, hydrate, loadData, create, eligible});
})(globalThis);
