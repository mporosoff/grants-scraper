(function (global) {
  "use strict";

  var API = global.OpportunityTeam;
  var openPanels = new Map();
  var panelSequence = 0;
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
    var drawer = document.getElementById("team-builder");
    return Boolean(current.trigger.closest(".result-card") && drawer && drawer.open &&
      drawer.contains(current.panel));
  }

  function closePanel(current, options) {
    options = options || {};
    if (!current) return;
    var trigger = current.trigger;
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-controls");
    }
    if (current.panel) {
      openPanels.delete(current.panel);
      current.panel.remove();
    }
    global.SiteShell?.closeDrawer(document.getElementById("team-builder"), options);
  }

  function closeAll() {
    Array.from(openPanels.values()).forEach(function (current) {
      closePanel(current, { restoreFocus: false });
    });
  }

  function reconcile(current) {
    if (!current || !openPanels.has(current.panel)) return false;
    if (panelOwned(current)) return true;
    closePanel(current, { restoreFocus: false });
    return false;
  }

  function currentForElement(element) {
    var panel = element && element.closest && element.closest(".opportunity-team-panel");
    return panel ? openPanels.get(panel) || null : null;
  }

  function currentForTrigger(trigger) {
    return Array.from(openPanels.values()).find(function (current) {
      return current.trigger === trigger;
    }) || null;
  }

  function panelShell(trigger, parentId, scopeId) {
    var card = trigger.closest(".result-card");
    if (!card) return null;
    var drawer = document.getElementById("team-builder");
    var content = document.getElementById("team-builder-content");
    if (!drawer || !content || !global.SiteShell?.openDrawer) {
      document.getElementById("search-status").textContent = "Team Builder is temporarily unavailable. Ordinary search and Team Match remain available.";
      return null;
    }
    closeAll();
    panelSequence += 1;
    var panelId = "opportunity-team-panel-" + safeId(parentId) + "-" + panelSequence;
    var panel = document.createElement("section");
    panel.className = "opportunity-team-panel";
    panel.id = panelId;
    panel.setAttribute("aria-labelledby", panelId + "-heading");
    panel.innerHTML = '<div class="opportunity-team-heading"><div><p class="eyebrow">Proposed Team</p>' +
      '<h4 id="' + panelId + '-heading" tabindex="-1">Proposed research team</h4></div></div>' +
      '<div class="opportunity-team-body" role="status" aria-live="polite"><p>Loading proposed teams…</p></div>';
    content.appendChild(panel);
    trigger.setAttribute("aria-expanded", "true");
    trigger.setAttribute("aria-controls", "team-builder");
    var current = {
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
      scopeSequence: 0,
    };
    openPanels.set(panel, current);
    try {
      // Presentation adapter over the existing reviewed scope/proposal API.
      global.SiteShell.openDrawer(drawer, trigger, panel.querySelector("h4"), {
        context: "team",
        onClose: closeAll,
        resolveOpener: function () {
          return Array.from(document.querySelectorAll("[data-opportunity-team]")).find(function (node) {
            return node.getAttribute("data-opportunity-team") === String(parentId) &&
              node.getAttribute("data-opportunity-team-scope") === String(scopeId || "");
          }) || document.getElementById("open-results-chat");
        },
      });
    } catch (_error) {
      closeAll();
      document.getElementById("search-status").textContent = "Team Builder could not open. Ordinary search and Team Match remain available.";
      return null;
    }
    return current;
  }

  function teamMatchHref(view) {
    var url = new URL("team_match.html", location.href);
    url.searchParams.set("opportunity", view.opportunity.id);
    if (view.selectedIds.length) url.searchParams.set("proposed", view.selectedIds.join(","));
    return url.pathname + url.search;
  }

  function stateLabel(view) {
    if (view.complete && view.opportunity.gate_state === "pass") return "Proposed team with required roles covered";
    if (view.opportunity.gate_state === "fail") return "Insufficient internal role coverage";
    return "Credible internal core with missing skills";
  }

  function memberCard(item) {
    var profile = item.profile;
    var evidence = item.evidence;
    var why = evidence && evidence.why_person || (item.roles.length
      ? profile.name + " has source-backed capability evidence adjacent to " + item.roles.map(function (role) { return role.label; }).join(" and ") + "; exact role coverage remains unconfirmed."
      : "This person remains on the proposed team, but no required role is currently attributed to them.");
    var evidenceLine = evidence
      ? '<p><strong>Evidence:</strong> ' + escapeHtml(evidence.evidence_term) + ' — ' + escapeHtml(evidence.evidence_phrase) + '</p>'
      : '<p><strong>Evidence:</strong> ' + escapeHtml((item.relevantTerms || []).slice(0, 2).map(function (term) { return term.label + " — " + term.evidence; }).join(" · ") || "No retained capability for this role") + '</p>';
    var source = evidence && evidence.source_url || (item.relevantTerms || []).flatMap(function (term) { return term.source_urls; })[0] || profile.source_url;
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
    var label = role.filled ? (role.directEvidence ? "Direct evidence" : "Supported by method transfer") : alternativeNames.length ? "Coverage unconfirmed" : role.coverage === "adjacent" ? "Adjacent support only" : role.required === false ? "Optional extension" : "Missing";
    return '<li class="opportunity-team-role ' + (role.filled ? "filled" : "missing") + '"><div><strong>' + escapeHtml(role.label) + '</strong>' +
      '<span class="opportunity-team-role-state">' + escapeHtml(label) + '</span></div>' +
      (selectedNames.length ? '<p>Attributed to ' + escapeHtml(selectedNames.join(" and ")) + '.</p>' : '') +
      (alternativeNames.length ? '<p>Possible source-backed alternative: ' + escapeHtml(alternativeNames.join(" and ")) + '.</p>' : '') +
      '<p>' + escapeHtml(role.rationale) + '</p>' +
      '<a href="' + escapeHtml(role.source_url) + '" target="_blank" rel="noopener">Opportunity role source ↗</a></li>';
  }

  function renderProposal(current) {
    if (!reconcile(current) || !current.engine || !current.state) return;
    var view = current.engine.proposalView(current.state);
    var body = current.panel.querySelector(".opportunity-team-body");
    var replacementId = current.panel.id + "-replacement";
    var rolesId = current.panel.id + "-roles";
    var options = current.engine.proposalOptions(current.state);
    var originalIds = view.opportunity.members.map(function (member) { return member.faculty_id; }).sort().join("|");
    var whyTeam = view.selectedIds.slice().sort().join("|") === originalIds ? view.opportunity.why_team :
      view.selected.map(function (member) {
        var supported = member.roles.filter(function (role) { return role.selected_candidate_ids.includes(member.profile.id); });
        return member.profile.name + (supported.length ? " contributes to " + supported.map(function (role) { return role.label; }).join(" and ") : " offers possible support with role coverage unconfirmed") + ".";
      }).join(" ") + (view.complete ? "" : " The remaining role gaps are listed below.");
    var missingSkills = view.opportunity.missing_skills.filter(function (skill) {
      return !view.roles.some(function (role) { return role.label === skill && role.filled; });
    });
    view.unfilledRoles.forEach(function (role) {
      if (!missingSkills.includes(role.label)) missingSkills.push(role.label);
    });
    var replacement = view.replacements.length && view.selectedIds.length < 4
      ? '<div class="opportunity-team-replacement"><label for="' + replacementId + '">Source-backed replacement options</label>' +
        '<div><select id="' + replacementId + '" data-opportunity-team-replacement><option value="">Choose a replacement</option>' +
        view.replacements.map(function (item) {
          return '<option value="' + escapeHtml(item.profile.id) + '">' + escapeHtml(item.profile.name) + ' — ' + (item.previouslySelected ? 'Previously selected · ' : '') + escapeHtml(item.roles.map(function (role) { return role.label; }).join("; ")) + (item.reviewed ? '' : ' (coverage unconfirmed)') + '</option>';
        }).join("") + '</select><button type="button" data-opportunity-team-add-replacement disabled>Add to team</button></div></div>'
      : '<p class="opportunity-team-no-replacement">' + (view.selectedIds.length >= 4
        ? "Remove a team member to compare replacement options."
        : "No additional internal faculty member has source-backed evidence for the currently missing roles.") + '</p>';
    body.removeAttribute("role");
    body.innerHTML = (options.length > 1 ? '<div class="opportunity-team-scope-options" aria-label="Proposed team options">' + options.map(function (option, index) {
      var selected = option.state.selectedIds.slice().sort().join("|") === view.selectedIds.slice().sort().join("|");
      return '<button type="button" aria-pressed="' + selected + '" data-opportunity-team-variant="' + index + '"><strong>Team option ' + (index + 1) + '</strong><span>' + escapeHtml(option.label) + '</span></button>';
    }).join("") + '</div>' : '') + '<div class="opportunity-team-status"><span class="badge ' + (view.complete ? "open" : "warning") + '">' + escapeHtml(stateLabel(view)) + '</span>' +
      '<span>' + view.selectedIds.length + ' of 4 team slots used</span></div>' +
      '<h5 class="opportunity-team-scope">' + escapeHtml(view.opportunity.scope_label) + '</h5>' +
      '<p><strong>Specific objective:</strong> ' + escapeHtml(view.opportunity.objective) + '</p>' +
      '<div class="opportunity-team-why"><strong>Why this team</strong><p>' + escapeHtml(whyTeam) + '</p></div>' +
      '<div class="opportunity-team-members">' + view.selected.map(memberCard).join("") + '</div>' +
      '<section class="opportunity-team-roles" aria-labelledby="' + rolesId + '"><h5 id="' + rolesId + '">Roles for this research approach</h5><ul>' +
      view.roles.map(function (role) { return roleRow(role, current.engine); }).join("") + '</ul></section>' +
      (missingSkills.length ? '<section class="opportunity-team-gaps"><h5>Missing skills to recruit</h5><ul>' + missingSkills.map(function (skill) { return '<li>' + escapeHtml(skill) + '</li>'; }).join("") + '</ul></section>' : '') +
      replacement +
      '<div class="opportunity-team-next"><a class="button secondary" href="' + escapeHtml(teamMatchHref(view)) + '">Continue in Team Match</a>' +
      '<a class="source-action" href="faculty_interests.html?mode=add&return=team_match&opportunity=' + encodeURIComponent(view.opportunity.id) + '">Add a missing researcher</a></div>' +
      '<p class="opportunity-team-caveat">This is an evidence-calibrated planning aid, not a statement of eligibility, availability, willingness, or sponsor fit. Verify the official notice and contact each proposed investigator.</p>';
  }

  function renderScopeChoice(current, scopes) {
    if (!reconcile(current)) return;
    var body = current.panel.querySelector(".opportunity-team-body");
    body.removeAttribute("role");
    body.innerHTML = '<h5>Choose a specific opportunity topic</h5><p>This parent call is too broad for automatic team assembly. Select a specific child topic or declared branch.</p>' +
      '<div class="opportunity-team-scope-options">' + scopes.map(function (scope) {
        return '<button type="button" data-opportunity-team-scope="' + escapeHtml(scope.id) + '"><strong>' + escapeHtml(scope.scope_label) + '</strong><span>' + escapeHtml(scope.record_type.replace(/_/g, " ")) + '</span></button>';
      }).join("") + '</div>';
  }

  function renderUnavailable(current, reason, scopes) {
    if (!reconcile(current)) return;
    if (reason === "specific_scope_required" && scopes && scopes.length) {
      renderScopeChoice(current, scopes);
      return;
    }
    var messages = {
      unsupported_scope: "This opportunity does not yet have a proposed team for a specific research topic.",
      not_current: "This opportunity is no longer current, so its saved team model is not displayed.",
      broad_parent_rejected: "A broad parent program cannot receive an automatic team proposal. Choose a specific child or declared branch.",
      needs_revalidation: "Researcher interests or eligibility changed. This team is awaiting revalidation; current profiles remain available in Team Match.",
      child_not_publication_eligible: "The selected child topic is not currently publication-eligible, so it cannot support a team proposal.",
      currentness_unavailable: "The authoritative opportunity-currentness check is unavailable.",
    };
    var body = current.panel.querySelector(".opportunity-team-body");
    body.removeAttribute("role");
    body.innerHTML = '<p>' + escapeHtml(messages[reason] || "The proposed team is temporarily unavailable.") + '</p>' +
      '<p>Ordinary Funding Finder search and Team Match remain available.</p>' +
      '<a class="button secondary" href="team_match.html">Open Team Match</a>';
  }

  function renderFailure(current, error) {
    if (!reconcile(current)) return;
    var body = current.panel.querySelector(".opportunity-team-body");
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

  function resolveCurrent(current) {
    if (!current || !panelOwned(current) || !current.engine) return;
    var sequence = ++current.scopeSequence;
    var tentative = current.engine.opportunityById.get(current.scopeId);
    var needChildren = tentative ? tentative.record_type === "publishable_child" : current.engine.scopesFor(current.parentId).some(function (scope) {
      return scope.record_type === "publishable_child";
    });
    var childReady = needChildren ? loadChildCatalog() : Promise.resolve(null);
    childReady.then(function (childCatalog) {
      if (!reconcile(current) || current.scopeSequence !== sequence) return;
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
        renderUnavailable(current, outcome.reason, outcome.scopes);
        return;
      }
      current.scopeId = outcome.opportunity.id;
      current.state = current.engine.proposal(outcome.opportunity);
      renderProposal(current);
    }).catch(function (error) {
      if (reconcile(current) && current.scopeSequence === sequence) renderFailure(current, error);
    });
  }

  function loadCurrent(current) {
    if (!current || !panelOwned(current) || !API || !current.record) {
      if (current) renderFailure(current, new Error("Team helper or catalog record unavailable."));
      return;
    }
    var generationId;
    try { generationId = API.pageGenerationId(); } catch (error) {
      renderFailure(current, error);
      return;
    }
    API.loadData(generationId).then(function (data) {
      if (!reconcile(current)) return;
      current.engine = API.create(data);
      resolveCurrent(current);
    }).catch(function (error) {
      if (reconcile(current)) renderFailure(current, error);
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-opportunity-team]");
    if (trigger) {
      var parentId = trigger.getAttribute("data-opportunity-team");
      var scopeId = trigger.getAttribute("data-opportunity-team-scope") || "";
      var existing = currentForTrigger(trigger);
      if (existing && existing.parentId === parentId) {
        closePanel(existing, { restoreFocus: true });
        return;
      }
      var created = panelShell(trigger, parentId, scopeId);
      if (created) loadCurrent(created);
      return;
    }
    var current = currentForElement(event.target);
    if (event.target.closest("[data-opportunity-team-retry]") && current) {
      loadCurrent(current);
      return;
    }
    var scope = event.target.closest("[data-opportunity-team-scope]");
    if (scope && reconcile(current)) {
      current.scopeId = scope.getAttribute("data-opportunity-team-scope");
      current.panel.querySelector(".opportunity-team-body").innerHTML = "<p>Checking the selected topic and its current publication eligibility…</p>";
      resolveCurrent(current);
      return;
    }
    var remove = event.target.closest("[data-opportunity-team-remove]");
    var variant = event.target.closest("[data-opportunity-team-variant]");
    if (variant && reconcile(current) && current.state) {
      var option = current.engine.proposalOptions(current.state)[Number(variant.getAttribute("data-opportunity-team-variant"))];
      if (option) { current.state = option.state; renderProposal(current); }
      return;
    }
    if (remove && reconcile(current) && current.state) {
      current.state = current.engine.removeMember(current.state, remove.getAttribute("data-opportunity-team-remove"));
      renderProposal(current);
      return;
    }
    var add = event.target.closest("[data-opportunity-team-add-replacement]");
    if (add && reconcile(current) && current.state) {
      var select = current.panel.querySelector("[data-opportunity-team-replacement]");
      if (select && select.value) {
        current.state = current.engine.addReplacement(current.state, select.value);
        renderProposal(current);
      }
    }
  });

  document.addEventListener("change", function (event) {
    var current = currentForElement(event.target);
    if (!reconcile(current) || !event.target.matches("[data-opportunity-team-replacement]")) return;
    var button = current.panel.querySelector("[data-opportunity-team-add-replacement]");
    if (button) button.disabled = !event.target.value;
  });

  document.addEventListener("funding-finder:before-results-render", function () {
    closeAll();
  });

  global.OpportunityTeamPanel = Object.freeze({ closeAll: closeAll, reconcile: reconcile });
})(globalThis);
