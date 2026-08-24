(() => {
  "use strict";

  const CONTRACT_VERSION = 1;
  const EMBEDDING_MODEL = "voyage-4-lite";
  const RERANK_MODEL = "rerank-2.5";
  const EMBEDDING_DIMENSION = 1024;
  const BM25_DEPTH = 200;
  const SEMANTIC_DEPTH = 200;
  const RERANK_DEPTH = 300;
  const RRF_K = 60;
  const MAX_PASSAGE_CHARS = 3_000;
  const MAX_QUERY_CHARS = 500;
  const DEFAULT_TIMEOUT_MS = 8_000;

  class HybridSearchError extends Error {
    constructor(code, message, options = {}) {
      super(message);
      this.name = "HybridSearchError";
      this.code = code;
      this.retryAfter = Number(options.retryAfter || 0) || 0;
    }
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function uniqueText(values) {
    const seen = new Set();
    return (Array.isArray(values) ? values : [values]).flatMap(value => {
      const text = normalizeText(value);
      if (!text || seen.has(text)) return [];
      seen.add(text);
      return [text];
    });
  }

  function clipped(value, limit) {
    const text = normalizeText(value);
    if (text.length <= limit) return text;
    const cut = text.slice(0, limit);
    const boundary = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "), cut.lastIndexOf(" "));
    return `${cut.slice(0, Math.max(Math.floor(limit * .8), boundary))}…`;
  }

  function labeled(label, values, limit) {
    const text = clipped(uniqueText(values).join("; "), limit);
    return text ? `${label}: ${text}` : "";
  }

  function boundedPassage(parts) {
    return clipped(parts.filter(Boolean).join("\n"), MAX_PASSAGE_CHARS);
  }

  function authoritativeSourceEvidence(record) {
    return (record?.document_evidence?.facts || [])
      .filter(fact => fact?.type === "review_criteria")
      .flatMap(fact => [fact.value, fact.citation?.quote])
      .filter(Boolean);
  }

  function parentPassage(record) {
    const values = {
      parent_title: uniqueText([record.title]),
      authoritative_program_area: uniqueText(record.program_area_labels || record.document_program_areas || []),
      parent_description: uniqueText([record.description]),
      bounded_source_evidence: uniqueText(authoritativeSourceEvidence(record)),
    };
    return {
      fields: Object.entries(values).flatMap(([field, items]) => items.length ? [field] : []),
      values,
      text: boundedPassage([
        labeled("Parent title", values.parent_title, 500),
        labeled("Authoritative program area", values.authoritative_program_area, 600),
        labeled("Parent description", values.parent_description, 1_650),
        labeled("Public source evidence", values.bounded_source_evidence, 1_200),
      ]),
    };
  }

  function childPassage(record, parent) {
    const values = {
      parent_title: uniqueText([parent?.title]),
      child_title: uniqueText([record.title]),
      child_summary: uniqueText([record.description || record.summary]),
      authoritative_program_area: uniqueText(record.program_area_labels || []),
    };
    return {
      fields: Object.entries(values).flatMap(([field, items]) => items.length ? [field] : []),
      values,
      text: boundedPassage([
        labeled("Parent title", values.parent_title, 500),
        labeled("Publication-eligible child title", values.child_title, 700),
        labeled("Authoritative program area", values.authoritative_program_area, 600),
        labeled("Child summary", values.child_summary, 2_000),
      ]),
    };
  }

  function buildCorpus({ parentCatalog, childCatalog, currentnessRejectedIndexes = [] }) {
    const rejected = new Set(currentnessRejectedIndexes || []);
    const parentById = new Map();
    const passages = [];
    (parentCatalog?.opportunities || []).forEach((record, index) => {
      if (record.status === "archived" || rejected.has(index)) return;
      const passage = parentPassage(record);
      if (!passage.text) return;
      const parentId = String(record.opportunity_id);
      parentById.set(parentId, record);
      passages.push({
        parent_id: parentId,
        passage_id: `parent:${parentId}`,
        passage_kind: "parent",
        record_id: parentId,
        title: record.title || "",
        fields: passage.fields,
        values: passage.values,
        text: passage.text,
      });
    });
    (childCatalog?.opportunities || []).forEach(record => {
      const parentId = String(record.parent_id || "");
      const parent = parentById.get(parentId);
      if (!parent || record.status === "archived" || record.child_type !== "subject") return;
      if (record.publication_state && record.publication_state !== "publishable") return;
      const passage = childPassage(record, parent);
      if (!passage.text) return;
      const recordId = String(record.subtopic_id || record.opportunity_id);
      passages.push({
        parent_id: parentId,
        passage_id: `child:${recordId}`,
        passage_kind: "publication_eligible_child",
        record_id: recordId,
        title: record.title || "",
        fields: passage.fields,
        values: passage.values,
        text: passage.text,
      });
    });
    return passages.sort((left, right) => left.passage_id.localeCompare(right.passage_id));
  }

  function bytesOf(value) {
    if (typeof value === "string") return new TextEncoder().encode(value);
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    throw new TypeError("Expected text or binary data for SHA-256.");
  }

  async function sha256Hex(value) {
    const subtle = globalThis.crypto?.subtle;
    if (!subtle) throw new HybridSearchError("hash_unavailable", "SHA-256 is unavailable in this browser.");
    const digest = new Uint8Array(await subtle.digest("SHA-256", bytesOf(value)));
    return [...digest].map(byte => byte.toString(16).padStart(2, "0")).join("");
  }

  async function corpusHash(corpus) {
    return sha256Hex(corpus.map(item => `${item.passage_id}\0${item.parent_id}\0${item.text}\n`).join(""));
  }

  function halfToFloat(value) {
    const sign = (value & 0x8000) ? -1 : 1;
    const exponent = (value >>> 10) & 0x1f;
    const fraction = value & 0x03ff;
    if (exponent === 0) return sign * Math.pow(2, -14) * (fraction / 1024);
    if (exponent === 31) return fraction ? Number.NaN : sign * Number.POSITIVE_INFINITY;
    return sign * Math.pow(2, exponent - 15) * (1 + fraction / 1024);
  }

  function decodeFloat16(buffer, count, dimension) {
    const words = new Uint16Array(buffer);
    if (words.length !== count * dimension) {
      throw new HybridSearchError("vector_shape_mismatch", "The semantic vector asset has an unexpected size.");
    }
    const vectors = new Float32Array(words.length);
    for (let index = 0; index < words.length; index += 1) vectors[index] = halfToFloat(words[index]);
    return vectors;
  }

  function vectorNorm(vector, offset = 0, length = vector.length) {
    let sum = 0;
    for (let index = 0; index < length; index += 1) {
      const value = vector[offset + index];
      sum += value * value;
    }
    return Math.sqrt(sum) || 1;
  }

  function normalizedParentEligibility(parentIds) {
    if (parentIds == null) return null;
    return new Set((Array.isArray(parentIds) ? parentIds : [...parentIds])
      .map(value => String(value || "").trim())
      .filter(Boolean));
  }

  function semanticCandidates(
    corpus,
    vectors,
    queryVector,
    depth = SEMANTIC_DEPTH,
    eligibleParentIds = null,
  ) {
    if (queryVector.length !== EMBEDDING_DIMENSION) {
      throw new HybridSearchError("query_vector_shape", "The query embedding has an unexpected size.");
    }
    const queryNorm = vectorNorm(queryVector);
    const eligible = normalizedParentEligibility(eligibleParentIds);
    const scored = corpus.flatMap((passage, row) => {
      if (eligible && !eligible.has(String(passage.parent_id))) return [];
      const offset = row * EMBEDDING_DIMENSION;
      let dot = 0;
      let sum = 0;
      for (let column = 0; column < EMBEDDING_DIMENSION; column += 1) {
        const value = vectors[offset + column];
        dot += queryVector[column] * value;
        sum += value * value;
      }
      return [{ ...passage, semantic_score: dot / (queryNorm * (Math.sqrt(sum) || 1)) }];
    });
    return scored.sort((left, right) => (
      right.semantic_score - left.semantic_score
      || left.passage_id.localeCompare(right.passage_id)
    )).slice(0, depth);
  }

  function percentile(values, fraction) {
    const ordered = values.filter(Number.isFinite).sort((left, right) => left - right);
    return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
  }

  function scoreScale(values) {
    const positive = values.filter(value => value > 0);
    return Math.max(1e-9, percentile(positive, .9));
  }

  function buildBm25Candidates({
    parentCatalog,
    childCatalog,
    parentDirect,
    childDirect,
    corpusById,
    eligibleParentIds = null,
  }) {
    const parentScores = Array.from(parentDirect?.discoveryScores || []);
    const childScores = Array.from(childDirect?.discoveryScores || []);
    const parentScale = scoreScale(parentScores);
    const childScale = scoreScale(childScores);
    const rejected = new Set(parentDirect?.currentnessRejectedIndexes || []);
    const eligible = normalizedParentEligibility(eligibleParentIds);
    const candidates = [];
    (parentCatalog?.opportunities || []).forEach((record, index) => {
      if (eligible && !eligible.has(String(record.opportunity_id))) return;
      const score = Number(parentScores[index] || 0);
      const item = corpusById.get(`parent:${record.opportunity_id}`);
      if (!(score > 0) || rejected.has(index) || !item) return;
      candidates.push({ ...item, bm25f_raw_score: score, bm25f_score: score / parentScale });
    });
    (childCatalog?.opportunities || []).forEach((record, index) => {
      if (eligible && !eligible.has(String(record.parent_id))) return;
      const score = Number(childScores[index] || 0);
      const recordId = String(record.subtopic_id || record.opportunity_id);
      const item = corpusById.get(`child:${recordId}`);
      if (!(score > 0) || !item) return;
      candidates.push({ ...item, bm25f_raw_score: score, bm25f_score: score / childScale });
    });
    return candidates.sort((left, right) => (
      right.bm25f_score - left.bm25f_score
      || right.bm25f_raw_score - left.bm25f_raw_score
      || left.passage_id.localeCompare(right.passage_id)
    ));
  }

  function fuseCandidates(bm25, semantic) {
    const map = new Map();
    bm25.slice(0, BM25_DEPTH).forEach((item, index) => map.set(item.passage_id, {
      ...item,
      bm25f_rank: index + 1,
      semantic_rank: null,
      rrf_score: 1 / (RRF_K + index + 1),
    }));
    semantic.slice(0, SEMANTIC_DEPTH).forEach((item, index) => {
      const current = map.get(item.passage_id);
      const contribution = 1 / (RRF_K + index + 1);
      map.set(item.passage_id, current ? {
        ...current,
        semantic_score: item.semantic_score,
        semantic_rank: index + 1,
        rrf_score: current.rrf_score + contribution,
      } : {
        ...item,
        bm25f_rank: null,
        semantic_rank: index + 1,
        rrf_score: contribution,
      });
    });
    return [...map.values()].sort((left, right) => (
      right.rrf_score - left.rrf_score
      || Number(left.bm25f_rank || Number.MAX_SAFE_INTEGER) - Number(right.bm25f_rank || Number.MAX_SAFE_INTEGER)
      || Number(left.semantic_rank || Number.MAX_SAFE_INTEGER) - Number(right.semantic_rank || Number.MAX_SAFE_INTEGER)
      || left.passage_id.localeCompare(right.passage_id)
    ));
  }

  function shortUppercaseAcronyms(query) {
    return [...new Set(String(query || "").match(/(?:^|\s|[(/[{:])([A-Z][A-Z0-9]{1,5}s?)(?=$|\s|[)\]/},.:;!?-])/g)
      ?.map(value => value.replace(/^[^A-Z]*/, "").replace(/[^A-Za-z0-9].*$/, "")) || [])];
  }

  function identifierTokens(query) {
    return [...new Set(String(query || "").match(/\b(?=[A-Za-z0-9-]{4,}\b)(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b|\b\d{5,}\b/g) || [])];
  }

  function exactToken(text, token, caseSensitive = false) {
    const escaped = String(token).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(
      `(^|[^A-Za-z0-9])${escaped}([^A-Za-z0-9]|$)`,
      caseSensitive ? "" : "i",
    ).test(String(text || ""));
  }

  function resolvedAcronymMap(parentDirect, childDirect) {
    const expansions = [
      ...(parentDirect?.diagnostics?.acronymExpansions || []),
      ...(childDirect?.diagnostics?.acronymExpansions || []),
    ];
    const resolved = new Map();
    expansions.forEach(item => {
      if (Number(item.confidence || 0) < .95 || !item.phrase) return;
      resolved.set(String(item.source || "").toUpperCase(), normalizeText(item.phrase));
    });
    return resolved;
  }

  function resolvedAcronymSet(parentDirect, childDirect) {
    return new Set(resolvedAcronymMap(parentDirect, childDirect).keys());
  }

  function canonicalSemanticQuery(query, parentDirect, childDirect) {
    const resolved = resolvedAcronymMap(parentDirect, childDirect);
    let canonical = normalizeText(query);
    const acronymTokens = shortUppercaseAcronyms(query);
    acronymTokens.forEach(token => {
      const phrase = resolved.get(token.toUpperCase());
      if (!phrase) return;
      const escaped = String(token).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      canonical = canonical.replace(
        new RegExp(`(^|[^A-Za-z0-9])${escaped}(?=[^A-Za-z0-9]|$)`, "g"),
        (_match, prefix) => `${prefix}${phrase}`,
      );
    });
    const sourceWords = String(query || "").match(/[A-Za-z0-9]+/g) || [];
    if (sourceWords.length && sourceWords.every(word => resolved.has(word.toUpperCase()))) {
      canonical += ". Prioritize scientific research, engineering, and technology development; "
        + "do not rank policy workshops, training, diplomacy, or administrative programs as topical matches.";
    }
    return clipped(normalizeText(canonical), MAX_QUERY_CHARS);
  }

  function deterministicSafeguard(query, passage, resolvedAcronyms = new Set()) {
    const unresolved = shortUppercaseAcronyms(query).filter(token => !resolvedAcronyms.has(token.toUpperCase()));
    if (unresolved.some(token => !exactToken(passage.text, token, true))) {
      return { allowed: false, reason: "short_acronym_requires_exact_evidence" };
    }
    const unresolvedSet = new Set(unresolved);
    const remainingTerms = String(query || "").match(/[A-Za-z0-9]+/g)?.filter(token => (
      !unresolvedSet.has(token)
      && token.length >= 3
      && !/^(?:and|for|from|the|with)$/i.test(token)
    )) || [];
    if (unresolved.length && remainingTerms.some(token => !exactToken(passage.text, token))) {
      return { allowed: false, reason: "short_acronym_complete_intent_missing" };
    }
    const identifiers = identifierTokens(query);
    if (identifiers.some(token => !exactToken(passage.text, token)
      && passage.parent_id !== token && passage.record_id !== token)) {
      return { allowed: false, reason: "identifier_requires_exact_evidence" };
    }
    return {
      allowed: true,
      exact_identifier: identifiers.some(token => exactToken(passage.text, token)
        || passage.parent_id === token || passage.record_id === token),
    };
  }

  function strongestParents(passages, scoreKey = "voyage_score") {
    const parents = new Map();
    passages.forEach(passage => {
      const current = parents.get(passage.parent_id);
      const priority = passage.exact_identifier ? 1 : 0;
      const currentPriority = current?.exact_identifier ? 1 : 0;
      if (!current
        || priority > currentPriority
        || (priority === currentPriority && Number(passage[scoreKey]) > Number(current[scoreKey]))
        || (priority === currentPriority
          && Number(passage[scoreKey]) === Number(current[scoreKey])
          && passage.passage_id.localeCompare(current.passage_id) < 0)) {
        parents.set(passage.parent_id, passage);
      }
    });
    return [...parents.values()].sort((left, right) => (
      Number(Boolean(right.exact_identifier)) - Number(Boolean(left.exact_identifier))
      || Number(right[scoreKey]) - Number(left[scoreKey])
      || left.parent_id.localeCompare(right.parent_id)
    ));
  }

  function explanationFromPassage(passage) {
    if (!passage) return null;
    const preferences = passage.passage_kind === "publication_eligible_child"
      ? [
          ["child_summary", "Child summary"],
          ["child_title", "Child/subprogram title"],
          ["authoritative_program_area", "Program area"],
          ["parent_title", "Opportunity title"],
        ]
      : [
          ["parent_description", "Opportunity description"],
          ["authoritative_program_area", "Program area"],
          ["bounded_source_evidence", "Public source evidence"],
          ["parent_title", "Opportunity title"],
        ];
    const selected = preferences.find(([field]) => passage.values?.[field]?.length);
    if (!selected) return null;
    const [field, label] = selected;
    return {
      passage_id: passage.passage_id,
      passage_kind: passage.passage_kind,
      source_field: field,
      source_label: label,
      title: passage.title || "",
      excerpt: clipped(passage.values[field].join("; "), 360),
    };
  }

  function safeProxyUrl(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    try {
      const url = new URL(text, globalThis.location?.href || "http://localhost/");
      if (url.protocol !== "https:" && !(url.protocol === "http:" && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname))) return "";
      return url.href.endsWith("/") ? url.href : `${url.href}/`;
    } catch {
      return "";
    }
  }

  async function responseJson(response, code) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new HybridSearchError(code, "The enhanced-search service returned an unreadable response.");
    }
    if (!response.ok) throw new HybridSearchError(
      payload?.error?.code || code,
      "Enhanced search is temporarily unavailable.",
      { retryAfter: Number(response.headers?.get?.("Retry-After") || 0) },
    );
    return payload;
  }

  function createClient({
    parentCatalog,
    childCatalog,
    parentEngine,
    childEngine,
    manifestUrl = "./data/search-v2-voyage-manifest.json",
    vectorUrl = "./data/search-v2-voyage-vectors.f16",
    proxyUrl = "",
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchImpl = globalThis.fetch?.bind(globalThis),
  }) {
    const endpoint = safeProxyUrl(proxyUrl);
    let assetsPromise = null;
    const resultCache = new Map();
    const localResultCache = new Map();
    const usage = {
      embedding_requests: 0,
      rerank_requests: 0,
      embedding_tokens: 0,
      rerank_tokens: 0,
      fallbacks: 0,
      failures: 0,
      last_latency_ms: 0,
    };

    async function post(path, body) {
      if (!endpoint || !fetchImpl) throw new HybridSearchError("proxy_unconfigured", "Enhanced search is not configured.");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), Math.max(500, Number(timeoutMs) || DEFAULT_TIMEOUT_MS));
      try {
        const response = await fetchImpl(new URL(path, endpoint).href, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          credentials: "omit",
          cache: "no-store",
          referrerPolicy: "no-referrer",
          signal: controller.signal,
        });
        return await responseJson(response, "proxy_error");
      } catch (error) {
        if (error?.name === "AbortError") throw new HybridSearchError("proxy_timeout", "Enhanced search timed out.");
        if (error instanceof HybridSearchError) throw error;
        throw new HybridSearchError("proxy_unavailable", "Enhanced search is temporarily unavailable.");
      } finally {
        clearTimeout(timer);
      }
    }

    async function loadAssets() {
      if (assetsPromise) return assetsPromise;
      assetsPromise = (async () => {
        if (!fetchImpl) throw new HybridSearchError("asset_fetch_unavailable", "Semantic assets cannot be loaded.");
        const currentness = parentEngine.score("funding research", { evidence: false });
        const corpus = buildCorpus({
          parentCatalog,
          childCatalog,
          currentnessRejectedIndexes: currentness.currentnessRejectedIndexes,
        });
        const [manifestResponse, localCorpusHash] = await Promise.all([
          fetchImpl(manifestUrl, { cache: "no-cache", credentials: "same-origin" }),
          corpusHash(corpus),
        ]);
        if (!manifestResponse.ok) throw new HybridSearchError("manifest_missing", "The semantic manifest is unavailable.");
        const manifest = await manifestResponse.json();
        if (manifest.schema_version !== CONTRACT_VERSION
          || manifest.model !== EMBEDDING_MODEL
          || manifest.dimension !== EMBEDDING_DIMENSION
          || manifest.dtype !== "float16-le"
          || !/^[a-f0-9]{64}$/.test(String(manifest.model_space_fingerprint || ""))
          || manifest.model_space?.canary_set_version !== 1
          || !(manifest.model_space?.canary_count > 0)
          || manifest.passage_count !== corpus.length
          || manifest.corpus_sha256 !== localCorpusHash) {
          throw new HybridSearchError("manifest_corpus_mismatch", "The semantic manifest does not match the current catalog.");
        }
        if (!Array.isArray(manifest.passages) || manifest.passages.length !== corpus.length
          || manifest.passages.some((entry, index) => entry.passage_id !== corpus[index].passage_id)) {
          throw new HybridSearchError("manifest_passage_mismatch", "The semantic passage order does not match the current catalog.");
        }
        const versionedVectorUrl = `${vectorUrl}${String(vectorUrl).includes("?") ? "&" : "?"}v=${manifest.vector_sha256}`;
        const vectorResponse = await fetchImpl(versionedVectorUrl, { cache: "force-cache", credentials: "same-origin" });
        if (!vectorResponse.ok) throw new HybridSearchError("vector_asset_missing", "The semantic vectors are unavailable.");
        const vectorBuffer = await vectorResponse.arrayBuffer();
        if (await sha256Hex(vectorBuffer) !== manifest.vector_sha256) {
          throw new HybridSearchError("vector_hash_mismatch", "The semantic vectors failed their integrity check.");
        }
        corpus.forEach((passage, index) => {
          passage.text_sha256 = manifest.passages[index].text_sha256;
        });
        return {
          corpus,
          corpusById: new Map(corpus.map(item => [item.passage_id, item])),
          vectors: decodeFloat16(vectorBuffer, corpus.length, EMBEDDING_DIMENSION),
          manifest,
        };
      })().catch(error => {
        assetsPromise = null;
        throw error;
      });
      return assetsPromise;
    }

    async function search(query, { context = "", eligibleParentIds = null } = {}) {
      const normalizedQuery = normalizeText(query);
      if (!normalizedQuery || normalizedQuery.length > MAX_QUERY_CHARS) {
        throw new HybridSearchError("invalid_query", "The enhanced-search query is empty or too long.");
      }
      const started = performance.now();
      try {
        const assetsTask = loadAssets().then(
          value => ({ value, error: null }),
          error => ({ value: null, error }),
        );
        const parentDirect = parentEngine.score(normalizedQuery, { evidence: true, context });
        const childDirect = childEngine.score(normalizedQuery, { evidence: true, context });
        const semanticQuery = canonicalSemanticQuery(normalizedQuery, parentDirect, childDirect);
        const eligible = normalizedParentEligibility(eligibleParentIds);
        const localSignature = await sha256Hex(JSON.stringify({
          semantic_query: semanticQuery,
          eligible_parent_ids: eligible ? [...eligible].sort() : null,
        }));
        const locallyCached = localResultCache.get(localSignature);
        if (locallyCached) return {
          ...locallyCached,
          diagnostics: { ...locallyCached.diagnostics, cache_hit: true },
          usage: { ...usage },
        };
        const embeddedTask = post("embed-query", { query: semanticQuery }).then(response => {
          usage.embedding_requests += 1;
          usage.embedding_tokens += Number(response.usage?.total_tokens || 0);
          return { value: response, error: null };
        }, error => ({ value: null, error }));
        const [assetState, embeddedState] = await Promise.all([assetsTask, embeddedTask]);
        if (assetState.error) throw assetState.error;
        if (embeddedState.error) throw embeddedState.error;
        const assets = assetState.value;
        const embedded = embeddedState.value;
        const requestSignature = await sha256Hex(JSON.stringify({
          semantic_query: semanticQuery,
          corpus_sha256: assets.manifest.corpus_sha256,
          model_space_fingerprint: assets.manifest.model_space_fingerprint,
          eligible_parent_ids: eligible ? [...eligible].sort() : null,
        }));
        const cached = resultCache.get(requestSignature);
        if (cached) return {
          ...cached,
          diagnostics: { ...cached.diagnostics, cache_hit: true },
          usage: { ...usage },
        };
        const bm25 = buildBm25Candidates({
          parentCatalog,
          childCatalog,
          parentDirect,
          childDirect,
          corpusById: assets.corpusById,
          eligibleParentIds: eligible,
        });
        const semantic = semanticCandidates(
          assets.corpus,
          assets.vectors,
          Float32Array.from(embedded.embedding || []),
          SEMANTIC_DEPTH,
          eligible,
        );
        const resolved = resolvedAcronymSet(parentDirect, childDirect);
        const fused = fuseCandidates(bm25, semantic);
        let safeguardRejections = 0;
        const guarded = fused.flatMap(passage => {
          const safeguard = deterministicSafeguard(normalizedQuery, passage, resolved);
          if (!safeguard.allowed) {
            safeguardRejections += 1;
            return [];
          }
          return [{ ...passage, exact_identifier: safeguard.exact_identifier === true }];
        }).slice(0, RERANK_DEPTH);
        if (!guarded.length) {
          const emptyOutcome = {
            parents: [],
            diagnostics: {
              bm25_candidates: bm25.length,
              semantic_candidates: semantic.length,
              union_candidates: 0,
              safeguard_rejections: safeguardRejections,
              eligible_parent_count: eligible?.size ?? null,
              request_signature: requestSignature,
            },
            usage: { ...usage },
          };
          resultCache.set(requestSignature, emptyOutcome);
          localResultCache.set(localSignature, emptyOutcome);
          return emptyOutcome;
        }
        const reranked = await post("rerank", {
          query: semanticQuery,
          corpus_sha256: assets.manifest.corpus_sha256,
          model_space_fingerprint: assets.manifest.model_space_fingerprint,
          candidates: guarded.map(item => ({
            passage_id: item.passage_id,
            text_sha256: item.text_sha256,
            text: item.text,
          })),
        });
        usage.rerank_requests += 1;
        usage.rerank_tokens += Number(reranked.usage?.total_tokens || 0);
        const passages = (reranked.rankings || []).map(item => {
          const source = guarded[Number(item.index)];
          if (!source || item.passage_id !== source.passage_id) {
            throw new HybridSearchError("rerank_contract_mismatch", "The reranker returned an invalid passage reference.");
          }
          return { ...source, voyage_score: Number(item.relevance_score) };
        });
        const rankedParents = strongestParents(passages).map((passage, index) => ({
          ...passage,
          hybrid_rank: index + 1,
          explanation: explanationFromPassage(passage),
        }));
        usage.last_latency_ms = performance.now() - started;
        const outcome = {
          parents: rankedParents,
          diagnostics: {
            bm25_candidates: Math.min(BM25_DEPTH, bm25.length),
            semantic_candidates: semantic.length,
            union_candidates: guarded.length,
            safeguard_rejections: safeguardRejections,
            parent_count: rankedParents.length,
            candidate_top_50: rankedParents.slice(0, 50).map(item => item.parent_id),
            corpus_sha256: assets.manifest.corpus_sha256,
            vector_sha256: assets.manifest.vector_sha256,
            latency_ms: usage.last_latency_ms,
            eligible_parent_count: eligible?.size ?? null,
            request_signature: requestSignature,
          },
          usage: { ...usage },
        };
        resultCache.set(requestSignature, outcome);
        localResultCache.set(localSignature, outcome);
        return outcome;
      } catch (error) {
        usage.failures += 1;
        usage.fallbacks += 1;
        if (error instanceof HybridSearchError) throw error;
        throw new HybridSearchError("hybrid_failure", "Enhanced search is temporarily unavailable.");
      }
    }

    return Object.freeze({
      search,
      loadAssets,
      usage: () => ({ ...usage }),
      configured: Boolean(endpoint),
    });
  }

  globalThis.FUNDING_HYBRID_SEARCH = Object.freeze({
    CONTRACT_VERSION,
    EMBEDDING_MODEL,
    RERANK_MODEL,
    EMBEDDING_DIMENSION,
    BM25_DEPTH,
    SEMANTIC_DEPTH,
    RERANK_DEPTH,
    RRF_K,
    MAX_PASSAGE_CHARS,
    MAX_QUERY_CHARS,
    HybridSearchError,
    normalizeText,
    parentPassage,
    childPassage,
    buildCorpus,
    corpusHash,
    sha256Hex,
    decodeFloat16,
    semanticCandidates,
    buildBm25Candidates,
    fuseCandidates,
    canonicalSemanticQuery,
    deterministicSafeguard,
    strongestParents,
    explanationFromPassage,
    createClient,
  });
})();
