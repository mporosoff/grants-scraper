export const ALERT_EMAIL_TEMPLATE_VERSION = "phase4-operations-20260827";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function clean(value, maximum = 600) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
}

function safeUrl(value) {
  try {
    const url = new URL(clean(value, 1_000));
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function displayDate(value) {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))
    ? new Date(`${value}T12:00:00Z`)
    : null;
  return date && Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("en-US", {
        month: "long", day: "numeric", year: "numeric", timeZone: "UTC",
      }).format(date)
    : clean(value, 40);
}

function links(env, manageToken, subscriptionId) {
  const origin = String(env.PUBLIC_WORKER_ORIGIN).replace(/\/$/, "");
  const token = encodeURIComponent(manageToken);
  const subscription = encodeURIComponent(subscriptionId);
  return {
    manage: `${origin}/manage?token=${token}`,
    unsubscribeThis: `${origin}/unsubscribe?token=${token}&subscription=${subscription}`,
    unsubscribeAll: `${origin}/unsubscribe?token=${token}&scope=all`,
  };
}

function footerHtml(urls, scope = "subscription") {
  const unsubscribeUrl = scope === "all" ? urls.unsubscribeAll : urls.unsubscribeThis;
  const unsubscribeLabel = scope === "all"
    ? "Unsubscribe from all Funding Finder email alerts"
    : "Unsubscribe from this alert";
  return `<div style="border-top:1px solid #d8dfeb;margin-top:24px;padding-top:16px"><p style="margin:0 0 10px"><a href="${escapeHtml(urls.manage)}" style="color:#021bc3">Manage all alerts</a> &middot; <a href="${escapeHtml(unsubscribeUrl)}" style="color:#021bc3">${unsubscribeLabel}</a></p><p style="color:#58647a;font-size:12px;line-height:1.5;margin:0">Funding Finder stores only the alert information you authorized. Verify opportunity details in the official notice.</p></div>`;
}

function footerText(urls, scope = "subscription") {
  const unsubscribe = scope === "all"
    ? `Unsubscribe from all Funding Finder email alerts: ${urls.unsubscribeAll}`
    : `Unsubscribe from this alert: ${urls.unsubscribeThis}`;
  return `\n\nManage all alerts: ${urls.manage}\n${unsubscribe}\n\nVerify opportunity details in the official notice.`;
}

function emailFrame(content, preheader = "Funding Finder alert") {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="background:#f3f6fb;color:#14213d;font:16px/1.5 Arial,sans-serif;margin:0;padding:0"><div style="display:none;max-height:0;overflow:hidden;opacity:0">${escapeHtml(preheader)}</div><main style="background:#ffffff;border:1px solid #d8dfeb;border-radius:12px;box-sizing:border-box;margin:20px auto;max-width:640px;padding:24px;width:calc(100% - 24px)">${content}</main></body></html>`;
}

function actionHtml(body) {
  const actions = [];
  if (body.fundingFinderUrl) {
    actions.push(`<a href="${escapeHtml(body.fundingFinderUrl)}" style="background:#021bc3;border-radius:7px;color:#ffffff;display:inline-block;font-weight:700;margin:0 8px 8px 0;padding:10px 14px;text-decoration:none">Open in Funding Finder &rarr;</a>`);
  }
  if (body.officialUrl) {
    actions.push(`<a href="${escapeHtml(body.officialUrl)}" style="border:1px solid #021bc3;border-radius:7px;color:#021bc3;display:inline-block;font-weight:700;margin:0 8px 8px 0;padding:9px 13px;text-decoration:none">Verify on official source &rarr;</a>`);
  }
  return actions.length ? `<p style="margin:18px 0 0">${actions.join("")}</p>` : "";
}

function actionText(body) {
  return [
    body.fundingFinderUrl ? `Open in Funding Finder: ${body.fundingFinderUrl}` : "",
    body.officialUrl ? `Verify on official source: ${body.officialUrl}` : "",
  ].filter(Boolean).join("\n");
}

export function verificationEmail({ env, to, token, subscriptionId, manageToken, capabilityLinks = null, type }) {
  const origin = String(env.PUBLIC_WORKER_ORIGIN).replace(/\/$/, "");
  const verify = `${origin}/verify?token=${encodeURIComponent(token)}`;
  const urls = capabilityLinks || links(env, manageToken, subscriptionId);
  const kind = {
    opportunity: "opportunity watch", saved_search: "saved-search alert", program: "program watch",
  }[type] || "alert";
  const text = `Verify your Funding Finder ${kind}\n\nActivate it: ${verify}${footerText(urls)}`;
  return {
    to,
    subject: "Verify your Funding Finder alert",
    text,
    html: emailFrame(`<h1 style="color:#001e5f;font-size:24px;line-height:1.2;margin:0 0 12px">Verify your Funding Finder alert</h1><p>Activate your ${escapeHtml(kind)} using this one-time link:</p><p><a href="${escapeHtml(verify)}" style="background:#021bc3;border-radius:7px;color:#ffffff;display:inline-block;font-weight:700;padding:10px 14px;text-decoration:none">Verify email and activate alert</a></p>${footerHtml(urls)}`, `Verify your Funding Finder ${kind}`),
    headers: { "List-Unsubscribe": `<${urls.unsubscribeThis}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
  };
}

function eventTitle(event) {
  return {
    strong_match: "New Strong funding match",
    deadline_changed: "Funding deadline changed",
    amended: "Funding opportunity amended",
    closing_reminder: "Funding deadline reminder",
    status_changed: "Funding opportunity status changed",
    program_new_cycle: "New solicitation in a program you watch",
    program_amended: "Program solicitation changed",
    program_deadline_changed: "Program solicitation deadline changed",
    program_status_changed: "Program solicitation status changed",
  }[event.event_kind] || "Funding Finder alert";
}

function eventBody(event) {
  const payload = typeof event.payload_json === "string" ? JSON.parse(event.payload_json) : event.payload;
  const whyMatched = Array.isArray(payload?.why_matched)
    ? payload.why_matched.map(value => clean(value, 320)).filter(Boolean).slice(0, 2)
    : [];
  return {
    title: clean(payload?.title) || "Funding opportunity",
    agency: clean(payload?.agency),
    program: clean(payload?.program),
    detail: clean(payload?.detail),
    deadline: displayDate(payload?.close_date),
    whyMatched,
    fundingFinderUrl: safeUrl(payload?.funding_finder_url),
    officialUrl: safeUrl(payload?.official_url || payload?.url),
  };
}

function eventText(heading, body) {
  const rows = [
    heading,
    "",
    body.title,
    body.agency ? `Agency: ${body.agency}` : "",
    body.program ? `Program: ${body.program}` : "",
    body.deadline ? `Deadline: ${body.deadline}` : "",
    body.detail ? `Update: ${body.detail}` : "",
    body.whyMatched.length ? `\nWhy it matched:\n${body.whyMatched.map(reason => `- ${reason}`).join("\n")}` : "",
    actionText(body) ? `\n${actionText(body)}` : "",
  ];
  return rows.filter((row, index) => row || index === 1).join("\n");
}

function eventHtml(heading, body, headingLevel = 1) {
  const tag = headingLevel === 1 ? "h1" : "h2";
  const size = headingLevel === 1 ? "24px" : "20px";
  const facts = [
    body.agency ? `<p style="margin:5px 0"><strong>Agency:</strong> ${escapeHtml(body.agency)}</p>` : "",
    body.program ? `<p style="margin:5px 0"><strong>Program:</strong> ${escapeHtml(body.program)}</p>` : "",
    body.deadline ? `<p style="margin:5px 0"><strong>Deadline:</strong> ${escapeHtml(body.deadline)}</p>` : "",
    body.detail ? `<p style="margin:10px 0 0"><strong>Update:</strong> ${escapeHtml(body.detail)}</p>` : "",
  ].join("");
  const reasons = body.whyMatched.length
    ? `<div style="background:#f3f6fb;border-radius:8px;margin-top:14px;padding:12px 14px"><p style="font-weight:700;margin:0 0 6px">Why it matched</p><ul style="margin:0;padding-left:20px">${body.whyMatched.map(reason => `<li style="margin:4px 0">${escapeHtml(reason)}</li>`).join("")}</ul></div>`
    : "";
  return `<${tag} style="color:#001e5f;font-size:${size};line-height:1.25;margin:0 0 10px">${escapeHtml(heading)}</${tag}><p style="font-size:18px;font-weight:700;margin:0 0 10px">${escapeHtml(body.title)}</p>${facts}${reasons}${actionHtml(body)}`;
}

export function eventEmail({ env, event, capabilityLinks = null }) {
  const urls = capabilityLinks || links(env, event.manage_token, event.subscription_id);
  const heading = eventTitle(event);
  const body = eventBody(event);
  return {
    to: event.email,
    subject: heading,
    text: `${eventText(heading, body)}${footerText(urls)}`,
    html: emailFrame(`${eventHtml(heading, body)}${footerHtml(urls)}`, `${heading}: ${body.title}`),
    headers: { "List-Unsubscribe": `<${urls.unsubscribeThis}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
  };
}

export function digestEmail({ env, events, hasOverflow = false, capabilityLinks = null }) {
  const first = events[0];
  const urls = capabilityLinks || links(env, first.manage_token, first.subscription_id);
  const items = events.map(event => ({ heading: eventTitle(event), ...eventBody(event) }));
  const digestText = items.map(item => eventText(item.heading, item)).join("\n\n---\n\n");
  const digestHtml = items.map(item => `<section style="border-top:1px solid #d8dfeb;margin-top:20px;padding-top:20px">${eventHtml(item.heading, item, 2)}</section>`).join("");
  const overflowText = hasOverflow
    ? "\n\nAdditional updates remain queued for a later digest."
    : "";
  const overflowHtml = hasOverflow
    ? '<p style="background:#fff8e6;border-radius:8px;margin:20px 0 0;padding:12px 14px"><strong>Additional updates remain queued for a later digest.</strong></p>'
    : "";
  return {
    to: first.email,
    subject: `Funding Finder weekly digest: ${items.length} ${items.length === 1 ? "update" : "updates"}`,
    text: `Funding Finder weekly digest\n\n${digestText}${overflowText}${footerText(urls, "all")}`,
    html: emailFrame(`<h1 style="color:#001e5f;font-size:24px;line-height:1.2;margin:0">Funding Finder weekly digest</h1><p style="color:#58647a;margin:6px 0 0">${items.length} ${items.length === 1 ? "update" : "updates"}</p>${digestHtml}${overflowHtml}${footerHtml(urls, "all")}`, `Funding Finder weekly digest: ${items.length} ${items.length === 1 ? "update" : "updates"}`),
    headers: { "List-Unsubscribe": `<${urls.unsubscribeAll}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
  };
}
