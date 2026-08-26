(() => {
  "use strict";

  const release = Object.freeze({
    version: "1.3.0",
    updated: "2026-08-24",
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
  const configuredScriptTimeout = local
    ? Number(globalThis.FUNDING_FINDER_SCRIPT_TIMEOUT_MS)
    : Number.NaN;
  const scriptTimeoutMs = Number.isFinite(configuredScriptTimeout)
    && configuredScriptTimeout > 0
    ? Math.min(60_000, Math.max(1, configuredScriptTimeout))
    : 15_000;
  const boundedScript = Object.freeze({
    timeoutMs: scriptTimeoutMs,
    setTimeout(callback) {
      const clock = globalThis.FUNDING_FINDER_SCRIPT_CLOCK;
      return typeof clock?.setTimeout === "function"
        ? clock.setTimeout(callback, scriptTimeoutMs)
        : globalThis.setTimeout(callback, scriptTimeoutMs);
    },
    clearTimeout(timer) {
      const clock = globalThis.FUNDING_FINDER_SCRIPT_CLOCK;
      if (typeof clock?.clearTimeout === "function") clock.clearTimeout(timer);
      else globalThis.clearTimeout(timer);
    },
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
    boundedScript,
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
