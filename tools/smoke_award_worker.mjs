const baseUrl = String(process.env.AWARD_API_URL || "https://funding-finder-award-api.urochestercheme.workers.dev/").trim();
const origin = "https://mporosoff.github.io";

async function jsonRequest(path, options = {}) {
  const response = await fetch(new URL(path, baseUrl), {
    ...options,
    headers: { Origin: origin, ...(options.headers || {}) },
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return payload;
}

const health = await jsonRequest("health");
if (health.service !== "available" || health.schema_version !== 1) {
  throw new Error("Award Worker health contract did not match Phase 1.");
}
if (health.credentials_required !== false) {
  throw new Error("Award Worker unexpectedly reports a credential requirement.");
}

for (const body of [
  { sources: ["NSF"], criteria: { award_id: "2605508" }, limit: 1, offset: 0 },
  { sources: ["NIH"], criteria: { core_project_number: "K12GM106997" }, limit: 1, offset: 0 },
]) {
  const payload = await jsonRequest("awards/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (payload.schema_version !== 1 || payload.results.length !== 1) {
    throw new Error(`${body.sources[0]} exact-ID smoke did not return one normalized project.`);
  }
  if (payload.results[0].source !== body.sources[0] || !payload.results[0].official_award_url) {
    throw new Error(`${body.sources[0]} exact-ID smoke returned an invalid normalized record.`);
  }
}

console.log("Award Worker health and exact NSF/NIH source smokes passed.");
