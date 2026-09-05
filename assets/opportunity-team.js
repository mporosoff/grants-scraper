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
        !Array.isArray(index.scopes) || index.scopes.length > 2000 ||
        (index.scope_count != null && index.scopes.length !== index.scope_count)) {
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
      if (scope.review_state === "needs_revalidation") return false;
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
        !Array.isArray(data.opportunities) || data.opportunities.length > 2000 ||
        (data.scope_count != null && data.opportunities.length !== data.scope_count) ||
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
            source_urls: claim.source_urls || [],
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
          !Array.isArray(opportunity.members) || opportunity.members.length < 2 || opportunity.members.length > 4 ||
          !Array.isArray(opportunity.roles) || opportunity.roles.length < 1 || opportunity.roles.length > 8 ||
          opportunity.members.some(function (member) { return !facultyIds.has(member.faculty_id); }) ||
          (opportunity.variants || []).some(function (variant) {
            return !Array.isArray(variant.member_ids) || variant.member_ids.length < 2 || variant.member_ids.length > 4 ||
              new Set(variant.member_ids).size !== variant.member_ids.length || variant.member_ids.some(function (id) { return !facultyIds.has(id); });
          })) {
        throw new Error("The opportunity-team role model is invalid.");
      }
    });
    var indexedScopes = validateIndex(
      global.OPPORTUNITY_TEAM_INDEX,
      expectedGenerationId || data.generation_id,
    ).scopes;
    var projectedScopes = data.opportunities.map(function (opportunity) {
      var scope = {
        id: opportunity.id,
        parent_id: opportunity.parent_id,
        record_type: opportunity.record_type,
      };
      if (opportunity.review_state) scope.review_state = opportunity.review_state;
      return scope;
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
    return (data.faculty || []).filter(function (profile) {
      return (!profile.status || profile.status === "active") && profile.pool_visibility !== "hidden";
    }).map(function (profile) {
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

  function eligibleProfile(profile) {
    return Boolean(profile && profile.status === "active" && profile.auto_proposable === true &&
      ["main", "standby"].includes(profile.pool_state) &&
      !["hidden", "reference_only"].includes(profile.pool_visibility));
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
      return (opportunitiesByParent.get(String(parentId)) || []).filter(function (scope) {
        return scope.review_state !== "needs_revalidation";
      }).sort(function (left, right) {
        return left.scope_label.localeCompare(right.scope_label);
      });
    }

    function resolveScope(options) {
      options = options || {};
      var record = options.record || null;
      var parentId = String(options.parentId || recordId(record));
      var requestedId = String(options.scopeId || "");
      var publishedChildren = options.childCatalog && options.childCatalog.opportunities;
      var scopes = scopesFor(parentId).filter(function (scope) {
        return scope.record_type !== "publishable_child" || !Array.isArray(publishedChildren) || publishedChildren.some(function (child) {
          return childId(child) === scope.id && String(child.parent_id || "") === parentId;
        });
      });
      var opportunity = requestedId ? opportunityById.get(requestedId) : null;
      if (!opportunity && scopes.length === 1 && scopes[0].record_type === "specific_parent") {
        opportunity = scopes[0];
      }
      if (!opportunity || opportunity.parent_id !== parentId) {
        return { ok: false, reason: scopes.length ? "specific_scope_required" : "unsupported_scope", scopes: scopes };
      }
      if (opportunity.review_state === "needs_revalidation") {
        return { ok: false, reason: "needs_revalidation", scopes: scopes.filter(function (scope) {
          return scope.review_state !== "needs_revalidation";
        }) };
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

    function roleHasDirectEvidence(role, selectedIds) {
      if (!roleIsFilled(role, selectedIds)) return false;
      if (!role.claim_refs) return role.coverage === "direct" || role.coverage === "direct_and_adjacent";
      return role.claim_refs.some(function (ref) { return ref.coverage === "direct" && selectedIds.has(ref.researcher_id); });
    }

    function teamFitness(opportunity, ids) {
      var selected = new Set(ids);
      var required = opportunity.roles.filter(function (role) { return role.required !== false; });
      return { missing: required.filter(function (role) { return !roleIsFilled(role, selected); }).length,
        direct: required.filter(function (role) { return roleHasDirectEvidence(role, selected); }).length };
    }

    function proposal(opportunity) {
      if (!opportunityById.has(opportunity.id)) throw new Error("Unknown opportunity-team scope.");
      if (opportunity.review_state === "needs_revalidation") throw new Error("This team needs revalidation.");
      var teams = [opportunity.members.map(function (member) { return member.faculty_id; })]
        .concat((opportunity.variants || []).map(function (variant) { return variant.member_ids; }))
        .map(function (ids) { return ids.filter(function (id) { return eligibleProfile(facultyById.get(id)); }); });
      teams.sort(function (a, b) {
        var left = teamFitness(opportunity, a), right = teamFitness(opportunity, b);
        return left.missing - right.missing || right.direct - left.direct || a.length - b.length;
      });
      return {
        opportunityId: opportunity.id,
        selectedIds: teams[0],
        excludedIds: [],
      };
    }

    function candidatesForRole(role) {
      if (role.coverage === "gap" || role.coverage === "adjacent") return [];
      var reviewed = new Set(role.candidate_ids || []);
      var identifiers = new Set([].concat(role.candidate_ids || [], role.alternative_ids || []));
      var accepted = new Set((role.accepted_terms || []).map(normalize));
      // New researchers participate immediately through current retained claims.
      // Vocabulary agreement proposes a replacement; it never certifies coverage.
      data.faculty.forEach(function (profile) {
        if (eligibleProfile(profile) && profile.terms.some(function (term) { return accepted.has(normalize(term.label)); })) {
          identifiers.add(profile.id);
        }
      });
      return Array.from(identifiers).filter(function (id) { return eligibleProfile(facultyById.get(id)); })
        .map(function (id) { return { id: id, reviewed: reviewed.has(id) }; });
    }

    function proposalView(state) {
      var opportunity = opportunityById.get(String(state && state.opportunityId || ""));
      if (!opportunity) throw new Error("Unknown opportunity-team proposal.");
      if (opportunity.review_state === "needs_revalidation") throw new Error("This team needs revalidation.");
      var selectedIds = new Set((state.selectedIds || []).filter(function (id) { return eligibleProfile(facultyById.get(id)); }).slice(0, 4));
      var excludedIds = new Set(state.excludedIds || []);
      var roles = opportunity.roles.map(function (role) {
        var filled = roleIsFilled(role, selectedIds);
        return Object.assign({}, role, {
          filled: filled,
          directEvidence: roleHasDirectEvidence(role, selectedIds),
          selected_candidate_ids: (role.candidate_ids || []).filter(function (id) { return selectedIds.has(id); }),
          selected_alternative_ids: candidatesForRole(role).filter(function (candidate) {
            return !candidate.reviewed && selectedIds.has(candidate.id);
          }).map(function (candidate) { return candidate.id; }),
        });
      });
      var unfilled = roles.filter(function (role) { return role.required !== false && !role.filled; });
      var candidates = new Map();
      unfilled.forEach(function (role) {
        if (role.coverage === "gap" || role.coverage === "adjacent") return;
        candidatesForRole(role).forEach(function (candidate) {
          var identifier = candidate.id;
          if (selectedIds.has(identifier) || excludedIds.has(identifier) || !facultyById.has(identifier)) return;
          var item = candidates.get(identifier) || { profile: facultyById.get(identifier), roles: [], reviewed: true };
          item.roles.push(role);
          if (!candidate.reviewed) item.reviewed = false;
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
        var profile = facultyById.get(identifier);
        var evidence = memberEvidence.get(identifier) || null;
        var attributedRoles = roles.filter(function (role) {
          return role.selected_candidate_ids.includes(identifier) || role.selected_alternative_ids.includes(identifier);
        });
        if (!evidence) {
          attributedRoles.some(function (role) {
            var reference = (role.claim_refs || []).find(function (ref) {
              return ref.researcher_id === identifier && ref.coverage !== "adjacent";
            });
            var term = reference && profile.terms.find(function (claim) {
              return claim.claim_id === reference.claim_id && claim.claim_revision === reference.revision;
            });
            if (!term) return false;
            evidence = { contribution: role.label, evidence_term: term.label, evidence_phrase: term.evidence,
              source_url: term.source_urls[0] || profile.source_url,
              why_person: reference.reason || (term.evidence + " supports " +
                (reference.coverage === "method_transfer" ? "a methodological transfer to " : "the contribution of ") +
                role.label.toLowerCase() + "." + (reference.coverage === "method_transfer" ? " The specific application remains to be established." : "")) };
            return true;
          });
        }
        return {
          profile: profile,
          evidence: evidence,
          roles: attributedRoles,
          relevantTerms: profile.terms.filter(function (term) {
            return attributedRoles.some(function (role) {
              return (role.accepted_terms || []).some(function (label) { return normalize(label) === normalize(term.label); });
            });
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

    function proposalOptions(state) {
      var opportunity = opportunityById.get(String(state.opportunityId));
      if (!opportunity || opportunity.review_state === "needs_revalidation") return [];
      var excluded = new Set(state.excludedIds || []);
      var original = proposal(opportunity).selectedIds.filter(function (id) { return !excluded.has(id); });
      var options = [];
      var seen = new Set();
      function add(ids) {
        var selected = Array.from(new Set(ids)).filter(function (id) { return !excluded.has(id) && eligibleProfile(facultyById.get(id)); });
        if (selected.length < 2 || selected.length > 4) return;
        if (opportunity.assembly_version) {
          var covered = opportunity.roles.filter(function (role) { return roleIsFilled(role, new Set(selected)); });
          if (covered.length < 2 || selected.some(function (omitted) {
            var remaining = new Set(selected.filter(function (id) { return id !== omitted; }));
            return covered.every(function (role) { return roleIsFilled(role, remaining); });
          })) return;
        }
        var signature = selected.slice().sort().join("|");
        if (seen.has(signature)) return;
        seen.add(signature);
        var proposalState = { opportunityId: opportunity.id, selectedIds: selected, excludedIds: Array.from(excluded) };
        var view = proposalView(proposalState);
        options.push({ state: proposalState, missing: view.unfilledRoles.length,
          direct: teamFitness(opportunity, selected).direct,
          label: selected.map(function (id) { return facultyById.get(id).name; }).join(" + ") });
      }
      add(original);
      (opportunity.variants || []).forEach(function (variant) { add(variant.member_ids || []); });
      opportunity.roles.forEach(function (role) {
        candidatesForRole(role).slice(0, 12).forEach(function (candidate) {
          if (excluded.has(candidate.id) || original.includes(candidate.id)) return;
          var replaceable = original.filter(function (id) { return (role.candidate_ids || []).includes(id); });
          if (!replaceable.length && original.length < 4) add(original.concat(candidate.id));
          replaceable.forEach(function (id) { add(original.map(function (selected) { return selected === id ? candidate.id : selected; })); });
        });
      });
      options.sort(function (a, b) { return a.missing - b.missing || b.direct - a.direct; });
      return options.filter(function (option) { return option.missing === options[0].missing; }).slice(0, 3);
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
      proposalOptions: proposalOptions,
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
