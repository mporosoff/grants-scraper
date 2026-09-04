(function (global) {
  "use strict";

  var SCHEMA_VERSION = 1;
  var MAX_DIRECTORY_RESULTS = 12;
  var dataPromise = null;

  function normalize(value) {
    return String(value == null ? "" : value)
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/&/g, " and ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function pageGenerationId() {
    var marker = document.querySelector('meta[name="opportunity-team-generation"]');
    var value = marker && marker.getAttribute("content");
    if (!/^[a-f0-9]{64}$/.test(value || "")) {
      throw new Error("The page does not declare a valid opportunity-team generation.");
    }
    return value;
  }

  function versionedAssetUrl(generationId) {
    if (!/^[a-f0-9]{64}$/.test(generationId || "")) {
      throw new Error("A valid opportunity-team generation is required.");
    }
    return "data/opportunity_teams.js?v=" + generationId;
  }

  function validateIndex(index, expectedGenerationId) {
    if (!index || index.schema_version !== SCHEMA_VERSION ||
        !/^[a-f0-9]{64}$/.test(index.generation_id || "") ||
        (expectedGenerationId && index.generation_id !== expectedGenerationId) ||
        !Array.isArray(index.scopes) || index.scopes.length !== 10) {
      throw new Error("The opportunity-team availability index is incompatible.");
    }
    var identifiers = new Set();
    index.scopes.forEach(function (scope) {
      if (!scope || !scope.id || !scope.parent_id || identifiers.has(scope.id) ||
          !["specific_parent", "publishable_child", "declared_branch"].includes(scope.record_type)) {
        throw new Error("The opportunity-team availability index is invalid.");
      }
      identifiers.add(scope.id);
    });
    return index;
  }

  function availabilityIndex() {
    return validateIndex(global.OPPORTUNITY_TEAM_INDEX, pageGenerationId());
  }

  function availableScopes(options) {
    options = options || {};
    var parentId = String(options.parentId || "");
    var scopeId = String(options.scopeId || "");
    return availabilityIndex().scopes.filter(function (scope) {
      if (scopeId && scope.id !== scopeId) return false;
      return !parentId || scope.parent_id === parentId;
    });
  }

  function hasAvailableScope(options) {
    return availableScopes(options).length > 0;
  }

  function validateData(data, expectedGenerationId) {
    var source = data && data.source_roster_counts;
    var pools = data && data.pool_counts;
    var directory = global.RESEARCHER_DIRECTORY;
    if (!data || data.schema_version !== SCHEMA_VERSION ||
        !/^[a-f0-9]{64}$/.test(data.generation_id || "") ||
        (expectedGenerationId && data.generation_id !== expectedGenerationId) ||
        !Array.isArray(data.opportunities) || data.opportunities.length !== 10 ||
        !source || !pools || !directory || directory.schema_version !== 1 ||
        directory.registry_generation !== data.researcher_registry_generation ||
        !Array.isArray(directory.researchers) || !directory.counts ||
        source.total !== directory.counts.total ||
        source.rankable !== directory.counts.rankable ||
        source.unrankable !== directory.counts.unrankable ||
        pools.main !== directory.counts.pool_counts.main ||
        pools.standby !== directory.counts.pool_counts.standby ||
        pools.unadmitted !== directory.counts.pool_counts.unadmitted) {
      throw new Error("The opportunity-team data has an incompatible identity or roster contract.");
    }
    data.faculty = directory.researchers.map(function (researcher) {
      return {
        id: researcher.id,
        legacy_ids: researcher.legacy_ids || [],
        name: researcher.name,
        home_unit: researcher.home_unit,
        relationship: researcher.relationship,
        pool_visibility: researcher.pool_visibility,
        auto_proposable: researcher.auto_proposable,
        status: researcher.status,
        pool_state: researcher.pool_state,
        claim_status: "registry-reviewed",
        terms: (researcher.claims || []).filter(function (claim) {
          return claim.status === "active";
        }).map(function (claim) {
          return {
            claim_id: claim.claim_id,
            claim_revision: claim.revision,
            label: claim.label,
            evidence: claim.evidence,
            evidence_tier: claim.evidence_level,
          };
        }),
        source_url: researcher.source_url,
        source_checked_date: researcher.source_checked_date,
      };
    });
    var facultyIds = new Set();
    data.faculty.forEach(function (profile) {
      if (!profile || !profile.id || !profile.name || facultyIds.has(profile.id) ||
          !["main", "standby", "unadmitted"].includes(profile.pool_state) ||
          !Array.isArray(profile.terms) || !profile.source_url) {
        throw new Error("The opportunity-team faculty directory is invalid.");
      }
      facultyIds.add(profile.id);
    });
    data.opportunities.forEach(function (opportunity) {
      if (!opportunity || !opportunity.id || !opportunity.parent_id ||
          !["specific_parent", "publishable_child", "declared_branch"].includes(opportunity.record_type) ||
          !["pass", "conditional", "fail"].includes(opportunity.gate_state) ||
          !Array.isArray(opportunity.members) || ![3, 4].includes(opportunity.members.length) ||
          !Array.isArray(opportunity.roles) || opportunity.roles.length !== 4 ||
          opportunity.members.some(function (member) { return !facultyIds.has(member.faculty_id); })) {
        throw new Error("The opportunity-team role model is invalid.");
      }
    });
    var indexedScopes = validateIndex(
      global.OPPORTUNITY_TEAM_INDEX,
      expectedGenerationId || data.generation_id,
    ).scopes;
    var projectedScopes = data.opportunities.map(function (opportunity) {
      return {
        id: opportunity.id,
        parent_id: opportunity.parent_id,
        record_type: opportunity.record_type,
      };
    });
    if (JSON.stringify(indexedScopes) !== JSON.stringify(projectedScopes)) {
      throw new Error("The opportunity-team data and availability index do not match.");
    }
    return data;
  }

  function discardData() {
    try { delete global.OPPORTUNITY_TEAM_DATA; } catch (_error) {
      global.OPPORTUNITY_TEAM_DATA = undefined;
    }
    document.querySelectorAll("script[data-opportunity-team-data]").forEach(function (script) {
      script.remove();
    });
  }

  function injectData(src) {
    return new Promise(function (resolve, reject) {
      var bounded = global.FUNDING_FINDER_APP &&
        global.FUNDING_FINDER_APP.boundedScripts &&
        global.FUNDING_FINDER_APP.boundedScripts.sidecar;
      if (!bounded) {
        reject(new Error("The bounded team-data loader is unavailable."));
        return;
      }
      var script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.opportunityTeamData = "true";
      var settled = false;
      var timeout = null;
      function cleanup(remove) {
        if (timeout !== null) bounded.clearTimeout(timeout);
        timeout = null;
        script.removeEventListener("load", onLoad);
        script.removeEventListener("error", onError);
        if (remove) script.remove();
      }
      function finish(callback, remove) {
        if (settled) return;
        settled = true;
        cleanup(remove);
        callback();
      }
      function onLoad() {
        finish(function () {
          if (global.OPPORTUNITY_TEAM_DATA) resolve(global.OPPORTUNITY_TEAM_DATA);
          else reject(new Error("The team-data asset loaded without initializing."));
        }, !global.OPPORTUNITY_TEAM_DATA);
      }
      function onError() {
        finish(function () { reject(new Error("The team-data asset could not be loaded.")); }, true);
      }
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
      timeout = bounded.setTimeout(function () {
        finish(function () { reject(new Error("The team-data asset request timed out.")); }, true);
      });
      document.head.appendChild(script);
    });
  }

  function loadData(expectedGenerationId) {
    var generationId = expectedGenerationId || pageGenerationId();
    if (!dataPromise) {
      dataPromise = Promise.resolve(global.OPPORTUNITY_TEAM_DATA || null)
        .then(function (value) {
          return value || injectData(versionedAssetUrl(generationId));
        })
        .then(function (value) { return validateData(value, generationId); })
        .catch(function (error) {
          discardData();
          dataPromise = null;
          throw error;
        });
    }
    return dataPromise;
  }

  function resetLoadForTest() {
    dataPromise = null;
  }

  function poolRank(value) {
    return value === "main" ? 0 : value === "standby" ? 1 : 2;
  }

  function searchFaculty(data, query, options) {
    options = options || {};
    var value = normalize(query);
    if (!options.showAll && value.length < 2) return [];
    var terms = value.split(" ").filter(Boolean);
    return (data.faculty || []).map(function (profile) {
      var name = normalize(profile.name);
      var unit = normalize(profile.home_unit);
      var capabilities = normalize((profile.terms || []).map(function (term) {
        return term.label + " " + term.evidence;
      }).join(" "));
      var score = 99;
      if (!value) score = 10;
      else if (name === value) score = 0;
      else if (name.indexOf(value) === 0 || terms.every(function (term) {
        return name.split(" ").some(function (part) { return part.indexOf(term) === 0; });
      })) score = 1;
      else if (name.indexOf(value) !== -1) score = 2;
      else if (unit.indexOf(value) !== -1) score = 3;
      else if (terms.every(function (term) { return capabilities.indexOf(term) !== -1; })) score = 4;
      return score < 99 ? { profile: profile, score: score } : null;
    }).filter(Boolean).sort(function (left, right) {
      return left.score - right.score || poolRank(left.profile.pool_state) - poolRank(right.profile.pool_state) ||
        left.profile.name.localeCompare(right.profile.name);
    }).slice(0, Math.min(MAX_DIRECTORY_RESULTS, Math.max(1, Number(options.limit) || MAX_DIRECTORY_RESULTS)))
      .map(function (item) { return item.profile; });
  }

  function recordId(record) {
    return String(record && (record.opportunity_id || record.opportunity_number || record.title) || "");
  }

  function childId(record) {
    return String(record && (record.subtopic_id || record.opportunity_id) || "");
  }

  function create(data) {
    validateData(data);
    var facultyById = new Map();
    data.faculty.forEach(function (profile) {
      facultyById.set(profile.id, profile);
      (profile.legacy_ids || []).forEach(function (legacyId) { facultyById.set(legacyId, profile); });
    });
    var opportunityById = new Map(data.opportunities.map(function (opportunity) { return [opportunity.id, opportunity]; }));
    var opportunitiesByParent = new Map();
    data.opportunities.forEach(function (opportunity) {
      var values = opportunitiesByParent.get(opportunity.parent_id) || [];
      values.push(opportunity);
      opportunitiesByParent.set(opportunity.parent_id, values);
    });

    function scopesFor(parentId) {
      return (opportunitiesByParent.get(String(parentId)) || []).slice().sort(function (left, right) {
        return left.scope_label.localeCompare(right.scope_label);
      });
    }

    function resolveScope(options) {
      options = options || {};
      var record = options.record || null;
      var parentId = String(options.parentId || recordId(record));
      var requestedId = String(options.scopeId || "");
      var scopes = scopesFor(parentId);
      var opportunity = requestedId ? opportunityById.get(requestedId) : null;
      if (!opportunity && scopes.length === 1 && scopes[0].record_type === "specific_parent") {
        opportunity = scopes[0];
      }
      if (!opportunity || opportunity.parent_id !== parentId) {
        return { ok: false, reason: scopes.length ? "specific_scope_required" : "unsupported_scope", scopes: scopes };
      }
      var currentness = global.FUNDING_RETRIEVAL && global.FUNDING_RETRIEVAL.recordIsCurrent;
      if (typeof currentness !== "function") {
        return { ok: false, reason: "currentness_unavailable", scopes: scopes };
      }
      var now = options.now instanceof Date ? options.now : new Date(options.now || Date.now());
      if (!currentness(record, now)) {
        return { ok: false, reason: "not_current", scopes: scopes };
      }
      if (opportunity.record_type === "specific_parent" && options.isBroad === true) {
        return { ok: false, reason: "broad_parent_rejected", scopes: scopes };
      }
      if (opportunity.record_type === "publishable_child") {
        var children = options.childCatalog && options.childCatalog.opportunities;
        var eligible = Array.isArray(children) && children.some(function (child) {
          return childId(child) === opportunity.id && String(child.parent_id || "") === parentId;
        });
        if (!eligible) return { ok: false, reason: "child_not_publication_eligible", scopes: scopes };
      }
      return { ok: true, opportunity: opportunity, scopes: scopes };
    }

    function roleIsFilled(role, selectedIds) {
      if (role.coverage === "gap" || role.coverage === "adjacent") return false;
      return (role.candidate_ids || []).some(function (identifier) { return selectedIds.has(identifier); });
    }

    function proposal(opportunity) {
      if (!opportunityById.has(opportunity.id)) throw new Error("Unknown opportunity-team scope.");
      return {
        opportunityId: opportunity.id,
        selectedIds: opportunity.members.map(function (member) { return member.faculty_id; }),
        excludedIds: [],
      };
    }

    function proposalView(state) {
      var opportunity = opportunityById.get(String(state && state.opportunityId || ""));
      if (!opportunity) throw new Error("Unknown opportunity-team proposal.");
      var selectedIds = new Set((state.selectedIds || []).filter(function (id) { return facultyById.has(id); }).slice(0, 4));
      var excludedIds = new Set(state.excludedIds || []);
      var roles = opportunity.roles.map(function (role) {
        var filled = roleIsFilled(role, selectedIds);
        return Object.assign({}, role, {
          filled: filled,
          selected_candidate_ids: (role.candidate_ids || []).filter(function (id) { return selectedIds.has(id); }),
          selected_alternative_ids: (role.alternative_ids || []).filter(function (id) { return selectedIds.has(id); }),
        });
      });
      var unfilled = roles.filter(function (role) { return !role.filled; });
      var candidates = new Map();
      unfilled.forEach(function (role) {
        if (role.coverage === "gap" || role.coverage === "adjacent") return;
        [].concat(role.candidate_ids || [], role.alternative_ids || []).forEach(function (identifier) {
          if (selectedIds.has(identifier) || excludedIds.has(identifier) || !facultyById.has(identifier)) return;
          var item = candidates.get(identifier) || { profile: facultyById.get(identifier), roles: [], reviewed: true };
          item.roles.push(role);
          if ((role.alternative_ids || []).includes(identifier)) item.reviewed = false;
          candidates.set(identifier, item);
        });
      });
      var replacements = Array.from(candidates.values()).sort(function (left, right) {
        return right.roles.length - left.roles.length || poolRank(left.profile.pool_state) - poolRank(right.profile.pool_state) ||
          left.profile.name.localeCompare(right.profile.name);
      });
      var memberEvidence = new Map(opportunity.members.map(function (member) {
        return [member.faculty_id, member];
      }));
      var selected = Array.from(selectedIds).map(function (identifier) {
        return {
          profile: facultyById.get(identifier),
          evidence: memberEvidence.get(identifier) || null,
          roles: roles.filter(function (role) {
            return role.selected_candidate_ids.includes(identifier) || role.selected_alternative_ids.includes(identifier);
          }),
        };
      });
      return {
        opportunity: opportunity,
        selected: selected,
        roles: roles,
        unfilledRoles: unfilled,
        replacements: replacements,
        complete: unfilled.length === 0,
        selectedIds: Array.from(selectedIds),
        excludedIds: Array.from(excludedIds),
      };
    }

    function removeMember(state, facultyId) {
      var identifier = String(facultyId || "");
      return {
        opportunityId: state.opportunityId,
        selectedIds: (state.selectedIds || []).filter(function (id) { return id !== identifier; }),
        excludedIds: Array.from(new Set([].concat(state.excludedIds || [], identifier))),
      };
    }

    function addReplacement(state, facultyId) {
      var identifier = String(facultyId || "");
      var view = proposalView(state);
      if (view.selectedIds.length >= 4 || !view.replacements.some(function (item) { return item.profile.id === identifier; })) {
        throw new Error("That replacement is not eligible for the current missing roles.");
      }
      return {
        opportunityId: state.opportunityId,
        selectedIds: view.selectedIds.concat(identifier),
        excludedIds: (state.excludedIds || []).filter(function (id) { return id !== identifier; }),
      };
    }

    return Object.freeze({
      data: data,
      facultyById: facultyById,
      opportunityById: opportunityById,
      scopesFor: scopesFor,
      resolveScope: resolveScope,
      proposal: proposal,
      proposalView: proposalView,
      removeMember: removeMember,
      addReplacement: addReplacement,
    });
  }

  global.OpportunityTeam = Object.freeze({
    MAX_DIRECTORY_RESULTS: MAX_DIRECTORY_RESULTS,
    normalize: normalize,
    pageGenerationId: pageGenerationId,
    versionedAssetUrl: versionedAssetUrl,
    validateIndex: validateIndex,
    availabilityIndex: availabilityIndex,
    availableScopes: availableScopes,
    hasAvailableScope: hasAvailableScope,
    validateData: validateData,
    loadData: loadData,
    resetLoadForTest: resetLoadForTest,
    searchFaculty: searchFaculty,
    create: create,
  });
})(globalThis);
