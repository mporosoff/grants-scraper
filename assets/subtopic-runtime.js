(() => {
  "use strict";

  let sidecarPromise = null;

  function loadSidecar() {
    if (globalThis.SUBTOPIC_CATALOG) return Promise.resolve(globalThis.SUBTOPIC_CATALOG);
    if (sidecarPromise) return sidecarPromise;
    sidecarPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const catalogVersion = encodeURIComponent(
        globalThis.GRANT_CATALOG?.generated_at || "search-v2-phase2-1-20260822",
      );
      script.src = `./data/subtopics.js?v=${catalogVersion}`;
      script.async = true;
      script.addEventListener("load", () => {
        if (globalThis.SUBTOPIC_CATALOG) resolve(globalThis.SUBTOPIC_CATALOG);
        else reject(new Error("The topic sidecar loaded without a catalog."));
      }, { once: true });
      script.addEventListener("error", () => {
        reject(new Error("The topic sidecar could not be loaded."));
      }, { once: true });
      document.head.append(script);
    });
    return sidecarPromise;
  }

  function enabled() {
    return Boolean(globalThis.FUNDING_FINDER_APP?.flags?.subtopics);
  }

  globalThis.FUNDING_SUBTOPICS = Object.freeze({ enabled, loadSidecar });
})();
