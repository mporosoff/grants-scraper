/* Versioned public ingredients and the existing nonvisual proposal contract. */
(function (global) {
  "use strict";
  const N = global.TeamRecommender;
  const VERSION = "ingredients-v2.1";
  const HASH = /^[a-f0-9]{64}$/;
  const ID = /^[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}$/;
  // Canonical NSF feed IDs are source identities, never fetch destinations.
  // Preserve exact catalog bytes; reject aliases, query strings and URL tricks.
  const NSF_ID = /^nsf-funding:https:\/\/www\.nsf\.gov\/funding\/opportunities\/[a-z0-9]+(?:-[a-z0-9]+)*\/(?:nsf[0-9]{2}-[0-9]{3}|pd[0-9]{2}-[0-9]{3}[0-9a-z])$/;
  function sourceId(value) { return typeof value === "string" && (ID.test(value) || value.length <= 256 && NSF_ID.test(value)); }
  const MAX_BYTES = 8 * 1024 * 1024;
  const prepared = new WeakMap();
  const rowCache = new N.LRU(1600);
  const materialFields = ["opportunity_id", "subtopic_id", "parent_id", "title", "description", "summary", "source", "source_url",
    "documents", "publication_state", "child_type", "scope", "source_hash", "content_hash", "source_updated_date",
    "source_document_hash", "source_document_url", "source_version", "parent_subtopic_id", "source_role"];
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort(N.cmp).map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  function recordKey(record) {
    return canonical(Object.fromEntries(materialFields.map(key => [key, record?.[key] ?? null])));
  }
  function requireValue(ok, message) { if (!ok) throw new Error(message); }
  function exactKeys(value, keys, label) {
    requireValue(value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).every(k => keys.includes(k)), "Unexpected " + label + " fields.");
  }
  function string(value, max = 2000) { return typeof value === "string" && value.length > 0 && new TextEncoder().encode(value).length <= max; }
  function eligible(p) { return p.status === "active" && p.auto_proposable === true && ["main", "standby"].includes(p.pool_state) && !["hidden", "reference_only"].includes(p.pool_visibility); }
  function safeUrl(value) {
    try {
      const u = new URL(value);
      return u.protocol === "https:" && !u.username && !u.password && !u.port && !u.hash.startsWith("#javascript")
        && !/^(localhost|.*\.localhost|.*\.local|\d+(?:\.\d+){3}|\[.*\])$/i.test(u.hostname) && u.hostname.includes(".");
    } catch (_) { return false; }
  }
  function freeze(value) {
    if (value && typeof value === "object" && !Object.isFrozen(value)) { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
  }
  async function sha256(value) {
    const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
    return [...new Uint8Array(await global.crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function current(record, now) {
    const retrieval = global.FUNDING_RETRIEVAL, schedule = global.FUNDING_SUBMISSION_SCHEDULE;
    if (!retrieval?.recordIsCurrent || !schedule?.nextSubmission) return {ok: false, reason: "currentness_unavailable"};
    if (!Number.isFinite(now.getTime()) || !retrieval.recordIsCurrent(record, now)) return {ok: false, reason: "not_current"};
    const submission = schedule.nextSubmission(record, now.toISOString().slice(0, 10));
    // Unknown/invitation prerequisites cannot truthfully become an actionable automatic proposal.
    if (["closed", "prerequisite_closed", "resubmission_only"].includes(submission.access)) return {ok: false, reason: "not_current", submission};
    if (!["open", "rolling", "not_listed"].includes(submission.access)) return {ok: false, reason: "unsupported_scope", submission};
    return {ok: true, submission};
  }
  function readiness(scope, source, record, now) {
    if (!scope || scope.prepared !== true) return {ok: false, reason: "unsupported_scope", readiness: scope?.readiness || "missing"};
    const r = source?.receipt;
    if (!r || r.kind !== "source-span-validation-v1" || r.validation_state !== "source-backed") return {ok: false, reason: "unsupported_scope", readiness: "unvalidated"};
    if (source.record_key !== recordKey(record) || r.source_record_key !== source.record_key) return {ok: false, reason: "unsupported_scope", readiness: "source-changed"};
    if (!Number.isFinite(Date.parse(r.checked_at)) || !Number.isFinite(Date.parse(r.valid_until))
        || Date.parse(r.checked_at) > now.getTime() || Date.parse(r.valid_until) < now.getTime()) return {ok: false, reason: "unsupported_scope", readiness: "stale-receipt"};
    return {ok: true, readiness: "prepared-source-backed"};
  }
  async function hydrate(input, vectorsBuffer, manifest, index, directory) {
    // Clone before validation; callers cannot change a validated snapshot underneath an open panel.
    const bundle = JSON.parse(JSON.stringify(input));
    exactKeys(manifest, ["schema_version", "generation_id", "registry_generation", "engine_version", "ingredient_version", "embedding_space", "metadata", "vectors", "reviewed_relations", "source_validations"], "ingredient manifest");
    requireValue(N && manifest.schema_version === 2 && manifest.engine_version === N.VERSION && manifest.ingredient_version === VERSION,
      "Ingredient engine/schema mismatch.");
    requireValue(manifest.generation_id === index.generation_id && HASH.test(manifest.generation_id)
      && manifest.registry_generation === directory.registry_generation, "Mixed registry/ingredient snapshot.");
    exactKeys(bundle, ["schema_version", "registry_generation", "sources", "people", "scopes", "vector_rows", "space"], "ingredient bundle");
    requireValue(bundle.schema_version === 2 && bundle.registry_generation === directory.registry_generation, "Mixed public bundle identity.");
    const space = bundle.space;
    exactKeys(space, ["provider", "model", "dimension", "preprocessing", "normalization", "serialization", "truncation", "roles", "canaries", "fingerprint", "source_output_dtype", "chunking", "input_encoding"], "embedding-space");
    requireValue(space.provider === "voyage" && space.model === "voyage-4-lite" && space.dimension === 1024
      && space.preprocessing === "exact-utf8-text-v1" && space.normalization === "l2-v1" && space.serialization === "f32le-v1"
      && space.source_output_dtype === "float" && space.chunking === "one-input-per-item" && space.input_encoding === "utf8"
      && space.truncation === false && canonical(space.roles) === canonical({scope: "query", passage: "document"})
      && HASH.test(space.canaries?.query) && HASH.test(space.canaries?.document), "Embedding-space contract is incomplete.");
    const {fingerprint, ...spaceContract} = space;
    requireValue(await sha256(canonical(spaceContract)) === fingerprint && fingerprint === manifest.embedding_space, "Embedding-space identity mismatch.");
    requireValue(Array.isArray(bundle.vector_rows) && bundle.vector_rows.length <= 3840 && vectorsBuffer.byteLength === bundle.vector_rows.length * 1024 * 4, "Invalid vector byte length.");
    requireValue(await sha256(vectorsBuffer) === manifest.vectors.sha256 && vectorsBuffer.byteLength === manifest.vectors.bytes, "Corrupt vector asset.");
    requireValue(Array.isArray(bundle.scopes) && bundle.scopes.length <= 330 && Array.isArray(bundle.sources) && bundle.sources.length === bundle.scopes.length,
      "Invalid scope/source inventory.");
    requireValue(Array.isArray(manifest.source_validations) && manifest.source_validations.length === bundle.scopes.filter(s => s.prepared === true).length,
      "Original-source validation inventory mismatch.");
    requireValue(Array.isArray(bundle.people) && bundle.people.length <= N.PARAMETERS.maxPeople, "Invalid public researcher inventory.");
    const vectorView = new DataView(vectorsBuffer), vectors = [], rowIds = new Set(), rowHashes = [], exactInputs = new Map();
    for (let i = 0; i < bundle.vector_rows.length; i++) {
      const row = bundle.vector_rows[i];
      exactKeys(row, ["id", "text_sha256", "input_role", "space"], "vector row");
      requireValue(ID.test(row.id) && !rowIds.has(row.id) && HASH.test(row.text_sha256) && ["query", "document"].includes(row.input_role) && row.space === fingerprint, "Invalid vector-row provenance.");
      rowIds.add(row.id);
      const values = new Float32Array(1024); let norm = 0;
      for (let k = 0; k < 1024; k++) { const v = vectorView.getFloat32((i * 1024 + k) * 4, true); requireValue(Number.isFinite(v), "Nonfinite vector."); values[k] = v; norm += v * v; }
      requireValue(Math.abs(norm - 1) <= .0001, "Unnormalized vector."); vectors.push(values);
      const hash = await sha256(vectorsBuffer.slice(i * 4096, (i + 1) * 4096)), key = row.input_role + ":" + row.text_sha256;
      requireValue(!exactInputs.has(key) || exactInputs.get(key) === hash, "Conflicting vectors for one exact input.");
      exactInputs.set(key, hash); rowHashes.push(hash);
    }
    const usedRows = new Set();
    async function vectorRecord(item, role) {
      const row = bundle.vector_rows[item.vector];
      requireValue(Number.isInteger(item.vector) && row && row.input_role === role && row.text_sha256 === await sha256(item.text), "Vector text/input-role mismatch.");
      usedRows.add(item.vector);
      item.vector_identity = rowHashes[item.vector];
    }
    const directoryById = new Map(directory.researchers.map(p => [p.id, p]));
    const expectedPeople = directory.researchers.filter(eligible).map(p => p.id).sort(N.cmp);
    requireValue(canonical(bundle.people.map(p => p.id).sort(N.cmp)) === canonical(expectedPeople), "Prepared directory omits or adds eligible researchers.");
    for (const person of bundle.people) {
      exactKeys(person, ["id", "passages"], "person");
      const profile = directoryById.get(person.id), seen = new Set(), retained = new Set();
      requireValue(Array.isArray(person.passages) && person.passages.length <= 16, "Public passage bound exceeded.");
      for (const passage of person.passages) {
        exactKeys(passage, ["id", "text", "claim_refs", "source_urls", "operation", "context", "vector"], "passage");
        requireValue(ID.test(passage.id) && string(passage.text) && !seen.has(passage.text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim()), "Duplicate or over-bound passage.");
        seen.add(passage.text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim());
        requireValue(Array.isArray(passage.claim_refs) && passage.claim_refs.length > 0 && Array.isArray(passage.source_urls) && passage.source_urls.length > 0 && passage.source_urls.every(safeUrl), "Missing public passage provenance.");
        for (const ref of passage.claim_refs) {
          exactKeys(ref, ["claim_id", "revision"], "claim reference");
          const claim = profile.claims.find(c => c.claim_id === ref.claim_id && c.revision === ref.revision && c.status === "active");
          requireValue(claim && claim.evidence === passage.text && passage.source_urls.every(url => claim.source_urls.includes(url)) && !retained.has(ref.claim_id), "Stale, private, or altered claim passage.");
          retained.add(ref.claim_id);
        }
        for (const key of ["operation", "context"]) requireValue(!passage[key] || string(passage[key], 200) && passage.text.includes(passage[key]), "Unsupported profile descriptor.");
        await vectorRecord(passage, "document");
      }
      requireValue(profile.claims.filter(c => c.status === "active").every(c => retained.has(c.claim_id)), "Prepared profile drops active evidence.");
      person.semantic_key = await sha256(canonical([fingerprint, person.id, person.passages]));
    }
    const sources = new Map(), scopeIds = new Set();
    for (const source of bundle.sources) {
      exactKeys(source, ["id", "parent_id", "record_key", "source_url", "document_sha256", "receipt", "excerpts"], "source");
      requireValue(sourceId(source.id) && sourceId(source.parent_id) && !sources.has(source.id) && safeUrl(source.source_url) && HASH.test(source.document_sha256) && string(source.record_key, 32000), "Invalid source identity.");
      requireValue(Array.isArray(source.excerpts) && source.excerpts.length <= 16, "Over-bound source excerpts.");
      const ids = new Set();
      for (const e of source.excerpts) {
        exactKeys(e, ["id", "text", "offset", "locator", "sha256"], "source excerpt");
        requireValue(ID.test(e.id) && !ids.has(e.id) && string(e.text, 8000) && string(e.locator, 200) && Number.isInteger(e.offset) && e.offset >= 0 && await sha256(e.text) === e.sha256, "Invalid original source span."); ids.add(e.id);
      }
      if (source.receipt) {
        const r = source.receipt;
        exactKeys(r, ["id", "kind", "validation_state", "scope_id", "parent_id", "approach_id", "document_sha256", "source_record_key", "checked_at", "valid_until", "span_hashes"], "validation receipt");
        requireValue(ID.test(r.id) && r.scope_id === source.id && r.parent_id === source.parent_id && r.document_sha256 === source.document_sha256
          && r.source_record_key === source.record_key && canonical(r.span_hashes) === canonical(source.excerpts.map(e => e.sha256)), "Source receipt ownership mismatch.");
      }
      sources.set(source.id, source);
    }
    function span(item, source) {
      const s = item.span, excerpt = source.excerpts.find(e => e.id === s?.excerpt_id);
      exactKeys(s, ["excerpt_id", "start", "end"], "source span");
      requireValue(excerpt && Number.isInteger(s.start) && Number.isInteger(s.end) && s.start >= 0 && s.end > s.start && s.end <= excerpt.text.length
        && excerpt.text.slice(s.start, s.end) === item.text, "Source span text/ownership mismatch.");
      for (const key of ["operation", "context"]) requireValue(!item[key] || string(item[key], 200) && item.text.includes(item[key]), "Unsupported source descriptor.");
    }
    for (const scope of bundle.scopes) {
      exactKeys(scope, ["id", "parent_id", "record_type", "scope_label", "approach_id", "prepared", "readiness", "core", "whole_call", "aspects", "group_budgets", "evidence_links"], "scope");
      requireValue(sourceId(scope.id) && sourceId(scope.parent_id) && !scopeIds.has(scope.id) && ["specific_parent", "publishable_child", "declared_branch"].includes(scope.record_type)
        && (scope.record_type !== "specific_parent" || scope.id === scope.parent_id) && string(scope.scope_label, 1000), "Invalid scope identity.");
      scopeIds.add(scope.id);
      const source = sources.get(scope.id);
      requireValue(source && source.parent_id === scope.parent_id, "Missing owned source.");
      if (!scope.prepared) { requireValue(["missing", "stale", "ambiguous", "unvalidated", "unsupported"].includes(scope.readiness) && !scope.aspects?.length, "Unprepared source carries recommendations."); continue; }
      requireValue(source.receipt?.kind === "source-span-validation-v1" && source.receipt.validation_state === "source-backed" && source.receipt.approach_id === scope.approach_id, "Prepared source lacks validation receipt.");
      const originalValidation = (manifest.source_validations || []).find(r => r.scope_id === scope.id);
      exactKeys(originalValidation, ["validation", "scope_id", "parent_id", "document_sha256", "text_sha256", "retrieved_at", "observed_at", "new_retrieval", "excerpt_count", "excerpt_hashes", "semantic_judgment", "provenance", "limitations"], "original-source validation");
      const retained = ["retained-official-fields-verified", "retained-native-spans-verified"].includes(originalValidation.validation);
      if (originalValidation.validation === "retained-official-fields-verified") {
        const p = originalValidation.provenance;
        exactKeys(p, ["kind", "artifact_sha256", "export_identity", "source_url", "fields"], "retained provenance");
        requireValue(p.kind === "official-export-fields-v1" && p.artifact_sha256 === source.document_sha256
          && /^GrantsDBExtract[0-9]{8}v[0-9]+\.zip$/.test(p.export_identity) && p.source_url === source.source_url
          && ["www.grants.gov", "grants.gov"].includes(new URL(p.source_url).hostname)
          && originalValidation.retrieved_at === null && string(originalValidation.limitations, 2000)
          && canonical(p.fields) === canonical(source.excerpts.map(e => ({field: e.locator, sha256: e.sha256})))
          && p.fields.every(f => ["title", "description", "eligibility_text"].includes(f.field)), "Invalid retained official field provenance.");
      }
      if (originalValidation.validation === "retained-native-spans-verified") {
        const p = originalValidation.provenance;
        exactKeys(p, ["kind", "artifact_sha256", "source_url", "parent_id", "scope_id", "document_sha256", "locator"], "retained native provenance");
        requireValue(p.kind === "native-catalog-scope-v1" && HASH.test(p.artifact_sha256) && p.source_url === source.source_url
          && p.scope_id === scope.id && p.parent_id === scope.parent_id && p.document_sha256 === source.document_sha256
          && string(p.locator, 500) && originalValidation.retrieved_at === null && string(originalValidation.limitations, 2000), "Invalid retained native provenance.");
      }
      const nsfPage = originalValidation.validation === "retained-nsf-page-verified";
      if (nsfPage) {
        const p = originalValidation.provenance;
        exactKeys(p, ["kind", "artifact_sha256", "source_url", "parser_version", "original_text_sha256"], "retained NSF provenance");
        requireValue(p.kind === "official-nsf-page-v1" && p.artifact_sha256 === source.document_sha256
          && /^https:\/\/www\.nsf\.gov\/funding\/opportunities\/[a-z0-9-]+$/.test(p.source_url) && p.source_url === source.source_url
          && Number.isInteger(p.parser_version) && HASH.test(p.original_text_sha256) && string(originalValidation.limitations, 2000), "Invalid retained NSF page provenance.");
      }
      requireValue((retained || nsfPage || originalValidation?.validation === "original-source-spans-verified") && originalValidation.parent_id === scope.parent_id
        && originalValidation.document_sha256 === source.document_sha256 && HASH.test(originalValidation.text_sha256)
        && (retained ? originalValidation.observed_at : originalValidation.retrieved_at) === source.receipt.checked_at && originalValidation.new_retrieval === false
        && canonical(originalValidation.excerpt_hashes) === canonical(source.excerpts.map(e => e.sha256)), "Missing original-source validation record.");
      requireValue(Array.isArray(scope.aspects) && scope.aspects.length >= 1 && scope.aspects.length <= 8 && ID.test(scope.approach_id), "Unsupported scientific aspect count.");
      const aspectIds = new Set(), budgets = {}, grouped = {}, optional = {weight: 0};
      for (const item of [scope.core, scope.whole_call, ...scope.aspects]) {
        exactKeys(item, ["id", "text", "span", "vector", "operation", "context", "kind", "group_id", "weight", "requirement_kind"], "aspect");
        requireValue(ID.test(item?.id) && string(item.text, 4000), "Invalid aspect text."); span(item, source); await vectorRecord(item, "query");
      }
      for (const a of scope.aspects) {
        requireValue(!aspectIds.has(a.id) && ID.test(a.group_id) && ["central", "supporting", "optional"].includes(a.kind)
          && ["source_requirement", "planning_contribution"].includes(a.requirement_kind) && Number.isFinite(a.weight) && a.weight >= 0, "Invalid aspect weights or kind.");
        aspectIds.add(a.id); grouped[a.group_id] = (grouped[a.group_id] || 0) + a.weight; if (a.kind === "optional") optional.weight += a.weight;
      }
      requireValue(scope.aspects.some(a => a.kind === "central") && optional.weight <= .100001 && Math.abs(scope.aspects.reduce((s, a) => s + a.weight, 0) - 1) < 1e-9, "Invalid central/optional weight budget.");
      const central = scope.aspects.filter(a => a.kind === "central").reduce((sum, a) => sum + a.weight, 0);
      requireValue(Math.abs(central - (scope.aspects.some(a => a.kind === "supporting") ? .7 : 1 - optional.weight)) < 1e-9, "Central scientific weight budget changed.");
      const distinctText = new Map();
      for (const a of scope.aspects) {
        const text = a.text.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
        requireValue(!distinctText.has(text) || distinctText.get(text) === a.group_id, "Repeated aspect crosses source weight groups.");
        distinctText.set(text, a.group_id);
      }
      for (const g of scope.group_budgets || []) { requireValue(ID.test(g.id) && !Object.hasOwn(budgets, g.id) && Number.isFinite(g.weight) && g.weight >= 0, "Invalid source group budget."); budgets[g.id] = g.weight; }
      requireValue(Object.keys(grouped).length === Object.keys(budgets).length && Object.keys(grouped).every(k => Math.abs(grouped[k] - budgets[k]) < 1e-9), "Aspect splitting changes group weight.");
      // Only exact retained reviewed relations can create a proof label; scores never do.
      for (const link of scope.evidence_links || []) {
        exactKeys(link, ["aspect_id", "researcher_id", "claim_id", "revision", "status", "source_text", "claim_text", "receipt_id", "reviewed_relation"], "evidence relation");
        const aspect = scope.aspects.find(a => a.id === link.aspect_id), profile = directoryById.get(link.researcher_id);
        const claim = profile?.claims.find(c => c.claim_id === link.claim_id && c.revision === link.revision && c.status === "active");
        requireValue(aspect && claim && eligible(profile) && link.source_text === aspect.text && link.claim_text === claim.evidence && ID.test(link.receipt_id)
          && link.reviewed_relation === "exact-source-claim-v1" && ["direct", "method_transfer"].includes(link.status), "Unproven evidence relation.");
        // The publisher must supply an independently retained relation receipt in the manifest.
        requireValue((manifest.reviewed_relations || []).some(r => canonical(r) === canonical({...link, scope_id: scope.id, document_sha256: source.document_sha256})), "Missing independently retained evidence receipt.");
      }
      scope.semantic_key = await sha256(canonical([fingerprint, scope.id, scope.approach_id, scope.core, scope.whole_call, scope.aspects, scope.group_budgets]));
    }
    requireValue(usedRows.size === bundle.vector_rows.length, "Unowned vectors in public bundle.");
    requireValue(Array.isArray(manifest.reviewed_relations) && manifest.reviewed_relations.every(r => bundle.scopes.some(s =>
      (s.evidence_links || []).some(l => canonical(r) === canonical({...l, scope_id: s.id, document_sha256: sources.get(s.id).document_sha256})))), "Unowned reviewed relation in public manifest.");
    const routes = index.scopes.filter(s => s.engine === "ingredients-v2");
    requireValue(canonical(routes.map(s => [s.id, s.parent_id, s.record_type, s.prepared]).sort((a, b) => N.cmp(a[0], b[0])))
      === canonical(bundle.scopes.map(s => [s.id, s.parent_id, s.record_type, s.prepared]).sort((a, b) => N.cmp(a[0], b[0]))), "Routing/ingredient scope mismatch.");
    const faculty = directory.researchers.map(p => ({...p, terms: p.claims.filter(c => c.status === "active").map(c => ({claim_id: c.claim_id, claim_revision: c.revision,
      label: c.label, evidence: c.evidence, source_urls: c.source_urls, evidence_tier: c.evidence_level}))}));
    requireValue(faculty.every(p => safeUrl(p.source_url) && p.terms.every(t => t.source_urls.every(safeUrl))), "Unsafe researcher source URL.");
    const publicData = freeze({schema_version: 2, generation_id: manifest.generation_id, faculty, scope_count: bundle.scopes.length});
    freeze(bundle); freeze(manifest);
    prepared.set(publicData, {bundle, vectors, sources, manifest});
    return publicData;
  }
  async function readAsset(descriptor, budget) {
    requireValue(descriptor && /^data\/team-recommender\/[a-zA-Z0-9_.-]+\.(json|f32)$/.test(descriptor.path) && HASH.test(descriptor.sha256)
      && Number.isInteger(descriptor.bytes) && descriptor.bytes > 0 && descriptor.bytes <= MAX_BYTES, "Invalid bounded asset reference.");
    budget.bytes += descriptor.bytes; requireValue(budget.bytes <= MAX_BYTES, "Ingredient transfer budget exceeded.");
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await global.fetch(descriptor.path + "?v=" + descriptor.sha256, {credentials: "omit", redirect: "error", signal: controller.signal});
      requireValue(response.ok && response.body?.getReader, "Ingredient asset unavailable.");
      const reader = response.body.getReader(), chunks = []; let length = 0;
      while (true) { const {done, value} = await reader.read(); if (done) break; length += value.byteLength;
        if (length > descriptor.bytes) { await reader.cancel(); throw new Error("Ingredient asset exceeds declared length."); } chunks.push(value); }
      const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      requireValue(length === descriptor.bytes && await sha256(bytes) === descriptor.sha256, "Ingredient asset integrity failure."); return bytes;
    } finally { clearTimeout(timer); }
  }
  async function loadData(index, directory) {
    const budget = {bytes: 0};
    const manifest = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(await readAsset(index.ingredients, budget)));
    const data = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(await readAsset(manifest.metadata, budget)));
    const vectors = await readAsset(manifest.vectors, budget);
    return hydrate(data, vectors.buffer, manifest, index, directory);
  }
  function create(data, legacy) {
    const privateData = prepared.get(data); requireValue(privateData, "Ingredients were not atomically validated.");
    const {bundle, vectors, sources} = privateData;
    const facultyById = new Map(data.faculty.map(p => [p.id, p]));
    data.faculty.forEach(p => (p.legacy_ids || []).forEach(id => facultyById.set(id, p)));
    const own = new Map(bundle.scopes.map(s => [s.id, s]));
    const opportunityById = new Map(legacy?.opportunityById || []); own.forEach((s, id) => opportunityById.set(id, s));
    const matrices = new N.LRU(8), options = new N.LRU(32), decisions = new Map();
    const statistics = {matrices: 0, optimizations: 0};
    function scopesFor(parent) { return [...opportunityById.values()].filter(s => s.parent_id === String(parent) && s.review_state !== "needs_revalidation" && (!own.has(s.id) || s.prepared)).sort((a, b) => N.cmp(a.id, b.id)); }
    function resolveScope(input = {}) {
      const parent = String(input.parentId || input.record?.opportunity_id || ""), scopes = scopesFor(parent);
      const scope = opportunityById.get(input.scopeId) || (scopes.length === 1 && scopes[0].record_type === "specific_parent" ? scopes[0] : null);
      if (scope && !own.has(scope.id)) {
        const result = legacy.resolveScope(input);
        return {...result, scopes: (result.scopes || []).filter(s => opportunityById.has(s.id))};
      }
      if (scope) decisions.delete(scope.id);
      const now = input.now instanceof Date ? input.now : new Date(input.now ?? Date.now());
      const status = current(input.record, now); if (!status.ok) return {...status, scopes};
      if (!scope || scope.parent_id !== parent) return {ok: false, reason: scopes.length ? "specific_scope_required" : "unsupported_scope", scopes};
      if (scope.record_type === "specific_parent" && input.isBroad) return {ok: false, reason: "broad_parent_rejected", scopes};
      let sourceRecord = input.record;
      if (scope.record_type === "publishable_child") {
        sourceRecord = input.childCatalog?.opportunities.find(c => String(c.subtopic_id || c.opportunity_id) === scope.id && String(c.parent_id) === parent);
        if (!sourceRecord || sourceRecord.publication_state !== "publishable" || sourceRecord.child_type !== "subject") return {ok: false, reason: "child_not_publication_eligible", scopes};
        const childStatus = current(sourceRecord, now); if (!childStatus.ok) return {...childStatus, scopes};
      }
      const ready = readiness(scope, sources.get(scope.id), sourceRecord, now);
      if (!ready.ok) return {...ready, scopes};
      decisions.set(scope.id, {...input, record: input.record, now, sourceRecord});
      return {ok: true, opportunity: scope, scopes, readiness: ready.readiness};
    }
    function checked(state) {
      const scope = own.get(state.opportunityId), context = decisions.get(state.opportunityId);
      requireValue(scope && context && state.generation === data.generation_id, "Stale or unresolved ingredient selection.");
      requireValue(resolveScope({...context, scopeId: scope.id}).ok, "Opportunity or prepared evidence is no longer current.");
      requireValue(Array.isArray(state.selectedIds) && state.selectedIds.length <= 4 && new Set(state.selectedIds).size === state.selectedIds.length, "Invalid team selection.");
      requireValue(Array.isArray(state.excludedIds) && state.excludedIds.length <= N.PARAMETERS.maxPeople && state.excludedIds.every(id => typeof id === "string" && facultyById.has(id)), "Invalid team exclusions.");
      return scope;
    }
    function matrixFor(scope) { let m = matrices.get(scope.id); if (!m) { m = N.matrix(scope, bundle.people, vectors, rowCache); matrices.set(scope.id, m); statistics.matrices++; } return m; }
    function optimal(scope, exclusions) { const key = JSON.stringify([scope.id, exclusions.slice().sort(N.cmp)]); let result = options.get(key);
      if (!result) { result = N.optimize(matrixFor(scope), exclusions); options.set(key, result); statistics.optimizations++; } return result; }
    function stateFor(scope, ids, excluded = []) { return freeze({opportunityId: scope.id, generation: data.generation_id, selectedIds: ids.slice(), excludedIds: excluded.slice()}); }
    function proposal(scope) {
      if (!own.has(scope.id)) return legacy.proposal(scope);
      const empty = stateFor(scope, []); checked(empty);
      return stateFor(scope, optimal(scope, []).defaultIds);
    }
    function proposalOptions(state) {
      if (!own.has(state.opportunityId)) return legacy.proposalOptions(state);
      const scope = checked(state);
      return optimal(scope, state.excludedIds).options.map(t => ({id: scope.id + ":" + t.key, state: stateFor(scope, t.ids, state.excludedIds),
        label: t.ids.map(id => facultyById.get(id).name).join(" + ")}));
    }
    function proposalView(state) {
      if (!own.has(state.opportunityId)) return legacy.proposalView(state);
      const scope = checked(state), m = matrixFor(scope), source = sources.get(scope.id), selected = new Set(state.selectedIds.map(id => facultyById.get(id)?.id));
      const rows = new Map(m.rows.map(r => [r.id, r]));
      requireValue([...selected].every(id => facultyById.has(id) && eligible(facultyById.get(id))), "Ineligible cached member.");
      const roles = m.aspects.map((a, i) => {
        const links = (scope.evidence_links || []).filter(l => l.aspect_id === a.id && selected.has(l.researcher_id) && rows.get(l.researcher_id)?.edges[i].admitted);
        const confirmed = [...new Set(links.map(l => l.researcher_id))];
        return {id: a.id, label: a.text, rationale: (a.requirement_kind === "planning_contribution" ? "Planning contribution grounded in the source: " : "Source requirement: ") + a.text,
          source_url: source.source_url, required: a.kind !== "optional", coverage: "adjacent", filled: confirmed.length > 0,
          directEvidence: links.some(l => l.status === "direct"), selected_candidate_ids: confirmed,
          selected_alternative_ids: [...selected].filter(id => !confirmed.includes(id) && rows.get(id)?.edges[i].admitted && rows.get(id).edges[i].score > 0)};
      });
      const unfilled = roles.filter(r => r.required && !r.filled), complete = unfilled.length === 0 && selected.size >= 2;
      const members = [...selected].map(id => {
        const profile = facultyById.get(id), row = rows.get(id);
        const ranked = row.edges.map((e, i) => ({e, i})).filter(x => x.e.admitted && x.e.score > 0).sort((a, b) => N.quantize(b.e.score) - N.quantize(a.e.score) || a.i - b.i);
        const best = ranked[0], passage = best?.e.passage;
        const evidence = passage ? {faculty_id: id, contribution: m.aspects[best.i].text, evidence_term: profile.terms.find(t => passage.claim_refs.some(r => r.claim_id === t.claim_id))?.label || "Public evidence",
          evidence_phrase: passage.text, source_url: passage.source_urls[0], why_person: "The public passage “" + passage.text + "” suggests a scientific conversation about “" + m.aspects[best.i].text + "”. Exact contribution and application remain to be established."} : null;
        return {profile, evidence, roles: roles.filter(r => r.selected_candidate_ids.includes(id) || r.selected_alternative_ids.includes(id)), relevantTerms: []};
      });
      const baseScore = N.coverage(m, [...selected]);
      const replacements = m.admitted.filter(r => !selected.has(r.id)).map(row => ({profile: facultyById.get(row.id),
        roles: roles.filter((_, i) => row.edges[i].admitted && row.edges[i].score > 0),
        reviewed: false, previouslySelected: state.excludedIds.includes(row.id), marginal: N.coverage(m, [...selected, row.id]) - baseScore}))
        .sort((a, b) => N.quantize(b.marginal) - N.quantize(a.marginal) || N.cmp(a.profile.id, b.profile.id));
      const viable = selected.size >= 2 && baseScore >= N.PARAMETERS.group && [...selected].some(id => rows.get(id).edges.some(e => e.admitted && e.core >= N.PARAMETERS.anchor));
      const opportunity = {id: scope.id, parent_id: scope.parent_id, record_type: scope.record_type, scope_label: scope.scope_label, objective: scope.core.text,
        gate_state: complete ? "pass" : viable ? "conditional" : "fail", roles, members: members.map(m => ({faculty_id: m.profile.id, ...m.evidence})),
        why_team: members.map(m => m.evidence?.why_person || "No current scoped contribution is attributed.").join(" ") || "No adequate complementary group was found in the prepared directory.", missing_skills: unfilled.map(r => r.label)};
      return {opportunity, selected: members, selectedIds: [...selected], excludedIds: state.excludedIds.slice(), roles, unfilledRoles: unfilled, complete,
        replacements, prepared: true, matched_people_count: m.admitted.length, feasible_team_count: optimal(scope, state.excludedIds).feasibleCount};
    }
    function removeMember(state, id) { if (!own.has(state.opportunityId)) return legacy.removeMember(state, id); const scope = checked(state), canonicalId = facultyById.get(id)?.id || id;
      return stateFor(scope, state.selectedIds.filter(x => x !== canonicalId), [...new Set([...state.excludedIds, canonicalId])]); }
    function addReplacement(state, id) { if (!own.has(state.opportunityId)) return legacy.addReplacement(state, id); const scope = checked(state), view = proposalView(state), canonicalId = facultyById.get(id)?.id;
      requireValue(view.selectedIds.length < 4 && view.replacements.some(r => r.profile.id === canonicalId), "Replacement is not an admitted scoped match.");
      return stateFor(scope, [...view.selectedIds, canonicalId], state.excludedIds.filter(x => x !== canonicalId)); }
    return Object.freeze({data, facultyById, opportunityById, scopesFor, resolveScope, proposal, proposalView, proposalOptions, removeMember, addReplacement,
      statistics: () => ({...statistics, matricesCached: matrices.values.size, optionsCached: options.values.size, rowsCached: rowCache.values.size})});
  }
  global.TeamIngredients = Object.freeze({VERSION, canonical, recordKey, safeUrl, sha256, current, readiness, hydrate, loadData, create});
})(globalThis);
