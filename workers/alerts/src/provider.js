export const RESEND_ENDPOINT = "https://api.resend.com/emails";
export const ALERT_SENDER = "Funding Finder <notifications@funding.porosoffresearchgroup.com>";
export const PROVIDER_TIMEOUT_MS = 10_000;

export class ResendEmailProvider {
  constructor({ apiKey, fetchImpl = fetch, timeoutMs = PROVIDER_TIMEOUT_MS } = {}) {
    this.apiKey = String(apiKey || "");
    this.fetchImpl = fetchImpl;
    this.timeoutMs = Math.max(1, Math.min(30_000, Number(timeoutMs) || PROVIDER_TIMEOUT_MS));
  }

  get configured() { return Boolean(this.apiKey); }

  async sendEmail(message, idempotencyKey) {
    if (!this.configured) throw Object.assign(new Error("Email provider is not configured."), { code: "provider_unconfigured" });
    let response;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      response = await this.fetchImpl(RESEND_ENDPOINT, {
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
        signal: controller.signal,
      });
    } catch {
      throw Object.assign(new Error("Email provider request failed."), {
        code: "provider_network_failure",
        providerFailureKind: "network",
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }
    let payload = null;
    try { payload = await response.json(); } catch { /* bounded error below */ }
    if (!response.ok || !payload?.id) {
      const status = Number(response.status) || 0;
      const retryable = response.ok || status === 408 || status === 409 || status === 425 || status === 429 || status >= 500;
      throw Object.assign(new Error("Email provider rejected the request."), {
        code: status === 429
          ? "provider_rate_limited"
          : retryable ? "provider_unavailable" : "provider_rejected",
        providerFailureKind: "http",
        providerHttpStatus: status,
        retryable,
      });
    }
    return { id: String(payload.id) };
  }
}

export class MockEmailProvider {
  constructor({ fail = false, failures = [] } = {}) {
    this.fail = fail;
    this.failures = [...failures];
    this.messages = [];
    this.configured = true;
  }

  async sendEmail(message, idempotencyKey) {
    const failure = this.failures.shift();
    if (failure) throw Object.assign(new Error("Mock provider failure."), failure);
    if (this.fail) throw Object.assign(new Error("Mock provider failure."), {
      code: "provider_unavailable", retryable: true,
    });
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
