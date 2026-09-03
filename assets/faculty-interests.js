(function () {
  "use strict";
  var intake = globalThis.FUNDING_RESEARCHER_INTAKE;
  var directory = globalThis.RESEARCHER_DIRECTORY;
  var form = document.getElementById("researcher-request-form");
  var status = document.getElementById("request-status");
  var fallback = document.getElementById("download-request");
  var currentSubmission = null;
  var idempotencyKey = "";

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
  function renderResearcherOptions() {
    var select = element("existing-researcher");
    (directory.researchers || []).filter(function (profile) {
      return profile.status === "active" && profile.pool_visibility !== "hidden";
    }).slice().sort(function (left, right) { return left.name.localeCompare(right.name); }).forEach(function (profile) {
      var option = document.createElement("option");
      option.value = profile.id;
      option.textContent = profile.name + " — " + profile.home_unit;
      select.appendChild(option);
    });
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
    element("existing-researcher").required = correction;
    if (!correction) {
      element("existing-researcher").value = "";
      fillProfile(null);
    } else if (element("existing-researcher").value) {
      fillProfile(findResearcher(element("existing-researcher").value));
    }
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
  renderResearcherOptions();
  form.addEventListener("change", function (event) {
    if (event.target.name === "request_type") updateType();
    if (event.target.id === "existing-researcher") fillProfile(findResearcher(event.target.value));
    renderDuplicates();
  });
  ["display-name", "orcid-id", "source-urls"].forEach(function (id) {
    element(id).addEventListener("input", renderDuplicates);
  });
  form.addEventListener("submit", submitRequest);
  fallback.addEventListener("click", function () { if (currentSubmission) intake.downloadFallback(currentSubmission); });
  updateType();
})();
