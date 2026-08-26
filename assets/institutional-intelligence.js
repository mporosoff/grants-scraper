(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const core = globalThis.FUNDING_INSTITUTIONAL_INTELLIGENCE;
  const awardProduct = globalThis.FUNDING_AWARD_PRODUCT;
  const apiConfig = globalThis.FUNDING_AWARD_API_CONFIG;
  const credentials = globalThis.FUNDING_CREDENTIALS;
  const ai = globalThis.FUNDING_AI;
  if (!core || !awardProduct || !apiConfig || !credentials || !$(`institutional-intelligence`)) return;

  const state = {
    selectedInstitution: null,
    registryCandidates: [],
    registrySequence: 0,
    registryController: null,
    registryTimer: null,
    registryAvailable: true,
    activeOption: -1,
    searchSequence: 0,
    searchController: null,
    payload: null,
    sourcePages: new Map(),
    loadingSource: "",
    aggregate: null,
    investigatorGroups: new Map(),
    selectedInvestigator: null,
    question: null,
    answering: false,
  };
  const SOURCE_LIMITS = Object.freeze({ NSF: 25, NIH: 25, DOE: 10 });

  function clean(value, maximum = 500) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
  }

  function safeUrl(value) {
    try {
      const url = new URL(clean(value, 2_000));
      return url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function evidenceDomId(value) {
    const id = typeof value === "string" ? value : core.evidenceId(value);
    return `ii-evidence-${clean(id, 140).replace(/[^A-Za-z0-9_-]+/g, "-")}`;
  }

  function investigatorIdentityFromName(name) {
    const normalized = core.normalizedInvestigatorName(name);
    if (!normalized) return null;
    return {
      identity_key: `shared-investigator:${normalized.base_key}:${normalized.middle_initial || "none"}`,
      name: clean(name, 160),
      normalized: {
        first: normalized.first,
        middle: normalized.middle,
        middle_initial: normalized.middle_initial,
        family: normalized.family,
      },
      projects: 0,
      variants: [{ name: clean(name, 160), source: "Shared URL", award_id: "" }],
      source_variants: {},
      members: [],
    };
  }

  function setStatus(message, error = false) {
    $("ii-status").textContent = message;
    $("ii-status").classList.toggle("error-text", error);
  }

  function setBusy(busy) {
    $("ii-search").disabled = busy;
    $("ii-ask-button").disabled = busy;
    if ($("ii-update-answer")) $("ii-update-answer").disabled = busy;
    $("ii-output").setAttribute("aria-busy", busy ? "true" : "false");
    syncPaginationControls(busy);
  }

  function selectedLocation(institution) {
    return [institution?.location?.city, institution?.location?.country].filter(Boolean).join(", ");
  }

  function setSelectedInstitution(institution, { announce = true } = {}) {
    state.selectedInstitution = institution ? {
      id: clean(institution.id, 100),
      canonical_name: clean(institution.canonical_name, 300),
      aliases: [...(institution.aliases || [])].map(value => clean(value, 300)).filter(Boolean).slice(0, 25),
      acronyms: [...(institution.acronyms || [])].map(value => clean(value, 80)).filter(Boolean).slice(0, 25),
      registryMetadataLoaded: true,
      location: institution.location || {},
      match: institution.match || {},
    } : null;
    if (!state.selectedInstitution) return;
    $("ii-institution").value = state.selectedInstitution.canonical_name;
    hideRegistryOptions();
    if (announce) {
      const location = selectedLocation(state.selectedInstitution);
      $("ii-registry-status").textContent = `Resolved to ${state.selectedInstitution.canonical_name}${location ? ` · ${location}` : ""} via the Research Organization Registry (ROR).`;
    }
  }

  function hideRegistryOptions() {
    $("ii-institution-options").classList.add("hidden");
    $("ii-institution").setAttribute("aria-expanded", "false");
    $("ii-institution").removeAttribute("aria-activedescendant");
    state.activeOption = -1;
  }

  function updateActiveOption(index) {
    const buttons = [...$("ii-institution-options").querySelectorAll("[role='option']")];
    if (!buttons.length) return;
    state.activeOption = Math.max(0, Math.min(buttons.length - 1, index));
    buttons.forEach((button, buttonIndex) => button.setAttribute("aria-selected", buttonIndex === state.activeOption ? "true" : "false"));
    const active = buttons[state.activeOption];
    $("ii-institution").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }

  function renderRegistryOptions(candidates) {
    state.registryCandidates = Array.isArray(candidates) ? candidates : [];
    const list = $("ii-institution-options");
    if (!state.registryCandidates.length) {
      hideRegistryOptions();
      return;
    }
    list.innerHTML = state.registryCandidates.map((institution, index) => {
      const aliases = [...(institution.acronyms || []), ...(institution.aliases || [])].slice(0, 3).join(", ");
      const location = selectedLocation(institution) || "Location not listed";
      return `<button id="ii-institution-option-${index}" type="button" role="option" aria-selected="false" data-ii-institution-index="${index}">
        <strong>${escapeHtml(institution.canonical_name)}</strong>
        <small>${escapeHtml(location)}${aliases ? ` · ${escapeHtml(aliases)}` : ""}</small>
      </button>`;
    }).join("");
    list.classList.remove("hidden");
    $("ii-institution").setAttribute("aria-expanded", "true");
  }

  async function fetchRegistry(query) {
    const normalized = clean(query, 120);
    if (normalized.length < 2) return [];
    const sequence = ++state.registrySequence;
    state.registryController?.abort();
    state.registryController = new AbortController();
    const url = new URL(apiConfig.institutionSearchUrl);
    url.searchParams.set("query", normalized);
    $("ii-registry-status").textContent = "Searching the open Research Organization Registry (ROR)…";
    try {
      const response = await fetch(url.href, {
        headers: { Accept: "application/json" },
        credentials: "omit",
        signal: state.registryController.signal,
      });
      const payload = await response.json().catch(() => null);
      if (sequence !== state.registrySequence) return [];
      if (!response.ok || payload?.schema_version !== 1 || !Array.isArray(payload?.institutions)) {
        throw new Error("registry_unavailable");
      }
      state.registryAvailable = true;
      renderRegistryOptions(payload.institutions);
      $("ii-registry-status").textContent = payload.institutions.length
        ? `${payload.institutions.length} Research Organization Registry (ROR) matches. Choose the intended institution; exact acronym matches are ranked for this U.S.-agency award corpus.`
        : "No Research Organization Registry (ROR) institution matched that text. You may still submit a complete source-listed institution name.";
      return payload.institutions;
    } catch (error) {
      if (error?.name === "AbortError" || sequence !== state.registrySequence) return [];
      state.registryAvailable = false;
      state.registryCandidates = [];
      hideRegistryOptions();
      $("ii-registry-status").textContent = "Research Organization Registry (ROR) autocomplete is temporarily unavailable. A complete institution name can still be sent to the official award sources.";
      return [];
    }
  }

  async function resolveTypedInstitution() {
    clearTimeout(state.registryTimer);
    const typed = clean($("ii-institution").value, 300);
    if (!typed) {
      state.selectedInstitution = null;
      hideRegistryOptions();
      $("ii-registry-status").textContent = "No institution selected. The search will use the other public award filters.";
      return null;
    }
    if (state.selectedInstitution && core.identityKey(state.selectedInstitution.canonical_name) === core.identityKey(typed)) {
      if (state.selectedInstitution.id && !state.selectedInstitution.registryMetadataLoaded) {
        const candidates = await fetchRegistry(typed);
        const restored = candidates.find(candidate => clean(candidate.id, 100) === state.selectedInstitution.id);
        if (restored) setSelectedInstitution(restored);
      }
      return state.selectedInstitution;
    }
    const candidates = await fetchRegistry(typed);
    const selected = core.chooseInstitution(typed, candidates);
    if (selected) {
      setSelectedInstitution(selected);
      return state.selectedInstitution;
    }
    if (state.registryAvailable && candidates.length) {
      const exact = candidates.filter(candidate => candidate?.match?.exact === true);
      throw new Error(exact.length > 1 || exact.some(candidate => candidate?.match?.type === "acronym")
        ? "That acronym or alias can identify more than one institution. Choose the intended Research Organization Registry (ROR) suggestion explicitly."
        : "Choose the intended Research Organization Registry (ROR) suggestion or type the institution’s complete canonical name.");
    }
    if (core.requiresExplicitInstitutionSelection(typed)) {
      throw new Error("A short institution name or acronym requires an explicit Research Organization Registry (ROR) selection. Retry when the registry is available or enter the complete source-listed institution name.");
    }
    state.selectedInstitution = { id: "", canonical_name: typed, location: {}, match: { type: "source_text" } };
    $("ii-registry-status").textContent = "Using the complete typed name as an exact source search because no deterministic Research Organization Registry (ROR) match was available.";
    return state.selectedInstitution;
  }

  function formState() {
    return {
      open: true,
      institution: clean(state.selectedInstitution?.canonical_name || $("ii-institution").value, 300),
      ror_id: clean(state.selectedInstitution?.id, 100),
      agency: $("ii-agency").value,
      program: clean($("ii-program").value, 160),
      topic: clean($("ii-topic").value, 500),
      pi: clean($("ii-pi").value, 160),
      pi_identity: Boolean(state.selectedInvestigator),
      program_officer: clean($("ii-program-officer").value, 160),
      year_start: $("ii-year-start").value,
      year_end: $("ii-year-end").value,
      offset: Number(state.payload?.pagination?.offset || 0),
    };
  }

  function applyFormState(value) {
    $("ii-institution").value = value.institution || "";
    $("ii-agency").value = value.agency || "all";
    $("ii-program").value = value.program || "";
    $("ii-topic").value = value.topic || "";
    $("ii-pi").value = value.pi || "";
    $("ii-program-officer").value = value.program_officer || "";
    $("ii-year-start").value = value.year_start || "";
    $("ii-year-end").value = value.year_end || "";
    state.selectedInstitution = value.institution ? {
      id: value.ror_id || "",
      canonical_name: value.institution,
      aliases: [],
      acronyms: [],
      registryMetadataLoaded: false,
      location: {},
      match: { type: value.ror_id ? "shared_ror" : "shared_source_text" },
    } : null;
    state.selectedInvestigator = value.pi_identity && value.pi
      ? investigatorIdentityFromName(value.pi)
      : null;
    if (value.institution) {
      $("ii-registry-status").textContent = value.ror_id
        ? `Restored ${value.institution} with its shared Research Organization Registry (ROR) identity.`
        : `Restored ${value.institution} as the shared canonical award-source name.`;
    } else {
      $("ii-registry-status").textContent = "Optional: type at least two characters to search the Research Organization Registry (ROR), or search the other fields without an institution.";
    }
  }

  function hasSearchState(value) {
    return Boolean(value?.institution || value?.program || value?.topic || value?.pi || value?.program_officer);
  }

  function syncUrl(value, mode = "replace") {
    if (!location.protocol.startsWith("http")) return;
    if (hasSearchState(value) && new URLSearchParams(location.search).has("opportunity")) {
      $("selected-opportunity")?.classList.add("hidden");
      $("award-results")?.classList.add("hidden");
    }
    const url = core.urlForState(location.href, value);
    history[mode === "push" ? "pushState" : "replaceState"](null, "", url);
  }

  function formatMoney(value) {
    const number = awardProduct.presentFiniteNumber(value);
    return number !== null
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(number)
      : "Amount not listed";
  }

  function renderAbstract(value) {
    const paragraphs = String(value || "")
      .replace(/\r\n?/g, "\n")
      .trim()
      .split(/\n\s*\n+/)
      .map(paragraph => paragraph.replace(/\s+/g, " ").trim())
      .filter(Boolean);
    return (paragraphs.length ? paragraphs : ["Abstract not listed by the source."])
      .map(paragraph => `<p>${escapeHtml(paragraph)}</p>`)
      .join("");
  }

  function contactLine(person, source, officialUrl) {
    const name = clean(person?.name, 300) || "Name not listed";
    const role = clean(person?.role, 160) || "Contact";
    const email = clean(person?.email, 320);
    const contactUrl = safeUrl(person?.official_contact_url || officialUrl);
    const identity = `<strong>${escapeHtml(name)}</strong> · ${escapeHtml(role)}`;
    if (email) {
      return `<li>${identity} · <a href="mailto:${escapeAttribute(email)}">${escapeHtml(email)}</a><span class="ii-contact-provenance">Direct ${escapeHtml(source)} source field</span></li>`;
    }
    return contactUrl
      ? `<li>${identity} · <a href="${escapeAttribute(contactUrl)}" target="_blank" rel="noopener">View on official record ↗</a><span class="ii-contact-provenance">Official ${escapeHtml(source)} record</span></li>`
      : `<li>${identity} · Email not listed</li>`;
  }

  function awardCard(award) {
    const source = clean(award?.source, 10) || "Source";
    const title = clean(award?.title, 1_000) || "Untitled funded project";
    const officialUrl = safeUrl(award?.official_award_url);
    const investigatorRecords = Array.isArray(award?.principal_investigators) ? award.principal_investigators : [];
    const programContacts = Array.isArray(award?.program_contacts) ? award.program_contacts : [];
    const investigators = investigatorRecords
      .map(person => clean(person?.name, 300))
      .filter(Boolean);
    const programs = [clean(award?.program_name, 300), ...(award?.program_codes || []).map(value => clean(value, 100))]
      .filter(Boolean);
    const year = awardProduct.awardYear(award?.award_year) ?? "Year not listed";
    const contacts = [...investigatorRecords, ...programContacts]
      .map(person => contactLine(person, source, officialUrl))
      .join("");
    return `<article class="ii-award-card" id="${escapeAttribute(evidenceDomId(award))}" data-source="${escapeAttribute(source)}">
      <div class="ii-award-kicker"><span class="ii-award-source">${escapeHtml(source)}</span><span>${escapeHtml(award?.award_id || "ID not listed")}</span><span>${escapeHtml(year)}</span><span>${escapeHtml(formatMoney(award?.total_award))}</span></div>
      <h3>${officialUrl ? `<a href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>` : escapeHtml(title)}</h3>
      <p class="ii-award-meta">${escapeHtml(award?.institution?.normalized_name || award?.institution?.name || "Institution not listed")}${investigators.length ? ` · ${escapeHtml(investigators.join(", "))}` : ""}</p>
      <p class="ii-award-program"><strong>Program:</strong> ${escapeHtml(programs.join(" · ") || award?.subagency || "Not listed")}</p>
      ${contacts ? `<section class="ii-award-contacts" aria-label="Public award contacts"><h4>Investigators and program contacts</h4><ul>${contacts}</ul></section>` : ""}
      <div class="ii-award-actions">${officialUrl ? `<a href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">Official ${escapeHtml(source)} record ↗</a>` : "Official link not listed"}</div>
      <details class="ii-award-abstract"><summary>Project abstract</summary>${renderAbstract(award?.abstract)}</details>
    </article>`;
  }

  function renderSourceStatus(sources) {
    const list = $("ii-source-status");
    const values = Array.isArray(sources) ? sources : [];
    list.innerHTML = values.map(source => {
      const status = source.status || "unavailable";
      const label = status === "ok"
        ? `${source.source} available · ${source.result_count || 0} loaded${source.safety_bound_reached === true ? " · upstream scan bound reached" : ""}`
        : source.retained_count
          ? `${awardProduct.sourceIssueText(source)} ${source.retained_count} previously loaded ${source.source} project${source.retained_count === 1 ? " was" : "s were"} retained.`
          : awardProduct.sourceIssueText(source);
      return `<li data-status="${escapeAttribute(status)}">${escapeHtml(label)}</li>`;
    }).join("");
    list.classList.toggle("hidden", !values.length);
  }

  function syncPaginationControls(busy = false) {
    for (const button of $("ii-load-more-actions").querySelectorAll("[data-ii-load-source]")) {
      const source = button.dataset.iiLoadSource;
      button.disabled = busy || state.loadingSource === source;
    }
  }

  function combinedPayload() {
    const pages = [...state.sourcePages.values()];
    return {
      schema_version: 1,
      request: { sources: pages.map(page => page.source) },
      results: pages.flatMap(page => page.results),
      sources: pages.map(page => {
        const status = page.error ? "unavailable" : page.meta?.status || "unavailable";
        return {
          ...(page.error || page.meta),
          source: page.source,
          status,
          result_count: page.results.length,
          retained_count: status === "ok" ? 0 : page.results.length,
          has_more: page.error ? false : page.hasMore,
        };
      }),
      pagination: { limit: 0, offset: 0 },
    };
  }

  function renderFacetSelect(select, items, { kind }) {
    const noun = kind === "investigator" ? "investigator" : "program";
    if (kind === "investigator") state.investigatorGroups = new Map(items.map(item => [item.identity_key, item]));
    select.innerHTML = items.length
      ? `<option value="">Choose a ${noun} (${items.length})</option>${items.map(item => {
        const value = kind === "investigator" ? item.identity_key : item.query;
        const attributes = kind === "program" ? ` data-ii-program-source="${escapeAttribute(item.source)}"` : "";
        const label = kind === "investigator"
          ? `${item.name} · ${item.projects} currently loaded award${item.projects === 1 ? "" : "s"}`
          : `${item.label} · ${item.projects} project${item.projects === 1 ? "" : "s"}`;
        const variantLabel = kind === "investigator"
          ? ` aria-label="${escapeAttribute(`${label}. Source-published variants: ${item.variants.map(variant => `${variant.name} from ${variant.source}`).join("; ")}`)}"`
          : "";
        return `<option value="${escapeAttribute(value)}"${attributes}${variantLabel}>${escapeHtml(label)}</option>`;
      }).join("")}`
      : `<option value="">No ${kind === "investigator" ? "investigators" : "programs"} loaded</option>`;
    select.disabled = items.length === 0;
  }

  function renderLoadMore(aggregate) {
    const pages = [...state.sourcePages.values()];
    const available = pages.filter(page => page.hasMore);
    const retryable = pages.filter(page => page.error);
    const bounded = pages.filter(page => page.meta?.safety_bound_reached === true).map(page => page.source);
    const actions = [...available, ...retryable.filter(page => !available.includes(page))];
    $("ii-pagination").classList.toggle("hidden", actions.length === 0);
    $("ii-page-label").textContent = actions.length
      ? `${aggregate.project_count.toLocaleString()} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded. Additional source pages are available from ${available.map(page => page.source).join(", ") || "the source that could not be reached"}.${bounded.length ? ` The upstream scan bound was reached for ${bounded.join(", ")}.` : ""}`
      : `${aggregate.project_count.toLocaleString()} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded in this view.${bounded.length ? ` The upstream scan bound was reached for ${bounded.join(", ")}.` : ""}`;
    $("ii-load-more-actions").innerHTML = actions.map(page => `<button class="button secondary" type="button" data-ii-load-source="${escapeAttribute(page.source)}">${page.error ? "Retry" : "Load more"} ${escapeHtml(page.source)}</button>`).join("");
    syncPaginationControls();
  }

  function answerEvidenceSignature(payload = state.payload) {
    const ids = (payload?.results || []).map(core.evidenceId).sort();
    const sourceState = (payload?.sources || []).map(source => [
      source.source,
      source.status,
      source.has_more === true,
      source.safety_bound_reached === true,
    ]);
    return JSON.stringify({ ids, sourceState });
  }

  function answerLimitations(snapshot) {
    const searched = snapshot.deterministic.searched.length ? snapshot.deterministic.searched.join(", ") : "none";
    const unavailable = snapshot.deterministic.unavailable;
    const more = snapshot.deterministic.has_more;
    const boundedSources = (snapshot.sources || []).filter(source => source?.safety_bound_reached === true).map(source => source.source);
    const parts = [
      `${snapshot.aggregate.project_count} normalized award${snapshot.aggregate.project_count === 1 ? "" : "s"} loaded; sources searched: ${searched}.`,
      unavailable.length ? `Unavailable or unsupported sources: ${unavailable.join(", ")}.` : "All requested sources returned a usable response.",
      more.length ? `Additional pages remain for ${more.join(", ")}; this is not a complete institutional history.` : "No requested source reported another normalized page within its product bound.",
      boundedSources.length ? `The upstream safety bound was reached for ${boundedSources.join(", ")}.` : "",
      snapshot.evidencePack.truncated
        ? `The answer evidence was bounded or truncated to ${snapshot.evidencePack.awards.length} public award records.`
        : `The answer evidence used all ${snapshot.evidencePack.awards.length} loaded public award records.`,
      snapshot.translationFallback ? "Question translation was unavailable, so the deterministic answer used the visible filters and a locally inferred answer intent." : "",
      snapshot.narrativeFailure ? "Narrative synthesis was unavailable or failed evidence validation, so the deterministic answer is shown." : "",
    ].filter(Boolean);
    return parts.join(" ");
  }

  function renderQuestionAnswer() {
    const container = $("ii-question-answer");
    const snapshot = state.question?.snapshot;
    if (!container || !snapshot) {
      container?.classList.add("hidden");
      return;
    }
    container.classList.remove("hidden");
    $("ii-answered-question").textContent = state.question.question;
    const narrative = snapshot.narrative?.claims || [];
    $("ii-direct-answer").innerHTML = [
      `<p>${escapeHtml(snapshot.deterministic.answer)}</p>`,
      narrative.length
        ? `<ul>${narrative.map(claim => `<li>${escapeHtml(claim.text)} ${claim.evidence_ids.map(id => `<a href="#${escapeAttribute(evidenceDomId(id))}" aria-label="Supporting award ${escapeAttribute(id)}">[${escapeHtml(id)}]</a>`).join(" ")}</li>`).join("")}</ul>`
        : "",
    ].join("");
    const knownEvidence = new Map(snapshot.evidencePack.awards.map(item => [item.evidence_id, item]));
    const cited = [...new Set([
      ...snapshot.deterministic.evidence_ids,
      ...narrative.flatMap(claim => claim.evidence_ids),
    ])].map(id => knownEvidence.get(id)).filter(Boolean);
    $("ii-answer-evidence").innerHTML = cited.length
      ? `<strong>Supporting award evidence:</strong><ul>${cited.map(item => `<li><a href="#${escapeAttribute(evidenceDomId(item.evidence_id))}">${escapeHtml(item.evidence_id)}</a> · ${escapeHtml(item.title || "Title not listed")}</li>`).join("")}</ul>`
      : "<strong>Supporting award evidence:</strong> No matching award record is loaded.";
    $("ii-answer-limitations").textContent = answerLimitations(snapshot);
    $("ii-update-answer").classList.toggle("hidden", snapshot.signature === answerEvidenceSignature());
  }

  function renderSelectedInvestigatorDetail(aggregate) {
    if (!state.selectedInvestigator) return;
    const selectedBase = core.normalizedInvestigatorName(state.selectedInvestigator.name)?.base_key;
    const selected = aggregate.investigators.find(item => item.identity_key === state.selectedInvestigator.identity_key)
      || aggregate.investigators.find(item => core.normalizedInvestigatorName(item.name)?.base_key === selectedBase);
    $("ii-investigator-variants").textContent = selected
      ? `${selected.name} represents ${selected.projects} currently loaded award${selected.projects === 1 ? "" : "s"}. Source-published variants: ${selected.variants.map(variant => `${variant.name} (${variant.source})`).join("; ")}.`
      : `No returned investigator identity safely matched ${state.selectedInvestigator.name}; unrelated common-name records were excluded.`;
  }

  async function refreshQuestionAnswer({ allowNarrative = true } = {}) {
    if (state.answering || !state.question || !state.payload || !state.aggregate) return;
    const questionState = state.question;
    const aggregate = state.aggregate;
    const payload = state.payload;
    const signature = answerEvidenceSignature(payload);
    state.answering = true;
    $("ii-update-answer").disabled = true;
    const evidencePack = core.questionEvidencePack(aggregate.awards);
    const deterministic = core.deterministicInstitutionAnswer({
      question: questionState.question,
      intent: questionState.intent,
      aggregate,
      sources: payload.sources,
    });
    let narrative = null;
    let narrativeFailure = false;
    if (allowNarrative && questionState.narrativeNeeded) {
      const provider = questionState.provider;
      const key = credentials.loadKey(provider);
      if (key) {
        try {
          const providerPayload = core.questionProviderPayload({
            question: questionState.question,
            institution: state.selectedInstitution,
            filters: questionState.filters,
            intent: questionState.intent,
            evidencePack,
          });
          const proposed = await ai.providerJson({
            provider,
            key,
            fetchImpl: globalThis.fetch,
            system: "Synthesize only the supplied public award titles and abstract excerpts when narrative interpretation is useful. Return JSON with claims, an array of at most six objects containing text and evidence_ids. Every claim must cite one or more exact supplied evidence IDs. Do not use model pretraining, add facts, infer identities or contacts, recommend collaborators, rank investigators, score fit, or return HTML. If the evidence cannot support a claim, omit it.",
            user: JSON.stringify(providerPayload),
          });
          narrative = core.validateNarrativeAnswer(proposed, evidencePack.awards);
          narrativeFailure = !narrative;
        } catch {
          narrativeFailure = true;
        }
      } else {
        narrativeFailure = true;
      }
    }
    if (state.question !== questionState) {
      state.answering = false;
      $("ii-update-answer").disabled = false;
      return;
    }
    state.question.snapshot = {
      aggregate,
      sources: payload.sources,
      deterministic,
      evidencePack,
      narrative,
      narrativeFailure,
      translationFallback: questionState.translationFallback === true,
      signature,
    };
    state.answering = false;
    $("ii-update-answer").disabled = false;
    renderQuestionAnswer();
  }

  function renderAggregate(payload) {
    const aggregate = core.aggregateAwards(payload.results);
    state.aggregate = aggregate;
    const submittedPage = state.sourcePages.values().next().value;
    const institution = submittedPage
      ? clean(submittedPage.request?.criteria?.institution, 300)
      : clean(state.selectedInstitution?.canonical_name || $("ii-institution").value, 300);
    $("ii-output").classList.remove("hidden");
    $("ii-output-heading").textContent = institution ? `${institution} funded projects` : "Funded award summary";
    const moreSources = (payload.sources || []).filter(source => source.status === "ok" && source.has_more === true).map(source => source.source);
    const boundedSources = (payload.sources || []).filter(source => source.status === "ok" && source.safety_bound_reached === true).map(source => source.source);
    $("ii-result-scope").textContent = `Summaries cover ${aggregate.project_count} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded across source-specific pages${moreSources.length ? `; load more from ${moreSources.join(", ")}` : ""}${boundedSources.length ? `; upstream scan bound reached for ${boundedSources.join(", ")}` : ""}.`;
    const years = aggregate.year_start
      ? aggregate.year_start === aggregate.year_end ? String(aggregate.year_start) : `${aggregate.year_start}–${aggregate.year_end}`
      : "Not listed";
    $("ii-metrics").innerHTML = [
      [aggregate.project_count, "Projects returned"],
      [aggregate.investigator_count, "Unique investigators"],
      [aggregate.program_count, "Program labels"],
      [years, "Award years"],
    ].map(([value, label]) => `<div class="ii-metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    renderFacetSelect($("ii-investigators"), aggregate.investigators, { kind: "investigator" });
    renderSelectedInvestigatorDetail(aggregate);
    renderFacetSelect($("ii-programs"), aggregate.programs, { kind: "program" });
    $("ii-awards").innerHTML = aggregate.awards.length
      ? aggregate.awards.map(awardCard).join("")
      : "<p>No normalized public award records matched these filters.</p>";
    renderSourceStatus(payload.sources);
    renderLoadMore(aggregate);
    renderQuestionAnswer();
    return aggregate;
  }

  async function fetchAwardPage(requestBody, controller) {
    const timer = setTimeout(() => controller.abort(), apiConfig.timeoutMs);
    let response;
    try {
      response = await fetch(apiConfig.searchUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "omit",
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    const payload = await response.json().catch(() => null);
    if (!payload || !awardProduct.validatePayload(payload)) {
      const error = new Error(awardProduct.serviceIssueText(payload) || "The award service returned an invalid response. Retry later.");
      error.code = awardProduct.boundedErrorCode(payload) || "invalid_response";
      throw error;
    }
    return payload;
  }

  function sourcePage(requestBody, payload) {
    const source = requestBody.sources[0];
    const meta = (payload.sources || []).find(item => item.source === source) || {
      source,
      status: "unavailable",
      error: { code: "source_unavailable" },
    };
    return {
      source,
      limit: requestBody.limit,
      request: requestBody,
      nextOffset: meta.status === "ok" ? requestBody.offset + requestBody.limit : requestBody.offset,
      results: payload.results.filter(result => result.source === source),
      meta,
      hasMore: meta.status === "ok" && meta.has_more === true && requestBody.offset + requestBody.limit <= 1_000,
      error: meta.status === "unavailable" ? meta : null,
    };
  }

  function failedSourcePage(requestBody, error) {
    return {
      source: requestBody.sources[0],
      limit: requestBody.limit,
      request: requestBody,
      nextOffset: requestBody.offset,
      results: [],
      meta: null,
      hasMore: false,
      error: {
        source: requestBody.sources[0],
        status: "unavailable",
        error: { code: error?.code || (error?.name === "AbortError" ? "source_unavailable" : "service_unavailable") },
      },
    };
  }

  function setLoadedStatus(payload, aggregate) {
    const failed = (payload.sources || []).filter(source => source.status !== "ok");
    const issueText = failed.map(awardProduct.sourceIssueText).join(" ");
    setStatus(failed.length
      ? aggregate.project_count
        ? `${aggregate.project_count} public project${aggregate.project_count === 1 ? "" : "s"} loaded from available sources. ${issueText}`
        : issueText
      : `${aggregate.project_count} public project${aggregate.project_count === 1 ? "" : "s"} loaded. Use the investigator or program menus to drill into the official records.`, failed.length > 0 && aggregate.project_count === 0);
  }

  async function runSearch({ historyMode = "replace", resolveInstitution = true, offset = null, focusResults = false, scrollResults = false, questionSearch = false } = {}) {
    let outcome = null;
    const sequence = ++state.searchSequence;
    state.searchController?.abort();
    state.loadingSource = "";
    state.searchController = new AbortController();
    setBusy(true);
    setStatus("Searching normalized public NSF, NIH, and DOE award records…");
    try {
      if (resolveInstitution) await resolveTypedInstitution();
      if (!questionSearch) {
        state.question = null;
        $("ii-question-answer").classList.add("hidden");
      }
      state.selectedInvestigator = null;
      const current = formState();
      if (offset !== null) current.offset = Math.max(0, Math.min(1_000, Number(offset) || 0));
      core.buildAwardRequest(current, SOURCE_LIMITS.DOE);
      const sources = core.sourcesForAgency(current.agency);
      const requestBodies = sources.map(source => core.buildAwardRequest(
        { ...current, agency: source },
        SOURCE_LIMITS[source],
      ));
      syncUrl(current, historyMode);
      const controller = state.searchController;
      const settled = await Promise.allSettled(requestBodies.map(requestBody => fetchAwardPage(requestBody, controller)));
      if (sequence !== state.searchSequence) return;
      if (settled.every(result => result.status === "rejected" && result.reason?.name === "AbortError")) {
        throw settled[0].reason;
      }
      state.sourcePages = new Map(requestBodies.map((requestBody, index) => {
        const result = settled[index];
        const page = result.status === "fulfilled"
          ? sourcePage(requestBody, result.value)
          : failedSourcePage(requestBody, result.reason);
        return [page.source, page];
      }));
      state.payload = combinedPayload();
      const aggregate = renderAggregate(state.payload);
      outcome = { payload: state.payload, aggregate };
      setLoadedStatus(state.payload, aggregate);
      if (focusResults) $("ii-output-heading").focus({ preventScroll: true });
      if (scrollResults) $("ii-output-heading").scrollIntoView({ block: "start" });
    } catch (error) {
      if (sequence !== state.searchSequence) return;
      if (error?.name === "AbortError") {
        setStatus("The award search timed out. Retry later.", true);
        return;
      }
      setStatus(error?.message || "Funded award search could not be completed. Retry later.", true);
    } finally {
      if (sequence === state.searchSequence) setBusy(false);
    }
    return outcome;
  }

  async function fetchInvestigatorSourcePage(current, source, group, offset, controller, requestTemplates = null) {
    const limit = SOURCE_LIMITS[source];
    const templates = Array.isArray(requestTemplates) ? requestTemplates : [];
    const variants = templates.length
      ? templates.map(template => clean(template?.criteria?.pi, 160)).filter(Boolean)
      : core.investigatorQueryVariants(group, source);
    const requests = templates.length
      ? templates.map(template => ({
        ...template,
        sources: [source],
        criteria: { ...template.criteria },
        limit,
        offset,
      }))
      : variants.map(variant => core.buildAwardRequest({
        ...current,
        agency: source,
        pi: variant,
        pi_identity: false,
        offset,
      }, limit));
    const settled = await Promise.allSettled(requests.map(request => fetchAwardPage(request, controller)));
    const fulfilled = settled.filter(result => result.status === "fulfilled").map(result => result.value);
    if (!fulfilled.length) throw settled.find(result => result.status === "rejected")?.reason || new Error("source_unavailable");
    const metas = fulfilled.map(payload => (payload.sources || []).find(item => item.source === source)).filter(Boolean);
    const available = fulfilled.filter(payload => (payload.sources || []).some(item => item.source === source && item.status === "ok"));
    if (!available.length) {
      const request = requests[0];
      const page = sourcePage(request, fulfilled[0]);
      page.investigatorIdentity = group;
      page.variantRequests = requests;
      return page;
    }
    const seen = new Set();
    const results = available.flatMap(payload => payload.results || []).filter(award => {
      const key = `${award.source}:${award.award_id}`;
      if (seen.has(key) || !core.awardMatchesInvestigator(award, group)) return false;
      seen.add(key);
      return true;
    });
    const successfulMetas = metas.filter(meta => meta.status === "ok");
    const failedVariantCount = settled.filter(result => result.status === "rejected").length
      + metas.filter(meta => meta.status !== "ok").length;
    const failedVariant = metas.find(meta => meta.status !== "ok")
      || settled.find(result => result.status === "rejected")?.reason;
    const partialError = failedVariantCount ? {
      source,
      status: "unavailable",
      error: { code: failedVariant?.error?.code || failedVariant?.code || (failedVariant?.name === "AbortError" ? "source_unavailable" : "service_unavailable") },
    } : null;
    const baseRequest = { ...requests[0], criteria: { ...requests[0].criteria, pi: group.name } };
    return {
      source,
      limit,
      request: baseRequest,
      nextOffset: partialError ? offset : offset + limit,
      results,
      meta: {
        source,
        status: "ok",
        result_count: results.length,
        has_more: successfulMetas.some(meta => meta.has_more === true),
        safety_bound_reached: successfulMetas.some(meta => meta.safety_bound_reached === true),
        raw_record_count: successfulMetas.reduce((sum, meta) => sum + (Number(meta.raw_record_count) || 0), 0),
        investigator_variant_queries: variants.length,
        ...(partialError ? { health: { status: "degraded", investigator_variant_failures: failedVariantCount } } : {}),
      },
      hasMore: !partialError && successfulMetas.some(meta => meta.has_more === true) && offset + limit <= 1_000,
      error: partialError,
      investigatorIdentity: group,
      variantRequests: requests,
    };
  }

  async function runInvestigatorSearch(group, { historyMode = "push", focusResults = true } = {}) {
    if (!group) return null;
    const sequence = ++state.searchSequence;
    state.searchController?.abort();
    state.searchController = new AbortController();
    state.loadingSource = "";
    state.question = null;
    $("ii-question-answer").classList.add("hidden");
    state.selectedInvestigator = group;
    $("ii-pi").value = group.name;
    const current = { ...formState(), pi: group.name, pi_identity: true, offset: 0 };
    const sources = core.sourcesForAgency(current.agency);
    syncUrl(current, historyMode);
    setBusy(true);
    setStatus(`Searching bounded source-published variants for ${group.name}…`);
    try {
      const controller = state.searchController;
      const settled = await Promise.allSettled(sources.map(source => (
        fetchInvestigatorSourcePage(current, source, group, 0, controller)
      )));
      if (sequence !== state.searchSequence) return null;
      state.sourcePages = new Map(sources.map((source, index) => {
        const result = settled[index];
        if (result.status === "fulfilled") return [source, result.value];
        const request = core.buildAwardRequest({ ...current, agency: source, pi: group.name, offset: 0 }, SOURCE_LIMITS[source]);
        const page = failedSourcePage(request, result.reason);
        page.investigatorIdentity = group;
        page.variantRequests = core.investigatorQueryVariants(group, source).map(variant => core.buildAwardRequest({
          ...current,
          agency: source,
          pi: variant,
          pi_identity: false,
          offset: 0,
        }, SOURCE_LIMITS[source]));
        return [source, page];
      }));
      state.payload = combinedPayload();
      const aggregate = renderAggregate(state.payload);
      setLoadedStatus(state.payload, aggregate);
      if (focusResults) $("ii-output-heading").focus({ preventScroll: true });
      return { payload: state.payload, aggregate };
    } catch (error) {
      if (sequence === state.searchSequence) setStatus(error?.message || "The investigator search could not be completed.", true);
      return null;
    } finally {
      if (sequence === state.searchSequence) setBusy(false);
    }
  }

  async function loadMoreSource(source) {
    const page = state.sourcePages.get(source);
    if (!page || (!page.hasMore && !page.error)) return;
    const sequence = ++state.searchSequence;
    state.searchController?.abort();
    state.searchController = new AbortController();
    state.loadingSource = source;
    setBusy(true);
    setStatus(`${page.error ? "Retrying" : "Loading more from"} ${source}…`);
    try {
      const requestBody = { ...page.request, sources: [source], offset: page.nextOffset };
      const next = page.investigatorIdentity
        ? await fetchInvestigatorSourcePage(null, source, page.investigatorIdentity, page.nextOffset, state.searchController, page.variantRequests)
        : sourcePage(requestBody, await fetchAwardPage(requestBody, state.searchController));
      if (sequence !== state.searchSequence) return;
      if (next.meta.status !== "ok") {
        page.meta = next.meta;
        page.error = next.meta.status === "unsupported" ? null : next.meta;
        page.hasMore = false;
      } else {
        const seen = new Set(page.results.map(award => `${award.source}:${award.award_id}`));
        const added = next.results.filter(award => {
          const key = `${award.source}:${award.award_id}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        page.results.push(...added);
        page.meta = next.meta;
        page.request = next.request;
        page.nextOffset = next.nextOffset;
        page.hasMore = !next.error && next.hasMore && next.nextOffset <= 1_000;
        page.error = next.error || null;
        state.sourcePages.set(source, page);
        state.payload = combinedPayload();
        const aggregate = renderAggregate(state.payload);
        setStatus(next.error
          ? `${source} retained ${page.results.length} safely matched project${page.results.length === 1 ? "" : "s"}, but ${next.meta.health?.investigator_variant_failures || 1} investigator spelling request${next.meta.health?.investigator_variant_failures === 1 ? "" : "s"} could not be completed. Retry ${source} to fill the same normalized page.`
          : `${added.length} additional ${source} project${added.length === 1 ? "" : "s"} loaded. ${aggregate.project_count} normalized project${aggregate.project_count === 1 ? " is" : "s are"} now shown.`, Boolean(next.error));
        return;
      }
      state.sourcePages.set(source, page);
      state.payload = combinedPayload();
      const aggregate = renderAggregate(state.payload);
      setLoadedStatus(state.payload, aggregate);
    } catch (error) {
      if (sequence !== state.searchSequence) return;
      if (error?.name === "AbortError") {
        setStatus(`Loading more ${source} projects timed out. Previously loaded projects remain visible.`, true);
      } else {
        page.error = {
          source,
          status: "unavailable",
          error: { code: error?.code || "service_unavailable" },
        };
        page.hasMore = false;
        state.sourcePages.set(source, page);
        state.payload = combinedPayload();
        renderAggregate(state.payload);
        setStatus(`${source} could not load another page. Previously loaded projects remain visible.`, true);
      }
    } finally {
      if (sequence === state.searchSequence) {
        state.loadingSource = "";
        setBusy(false);
      }
    }
  }

  function clearSearch({ historyMode = "push" } = {}) {
    state.searchSequence += 1;
    state.searchController?.abort();
    state.selectedInstitution = null;
    state.payload = null;
    state.aggregate = null;
    state.investigatorGroups.clear();
    state.selectedInvestigator = null;
    state.question = null;
    state.sourcePages.clear();
    state.loadingSource = "";
    applyFormState({ open: true, institution: "", agency: "all", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", offset: 0 });
    $("ii-output").classList.add("hidden");
    $("ii-source-status").classList.add("hidden");
    $("ii-question-plan").classList.add("hidden");
    $("ii-question-answer").classList.add("hidden");
    $("ii-pagination").classList.add("hidden");
    setStatus("Structured award search and institution resolution do not require an AI key.");
    syncUrl({ open: true }, historyMode);
  }

  function modelForProvider(provider) {
    return provider === "anthropic" ? ai?.ANTHROPIC_MODEL : ai?.OPENAI_MODEL;
  }

  function refreshProvider({ preferMain = true } = {}) {
    let provider = preferMain ? clean($("k-provider")?.value, 20) : clean($("ii-provider").value, 20);
    if (!new Set(["openai", "anthropic"]).has(provider)) provider = "openai";
    if (preferMain && !credentials.loadKey(provider)) {
      const alternative = provider === "openai" ? "anthropic" : "openai";
      if (credentials.loadKey(alternative)) provider = alternative;
    }
    $("ii-provider").value = provider;
    $("ii-model").textContent = modelForProvider(provider) || "Funding Finder default";
    $("ii-key").placeholder = provider === "anthropic" ? "sk-ant-..." : "sk-...";
    const configured = Boolean(credentials.loadKey(provider));
    $("ii-ai-state").textContent = configured
      ? `${provider === "anthropic" ? "Anthropic" : "OpenAI"} · ${modelForProvider(provider)} configured`
      : "Connect a provider to translate questions";
    $("ii-key-setup").classList.toggle("hidden", configured);
    $("ii-key-status").textContent = configured
      ? "Using the Funding Finder key already saved on this device."
      : `No ${provider === "anthropic" ? "Anthropic" : "OpenAI"} key is saved on this device.`;
    return { provider, configured };
  }

  function saveSharedKey() {
    const provider = $("ii-provider").value;
    const key = clean($("ii-key").value, 500);
    if (!key) {
      $("ii-key-status").textContent = "Enter a provider key first.";
      $("ii-key").focus();
      return;
    }
    const result = credentials.saveKey(provider, key);
    if (!result.saved) {
      $("ii-key-status").textContent = "This browser did not allow the shared key to be saved.";
      return;
    }
    if ($("k-provider")) $("k-provider").value = provider;
    if ($("k-key")) {
      $("k-key").value = key;
      $("k-key").dispatchEvent(new Event("input", { bubbles: true }));
    }
    $("ii-key").value = "";
    refreshProvider({ preferMain: false });
    $("ii-key-status").textContent = "Saved to Funding Finder’s shared browser-local provider configuration.";
  }

  function inferQuestionAgency(plan, question) {
    const agency = clean(plan?.agency, 10).toUpperCase();
    if (["NSF", "NIH", "DOE"].includes(agency)) return agency;
    const combined = `${clean(question)} ${clean(plan?.program)}`;
    if (/\b(DOE|BES|SC-\d+)/i.test(combined)) return "DOE";
    if (/\bNIH\b|\b[RKUPFT]\d{2}\b/i.test(combined)) return "NIH";
    if (/\bNSF\b/i.test(combined)) return "NSF";
    return "all";
  }

  function renderQuestionPlan(value, intent = "", note = "") {
    const labels = [
      value.institution ? `Institution: ${value.institution}` : "",
      `Agency: ${value.agency === "all" ? "NSF + NIH + DOE" : value.agency}`,
      value.program ? `Program: ${value.program}` : "",
      value.topic ? `Topic: ${value.topic}` : "",
      value.pi ? `Investigator: ${value.pi}` : "",
      value.program_officer ? `Program officer: ${value.program_officer}` : "",
      value.year_start || value.year_end ? `Years: ${value.year_start || "any"}–${value.year_end || "any"}` : "",
      intent ? `Answer intent: ${intent}` : "",
    ].filter(Boolean);
    $("ii-question-plan").innerHTML = `<strong>Transparent search plan:</strong> ${labels.map(escapeHtml).join(" · ")}. The public award records below remain authoritative.${note ? ` ${escapeHtml(note)}` : ""}`;
    $("ii-question-plan").classList.remove("hidden");
  }

  async function askQuestion() {
    const question = clean($("ii-question").value, 1_000);
    if (!question) {
      $("ii-question-plan").textContent = "Enter a question about the selected institution.";
      $("ii-question-plan").classList.remove("hidden");
      $("ii-question").focus();
      return;
    }
    try {
      const institution = await resolveTypedInstitution();
      if (!institution) throw new Error("Select an institution before asking a question about it.");
    } catch (error) {
      setStatus(error?.message || String(error), true);
      return;
    }
    const { provider, configured } = refreshProvider();
    const key = credentials.loadKey(provider);
    if (!configured || !key) {
      $("ii-key-setup").classList.remove("hidden");
      $("ii-key-status").textContent = "No key is configured, so the answer will use the visible filters and deterministic loaded-award evidence. Save a key to enable question translation and bounded narrative synthesis.";
    }
    $("ii-ask-button").disabled = true;
    state.question = null;
    $("ii-question-answer").classList.add("hidden");
    $("ii-question-plan").textContent = "Translating the question into bounded public-award filters…";
    $("ii-question-plan").classList.remove("hidden");
    try {
      const current = formState();
      let plan = { ...current };
      let translationFallback = !configured || !key;
      if (!translationFallback) {
        try {
          const translated = await ai.providerJson({
            provider,
            key,
            fetchImpl: globalThis.fetch,
            system: "Translate one question about public NSF, NIH, or DOE funded awards into structured filters and a bounded answer intent. Return only JSON with agency (all, NSF, NIH, or DOE), program, topic, pi, program_officer, year_start, year_end, answer_intent (count, investigators, programs, years, awards, or narrative), and narrative_needed (boolean). Use empty strings for absent filters. Put an explicitly named investigator in pi unless the question clearly identifies that person as a program officer. Do not answer the question, name awards, infer contacts, recommend collaborators, rank investigators, score funding fit, or invent facts. Request narrative only when returned titles or abstract excerpts require interpretation; counts, names, programs, years, and award lists are deterministic. DOE Basic Energy Sciences is agency DOE and program BES. NIH programs use activity codes when stated. Preserve explicit user constraints.",
            user: JSON.stringify({
              institution: current.institution,
              current_filters: {
                agency: current.agency,
                program: current.program,
                topic: current.topic,
                pi: current.pi,
                program_officer: current.program_officer,
                year_start: current.year_start,
                year_end: current.year_end,
              },
              question,
            }),
          });
          if (!translated || typeof translated !== "object" || Array.isArray(translated)) throw new Error("invalid_translation");
          plan = { ...translated };
        } catch {
          translationFallback = true;
          plan = { ...current };
        }
      }
      plan.agency = inferQuestionAgency(plan, question);
      const selectedInstitution = state.selectedInstitution;
      const institutionAliases = [
        ...(selectedInstitution?.aliases || []),
        ...(selectedInstitution?.acronyms || []),
      ];
      const explicitPi = core.explicitInvestigator(question, current.institution, plan.program, institutionAliases, plan.topic);
      if (explicitPi && !clean(plan.pi) && !clean(plan.program_officer)) plan.pi = explicitPi;
      const next = core.sanitizeQuestionPlan(plan, current);
      const intent = core.sanitizeAnswerIntent(plan, question);
      applyFormState(next);
      state.selectedInstitution = {
        ...selectedInstitution,
        id: current.ror_id,
        canonical_name: current.institution,
      };
      state.question = {
        question,
        filters: next,
        intent,
        narrativeNeeded: plan.narrative_needed === true || intent === "narrative",
        provider,
        translationFallback,
        snapshot: null,
      };
      renderQuestionPlan(next, intent, translationFallback
        ? "Provider translation was unavailable; the visible filters and deterministic answer intent were used."
        : "");
      const outcome = await runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true, questionSearch: true });
      if (outcome) await refreshQuestionAnswer({ allowNarrative: true });
    } catch (error) {
      $("ii-question-plan").textContent = `The evidence-grounded question could not be completed: ${error?.message || String(error)} Structured filters remain available without AI.`;
    } finally {
      $("ii-ask-button").disabled = false;
    }
  }

  function bindEvents() {
    $("ii-institution").addEventListener("input", () => {
      state.selectedInstitution = null;
      clearTimeout(state.registryTimer);
      const query = clean($("ii-institution").value, 120);
      if (query.length < 2) {
        hideRegistryOptions();
        $("ii-registry-status").textContent = query
          ? "Type at least two characters to search the Research Organization Registry (ROR)."
          : "Optional: type at least two characters to search the Research Organization Registry (ROR), or search the other fields without an institution.";
        return;
      }
      state.registryTimer = setTimeout(() => fetchRegistry(query), 300);
    });
    $("ii-institution").addEventListener("keydown", event => {
      if ($("ii-institution-options").classList.contains("hidden")) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        updateActiveOption(state.activeOption + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        updateActiveOption(state.activeOption < 0 ? state.registryCandidates.length - 1 : state.activeOption - 1);
      } else if (event.key === "Enter" && state.activeOption >= 0) {
        event.preventDefault();
        setSelectedInstitution(state.registryCandidates[state.activeOption]);
      } else if (event.key === "Escape") {
        hideRegistryOptions();
      }
    });
    $("ii-institution").addEventListener("blur", () => setTimeout(hideRegistryOptions, 120));
    $("ii-institution-options").addEventListener("mousedown", event => event.preventDefault());
    $("ii-institution-options").addEventListener("click", event => {
      const option = event.target.closest("[data-ii-institution-index]");
      if (!option) return;
      setSelectedInstitution(state.registryCandidates[Number(option.dataset.iiInstitutionIndex)]);
      $("ii-institution").focus();
    });
    $("ii-form").addEventListener("submit", event => {
      event.preventDefault();
      runSearch({ historyMode: "push", offset: 0, focusResults: true });
    });
    $("ii-clear").addEventListener("click", () => clearSearch());
    $("ii-investigators").addEventListener("change", event => {
      const group = state.investigatorGroups.get(event.currentTarget.value);
      if (!group) return;
      $("ii-investigator-variants").textContent = `${group.name} represents ${group.projects} currently loaded award${group.projects === 1 ? "" : "s"}. Source-published variants: ${group.variants.map(variant => `${variant.name} (${variant.source})`).join("; ")}.`;
      runInvestigatorSearch(group);
    });
    $("ii-programs").addEventListener("change", event => {
      const option = event.currentTarget.selectedOptions[0];
      const program = clean(option?.value, 160);
      if (!program) return;
      $("ii-agency").value = option.dataset.iiProgramSource;
      $("ii-program").value = program;
      runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true });
    });
    $("ii-load-more-actions").addEventListener("click", event => {
      const button = event.target.closest("[data-ii-load-source]");
      if (button) loadMoreSource(button.dataset.iiLoadSource);
    });
    $("ii-provider").addEventListener("change", () => refreshProvider({ preferMain: false }));
    $("ii-save-key").addEventListener("click", saveSharedKey);
    $("ii-ask-button").addEventListener("click", askQuestion);
    $("ii-update-answer").addEventListener("click", () => refreshQuestionAnswer({ allowNarrative: true }));
    $("k-provider")?.addEventListener("change", () => setTimeout(refreshProvider, 0));
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(location.search);
      const restored = core.stateFromSearch(location.search);
      applyFormState(restored);
      state.payload = null;
      state.aggregate = null;
      state.sourcePages.clear();
      state.loadingSource = "";
      if (hasSearchState(restored) && !params.get("opportunity")) {
        if (restored.pi_identity && state.selectedInvestigator) runInvestigatorSearch(state.selectedInvestigator, { historyMode: "replace", focusResults: false });
        else runSearch({ historyMode: "replace", resolveInstitution: false, offset: restored.offset });
      } else {
        $("ii-output").classList.add("hidden");
        $("ii-source-status").classList.add("hidden");
        $("ii-pagination").classList.add("hidden");
        setStatus("Structured award search and institution resolution do not require an AI key.");
      }
    });
  }

  function initialize() {
    const restored = core.stateFromSearch(location.search);
    applyFormState(restored);
    bindEvents();
    refreshProvider();
    if (hasSearchState(restored) && !new URLSearchParams(location.search).get("opportunity")) {
      if (restored.pi_identity && state.selectedInvestigator) runInvestigatorSearch(state.selectedInvestigator, { historyMode: "replace", focusResults: false });
      else runSearch({ historyMode: "replace", resolveInstitution: false, offset: restored.offset });
    }
  }

  initialize();
})();
