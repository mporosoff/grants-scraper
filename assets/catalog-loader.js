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
  };

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
    const stamp = new Date(catalogPipelineTimestamp(catalog).time)
      .toISOString()
      .replace(/[-:]/g, "")
      .replace(/\.\d{3}Z$/, "Z");
    return `catalog-${stamp}`;
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
      const timeout = globalThis.setTimeout(() => {
        script.remove();
        reject(new Error("Catalog startup metadata refresh timed out."));
      }, 15_000);
      script.addEventListener("load", () => {
        globalThis.clearTimeout(timeout);
        script.remove();
        try {
          metadata = globalThis.GRANT_CATALOG_METADATA;
          const refreshed = validatedMetadata();
          counts.metadataRefreshes += 1;
          resolve(refreshed);
        } catch (error) {
          reject(error);
        }
      }, { once: true });
      script.addEventListener("error", () => {
        globalThis.clearTimeout(timeout);
        script.remove();
        reject(new Error("Catalog startup metadata could not be refreshed."));
      }, { once: true });
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
    if (globalThis.GRANT_CATALOG) return Promise.resolve(globalThis.GRANT_CATALOG);
    counts.requests += 1;
    mark("funding-catalog-requested");
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.async = true;
      script.src = url;
      script.dataset.fundingCatalog = "true";
      script.addEventListener("load", () => {
        counts.executions += 1;
        mark("funding-catalog-executed");
        resolve(globalThis.GRANT_CATALOG);
      }, { once: true });
      script.addEventListener("error", () => {
        reject(new Error("The funding catalog could not be downloaded."));
      }, { once: true });
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
        const candidate = await executeCatalogScript(
          catalogRequestUrl(startup, retrying),
        );
        await validateLoadedCatalog(candidate, startup);
        if (!initializer) throw new Error("Catalog initialization is unavailable.");
        setState("initializing");
        counts.initializations += 1;
        await initializer(candidate, startup);
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
        try { delete globalThis.GRANT_CATALOG; } catch (_error) {
          globalThis.GRANT_CATALOG = undefined;
        }
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
    schedulePrefetch,
    subscribe,
  });

  globalThis.FUNDING_CATALOG_LOADER = api;
})();
