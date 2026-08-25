function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function clean(value, maximum = 600) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
}

function links(env, manageToken, subscriptionId) {
  const origin = String(env.PUBLIC_WORKER_ORIGIN).replace(/\/$/, "");
  const token = encodeURIComponent(manageToken);
  const subscription = encodeURIComponent(subscriptionId);
  return {
    manage: `${origin}/manage?token=${token}`,
    unsubscribe: `${origin}/unsubscribe?token=${token}&subscription=${subscription}`,
  };
}

function footerHtml(urls) {
  return `<hr><p><a href="${escapeHtml(urls.manage)}">Manage alerts</a> · <a href="${escapeHtml(urls.unsubscribe)}">Unsubscribe</a></p><p style="color:#58647a;font-size:12px">Funding Finder stores only the alert information you authorized. Verify opportunity details in the official notice.</p>`;
}

function footerText(urls) {
  return `\n\nManage alerts: ${urls.manage}\nUnsubscribe: ${urls.unsubscribe}\n\nVerify opportunity details in the official notice.`;
}

export function verificationEmail({ env, to, token, subscriptionId, manageToken, type }) {
  const origin = String(env.PUBLIC_WORKER_ORIGIN).replace(/\/$/, "");
  const verify = `${origin}/verify?token=${encodeURIComponent(token)}`;
  const urls = links(env, manageToken, subscriptionId);
  const kind = {
    opportunity: "opportunity watch", saved_search: "saved-search alert", program: "program watch",
  }[type] || "alert";
  const text = `Verify your Funding Finder ${kind}\n\nActivate it: ${verify}${footerText(urls)}`;
  return {
    to,
    subject: "Verify your Funding Finder alert",
    text,
    html: `<h1>Verify your Funding Finder alert</h1><p>Activate your ${escapeHtml(kind)} using this one-time link:</p><p><a href="${escapeHtml(verify)}">Verify email and activate alert</a></p>${footerHtml(urls)}`,
    headers: { "List-Unsubscribe": `<${urls.unsubscribe}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
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
  return {
    title: clean(payload?.title) || "Funding opportunity",
    agency: clean(payload?.agency),
    detail: clean(payload?.detail),
    deadline: clean(payload?.close_date, 20),
    url: clean(payload?.url, 1_000),
  };
}

export function eventEmail({ env, event }) {
  const urls = links(env, event.manage_token, event.subscription_id);
  const heading = eventTitle(event);
  const body = eventBody(event);
  const details = [body.agency, body.detail, body.deadline ? `Deadline: ${body.deadline}` : ""].filter(Boolean);
  const action = body.url ? `\n\nOpen in Funding Finder or the official source: ${body.url}` : "";
  return {
    to: event.email,
    subject: heading,
    text: `${heading}\n\n${body.title}${details.length ? `\n${details.join("\n")}` : ""}${action}${footerText(urls)}`,
    html: `<h1>${escapeHtml(heading)}</h1><h2>${escapeHtml(body.title)}</h2>${details.map(item => `<p>${escapeHtml(item)}</p>`).join("")}${body.url ? `<p><a href="${escapeHtml(body.url)}">Open and verify details →</a></p>` : ""}${footerHtml(urls)}`,
    headers: { "List-Unsubscribe": `<${urls.unsubscribe}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
  };
}

export function digestEmail({ env, events }) {
  const first = events[0];
  const urls = links(env, first.manage_token, first.subscription_id);
  const items = events.map(event => ({ heading: eventTitle(event), ...eventBody(event) }));
  return {
    to: first.email,
    subject: `Funding Finder weekly digest: ${items.length} ${items.length === 1 ? "update" : "updates"}`,
    text: `Funding Finder weekly digest\n\n${items.map(item => `${item.heading}\n${item.title}${item.detail ? `\n${item.detail}` : ""}${item.url ? `\n${item.url}` : ""}`).join("\n\n")}${footerText(urls)}`,
    html: `<h1>Funding Finder weekly digest</h1>${items.map(item => `<section><h2>${escapeHtml(item.heading)}</h2><p><strong>${escapeHtml(item.title)}</strong></p>${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : ""}${item.url ? `<p><a href="${escapeHtml(item.url)}">Open and verify details →</a></p>` : ""}</section>`).join("")}${footerHtml(urls)}`,
    headers: { "List-Unsubscribe": `<${urls.unsubscribe}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" },
  };
}
