(() => {
  "use strict";

  const STATES = new Set([
    "idle",
    "prefetching",
    "loading",
    "initializing",
    "ready",
    "failed",
  ]);
  const BOUNDED_SCRIPTS = globalThis.FUNDING_FINDER_APP?.boundedScripts;
  let metadata = globalThis.GRANT_CATALOG_METADATA;
  const listeners = new Set();
  let lifecycle = "idle";
  let inFlight = null;
  let readyCatalog = null;
  let initializer = null;
  let validator = null;
  let resetter = null;
  let injectedScript = null;
  let prefetchLink = null;
  let prefetchQueued = false;
  let visibilityBound = false;
  let metadataRefreshPromise = null;
  let lastError = "";
  let catalogAttemptSequence = 0;
  let activeCatalogAttempt = null;
  let publishedCatalog;
  const catalogAttempts = new Map();
  const metadataScriptSource = [...document.scripts]
    .map(script => script.src || "")
    .find(source => {
      try {
        const url = new URL(source, location.href);
        return url.origin === location.origin
          && url.pathname.endsWith("/data/catalog-metadata.js");
      } catch (_error) {
        return false;
      }
    }) || "";
  const counts = {
    requests: 0,
    executions: 0,
    initializations: 0,
    prefetches: 0,
    metadataRefreshes: 0,
    catalogScriptCleanups: 0,
    quarantinedCatalogAssignments: 0,
  };

  function installCatalogAssignmentGate() {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "GRANT_CATALOG");
    if (descriptor && !descriptor.configurable) {
      throw new Error("The funding catalog assignment gate could not be installed.");
    }
    Object.defineProperty(globalThis, "GRANT_CATALOG", {
      configurable: false,
      enumerable: true,
      get() {
        return publishedCatalog;
      },
      set(candidate) {
        const attemptId = document.currentScript?.dataset?.fundingCatalogAttempt || "";
        const attempt = catalogAttempts.get(attemptId);
        if (!attempt
          || attempt !== activeCatalogAttempt
          || attempt.status !== "loading") {
          counts.quarantinedCatalogAssignments += 1;
          return;
        }
        attempt.candidate = candidate;
      },
    });
  }

  function clearPublishedCatalog() {
    publishedCatalog = undefined;
  }

  function invalidateCatalogAttempt(attempt, status) {
    if (!attempt) return;
    attempt.status = status;
    attempt.candidate = undefined;
    if (activeCatalogAttempt === attempt) activeCatalogAttempt = null;
  }

  installCatalogAssignmentGate();

  function mark(name) {
    try {
      if (!performance.getEntriesByName(name, "mark").length) {
        performance.mark(name);
      }
    } catch (_error) {
      // Performance telemetry must never affect catalog availability.
    }
  }

  function boundedMessage(error, fallback) {
    const message = String(error?.message || error || fallback)
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 240);
    return message || fallback;
  }

  function snapshot() {
    return Object.freeze({
      state: lifecycle,
      error: lastError,
      ...counts,
      catalogUrl: metadata?.catalog_url || "",
      releaseIdentity: metadata?.release_identity || "",
    });
  }

  function notify() {
    const value = snapshot();
    listeners.forEach(listener => {
      try { listener(value); } catch (_error) { /* observer-only */ }
    });
  }

  function setState(next, error = "") {
    if (!STATES.has(next)) throw new Error("Unsupported catalog lifecycle state.");
    lifecycle = next;
    lastError = error;
    notify();
  }

  function statusIdentity(statusCounts) {
    return Object.entries(statusCounts || {})
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, value]) => `${key}=${Number(value) || 0}`)
      .join(",");
  }

  function catalogPipelineTimestamp(catalog) {
    const values = [
      catalog?.generated_at,
      catalog?.detail_enrichment_generated_at,
      catalog?.document_evidence_generated_at,
      catalog?.catalog_audit_generated_at,
      catalog?.link_health_generated_at,
      catalog?.diagnostics?.additional_sources?.merged_at,
    ].filter(Boolean);
    const parsed = values
      .map(value => {
        const text = String(value);
        const canonical = text.match(
          /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$/,
        );
        return {
          value: text,
          time: canonical
            ? Date.parse(`${canonical[1]}Z`)
            : Date.parse(text),
          fraction: canonical
            ? Number(String(canonical[2] || "").padEnd(9, "0").slice(0, 9))
            : 0,
        };
      })
      .filter(item => Number.isFinite(item.time))
      .sort((left, right) => (
        right.time - left.time || right.fraction - left.fraction
      ));
    if (!parsed.length) {
      throw new Error("The funding catalog has no valid pipeline timestamp.");
    }
    return parsed[0];
  }

  function catalogAssetVersion(catalog) {
    const selected = catalogPipelineTimestamp(catalog);
    const canonical = selected.value.match(
      /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/,
    );
    if (!canonical) {
      throw new Error("The funding catalog timestamp is not canonical UTC.");
    }
    const fraction = String(canonical[7] || "")
      .padEnd(6, "0")
      .slice(0, 6);
    const date = canonical.slice(1, 4).join("");
    const time = canonical.slice(4, 7).join("");
    return `catalog-${date}T${time}${fraction}Z`;
  }

  function releaseIdentity(catalog, assetVersion = catalogAssetVersion(catalog)) {
    const index = catalog?.search_index || {};
    return [
      `catalog-v${Number(catalog?.schema_version) || 0}`,
      assetVersion,
      `records=${Number(catalog?.record_count) || 0}`,
      `documents=${Number(index.document_count) || 0}`,
      `terms=${Object.keys(index.postings || {}).length}`,
      `status=${statusIdentity(catalog?.status_counts)}`,
    ].join(":");
  }

  function validatedMetadata() {
    if (!metadata || Number(metadata.schema_version) !== 1) {
      throw new Error("Catalog startup metadata is missing or unsupported.");
    }
    if (Number(metadata.catalog_schema_version) !== 3
      || Number(metadata.record_count) < 1000
      || !metadata.generated_at
      || !metadata.pipeline_generated_at
      || !metadata.asset_version
      || !metadata.release_identity) {
      throw new Error("Catalog startup metadata is incomplete.");
    }
    const url = new URL(metadata.catalog_url || "", location.href);
    if (url.origin !== location.origin
      || !url.pathname.endsWith("/data/opportunities.js")
      || url.searchParams.get("v") !== metadata.asset_version) {
      throw new Error("Catalog startup metadata requested an invalid asset URL.");
    }
    return { ...metadata, resolvedCatalogUrl: url.href };
  }

  function refreshMetadata() {
    if (metadataRefreshPromise) return metadataRefreshPromise;
    metadataRefreshPromise = new Promise((resolve, reject) => {
      let url;
      try {
        url = new URL(metadataScriptSource, location.href);
        if (url.origin !== location.origin
          || !url.pathname.endsWith("/data/catalog-metadata.js")) {
          throw new Error("Catalog startup metadata cannot be refreshed safely.");
        }
      } catch (error) {
        reject(error);
        return;
      }
      url.searchParams.set(
        "recovery",
        `${Date.now()}-${counts.metadataRefreshes + 1}`,
      );
      const script = document.createElement("script");
      script.async = true;
      script.src = url.href;
      script.dataset.fundingCatalogMetadataRecovery = "true";
      let settled = false;
      let timeout = null;
      const cleanup = () => {
        if (timeout !== null) BOUNDED_SCRIPTS.sidecar.clearTimeout(timeout);
        timeout = null;
        script.removeEventListener("load", onLoad);
        script.removeEventListener("error", onError);
        script.remove();
      };
      const finish = callback => {
        if (settled) return;
        settled = true;
        cleanup();
        callback();
      };
      const onLoad = () => finish(() => {
        try {
          metadata = globalThis.GRANT_CATALOG_METADATA;
          const refreshed = validatedMetadata();
          counts.metadataRefreshes += 1;
          resolve(refreshed);
        } catch (error) {
          reject(error);
        }
      });
      const onError = () => finish(() => {
        reject(new Error("Catalog startup metadata could not be refreshed."));
      });
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
      timeout = BOUNDED_SCRIPTS.sidecar.setTimeout(() => finish(() => {
        reject(new Error("Catalog startup metadata refresh timed out."));
      }));
      document.head.append(script);
    }).finally(() => {
      metadataRefreshPromise = null;
    });
    return metadataRefreshPromise;
  }

  async function validateLoadedCatalog(candidate, startup) {
    if (!candidate || Number(candidate.schema_version) !== Number(startup.catalog_schema_version)) {
      throw new Error("The funding catalog uses an unsupported schema.");
    }
    const candidateAssetVersion = catalogAssetVersion(candidate);
    const candidatePipelineTimestamp = catalogPipelineTimestamp(candidate).value;
    if (!Array.isArray(candidate.opportunities)
      || candidate.opportunities.length !== Number(startup.record_count)
      || Number(candidate.record_count) !== Number(startup.record_count)
      || candidate.generated_at !== startup.generated_at
      || candidatePipelineTimestamp !== startup.pipeline_generated_at
      || candidateAssetVersion !== startup.asset_version
      || statusIdentity(candidate.status_counts) !== statusIdentity(startup.status_counts)
      || releaseIdentity(candidate) !== startup.release_identity) {
      throw new Error("The funding catalog does not match its startup metadata.");
    }
    if (validator) await validator(candidate, startup);
  }

  function executeCatalogScript(url) {
    counts.requests += 1;
    mark("funding-catalog-requested");
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const attempt = {
        id: `catalog-attempt-${++catalogAttemptSequence}`,
        status: "loading",
        candidate: undefined,
      };
      catalogAttempts.set(attempt.id, attempt);
      activeCatalogAttempt = attempt;
      clearPublishedCatalog();
      script.async = true;
      script.src = url;
      script.dataset.fundingCatalog = "true";
      script.dataset.fundingCatalogAttempt = attempt.id;
      let settled = false;
      let timeout = null;
      const cleanup = ({ remove = false } = {}) => {
        counts.catalogScriptCleanups += 1;
        if (timeout !== null) BOUNDED_SCRIPTS.catalog.clearTimeout(timeout);
        timeout = null;
        script.removeEventListener("load", onLoad);
        script.removeEventListener("error", onError);
        if (remove) script.remove();
        if (injectedScript === script) injectedScript = null;
      };
      const finish = (callback, options) => {
        if (settled) return;
        settled = true;
        cleanup(options);
        callback();
      };
      const onLoad = () => finish(() => {
        if (attempt !== activeCatalogAttempt
          || attempt.status !== "loading"
          || !attempt.candidate) {
          invalidateCatalogAttempt(attempt, "invalid");
          clearPublishedCatalog();
          reject(new Error("The funding catalog script did not own a catalog assignment."));
          return;
        }
        const candidate = attempt.candidate;
        attempt.status = "loaded";
        publishedCatalog = candidate;
        counts.executions += 1;
        mark("funding-catalog-executed");
        resolve({ attempt, candidate });
      });
      const onError = () => finish(() => {
        invalidateCatalogAttempt(attempt, "failed");
        clearPublishedCatalog();
        reject(new Error("The funding catalog could not be downloaded."));
      }, { remove: true });
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
      timeout = BOUNDED_SCRIPTS.catalog.setTimeout(() => finish(() => {
        invalidateCatalogAttempt(attempt, "timed_out");
        clearPublishedCatalog();
        reject(new Error("The funding catalog request timed out."));
      }, { remove: true }));
      injectedScript = script;
      document.head.append(script);
    });
  }

  function catalogRequestUrl(startup, retrying) {
    if (!retrying) return startup.resolvedCatalogUrl;
    const url = new URL(startup.resolvedCatalogUrl);
    url.searchParams.set(
      "recovery",
      `${Date.now()}-${counts.metadataRefreshes}`,
    );
    return url.href;
  }

  async function ensureCatalogReady() {
    if (lifecycle === "ready" && readyCatalog) return readyCatalog;
    if (inFlight) return inFlight;
    const retrying = lifecycle === "failed";
    inFlight = (async () => {
      try {
        setState("loading");
        if (retrying) await refreshMetadata();
        const startup = validatedMetadata();
        const loaded = await executeCatalogScript(
          catalogRequestUrl(startup, retrying),
        );
        const { attempt, candidate } = loaded;
        await validateLoadedCatalog(candidate, startup);
        if (attempt !== activeCatalogAttempt || attempt.status !== "loaded") {
          throw new Error("The funding catalog attempt became stale before initialization.");
        }
        if (!initializer) throw new Error("Catalog initialization is unavailable.");
        setState("initializing");
        counts.initializations += 1;
        await initializer(candidate, startup);
        if (attempt !== activeCatalogAttempt || attempt.status !== "loaded") {
          throw new Error("The funding catalog attempt became stale during initialization.");
        }
        attempt.status = "accepted";
        publishedCatalog = candidate;
        readyCatalog = candidate;
        mark("funding-catalog-initialized");
        setState("ready");
        return candidate;
      } catch (error) {
        const message = boundedMessage(
          error,
          "The funding catalog could not be prepared.",
        );
        readyCatalog = null;
        try { await resetter?.(); } catch (_resetError) { /* best effort */ }
        if (injectedScript) injectedScript.remove();
        injectedScript = null;
        invalidateCatalogAttempt(activeCatalogAttempt, "failed");
        clearPublishedCatalog();
        setState("failed", message);
        throw new Error(message);
      } finally {
        if (lifecycle !== "ready") inFlight = null;
      }
    })();
    return inFlight;
  }

  function connectionBlocksPrefetch() {
    const connection = navigator.connection
      || navigator.mozConnection
      || navigator.webkitConnection;
    const type = String(connection?.effectiveType || "").toLowerCase();
    return connection?.saveData === true || type === "slow-2g" || type === "2g";
  }

  function whenVisible() {
    if (visibilityBound) return;
    visibilityBound = true;
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        visibilityBound = false;
        schedulePrefetch();
      }
    }, { once: true });
  }

  function addPrefetch() {
    prefetchQueued = false;
    if (document.hidden) {
      whenVisible();
      return;
    }
    if (connectionBlocksPrefetch()
      || prefetchLink
      || ["loading", "initializing", "ready"].includes(lifecycle)) return;
    let startup;
    try { startup = validatedMetadata(); } catch (_error) { return; }
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.as = "script";
    link.href = startup.resolvedCatalogUrl;
    link.dataset.fundingCatalogPrefetch = "true";
    prefetchLink = link;
    counts.prefetches += 1;
    setState("prefetching");
    document.head.append(link);
  }

  function queuePrefetch() {
    if (prefetchQueued || prefetchLink
      || ["loading", "initializing", "ready"].includes(lifecycle)) return;
    if (document.hidden) {
      whenVisible();
      return;
    }
    if (connectionBlocksPrefetch()) return;
    prefetchQueued = true;
    const schedule = globalThis.requestIdleCallback
      ? callback => globalThis.requestIdleCallback(callback, { timeout: 1500 })
      : callback => globalThis.setTimeout(callback, 600);
    schedule(addPrefetch);
  }

  function schedulePrefetch() {
    if (document.readyState === "complete") queuePrefetch();
    else globalThis.addEventListener("load", queuePrefetch, { once: true });
  }

  function configure(options = {}) {
    if (initializer && options.initialize && initializer !== options.initialize) {
      throw new Error("The catalog loader was already configured.");
    }
    initializer = options.initialize || initializer;
    validator = options.validate || validator;
    resetter = options.reset || resetter;
    return api;
  }

  function subscribe(listener) {
    if (typeof listener !== "function") return () => {};
    listeners.add(listener);
    listener(snapshot());
    return () => listeners.delete(listener);
  }

  const api = Object.freeze({
    configure,
    ensureCatalogReady,
    getMetadata: () => metadata,
    getSnapshot: snapshot,
    releaseIdentity,
    catalogTimeoutMs: Number(BOUNDED_SCRIPTS?.catalog?.timeoutMs || 0),
    sidecarTimeoutMs: Number(BOUNDED_SCRIPTS?.sidecar?.timeoutMs || 0),
    schedulePrefetch,
    subscribe,
  });

  globalThis.FUNDING_CATALOG_LOADER = api;
})();
