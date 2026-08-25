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

  function setStatus(message, error = false) {
    $("ii-status").textContent = message;
    $("ii-status").classList.toggle("error-text", error);
  }

  function setBusy(busy) {
    $("ii-search").disabled = busy;
    $("ii-ask-button").disabled = busy;
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
      throw new Error("Choose the intended Research Organization Registry (ROR) suggestion or type the institution’s complete canonical name.");
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
    return `<article class="ii-award-card" data-source="${escapeAttribute(source)}">
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
        ? `${source.source} available · ${source.result_count || 0} loaded`
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
    select.innerHTML = items.length
      ? `<option value="">Choose a ${noun} (${items.length})</option>${items.map(item => {
        const value = kind === "investigator" ? item.name : item.query;
        const attributes = kind === "program" ? ` data-ii-program-source="${escapeAttribute(item.source)}"` : "";
        return `<option value="${escapeAttribute(value)}"${attributes}>${escapeHtml(kind === "investigator" ? item.name : item.label)} · ${item.projects} project${item.projects === 1 ? "" : "s"}</option>`;
      }).join("")}`
      : `<option value="">No ${kind === "investigator" ? "investigators" : "programs"} loaded</option>`;
    select.disabled = items.length === 0;
  }

  function renderLoadMore(aggregate) {
    const pages = [...state.sourcePages.values()];
    const available = pages.filter(page => page.hasMore);
    const retryable = pages.filter(page => page.error);
    const actions = [...available, ...retryable.filter(page => !available.includes(page))];
    $("ii-pagination").classList.toggle("hidden", actions.length === 0);
    $("ii-page-label").textContent = actions.length
      ? `${aggregate.project_count.toLocaleString()} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded. Additional source pages are available from ${available.map(page => page.source).join(", ") || "the source that could not be reached"}.`
      : `${aggregate.project_count.toLocaleString()} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded in this view.`;
    $("ii-load-more-actions").innerHTML = actions.map(page => `<button class="button secondary" type="button" data-ii-load-source="${escapeAttribute(page.source)}">${page.error ? "Retry" : "Load more"} ${escapeHtml(page.source)}</button>`).join("");
    syncPaginationControls();
  }

  function renderAggregate(payload) {
    const aggregate = core.aggregateAwards(payload.results);
    const submittedPage = state.sourcePages.values().next().value;
    const institution = submittedPage
      ? clean(submittedPage.request?.criteria?.institution, 300)
      : clean(state.selectedInstitution?.canonical_name || $("ii-institution").value, 300);
    $("ii-output").classList.remove("hidden");
    $("ii-output-heading").textContent = institution ? `${institution} funded projects` : "Funded award summary";
    const moreSources = (payload.sources || []).filter(source => source.status === "ok" && source.has_more === true).map(source => source.source);
    $("ii-result-scope").textContent = `Summaries cover ${aggregate.project_count} normalized project${aggregate.project_count === 1 ? "" : "s"} loaded across source-specific pages${moreSources.length ? `; load more from ${moreSources.join(", ")}` : ""}.`;
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
    renderFacetSelect($("ii-programs"), aggregate.programs, { kind: "program" });
    $("ii-awards").innerHTML = aggregate.awards.length
      ? aggregate.awards.map(awardCard).join("")
      : "<p>No normalized public award records matched these filters.</p>";
    renderSourceStatus(payload.sources);
    renderLoadMore(aggregate);
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

  async function runSearch({ historyMode = "replace", resolveInstitution = true, offset = null, focusResults = false, scrollResults = false } = {}) {
    const sequence = ++state.searchSequence;
    state.searchController?.abort();
    state.loadingSource = "";
    state.searchController = new AbortController();
    setBusy(true);
    setStatus("Searching normalized public NSF, NIH, and DOE award records…");
    try {
      if (resolveInstitution) await resolveTypedInstitution();
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
      const payload = await fetchAwardPage(requestBody, state.searchController);
      if (sequence !== state.searchSequence) return;
      const next = sourcePage(requestBody, payload);
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
        page.hasMore = next.hasMore && next.nextOffset <= 1_000;
        page.error = null;
        state.sourcePages.set(source, page);
        state.payload = combinedPayload();
        const aggregate = renderAggregate(state.payload);
        setStatus(`${added.length} additional ${source} project${added.length === 1 ? "" : "s"} loaded. ${aggregate.project_count} normalized project${aggregate.project_count === 1 ? " is" : "s are"} now shown.`);
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
    state.sourcePages.clear();
    state.loadingSource = "";
    applyFormState({ open: true, institution: "", agency: "all", program: "", topic: "", pi: "", program_officer: "", year_start: "", year_end: "", offset: 0 });
    $("ii-output").classList.add("hidden");
    $("ii-source-status").classList.add("hidden");
    $("ii-question-plan").classList.add("hidden");
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

  function renderQuestionPlan(value) {
    const labels = [
      value.institution ? `Institution: ${value.institution}` : "",
      `Agency: ${value.agency === "all" ? "NSF + NIH + DOE" : value.agency}`,
      value.program ? `Program: ${value.program}` : "",
      value.topic ? `Topic: ${value.topic}` : "",
      value.pi ? `Investigator: ${value.pi}` : "",
      value.program_officer ? `Program officer: ${value.program_officer}` : "",
      value.year_start || value.year_end ? `Years: ${value.year_start || "any"}–${value.year_end || "any"}` : "",
    ].filter(Boolean);
    $("ii-question-plan").innerHTML = `<strong>Transparent search plan:</strong> ${labels.map(escapeHtml).join(" · ")}. The public award records below remain authoritative.`;
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
      $("ii-key-status").textContent = "Save a key here or in Funding Finder’s existing AI setup to translate this question. Structured filters remain available without one.";
      $("ii-key").focus();
      return;
    }
    $("ii-ask-button").disabled = true;
    $("ii-question-plan").textContent = "Translating the question into bounded public-award filters…";
    $("ii-question-plan").classList.remove("hidden");
    try {
      const current = formState();
      const translated = await ai.providerJson({
        provider,
        key,
        fetchImpl: globalThis.fetch,
        system: "Translate one question about public NSF, NIH, or DOE funded awards into structured filters. Return only JSON with agency (all, NSF, NIH, or DOE), program, topic, pi, program_officer, year_start, and year_end. Use empty strings for absent values. Put an explicitly named investigator in pi unless the question clearly identifies that person as a program officer. Do not answer the question, name awards, infer contacts, recommend collaborators, score funding fit, or invent facts. DOE Basic Energy Sciences is agency DOE and program BES. NIH programs use activity codes when stated. Preserve explicit user constraints.",
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
      const plan = translated && typeof translated === "object" && !Array.isArray(translated)
        ? { ...translated }
        : {};
      plan.agency = inferQuestionAgency(plan, question);
      const selectedInstitution = state.selectedInstitution;
      const institutionAliases = [
        ...(selectedInstitution?.aliases || []),
        ...(selectedInstitution?.acronyms || []),
      ];
      const explicitPi = core.explicitInvestigator(question, current.institution, plan.program, institutionAliases);
      if (explicitPi && !clean(plan.pi) && !clean(plan.program_officer)) plan.pi = explicitPi;
      const next = core.sanitizeQuestionPlan(plan, current);
      applyFormState(next);
      state.selectedInstitution = {
        ...selectedInstitution,
        id: current.ror_id,
        canonical_name: current.institution,
      };
      renderQuestionPlan(next);
      await runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true });
    } catch (error) {
      $("ii-question-plan").textContent = `The question could not be translated: ${error?.message || String(error)} Structured filters remain available without AI.`;
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
      const investigator = clean(event.currentTarget.value, 160);
      if (!investigator) return;
      $("ii-pi").value = investigator;
      runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true });
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
    $("k-provider")?.addEventListener("change", () => setTimeout(refreshProvider, 0));
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(location.search);
      const restored = core.stateFromSearch(location.search);
      applyFormState(restored);
      state.payload = null;
      state.sourcePages.clear();
      state.loadingSource = "";
      if (hasSearchState(restored) && !params.get("opportunity")) {
        runSearch({ historyMode: "replace", resolveInstitution: false, offset: restored.offset });
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
      runSearch({ historyMode: "replace", resolveInstitution: false, offset: restored.offset });
    }
  }

  initialize();
})();
