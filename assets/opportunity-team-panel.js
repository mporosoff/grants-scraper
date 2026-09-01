(function (global) {
  "use strict";

  var API = global.OpportunityTeam;
  var openPanel = null;
  var childCatalogPromise = null;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function safeId(value) {
    return String(value || "").replace(/[^a-z0-9_-]+/gi, "-");
  }

  function catalogRecord(identifier) {
    var records = global.GRANT_CATALOG && global.GRANT_CATALOG.opportunities || [];
    var target = String(identifier || "");
    return records.find(function (record) {
      return String(record.opportunity_id || record.opportunity_number || record.title || "") === target;
    }) || null;
  }

  function panelOwned(current) {
    if (!current || !current.trigger || !current.panel ||
        !current.trigger.isConnected || !current.panel.isConnected) return false;
    var card = current.trigger.closest(".result-card");
    return Boolean(card && card === current.panel.closest(".result-card") &&
      card.contains(current.trigger) && card.contains(current.panel));
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

  function reconcile() {
    if (!openPanel) return false;
    if (panelOwned(openPanel)) return true;
    closeCurrent({ restoreFocus: false });
    return false;
  }

  function panelShell(trigger, parentId, scopeId) {
    closeCurrent({ restoreFocus: false });
    var card = trigger.closest(".result-card");
    if (!card) return null;
    var panelId = "opportunity-team-panel-" + safeId(parentId);
    var panel = document.createElement("section");
    panel.className = "opportunity-team-panel";
    panel.id = panelId;
    panel.setAttribute("aria-labelledby", panelId + "-heading");
    panel.innerHTML = '<div class="opportunity-team-heading"><div><p class="eyebrow">Opportunity-to-team pilot</p>' +
      '<h4 id="' + panelId + '-heading" tabindex="-1">Proposed research team</h4></div>' +
      '<button type="button" class="opportunity-team-close" data-opportunity-team-close aria-label="Close proposed research team">Close</button></div>' +
      '<div class="opportunity-team-body" role="status" aria-live="polite"><p>Loading the evidence-calibrated role model…</p></div>';
    card.appendChild(panel);
    trigger.setAttribute("aria-expanded", "true");
    trigger.setAttribute("aria-controls", panelId);
    openPanel = {
      trigger: trigger,
      panel: panel,
      parentId: String(parentId),
      scopeId: String(scopeId || ""),
      record: catalogRecord(parentId),
      isBroad: trigger.getAttribute("data-opportunity-team-broad") === "true",
      now: new Date(),
      engine: null,
      state: null,
      childCatalog: null,
    };
    panel.querySelector("h4").focus();
    return openPanel;
  }

  function teamMatchHref(view) {
    var url = new URL("team_match.html", location.href);
    url.searchParams.set("opportunity", view.opportunity.id);
    if (view.selectedIds.length) url.searchParams.set("proposed", view.selectedIds.join(","));
    return url.pathname + url.search;
  }

  function stateLabel(view) {
    if (view.complete && view.opportunity.gate_state === "pass") return "Complete reviewed internal team";
    if (view.opportunity.gate_state === "fail") return "Insufficient internal role coverage";
    return "Credible internal core with missing skills";
  }

  function memberCard(item) {
    var profile = item.profile;
    var evidence = item.evidence;
    var why = evidence && evidence.why_person || (item.roles.length
      ? profile.name + " has source-backed capability evidence adjacent to " + item.roles.map(function (role) { return role.label; }).join(" and ") + "; the role transfer still requires review."
      : "This person remains on the proposed team, but no required role is currently attributed to them.");
    var evidenceLine = evidence
      ? '<p><strong>Evidence:</strong> ' + escapeHtml(evidence.evidence_term) + ' — ' + escapeHtml(evidence.evidence_phrase) + '</p>'
      : '<p><strong>Evidence:</strong> ' + escapeHtml((profile.terms || []).slice(0, 2).map(function (term) { return term.label; }).join(" · ") || "No retained capability") + '</p>';
    var source = evidence && evidence.source_url || profile.source_url;
    return '<article class="opportunity-team-member"><div class="opportunity-team-member-title"><div><h5>' + escapeHtml(profile.name) + '</h5><p>' + escapeHtml(profile.home_unit) + '</p></div>' +
      '<button type="button" class="opportunity-team-remove" data-opportunity-team-remove="' + escapeHtml(profile.id) + '" aria-label="Remove ' + escapeHtml(profile.name) + ' from this proposed team">Remove</button></div>' +
      (evidence ? '<p class="opportunity-team-contribution"><strong>Contribution:</strong> ' + escapeHtml(evidence.contribution) + '</p>' : '') +
      '<p>' + escapeHtml(why) + '</p>' + evidenceLine +
      '<p class="opportunity-team-source"><a href="' + escapeHtml(source) + '" target="_blank" rel="noopener">Faculty evidence source ↗</a> · checked ' + escapeHtml(profile.source_checked_date) + '</p></article>';
  }

  function roleRow(role, engine) {
    var selectedNames = role.selected_candidate_ids.map(function (identifier) {
      return engine.facultyById.get(identifier).name;
    });
    var alternativeNames = role.selected_alternative_ids.map(function (identifier) {
      return engine.facultyById.get(identifier).name;
    });
    var label = role.filled ? "Covered" : alternativeNames.length ? "Role review required" : role.coverage === "adjacent" ? "Adjacent support only" : "Missing";
    return '<li class="opportunity-team-role ' + (role.filled ? "filled" : "missing") + '"><div><strong>' + escapeHtml(role.label) + '</strong>' +
      '<span class="opportunity-team-role-state">' + escapeHtml(label) + '</span></div>' +
      (selectedNames.length ? '<p>Attributed to ' + escapeHtml(selectedNames.join(" and ")) + '.</p>' : '') +
      (alternativeNames.length ? '<p>Source-backed alternative under review: ' + escapeHtml(alternativeNames.join(" and ")) + '.</p>' : '') +
      '<p>' + escapeHtml(role.rationale) + '</p>' +
      '<a href="' + escapeHtml(role.source_url) + '" target="_blank" rel="noopener">Opportunity role source ↗</a></li>';
  }

  function renderProposal() {
    if (!reconcile() || !openPanel.engine || !openPanel.state) return;
    var current = openPanel;
    var view = current.engine.proposalView(current.state);
    var body = current.panel.querySelector(".opportunity-team-body");
    var missingSkills = view.opportunity.missing_skills.slice();
    view.unfilledRoles.forEach(function (role) {
      if (!missingSkills.includes(role.label)) missingSkills.push(role.label);
    });
    var replacement = view.replacements.length && view.selectedIds.length < 4
      ? '<div class="opportunity-team-replacement"><label for="opportunity-team-replacement-' + safeId(view.opportunity.id) + '">Source-backed replacement options</label>' +
        '<div><select id="opportunity-team-replacement-' + safeId(view.opportunity.id) + '" data-opportunity-team-replacement><option value="">Choose a replacement</option>' +
        view.replacements.map(function (item) {
          return '<option value="' + escapeHtml(item.profile.id) + '">' + escapeHtml(item.profile.name) + ' — ' + escapeHtml(item.roles.map(function (role) { return role.label; }).join("; ")) + (item.reviewed ? '' : ' (role review required)') + '</option>';
        }).join("") + '</select><button type="button" data-opportunity-team-add-replacement disabled>Add to team</button></div></div>'
      : '<p class="opportunity-team-no-replacement">' + (view.selectedIds.length >= 4
        ? "Remove a team member to compare reviewed replacements."
        : "No additional internal faculty member has source-backed evidence for the currently missing roles.") + '</p>';
    body.removeAttribute("role");
    body.innerHTML = '<div class="opportunity-team-status"><span class="badge ' + (view.complete ? "open" : "warning") + '">' + escapeHtml(stateLabel(view)) + '</span>' +
      '<span>' + view.selectedIds.length + ' of 4 team slots used</span></div>' +
      '<h5 class="opportunity-team-scope">' + escapeHtml(view.opportunity.scope_label) + '</h5>' +
      '<p><strong>Specific objective:</strong> ' + escapeHtml(view.opportunity.objective) + '</p>' +
      '<div class="opportunity-team-why"><strong>Why this team</strong><p>' + escapeHtml(view.opportunity.why_team) + '</p></div>' +
      '<div class="opportunity-team-members">' + view.selected.map(memberCard).join("") + '</div>' +
      '<section class="opportunity-team-roles" aria-labelledby="opportunity-team-roles-' + safeId(view.opportunity.id) + '"><h5 id="opportunity-team-roles-' + safeId(view.opportunity.id) + '">Required roles and evidence</h5><ul>' +
      view.roles.map(function (role) { return roleRow(role, current.engine); }).join("") + '</ul></section>' +
      (missingSkills.length ? '<section class="opportunity-team-gaps"><h5>Missing skills to recruit</h5><ul>' + missingSkills.map(function (skill) { return '<li>' + escapeHtml(skill) + '</li>'; }).join("") + '</ul></section>' : '') +
      replacement +
      '<div class="opportunity-team-next"><a class="button secondary" href="' + escapeHtml(teamMatchHref(view)) + '">Continue in Team Match</a>' +
      '<a class="source-action" href="team_match.html?manual=1&opportunity=' + encodeURIComponent(view.opportunity.id) + '">Add a researcher manually</a></div>' +
      '<p class="opportunity-team-caveat">This is an evidence-calibrated planning aid, not a statement of eligibility, availability, willingness, or sponsor fit. Verify the official notice and contact each proposed investigator.</p>';
  }

  function renderScopeChoice(scopes) {
    if (!reconcile()) return;
    var body = openPanel.panel.querySelector(".opportunity-team-body");
    body.removeAttribute("role");
    body.innerHTML = '<h5>Choose a specific opportunity topic</h5><p>This parent call is too broad for automatic team assembly. Select one reviewed child or declared branch.</p>' +
      '<div class="opportunity-team-scope-options">' + scopes.map(function (scope) {
        return '<button type="button" data-opportunity-team-scope="' + escapeHtml(scope.id) + '"><strong>' + escapeHtml(scope.scope_label) + '</strong><span>' + escapeHtml(scope.record_type.replace(/_/g, " ")) + '</span></button>';
      }).join("") + '</div>';
  }

  function renderUnavailable(reason, scopes) {
    if (!reconcile()) return;
    if (reason === "specific_scope_required" && scopes && scopes.length) {
      renderScopeChoice(scopes);
      return;
    }
    var messages = {
      unsupported_scope: "This opportunity does not yet have a reviewed role-and-team model.",
      not_current: "This opportunity is no longer current, so its saved team model is not displayed.",
      broad_parent_rejected: "A broad parent program cannot receive an automatic team proposal. Choose a specific child or declared branch.",
      child_not_publication_eligible: "The selected child topic is not currently publication-eligible, so it cannot support a team proposal.",
      currentness_unavailable: "The authoritative opportunity-currentness check is unavailable.",
    };
    var body = openPanel.panel.querySelector(".opportunity-team-body");
    body.removeAttribute("role");
    body.innerHTML = '<p>' + escapeHtml(messages[reason] || "The proposed team is temporarily unavailable.") + '</p>' +
      '<p>Ordinary Funding Finder search and Team Match remain available.</p>' +
      '<a class="button secondary" href="team_match.html">Open Team Match</a>';
  }

  function renderFailure(error) {
    if (!reconcile()) return;
    var body = openPanel.panel.querySelector(".opportunity-team-body");
    body.innerHTML = '<p>Team proposals are temporarily unavailable. Ordinary Funding Finder search and actions still work.</p>' +
      '<button type="button" class="source-action" data-opportunity-team-retry>Retry</button>';
    body.dataset.error = String(error && error.message || "load_failed").slice(0, 200);
  }

  function loadChildCatalog() {
    if (childCatalogPromise) return childCatalogPromise;
    if (!global.FUNDING_SUBTOPICS || !global.FUNDING_RETRIEVAL) {
      return Promise.reject(new Error("The publication-eligible child catalog is unavailable."));
    }
    childCatalogPromise = global.FUNDING_SUBTOPICS.loadSidecar().then(function (sidecar) {
      return global.FUNDING_RETRIEVAL.createChildCatalog(sidecar);
    }).catch(function (error) {
      childCatalogPromise = null;
      throw error;
    });
    return childCatalogPromise;
  }

  function resolveCurrent() {
    var current = openPanel;
    if (!current || !panelOwned(current) || !current.engine) return;
    var tentative = current.engine.opportunityById.get(current.scopeId);
    var needChildren = tentative && tentative.record_type === "publishable_child";
    var childReady = needChildren ? loadChildCatalog() : Promise.resolve(null);
    childReady.then(function (childCatalog) {
      if (openPanel !== current || !panelOwned(current)) return;
      current.childCatalog = childCatalog;
      var outcome = current.engine.resolveScope({
        parentId: current.parentId,
        scopeId: current.scopeId,
        record: current.record,
        childCatalog: childCatalog,
        isBroad: current.isBroad,
        now: current.now,
      });
      if (!outcome.ok) {
        renderUnavailable(outcome.reason, outcome.scopes);
        return;
      }
      current.scopeId = outcome.opportunity.id;
      current.state = current.engine.proposal(outcome.opportunity);
      renderProposal();
      var heading = current.panel.querySelector("h4");
      if (heading) heading.focus();
    }).catch(function (error) {
      if (openPanel === current) renderFailure(error);
    });
  }

  function loadCurrent() {
    var current = openPanel;
    if (!current || !panelOwned(current) || !API || !current.record) {
      renderFailure(new Error("Team helper or catalog record unavailable."));
      return;
    }
    var generationId;
    try { generationId = API.pageGenerationId(); } catch (error) {
      renderFailure(error);
      return;
    }
    API.loadData(generationId).then(function (data) {
      if (openPanel !== current || !panelOwned(current)) return;
      current.engine = API.create(data);
      resolveCurrent();
    }).catch(function (error) {
      if (openPanel === current) renderFailure(error);
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-opportunity-team]");
    if (trigger) {
      reconcile();
      var parentId = trigger.getAttribute("data-opportunity-team");
      var scopeId = trigger.getAttribute("data-opportunity-team-scope") || "";
      if (openPanel && openPanel.trigger === trigger && openPanel.parentId === parentId) {
        closeCurrent({ restoreFocus: true });
        return;
      }
      if (panelShell(trigger, parentId, scopeId)) loadCurrent();
      return;
    }
    if (event.target.closest("[data-opportunity-team-close]")) {
      closeCurrent({ restoreFocus: true });
      return;
    }
    if (event.target.closest("[data-opportunity-team-retry]")) {
      loadCurrent();
      return;
    }
    var scope = event.target.closest("[data-opportunity-team-scope]");
    if (scope && reconcile()) {
      openPanel.scopeId = scope.getAttribute("data-opportunity-team-scope");
      openPanel.panel.querySelector(".opportunity-team-body").innerHTML = "<p>Checking the selected topic and its current publication eligibility…</p>";
      resolveCurrent();
      return;
    }
    var remove = event.target.closest("[data-opportunity-team-remove]");
    if (remove && reconcile() && openPanel.state) {
      openPanel.state = openPanel.engine.removeMember(openPanel.state, remove.getAttribute("data-opportunity-team-remove"));
      renderProposal();
      return;
    }
    var add = event.target.closest("[data-opportunity-team-add-replacement]");
    if (add && reconcile() && openPanel.state) {
      var select = openPanel.panel.querySelector("[data-opportunity-team-replacement]");
      if (select && select.value) {
        openPanel.state = openPanel.engine.addReplacement(openPanel.state, select.value);
        renderProposal();
      }
    }
  });

  document.addEventListener("change", function (event) {
    if (!reconcile() || !event.target.matches("[data-opportunity-team-replacement]")) return;
    var button = openPanel.panel.querySelector("[data-opportunity-team-add-replacement]");
    if (button) button.disabled = !event.target.value;
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && reconcile()) closeCurrent({ restoreFocus: true });
  });

  document.addEventListener("funding-finder:before-results-render", function () {
    closeCurrent({ restoreFocus: false });
  });

  global.OpportunityTeamPanel = Object.freeze({ closeCurrent: closeCurrent, reconcile: reconcile });
})(globalThis);
