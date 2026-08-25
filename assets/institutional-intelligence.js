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
  };

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
    if (busy) {
      $("ii-previous").disabled = true;
      $("ii-next").disabled = true;
    } else {
      syncPaginationControls();
    }
  }

  function selectedLocation(institution) {
    return [institution?.location?.city, institution?.location?.country].filter(Boolean).join(", ");
  }

  function setSelectedInstitution(institution, { announce = true } = {}) {
    state.selectedInstitution = institution ? {
      id: clean(institution.id, 100),
      canonical_name: clean(institution.canonical_name, 300),
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
    const number = Number(value);
    return Number.isFinite(number)
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
    const year = Number(award?.award_year) || "Year not listed";
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
        ? `${source.source} available · ${source.result_count || 0} returned`
        : status === "unsupported"
          ? `${source.source} does not support this filter combination`
          : `${source.source} temporarily unavailable`;
      return `<li data-status="${escapeAttribute(status)}">${escapeHtml(label)}</li>`;
    }).join("");
    list.classList.toggle("hidden", !values.length);
  }

  function syncPaginationControls() {
    const offset = Number(state.payload?.pagination?.offset || 0);
    $("ii-previous").disabled = !state.payload || offset === 0;
    $("ii-next").disabled = !state.payload || !awardProduct.canPageForward(state.payload);
  }

  function renderAggregate(payload) {
    const aggregate = core.aggregateAwards(payload.results);
    const institution = clean(state.selectedInstitution?.canonical_name || $("ii-institution").value, 300);
    $("ii-output").classList.remove("hidden");
    $("ii-output-heading").textContent = institution ? `${institution} funded projects` : "Funded award summary";
    const hasMore = (payload.sources || []).some(source => source.status === "ok" && source.has_more === true);
    $("ii-result-scope").textContent = `Summaries cover ${aggregate.project_count} normalized project${aggregate.project_count === 1 ? "" : "s"} on this source-native result page${hasMore ? "; additional source results exist" : ""}.`;
    const years = aggregate.year_start
      ? aggregate.year_start === aggregate.year_end ? String(aggregate.year_start) : `${aggregate.year_start}–${aggregate.year_end}`
      : "Not listed";
    $("ii-metrics").innerHTML = [
      [aggregate.project_count, "Projects returned"],
      [aggregate.investigator_count, "Unique investigators"],
      [aggregate.program_count, "Program labels"],
      [years, "Award years"],
    ].map(([value, label]) => `<div class="ii-metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
    $("ii-investigators").innerHTML = aggregate.investigators.length
      ? aggregate.investigators.map(person => `<button type="button" data-ii-pi="${escapeAttribute(person.name)}">${escapeHtml(person.name)} · ${person.projects}</button>`).join("")
      : "<p>No structured investigator names were returned.</p>";
    $("ii-programs").innerHTML = aggregate.programs.length
      ? aggregate.programs.map(program => `<button type="button" data-ii-program="${escapeAttribute(program.query)}" data-ii-program-source="${escapeAttribute(program.source)}">${escapeHtml(program.label)} · ${program.projects}</button>`).join("")
      : "<p>No structured program labels were returned.</p>";
    $("ii-awards").innerHTML = aggregate.awards.length
      ? aggregate.awards.map(awardCard).join("")
      : "<p>No normalized public award records matched these filters.</p>";
    renderSourceStatus(payload.sources);
    const offset = Number(payload.pagination?.offset || 0);
    const canNext = awardProduct.canPageForward(payload);
    $("ii-pagination").classList.toggle("hidden", offset === 0 && !canNext);
    $("ii-page-label").textContent = aggregate.project_count
      ? `Results ${offset + 1}–${offset + aggregate.project_count}`
      : "No results on this page";
    syncPaginationControls();
    return aggregate;
  }

  async function runSearch({ historyMode = "replace", resolveInstitution = true, offset = null, focusResults = false, scrollResults = false } = {}) {
    const sequence = ++state.searchSequence;
    state.searchController?.abort();
    state.searchController = new AbortController();
    setBusy(true);
    setStatus("Searching normalized public NSF, NIH, and DOE award records…");
    try {
      if (resolveInstitution) await resolveTypedInstitution();
      const current = formState();
      if (offset !== null) current.offset = Math.max(0, Math.min(1_000, Number(offset) || 0));
      const requestBody = core.buildAwardRequest(current, 10);
      syncUrl(current, historyMode);
      const timer = setTimeout(() => state.searchController?.abort(), apiConfig.timeoutMs);
      let response;
      try {
        response = await fetch(apiConfig.searchUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          credentials: "omit",
          body: JSON.stringify(requestBody),
          signal: state.searchController.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      const payload = await response.json().catch(() => null);
      if (sequence !== state.searchSequence) return;
      if (!payload || !awardProduct.validatePayload(payload)) throw new Error("The award service returned an invalid response.");
      if (!response.ok && !payload.results.length) {
        state.payload = payload;
        renderAggregate(payload);
        throw new Error("The selected award sources are temporarily unavailable or do not support this filter combination.");
      }
      state.payload = payload;
      const aggregate = renderAggregate(payload);
      const failed = (payload.sources || []).filter(source => source.status !== "ok");
      setStatus(failed.length
        ? `${aggregate.project_count} public project${aggregate.project_count === 1 ? "" : "s"} returned from available sources. ${failed.map(source => source.source).join(", ")} did not complete.`
        : `${aggregate.project_count} public project${aggregate.project_count === 1 ? "" : "s"} returned. Use investigator or program selections to drill into the official records.`);
      if (focusResults) $("ii-output-heading").focus({ preventScroll: true });
      if (scrollResults) $("ii-output-heading").scrollIntoView({ block: "start" });
    } catch (error) {
      if (error?.name === "AbortError" || sequence !== state.searchSequence) return;
      setStatus(error?.message || "Funded award search could not be completed.", true);
    } finally {
      if (sequence === state.searchSequence) setBusy(false);
    }
  }

  function clearSearch({ historyMode = "push" } = {}) {
    state.searchSequence += 1;
    state.searchController?.abort();
    state.selectedInstitution = null;
    state.payload = null;
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
        system: "Translate one question about public NSF, NIH, or DOE funded awards into structured filters. Return only JSON with agency (all, NSF, NIH, or DOE), program, topic, pi, program_officer, year_start, and year_end. Use empty strings for absent values. Do not answer the question, name awards, infer contacts, recommend collaborators, score funding fit, or invent facts. DOE Basic Energy Sciences is agency DOE and program BES. NIH programs use activity codes when stated. Preserve explicit user constraints.",
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
      const next = core.sanitizeQuestionPlan(plan, current);
      applyFormState(next);
      state.selectedInstitution = {
        ...state.selectedInstitution,
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
    $("ii-output").addEventListener("click", event => {
      const investigator = event.target.closest("[data-ii-pi]");
      if (investigator) {
        $("ii-pi").value = investigator.dataset.iiPi;
        runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true });
        return;
      }
      const program = event.target.closest("[data-ii-program]");
      if (program) {
        $("ii-agency").value = program.dataset.iiProgramSource;
        $("ii-program").value = program.dataset.iiProgram;
        runSearch({ historyMode: "push", resolveInstitution: false, offset: 0, focusResults: true });
      }
    });
    $("ii-previous").addEventListener("click", () => {
      const pageSize = Number(state.payload?.request?.limit || 10);
      const offset = Math.max(0, Number(state.payload?.pagination?.offset || 0) - pageSize);
      runSearch({ historyMode: "push", resolveInstitution: false, offset, focusResults: true, scrollResults: true });
    });
    $("ii-next").addEventListener("click", () => {
      const pageSize = Number(state.payload?.request?.limit || 10);
      const offset = Number(state.payload?.pagination?.offset || 0) + pageSize;
      runSearch({ historyMode: "push", resolveInstitution: false, offset, focusResults: true, scrollResults: true });
    });
    $("ii-provider").addEventListener("change", () => refreshProvider({ preferMain: false }));
    $("ii-save-key").addEventListener("click", saveSharedKey);
    $("ii-ask-button").addEventListener("click", askQuestion);
    $("k-provider")?.addEventListener("change", () => setTimeout(refreshProvider, 0));
    window.addEventListener("popstate", () => {
      const restored = core.stateFromSearch(location.search);
      applyFormState(restored);
      state.payload = null;
      if (hasSearchState(restored)) runSearch({ historyMode: "replace", resolveInstitution: false, offset: restored.offset });
      else {
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
