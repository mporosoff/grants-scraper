(() => {
  "use strict";

  // Search criteria are intentionally shareable in the page URL. Do not load
  // third-party page analytics on parameterized routes, where the request
  // could otherwise expose those criteria.
  if (location.search) return;

  const beacon = document.createElement("script");
  beacon.type = "module";
  beacon.src = "https://static.cloudflareinsights.com/beacon.min.js";
  beacon.dataset.cfBeacon = JSON.stringify({
    token: "209e9983c16e4747947cf621792fe833",
  });
  document.head.append(beacon);
})();
