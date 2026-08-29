(function (global) {
  "use strict";

  var SCHEMA_FAMILY = "hajim-faculty-match";
  var DIRECTORY_SCHEMA = 2;
  var GRAPH_SCHEMA = 4;
  var MAX_RESULTS = 12;
  var graphPromise = null;
  var directoryPromise = null;

  function pageGenerationId() {
    var marker = document.querySelector('meta[name="hajim-match-generation"]');
    var generationId = marker && marker.getAttribute("content");
    if (!/^[a-f0-9]{64}$/.test(generationId || "")) {
      throw new Error("The page does not declare a valid Hajim faculty generation.");
    }
    return generationId;
  }

  function versionedAssetUrl(path, generationId) {
    if (!/^[a-f0-9]{64}$/.test(generationId || "")) {
      throw new Error("A valid Hajim faculty generation is required for asset loading.");
    }
    return path + (path.indexOf("?") === -1 ? "?" : "&") + "v=" + generationId;
  }

  function normalize(value) {
    return String(value == null ? "" : value).normalize("NFC").toLocaleLowerCase().replace(/&/g, " and ").replace(/\s+/g, " ").trim();
  }

  function catalogCompatible(identity, catalog) {
    if (!identity || !catalog) return false;
    var records = Array.isArray(catalog.opportunities) ? catalog.opportunities : [];
    return identity.record_count === records.length && identity.record_count === catalog.record_count &&
      identity.generated_at === (catalog.generated_at || "") && /^[a-f0-9]{64}$/.test(identity.fingerprint || "");
  }

  function validateIdentity(asset, expectedGenerationId) {
    var fingerprints = asset && asset.projection_fingerprints;
    if (!asset || !/^[a-f0-9]{64}$/.test(asset.generation_id || "") ||
        asset.asset_version !== asset.generation_id ||
        !fingerprints || !/^[a-f0-9]{64}$/.test(fingerprints.directory || "") ||
        !/^[a-f0-9]{64}$/.test(fingerprints.graph || "") ||
        (expectedGenerationId && asset.generation_id !== expectedGenerationId)) {
      throw new Error("The Hajim faculty asset does not match the page generation.");
    }
  }

  function validateDirectory(directory, catalog, expectedGenerationId) {
    if (!directory || directory.schema_family !== SCHEMA_FAMILY || directory.schema_version !== DIRECTORY_SCHEMA) {
      throw new Error("The Hajim faculty directory has an incompatible schema.");
    }
    validateIdentity(directory, expectedGenerationId);
    var source = directory.faculty_source || {};
    var workbook = source.workbook || {};
    if (!Array.isArray(directory.profiles) || directory.profiles.length !== 158 ||
        source.union_record_count !== 158 || source.union_rankable_record_count !== 148 ||
        source.union_unrankable_count !== 10 || workbook.record_count !== 156 ||
        workbook.rankable_record_count !== 145 || workbook.unlisted_interest_count !== 11) {
      throw new Error("The Hajim faculty directory has incompatible roster counts.");
    }
    if (catalog && !catalogCompatible(directory.catalog, catalog)) {
      throw new Error("The Hajim faculty directory was built for a different opportunity catalog.");
    }
    return directory;
  }

  function validateGraph(graph, directory, catalog, expectedGenerationId) {
    if (!graph || graph.schema_family !== SCHEMA_FAMILY || graph.schema_version !== GRAPH_SCHEMA ||
        !Array.isArray(graph.edges) || !graph.by_faculty || !graph.by_opportunity ||
        !graph.by_opportunity_primary) {
      throw new Error("The Hajim faculty match data has an incompatible schema.");
    }
    validateIdentity(graph, expectedGenerationId);
    if (!directory || graph.generation_id !== directory.generation_id ||
        graph.asset_version !== directory.asset_version ||
        JSON.stringify(graph.projection_fingerprints) !== JSON.stringify(directory.projection_fingerprints) ||
        JSON.stringify(graph.catalog) !== JSON.stringify(directory.catalog) ||
        JSON.stringify(graph.faculty_source) !== JSON.stringify(directory.faculty_source)) {
      throw new Error("The Hajim faculty directory and match data are out of sync.");
    }
    if (catalog && !catalogCompatible(graph.catalog, catalog)) {
      throw new Error("The Hajim faculty match data was built for a different opportunity catalog.");
    }
    return graph;
  }

  function search(directory, query, options) {
    options = options || {};
    var value = normalize(query);
    if (!options.showAll && value.length < 2) return [];
    var terms = value.split(" ").filter(Boolean);
    var queryParts = value.split(/[^a-z0-9\u00c0-\u024f]+/).filter(Boolean);
    var ranked = [];
    (directory.profiles || []).forEach(function (profile) {
      var name = normalize(profile.name);
      var aliasNames = (profile.aliases || []).map(normalize);
      var aliases = aliasNames.join(" ");
      var unit = normalize(profile.home_unit);
      var rosters = normalize((profile.rosters || []).join(" "));
      var interests = normalize([
        profile.search_document,
        profile.research_summary,
        (profile.research_domains || []).join(" ")
      ].join(" "));
      var score = 99;
      if (!value) score = 10;
      else if (name === value) score = 0;
      else if (name.indexOf(value) === 0 || terms.every(function (term) { return name.split(" ").some(function (part) { return part.indexOf(term) === 0; }); })) score = 1;
      else if (aliasNames.some(function (alias) {
        var parts = alias.split(/[^a-z0-9\u00c0-\u024f]+/).filter(Boolean);
        return alias === value || alias.indexOf(value) === 0 || queryParts.every(function (term) {
          return parts.some(function (part) { return part.indexOf(term) === 0; });
        });
      })) score = 1;
      else if (name.indexOf(value) !== -1 || aliases.indexOf(value) !== -1) score = 2;
      else if (unit.indexOf(value) !== -1 || rosters.indexOf(value) !== -1) score = 3;
      else if (terms.every(function (term) { return interests.indexOf(term) !== -1; })) score = 4;
      if (score < 99) ranked.push({ profile: profile, score: score });
    });
    ranked.sort(function (left, right) {
      return left.score - right.score || left.profile.name.localeCompare(right.profile.name);
    });
    return ranked.slice(0, Math.min(MAX_RESULTS, Math.max(1, options.limit || MAX_RESULTS))).map(function (item) { return item.profile; });
  }

  function injectScript(src, globalName) {
    return new Promise(function (resolve, reject) {
      var boundedScript = global.FUNDING_FINDER_APP &&
        global.FUNDING_FINDER_APP.boundedScripts &&
        global.FUNDING_FINDER_APP.boundedScripts.sidecar;
      var existing = document.querySelector('script[data-hajim-asset="' + globalName + '"]');
      if (global[globalName]) return resolve(global[globalName]);
      if (!boundedScript) return reject(new Error("The bounded faculty asset loader is unavailable."));
      var settled = false;
      var timeout = null;
      function cleanup(script, remove) {
        if (timeout !== null) boundedScript.clearTimeout(timeout);
        timeout = null;
        script.removeEventListener("load", onLoad);
        script.removeEventListener("error", onError);
        if (remove) script.remove();
      }
      function finish(script, callback, remove) {
        if (settled) return;
        settled = true;
        cleanup(script, remove);
        callback();
      }
      function loaded(script) {
        if (settled) return;
        script.dataset.hajimState = "loaded";
        if (global[globalName]) finish(script, function () { resolve(global[globalName]); }, false);
        else {
          finish(script, function () { reject(new Error(globalName + " did not initialize.")); }, true);
        }
      }
      function failed(script) {
        if (settled) return;
        script.dataset.hajimState = "failed";
        finish(script, function () { reject(new Error("Unable to load " + globalName)); }, true);
      }
      function onLoad() { loaded(this); }
      function onError() { failed(this); }
      function watch(script) {
        script.addEventListener("load", onLoad, { once: true });
        script.addEventListener("error", onError, { once: true });
        timeout = boundedScript.setTimeout(function () {
          if (settled) return;
          script.dataset.hajimState = "timed-out";
          finish(script, function () {
            reject(new Error("Timed out loading " + globalName));
          }, true);
        });
      }
      if (existing && existing.dataset.hajimState !== "loading") {
        existing.remove();
        existing = null;
      }
      if (existing) {
        watch(existing);
        if (global[globalName]) loaded(existing);
        return;
      }
      var script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.hajimAsset = globalName;
      script.dataset.hajimState = "loading";
      watch(script);
      document.head.appendChild(script);
    });
  }

  function discardAsset(globalName) {
    try { delete global[globalName]; } catch (_error) { global[globalName] = undefined; }
    document.querySelectorAll('script[data-hajim-asset="' + globalName + '"]').forEach(function (script) {
      script.remove();
    });
  }

  function loadDirectory(catalog, src, expectedGenerationId) {
    if (!directoryPromise) {
      directoryPromise = Promise.resolve(global.HAJIM_FACULTY_DIRECTORY || null).then(function (value) {
        return value || injectScript(src || "data/hajim_faculty_directory.js", "HAJIM_FACULTY_DIRECTORY");
      }).then(function (directory) { return validateDirectory(directory, catalog, expectedGenerationId); }).catch(function (error) {
        discardAsset("HAJIM_FACULTY_DIRECTORY");
        directoryPromise = null;
        throw error;
      });
    }
    return directoryPromise;
  }

  function loadGraph(directory, catalog, src, expectedGenerationId) {
    if (!graphPromise) {
      graphPromise = Promise.resolve(global.FACULTY_MATCHES || null).then(function (value) {
        return value || injectScript(src || "data/faculty_matches.js", "FACULTY_MATCHES");
      }).then(function (graph) { return validateGraph(graph, directory, catalog, expectedGenerationId); }).catch(function (error) {
        discardAsset("FACULTY_MATCHES");
        graphPromise = null;
        throw error;
      });
    }
    return graphPromise;
  }

  function resetLoadsForTest() {
    graphPromise = null;
    directoryPromise = null;
  }

  function opportunityMatches(graph, directory, opportunityId, primaryOnly) {
    var profiles = {};
    (directory.profiles || []).forEach(function (profile) { profiles[profile.faculty_id] = profile; });
    var indexFamily = primaryOnly ? graph.by_opportunity_primary : graph.by_opportunity;
    return (indexFamily[String(opportunityId)] || []).map(function (index) {
      var edge = graph.edges[index];
      var profile = profiles[edge.faculty_id];
      if (!profile) return null;
      if (primaryOnly && profile.relationship !== "hajim_primary_core" && profile.relationship !== "hajim_research") return null;
      return { edge: edge, profile: profile, contact: (graph.contacts || {})[edge.faculty_id] || {} };
    }).filter(Boolean);
  }

  function facultyMatches(graph, facultyId) {
    return (graph.by_faculty[String(facultyId)] || []).map(function (index) { return graph.edges[index]; });
  }

  global.HajimFaculty = Object.freeze({
    MAX_RESULTS: MAX_RESULTS,
    normalize: normalize,
    pageGenerationId: pageGenerationId,
    versionedAssetUrl: versionedAssetUrl,
    search: search,
    validateDirectory: validateDirectory,
    validateGraph: validateGraph,
    loadDirectory: loadDirectory,
    loadGraph: loadGraph,
    opportunityMatches: opportunityMatches,
    facultyMatches: facultyMatches,
    resetLoadsForTest: resetLoadsForTest
  });
})(globalThis);
