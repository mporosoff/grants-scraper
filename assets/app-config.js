(() => {
  "use strict";

  const release = Object.freeze({
    version: "1.3.0",
    updated: "2026-08-30",
  });
  const productionFlags = Object.freeze({
    subtopics: true,
    matchExplanations: true,
    searchV2: true,
  });
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = localHosts.has(globalThis.location?.hostname || "");
  const parameters = new URLSearchParams(globalThis.location?.search || "");
  const productionHybridProxy = "https://funding-finder-voyage-search.urochestercheme.workers.dev/";

  function localHybridProxy() {
    if (!local) return "";
    const value = String(parameters.get("ff-hybrid-proxy") || "").trim();
    if (!value) return "";
    try {
      const url = new URL(value, globalThis.location?.href || "http://localhost/");
      const localProxy = url.protocol === "http:"
        && localHosts.has(url.hostname);
      return url.protocol === "https:" || localProxy ? url.href : "";
    } catch {
      return "";
    }
  }

  const flags = Object.freeze({
    subtopics: productionFlags.subtopics || (
      local && parameters.get("ff-subtopics") === "1"
    ),
    matchExplanations: productionFlags.matchExplanations || (
      local && parameters.get("ff-explain") === "1"
    ),
    searchV2: productionFlags.searchV2 || (
      local && parameters.get("ff-search-v2") === "1"
    ),
  });
  const hybridSearch = Object.freeze({
    proxyUrl: productionHybridProxy || localHybridProxy(),
    manifestUrl: "./data/search-v2-voyage-manifest.json",
    vectorUrl: "./data/search-v2-voyage-vectors.f16",
    timeoutMs: 8_000,
  });
  function boundedScript(defaultTimeoutMs, overrideName) {
    const configuredTimeout = local
      ? Number(globalThis[overrideName])
      : Number.NaN;
    const timeoutMs = Number.isFinite(configuredTimeout)
      && configuredTimeout > 0
      ? Math.min(900_000, Math.max(1, configuredTimeout))
      : defaultTimeoutMs;
    return Object.freeze({
      timeoutMs,
      setTimeout(callback) {
        const clock = globalThis.FUNDING_FINDER_SCRIPT_CLOCK;
        return typeof clock?.setTimeout === "function"
          ? clock.setTimeout(callback, timeoutMs)
          : globalThis.setTimeout(callback, timeoutMs);
      },
      clearTimeout(timer) {
        const clock = globalThis.FUNDING_FINDER_SCRIPT_CLOCK;
        if (typeof clock?.clearTimeout === "function") clock.clearTimeout(timer);
        else globalThis.clearTimeout(timer);
      },
    });
  }
  const boundedScripts = Object.freeze({
    // The current catalog is 2.93 MB gzip. Ten minutes keeps a genuinely
    // stalled operation bounded while allowing roughly 39 kbps throughput,
    // including first-use loads where 2g/slow-2g suppresses prefetch.
    catalog: boundedScript(600_000, "FUNDING_FINDER_CATALOG_TIMEOUT_MS"),
    // The topic sidecar is 222 KB gzip and startup metadata is smaller still.
    // One minute covers roughly 30 kbps without inheriting the catalog budget.
    sidecar: boundedScript(60_000, "FUNDING_FINDER_SIDECAR_TIMEOUT_MS"),
  });

  function releaseLabel() {
    const date = new Date(`${release.updated}T00:00:00Z`);
    const updated = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(date);
    return `Funding Finder v${release.version} · Updated ${updated}`;
  }

  function renderRelease(root = document) {
    root.querySelectorAll("[data-app-version]").forEach(node => {
      node.textContent = releaseLabel();
    });
  }

  globalThis.FUNDING_FINDER_APP = Object.freeze({
    flags,
    productionFlags,
    boundedScripts,
    hybridSearch,
    release,
    releaseLabel,
    renderRelease,
  });

  if (globalThis.document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => renderRelease(), { once: true });
    } else {
      renderRelease();
    }
  }
})();
