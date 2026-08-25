export const RESEND_ENDPOINT = "https://api.resend.com/emails";
export const ALERT_SENDER = "Funding Finder <notifications@funding.porosoffresearchgroup.com>";

export class ResendEmailProvider {
  constructor({ apiKey, fetchImpl = fetch } = {}) {
    this.apiKey = String(apiKey || "");
    this.fetchImpl = fetchImpl;
  }

  get configured() { return Boolean(this.apiKey); }

  async sendEmail(message, idempotencyKey) {
    if (!this.configured) throw Object.assign(new Error("Email provider is not configured."), { code: "provider_unconfigured" });
    const response = await this.fetchImpl(RESEND_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        "Idempotency-Key": String(idempotencyKey).slice(0, 256),
      },
      body: JSON.stringify({
        from: ALERT_SENDER,
        to: [message.to],
        subject: message.subject,
        html: message.html,
        text: message.text,
        headers: message.headers || {},
      }),
    });
    let payload = null;
    try { payload = await response.json(); } catch { /* bounded error below */ }
    if (!response.ok || !payload?.id) {
      throw Object.assign(new Error("Email provider rejected the request."), {
        code: response.status === 429 ? "provider_rate_limited" : "provider_failed",
      });
    }
    return { id: String(payload.id) };
  }
}

export class MockEmailProvider {
  constructor({ fail = false } = {}) {
    this.fail = fail;
    this.messages = [];
    this.configured = true;
  }

  async sendEmail(message, idempotencyKey) {
    if (this.fail) throw Object.assign(new Error("Mock provider failure."), { code: "provider_failed" });
    const id = `mock-${this.messages.length + 1}`;
    this.messages.push({ ...message, idempotencyKey, id });
    return { id };
  }
}

export function createEmailProvider(env, fetchImpl = fetch) {
  if (String(env.EMAIL_PROVIDER || "").toLowerCase() === "resend") {
    return new ResendEmailProvider({ apiKey: env.RESEND_API_KEY, fetchImpl });
  }
  throw new Error("Production Worker requires the Resend provider.");
}
