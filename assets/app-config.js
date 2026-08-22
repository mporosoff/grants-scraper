(() => {
  "use strict";

  const release = Object.freeze({
    version: "1.1.0",
    updated: "2026-08-21",
  });
  const productionFlags = Object.freeze({
    subtopics: true,
    matchExplanations: true,
    searchV2: false,
  });
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = localHosts.has(globalThis.location?.hostname || "");
  const parameters = new URLSearchParams(globalThis.location?.search || "");
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
