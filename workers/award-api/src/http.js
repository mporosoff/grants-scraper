const MAX_SOURCE_RESPONSE_BYTES = 6 * 1024 * 1024;
const SOURCE_TIMEOUT_MS = 8_000;

export class AwardSourceError extends Error {
  constructor(code, kind = "unavailable") {
    super(code);
    this.name = "AwardSourceError";
    this.code = code;
    this.kind = kind;
  }
}

export function boundedRequestTimeout(monotonicNow, operationDeadline, maximumTimeout) {
  const remaining = Math.floor(operationDeadline - monotonicNow());
  if (remaining <= 0) throw new AwardSourceError("source_timeout");
  return Math.min(maximumTimeout, remaining);
}

export async function withinOperationBudget(operation, monotonicNow, operationDeadline, maximumTimeout) {
  const timeoutMs = boundedRequestTimeout(monotonicNow, operationDeadline, maximumTimeout);
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new AwardSourceError("source_timeout")), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSourceText(fetchImpl, url, options = {}, {
  maximumBytes = MAX_SOURCE_RESPONSE_BYTES,
  timeoutMs = SOURCE_TIMEOUT_MS,
} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      const code = response.status === 429 ? "source_rate_limited" : "source_unavailable";
      throw new AwardSourceError(code);
    }
    const declaredBytes = Number(response.headers.get("content-length") || 0);
    if (declaredBytes > maximumBytes) {
      throw new AwardSourceError("source_response_too_large");
    }
    const body = await response.text();
    if (new TextEncoder().encode(body).byteLength > maximumBytes) {
      throw new AwardSourceError("source_response_too_large");
    }
    return { body, response };
  } catch (error) {
    if (error?.name === "AbortError") throw new AwardSourceError("source_timeout");
    if (error instanceof AwardSourceError) throw error;
    throw new AwardSourceError("source_unavailable");
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSourceJson(fetchImpl, url, options = {}, requestLimits = {}) {
  const { body } = await fetchSourceText(fetchImpl, url, options, requestLimits);
  try {
    return JSON.parse(body);
  } catch {
    throw new AwardSourceError("source_invalid_response");
  }
}

export { MAX_SOURCE_RESPONSE_BYTES, SOURCE_TIMEOUT_MS };
