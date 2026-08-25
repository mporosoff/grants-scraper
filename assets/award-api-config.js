(() => {
  "use strict";

  const productionBaseUrl = "https://funding-finder-award-api.urochestercheme.workers.dev/";
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  const local = localHosts.has(globalThis.location?.hostname || "");
  const parameters = new URLSearchParams(globalThis.location?.search || "");

  function localOverride() {
    if (!local) return "";
    const value = String(parameters.get("ff-award-api") || "").trim();
    if (!value) return "";
    try {
      const url = new URL(value, globalThis.location?.href || "http://localhost/");
      const allowedLocal = url.protocol === "http:" && localHosts.has(url.hostname);
      return url.protocol === "https:" || allowedLocal ? url.href : "";
    } catch {
      return "";
    }
  }

  const baseUrl = localOverride() || productionBaseUrl;
  globalThis.FUNDING_AWARD_API_CONFIG = Object.freeze({
    baseUrl,
    institutionSearchUrl: new URL("institutions/search", baseUrl).href,
    searchUrl: new URL("awards/search", baseUrl).href,
    timeoutMs: 45_000,
    maxResultsPerSource: 25,
  });
})();
