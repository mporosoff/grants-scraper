(function (global) {
  "use strict";

  var API = global.HajimFaculty;
  var openPanel = null;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function safeId(value) {
    return String(value || "").replace(/[^a-z0-9_-]+/gi, "-");
  }

  function catalog() {
    return global.GRANT_CATALOG || null;
  }

  function panelIsOwned(current) {
    if (!current || !current.trigger || !current.panel ||
        !current.trigger.isConnected || !current.panel.isConnected) return false;
    var triggerCard = current.trigger.closest(".result-card");
    var panelCard = current.panel.closest(".result-card");
    return Boolean(triggerCard && triggerCard === panelCard &&
      triggerCard.contains(current.trigger) && triggerCard.contains(current.panel));
  }

  function closeCurrent(options) {
    options = options || {};
    if (!openPanel) return;
    var trigger = openPanel.trigger;
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-controls");
      if (options.restoreFocus && trigger.isConnected) trigger.focus();
    }
    if (openPanel.panel) openPanel.panel.remove();
    openPanel = null;
  }

  function reconcileOpenPanel() {
    if (!openPanel) return false;
    if (panelIsOwned(openPanel)) return true;
    closeCurrent({ restoreFocus: false });
    return false;
  }

  function panelShell(trigger, opportunityId) {
    closeCurrent({ restoreFocus: false });
    var card = trigger.closest(".result-card");
    if (!card) return null;
    var panelId = "hajim-match-panel-" + safeId(opportunityId);
    var panel = document.createElement("section");
    panel.className = "hajim-match-panel";
    panel.id = panelId;
    panel.setAttribute("aria-labelledby", panelId + "-heading");
    panel.innerHTML = '<div class="hajim-match-heading"><div><p class="eyebrow">Local faculty discovery</p>' +
      '<h4 id="' + panelId + '-heading" tabindex="-1">Relevant Hajim faculty</h4></div>' +
      '<button type="button" class="hajim-match-close" data-hajim-close aria-label="Close relevant Hajim faculty">Close</button></div>' +
      '<div class="hajim-match-body" role="status" aria-live="polite"><p>Loading evidence-qualified faculty matches…</p></div>';
    card.appendChild(panel);
    trigger.setAttribute("aria-controls", panelId);
    trigger.setAttribute("aria-expanded", "true");
    openPanel = { trigger: trigger, panel: panel, opportunityId: String(opportunityId), directory: null, graph: null, primaryOnly: false };
    panel.querySelector("h4").focus();
    return openPanel;
  }

  function evidenceLabel(field) {
    if (field === "title") return "Title";
    if (field === "description") return "Synopsis";
    return "Published document or subject text";
  }

  function facultyRow(match) {
    var profile = match.profile;
    var edge = match.edge;
    var contact = match.contact || {};
    var sourceUrl = contact.website_url || (contact.source_urls || [])[0] || "";
    var evidence = (edge.opportunity_evidence || []).map(function (item) {
      return '<p class="hajim-evidence"><strong>Opportunity evidence (' + escapeHtml(evidenceLabel(item.field)) + '):</strong> ' + escapeHtml(item.excerpt) + '</p>';
    }).join("");
    var themes = edge.corroborating_themes && edge.corroborating_themes.length
      ? '<p class="hajim-derived"><strong>Derived corroboration:</strong> ' + escapeHtml(edge.corroborating_themes.join(" · ")) + '</p>' : "";
    return '<article class="hajim-faculty-match">' +
      '<div class="hajim-faculty-title"><div><h5>' + escapeHtml(profile.name) + '</h5><p>' + escapeHtml(profile.home_unit) + ' · ' + escapeHtml(profile.relationship_label) + '</p></div>' +
      '<span class="hajim-tier">' + (edge.tier === "likely_relevant" ? "Likely relevant" : "Possible relevance") + '</span></div>' +
      '<p><strong>Matched faculty interest:</strong> ' + escapeHtml((edge.matched_profile_phrases || []).map(function (phrase) { return '“' + phrase + '”'; }).join(" · ")) + '</p>' +
      evidence + themes +
      '<div class="hajim-faculty-actions"><a href="mailto:' + escapeHtml(contact.email || "") + '">Email faculty</a>' +
      (sourceUrl ? '<a href="' + escapeHtml(sourceUrl) + '" target="_blank" rel="noopener">Faculty source ↗</a>' : "") +
      '<span>Source checked ' + escapeHtml(contact.checked_date || "Not listed") + '</span></div></article>';
  }

  function renderMatches() {
    if (!reconcileOpenPanel() || !openPanel.directory || !openPanel.graph) return;
    var body = openPanel.panel.querySelector(".hajim-match-body");
    var matches = API.opportunityMatches(
      openPanel.graph, openPanel.directory, openPanel.opportunityId, openPanel.primaryOnly
    );
    var source = openPanel.directory.faculty_source || {};
    var unionCount = source.union_record_count || openPanel.directory.profiles.length;
    var workbook = source.workbook || {};
    var restoredCount = Math.max(0, (workbook.unlisted_interest_count || 0) - (source.union_unrankable_count || 0));
    body.removeAttribute("role");
    body.innerHTML = '<div class="hajim-match-controls"><label for="hajim-scope-' + safeId(openPanel.opportunityId) + '">Faculty scope</label>' +
      '<select id="hajim-scope-' + safeId(openPanel.opportunityId) + '" data-hajim-scope>' +
      '<option value="all"' + (openPanel.primaryOnly ? "" : " selected") + '>Full Hajim and preserved Team Match directory (' + unionCount + ')</option>' +
      '<option value="primary"' + (openPanel.primaryOnly ? " selected" : "") + '>Hajim primary/research only (126)</option></select></div>' +
      '<p class="hajim-match-note">Matches use official faculty-interest phrases and published opportunity text. They do not imply eligibility, availability, or willingness to participate.</p>' +
      '<p class="hajim-unranked-note">' + (workbook.unlisted_interest_count || 0) + ' workbook profiles do not list research interests on their source faculty page. Preserved reviewed expertise restores ' + restoredCount + '; ' + (source.union_unrankable_count || 0) + ' directory profiles remain unranked.</p>' +
      (matches.length ? '<div class="hajim-match-list">' + matches.map(facultyRow).join("") + '</div>' :
        '<p class="hajim-no-matches">No faculty passed the evidence gate for this opportunity in the selected scope.</p>');
  }

  function renderFailure(error) {
    if (!reconcileOpenPanel()) return;
    var body = openPanel.panel.querySelector(".hajim-match-body");
    body.innerHTML = '<p>Faculty matches are temporarily unavailable. Ordinary Funding Finder search and actions still work.</p>' +
      '<button type="button" class="source-action" data-hajim-retry>Retry</button>';
    body.dataset.error = error && error.message ? error.message : "load_failed";
  }

  function loadCurrent() {
    var current = openPanel;
    if (!current || !panelIsOwned(current) || !API || !catalog()) {
      renderFailure(new Error("Faculty matching helper or catalog unavailable."));
      return;
    }
    var generationId;
    try {
      generationId = API.pageGenerationId();
    } catch (error) {
      renderFailure(error);
      return;
    }
    current.panel.querySelector(".hajim-match-body").innerHTML = "<p>Loading evidence-qualified faculty matches…</p>";
    API.loadDirectory(
      catalog(), API.versionedAssetUrl("data/hajim_faculty_directory.js", generationId), generationId
    ).then(function (directory) {
      if (openPanel !== current || !panelIsOwned(current)) {
        if (openPanel === current) closeCurrent({ restoreFocus: false });
        return null;
      }
      current.directory = directory;
      return API.loadGraph(
        directory, catalog(), API.versionedAssetUrl("data/faculty_matches.js", generationId), generationId
      );
    }).then(function (graph) {
      if (!graph || openPanel !== current || !panelIsOwned(current)) {
        if (openPanel === current) closeCurrent({ restoreFocus: false });
        return;
      }
      current.graph = graph;
      renderMatches();
      var heading = current.panel.querySelector("h4");
      if (heading) heading.focus();
    }).catch(function (error) {
      if (openPanel === current) renderFailure(error);
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-hajim-match]");
    if (trigger) {
      reconcileOpenPanel();
      var opportunityId = trigger.getAttribute("data-hajim-match");
      if (openPanel && openPanel.trigger === trigger && openPanel.opportunityId === opportunityId) {
        closeCurrent({ restoreFocus: true });
        return;
      }
      if (panelShell(trigger, opportunityId)) loadCurrent();
      return;
    }
    if (event.target.closest("[data-hajim-close]")) {
      closeCurrent({ restoreFocus: true });
      return;
    }
    if (event.target.closest("[data-hajim-retry]")) loadCurrent();
  });

  document.addEventListener("change", function (event) {
    if (!reconcileOpenPanel() || !event.target.matches("[data-hajim-scope]")) return;
    openPanel.primaryOnly = event.target.value === "primary";
    renderMatches();
  });

  document.addEventListener("funding-finder:before-results-render", function () {
    closeCurrent({ restoreFocus: false });
  });

  global.HajimReverseMatch = Object.freeze({ closeCurrent: closeCurrent, reconcileOpenPanel: reconcileOpenPanel });
})(globalThis);
