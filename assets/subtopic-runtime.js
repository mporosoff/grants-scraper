(() => {
  "use strict";

  let sidecarPromise = null;
  let timedOutAttempt = false;
  let recoveryAttempt = 0;

  function discardSidecar() {
    try { delete globalThis.SUBTOPIC_CATALOG; } catch (_error) {
      globalThis.SUBTOPIC_CATALOG = undefined;
    }
  }

  function timeoutError() {
    const error = new Error("The topic catalog request timed out.");
    error.code = "topic_sidecar_timeout";
    return error;
  }

  function loadSidecar() {
    const recovering = timedOutAttempt;
    if (recovering) {
      timedOutAttempt = false;
      recoveryAttempt += 1;
      discardSidecar();
    }
    if (globalThis.SUBTOPIC_CATALOG) {
      return Promise.resolve(globalThis.SUBTOPIC_CATALOG);
    }
    if (sidecarPromise) return sidecarPromise;
    const boundedScript = globalThis.FUNDING_FINDER_APP?.boundedScript;
    const operation = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const catalogVersion = encodeURIComponent(
        globalThis.GRANT_CATALOG?.generated_at || "search-v2-phase2-1-20260822",
      );
      const url = new URL(`./data/subtopics.js?v=${catalogVersion}`, location.href);
      if (recovering) url.searchParams.set("recovery", String(recoveryAttempt));
      script.src = url.href;
      script.async = true;
      script.dataset.fundingSubtopicCatalog = "true";
      let settled = false;
      let timeout = null;
      const cleanup = ({ remove = false } = {}) => {
        if (timeout !== null) boundedScript.clearTimeout(timeout);
        timeout = null;
        script.removeEventListener("load", onLoad);
        script.removeEventListener("error", onError);
        if (remove) script.remove();
      };
      const finish = (callback, options) => {
        if (settled) return;
        settled = true;
        cleanup(options);
        callback();
      };
      const onLoad = () => finish(() => {
        if (globalThis.SUBTOPIC_CATALOG) resolve(globalThis.SUBTOPIC_CATALOG);
        else reject(new Error("The topic sidecar loaded without a catalog."));
      });
      const onError = () => finish(() => {
        reject(new Error("The topic sidecar could not be loaded."));
      }, { remove: true });
      script.addEventListener("load", onLoad, { once: true });
      script.addEventListener("error", onError, { once: true });
      timeout = boundedScript.setTimeout(() => finish(() => {
        timedOutAttempt = true;
        discardSidecar();
        reject(timeoutError());
      }, { remove: true }));
      document.head.append(script);
    });
    const shared = operation.catch(error => {
      if (sidecarPromise === shared) sidecarPromise = null;
      throw error;
    });
    sidecarPromise = shared;
    return shared;
  }

  function enabled() {
    return Boolean(globalThis.FUNDING_FINDER_APP?.flags?.subtopics);
  }

  globalThis.FUNDING_SUBTOPICS = Object.freeze({ enabled, loadSidecar });
})();
