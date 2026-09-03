(function () {
  "use strict";
  var intake = globalThis.FUNDING_RESEARCHER_INTAKE;
  var directory = globalThis.RESEARCHER_DIRECTORY;
  var form = document.getElementById("researcher-request-form");
  var status = document.getElementById("request-status");
  var fallback = document.getElementById("download-request");
  var currentSubmission = null;
  var idempotencyKey = "";
  var researcherCandidates = [];
  var activeResearcherOption = -1;

  function element(id) { return document.getElementById(id); }
  function selectedType() { return form.elements.request_type.value; }
  function setStatus(message, kind) {
    status.textContent = message || "";
    status.className = "form-status" + (kind ? " " + kind : "");
  }
  function activeClaims(profile) {
    return (profile.claims || []).filter(function (claim) { return claim.status === "active"; });
  }
  function findResearcher(id) {
    return (directory.researchers || []).find(function (profile) { return profile.id === id; }) || null;
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
  function fillProfile(profile) {
    element("display-name").value = profile ? profile.name : "";
    element("home-unit").value = profile ? profile.home_unit : "";
    element("orcid-id").value = profile ? profile.orcid_id || "" : "";
    element("research-summary").value = profile ? profile.research_summary || "" : "";
    element("research-claims").value = profile ? activeClaims(profile).map(function (claim) { return claim.label; }).join("\n") : "";
    element("source-urls").value = profile ? (profile.source_urls || []).join("\n") : "";
  }
  function updateType() {
    var correction = selectedType() === "profile_correction";
    element("existing-wrap").classList.toggle("hidden", !correction);
    element("relationship-wrap").classList.toggle("hidden", correction);
    element("researcher-search").required = correction;
    if (!correction) {
      element("existing-researcher").value = "";
      element("researcher-search").value = "";
      fillProfile(null);
    } else if (element("existing-researcher").value) {
      fillProfile(findResearcher(element("existing-researcher").value));
    }
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
      setStatus("Request received. The currently published profile remains active until approval and deployment succeed.", "success");
      idempotencyKey = "";
    } catch (error) {
      setStatus(error.message + " Your form is still here; you may retry or download the bounded request.", "error");
      fallback.hidden = false;
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  if (!intake || !directory || !form) return;
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
  fallback.addEventListener("click", function () { if (currentSubmission) intake.downloadFallback(currentSubmission); });
  updateType();
})();
