(function () {
  "use strict";
  var intake = globalThis.FUNDING_RESEARCHER_INTAKE;
  var directory = globalThis.RESEARCHER_DIRECTORY;
  var orcidApi = globalThis.FUNDING_ORCID;
  var teamApi = globalThis.FUNDING_TEAM_RESEARCHERS;
  var form = document.getElementById("researcher-request-form");
  var status = document.getElementById("request-status");
  var fallback = document.getElementById("download-request");
  var currentSubmission = null;
  var idempotencyKey = "";
  var researcherCandidates = [];
  var activeResearcherOption = -1;
  var activeRequestType = "";
  var modeDrafts = {
    profile_correction: null,
    new_researcher_nomination: null,
  };
  var draftFieldIds = [
    "researcher-search", "existing-researcher", "display-name", "home-unit", "orcid-id",
    "relationship-note", "research-summary", "research-claims", "source-urls", "contact-email",
    "submitter-note", "review-consent",
  ];

  function element(id) { return document.getElementById(id); }
  function selectedType() { return form.elements.request_type.value; }
  function setStatus(message, kind) {
    status.textContent = message || "";
    status.className = "form-status" + (kind ? " " + kind : "");
  }
  function activeClaims(profile) {
    return (profile.claims || []).filter(function (claim) { return claim.status === "active"; });
  }
  function normalized(value) {
    return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }
  function researcherSortName(profile) {
    if (profile.sort_name) return profile.sort_name;
    var parts = String(profile.name || "").trim().split(/\s+/).filter(Boolean);
    var suffix = parts.length > 1 && /^(?:jr\.?|sr\.?|ii|iii|iv)$/i.test(parts[parts.length - 1]) ? parts.pop() : "";
    var family = parts.pop() || "";
    return family + ", " + parts.join(" ") + (suffix ? " " + suffix : "");
  }
  function eligibleResearchers() {
    return (directory.researchers || []).filter(function (profile) {
      return profile.status === "active" && profile.pool_visibility !== "hidden";
    }).slice().sort(function (left, right) {
      return researcherSortName(left).localeCompare(researcherSortName(right), undefined, { sensitivity: "base" }) || left.id.localeCompare(right.id);
    });
  }
  function hideResearcherOptions() {
    element("researcher-options").classList.add("hidden");
    element("researcher-search").setAttribute("aria-expanded", "false");
    element("researcher-search").removeAttribute("aria-activedescendant");
    activeResearcherOption = -1;
  }
  function updateActiveResearcherOption(index) {
    var buttons = Array.from(element("researcher-options").querySelectorAll("[role='option']"));
    if (!buttons.length) return;
    activeResearcherOption = Math.max(0, Math.min(buttons.length - 1, index));
    buttons.forEach(function (button, buttonIndex) {
      button.setAttribute("aria-selected", buttonIndex === activeResearcherOption ? "true" : "false");
    });
    var active = buttons[activeResearcherOption];
    element("researcher-search").setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }
  function matchingResearchers(query) {
    var terms = normalized(query).split(" ").filter(Boolean);
    return eligibleResearchers().filter(function (profile) {
      if (!terms.length) return true;
      var searchable = normalized([
        profile.name, researcherSortName(profile), profile.home_unit,
      ].concat(profile.aliases || []).join(" "));
      return terms.every(function (term) { return searchable.includes(term); });
    }).slice(0, 12);
  }
  function renderResearcherOptions(query) {
    activeResearcherOption = -1;
    element("researcher-search").removeAttribute("aria-activedescendant");
    researcherCandidates = matchingResearchers(query);
    var list = element("researcher-options");
    list.textContent = "";
    researcherCandidates.forEach(function (profile, index) {
      var option = document.createElement("button");
      option.id = "researcher-option-" + index;
      option.type = "button";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      option.dataset.researcherIndex = String(index);
      var name = document.createElement("strong");
      name.textContent = profile.name;
      var detail = document.createElement("small");
      detail.textContent = profile.home_unit;
      option.appendChild(name);
      option.appendChild(detail);
      list.appendChild(option);
    });
    if (!researcherCandidates.length) {
      hideResearcherOptions();
      element("researcher-search-status").textContent = "No matching published researcher was found.";
      return;
    }
    list.classList.remove("hidden");
    element("researcher-search").setAttribute("aria-expanded", "true");
    element("researcher-search-status").textContent = normalized(query)
      ? researcherCandidates.length + " matching researcher" + (researcherCandidates.length === 1 ? "" : "s") + ", ordered by last name."
      : "Showing the first 12 researchers by last name. Type to search the full directory.";
  }
  function fillProfile(profile) {
    element("display-name").value = profile ? profile.name : "";
    element("home-unit").value = profile ? profile.home_unit : "";
    element("orcid-id").value = profile ? profile.orcid_id || "" : "";
    if (orcidApi) element("orcid-id").value = orcidApi.formatInput(element("orcid-id").value);
    element("research-summary").value = profile ? profile.research_summary || "" : "";
    element("research-claims").value = profile ? activeClaims(profile).map(function (claim) { return claim.label; }).join("\n") : "";
    element("source-urls").value = profile ? (profile.source_urls || []).join("\n") : "";
  }
  function selectResearcher(profile) {
    if (!profile) return;
    element("existing-researcher").value = profile.id;
    element("researcher-search").value = profile.name;
    fillProfile(profile);
    element("researcher-search-status").textContent = "Selected " + profile.name + " · " + profile.home_unit + ".";
    hideResearcherOptions();
    idempotencyKey = "";
    fallback.hidden = true;
    setStatus("", "");
  }
  function captureDraft() {
    var draft = {};
    draftFieldIds.forEach(function (id) {
      var field = element(id);
      draft[id] = field.type === "checkbox" ? field.checked : field.value;
    });
    return draft;
  }
  function blankDraft() {
    var draft = {};
    draftFieldIds.forEach(function (id) { draft[id] = id === "review-consent" ? false : ""; });
    return draft;
  }
  function restoreDraft(draft) {
    draftFieldIds.forEach(function (id) {
      var field = element(id);
      var value = draft && Object.prototype.hasOwnProperty.call(draft, id) ? draft[id] : (id === "review-consent" ? false : "");
      if (field.type === "checkbox") field.checked = Boolean(value);
      else field.value = value;
    });
    if (orcidApi) element("orcid-id").value = orcidApi.formatInput(element("orcid-id").value);
  }
  function resetActiveDraft() {
    modeDrafts[selectedType()] = null;
    restoreDraft(blankDraft());
    element("researcher-search-status").textContent = "Search the published directory by name or department. Results are ordered by last name.";
    renderDuplicates();
  }
  function updateType() {
    var nextType = selectedType();
    if (activeRequestType && activeRequestType !== nextType) modeDrafts[activeRequestType] = captureDraft();
    activeRequestType = nextType;
    var correction = nextType === "profile_correction";
    element("existing-wrap").classList.toggle("hidden", !correction);
    element("relationship-wrap").classList.toggle("hidden", correction);
    element("local-save-wrap").hidden = correction;
    element("researcher-search").required = correction;
    restoreDraft(modeDrafts[nextType] || blankDraft());
    hideResearcherOptions();
    idempotencyKey = "";
    fallback.hidden = true;
    setStatus("", "");
  }
  function inputValue(id) { return element(id).value; }
  function makeSubmission() {
    if (!idempotencyKey) idempotencyKey = intake.createIdempotencyKey();
    return intake.buildSubmission({
      submissionType: selectedType(), sourceSurface: "faculty_interests",
      researcherId: inputValue("existing-researcher"),
      baseRegistryGeneration: directory.registry_generation,
      displayName: inputValue("display-name"), homeUnit: inputValue("home-unit"),
      orcidId: inputValue("orcid-id"), researchSummary: inputValue("research-summary"),
      claims: inputValue("research-claims"), sourceUrls: inputValue("source-urls"),
      relationshipNote: inputValue("relationship-note"), contactEmail: inputValue("contact-email"),
      note: inputValue("submitter-note"), idempotencyKey: idempotencyKey,
      submittedForAdminReview: element("review-consent").checked,
    });
  }
  function renderDuplicates() {
    var warning = element("duplicate-warning");
    if (selectedType() !== "new_researcher_nomination") { warning.hidden = true; return; }
    var sources = [];
    try { sources = intake.normalizeUrls(inputValue("source-urls")); } catch (_error) {}
    var duplicates = intake.findPossibleDuplicates(directory, {
      display_name: inputValue("display-name"), orcid_id: inputValue("orcid-id"), source_urls: sources,
    });
    warning.hidden = !duplicates.length;
    warning.textContent = duplicates.length
      ? "Possible existing profile: " + duplicates.slice(0, 3).map(function (item) {
          return item.researcher.name + " (" + item.reasons.join(", ") + ")";
        }).join("; ") + ". Administrators will review identity; nothing is merged automatically."
      : "";
  }
  function safeStorage() {
    try { return globalThis.localStorage; }
    catch (_error) { return null; }
  }
  function safeHandoffStorage() {
    try { return globalThis.sessionStorage; }
    catch (_error) { return null; }
  }
  function addLocally() {
    if (!teamApi || !orcidApi) {
      setStatus("Browser-only Team Match profiles are unavailable because a helper did not load.", "error");
      return;
    }
    var name = inputValue("display-name").replace(/\s+/g, " ").trim();
    var keywords = teamApi.parseKeywords(inputValue("research-claims"), 50);
    var rawOrcid = inputValue("orcid-id").trim();
    var orcidId = rawOrcid ? orcidApi.normalizeId(rawOrcid) : "";
    if (name.length < 2) {
      setStatus("Enter the researcher's name before adding this profile locally.", "error");
      element("display-name").focus();
      return;
    }
    if (keywords.length < teamApi.MIN_KEYWORDS || keywords.length > teamApi.MAX_KEYWORDS) {
      setStatus("Add three to eight distinct research interests for Team Match; about five works best.", "error");
      element("research-claims").focus();
      return;
    }
    if (rawOrcid && !orcidId) {
      setStatus("Enter a valid ORCID, including all 16 characters, or leave it blank.", "error");
      element("orcid-id").focus();
      return;
    }
    var storage = safeStorage();
    var loaded = teamApi.load(storage);
    if (!loaded.available) {
      setStatus("Browser storage is unavailable, so this researcher cannot be carried into Team Match.", "error");
      return;
    }
    var duplicate = loaded.profiles.find(function (profile) {
      return profile.name.toLowerCase() === name.toLowerCase() || (orcidId && profile.orcid_id === orcidId);
    });
    if (duplicate) {
      setStatus(duplicate.name + " is already stored in this browser.", "error");
      return;
    }
    if (loaded.profiles.length >= teamApi.MAX_EXTERNAL) {
      setStatus("You can store up to four browser-only researchers. Remove one in Team Match before adding another.", "error");
      return;
    }
    var savedId = teamApi.createId(name, loaded.profiles);
    var profile = {
      id: savedId, registry_id: "", name: name, keywords: keywords,
      orcid_id: orcidId, orcid_name: "", orcid_text: "", orcid_work_count: 0,
      orcid_total_work_count: 0, orcid_source: "", orcid_updated_at: "",
    };
    var result = teamApi.save(storage, loaded.profiles.concat(profile));
    if (!result.saved) {
      setStatus(result.error || "This researcher could not be stored in the browser.", "error");
      return;
    }
    resetActiveDraft();
    var returnParams = new URLSearchParams(location.search);
    if (returnParams.get("return") === "team_match") {
      var expectedHandoffToken = returnParams.get("handoff") || "";
      var handoff = teamApi.completeHandoff(safeHandoffStorage(), savedId, expectedHandoffToken);
      if (!handoff.saved) {
        setStatus("This researcher was stored in this browser, but the team handoff is unavailable in this tab. Open Team Match to add the saved researcher.", "success");
        return;
      }
      location.assign("./team_match.html?handoff=" + encodeURIComponent(handoff.handoff.token));
      return;
    }
    setStatus(name + " was stored only in this browser for Team Match. It was not submitted for catalog review.", "success");
  }
  async function submitRequest(event) {
    event.preventDefault();
    fallback.hidden = true;
    try { currentSubmission = makeSubmission(); }
    catch (error) { setStatus(error.message, "error"); return; }
    var button = element("submit-request");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    setStatus("Sending the request for administrator review…", "");
    try {
      var receipt = await intake.submit(currentSubmission);
      element("receipt-id").textContent = receipt.submission_id;
      element("receipt-link").href = receipt.status_url;
      element("receipt").hidden = false;
      modeDrafts[selectedType()] = null;
      resetActiveDraft();
      setStatus("Request received. The currently published profile remains active until approval and deployment succeed.", "success");
      idempotencyKey = "";
      currentSubmission = null;
    } catch (error) {
      setStatus(error.message + " Your form is still here; you may retry or download the bounded request.", "error");
      fallback.hidden = false;
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  if (!intake || !directory || !form) return;
  var query = new URLSearchParams(location.search);
  if (query.get("mode") === "add") form.elements.request_type.value = "new_researcher_nomination";
  if (orcidApi) orcidApi.bindInput(element("orcid-id"));
  form.addEventListener("change", function (event) {
    if (event.target.name === "request_type") updateType();
    renderDuplicates();
  });
  element("researcher-search").addEventListener("focus", function () {
    if (selectedType() === "profile_correction") renderResearcherOptions(this.value);
  });
  element("researcher-search").addEventListener("input", function () {
    element("existing-researcher").value = "";
    idempotencyKey = "";
    fallback.hidden = true;
    renderResearcherOptions(this.value);
  });
  element("researcher-search").addEventListener("keydown", function (event) {
    if (element("researcher-options").classList.contains("hidden")) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      updateActiveResearcherOption(activeResearcherOption + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      updateActiveResearcherOption(activeResearcherOption < 0 ? researcherCandidates.length - 1 : activeResearcherOption - 1);
    } else if (event.key === "Enter" && activeResearcherOption >= 0) {
      event.preventDefault();
      selectResearcher(researcherCandidates[activeResearcherOption]);
    } else if (event.key === "Escape") {
      hideResearcherOptions();
    }
  });
  element("researcher-search").addEventListener("blur", function () { setTimeout(hideResearcherOptions, 120); });
  element("researcher-options").addEventListener("mousedown", function (event) { event.preventDefault(); });
  element("researcher-options").addEventListener("click", function (event) {
    var option = event.target.closest("[data-researcher-index]");
    if (!option) return;
    selectResearcher(researcherCandidates[Number(option.dataset.researcherIndex)]);
    element("researcher-search").focus();
  });
  ["display-name", "orcid-id", "source-urls"].forEach(function (id) {
    element(id).addEventListener("input", renderDuplicates);
  });
  form.addEventListener("submit", submitRequest);
  element("add-locally").addEventListener("click", addLocally);
  fallback.addEventListener("click", function () { if (currentSubmission) intake.downloadFallback(currentSubmission); });
  updateType();
})();
