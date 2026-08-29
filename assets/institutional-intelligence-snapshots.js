(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const core = globalThis.FUNDING_INSTITUTIONAL_INTELLIGENCE;
  const awardProduct = globalThis.FUNDING_AWARD_PRODUCT;
  const api = globalThis.FUNDING_AWARD_API_CONFIG;
  const credentials = globalThis.FUNDING_CREDENTIALS;
  const ai = globalThis.FUNDING_AI;
  if (!core || !awardProduct || !api || !credentials || !$(`institutional-intelligence`)) return;

  const state = {
    selectedInstitution: null,
    registryCandidates: [],
    registrySequence: 0,
    registryController: null,
    registryTimer: null,
    registryAvailable: true,
    activeOption: -1,
    sequence: 0,
    pageRequestSequence: 0,
    busyDepth: 0,
    controller: null,
    submitted: null,
    snapshot: null,
    pagePayload: null,
    aggregate: null,
    baseAggregate: null,
    facet: { type: "all", key: "" },
    page: 1,
    pageSize: 10,
    residentAwards: new Map(),
    sourceOffsets: new Map(),
    sourceMessages: new Map(),
    investigatorGroups: new Map(),
    programGroups: new Map(),
    question: null,
    questionSubmitting: false,
    answering: false,
  };

  function clean(value, maximum = 500) {
    return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, maximum);
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

  function awardKey(award) {
    return `${clean(award?.source, 10).toUpperCase()}:${clean(award?.award_id, 120)}`;
  }

  function evidenceDomId(value) {
    const id = typeof value === "string" ? value : awardKey(value);
    return `ii-evidence-${clean(id, 140).replace(/[^A-Za-z0-9_-]+/g, "-")}`;
  }

  function setStatus(message, error = false) {
    $("ii-status").textContent = message;
    $("ii-status").classList.toggle("error-text", error);
  }

  function setBusy(busy) {
    state.busyDepth = Math.max(0, state.busyDepth + (busy ? 1 : -1));
    const active = state.busyDepth > 0;
    $("ii-search").disabled = active;
    $("ii-clear").disabled = active;
    $("ii-ask-button").disabled = active || state.questionSubmitting;
    $("ii-output").setAttribute("aria-busy", active ? "true" : "false");
    $("ii-card-previous").disabled = active || !state.pagePayload?.pagination?.has_previous;
    $("ii-card-next").disabled = active || !state.pagePayload?.pagination?.has_next;
    $("ii-card-page-numbers").querySelectorAll("button").forEach(button => { button.disabled = active; });
    $("ii-page-size").disabled = active || !state.pagePayload;
    $("ii-investigators").disabled = active || state.investigatorGroups.size === 0;
    $("ii-programs").disabled = active || state.programGroups.size === 0;
    $("ii-clear-facet").disabled = active || state.facet.type === "all";
    $("ii-load-more-actions").querySelectorAll("button").forEach(button => { button.disabled = active; });
  }

  function selectedLocation(institution) {
    return [institution?.location?.city, institution?.location?.country].filter(Boolean).join(", ");
  }

  function hideRegistryOptions() {
    $("ii-institution-options").classList.add("hidden");
    $("ii-institution").setAttribute("aria-expanded", "false");
    $("ii-institution").removeAttribute("aria-activedescendant");
    state.activeOption = -1;
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

  function updateActiveOption(index) {
    const options = [...$("ii-institution-options").querySelectorAll("[role='option']")];
    if (!options.length) return;
    state.activeOption = Math.max(0, Math.min(options.length - 1, index));
    options.forEach((option, optionIndex) => option.setAttribute("aria-selected", optionIndex === state.activeOption ? "true" : "false"));
    const active = options[state.activeOption];
    $("ii-institution").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }

  function renderRegistryOptions(candidates) {
    state.registryCandidates = Array.isArray(candidates) ? candidates : [];
    const list = $("ii-institution-options");
    if (!state.registryCandidates.length) return hideRegistryOptions();
    list.innerHTML = state.registryCandidates.map((institution, index) => {
      const aliases = [...(institution.acronyms || []), ...(institution.aliases || [])].slice(0, 3).join(", ");
      const location = selectedLocation(institution) || "Location not listed";
      return `<button id="ii-institution-option-${index}" type="button" role="option" aria-selected="false" data-ii-institution-index="${index}"><strong>${escapeHtml(institution.canonical_name)}</strong><small>${escapeHtml(location)}${aliases ? ` · ${escapeHtml(aliases)}` : ""}</small></button>`;
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
    const url = new URL(api.institutionSearchUrl);
    url.searchParams.set("query", normalized);
    $("ii-registry-status").textContent = "Searching the open Research Organization Registry (ROR)…";
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" }, credentials: "omit", signal: state.registryController.signal });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !Array.isArray(payload?.institutions)) throw new Error("registry_unavailable");
      if (sequence !== state.registrySequence) return [];
      state.registryAvailable = true;
      renderRegistryOptions(payload.institutions);
      $("ii-registry-status").textContent = payload.institutions.length
        ? "Choose the intended institution so aliases and acronyms cannot silently select the wrong organization."
        : "No deterministic ROR match was found. A complete source-listed institution name can still be searched.";
      return payload.institutions;
    } catch (error) {
      if (error?.name === "AbortError") return [];
      state.registryAvailable = false;
      hideRegistryOptions();
      $("ii-registry-status").textContent = "ROR lookup is temporarily unavailable. Enter a complete source-listed institution name; short names and acronyms remain blocked.";
      return [];
    }
  }

  async function resolveTypedInstitution() {
    const typed = clean($("ii-institution").value, 300);
    if (!typed) {
      state.selectedInstitution = null;
      return null;
    }
    if (state.selectedInstitution && core.identityKey(state.selectedInstitution.canonical_name) === core.identityKey(typed)) return state.selectedInstitution;
    const candidates = await fetchRegistry(typed);
    const chosen = core.chooseInstitution(typed, candidates);
    if (chosen) {
      setSelectedInstitution(chosen);
      return state.selectedInstitution;
    }
    if (state.registryAvailable && candidates.length) throw new Error("Choose the intended Research Organization Registry (ROR) suggestion or type the institution’s complete canonical name.");
    if (core.requiresExplicitInstitutionSelection(typed)) throw new Error("A short institution name or acronym requires an explicit Research Organization Registry (ROR) selection.");
    state.selectedInstitution = { id: "", canonical_name: typed, aliases: [], acronyms: [], location: {}, match: { type: "source_text" } };
    $("ii-registry-status").textContent = "Using the complete typed name as an exact source search because no deterministic ROR match was available.";
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
      program_officer: clean($("ii-program-officer").value, 160),
      year_start: $("ii-year-start").value,
      year_end: $("ii-year-end").value,
      snapshot_id: state.snapshot?.snapshot_id || "",
      page: state.page,
      page_size: state.pageSize,
      facet_type: state.facet.type,
      facet_key: state.facet.key,
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
    $("ii-page-size").value = String(value.page_size || 10);
    state.page = value.page || 1;
    state.pageSize = value.page_size || 10;
    state.facet = { type: value.facet_type || "all", key: value.facet_key || "" };
    state.selectedInstitution = value.institution ? {
      id: value.ror_id || "", canonical_name: value.institution, aliases: [], acronyms: [], registryMetadataLoaded: false,
      location: {}, match: { type: value.ror_id ? "shared_ror" : "shared_source_text" },
    } : null;
    if (value.institution) $("ii-registry-status").textContent = value.ror_id
      ? `Restored ${value.institution} with its shared Research Organization Registry (ROR) identity.`
      : `Restored ${value.institution} as the shared canonical award-source name.`;
  }

  function hasSearchState(value) {
    return Boolean(value?.institution || value?.program || value?.topic || value?.pi || value?.program_officer);
  }

  function syncUrl(mode = "replace") {
    if (!location.protocol.startsWith("http")) return;
    const value = { ...(state.submitted || formState()), ...formState() };
    const url = core.urlForState(location.href, value);
    const historyState = { scrollY: window.scrollY, focusId: document.activeElement?.id || "" };
    history[mode === "push" ? "pushState" : "replaceState"](historyState, "", url);
  }

  async function postJson(url, body, controller = state.controller) {
    const activeController = controller?.signal?.aborted ? new AbortController() : controller || new AbortController();
    const timer = setTimeout(() => activeController.abort(), api.timeoutMs);
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "omit",
        body: JSON.stringify(body),
        signal: activeController.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const error = new Error(payload?.error?.code === "snapshot_expired"
          ? "This result snapshot expired. Rebuild the submitted search to continue."
          : awardProduct.serviceIssueText(payload) || "The award service could not complete this request.");
        error.code = payload?.error?.code || "service_unavailable";
        error.payload = payload;
        throw error;
      }
      if (!payload || payload.schema_version !== 1 || !clean(payload.snapshot_id, 100)) throw new Error("The award service returned an invalid snapshot response.");
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  function absorbAwards(awards) {
    let added = 0;
    for (const award of Array.isArray(awards) ? awards : []) {
      const key = awardKey(award);
      if (!key || state.residentAwards.has(key)) continue;
      state.residentAwards.set(key, award);
      added += 1;
    }
    return added;
  }

  function absorbBatches(batches, { setOffsets = false } = {}) {
    for (const batch of Array.isArray(batches) ? batches : []) {
      if (!batch) continue;
      absorbAwards(batch.results);
      if (setOffsets) state.sourceOffsets.set(batch.source, Number(batch.loaded_through ?? batch.results?.length) || 0);
    }
  }

  function pageAwards(payload = state.pagePayload) {
    return (payload?.batches || []).flatMap(batch => batch.results || [])
      .sort((left, right) => Number(left.snapshot_position) - Number(right.snapshot_position));
  }

  function formatMoney(value) {
    const number = awardProduct.presentFiniteNumber(value);
    return number !== null
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(number)
      : "Amount not listed";
  }

  function renderAbstract(value) {
    const paragraphs = String(value || "").replace(/\r\n?/g, "\n").trim().split(/\n\s*\n+/)
      .map(paragraph => paragraph.replace(/\s+/g, " ").trim()).filter(Boolean);
    return (paragraphs.length ? paragraphs : ["Abstract not loaded in this compact snapshot. Use the official source record for full project text."])
      .map(paragraph => `<p>${escapeHtml(paragraph)}</p>`).join("");
  }

  function contactLine(person, source, officialUrl) {
    const name = clean(person?.name, 300) || "Name not listed";
    const role = clean(person?.role, 160) || "Contact";
    const email = clean(person?.email, 320);
    const contactUrl = safeUrl(person?.official_contact_url || officialUrl);
    if (email) return `<li><strong>${escapeHtml(name)}</strong> · ${escapeHtml(role)} · <a href="mailto:${escapeAttribute(email)}">${escapeHtml(email)}</a><span class="ii-contact-provenance">Direct ${escapeHtml(source)} source field</span></li>`;
    return contactUrl
      ? `<li><strong>${escapeHtml(name)}</strong> · ${escapeHtml(role)} · <a href="${escapeAttribute(contactUrl)}" target="_blank" rel="noopener">View on official record ↗</a></li>`
      : `<li><strong>${escapeHtml(name)}</strong> · ${escapeHtml(role)} · Email not listed</li>`;
  }

  function awardCard(award) {
    const source = clean(award?.source, 10) || "Source";
    const title = clean(award?.title, 1_000) || "Untitled funded project";
    const officialUrl = safeUrl(award?.official_award_url);
    const investigators = Array.isArray(award?.principal_investigators) ? award.principal_investigators : [];
    const contacts = [...investigators, ...(Array.isArray(award?.program_contacts) ? award.program_contacts : [])]
      .map(person => contactLine(person, source, officialUrl)).join("");
    const program = core.programDescriptors(award)[0] || null;
    const recency = clean(award?.award_date || award?.project_start || award?.award_year, 40) || "Date not listed";
    return `<article class="ii-award-card" id="${escapeAttribute(evidenceDomId(award))}" data-source="${escapeAttribute(source)}" data-evidence-id="${escapeAttribute(awardKey(award))}" tabindex="-1">
      <div class="ii-award-kicker"><span class="ii-award-source">${escapeHtml(source)}</span><span>${escapeHtml(award?.award_id || "ID not listed")}</span><span>${escapeHtml(recency)}</span><span>${escapeHtml(formatMoney(award?.total_award))}</span></div>
      <h3>${officialUrl ? `<a href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>` : escapeHtml(title)}</h3>
      <p class="ii-award-meta">${escapeHtml(award?.institution?.normalized_name || award?.institution?.name || "Institution not listed")}${investigators.length ? ` · ${escapeHtml(investigators.map(person => person.name).filter(Boolean).join(", "))}` : ""}</p>
      <p class="ii-award-program"><strong>Program:</strong> ${escapeHtml(program?.label || award?.subagency || "Not listed")}</p>
      ${contacts ? `<section class="ii-award-contacts" aria-label="Public award contacts"><h4>Investigators and program contacts</h4><ul>${contacts}</ul></section>` : ""}
      <div class="ii-award-actions">${officialUrl ? `<a href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">Official ${escapeHtml(source)} record ↗</a>` : "Official link not listed"}</div>
      <details class="ii-award-abstract"><summary>Project abstract</summary>${renderAbstract(award?.abstract)}</details>
    </article>`;
  }

  function sourceStatusText(source) {
    const message = state.sourceMessages.get(source.source);
    if (message) return message;
    if (source.status === "complete") return `${source.source} complete · ${source.result_count.toLocaleString()} awards · exact source total`;
    if (source.status === "safety_bounded") return `${source.source} safety-bounded · at least ${source.result_count.toLocaleString()} normalized awards available`;
    if (source.status === "partial") return `${source.source} partial · at least ${source.result_count.toLocaleString()} normalized awards available`;
    if (source.status === "rate_limited") return `${source.source} is rate-limited. Other source results remain available.`;
    if (source.status === "unsupported") return `${source.source} does not support this query shape. Other source results remain available.`;
    return `${source.source} is temporarily unavailable. Other source results remain available.`;
  }

  function renderSourceStatus() {
    const sources = state.snapshot?.sources || [];
    $("ii-source-status").innerHTML = sources.map(source => `<li data-status="${escapeAttribute(source.status)}">${escapeHtml(sourceStatusText(source))}</li>`).join("");
    $("ii-source-status").classList.toggle("hidden", !sources.length);
    const actions = [];
    for (const source of sources) {
      const offset = state.sourceOffsets.get(source.source) || 0;
      if (["unavailable", "rate_limited"].includes(source.status)) {
        actions.push(`<button class="button secondary" type="button" data-ii-retry-source="${escapeAttribute(source.source)}"${state.busyDepth ? " disabled" : ""}>Retry ${escapeHtml(source.source)}</button>`);
      } else if (offset < source.result_count) {
        actions.push(`<button class="button secondary" type="button" data-ii-load-source="${escapeAttribute(source.source)}"${state.busyDepth ? " disabled" : ""}>Load up to 25 more ${escapeHtml(source.source)} awards</button>`);
      }
    }
    $("ii-pagination").classList.toggle("hidden", !sources.length);
    $("ii-page-label").textContent = actions.length
      ? "Optional card hydration is source-specific and limited to 25 records per agency per action. Most recent available awards load first. Snapshot totals and pages do not depend on card hydration."
      : state.snapshot?.completeness === "complete"
        ? "All source batches in this exact result snapshot are available."
        : "All records found within the disclosed upstream safety bounds are available; this is not claimed as a complete institutional history.";
    $("ii-load-more-actions").innerHTML = actions.join("");
  }

  function renderFacetSelect(select, items, kind) {
    const allLabel = kind === "investigator" ? "All investigators" : "All programs";
    if (kind === "investigator") state.investigatorGroups = new Map(items.map(item => [item.identity_key, item]));
    else state.programGroups = new Map(items.map(item => [item.key, item]));
    select.innerHTML = `<option value="all">${allLabel}</option>${items.map(item => {
      const value = kind === "investigator" ? item.identity_key : item.key;
      return `<option value="${escapeAttribute(value)}">${escapeHtml(kind === "investigator" ? item.name : item.label)} (${item.projects})</option>`;
    }).join("")}`;
    select.disabled = state.busyDepth > 0 || items.length === 0;
    select.value = state.facet.type === kind ? state.facet.key : "all";
  }

  function renderPagination() {
    const pagination = state.pagePayload?.pagination;
    if (!pagination) return;
    const exact = state.pagePayload.completeness === "complete";
    const total = exact ? state.pagePayload.exact_total : state.pagePayload.at_least;
    $("ii-card-page-label").textContent = pagination.end
      ? exact
        ? `Awards ${pagination.start}–${pagination.end} of ${total.toLocaleString()} · Page ${pagination.page} of ${pagination.page_count}`
        : `Awards ${pagination.start}–${pagination.end} of at least ${total.toLocaleString()} available · Page ${pagination.page} (partial result set)`
      : exact ? "No awards matched this view." : "No awards were available within the current partial result set.";
    $("ii-card-previous").disabled = state.busyDepth > 0 || !pagination.has_previous;
    $("ii-card-next").disabled = state.busyDepth > 0 || !pagination.has_next;
    const knownPages = pagination.page_count || pagination.available_page_count;
    $("ii-card-page-numbers").innerHTML = core.compactPageNumbers(pagination.page, knownPages).map(value => value === null
      ? '<span class="ii-page-ellipsis" aria-hidden="true">…</span>'
      : `<button class="text-button${value === pagination.page ? " active" : ""}" type="button" data-ii-page-number="${value}"${value === pagination.page ? ' aria-current="page"' : ""}${state.busyDepth ? " disabled" : ""}>${value}</button>`).join("");
    $("ii-card-pagination").classList.toggle("hidden", knownPages <= 1 && !pagination.end);
    $("ii-page-size").value = String(state.pageSize);
    $("ii-page-size").disabled = state.busyDepth > 0;
  }

  function renderPage({ focus = false } = {}) {
    const payload = state.pagePayload;
    if (!payload) return;
    state.aggregate = { ...payload.aggregate, awards: pageAwards(payload) };
    state.baseAggregate = payload.facet?.type === "all"
      ? payload.aggregate
      : payload.base_aggregate || state.baseAggregate;
    const awards = state.aggregate.awards;
    absorbAwards(awards);
    $("ii-output").classList.remove("hidden");
    const institution = clean(state.submitted?.institution, 300);
    $("ii-output-heading").textContent = institution ? `${institution} funded projects` : "Funded award summary";
    const requestedYears = state.submitted?.year_start && state.submitted?.year_end
      ? `${state.submitted.year_start}–${state.submitted.year_end}`
      : state.submitted?.year_start ? `${state.submitted.year_start} onward` : state.submitted?.year_end ? `through ${state.submitted.year_end}` : "all available years";
    const totalText = payload.completeness === "complete"
      ? `${payload.exact_total.toLocaleString()} exact matching award${payload.exact_total === 1 ? "" : "s"}`
      : `at least ${payload.at_least.toLocaleString()} matching award${payload.at_least === 1 ? "" : "s"} within the disclosed source bounds`;
    $("ii-result-scope").textContent = `Requested award years: ${requestedYears}. This stable ${payload.as_of.slice(0, 10)} snapshot contains ${totalText}, ordered by award or action date, then project start, then award year; missing dates sort last.`;
    const years = payload.aggregate.year_start
      ? payload.aggregate.year_start === payload.aggregate.year_end ? String(payload.aggregate.year_start) : `${payload.aggregate.year_start}–${payload.aggregate.year_end}`
      : "Not listed";
    const scope = payload.completeness === "complete" ? "in complete result" : "in available partial result";
    $("ii-metrics").innerHTML = [
      [payload.aggregate.project_count, `Projects ${scope}`],
      [payload.aggregate.investigator_count, `Investigator identities ${scope}`],
      [payload.aggregate.program_count, `Distinct programs ${scope}`],
      [years, `Years represented ${scope}`],
    ].map(([value, label]) => `<div class="ii-metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    renderFacetSelect($("ii-investigators"), state.baseAggregate.investigators || [], "investigator");
    renderFacetSelect($("ii-programs"), state.baseAggregate.programs || [], "program");
    const active = payload.facet?.type !== "all";
    $("ii-active-facet").classList.toggle("hidden", !active);
    $("ii-clear-facet").disabled = state.busyDepth > 0 || !active;
    $("ii-active-facet-label").textContent = active ? `Active ${payload.facet.type} drill-down: ${payload.facet.label}` : "";
    if (active && payload.facet.type === "investigator") {
      const group = state.investigatorGroups.get(payload.facet.key);
      $("ii-investigator-variants").textContent = group
        ? `${group.name} · ${group.projects} award${group.projects === 1 ? "" : "s"}. Source-published variants: ${group.variants.map(variant => `${variant.name} (${variant.source})`).join("; ")}.`
        : "The selected investigator identity is no longer present in this snapshot.";
    } else {
      $("ii-investigator-variants").textContent = "Select an investigator to filter this snapshot without starting another upstream search.";
    }
    $("ii-awards").innerHTML = awards.length ? awards.map(awardCard).join("") : "<p>No normalized public award records matched this view.</p>";
    renderPagination();
    renderSourceStatus();
    renderQuestionAnswer();
    if (focus) requestAnimationFrame(() => {
      const first = $("ii-awards").querySelector(".ii-award-card");
      first?.focus({ preventScroll: true });
      first?.scrollIntoView({ block: "start" });
    });
  }

  async function fetchPage({ page = state.page, pageSize = state.pageSize, facet = state.facet, historyMode = "replace", focus = false } = {}) {
    if (!state.snapshot?.snapshot_id) return null;
    const requestSequence = ++state.pageRequestSequence;
    const snapshotId = state.snapshot.snapshot_id;
    let payload;
    try {
      payload = await postJson(api.snapshotPageUrl, {
        snapshot_id: snapshotId,
        page,
        page_size: pageSize,
        facet: { type: facet.type, key: facet.key },
      });
    } catch (error) {
      if (requestSequence !== state.pageRequestSequence) return null;
      throw error;
    }
    if (requestSequence !== state.pageRequestSequence || state.snapshot?.snapshot_id !== snapshotId) return null;
    state.page = payload.pagination.page;
    state.pageSize = payload.pagination.page_size;
    state.facet = { type: payload.facet.type, key: payload.facet.key };
    state.pagePayload = payload;
    state.snapshot = { ...state.snapshot, ...payload, snapshot_id: payload.snapshot_id };
    renderPage({ focus });
    syncUrl(historyMode);
    return payload;
  }

  async function fetchPageWithRecovery({ page = state.page, pageSize = state.pageSize, facet = state.facet, historyMode = "replace", focus = false } = {}) {
    try {
      return await fetchPage({ page, pageSize, facet, historyMode, focus });
    } catch (error) {
      if (error?.code !== "snapshot_expired") throw error;
      setStatus("The result snapshot expired. Rebuilding the submitted search before restoring this view…");
      const requestedFacet = facet?.type === "all" ? { type: "all", key: "" } : { type: facet.type, key: facet.key };
      const retryView = page !== 1 || requestedFacet.type !== "all";
      const submitted = {
        ...(state.submitted || formState()),
        snapshot_id: "",
        page: 1,
        page_size: pageSize,
        facet_type: "all",
        facet_key: "",
      };
      const refreshed = await runSearch({
        historyMode: retryView ? "replace" : historyMode,
        resolveInstitution: false,
        focusResults: !retryView && focus,
        searchState: submitted,
      });
      if (!refreshed) return null;
      if (!retryView) {
        setStatus("The expired result snapshot was rebuilt from the submitted search.");
        return state.pagePayload;
      }
      const payload = await fetchPage({ page, pageSize, facet: requestedFacet, historyMode, focus });
      if (payload) setStatus("The expired result snapshot was rebuilt and the requested view was restored.");
      return payload;
    }
  }

  async function runSearch({ historyMode = "replace", resolveInstitution = true, focusResults = false, questionSearch = false, searchState = null } = {}) {
    const sequence = ++state.sequence;
    state.pageRequestSequence += 1;
    state.controller?.abort();
    state.controller = new AbortController();
    setBusy(true);
    setStatus("Building a stable, safety-bounded NSF, NIH, and DOE result snapshot…");
    try {
      if (resolveInstitution) await resolveTypedInstitution();
      if (!questionSearch) {
        state.question = null;
        $("ii-question-answer").classList.add("hidden");
      }
      const current = searchState ? { ...searchState } : formState();
      const request = core.buildAwardRequest({ ...current, offset: 0 }, 10);
      state.submitted = { ...current, snapshot_id: "", page: 1, page_size: current.page_size || 10, facet_type: "all", facet_key: "" };
      const snapshot = await postJson(api.snapshotUrl, { sources: request.sources, criteria: request.criteria });
      if (sequence !== state.sequence) return null;
      state.snapshot = snapshot;
      state.page = 1;
      state.pageSize = current.page_size || 10;
      state.facet = { type: "all", key: "" };
      state.residentAwards.clear();
      state.sourceOffsets.clear();
      state.sourceMessages.clear();
      for (const batch of snapshot.initial_batches || []) {
        if (!batch) continue;
        absorbAwards(batch.results);
        state.sourceOffsets.set(batch.source, batch.loaded_through || batch.results.length);
      }
      state.submitted.snapshot_id = snapshot.snapshot_id;
      const initialPage = await fetchPage({ historyMode, focus: focusResults });
      if (!initialPage || sequence !== state.sequence) return null;
      const exact = snapshot.completeness === "complete";
      setStatus(exact
        ? `${snapshot.exact_total.toLocaleString()} exact matching award${snapshot.exact_total === 1 ? "" : "s"} are available in this stable snapshot.`
        : `${snapshot.at_least.toLocaleString()} matching award${snapshot.at_least === 1 ? "" : "s"} are available within disclosed safety bounds; incomplete sources are labeled below.`);
      if (focusResults) $("ii-output-heading").focus({ preventScroll: true });
      return { payload: state.pagePayload, aggregate: state.aggregate };
    } catch (error) {
      if (sequence !== state.sequence) return null;
      if (error?.name === "AbortError") setStatus("The result snapshot search timed out. Retry later.", true);
      else setStatus(error?.message || "Funded award search could not be completed.", true);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function changeFacet(type, key, { historyMode = "push", focus = true } = {}) {
    state.question = null;
    $("ii-question-answer").classList.add("hidden");
    state.facet = type === "all" ? { type: "all", key: "" } : { type, key };
    state.page = 1;
    setBusy(true);
    try {
      const payload = await fetchPageWithRecovery({ historyMode, focus });
      if (!payload) return;
      setStatus(state.facet.type === "all" ? "Showing all awards in the submitted result snapshot." : `Showing the ${state.pagePayload.facet.label} drill-down within the same result snapshot.`);
    } catch (error) {
      setStatus(error?.message || "The requested drill-down could not be loaded.", true);
    } finally {
      setBusy(false);
    }
  }

  async function loadSourceBatch(source) {
    const offset = state.sourceOffsets.get(source) || 0;
    setBusy(true);
    try {
      const batch = await postJson(api.snapshotBatchUrl, {
        snapshot_id: state.snapshot.snapshot_id,
        source,
        offset,
        facet: { type: "all", key: "" },
      });
      const actualAdded = absorbAwards(batch.results);
      state.sourceOffsets.set(source, batch.loaded_through);
      const loaded = [...state.residentAwards.values()].filter(award => clean(award.source, 10).toUpperCase() === source).length;
      state.sourceMessages.set(source, batch.source_total !== null
        ? batch.loaded_through >= batch.source_total
          ? `Loaded remaining ${actualAdded} ${source} award${actualAdded === 1 ? "" : "s"}; all ${batch.source_total} ${source} awards are available as hydrated cards.`
          : `Loaded ${actualAdded} additional ${source} award${actualAdded === 1 ? "" : "s"}; ${loaded} of ${batch.source_total} are hydrated. Most recent first.`
        : `Loaded ${actualAdded} additional ${source} award${actualAdded === 1 ? "" : "s"} after normalization; ${loaded} are hydrated within the partial source snapshot.`);
      renderSourceStatus();
      setStatus(state.sourceMessages.get(source));
      renderQuestionAnswer();
    } catch (error) {
      setStatus(`${source} card hydration failed. Existing results remain available.`, true);
    } finally {
      setBusy(false);
    }
  }

  async function retrySource(source) {
    const previous = state.snapshot.snapshot_id;
    setBusy(true);
    setStatus(`Retrying ${source}; successful source results remain available…`);
    try {
      const snapshot = await postJson(api.snapshotRetryUrl, { snapshot_id: previous, source });
      state.snapshot = snapshot;
      state.submitted.snapshot_id = snapshot.snapshot_id;
      state.sourceMessages.set(source, `${source} recovered. The successor snapshot retained the other successful sources.`);
      for (const batch of snapshot.initial_batches || []) {
        if (!batch || batch.source !== source) continue;
        absorbAwards(batch.results);
        state.sourceOffsets.set(source, batch.loaded_through);
      }
      state.page = 1;
      state.facet = { type: "all", key: "" };
      await fetchPage({ historyMode: "replace" });
      setStatus(`${source} recovered in successor snapshot ${snapshot.snapshot_id.slice(0, 12)}…; successful source results were retained.`);
    } catch (error) {
      state.sourceMessages.set(source, `${source} retry did not recover. Existing snapshot results remain available.`);
      renderSourceStatus();
      setStatus(state.sourceMessages.get(source), true);
    } finally {
      setBusy(false);
    }
  }

  function answerEvidenceSignature() {
    return JSON.stringify({ snapshot: state.snapshot?.snapshot_id, ids: [...state.residentAwards.keys()].sort(), facet: state.facet });
  }

  function renderQuestionAnswer() {
    const snapshot = state.question?.snapshot;
    if (!snapshot) return $("ii-question-answer").classList.add("hidden");
    $("ii-question-answer").classList.remove("hidden");
    $("ii-answered-question").textContent = state.question.question;
    const claims = snapshot.narrative?.claims || [];
    $("ii-direct-answer").innerHTML = `<p class="ii-answer-summary">${escapeHtml(snapshot.deterministic.answer)}</p>${claims.length
      ? `<ul class="ii-answer-claims">${claims.map(claim => `<li>${escapeHtml(claim.text)} ${claim.evidence_ids.map(id => `<a href="#${escapeAttribute(evidenceDomId(id))}" data-ii-evidence-link="${escapeAttribute(id)}">[${escapeHtml(id)}]</a>`).join(" ")}</li>`).join("")}</ul>`
      : ""}`;
    const ids = new Set(snapshot.deterministic.evidence_ids);
    const evidence = snapshot.evidencePack.awards.filter(item => ids.has(item.evidence_id));
    $("ii-answer-evidence").innerHTML = evidence.length
      ? `<h4>Supporting award evidence</h4><ul class="ii-evidence-list">${evidence.map(item => `<li><a href="#${escapeAttribute(evidenceDomId(item.evidence_id))}" data-ii-evidence-link="${escapeAttribute(item.evidence_id)}">${escapeHtml(item.evidence_id)}</a><span class="ii-evidence-title">${escapeHtml(item.title || "Title not listed")}</span></li>`).join("")}</ul>`
      : "<h4>Supporting award evidence</h4><p>No hydrated supporting award card is currently available.</p>";
    const incomplete = state.snapshot.completeness !== "complete";
    $("ii-answer-limitations").textContent = `${snapshot.aggregate.project_count} normalized awards informed the server aggregate. ${snapshot.evidencePack.awards.length} hydrated public records supplied bounded card evidence.${incomplete ? " One or more sources reached a disclosed safety bound or failed, so this is not a complete institutional history." : " All requested sources were exhausted within the published architecture bounds."}${state.question.translationFallback ? " Provider translation was unavailable, so visible filters and deterministic intent were used." : ""}${snapshot.narrativeFailure ? " Narrative synthesis was unavailable or failed evidence validation, so the deterministic answer is shown." : ""}`;
    $("ii-update-answer").classList.toggle("hidden", snapshot.signature === answerEvidenceSignature());
  }

  async function refreshQuestionAnswer() {
    if (!state.question || !state.aggregate || state.answering) return;
    state.answering = true;
    const evidencePack = core.questionEvidencePack([...state.residentAwards.values()]);
    const aggregate = { ...state.aggregate, awards: pageAwards(), ordered_refs: state.pagePayload.aggregate.ordered_refs };
    const deterministic = core.deterministicInstitutionAnswer({
      question: state.question.question,
      intent: state.question.intent,
      aggregate,
      sources: state.snapshot.sources,
    });
    let narrative = null;
    let narrativeFailure = false;
    if (state.question.narrativeNeeded) {
      const key = credentials.loadKey(state.question.provider);
      if (key) {
        try {
          const providerPayload = core.questionProviderPayload({
            question: state.question.question,
            institution: state.selectedInstitution,
            filters: state.question.filters,
            intent: state.question.intent,
            evidencePack,
          });
          const proposed = await ai.structuredResult({
            provider: state.question.provider,
            key,
            operation: "institution_narrative",
            fetchImpl: globalThis.fetch,
            system: "Synthesize only the supplied public award titles and abstract excerpts. Return JSON with claims, an array of at most six objects containing text and evidence_ids. Every claim must cite exact supplied evidence IDs. Do not use model pretraining, infer identities or contacts, recommend collaborators, rank investigators, score fit, or return HTML.",
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
    state.question.snapshot = { aggregate, evidencePack, deterministic, narrative, narrativeFailure, signature: answerEvidenceSignature() };
    state.answering = false;
    renderQuestionAnswer();
  }

  async function focusAwardEvidence(evidenceId) {
    const reference = state.pagePayload?.aggregate?.ordered_refs?.find(item => item.evidence_id === evidenceId);
    if (!reference) return;
    const page = Math.floor((reference.position - 1) / state.pageSize) + 1;
    if (page !== state.page) {
      setBusy(true);
      try { await fetchPageWithRecovery({ page, historyMode: "push" }); } finally { setBusy(false); }
    }
    requestAnimationFrame(() => {
      const card = $(evidenceDomId(evidenceId));
      card?.focus({ preventScroll: true });
      card?.scrollIntoView({ block: "start" });
    });
  }

  function modelForProvider(provider) {
    return provider === "anthropic" ? ai?.ANTHROPIC_MODEL : ai?.OPENAI_MODEL;
  }

  function refreshProvider({ preferMain = true } = {}) {
    let provider = preferMain ? clean($("k-provider")?.value, 20) : clean($("ii-provider").value, 20);
    if (!["openai", "anthropic"].includes(provider)) provider = "openai";
    $("ii-provider").value = provider;
    $("ii-model").textContent = modelForProvider(provider) || "Funding Finder default";
    $("ii-key").placeholder = provider === "anthropic" ? "sk-ant-..." : "sk-...";
    const configured = Boolean(credentials.loadKey(provider));
    $("ii-ai-state").textContent = configured ? `${provider === "anthropic" ? "Anthropic" : "OpenAI"} · ${modelForProvider(provider)} configured` : "No AI key required for deterministic answers";
    $("ii-key-setup").classList.toggle("hidden", configured);
    $("ii-key-status").textContent = configured ? "Using the Funding Finder key already saved on this device." : "Optional. Deterministic questions work without a key.";
    return { provider, configured };
  }

  function saveSharedKey() {
    const provider = $("ii-provider").value;
    const key = clean($("ii-key").value, 1_000);
    if (!key) return $("ii-key-status").textContent = "Enter a key to save it in the shared browser-local provider configuration.";
    credentials.saveKey(provider, key);
    $("ii-key").value = "";
    $("ii-key-status").textContent = "Saved in the shared browser-local provider configuration on this device.";
    refreshProvider({ preferMain: false });
  }

  async function askQuestion() {
    if (state.questionSubmitting) return;
    state.questionSubmitting = true;
    $("ii-ask-button").disabled = true;
    try {
      const question = clean($("ii-question").value, 1_000);
      if (!question) throw new Error("Enter a question first.");
      const institution = await resolveTypedInstitution();
      if (!institution) throw new Error("Select an institution before asking a question about it.");
      const current = formState();
      const { provider, configured } = refreshProvider();
      const key = credentials.loadKey(provider);
      let plan = { ...current };
      let translationFallback = !configured || !key;
      if (!translationFallback) {
        try {
          const currentFilters = {
            agency: current.agency,
            program: current.program,
            topic: current.topic,
            pi: current.pi,
            program_officer: current.program_officer,
            year_start: current.year_start,
            year_end: current.year_end,
          };
          const translated = await ai.structuredResult({
            provider,
            key,
            operation: "institution_question_translation",
            fetchImpl: globalThis.fetch,
            system: "Translate one question about public NSF, NIH, or DOE funded awards into structured filters and a bounded answer intent. Return only JSON with agency, program, topic, pi, program_officer, year_start, year_end, answer_intent, and narrative_needed. Use empty strings for absent filters. Do not answer the question, infer contacts, recommend collaborators, rank investigators, score fit, or invent facts. DOE Basic Energy Sciences is agency DOE and program BES.",
            user: JSON.stringify({ institution: current.institution, current_filters: currentFilters, question }),
          });
          if (!translated || typeof translated !== "object" || Array.isArray(translated)) throw new Error("invalid_translation");
          plan = { ...translated };
        } catch {
          translationFallback = true;
          plan = { ...current };
        }
      }
      const upper = `${question} ${clean(plan.program)}`.toUpperCase();
      plan.agency = ["NSF", "NIH", "DOE"].includes(clean(plan.agency, 10).toUpperCase())
        ? clean(plan.agency, 10).toUpperCase()
        : /\bNSF\b/.test(upper) ? "NSF" : /\bNIH\b/.test(upper) ? "NIH" : /\bDOE\b|\bBES\b|\bSC-\d+\b/.test(upper) ? "DOE" : "all";
      const investigator = core.explicitInvestigator(question, current.institution, plan.program, [...(state.selectedInstitution?.aliases || []), ...(state.selectedInstitution?.acronyms || [])], plan.topic);
      if (investigator && !clean(plan.pi) && !clean(plan.program_officer)) plan.pi = investigator;
      if (/\bBES\b/i.test(question) && !clean(plan.program)) plan.program = "BES";
      const next = core.sanitizeQuestionPlan(plan, current);
      const intent = core.sanitizeAnswerIntent(plan, question);
      const details = [`Answer intent: ${intent}`];
      if (next.agency !== "all") details.push(`Agency: ${next.agency}`);
      if (next.pi) details.push(`Investigator: ${next.pi}`);
      if (next.program) details.push(`Program: ${next.program}`);
      $("ii-question-plan").textContent = `Deterministic evidence plan · ${details.join(" · ")}`;
      $("ii-question-plan").classList.remove("hidden");
      applyFormState(next);
      state.question = { question, intent, filters: next, provider, narrativeNeeded: plan.narrative_needed === true || intent === "narrative", translationFallback, snapshot: null };
      const outcome = await runSearch({ historyMode: "push", resolveInstitution: false, focusResults: true, questionSearch: true, searchState: next });
      if (outcome) await refreshQuestionAnswer();
    } catch (error) {
      $("ii-question-plan").textContent = `The evidence-grounded question could not be completed: ${error?.message || String(error)}`;
      $("ii-question-plan").classList.remove("hidden");
    } finally {
      state.questionSubmitting = false;
      $("ii-ask-button").disabled = false;
    }
  }

  function resetResultState() {
    state.snapshot = null;
    state.pagePayload = null;
    state.aggregate = null;
    state.baseAggregate = null;
    state.submitted = null;
    state.facet = { type: "all", key: "" };
    state.page = 1;
    state.pageSize = 10;
    state.residentAwards.clear();
    state.sourceOffsets.clear();
    state.sourceMessages.clear();
    state.question = null;
  }

  function clearSearch({ historyMode = "push" } = {}) {
    state.sequence += 1;
    state.pageRequestSequence += 1;
    state.controller?.abort();
    state.selectedInstitution = null;
    resetResultState();
    applyFormState({ open: true, institution: "", agency: "all", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", page: 1, page_size: 10, facet_type: "all", facet_key: "" });
    for (const id of ["ii-output", "ii-source-status", "ii-question-plan", "ii-question-answer", "ii-pagination", "ii-card-pagination"]) $(id).classList.add("hidden");
    setStatus("Structured award search and institution resolution do not require an AI key.");
    if (location.protocol.startsWith("http")) history[historyMode === "push" ? "pushState" : "replaceState"](null, "", core.urlForState(location.href, { open: true }));
  }

  function bindEvents() {
    $("ii-institution").addEventListener("input", () => {
      state.selectedInstitution = null;
      clearTimeout(state.registryTimer);
      const query = clean($("ii-institution").value, 120);
      if (query.length < 2) {
        hideRegistryOptions();
        $("ii-registry-status").textContent = query ? "Type at least two characters to search ROR." : "Institution is optional.";
        return;
      }
      state.registryTimer = setTimeout(() => fetchRegistry(query), 300);
    });
    $("ii-institution").addEventListener("keydown", event => {
      if ($("ii-institution-options").classList.contains("hidden")) return;
      if (event.key === "ArrowDown") { event.preventDefault(); updateActiveOption(state.activeOption + 1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); updateActiveOption(state.activeOption < 0 ? state.registryCandidates.length - 1 : state.activeOption - 1); }
      else if (event.key === "Enter" && state.activeOption >= 0) { event.preventDefault(); setSelectedInstitution(state.registryCandidates[state.activeOption]); }
      else if (event.key === "Escape") hideRegistryOptions();
    });
    $("ii-institution").addEventListener("blur", () => setTimeout(hideRegistryOptions, 120));
    $("ii-institution-options").addEventListener("mousedown", event => event.preventDefault());
    $("ii-institution-options").addEventListener("click", event => {
      const option = event.target.closest("[data-ii-institution-index]");
      if (!option) return;
      setSelectedInstitution(state.registryCandidates[Number(option.dataset.iiInstitutionIndex)]);
      $("ii-institution").focus();
    });
    $("ii-form").addEventListener("submit", event => { event.preventDefault(); if (!state.busyDepth) runSearch({ historyMode: "push", focusResults: true }); });
    $("ii-clear").addEventListener("click", () => { if (!state.busyDepth) clearSearch(); });
    $("ii-clear-facet").addEventListener("click", () => { if (!state.busyDepth) changeFacet("all", ""); });
    $("ii-investigators").addEventListener("change", event => {
      if (state.busyDepth) return;
      const key = event.currentTarget.value;
      if (key === "all") return changeFacet("all", "");
      $("ii-programs").value = "all";
      return changeFacet("investigator", key);
    });
    $("ii-programs").addEventListener("change", event => {
      if (state.busyDepth) return;
      const key = event.currentTarget.value;
      if (key === "all") return changeFacet("all", "");
      $("ii-investigators").value = "all";
      return changeFacet("program", key);
    });
    $("ii-load-more-actions").addEventListener("click", event => {
      if (state.busyDepth) return;
      const load = event.target.closest("[data-ii-load-source]");
      const retry = event.target.closest("[data-ii-retry-source]");
      if (load) loadSourceBatch(load.dataset.iiLoadSource);
      else if (retry) retrySource(retry.dataset.iiRetrySource);
    });
    $("ii-card-pagination").addEventListener("click", event => {
      if (state.busyDepth) return;
      const numbered = event.target.closest("[data-ii-page-number]");
      const relative = event.target.closest("[data-ii-card-page]");
      const page = numbered ? Number(numbered.dataset.iiPageNumber)
        : relative ? state.page + (relative.dataset.iiCardPage === "next" ? 1 : -1) : null;
      if (!page || page === state.page) return;
      setBusy(true);
      fetchPageWithRecovery({ page, historyMode: "push", focus: true }).catch(error => setStatus(error.message, true)).finally(() => setBusy(false));
    });
    $("ii-page-size").addEventListener("change", event => {
      if (state.busyDepth) return;
      const nextSize = Number(event.currentTarget.value);
      const anchor = (state.page - 1) * state.pageSize;
      const page = Math.floor(anchor / nextSize) + 1;
      setBusy(true);
      fetchPageWithRecovery({ page, pageSize: nextSize, historyMode: "push", focus: true }).catch(error => setStatus(error.message, true)).finally(() => setBusy(false));
    });
    $("ii-question-answer").addEventListener("click", event => {
      const link = event.target.closest("[data-ii-evidence-link]");
      if (!link) return;
      event.preventDefault();
      focusAwardEvidence(link.dataset.iiEvidenceLink);
    });
    $("ii-provider").addEventListener("change", () => refreshProvider({ preferMain: false }));
    $("ii-save-key").addEventListener("click", saveSharedKey);
    $("ii-ask-button").addEventListener("click", askQuestion);
    $("ii-question").addEventListener("keydown", event => {
      if (event.key !== "Enter" || event.repeat || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
      event.preventDefault();
      if (!$("ii-ask-button").disabled) askQuestion();
    });
    $("ii-update-answer").addEventListener("click", refreshQuestionAnswer);
    $("k-provider")?.addEventListener("change", () => setTimeout(refreshProvider, 0));
    window.addEventListener("popstate", async event => {
      const restored = core.stateFromSearch(location.search);
      applyFormState(restored);
      state.submitted = { ...restored };
      state.page = restored.page;
      state.pageSize = restored.page_size;
      state.facet = { type: restored.facet_type, key: restored.facet_key };
      if (!hasSearchState(restored) || new URLSearchParams(location.search).has("opportunity")) return clearSearch({ historyMode: "replace" });
      state.sequence += 1;
      state.pageRequestSequence += 1;
      state.controller?.abort();
      state.controller = new AbortController();
      setBusy(true);
      try {
        if (restored.snapshot_id) {
          state.snapshot = { snapshot_id: restored.snapshot_id, sources: state.snapshot?.sources || [] };
          await fetchPageWithRecovery({ page: restored.page, pageSize: restored.page_size, facet: { type: restored.facet_type, key: restored.facet_key }, historyMode: "replace" });
        } else {
          await runSearch({ historyMode: "replace", resolveInstitution: false, searchState: restored });
        }
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        setBusy(false);
        requestAnimationFrame(() => {
          if (event.state?.focusId) $(event.state.focusId)?.focus({ preventScroll: true });
          if (Number.isFinite(event.state?.scrollY)) window.scrollTo({ top: event.state.scrollY });
        });
      }
    });
  }

  async function initialize() {
    const restored = core.stateFromSearch(location.search);
    applyFormState(restored);
    bindEvents();
    refreshProvider();
    if (!hasSearchState(restored) || new URLSearchParams(location.search).has("opportunity")) return;
    state.submitted = { ...restored };
    if (restored.snapshot_id) {
      state.snapshot = { snapshot_id: restored.snapshot_id, sources: [] };
      state.controller = new AbortController();
      setBusy(true);
      try {
        await fetchPageWithRecovery({ page: restored.page, pageSize: restored.page_size, facet: { type: restored.facet_type, key: restored.facet_key }, historyMode: "replace" });
        state.snapshot = { ...state.snapshot, ...state.pagePayload };
        setStatus("Restored the shared result snapshot and page.");
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        setBusy(false);
      }
    } else {
      await runSearch({ historyMode: "replace", resolveInstitution: false, searchState: restored });
    }
  }

  initialize();
})();
