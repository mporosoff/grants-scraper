(() => {
  "use strict";

  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = localHosts.has(globalThis.location?.hostname || "");
  const parameters = new URLSearchParams(globalThis.location?.search || "");
  const productionEndpoint = "https://funding-finder-alerts.urochestercheme.workers.dev";

  function localEndpoint() {
    if (!local) return "";
    const value = String(parameters.get("ff-alerts-api") || "").trim();
    if (!value) return "";
    try {
      const url = new URL(value, globalThis.location?.href || "http://localhost/");
      return url.protocol === "http:" && localHosts.has(url.hostname)
        ? url.origin
        : "";
    } catch {
      return "";
    }
  }

  globalThis.FUNDING_ALERTS_CONFIG = Object.freeze({
    endpoint: localEndpoint() || productionEndpoint,
    requestTimeoutMs: 10_000,
  });
})();
