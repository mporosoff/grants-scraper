(function (global) {
  "use strict";

  var SCHEMA_FAMILY = "hajim-faculty-match";
  var DIRECTORY_SCHEMA = 1;
  var GRAPH_SCHEMA = 2;
  var MAX_RESULTS = 12;
  var graphPromise = null;
  var directoryPromise = null;

  function normalize(value) {
    return String(value == null ? "" : value).normalize("NFC").toLocaleLowerCase().replace(/&/g, " and ").replace(/\s+/g, " ").trim();
  }

  function catalogCompatible(identity, catalog) {
    if (!identity || !catalog) return false;
    var records = Array.isArray(catalog.opportunities) ? catalog.opportunities : [];
    return identity.record_count === records.length && identity.record_count === catalog.record_count &&
      identity.generated_at === (catalog.generated_at || "") && /^[a-f0-9]{64}$/.test(identity.fingerprint || "");
  }

  function validateDirectory(directory, catalog) {
    if (!directory || directory.schema_family !== SCHEMA_FAMILY || directory.schema_version !== DIRECTORY_SCHEMA) {
      throw new Error("The Hajim faculty directory has an incompatible schema.");
    }
    var source = directory.faculty_source || {};
    if (!Array.isArray(directory.profiles) || directory.profiles.length !== 156 ||
        source.record_count !== 156 || source.rankable_record_count !== 145 || source.unlisted_interest_count !== 11) {
      throw new Error("The Hajim faculty directory has incompatible roster counts.");
    }
    if (catalog && !catalogCompatible(directory.catalog, catalog)) {
      throw new Error("The Hajim faculty directory was built for a different opportunity catalog.");
    }
    return directory;
  }

  function validateGraph(graph, directory, catalog) {
    if (!graph || graph.schema_family !== SCHEMA_FAMILY || graph.schema_version !== GRAPH_SCHEMA ||
        !Array.isArray(graph.edges) || !graph.by_faculty || !graph.by_opportunity) {
      throw new Error("The Hajim faculty match data has an incompatible schema.");
    }
    if (!directory || graph.generation_id !== directory.generation_id ||
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
    var ranked = [];
    (directory.profiles || []).forEach(function (profile) {
      var name = normalize(profile.name);
      var unit = normalize(profile.home_unit);
      var rosters = normalize((profile.rosters || []).join(" "));
      var interests = normalize(profile.search_document);
      var score = 99;
      if (!value) score = 10;
      else if (name === value) score = 0;
      else if (name.indexOf(value) === 0 || terms.every(function (term) { return name.split(" ").some(function (part) { return part.indexOf(term) === 0; }); })) score = 1;
      else if (name.indexOf(value) !== -1) score = 2;
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
      var existing = document.querySelector('script[data-hajim-asset="' + globalName + '"]');
      if (global[globalName]) return resolve(global[globalName]);
      function loaded(script) {
        script.dataset.hajimState = "loaded";
        if (global[globalName]) resolve(global[globalName]);
        else {
          script.remove();
          reject(new Error(globalName + " did not initialize."));
        }
      }
      function failed(script) {
        script.dataset.hajimState = "failed";
        script.remove();
        reject(new Error("Unable to load " + globalName));
      }
      if (existing && existing.dataset.hajimState !== "loading") {
        existing.remove();
        existing = null;
      }
      if (existing) {
        existing.addEventListener("load", function () { loaded(existing); }, { once: true });
        existing.addEventListener("error", function () { failed(existing); }, { once: true });
        return;
      }
      var script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.hajimAsset = globalName;
      script.dataset.hajimState = "loading";
      script.addEventListener("load", function () { loaded(script); }, { once: true });
      script.addEventListener("error", function () { failed(script); }, { once: true });
      document.head.appendChild(script);
    });
  }

  function loadDirectory(catalog, src) {
    if (!directoryPromise) {
      directoryPromise = Promise.resolve(global.HAJIM_FACULTY_DIRECTORY || null).then(function (value) {
        return value || injectScript(src || "data/hajim_faculty_directory.js", "HAJIM_FACULTY_DIRECTORY");
      }).then(function (directory) { return validateDirectory(directory, catalog); }).catch(function (error) {
        directoryPromise = null;
        throw error;
      });
    }
    return directoryPromise;
  }

  function loadGraph(directory, catalog, src) {
    if (!graphPromise) {
      graphPromise = Promise.resolve(global.FACULTY_MATCHES || null).then(function (value) {
        return value || injectScript(src || "data/faculty_matches.js", "FACULTY_MATCHES");
      }).then(function (graph) { return validateGraph(graph, directory, catalog); }).catch(function (error) {
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
    return (graph.by_opportunity[String(opportunityId)] || []).map(function (index) {
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
