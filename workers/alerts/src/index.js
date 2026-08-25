import "../../../assets/award-links.js";

import {
  ALERT_SCHEMA_VERSION, normalizeEmail, normalizeSubscription, stableJson,
} from "./contract.js";
import { randomToken, sha256Hex, verifySvixWebhook } from "./crypto.js";
import { baselineIds, dispatchNotifications, evaluateSubscriptions } from "./evaluator.js";
import { verificationEmail } from "./email.js";
import { createEmailProvider } from "./provider.js";
import { D1AlertStore } from "./store.js";
import { loadPublicAssets } from "./strong-match.js";

const MAX_REQUEST_BYTES = 32_768;
const PRODUCTION_ORIGIN = "https://mporosoff.github.io";
const LINKS_API = globalThis.FUNDING_AWARD_LINKS;

function allowedOrigin(value) {
  if (!value) return true;
  if (value === PRODUCTION_ORIGIN) return true;
  try {
    const url = new URL(value);
    return url.protocol === "http:" && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname);
  } catch { return false; }
}

function allowedOpaqueManageForm(request, url, origin) {
  if (origin !== "null" || request.method !== "POST") return false;
  if (!["/manage", "/unsubscribe"].includes(url.pathname.replace(/\/+$/, "") || "/")) return false;
  if (!String(request.headers.get("content-type") || "").toLowerCase().startsWith("application/x-www-form-urlencoded")) return false;
  return request.headers.get("sec-fetch-site") === "same-origin"
    && request.headers.get("sec-fetch-mode") === "navigate"
    && request.headers.get("sec-fetch-dest") === "document";
}

function headers(origin, contentType = "application/json; charset=utf-8", extra = {}) {
  return {
    ...(origin ? { "Access-Control-Allow-Origin": origin } : {}),
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Content-Type": contentType,
    "Referrer-Policy": "no-referrer",
    Vary: "Origin",
    ...extra,
  };
}

function json(origin, status, payload) {
  return new Response(JSON.stringify(payload), { status, headers: headers(origin) });
}

function html(status, body) {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>Funding Finder alerts</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:48rem;margin:0 auto;padding:2rem;color:#14213d}main{border:1px solid #ccd5e4;border-radius:1rem;padding:1.5rem}button,select{font:inherit;padding:.55rem .8rem}li{margin:1rem 0}.muted{color:#58647a}</style></head><body><main>${body}</main></body></html>`, {
    status,
    headers: headers("", "text/html; charset=utf-8", {
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      "X-Content-Type-Options": "nosniff",
    }),
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function parseJson(request) {
  if (!String(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    throw Object.assign(new Error("JSON required"), { status: 415, code: "json_required" });
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_REQUEST_BYTES) throw Object.assign(new Error("too large"), { status: 413, code: "request_too_large" });
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("too large"), { status: 413, code: "request_too_large" });
  }
  try { return JSON.parse(text); }
  catch { throw Object.assign(new Error("invalid JSON"), { status: 400, code: "invalid_json" }); }
}

function serviceConfig(env) {
  return {
    enabled: String(env.ALERTS_API_ENABLED || "").toLowerCase() === "true",
    outbound: String(env.OUTBOUND_EMAIL_ENABLED || "").toLowerCase() === "true",
    provider: String(env.EMAIL_PROVIDER || "").toLowerCase(),
    publicWorkerOrigin: String(env.PUBLIC_WORKER_ORIGIN || ""),
  };
}

function clientAddress(request) {
  return String(request.headers.get("cf-connecting-ip") || request.headers.get("x-forwarded-for") || "unknown").split(",")[0].trim();
}

async function rateLimit(store, request, action, limit, seconds, now) {
  const day = now.toISOString().slice(0, 10);
  const key = await sha256Hex(`${day}:${clientAddress(request)}`);
  return store.consumeRateLimit(action, key, limit, seconds, now);
}

function definitionSummary(subscription) {
  const definition = JSON.parse(subscription.definition_json);
  if (subscription.type === "opportunity") return `Opportunity ${definition.opportunity_id}`;
  if (subscription.type === "program") {
    return LINKS_API.programIdentityById(definition.program_id)?.label || definition.program_id;
  }
  return `Strong matches for “${definition.query}”`;
}

function managePage(subscriber, subscriptions) {
  const items = subscriptions.map(subscription => {
    const active = Number(subscription.active) === 1;
    const fields = `<input type="hidden" name="token" value="${escapeHtml(subscriber.manage_token)}"><input type="hidden" name="subscription" value="${escapeHtml(subscription.id)}">`;
    return `<li><strong>${escapeHtml(definitionSummary(subscription))}</strong><p>${active ? "Active" : "Paused"} · ${escapeHtml(subscription.cadence === "weekly" ? "Weekly digest" : "As changes happen")}</p><form method="post" action="/manage">${fields}<input type="hidden" name="active" value="${active ? "0" : "1"}"><button type="submit">${active ? "Pause" : "Resume"}</button></form><form method="post" action="/manage">${fields}<select name="cadence" aria-label="Email frequency"><option value="immediate"${subscription.cadence === "immediate" ? " selected" : ""}>As changes happen</option><option value="weekly"${subscription.cadence === "weekly" ? " selected" : ""}>Weekly digest</option></select> <button type="submit">Save frequency</button></form><form method="post" action="/unsubscribe">${fields}<button type="submit">Unsubscribe</button></form></li>`;
  }).join("");
  return `<h1>Manage Funding Finder alerts</h1><p>These are the email alerts authorized for this address. Browser-local saved statuses, notes, profiles, documents, and chat are not shown because the alert service never receives them.</p><ul>${items || "<li>No alerts found.</li>"}</ul><p class="muted">Closing this page does not change your browser-local Saved list.</p>`;
}

async function formValues(request) {
  if (String(request.headers.get("content-type") || "").startsWith("application/json")) return parseJson(request);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("too large"), { status: 413, code: "request_too_large" });
  }
  return Object.fromEntries(new URLSearchParams(text));
}

export function createHandler({
  storeFactory = env => new D1AlertStore(env.ALERTS_DB),
  providerFactory = (env, fetchImpl) => createEmailProvider(env, fetchImpl),
  assetLoader = (env, fetchImpl) => loadPublicAssets(env, fetchImpl),
  fetchImpl = (...args) => fetch(...args),
  now = () => new Date(),
  tokenFactory = () => randomToken(),
} = {}) {
  return async function handle(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("origin") || "";
    if (!allowedOrigin(origin) && origin !== url.origin && !allowedOpaqueManageForm(request, url, origin)) {
      return json(origin, 403, { error: { code: "origin_not_allowed" } });
    }
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: headers(origin) });
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const current = now();
    const config = serviceConfig(env);
    let store;
    try { store = storeFactory(env); }
    catch { return json(origin, 503, { error: { code: "alerts_unavailable" } }); }

    if (path === "/health" && request.method === "GET") {
      let databaseReady = false;
      try { databaseReady = await store.health(); } catch { /* unavailable */ }
      let providerConfigured = false;
      try { providerConfigured = providerFactory(env, fetchImpl).configured === true; } catch { /* unavailable */ }
      const available = config.enabled && databaseReady && config.provider === "resend";
      return json(origin, available ? 200 : 503, {
        service: available ? "available" : "unavailable",
        schema_version: ALERT_SCHEMA_VERSION,
        database_ready: databaseReady,
        email_provider: "resend",
        email_provider_configured: providerConfigured,
        outbound_email_enabled: config.outbound,
      });
    }
    if (!config.enabled) return json(origin, 503, { error: { code: "alerts_unavailable" } });

    try {
      if (path === "/subscriptions" && request.method === "POST") {
        if (!await rateLimit(store, request, "subscribe", 5, 3_600, current)) {
          return json(origin, 429, { error: { code: "rate_limited" } });
        }
        const body = await parseJson(request);
        if (!body || Object.keys(body).sort().join(",") !== "baseline_opportunity_ids,email,subscription") {
          return json(origin, 400, { error: { code: "invalid_request" } });
        }
        const email = normalizeEmail(body.email);
        const subscription = normalizeSubscription(body.subscription, LINKS_API);
        const suppliedBaseline = body.baseline_opportunity_ids;
        const baselineValid = Array.isArray(suppliedBaseline)
          && suppliedBaseline.length <= 1_500
          && suppliedBaseline.every(id => typeof id === "string" && id.trim() && id.length <= 200)
          && (subscription?.type === "saved_search" || suppliedBaseline.length === 0);
        if (!email || !subscription || !baselineValid) {
          return json(origin, 400, { error: { code: "invalid_request" } });
        }
        const baseline = baselineIds(subscription, suppliedBaseline);
        const emailHash = await sha256Hex(email);
        const definitionJson = stableJson(subscription.definition);
        const definitionHash = await sha256Hex(definitionJson);
        const subscriberId = `person_${emailHash.slice(0, 24)}`;
        const subscriptionId = `watch_${(await sha256Hex(`${subscriberId}|${subscription.type}|${definitionHash}`)).slice(0, 24)}`;
        const verificationToken = tokenFactory();
        const verificationTokenHash = await sha256Hex(verificationToken);
        const createdAt = current.toISOString();
        const subscriber = await store.upsertSubscriber({ id: subscriberId, email, manageToken: tokenFactory(), now: createdAt });
        const stored = await store.createPendingSubscription({
          id: subscriptionId, subscriberId: subscriber.id, type: subscription.type,
          cadence: subscription.cadence, definitionJson, definitionHash,
          verificationTokenHash,
          verificationExpiresAt: new Date(current.getTime() + 24 * 60 * 60_000).toISOString(),
          now: createdAt,
        });
        if (!stored.baseline_complete) await store.setBaseline(stored.id, baseline, createdAt);
        const provider = providerFactory(env, fetchImpl);
        const dailyLimit = Math.max(1, Math.min(100, Number(env.DAILY_EMAIL_LIMIT) || 100));
        if (!config.outbound || !await store.consumeRateLimit(
          "email_send", "global", dailyLimit, 86_400, current,
        )) {
          return json(origin, 503, { error: { code: "alerts_unavailable" } });
        }
        await provider.sendEmail(verificationEmail({
          env, to: email, token: verificationToken, subscriptionId: stored.id,
          manageToken: subscriber.manage_token, type: subscription.type,
        }), `verify:${stored.id}:${verificationTokenHash.slice(0, 24)}`);
        return json(origin, 202, { status: "verification_required" });
      }

      if (path === "/verify" && request.method === "GET") {
        if (!await rateLimit(store, request, "verify", 20, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const token = String(url.searchParams.get("token") || "");
        const verified = token.length >= 32
          ? await store.verifySubscription(await sha256Hex(token), current.toISOString())
          : null;
        return verified
          ? html(200, `<h1>Email verified</h1><p>Your Funding Finder alert is active.</p><p><a href="/manage?token=${encodeURIComponent(verified.manage_token)}">Manage alerts</a></p>`)
          : html(400, "<h1>This verification link is invalid or expired</h1><p>Create the alert again to receive a new link.</p>");
      }

      if (path === "/manage" && request.method === "GET") {
        if (!await rateLimit(store, request, "manage", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const subscriber = await store.subscriberByManageToken(String(url.searchParams.get("token") || ""));
        if (!subscriber) return html(404, "<h1>Manage link not found</h1>");
        return html(200, managePage(subscriber, await store.subscriptionsForSubscriber(subscriber.id)));
      }

      if (path === "/manage" && request.method === "POST") {
        if (!await rateLimit(store, request, "manage", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const body = await formValues(request);
        const updated = await store.updateSubscription(
          String(body.token || ""), String(body.subscription || ""),
          {
            ...(Object.prototype.hasOwnProperty.call(body, "active") ? { active: String(body.active) === "1" } : {}),
            cadence: String(body.cadence || ""),
          }, current.toISOString(),
        );
        return updated ? html(200, "<h1>Alert updated</h1><p>Your change is saved.</p>") : html(400, "<h1>Unable to update alert</h1>");
      }

      if (path === "/unsubscribe" && request.method === "GET") {
        const token = String(url.searchParams.get("token") || "");
        const subscription = String(url.searchParams.get("subscription") || "");
        const subscriber = await store.subscriberByManageToken(token);
        if (!subscriber || !subscription) return html(404, "<h1>Unsubscribe link not found</h1>");
        return html(200, `<h1>Unsubscribe from this alert?</h1><form method="post" action="/unsubscribe"><input type="hidden" name="token" value="${escapeHtml(token)}"><input type="hidden" name="subscription" value="${escapeHtml(subscription)}"><button type="submit">Unsubscribe</button></form>`);
      }

      if (path === "/unsubscribe" && request.method === "POST") {
        if (!await rateLimit(store, request, "unsubscribe", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const queryToken = String(url.searchParams.get("token") || "");
        const querySubscription = String(url.searchParams.get("subscription") || "");
        const body = queryToken && querySubscription ? {} : await formValues(request);
        const removed = await store.unsubscribe(
          queryToken || String(body.token || ""), querySubscription || String(body.subscription || ""), current.toISOString(),
        );
        return removed
          ? html(200, "<h1>Successfully unsubscribed</h1><p>You have been successfully unsubscribed from Funding Finder.</p>")
          : html(400, "<h1>Unable to unsubscribe</h1>");
      }

      if (path === "/webhooks/resend" && request.method === "POST") {
        const payload = await request.text();
        if (new TextEncoder().encode(payload).byteLength > MAX_REQUEST_BYTES) {
          return json(origin, 413, { error: { code: "request_too_large" } });
        }
        const valid = env.RESEND_WEBHOOK_SECRET && await verifySvixWebhook({
          payload,
          headers: {
            id: request.headers.get("svix-id"), timestamp: request.headers.get("svix-timestamp"),
            signature: request.headers.get("svix-signature"),
          },
          secret: env.RESEND_WEBHOOK_SECRET,
          now: current,
        });
        if (!valid) return json(origin, 400, { error: { code: "invalid_webhook" } });
        const event = JSON.parse(payload);
        if (["email.bounced", "email.complained", "email.suppressed"].includes(event.type)) {
          await store.suppressSubscriberByMessage(
            String(event.data?.email_id || ""), String(event.type),
            String(request.headers.get("svix-id") || ""), current.toISOString(),
          );
        }
        return json(origin, 200, { received: true });
      }
    } catch (error) {
      if (error?.status) return json(origin, error.status, { error: { code: error.code } });
      if (error?.providerFailureKind) {
        console.error("alerts_email_provider_failure", {
          kind: error.providerFailureKind,
          status: error.providerFailureKind === "http" ? error.providerHttpStatus : null,
        });
      }
      return json(origin, 503, { error: { code: "alerts_unavailable" } });
    }
    return json(origin, 404, { error: { code: "not_found" } });
  };
}

export function createScheduledHandler({
  storeFactory = env => new D1AlertStore(env.ALERTS_DB),
  providerFactory = (env, fetchImpl) => createEmailProvider(env, fetchImpl),
  assetLoader = (env, fetchImpl) => loadPublicAssets(env, fetchImpl),
  fetchImpl = (...args) => fetch(...args),
  now = scheduledTime => new Date(scheduledTime || Date.now()),
} = {}) {
  return async function scheduled(controller, env) {
    const current = now(controller?.scheduledTime);
    const store = storeFactory(env);
    const run = {
      id: `run_${current.toISOString().replace(/[^0-9]/g, "")}`,
      startedAt: current.toISOString(), subscriptionCount: 0, matchedEventCount: 0,
      attemptedCount: 0, deliveredCount: 0, failedCount: 0, status: "running",
    };
    await store.startRun(run);
    try {
      const assets = await assetLoader(env, fetchImpl);
      Object.assign(run, await evaluateSubscriptions({ store, assets, env, now: current }));
      const provider = providerFactory(env, fetchImpl);
      const immediate = await dispatchNotifications({ store, provider, env, now: current, weekly: false });
      const weekly = current.getUTCDay() === 0
        ? await dispatchNotifications({ store, provider, env, now: current, weekly: true })
        : { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
      run.attemptedCount = immediate.attemptedCount + weekly.attemptedCount;
      run.deliveredCount = immediate.deliveredCount + weekly.deliveredCount;
      run.failedCount = immediate.failedCount + weekly.failedCount;
      run.status = run.failedCount ? "completed_with_delivery_failures" : "completed";
    } catch {
      run.status = "failed";
    }
    run.completedAt = new Date(current.getTime()).toISOString();
    await store.finishRun(run);
    return run;
  };
}

const handle = createHandler();
const scheduled = createScheduledHandler();

export default {
  fetch(request, env) { return handle(request, env); },
  scheduled(controller, env, context) { context.waitUntil(scheduled(controller, env)); },
};
