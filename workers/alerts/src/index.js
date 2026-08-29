import "../../../assets/award-links.js";

import {
  ALERT_SCHEMA_VERSION, normalizeEmail, normalizeSubscription, stableJson,
} from "./contract.js";
import {
  createCapability, randomToken, sha256Hex, verificationToken as createVerificationToken,
  verifyCapability, verifySvixWebhook,
} from "./crypto.js";
import {
  baselineIds, dispatchNotifications, dispatchVerificationDeliveries, evaluateSubscriptions,
} from "./evaluator.js";
import { ALERT_EMAIL_TEMPLATE_VERSION } from "./email.js";
import { createEmailProvider } from "./provider.js";
import { D1AlertStore } from "./store.js";
import { loadPublicAssets } from "./strong-match.js";
import {
  boundedFinalization, SchedulerBudget, SchedulerFenceError, SchedulerTimeoutError,
} from "./scheduler-budget.js";

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
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>Funding Finder alerts</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:48rem;margin:0 auto;padding:2rem;color:#14213d}main{border:1px solid #ccd5e4;border-radius:1rem;padding:1.5rem}button,select,.button-link{font:inherit;padding:.55rem .8rem}.button-link{display:inline-block;border:1px solid #7b879c;border-radius:.25rem;color:inherit;text-decoration:none;background:#f5f7fa}li{margin:1rem 0}.muted{color:#58647a}</style></head><body><main>${body}</main></body></html>`, {
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
    scheduler: String(env.ALERT_SCHEDULER_ENABLED || "").toLowerCase() === "true",
    capability: Boolean(String(env.ALERT_CAPABILITY_SECRET || "")),
    capabilityPrevious: Boolean(String(env.ALERT_CAPABILITY_PREVIOUS_SECRET || "")),
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

function suppressionDescription(reason) {
  const value = String(reason || "").toLowerCase();
  if (value.includes("complain")) return "A complaint was reported for this address.";
  if (value.includes("bounce")) return "Delivery to this address bounced.";
  return "The email provider has suppressed delivery to this address.";
}

async function signedCapability(env, subscriberId, purpose, subscriptionId = "") {
  return createCapability(
    { subscriberId, purpose, subscriptionId },
    String(env.ALERT_CAPABILITY_SECRET || ""),
  );
}

async function resolveSubscriberCapability(store, token, purpose, subscriptionId, env, current) {
  const signed = env.ALERT_CAPABILITY_SECRET
    ? await verifyCapability(token, {
        secret: env.ALERT_CAPABILITY_SECRET,
        previousSecret: env.ALERT_CAPABILITY_PREVIOUS_SECRET,
        purpose,
        subscriptionId,
      })
    : null;
  if (signed) return store.subscriberById(signed.s);
  return store.subscriberByManageToken(token, current.toISOString());
}

async function managePage(subscriber, subscriptions, env) {
  const suppressed = Boolean(subscriber.suppressed_at);
  const manageToken = env.ALERT_CAPABILITY_SECRET
    ? await signedCapability(env, subscriber.id, "manage")
    : subscriber.manage_token;
  const items = (await Promise.all(subscriptions.map(async subscription => {
    const active = Number(subscription.active) === 1;
    const unsubscribeToken = env.ALERT_CAPABILITY_SECRET
      ? await signedCapability(env, subscriber.id, "unsubscribe_one", subscription.id)
      : subscriber.manage_token;
    const fields = `<input type="hidden" name="token" value="${escapeHtml(manageToken)}"><input type="hidden" name="subscription" value="${escapeHtml(subscription.id)}">`;
    const state = suppressed ? "Delivery suppressed" : active ? "Active" : "Paused";
    const activeForm = suppressed
      ? ""
      : `<form method="post" action="/manage">${fields}<input type="hidden" name="active" value="${active ? "0" : "1"}"><button type="submit">${active ? "Pause" : "Resume"}</button></form>`;
    const unsubscribeFields = `<input type="hidden" name="token" value="${escapeHtml(unsubscribeToken)}"><input type="hidden" name="subscription" value="${escapeHtml(subscription.id)}"><input type="hidden" name="return_token" value="${escapeHtml(manageToken)}">`;
    return `<li><strong>${escapeHtml(definitionSummary(subscription))}</strong><p>${state} · ${escapeHtml(subscription.cadence === "weekly" ? "Weekly digest" : "As changes happen")}</p>${activeForm}<form method="post" action="/manage">${fields}<select name="cadence" aria-label="Email frequency"><option value="immediate"${subscription.cadence === "immediate" ? " selected" : ""}>As changes happen</option><option value="weekly"${subscription.cadence === "weekly" ? " selected" : ""}>Weekly digest</option></select> <button type="submit">Save frequency</button></form><form method="post" action="/unsubscribe">${unsubscribeFields}<button type="submit">Unsubscribe from this alert</button></form></li>`;
  }))).join("");
  const suppression = suppressed
    ? `<div role="status"><h2>Email delivery is suppressed</h2><p>${escapeHtml(suppressionDescription(subscriber.suppression_reason))} These alerts cannot be resumed for this address. Use a different email address to create a deliverable alert.</p></div>`
    : "";
  const allToken = env.ALERT_CAPABILITY_SECRET
    ? await signedCapability(env, subscriber.id, "unsubscribe_all")
    : subscriber.manage_token;
  const allForm = subscriptions.length
    ? `<form method="post" action="/unsubscribe"><input type="hidden" name="token" value="${escapeHtml(allToken)}"><input type="hidden" name="scope" value="all"><input type="hidden" name="return_token" value="${escapeHtml(manageToken)}"><button type="submit">Unsubscribe from all Funding Finder email alerts</button></form>`
    : "";
  return `<h1>Manage Funding Finder alerts</h1>${suppression}<p>These are the email alerts authorized for this address. Browser-local saved statuses, notes, profiles, documents, and chat are not shown because the alert service never receives them.</p><ul>${items || "<li>No alerts found.</li>"}</ul>${allForm}<p class="muted">Closing this page does not change your browser-local Saved list.</p>`;
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
      let operations = {
        staleRunningRuns: 0, lastCompletedAt: "", lastStatus: "", lastDurationMs: null,
        lastDailyCompletedAt: "", lastDailyStatus: "", lastStage: "", lastErrorCode: "",
        pendingEvaluationWindows: 0, oldestPendingEvaluationWindow: "", schedulerRecent: true,
      };
      try {
        if (typeof store.operationalHealth === "function") {
          operations = await store.operationalHealth(current.toISOString());
        }
      } catch { operations.schedulerRecent = false; }
      let providerConfigured = false;
      try { providerConfigured = providerFactory(env, fetchImpl).configured === true; } catch { /* unavailable */ }
      const providerSelected = config.provider === "resend";
      const schedulerReady = config.scheduler && operations.schedulerRecent
        && operations.staleRunningRuns === 0;
      const deliveryReady = config.enabled && databaseReady && providerSelected
        && providerConfigured && config.outbound && schedulerReady
        && config.capability && config.capabilityPrevious;
      const capabilityKeyId = config.capability
        ? (await sha256Hex(env.ALERT_CAPABILITY_SECRET)).slice(0, 16)
        : null;
      return json(origin, deliveryReady ? 200 : 503, {
        service: deliveryReady ? "available" : "unavailable",
        delivery_ready: deliveryReady,
        api_enabled: config.enabled,
        schema_version: ALERT_SCHEMA_VERSION,
        database_ready: databaseReady,
        email_provider: config.provider || "unconfigured",
        email_provider_selected: providerSelected,
        email_provider_configured: providerConfigured,
        email_template_version: ALERT_EMAIL_TEMPLATE_VERSION,
        outbound_email_enabled: config.outbound,
        scheduler_ready: schedulerReady,
        capability_signing_ready: config.capability,
        capability_previous_signing_ready: config.capabilityPrevious,
        capability_key_id: capabilityKeyId,
        stale_running_runs: operations.staleRunningRuns,
        last_run_completed_at: operations.lastCompletedAt || null,
        last_run_status: operations.lastStatus || null,
        last_run_duration_ms: operations.lastDurationMs,
        last_run_stage: operations.lastStage || null,
        last_run_error_code: operations.lastErrorCode || null,
        last_daily_run_completed_at: operations.lastDailyCompletedAt || null,
        last_daily_run_status: operations.lastDailyStatus || null,
        pending_evaluation_windows: Number(operations.pendingEvaluationWindows || 0),
        oldest_pending_evaluation_window: operations.oldestPendingEvaluationWindow || null,
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
        let provider;
        try { provider = providerFactory(env, fetchImpl); } catch { /* bounded service response below */ }
        if (!config.outbound || config.provider !== "resend" || provider?.configured !== true || !config.scheduler || !config.capability) {
          return json(origin, 503, { error: { code: "alerts_unavailable" } });
        }
        const baseline = baselineIds(subscription, suppliedBaseline);
        const emailHash = await sha256Hex(email);
        const definitionJson = stableJson(subscription.definition);
        const definitionHash = await sha256Hex(definitionJson);
        const subscriberId = `person_${emailHash.slice(0, 24)}`;
        const subscriptionId = `watch_${(await sha256Hex(`${subscriberId}|${subscription.type}|${definitionHash}`)).slice(0, 24)}`;
        const verificationNonce = tokenFactory();
        const createdAt = current.toISOString();
        const subscriber = await store.upsertSubscriber({
          id: subscriberId, email, manageToken: `retired:${subscriberId}`, now: createdAt,
        });
        const verificationToken = await createVerificationToken({
          subscriberId: subscriber.id, subscriptionId, nonce: verificationNonce,
        }, env.ALERT_CAPABILITY_SECRET);
        const verificationTokenHash = await sha256Hex(verificationToken);
        const verificationEventId = `verify_${(await sha256Hex(`${subscriptionId}|${verificationTokenHash}`)).slice(0, 32)}`;
        const stored = await store.createSubscriptionCycle({
          id: subscriptionId, subscriberId: subscriber.id, type: subscription.type,
          cadence: subscription.cadence, definitionJson, definitionHash,
          baselineOpportunityIds: baseline,
          suppressed: Boolean(subscriber.suppressed_at),
          verificationNonce,
          verificationTokenHash,
          verificationExpiresAt: new Date(current.getTime() + 24 * 60 * 60_000).toISOString(),
          verificationEventId,
          verificationEventKey: `verification:${verificationTokenHash}`,
          now: createdAt,
        });
        if (!stored?.id) throw new Error("Subscription cycle was not durably stored.");
        if (stored.cycleAccepted && !subscriber.suppressed_at) {
          try {
            await dispatchVerificationDeliveries({
              store, provider, env, now: current, tokenFactory, limit: 1,
              eventIds: [verificationEventId],
            });
          } catch {
            // The durable queued job remains available to the retry scheduler.
          }
        }
        return json(origin, 202, { status: "verification_required" });
      }

      if (path === "/verify" && request.method === "GET") {
        if (!await rateLimit(store, request, "verify", 20, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const token = String(url.searchParams.get("token") || "");
        const verified = token.length >= 32
          ? await store.verifySubscription(await sha256Hex(token), current.toISOString())
          : null;
        const manageToken = verified && config.capability
          ? await signedCapability(env, verified.subscriber_id, "manage")
          : verified?.manage_token;
        return verified
          ? verified.deliverySuppressed
            ? html(200, `<h1>Email verified</h1><p>Email delivery remains suppressed for this address, so this alert is not active. Use a different email address to create a deliverable alert.</p><p><a href="/manage?token=${encodeURIComponent(manageToken)}">Manage all alerts</a></p>`)
            : html(200, `<h1>Email verified</h1><p>Your Funding Finder alert is active.</p><p><a href="/manage?token=${encodeURIComponent(manageToken)}">Manage all alerts</a></p>`)
          : html(400, "<h1>This verification link is invalid or expired</h1><p>Create the alert again to receive a new link.</p>");
      }

      if (path === "/manage" && request.method === "GET") {
        if (!await rateLimit(store, request, "manage", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const subscriber = await resolveSubscriberCapability(
          store, String(url.searchParams.get("token") || ""), "manage", "", env, current,
        );
        if (!subscriber) return html(404, "<h1>Manage link not found</h1>");
        return html(200, await managePage(subscriber, await store.subscriptionsForSubscriber(subscriber.id), env));
      }

      if (path === "/manage" && request.method === "POST") {
        if (!await rateLimit(store, request, "manage", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const body = await formValues(request);
        const subscriptionId = String(body.subscription || "");
        const subscriber = await resolveSubscriberCapability(
          store, String(body.token || ""), "manage", "", env, current,
        );
        const updated = subscriber && await store.updateSubscriptionForSubscriber(
          subscriber.id, subscriptionId,
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
        const all = url.searchParams.get("scope") === "all";
        const purpose = all ? "unsubscribe_all" : "unsubscribe_one";
        const subscriber = await resolveSubscriberCapability(
          store, token, purpose, all ? "" : subscription, env, current,
        );
        if (!subscriber || (!all && !subscription)) return html(404, "<h1>Unsubscribe link not found</h1>");
        return all
          ? html(200, `<h1>Unsubscribe from all Funding Finder email alerts?</h1><form method="post" action="/unsubscribe"><input type="hidden" name="token" value="${escapeHtml(token)}"><input type="hidden" name="scope" value="all"><button type="submit">Unsubscribe from all alerts</button></form>`)
          : html(200, `<h1>Unsubscribe from this alert?</h1><form method="post" action="/unsubscribe"><input type="hidden" name="token" value="${escapeHtml(token)}"><input type="hidden" name="subscription" value="${escapeHtml(subscription)}"><button type="submit">Unsubscribe from this alert</button></form>`);
      }

      if (path === "/unsubscribe" && request.method === "POST") {
        if (!await rateLimit(store, request, "unsubscribe", 30, 3_600, current)) return html(429, "<h1>Try again later</h1>");
        const queryToken = String(url.searchParams.get("token") || "");
        const querySubscription = String(url.searchParams.get("subscription") || "");
        const queryAll = url.searchParams.get("scope") === "all";
        const body = queryToken && (querySubscription || queryAll) ? {} : await formValues(request);
        const token = queryToken || String(body.token || "");
        const all = queryAll || String(body.scope || "") === "all";
        const subscriptionId = querySubscription || String(body.subscription || "");
        const subscriber = await resolveSubscriberCapability(
          store, token, all ? "unsubscribe_all" : "unsubscribe_one",
          all ? "" : subscriptionId, env, current,
        );
        const removed = subscriber && (all
          ? await store.unsubscribeAllForSubscriber(subscriber.id, current.toISOString())
          : await store.unsubscribeForSubscriber(subscriber.id, subscriptionId, current.toISOString()));
        const returnToken = String(body.return_token || "");
        const returnSubscriber = removed && subscriber && returnToken
          ? await resolveSubscriberCapability(store, returnToken, "manage", "", env, current)
          : null;
        const returnToManage = returnSubscriber?.id === subscriber?.id
          ? `<p><a class="button-link" href="/manage?token=${escapeHtml(encodeURIComponent(returnToken))}">Return to manage alerts</a></p>`
          : "";
        return removed
          ? all
            ? html(200, `<h1>Successfully unsubscribed</h1><p>You have been successfully unsubscribed from all Funding Finder email alerts.</p>${returnToManage}`)
            : html(200, `<h1>Successfully unsubscribed</h1><p>You have been successfully unsubscribed from this Funding Finder alert.</p>${returnToManage}`)
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
        } else if (["email.delivered", "email.delivery_delayed", "email.failed"].includes(event.type)) {
          await store.recordProviderEvent(
            String(request.headers.get("svix-id") || ""), String(event.type),
            String(event.data?.email_id || ""), current.toISOString(),
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

export function weeklyDigestEligibilityCutoff(now) {
  const value = new Date(now);
  if (!Number.isFinite(value.getTime())) throw new TypeError("A valid digest cutoff time is required.");
  const sundayStart = Date.UTC(
    value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate() - value.getUTCDay(),
    13, 15, 0, 0,
  );
  const eligibleSunday = value.getTime() < sundayStart
    ? sundayStart - (7 * 86_400_000)
    : sundayStart;
  const cutoff = new Date(eligibleSunday);
  cutoff.setUTCHours(23, 59, 59, 999);
  return cutoff.toISOString();
}

export function weeklyDigestWindowFor(originatingAt) {
  const value = new Date(originatingAt);
  if (!Number.isFinite(value.getTime())) throw new TypeError("A valid evaluation window is required.");
  const daysUntilSunday = (7 - value.getUTCDay()) % 7;
  const window = new Date(Date.UTC(
    value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate() + daysUntilSunday,
    23, 59, 59, 999,
  ));
  return window.toISOString();
}

export function createScheduledHandler({
  storeFactory = env => new D1AlertStore(env.ALERTS_DB),
  providerFactory = (env, fetchImpl) => createEmailProvider(env, fetchImpl),
  assetLoader = (env, fetchImpl, options) => loadPublicAssets(env, fetchImpl, options),
  fetchImpl = (...args) => fetch(...args),
  now = () => new Date(),
  clock = () => Date.now(),
  runClaimFactory = () => randomToken(),
} = {}) {
  return async function scheduled(controller, env) {
    const scheduledAt = new Date(controller?.scheduledTime || Date.now());
    const current = now();
    const store = storeFactory(env);
    const budget = new SchedulerBudget({
      timeoutMs: Number(env.ALERT_SCHEDULER_TIMEOUT_MS) || undefined,
      clock,
    });
    const triggerKind = controller?.cron && controller.cron !== "15 13 * * *" ? "retry" : "daily";
    let runKind = triggerKind;
    let dailyInProgress = false;
    let continuation = { state: "none" };
    if (
      typeof store.dailyContinuationState === "function"
      || typeof store.needsDailyContinuation === "function"
    ) {
      const continuationValue = await budget.run(
        "continuation_check",
        async () => {
          if (typeof store.dailyContinuationState === "function") {
            return store.dailyContinuationState(current.toISOString());
          }
          return await store.needsDailyContinuation(current.toISOString())
            ? { state: "pending" }
            : { state: "none" };
        },
        15_000,
      );
      continuation = typeof continuationValue === "string"
        ? { state: continuationValue }
        : continuationValue || { state: "none" };
      if (continuation.state === "pending") runKind = "continuation";
      if (continuation.state === "running") {
        dailyInProgress = true;
        runKind = "retry";
      }
    }
    const evaluationWindowStartedAt = runKind === "daily"
      ? scheduledAt.toISOString()
      : runKind === "continuation"
        ? String(continuation.evaluationWindowStartedAt || scheduledAt.toISOString())
        : "";
    const weeklyWindowAt = runKind === "daily"
      ? weeklyDigestWindowFor(evaluationWindowStartedAt)
      : runKind === "continuation"
        ? String(continuation.weeklyWindowAt || weeklyDigestWindowFor(evaluationWindowStartedAt))
        : "";
    const evaluationInputGeneratedAt = runKind === "continuation"
      ? String(continuation.evaluationInputGeneratedAt || "")
      : "";
    const evaluationSourceGeneratedAt = runKind === "continuation"
      ? String(continuation.evaluationSourceGeneratedAt || "")
      : "";
    const scheduledIdentity = scheduledAt.toISOString().replace(/[^0-9]/g, "");
    const deferredDailyWindow = triggerKind === "daily"
      && (continuation.state === "pending" || continuation.state === "running")
      && String(continuation.evaluationWindowStartedAt || "") !== scheduledAt.toISOString()
      ? {
          id: `pending_${scheduledIdentity}_daily`,
          queuedAt: current.toISOString(),
          scheduledAt: scheduledAt.toISOString(),
          evaluationWindowStartedAt: scheduledAt.toISOString(),
          weeklyWindowAt: weeklyDigestWindowFor(scheduledAt),
        }
      : null;
    const run = {
      id: `run_${scheduledIdentity}_${triggerKind}`,
      scheduledAt: scheduledAt.toISOString(), runKind,
      startedAt: current.toISOString(), subscriptionCount: 0, matchedEventCount: 0,
      attemptedCount: 0, deliveredCount: 0, failedCount: 0, status: "running",
      cleanupDeletedCount: 0, cleanupErrorCode: "",
      errorCode: "", evaluationCompletedAt: "", stage: "starting",
      evaluationWindowStartedAt, weeklyWindowAt,
      evaluationInputGeneratedAt, evaluationSourceGeneratedAt,
      stageStartedAt: current.toISOString(),
      progress: { processedSubscriptions: 0, processedChanges: 0, continuationRequired: false },
      claimToken: runClaimFactory(),
      deferredDailyWindow,
    };
    const schedulerClaim = { runId: run.id, token: run.claimToken };
    let claimRevoked = false;
    let fencingSafe = true;
    const revokeClaim = async status => {
      const revokedAt = new Date(Math.max(current.getTime(), clock())).toISOString();
      const revoked = typeof store.revokeRunClaim === "function"
        ? await boundedFinalization(() => store.revokeRunClaim(
            run.id, run.claimToken, revokedAt, status, "scheduler_deadline_exceeded",
          ))
        : false;
      const stillCurrent = typeof store.runClaimIsCurrent === "function"
        ? await boundedFinalization(() => store.runClaimIsCurrent(run.id, run.claimToken))
        : !revoked;
      if (!revoked && stillCurrent) {
        throw Object.assign(new Error("The scheduler claim could not be revoked."), {
          code: "scheduler_fence_revoke_failed",
        });
      }
      claimRevoked = true;
    };
    let startOperation = null;
    let started;
    try {
      started = await budget.run(
        "run_start",
        () => {
          startOperation = Promise.resolve(store.startRun(run));
          return startOperation;
        },
        15_000,
        {
          onTimeout: async () => {
            const accepted = await startOperation;
            if (accepted) {
              await revokeClaim(runKind === "retry" ? "failed_timeout" : "incomplete_timeout");
            }
          },
        },
      );
    } catch (error) {
      const completed = now();
      run.status = error instanceof SchedulerFenceError
        ? "failed_fence_revoke"
        : error instanceof SchedulerTimeoutError
          ? runKind === "retry" ? "failed_timeout" : "incomplete_timeout"
          : "failed";
      run.errorCode = String(error?.code || "scheduler_failed").slice(0, 80);
      run.completedAt = completed.toISOString();
      run.durationMs = Math.max(0, completed.getTime() - current.getTime());
      return run;
    }
    if (started === false) return { ...run, status: "duplicate_skipped" };
    if (dailyInProgress) {
      const completed = now();
      run.status = "completed_skipped_daily_in_progress";
      run.stage = "completed";
      run.stageStartedAt = completed.toISOString();
      run.completedAt = completed.toISOString();
      run.durationMs = Math.max(0, completed.getTime() - current.getTime());
      run.progress = { ...run.progress, dailyInProgress: true };
      try {
        await boundedFinalization(() => store.finishRun(run));
      } catch (error) {
        run.status = "failed_finalization";
        run.errorCode = String(error?.code || "finalization_failed").slice(0, 80);
      }
      return run;
    }

    const revokeTimedOutClaim = async () => {
      const timeoutStatus = run.evaluationCompletedAt ? "failed_timeout" : "incomplete_timeout";
      await revokeClaim(timeoutStatus);
    };
    const stage = async (name, operation, maximumMs, progress = run.progress) => {
      const stageNow = new Date(Math.max(current.getTime(), clock())).toISOString();
      run.stage = name;
      run.stageStartedAt = stageNow;
      run.progress = { ...run.progress, ...(progress || {}) };
      if (typeof store.updateRunProgress === "function") {
        const updated = await budget.run(
          `${name}_progress`,
          () => store.updateRunProgress(run.id, {
            stage: name,
            stageStartedAt: stageNow,
            heartbeatAt: stageNow,
            progress: run.progress,
          }, schedulerClaim),
          15_000,
          { onTimeout: revokeTimedOutClaim },
        );
        if (updated === false) throw Object.assign(new Error("The scheduler claim changed."), {
          code: "scheduler_claim_lost",
        });
      }
      return budget.run(name, operation, maximumMs, { onTimeout: revokeTimedOutClaim });
    };

    const deliveryBatch = Math.max(1, Math.min(10, Number(env.ALERT_SCHEDULER_DELIVERY_BATCH) || 10));
    let continuationRequired = false;
    let evaluationCompleted = Boolean(continuation.evaluationCompleted);
    if (evaluationCompleted) {
      run.evaluationCompletedAt = String(continuation.evaluationCompletedAt || current.toISOString());
    }
    let failureStage = "";
    let failureStageStartedAt = "";
    try {
      if ((runKind === "daily" || runKind === "continuation") && !evaluationCompleted) {
        const assets = await stage(
          "asset_loading",
          signal => assetLoader(env, fetchImpl, { signal }),
          45_000,
        );
        const sourceGeneratedAt = String(assets?.changes?.generated_at || "");
        run.evaluationInputGeneratedAt = run.evaluationInputGeneratedAt || sourceGeneratedAt;
        run.evaluationSourceGeneratedAt = sourceGeneratedAt;
        if (typeof store.bindRunEvaluationInput === "function") {
          const bound = await stage(
            "evaluation_input_checkpoint",
            () => store.bindRunEvaluationInput(
              run.id, evaluationWindowStartedAt,
              run.evaluationInputGeneratedAt, run.evaluationSourceGeneratedAt,
              new Date(Math.max(current.getTime(), clock())).toISOString(),
              schedulerClaim,
            ),
            15_000,
          );
          if (!bound) {
            throw Object.assign(new Error("Evaluation input ownership changed during adoption."), {
              code: "evaluation_input_claim_lost",
            });
          }
        }
        const evaluation = await stage(
          "subscription_evaluation",
          signal => evaluateSubscriptions({
            store, assets, env, now: current,
            evaluationWindowStartedAt, weeklyWindowAt,
            evaluationInputGeneratedAt: run.evaluationInputGeneratedAt,
            schedulerClaim, signal,
          }),
          5 * 60_000,
        );
        Object.assign(run, {
          subscriptionCount: evaluation.subscriptionCount,
          matchedEventCount: evaluation.matchedEventCount,
        });
        continuationRequired = evaluation.continuationRequired === true;
        run.progress = {
          processedSubscriptions: evaluation.subscriptionCount,
          processedChanges: evaluation.processedChangeCount,
          continuationRequired,
          rebasedSubscriptions: evaluation.rebasedSubscriptionCount,
        };
        run.evaluationInputGeneratedAt = evaluation.evaluationInputGeneratedAt;
        run.evaluationSourceGeneratedAt = evaluation.evaluationSourceGeneratedAt;
        if (!continuationRequired) {
          run.evaluationCompletedAt = new Date(Math.max(current.getTime(), clock())).toISOString();
          evaluationCompleted = true;
          if (typeof store.markRunEvaluationComplete === "function") {
            await stage(
              "evaluation_checkpoint",
              () => store.markRunEvaluationComplete(
                run.id, run.evaluationCompletedAt, run.progress,
                schedulerClaim,
              ),
              15_000,
            );
          }
        }
      }

      const provider = await stage(
        "provider_initialization",
        () => providerFactory(env, fetchImpl),
        15_000,
      );
      const verification = await stage(
        "verification_delivery",
        signal => dispatchVerificationDeliveries({
          store, provider, env, now: current, limit: deliveryBatch,
          schedulerClaim, signal,
        }),
        2 * 60_000,
      );
      let immediate = { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
      let weekly = { attemptedCount: 0, deliveredCount: 0, failedCount: 0 };
      immediate = await stage(
        "immediate_delivery",
        signal => dispatchNotifications({
          store, provider, env, now: current, weekly: false, limit: deliveryBatch,
          schedulerClaim, signal,
        }),
        2 * 60_000,
      );
      const weeklyCutoff = weeklyDigestEligibilityCutoff(current);
      const originatingWindowDue = evaluationCompleted && weeklyWindowAt
        && weeklyWindowAt <= weeklyCutoff;
      const weeklyDue = !continuationRequired
        && typeof store.pendingDigestEvents === "function"
        && (runKind === "retry" || originatingWindowDue);
      if (weeklyDue) {
        weekly = await stage(
          "weekly_delivery",
          signal => dispatchNotifications({
            store, provider, env, now: current, weekly: true, limit: deliveryBatch,
            eligibleBefore: weeklyCutoff,
            schedulerClaim, signal,
          }),
          2 * 60_000,
        );
      }
      run.attemptedCount = verification.attemptedCount + immediate.attemptedCount + weekly.attemptedCount;
      run.deliveredCount = verification.deliveredCount + immediate.deliveredCount + weekly.deliveredCount;
      run.failedCount = verification.failedCount + immediate.failedCount + weekly.failedCount;
      run.status = continuationRequired
        ? run.failedCount ? "incomplete_evaluation_with_delivery_failures" : "incomplete_evaluation"
        : run.failedCount ? "completed_with_delivery_failures" : "completed";
    } catch (error) {
      failureStage = run.stage;
      failureStageStartedAt = run.stageStartedAt;
      run.errorCode = String(error?.code || "scheduler_failed").slice(0, 80);
      fencingSafe = !(error instanceof SchedulerFenceError)
        && String(error?.code || "") !== "scheduler_fence_revoke_failed";
      run.status = !fencingSafe
        ? "failed_fence_revoke"
        : error instanceof SchedulerTimeoutError
        ? (run.evaluationCompletedAt ? "failed_timeout" : "incomplete_timeout")
        : "failed";
    }
    try {
      if (claimRevoked || !fencingSafe) throw Object.assign(new Error("Cleanup skipped after claim loss."), {
        code: "cleanup_claim_unavailable",
      });
      if (typeof store.cleanupOperationalData === "function") {
        const cleanup = await stage(
          "cleanup",
          () => store.cleanupOperationalData(now().toISOString(), 100, schedulerClaim),
          20_000,
        );
        run.cleanupDeletedCount = Number(cleanup?.deletedCount || 0);
      }
    } catch (error) {
      run.cleanupErrorCode = error?.code === "cleanup_claim_unavailable"
        ? "cleanup_skipped_claim_unavailable"
        : error instanceof SchedulerTimeoutError
        ? "cleanup_timeout"
        : "cleanup_failed";
      if (claimRevoked) {
        run.status = run.evaluationCompletedAt ? "failed_timeout" : "incomplete_timeout";
        run.errorCode = "scheduler_deadline_exceeded";
      } else if (run.status === "completed") run.status = "completed_with_cleanup_failure";
    }
    if (failureStage) {
      run.stage = failureStage;
      run.stageStartedAt = failureStageStartedAt;
    }
    if (continuationRequired && run.status.startsWith("incomplete_evaluation")) {
      run.stage = "continuation_pending";
      run.stageStartedAt = now().toISOString();
      run.errorCode = "evaluation_continuation_required";
    }
    const completed = now();
    run.completedAt = completed.toISOString();
    run.durationMs = Math.max(0, completed.getTime() - current.getTime());
    if (run.status.startsWith("completed")) {
      run.stage = "completed";
      run.stageStartedAt = run.completedAt;
    }
    if (claimRevoked || !fencingSafe) return run;
    try {
      const finished = await boundedFinalization(() => store.finishRun(run));
      if (finished === false) {
        run.status = "failed_fence_revoke";
        run.errorCode = "scheduler_claim_lost";
      }
    } catch (error) {
      run.status = "failed_finalization";
      run.errorCode = String(error?.code || "finalization_failed").slice(0, 80);
    }
    return run;
  };
}

const handle = createHandler();
const scheduled = createScheduledHandler();

export default {
  fetch(request, env) { return handle(request, env); },
  scheduled(controller, env, context) { context.waitUntil(scheduled(controller, env)); },
};
