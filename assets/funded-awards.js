(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const catalog = globalThis.GRANT_CATALOG;
  const linksApi = globalThis.FUNDING_AWARD_LINKS;
  const productApi = globalThis.FUNDING_AWARD_PRODUCT;
  const apiConfig = globalThis.FUNDING_AWARD_API_CONFIG;
  const alertsApi = globalThis.FUNDING_ALERTS;
  const INSTITUTION_STORAGE_KEY = "funding-finder.awards.institution.v1";
  const MANAGED_PARAMS = [
    "opportunity", "q", "mode", "agency", "institution", "year_start",
    "year_end", "pi", "program_officer", "offset",
  ];
  const state = {
    selectedRecord: null,
    selectedLookup: null,
    payload: null,
    request: null,
    sequence: 0,
    abortController: null,
  };

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

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function renderAbstract(value) {
    const sourceText = String(value ?? "").replace(/\r\n?/g, "\n").trim();
    const paragraphs = sourceText
      .split(/\n\s*\n+/)
      .map(paragraph => paragraph.replace(/\s+/g, " ").trim())
      .filter(Boolean);
    if (!paragraphs.length) return "<p>Not listed</p>";
    return paragraphs.map(paragraph => `<p>${escapeHtml(paragraph)}</p>`).join("");
  }

  function safeUrl(value, fallback = "") {
    try {
      const url = new URL(clean(value));
      return ["http:", "https:"].includes(url.protocol) ? url.href : fallback;
    } catch {
      return fallback;
    }
  }

  function recordId(record) {
    return clean(record?.opportunity_id || record?.opportunity_number);
  }

  function findOpportunity(id) {
    return (catalog?.opportunities || []).find(record => recordId(record) === clean(id)) || null;
  }

  function setStatus(message, { error = false } = {}) {
    const node = $("award-status");
    node.textContent = message;
    node.classList.toggle("error-text", error);
  }

  function syncPaginationControls() {
    const offset = Number(state.payload?.pagination?.offset || 0);
    $("award-previous").disabled = !state.payload || offset === 0;
    $("award-next").disabled = !state.payload || !productApi.canPageForward(state.payload);
  }

  function setBusy(busy) {
    $("award-results").setAttribute("aria-busy", busy ? "true" : "false");
    $("search-awards").disabled = busy;
    if (busy) {
      $("award-previous").disabled = true;
      $("award-next").disabled = true;
    } else {
      syncPaginationControls();
    }
  }

  function cancelPendingSearch() {
    state.sequence += 1;
    state.abortController?.abort();
    state.abortController = null;
    setBusy(false);
  }

  function clearRenderedResults() {
    state.payload = null;
    syncPaginationControls();
    for (const id of ["award-source-status", "institution-summary", "program-summary", "award-pagination"]) {
      $(id).classList.add("hidden");
    }
    $("award-result-list").innerHTML = "";
  }

  function loadDefaultInstitution() {
    try {
      return clean(globalThis.localStorage?.getItem(INSTITUTION_STORAGE_KEY));
    } catch {
      return "";
    }
  }

  function saveDefaultInstitution() {
    try {
      if ($("remember-institution").checked && clean($("award-institution").value)) {
        globalThis.localStorage?.setItem(INSTITUTION_STORAGE_KEY, clean($("award-institution").value));
      } else {
        globalThis.localStorage?.removeItem(INSTITUTION_STORAGE_KEY);
      }
    } catch {
      // Storage is optional; the current search remains usable.
    }
  }

  function formState() {
    return {
      opportunity: recordId(state.selectedRecord),
      query: clean($("award-query").value),
      mode: $("search-mode").value,
      agency: $("award-agency").value,
      institution: clean($("award-institution").value),
      year_start: $("year-start").value,
      year_end: $("year-end").value,
      pi: "",
      program_officer: "",
      offset: Number.parseInt(new URLSearchParams(location.search).get("offset"), 10) || 0,
    };
  }

  function syncUrl(searchState, mode = "replace") {
    if (!location.protocol.startsWith("http")) return;
    const url = new URL(location.href);
    MANAGED_PARAMS.forEach(key => url.searchParams.delete(key));
    if (searchState.opportunity) url.searchParams.set("opportunity", searchState.opportunity);
    if (searchState.query && !searchState.opportunity) url.searchParams.set("q", searchState.query);
    if (["program", "pi", "program_officer"].includes(searchState.mode) && !searchState.opportunity) {
      url.searchParams.set("mode", searchState.mode);
    }
    if (searchState.agency && searchState.agency !== "all" && !searchState.opportunity) {
      url.searchParams.set("agency", searchState.agency);
    }
    if (searchState.institution) url.searchParams.set("institution", searchState.institution);
    if (searchState.year_start) url.searchParams.set("year_start", searchState.year_start);
    if (searchState.year_end) url.searchParams.set("year_end", searchState.year_end);
    if (searchState.pi) url.searchParams.set("pi", searchState.pi);
    if (searchState.program_officer) url.searchParams.set("program_officer", searchState.program_officer);
    if (Number(searchState.offset) > 0) url.searchParams.set("offset", String(searchState.offset));
    history[mode === "push" ? "pushState" : "replaceState"](null, "", url);
  }

  function hydrateFromUrl() {
    const params = new URLSearchParams(location.search);
    const selectedId = clean(params.get("opportunity"));
    state.selectedRecord = selectedId ? findOpportunity(selectedId) : null;
    state.selectedLookup = state.selectedRecord ? linksApi.lookupForOpportunity(state.selectedRecord) : null;
    const legacyPi = clean(params.get("pi"));
    const legacyProgramOfficer = clean(params.get("program_officer"));
    const query = clean(params.get("q")) || legacyPi || legacyProgramOfficer;
    const requestedMode = clean(params.get("mode"));
    const validModes = ["topic", "program", "pi", "program_officer"];
    const inferredMode = !clean(params.get("q")) && legacyPi
      ? "pi"
      : !clean(params.get("q")) && legacyProgramOfficer
        ? "program_officer"
        : "topic";
    $("award-query").value = query;
    $("search-mode").value = validModes.includes(requestedMode) ? requestedMode : inferredMode;
    $("award-agency").value = ["NSF", "NIH", "DOE"].includes(params.get("agency")) ? params.get("agency") : "all";
    const defaultInstitution = loadDefaultInstitution();
    const urlInstitution = clean(params.get("institution"));
    $("award-institution").value = urlInstitution || defaultInstitution;
    $("remember-institution").checked = Boolean(defaultInstitution && $("award-institution").value === defaultInstitution);
    $("year-start").value = /^\d{4}$/.test(params.get("year_start") || "") ? params.get("year_start") : "";
    $("year-end").value = /^\d{4}$/.test(params.get("year_end") || "") ? params.get("year_end") : "";
    renderSelectedOpportunity();
  }

  function mappingDescription(lookup) {
    if (!lookup) return "No exact historical-award mapping is available for this opportunity. Clear the selection to search awards by topic or program.";
    if (lookup.mapping_basis === "reviewed_parent_program") {
      return `Historical lookup: ${lookup.label}. The current program and reviewed predecessor program-element codes are queried together.`;
    }
    if (lookup.mapping_basis === "exact_nsf_program_element") {
      return `Historical lookup: exact NSF program element ${lookup.criteria.program_codes[0]}.`;
    }
    if (lookup.mapping_basis === "exact_nih_opportunity_number") {
      return `Historical lookup: exact NIH opportunity number ${lookup.criteria.opportunity_number}.`;
    }
    return `Historical lookup: exact DOE Office of Science FOA ${lookup.criteria.opportunity_number}.`;
  }

  function renderSelectedOpportunity() {
    const panel = $("selected-opportunity");
    const standalone = document.querySelector(".standalone-search-fields");
    if (!state.selectedRecord) {
      panel.classList.add("hidden");
      standalone.classList.remove("hidden");
      $("watch-selected-program").classList.add("hidden");
      $("award-results").classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    $("award-results").classList.toggle("hidden", !state.selectedLookup);
    standalone.classList.toggle("hidden", Boolean(state.selectedLookup));
    $("selected-opportunity-heading").textContent = state.selectedRecord.title || "Selected opportunity";
    $("selected-opportunity-meta").textContent = [
      state.selectedRecord.agency || "Agency not listed",
      state.selectedRecord.opportunity_number || recordId(state.selectedRecord),
    ].filter(Boolean).join(" · ");
    $("selected-mapping-note").textContent = mappingDescription(state.selectedLookup);
    const programIdentity = linksApi.programIdentityForOpportunity?.(state.selectedRecord) || null;
    const watchProgram = $("watch-selected-program");
    watchProgram.classList.toggle("hidden", !programIdentity);
    watchProgram.dataset.programId = programIdentity?.id || "";
    watchProgram.dataset.programLabel = programIdentity?.label || "";
    const currentUrl = safeUrl(state.selectedRecord.detail_page || state.selectedRecord.funding_opportunity_url);
    const open = $("open-current-opportunity");
    if (currentUrl) {
      open.href = currentUrl;
      open.classList.remove("hidden");
    } else {
      open.removeAttribute("href");
      open.classList.add("hidden");
    }
  }

  function formatDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(clean(value))) return clean(value) || "Not listed";
    const date = new Date(`${value}T12:00:00Z`);
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
    }).format(date);
  }

  function formatMoney(value) {
    const number = productApi.presentFiniteNumber(value);
    return number !== null
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(number)
      : "Not listed";
  }

  function contactLine(person, source, officialUrl) {
    const name = clean(person?.name) || "Name not listed";
    const role = clean(person?.role) || "Contact";
    const email = clean(person?.email);
    const contactUrl = safeUrl(person?.official_contact_url || officialUrl);
    const identity = `<strong>${escapeHtml(name)}</strong> · ${escapeHtml(role)}`;
    if (email) {
      return `<li>${identity} · <a href="mailto:${escapeAttribute(email)}">${escapeHtml(email)}</a><span class="contact-provenance">Direct ${escapeHtml(source)} source field</span></li>`;
    }
    return `<li>${identity}${contactUrl ? ` · <a href="${escapeAttribute(contactUrl)}" target="_blank" rel="noopener">View contact on official award page ↗</a><span class="contact-provenance">Official ${escapeHtml(source)} record</span>` : " · Email not listed"}</li>`;
  }

  function awardCard(award, position) {
    const officialUrl = safeUrl(award.official_award_url);
    const title = clean(award.title) || "Untitled award";
    const id = clean(award.award_id) || `result-${position}`;
    const investigators = Array.isArray(award.principal_investigators) ? award.principal_investigators : [];
    const programContacts = Array.isArray(award.program_contacts) ? award.program_contacts : [];
    const primaryNames = investigators.map(person => clean(person?.name)).filter(Boolean);
    const institution = clean(award?.institution?.normalized_name || award?.institution?.name) || "Institution not listed";
    const program = clean(award.program_name) || (award.program_codes || []).map(clean).filter(Boolean).join(", ") || "Program not listed";
    const dates = [formatDate(award.project_start), formatDate(award.project_end)].join(" – ");
    const contacts = [...investigators, ...programContacts]
      .map(person => contactLine(person, award.source, officialUrl))
      .join("");
    const awardYear = productApi.awardYear(award.award_year);
    return `<article class="award-card" data-source="${escapeAttribute(award.source)}" data-award-id="${escapeAttribute(id)}" aria-labelledby="award-title-${position}">
      <div class="award-card-topline">
        <span class="badge ${award.source === "NIH" ? "candidate" : award.source === "DOE" ? "review" : "open"}">${escapeHtml(award.source)}</span>
        <span class="opportunity-number">Award ${escapeHtml(id)}</span>
        ${awardYear !== null ? `<span class="listed-date">Award year ${escapeHtml(awardYear)}</span>` : ""}
      </div>
      <h4 id="award-title-${position}">${officialUrl ? `<a href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>` : escapeHtml(title)}</h4>
      <p class="award-people"><strong>${escapeHtml(primaryNames.join(" · ") || "Investigator not listed")}</strong> · ${escapeHtml(institution)}</p>
      <p class="award-program-line">${escapeHtml(award.agency || award.source)} · ${escapeHtml(program)}</p>
      <div class="award-facts">
        <div class="award-fact"><span>Project dates</span><strong>${escapeHtml(dates)}</strong></div>
        <div class="award-fact"><span>Award amount</span><strong>${escapeHtml(formatMoney(award.total_award))}</strong></div>
        <div class="award-fact"><span>Amount basis</span><strong>${escapeHtml(clean(award.award_amount_basis)?.replaceAll("_", " ") || "Not listed")}</strong></div>
      </div>
      <section class="award-abstract" aria-label="Award abstract">
        <h5>Abstract</h5>
        ${renderAbstract(award.abstract)}
      </section>
      ${contacts ? `<section class="award-contacts" aria-label="Public award contacts"><h5>Investigators and program contacts</h5><ul>${contacts}</ul></section>` : ""}
      <div class="award-card-actions">
        ${officialUrl ? `<a class="source-action primary" href="${escapeAttribute(officialUrl)}" target="_blank" rel="noopener">View official award ↗</a>` : ""}
      </div>
    </article>`;
  }

  function renderSourceStatus(payload) {
    const list = $("award-source-status");
    const hasHealthySource = payload.sources.some(source => source.status === "ok");
    list.innerHTML = payload.sources.map(source => {
      if (source.status === "ok") {
        const cache = source.cache === "hit" ? "cached" : "live";
        const abstractWarning = Number(source.health?.abstracts_failed || 0);
        return `<li${abstractWarning ? ' class="source-degraded"' : ""}>${escapeHtml(source.source)} available · ${Number(source.result_count || 0).toLocaleString()} returned · ${cache}${abstractWarning ? ` · ${abstractWarning.toLocaleString()} public ${abstractWarning === 1 ? "abstract" : "abstracts"} unavailable` : ""}</li>`;
      }
      const suffix = hasHealthySource ? " Other sources remain usable." : "";
      return `<li class="source-unavailable" data-status="${escapeAttribute(source.status || "unavailable")}">${escapeHtml(productApi.sourceIssueText(source))}${escapeHtml(suffix)}</li>`;
    }).join("");
    list.classList.toggle("hidden", !payload.sources.length);
  }

  function renderInstitutionSummary(results, searchState) {
    const node = $("institution-summary");
    const summary = productApi.institutionSummary(results, searchState.institution);
    if (!summary) {
      node.classList.add("hidden");
      node.innerHTML = "";
      return;
    }
    const investigators = summary.investigators.slice(0, 12).map(person => (
      `<button class="pi-summary-button" type="button" data-award-pi="${escapeAttribute(person.name)}">${escapeHtml(person.name)} · ${person.projects.toLocaleString()} ${person.projects === 1 ? "project" : "projects"}</button>`
    )).join("");
    node.innerHTML = `<h3 id="institution-summary-heading">${escapeHtml(summary.institution)}</h3>
      <p class="summary-counts"><span><strong>${summary.projects.toLocaleString()}</strong> funded projects in this result page</span><span><strong>${summary.investigators.length.toLocaleString()}</strong> investigators</span></p>
      ${investigators ? `<div class="pi-summary-list" aria-label="Filter by investigator">${investigators}</div>` : ""}`;
    node.classList.remove("hidden");
  }

  function renderProgramSummary(results) {
    const node = $("program-summary");
    if (!results.length) {
      node.classList.add("hidden");
      node.innerHTML = "";
      return;
    }
    const investigators = new Set(results.flatMap(award => (
      (award.principal_investigators || []).map(person => clean(person?.name)).filter(Boolean)
    )));
    const institutions = new Set(results.map(award => clean(award?.institution?.normalized_name || award?.institution?.name)).filter(Boolean));
    const yearRange = productApi.awardYearRange(results) || "Years not listed";
    node.innerHTML = `<h3>Result-page summary</h3><p class="summary-counts"><span><strong>${results.length.toLocaleString()}</strong> funded projects</span><span><strong>${investigators.size.toLocaleString()}</strong> unique investigators</span><span><strong>${institutions.size.toLocaleString()}</strong> institutions</span><span>${escapeHtml(yearRange)}</span></p>`;
    node.classList.remove("hidden");
  }

  function renderResults(payload, searchState) {
    state.payload = payload;
    renderSourceStatus(payload);
    renderInstitutionSummary(payload.results, searchState);
    renderProgramSummary(payload.results);
    const resultList = $("award-result-list");
    if (!payload.results.length) {
      resultList.innerHTML = `<div class="award-empty"><h3>No funded projects were returned.</h3><p>Try a shorter topic query, another source, or a wider year range. An exact new program may not have reported awards yet.</p></div>`;
    } else {
      let position = Number(payload.pagination?.offset || 0) + 1;
      resultList.innerHTML = payload.request.sources.map(source => {
        const records = payload.results.filter(award => award.source === source);
        if (!records.length) return "";
        const cards = records.map(award => awardCard(award, position++)).join("");
        return `<section class="award-source-section" aria-labelledby="source-${source.toLowerCase()}">
          <div class="award-source-heading"><h3 id="source-${source.toLowerCase()}">${escapeHtml(source)} awards</h3><p>Source-native order; no cross-source reranking</p></div>
          <div class="award-card-list">${cards}</div>
        </section>`;
      }).join("");
    }
    const pagination = $("award-pagination");
    const offset = Number(payload.pagination?.offset || 0);
    const canNext = productApi.canPageForward(payload);
    pagination.classList.toggle("hidden", offset === 0 && !canNext);
    syncPaginationControls();
    $("award-page-label").textContent = productApi.paginationLabel(payload);
  }

  async function search({ historyMode = "replace", offset = null, focusResults = false, scrollResults = false } = {}) {
    const searchState = formState();
    if (offset !== null) searchState.offset = Math.max(0, Math.min(1_000, offset));
    let requestBody;
    try {
      if (state.selectedRecord && !state.selectedLookup) throw new Error(mappingDescription(null));
      requestBody = productApi.buildRequest(searchState, state.selectedLookup, apiConfig.maxResultsPerSource);
    } catch (error) {
      setStatus(error.message, { error: true });
      return;
    }
    saveDefaultInstitution();
    syncUrl(searchState, historyMode);
    state.request = requestBody;
    state.abortController?.abort();
    const controller = new AbortController();
    state.abortController = controller;
    const sequence = ++state.sequence;
    setBusy(true);
    setStatus(`Searching ${requestBody.sources.join(" and ")} public award records…`);
    const timeout = setTimeout(() => controller.abort(), apiConfig.timeoutMs);
    try {
      const response = await fetch(apiConfig.searchUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        credentials: "omit",
        referrerPolicy: "origin",
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      if (sequence !== state.sequence) return;
      if (!productApi.validatePayload(payload)) {
        const error = new Error(productApi.serviceIssueText(payload) || "The award service returned an invalid response. Retry later.");
        error.code = productApi.boundedErrorCode(payload) || "invalid_response";
        throw error;
      }
      renderResults(payload, searchState);
      const issues = payload.sources.filter(source => source.status !== "ok").map(productApi.sourceIssueText);
      const suffix = issues.length ? ` ${issues.join(" ")}` : "";
      setStatus(`${payload.results.length.toLocaleString()} funded projects returned.${suffix}`, { error: !response.ok && !payload.results.length });
      if (focusResults) $("award-results-heading").focus({ preventScroll: true });
      if (scrollResults) $("award-results-heading").scrollIntoView({ block: "start" });
    } catch (error) {
      if (sequence !== state.sequence || error?.name === "AbortError" && controller.signal.aborted && state.abortController !== controller) return;
      $("award-source-status").classList.add("hidden");
      $("institution-summary").classList.add("hidden");
      $("program-summary").classList.add("hidden");
      $("award-pagination").classList.add("hidden");
      const timedOut = error?.name === "AbortError";
      const invalidRequest = error?.code === "invalid_request";
      const rateLimited = ["rate_limited", "source_rate_limited"].includes(error?.code);
      const title = timedOut
        ? "Award search timed out."
        : invalidRequest
          ? "Check the award search filters."
          : rateLimited
            ? "Award search is rate limited."
            : error?.code === "invalid_response"
              ? "The award service returned an invalid response."
              : "Award search is temporarily unavailable.";
      const detail = timedOut
        ? "Retry later. Funding Finder and Team Match remain available."
        : error?.message || "The award service could not be reached. Retry later.";
      $("award-result-list").innerHTML = `<div class="award-empty"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(detail)}</p></div>`;
      setStatus(timedOut ? "The award search timed out. Retry later." : detail, { error: true });
    } finally {
      clearTimeout(timeout);
      if (sequence === state.sequence) {
        setBusy(false);
        if (state.abortController === controller) state.abortController = null;
      }
    }
  }

  function clearSelection() {
    cancelPendingSearch();
    state.selectedRecord = null;
    state.selectedLookup = null;
    renderSelectedOpportunity();
    const searchState = formState();
    searchState.offset = 0;
    syncUrl(searchState, "push");
    clearRenderedResults();
    $("award-results").classList.add("hidden");
    setStatus("Selection cleared. Search by research topic or program.");
  }

  function clearSearch() {
    cancelPendingSearch();
    state.selectedRecord = null;
    state.selectedLookup = null;
    $("award-search-form").reset();
    $("search-mode").value = "topic";
    $("award-agency").value = "all";
    const defaultInstitution = loadDefaultInstitution();
    $("award-institution").value = defaultInstitution;
    $("remember-institution").checked = Boolean(defaultInstitution);
    renderSelectedOpportunity();
    syncUrl(formState(), "push");
    clearRenderedResults();
    setStatus("Choose a topic, program, or eligible current opportunity to begin.");
  }

  function bindEvents() {
    $("award-search-form").addEventListener("submit", event => {
      event.preventDefault();
      search({ historyMode: "push", offset: 0, focusResults: true });
    });
    $("clear-opportunity").addEventListener("click", clearSelection);
    $("watch-selected-program").addEventListener("click", event => {
      const identity = linksApi.programIdentityById?.(event.currentTarget.dataset.programId);
      if (!identity || !alertsApi?.open) return;
      alertsApi.open({
        type: "program",
        definition: { program_id: identity.id },
        summary: `${identity.label} · controlled NSF program identity`,
        focus: event.currentTarget,
      });
    });
    $("clear-award-search").addEventListener("click", clearSearch);
    $("award-previous").addEventListener("click", () => {
      const pageSize = Number(state.request?.limit || apiConfig.maxResultsPerSource);
      const offset = Math.max(0, Number(state.payload?.pagination?.offset || 0) - pageSize);
      search({ historyMode: "push", offset, focusResults: true, scrollResults: true });
    });
    $("award-next").addEventListener("click", () => {
      const pageSize = Number(state.request?.limit || apiConfig.maxResultsPerSource);
      const offset = Number(state.payload?.pagination?.offset || 0) + pageSize;
      search({ historyMode: "push", offset, focusResults: true, scrollResults: true });
    });
    $("institution-summary").addEventListener("click", event => {
      const button = event.target.closest("[data-award-pi]");
      if (!button) return;
      const investigator = clean(button.getAttribute("data-award-pi"));
      const source = state.selectedLookup?.source || $("award-agency").value;
      const institution = clean($("award-institution").value);
      const yearStart = $("year-start").value;
      const yearEnd = $("year-end").value;
      cancelPendingSearch();
      state.selectedRecord = null;
      state.selectedLookup = null;
      renderSelectedOpportunity();
      clearRenderedResults();
      $("award-results").classList.add("hidden");
      $("ii-institution").value = institution;
      $("ii-institution").dispatchEvent(new Event("input", { bubbles: true }));
      $("ii-agency").value = ["NSF", "NIH", "DOE"].includes(source) ? source : "all";
      $("ii-program").value = "";
      $("ii-topic").value = "";
      $("ii-pi").value = investigator;
      $("ii-program-officer").value = "";
      $("ii-year-start").value = yearStart;
      $("ii-year-end").value = yearEnd;
      $("ii-form").requestSubmit();
    });
    window.addEventListener("popstate", () => {
      cancelPendingSearch();
      hydrateFromUrl();
      const params = new URLSearchParams(location.search);
      if (hasUrlSearch(params)) {
        search({ historyMode: "replace", offset: Number(params.get("offset") || 0) });
      } else {
        clearRenderedResults();
        setStatus("Choose a topic, program, or eligible current opportunity to begin.");
      }
    });
  }

  function hasUrlSearch(params) {
    return Boolean(state.selectedRecord && params.get("opportunity"));
  }

  function initialize() {
    try {
      if (!catalog?.opportunities || !linksApi || !productApi || !apiConfig?.searchUrl) {
        throw new Error("The funded-awards application could not load its required data.");
      }
      hydrateFromUrl();
      bindEvents();
      const params = new URLSearchParams(location.search);
      if (hasUrlSearch(params)) {
        search({ historyMode: "replace", offset: Number(params.get("offset") || 0) });
      }
    } catch (error) {
      setStatus(error?.message || "The funded-awards application could not start.", { error: true });
    }
  }

  initialize();
})();
