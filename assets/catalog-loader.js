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
  const metadata = globalThis.GRANT_CATALOG_METADATA;
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
  let lastError = "";
  const counts = {
    requests: 0,
    executions: 0,
    initializations: 0,
    prefetches: 0,
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

  function releaseIdentity(catalog, assetVersion) {
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

  async function validateLoadedCatalog(candidate, startup) {
    if (!candidate || Number(candidate.schema_version) !== Number(startup.catalog_schema_version)) {
      throw new Error("The funding catalog uses an unsupported schema.");
    }
    if (!Array.isArray(candidate.opportunities)
      || candidate.opportunities.length !== Number(startup.record_count)
      || Number(candidate.record_count) !== Number(startup.record_count)
      || candidate.generated_at !== startup.generated_at
      || statusIdentity(candidate.status_counts) !== statusIdentity(startup.status_counts)
      || releaseIdentity(candidate, startup.asset_version) !== startup.release_identity) {
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

  async function ensureCatalogReady() {
    if (lifecycle === "ready" && readyCatalog) return readyCatalog;
    if (inFlight) return inFlight;
    inFlight = (async () => {
      try {
        const startup = validatedMetadata();
        setState("loading");
        const candidate = await executeCatalogScript(startup.resolvedCatalogUrl);
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
