import { enforceSubmittedRelationship, fail, validateAdminProfile, validateSubmission } from "./contract.js";
import { ResearcherSubmissionStore } from "./store.js";

const MAX_REQUEST_BYTES = 32_768;
const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
const TERMINAL_PUBLIC_FIELDS = new Set([
  "submission_id", "submission_type", "source_surface", "state", "revision", "created_at", "updated_at",
  "published_at", "published_commit_sha", "published_registry_generation", "deployment_result", "public_verified_at", "failure_code",
]);

function isPublicOrigin(origin, env) {
  return Boolean(origin) && (origin === env.PUBLIC_APP_ORIGIN || /^http:\/\/(?:localhost|127\.0\.0\.1)(?::[0-9]+)?$/.test(origin));
}
function corsHeaders(origin, env) {
  return isPublicOrigin(origin, env) ? {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  } : {};
}
function json(status, value, origin = "", env = {}) {
  return new Response(JSON.stringify(value), { status, headers: { ...JSON_HEADERS, ...corsHeaders(origin, env) } });
}
function html(status, value) {
  return new Response(value, { status, headers: {
    "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
  } });
}
function text(status, value, contentType = "text/plain; charset=utf-8") {
  return new Response(value, { status, headers: { "Content-Type": contentType, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}
function randomToken(bytes = 24) {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  return Array.from(values, value => value.toString(16).padStart(2, "0")).join("");
}
async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value)));
  return Array.from(new Uint8Array(digest), item => item.toString(16).padStart(2, "0")).join("");
}
async function receiptToken(env, idempotencyKey) {
  if (!env.RECEIPT_TOKEN_SECRET) fail("service_not_configured", "Submission receipts are not configured.", 503);
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(env.RECEIPT_TOKEN_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(idempotencyKey));
  return Array.from(new Uint8Array(signature), item => item.toString(16).padStart(2, "0")).join("");
}
function safeEqual(left, right) {
  const a = new TextEncoder().encode(String(left || ""));
  const b = new TextEncoder().encode(String(right || ""));
  if (a.length !== b.length) return false;
  let different = 0;
  for (let index = 0; index < a.length; index += 1) different |= a[index] ^ b[index];
  return different === 0;
}
async function readJson(request) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_REQUEST_BYTES) fail("request_too_large", "The request is too large.", 413);
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) fail("request_too_large", "The request is too large.", 413);
  try { return JSON.parse(body); } catch { fail("invalid_json", "The request must be valid JSON."); }
}
function requirePublicOrigin(request, env) {
  const origin = request.headers.get("origin") || "";
  if (!isPublicOrigin(origin, env)) {
    fail("origin_not_allowed", "This site origin is not allowed.", 403);
  }
  return origin;
}
function decodeBase64Url(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}
async function adminActor(request, env, fetchImpl) {
  const assertion = request.headers.get("cf-access-jwt-assertion") || "";
  const teamDomain = String(env.ACCESS_TEAM_DOMAIN || "").replace(/\/$/, "");
  const audience = String(env.ACCESS_AUD || "");
  const allowed = String(env.ADMIN_EMAILS || "").toLocaleLowerCase().split(",").map(value => value.trim()).filter(Boolean);
  if (!assertion || !audience || !/^https:\/\/[a-z0-9.-]+\.cloudflareaccess\.com$/i.test(teamDomain) || !allowed.length) {
    fail("admin_access_required", "Administrator access is required.", 403);
  }
  try {
    const parts = assertion.split(".");
    if (parts.length !== 3) throw new Error("invalid JWT");
    const header = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0])));
    const payload = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1])));
    if (header.alg !== "RS256" || !header.kid || payload.iss !== teamDomain) throw new Error("invalid claims");
    const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    const timestamp = Math.floor(Date.now() / 1000);
    if (!audiences.includes(audience) || !Number.isFinite(payload.exp) || payload.exp <= timestamp || (payload.nbf && payload.nbf > timestamp)) {
      throw new Error("expired or mismatched claims");
    }
    const certificates = await fetchImpl(`${teamDomain}/cdn-cgi/access/certs`, { cf: { cacheEverything: true, cacheTtl: 300 } });
    if (!certificates.ok) throw new Error("signing keys unavailable");
    const jwks = await certificates.json();
    const jwk = (jwks.keys || []).find(key => key.kid === header.kid);
    if (!jwk) throw new Error("signing key not found");
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const verified = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5", key, decodeBase64Url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
    );
    const email = String(payload.email || "").toLocaleLowerCase();
    if (!verified || !email || !allowed.includes(email)) throw new Error("unauthorized identity");
    return email;
  } catch {
    fail("admin_access_required", "Administrator access is required.", 403);
  }
}
function requireInternal(request, env) {
  const token = String(request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.REGISTRY_WORKFLOW_TOKEN || !safeEqual(token, env.REGISTRY_WORKFLOW_TOKEN)) fail("workflow_access_required", "Workflow access is required.", 403);
}
function publicStatus(row) {
  return Object.fromEntries(Object.entries(row || {}).filter(([key]) => TERMINAL_PUBLIC_FIELDS.has(key)));
}
async function currentManifest(env, fetchImpl) {
  const response = await fetchImpl(env.REGISTRY_MANIFEST_URL, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) fail("registry_unavailable", "The current researcher registry could not be verified.", 503);
  const value = await response.json();
  if (!/^[a-f0-9]{64}$/.test(value.registry_generation || "")) fail("registry_unavailable", "The current researcher registry is invalid.", 503);
  return value;
}
async function currentDirectory(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/researcher_directory.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
async function currentTeamData(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/opportunity_teams.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
async function currentFacultyMatches(env, fetchImpl) {
  const url = `${env.PUBLIC_SITE_ROOT}/data/faculty_matches.js?admin=${Date.now()}`;
  const response = await fetchImpl(url, { headers: { "Cache-Control": "no-cache" } });
  if (!response.ok) return null;
  const source = await response.text();
  const start = source.indexOf("{");
  if (start < 0) return null;
  try { return JSON.parse(source.slice(start).trim().replace(/;$/, "")); } catch { return null; }
}
function normalized(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
function duplicateCandidates(directory, detail) {
  if (!directory) return [];
  const profile = detail.proposed_profile || {};
  const name = normalized(profile.display_name);
  const sources = new Set(profile.source_urls || []);
  return (directory.researchers || []).map(researcher => {
    const reasons = [];
    if ([researcher.name, ...(researcher.aliases || [])].map(normalized).includes(name)) reasons.push("normalized_name");
    if (profile.orcid_id && profile.orcid_id === researcher.orcid_id) reasons.push("orcid");
    if ((researcher.source_urls || []).some(url => sources.has(url))) reasons.push("source");
    return reasons.length ? { researcher_id: researcher.id, display_name: researcher.name, reasons } : null;
  }).filter(Boolean);
}
function trustSignals(detail, duplicates) {
  const profile = detail.proposed_profile || {};
  return {
    stable_id: Boolean(detail.researcher_id),
    orcid: Boolean(profile.orcid_id),
    source_count: (profile.source_urls || []).length,
    possible_duplicate_count: duplicates.length,
  };
}
function validatorWarnings(directory, detail, duplicates) {
  const warnings = [];
  if (!directory) warnings.push("The current public directory could not be loaded.");
  else if (directory.registry_generation !== detail.base_registry_generation) warnings.push("The submission is based on an older registry generation and must be rebased and re-reviewed.");
  if (detail.submission_type === "profile_correction" && directory && !(directory.researchers || []).some(row => row.id === detail.researcher_id)) {
    warnings.push("The correction's stable researcher ID is not in the current directory.");
  }
  if (detail.submission_type === "new_researcher_nomination" && !(detail.proposed_profile.source_urls || []).length) warnings.push("A new researcher requires at least one credible source.");
  if (duplicates.length > 1) warnings.push("Multiple possible identities require explicit administrator resolution; no automatic merge is allowed.");
  return warnings;
}
function materialEffect(directory, teamData, facultyMatches, detail) {
  const current = directory && (directory.researchers || []).find(row => row.id === detail.researcher_id);
  const generatedOutputs = [
    "researcher directory", "team directory", "faculty opportunity matches", "registry manifest",
  ];
  if (!current) return {
    classification: "new_researcher", changed_claims: detail.proposed_profile.claims.length,
    claim_changes: { additions: detail.proposed_profile.claims || [], retirements: [], unchanged: [] },
    generated_outputs: generatedOutputs, affected_matches: [], affected_team_scopes: [],
  };
  const oldClaims = (current.claims || []).filter(claim => claim.status === "active");
  const nextClaims = detail.proposed_profile.claims || [];
  const oldByLabel = new Map(oldClaims.map(claim => [normalized(claim.label), claim.label]));
  const nextByLabel = new Map(nextClaims.map(label => [normalized(label), label]));
  const additions = [...nextByLabel].filter(([key]) => !oldByLabel.has(key)).map(([, label]) => label);
  const retirements = [...oldByLabel].filter(([key]) => !nextByLabel.has(key)).map(([, label]) => label);
  const unchanged = [...oldByLabel].filter(([key]) => nextByLabel.has(key)).map(([, label]) => label);
  const scientific = additions.length > 0 || retirements.length > 0;
  const administrative = current.home_unit !== detail.proposed_profile.home_unit || current.orcid_id !== detail.proposed_profile.orcid_id;
  const affected = scientific && teamData ? (teamData.opportunities || []).filter(scope => {
    if ((scope.members || []).some(member => member.faculty_id === current.id)) return true;
    return (scope.roles || []).some(role => [...(role.candidate_ids || []), ...(role.alternative_ids || [])].includes(current.id));
  }).map(scope => scope.id) : [];
  const matchingEntry = facultyMatches && Object.entries(facultyMatches.faculty || {}).find(([, profile]) => profile.researcher_id === current.id);
  const affectedMatches = scientific && matchingEntry
    ? ((facultyMatches.pi_matches || {})[matchingEntry[0]] || []).map(match => match.id)
    : [];
  return {
    classification: scientific ? "scientific" : administrative ? "administrative" : "cosmetic",
    changed_claims: additions.length + retirements.length,
    claim_changes: { additions, retirements, unchanged },
    generated_outputs: generatedOutputs,
    affected_matches: affectedMatches,
    affected_team_scopes: affected,
  };
}
async function notifyOwner(env, submission, fetchImpl, event = "pending") {
  if (!env.RESEND_API_KEY || !env.ADMIN_NOTIFICATION_EMAIL || !env.NOTIFICATION_FROM) return;
  const failed = event === "publication_failed";
  await fetchImpl("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: env.NOTIFICATION_FROM, to: [env.ADMIN_NOTIFICATION_EMAIL],
      subject: failed ? "Funding Finder researcher publication failed" : "Funding Finder researcher request waiting",
      text: failed
        ? `Submission ${submission.submission_id} entered publication_failed. Open the protected queue to inspect and retry it.`
        : `Submission ${submission.submission_id} (${submission.submission_type}) is waiting in the protected researcher review queue.`,
    }),
  });
}
async function dispatchPublication(env, row, fetchImpl) {
  if (!env.GITHUB_DISPATCH_TOKEN) fail("publication_not_configured", "Registry publication is not configured.", 503);
  const response = await fetchImpl(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json",
      "Content-Type": "application/json", "User-Agent": "funding-finder-researcher-intake",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ event_type: "researcher-registry-publish", client_payload: {
      submission_id: row.submission_id, approved_revision: row.revision,
      expected_registry_generation: row.base_registry_generation,
    } }),
  });
  if (!response.ok) fail("publication_dispatch_failed", "The publication workflow could not be started.", 503);
}

const ADMIN_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Researcher review | Funding Finder</title><link rel="stylesheet" href="/admin/styles.css"></head><body><main><header><p>Funding Finder administration</p><h1>Researcher submissions</h1><p>Review the current and proposed public values before publishing a registry-only change.</p></header><section id="queue" aria-live="polite">Loading queue…</section><section id="detail" hidden><button id="back" type="button">Back to queue</button><h2 id="detail-title"></h2><div class="columns"><div><h3>Current</h3><pre id="current"></pre></div><div><h3>Proposed</h3><pre id="proposed"></pre></div></div><p id="signals"></p><label>Approved registry profile JSON<textarea id="approved" rows="22"></textarea></label><label>Administrator reason<input id="reason" maxlength="500"></label><div class="actions"><button data-action="start_review">Start review</button><button data-action="rebase">Rebase onto current registry</button><button data-action="approve">Approve or edit and publish</button><button data-action="request_changes">Request changes</button><button data-action="reject">Reject</button><button data-action="retry_publish">Retry publication</button></div><p id="admin-status" aria-live="polite"></p></section></main><script src="/admin/app.js"></script></body></html>`;
const ADMIN_CSS = `:root{font-family:Inter,system-ui,sans-serif;color:#17293f;background:#f3f6fb}body{margin:0}main{width:min(1180px,calc(100% - 32px));margin:auto;padding:30px 0}header{padding:20px 24px;color:#fff;background:#001e5f;border-radius:14px}header p,header h1{margin:4px 0}.queue{width:100%;margin-top:20px;border-collapse:collapse;background:#fff}.queue th,.queue td{padding:10px;border:1px solid #d6e0eb;text-align:left}.queue button,.actions button,#back{padding:8px 11px;font:inherit;font-weight:700}.columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}.columns>div{min-width:0;padding:12px;background:#fff;border:1px solid #d6e0eb;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:grid;gap:5px;margin-top:12px;font-weight:700}textarea,input{padding:10px;font:inherit;border:1px solid #9db2c8;border-radius:8px}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}@media(max-width:760px){.columns{grid-template-columns:1fr}}`;
const ADMIN_JS = `(() => {"use strict";let active=null;const q=document.getElementById("queue"),d=document.getElementById("detail"),status=document.getElementById("admin-status");const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));async function api(path,options){const r=await fetch(path,options);const v=await r.json();if(!r.ok)throw new Error(v.error?.message||"Request failed");return v}function defaultProfile(v){const p=v.proposed_profile,current=v.current_profile;const today=new Date().toISOString().slice(0,10);if(current)return {display_name:p.display_name||current.name,sort_name:current.name.split(" ").slice(-1)+", "+current.name.split(" ").slice(0,-1).join(" "),aliases:current.aliases||[],orcid_id:p.orcid_id||current.orcid_id||"",home_unit:p.home_unit||current.home_unit,relationship:current.relationship,pool_visibility:current.pool_visibility,auto_proposable:current.auto_proposable,status:current.status,research_summary:p.research_summary||current.research_summary,source_urls:p.source_urls.length?p.source_urls:current.source_urls,source_checked_date:today,claims:(current.claims||[]).map(c=>({...c,verified_on:today}))};return {display_name:p.display_name,sort_name:p.display_name.split(" ").slice(-1)+", "+p.display_name.split(" ").slice(0,-1).join(" "),aliases:[],orcid_id:p.orcid_id,home_unit:p.home_unit||"Pending administrator classification",relationship:"reference_only_researcher",pool_visibility:"hidden",auto_proposable:false,status:"active",research_summary:p.research_summary,source_urls:p.source_urls,source_checked_date:today,claims:p.claims.map((label,i)=>({claim_id:"",revision:1,status:"active",label,category:"Interdisciplinary research",type:"Capability",evidence:label,source_urls:p.source_urls,verified_on:today,evidence_level:"administrator_reviewed",legacy_claim_ids:[]}))}}async function load(){q.textContent="Loading queue…";const v=await api("/admin/api/submissions");q.innerHTML='<table class="queue"><thead><tr><th>Researcher</th><th>Request</th><th>Source</th><th>Trust</th><th>Effect</th><th>State</th><th>Submitted</th><th>Action</th></tr></thead><tbody>'+v.submissions.map(x=>'<tr><td>'+esc(x.proposed_profile.display_name)+'</td><td>'+esc(x.submission_type)+'</td><td>'+esc(x.source_surface)+'</td><td>'+esc(JSON.stringify(x.trust_signals))+'</td><td>'+esc(x.material_effect.classification+"; "+x.material_effect.changed_claims+" claim change(s); "+x.material_effect.affected_team_scopes.length+" team scope(s)")+'</td><td>'+esc(x.state)+'</td><td>'+esc(x.created_at)+'</td><td><button data-id="'+esc(x.submission_id)+'">Open</button></td></tr>').join("")+'</tbody></table>';q.querySelectorAll("[data-id]").forEach(b=>b.onclick=()=>open(b.dataset.id))}async function open(id){active=await api("/admin/api/submissions/"+encodeURIComponent(id));q.hidden=true;d.hidden=false;document.getElementById("detail-title").textContent=active.proposed_profile.display_name+" — "+active.state;document.getElementById("current").textContent=JSON.stringify(active.current_profile,null,2);document.getElementById("proposed").textContent=JSON.stringify(active.proposed_profile,null,2);document.getElementById("signals").textContent="Identity signals: "+JSON.stringify(active.duplicate_candidates)+" | Material effect: "+JSON.stringify(active.material_effect)+" | Validator warnings: "+JSON.stringify(active.validator_warnings);document.getElementById("approved").value=JSON.stringify(active.approved_profile||defaultProfile(active),null,2);status.textContent=""}document.getElementById("back").onclick=()=>{d.hidden=true;q.hidden=false;load()};document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{if(!active)return;let profile=null;try{if(["approve","retry_publish"].includes(b.dataset.action))profile=JSON.parse(document.getElementById("approved").value)}catch{status.textContent="Approved profile JSON is invalid.";return}b.disabled=true;try{const v=await api("/admin/api/submissions/"+encodeURIComponent(active.submission_id)+"/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:b.dataset.action,expected_revision:active.revision,approved_profile:profile,reason:document.getElementById("reason").value})});status.textContent="State: "+v.state;active=await api("/admin/api/submissions/"+encodeURIComponent(active.submission_id));}catch(e){status.textContent=e.message}finally{b.disabled=false}});load().catch(e=>q.textContent=e.message)})();`;

export function createHandler({ storeFactory = env => new ResearcherSubmissionStore(env.SUBMISSIONS_DB), fetchImpl = (...args) => fetch(...args), now = () => new Date() } = {}) {
  return async function handle(request, env, context = { waitUntil() {} }) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/$/, "") || "/";
    const origin = request.headers.get("origin") || "";
    try {
      if (request.method === "OPTIONS") {
        requirePublicOrigin(request, env);
        return new Response(null, { status: 204, headers: corsHeaders(origin, env) });
      }
      if (path === "/health" && request.method === "GET") return json(200, { ok: true, schema_version: 1 }, origin, env);
      const store = storeFactory(env);
      if (path === "/submissions" && request.method === "POST") {
        const allowedOrigin = requirePublicOrigin(request, env);
        const ip = request.headers.get("cf-connecting-ip") || "unknown";
        if (env.SUBMISSION_RATE_LIMITER && !(await env.SUBMISSION_RATE_LIMITER.limit({ key: await sha256(ip) })).success) {
          fail("rate_limited", "Too many submissions were attempted. Please wait and try again.", 429);
        }
        const submission = validateSubmission(await readJson(request));
        const payloadHash = await sha256(JSON.stringify(submission));
        const existing = await store.byIdempotencyKey(submission.idempotency_key);
        if (existing) {
          if (!safeEqual(existing.payload_hash, payloadHash)) fail("idempotency_conflict", "That submission identifier was already used for different content.", 409);
          const existingReceiptToken = await receiptToken(env, submission.idempotency_key);
          return json(200, { submission_id: existing.submission_id, state: existing.state, duplicate: true, status_url: `${url.origin}/status/${existing.submission_id}?token=${existingReceiptToken}` }, allowedOrigin, env);
        }
        const submissionId = `rs_${randomToken(12)}`;
        const submissionReceiptToken = await receiptToken(env, submission.idempotency_key);
        const createdAt = now().toISOString();
        const row = await store.create({
          submissionId, idempotencyKey: submission.idempotency_key, payloadHash,
          receiptTokenHash: await sha256(submissionReceiptToken), submissionType: submission.submission_type,
          sourceSurface: submission.source_surface, researcherId: submission.researcher_id,
          baseRegistryGeneration: submission.base_registry_generation,
          proposedProfile: submission.proposed_profile, contactEmail: submission.submitter.contact_email,
          submitterNote: submission.submitter.note, privacyNoticeVersion: submission.consent.privacy_notice_version,
          createdAt,
        });
        context.waitUntil(notifyOwner(env, row, fetchImpl).catch(() => undefined));
        return json(201, { submission_id: submissionId, state: "pending", duplicate: false, status_url: `${url.origin}/status/${submissionId}?token=${submissionReceiptToken}` }, allowedOrigin, env);
      }
      const statusMatch = path.match(/^\/status\/(rs_[a-f0-9]{24})$/);
      if (statusMatch && request.method === "GET") {
        const token = url.searchParams.get("token") || "";
        const row = token ? await store.publicStatus(statusMatch[1], await sha256(token)) : null;
        if (!row) return html(404, "<h1>Status not found</h1><p>Use the complete private receipt link from the original submission.</p>");
        return html(200, `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Researcher request status</title></head><body><main><h1>Researcher request status</h1><p>Submission <code>${row.submission_id}</code></p><p>Current state: <strong>${row.state}</strong></p><p>Last updated: ${row.updated_at}</p>${row.published_registry_generation ? `<p>Published registry generation: <code>${row.published_registry_generation}</code></p>` : ""}<p>No contact information or private note is shown here.</p></main></body></html>`);
      }
      if (path === "/admin/styles.css" && request.method === "GET") { await adminActor(request, env, fetchImpl); return text(200, ADMIN_CSS, "text/css; charset=utf-8"); }
      if (path === "/admin/app.js" && request.method === "GET") { await adminActor(request, env, fetchImpl); return text(200, ADMIN_JS, "text/javascript; charset=utf-8"); }
      if (path === "/admin" && request.method === "GET") { await adminActor(request, env, fetchImpl); return html(200, ADMIN_HTML); }
      if (path === "/admin/api/submissions" && request.method === "GET") {
        await adminActor(request, env, fetchImpl);
        const [submissions, directory, teamData, facultyMatches] = await Promise.all([
          store.listQueue(), currentDirectory(env, fetchImpl), currentTeamData(env, fetchImpl), currentFacultyMatches(env, fetchImpl),
        ]);
        return json(200, { submissions: submissions.map(detail => {
          const duplicates = duplicateCandidates(directory, detail);
          return {
            ...detail, trust_signals: trustSignals(detail, duplicates),
            material_effect: materialEffect(directory, teamData, facultyMatches, detail),
            validator_warnings: validatorWarnings(directory, detail, duplicates),
          };
        }) });
      }
      const adminDetailMatch = path.match(/^\/admin\/api\/submissions\/(rs_[a-f0-9]{24})$/);
      if (adminDetailMatch && request.method === "GET") {
        await adminActor(request, env, fetchImpl);
        const detail = await store.adminDetail(adminDetailMatch[1]);
        if (!detail) fail("not_found", "Submission not found.", 404);
        const [directory, teamData, facultyMatches] = await Promise.all([
          currentDirectory(env, fetchImpl), currentTeamData(env, fetchImpl), currentFacultyMatches(env, fetchImpl),
        ]);
        const duplicates = duplicateCandidates(directory, detail);
        const currentProfile = directory && directory.researchers.find(row => row.id === detail.researcher_id) || null;
        return json(200, {
          ...detail, contact_email: detail.contact_email || "", submitter_note: detail.submitter_note || "",
          current_profile: currentProfile, duplicate_candidates: duplicates,
          trust_signals: trustSignals(detail, duplicates),
          material_effect: materialEffect(directory, teamData, facultyMatches, detail),
          validator_warnings: validatorWarnings(directory, detail, duplicates),
        });
      }
      const adminActionMatch = path.match(/^\/admin\/api\/submissions\/(rs_[a-f0-9]{24})\/action$/);
      if (adminActionMatch && request.method === "POST") {
        const actor = await adminActor(request, env, fetchImpl);
        if (origin && origin !== url.origin) fail("admin_origin_not_allowed", "Administrator origin is not allowed.", 403);
        const body = await readJson(request);
        const expectedRevision = Number(body.expected_revision);
        if (!Number.isInteger(expectedRevision) || expectedRevision < 1) fail("invalid_revision", "The expected revision is invalid.");
        const current = await store.byId(adminActionMatch[1]);
        if (!current) fail("not_found", "Submission not found.", 404);
        const reason = String(body.reason || "").trim().slice(0, 500);
        if (body.action === "rebase") {
          const manifest = await currentManifest(env, fetchImpl);
          if (manifest.registry_generation === current.base_registry_generation) fail("rebase_not_required", "This submission already uses the current registry generation.", 409);
          const rebased = await store.rebase({
            id: current.submission_id, expectedRevision, nextGeneration: manifest.registry_generation,
            actor, reason, now: now().toISOString(),
          });
          if (!rebased) fail("state_conflict", "The submission changed before it could be rebased.", 409);
          return json(200, {
            submission_id: rebased.submission_id, state: rebased.state, revision: rebased.revision,
            base_registry_generation: rebased.base_registry_generation,
          });
        }
        if (body.action === "approve") {
          const manifest = await currentManifest(env, fetchImpl);
          if (manifest.registry_generation !== current.base_registry_generation) fail("stale_registry_generation", "The registry changed. Rebase and review this request again.", 409);
          const approvedProfile = enforceSubmittedRelationship(
            validateAdminProfile(body.approved_profile, current.researcher_id),
            JSON.parse(current.proposed_profile_json),
          );
          const approved = await store.transition({ id: current.submission_id, fromStates: ["pending", "under_review", "changes_requested"], toState: "approved", expectedRevision, actor, reason, approvedProfile, now: now().toISOString() });
          if (!approved) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
          const publishing = await store.markPublishing(approved.submission_id, approved.revision, actor, now().toISOString());
          if (!publishing) fail("state_conflict", "The submission changed before publication started.", 409);
          try { await dispatchPublication(env, publishing, fetchImpl); }
          catch (error) {
            const failed = await store.markPublicationFailed(publishing.submission_id, { expectedRevision: publishing.revision, failureCode: error.code || "publication_dispatch_failed", deploymentResult: "dispatch_failed" }, now().toISOString());
            if (failed) context.waitUntil(notifyOwner(env, failed, fetchImpl, "publication_failed").catch(() => undefined));
            throw error;
          }
          return json(200, { submission_id: publishing.submission_id, state: "publishing", revision: publishing.revision });
        }
        if (body.action === "retry_publish") {
          if (current.state !== "publication_failed") fail("state_conflict", "Only a failed publication can be retried.", 409);
          const manifest = await currentManifest(env, fetchImpl);
          if (manifest.registry_generation !== current.base_registry_generation) fail("stale_registry_generation", "The registry changed. Rebase and review this request again.", 409);
          const publishing = await store.markPublishing(current.submission_id, expectedRevision, actor, now().toISOString());
          if (!publishing) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
          try { await dispatchPublication(env, publishing, fetchImpl); }
          catch (error) {
            const failed = await store.markPublicationFailed(publishing.submission_id, { expectedRevision: publishing.revision, failureCode: error.code || "publication_dispatch_failed", deploymentResult: "dispatch_failed" }, now().toISOString());
            if (failed) context.waitUntil(notifyOwner(env, failed, fetchImpl, "publication_failed").catch(() => undefined));
            throw error;
          }
          return json(200, { submission_id: publishing.submission_id, state: "publishing", revision: publishing.revision });
        }
        const state = body.action === "request_changes" ? "changes_requested" : body.action === "reject" ? "rejected" : body.action === "start_review" ? "under_review" : "";
        if (!state) fail("invalid_action", "The administrator action is invalid.");
        if (["changes_requested", "rejected"].includes(state) && !reason) fail("reason_required", "A reason is required for this action.");
        const updated = await store.transition({ id: current.submission_id, fromStates: ["pending", "under_review", "changes_requested"], toState: state, expectedRevision, actor, reason, now: now().toISOString() });
        if (!updated) fail("state_conflict", "The submission changed while you were reviewing it.", 409);
        return json(200, { submission_id: updated.submission_id, state: updated.state, revision: updated.revision });
      }
      const publicationMatch = path.match(/^\/internal\/publications\/(rs_[a-f0-9]{24})$/);
      if (publicationMatch && request.method === "GET") {
        requireInternal(request, env);
        const row = await store.byId(publicationMatch[1]);
        if (!row || row.state !== "publishing") fail("publication_not_ready", "The approved publication is not ready.", 409);
        return json(200, {
          schema_version: 1, submission_id: row.submission_id, state: "approved", revision: row.revision,
          researcher_id: row.researcher_id, base_registry_generation: row.base_registry_generation,
          approved_at: row.approved_at, approved_profile: JSON.parse(row.approved_profile_json),
        });
      }
      const completionMatch = path.match(/^\/internal\/publications\/(rs_[a-f0-9]{24})\/(complete|fail)$/);
      if (completionMatch && request.method === "POST") {
        requireInternal(request, env);
        const body = await readJson(request);
        const expectedRevision = Number(body.expected_revision);
        const result = completionMatch[2] === "complete"
          ? await store.markPublished(completionMatch[1], {
              expectedRevision, commitSha: String(body.commit_sha || ""), registryGeneration: String(body.registry_generation || ""),
              deploymentResult: String(body.deployment_result || ""), verifiedAt: String(body.public_verified_at || ""),
            }, now().toISOString())
          : await store.markPublicationFailed(completionMatch[1], {
              expectedRevision, failureCode: String(body.failure_code || "publication_failed").slice(0, 80),
              deploymentResult: String(body.deployment_result || "").slice(0, 120),
            }, now().toISOString());
        if (!result) fail("state_conflict", "The publication state changed.", 409);
        if (result.state === "publication_failed") context.waitUntil(notifyOwner(env, result, fetchImpl, "publication_failed").catch(() => undefined));
        return json(200, { submission_id: result.submission_id, state: result.state, revision: result.revision });
      }
      return json(404, { error: { code: "not_found", message: "Not found." } }, origin, env);
    } catch (error) {
      return json(error.status || 503, { error: { code: error.code || "service_unavailable", message: error.message || "The service is unavailable." } }, origin, env);
    }
  };
}

export function createScheduledHandler({ storeFactory = env => new ResearcherSubmissionStore(env.SUBMISSIONS_DB), now = () => new Date() } = {}) {
  return async function scheduled(_controller, env) {
    const store = storeFactory(env);
    return store.cleanup(now().toISOString(), Math.max(1, Number(env.REJECTED_RETENTION_DAYS) || 90), Math.max(1, Number(env.CONTACT_RETENTION_DAYS) || 90));
  };
}

const handle = createHandler();
const scheduled = createScheduledHandler();
export default {
  fetch(request, env, context) { return handle(request, env, context); },
  scheduled(controller, env, context) { context.waitUntil(scheduled(controller, env)); },
};
