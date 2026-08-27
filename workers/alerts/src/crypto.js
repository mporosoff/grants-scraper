export function randomToken(byteLength = 32, cryptoImpl = crypto) {
  const bytes = new Uint8Array(byteLength);
  cryptoImpl.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export async function sha256Hex(value, cryptoImpl = crypto) {
  const digest = await cryptoImpl.subtle.digest("SHA-256", new TextEncoder().encode(String(value)));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

function base64UrlEncode(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlDecode(value) {
  const normalized = String(value || "").replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  return Uint8Array.from(atob(padded), character => character.charCodeAt(0));
}

async function hmac(value, secret, cryptoImpl = crypto) {
  const key = await cryptoImpl.subtle.importKey(
    "raw", new TextEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  return new Uint8Array(await cryptoImpl.subtle.sign(
    "HMAC", key, new TextEncoder().encode(String(value)),
  ));
}

export async function createCapability({ subscriberId, purpose, subscriptionId = "" }, secret, cryptoImpl = crypto) {
  if (!secret || !subscriberId || !purpose) throw new Error("Alert capability signing is unavailable.");
  const payload = base64UrlEncode(new TextEncoder().encode(JSON.stringify({
    v: 1, s: String(subscriberId), p: String(purpose), q: String(subscriptionId || ""),
  })));
  const signed = `v1.${payload}`;
  return `${signed}.${base64UrlEncode(await hmac(signed, secret, cryptoImpl))}`;
}

export async function verifyCapability(token, {
  secret, previousSecret = "", purpose, subscriptionId = "", cryptoImpl = crypto,
} = {}) {
  const [version, payload, signature, extra] = String(token || "").split(".");
  if (version !== "v1" || !payload || !signature || extra) return null;
  let decoded;
  let received;
  try {
    decoded = JSON.parse(new TextDecoder().decode(base64UrlDecode(payload)));
    received = base64UrlDecode(signature);
  } catch { return null; }
  if (
    decoded?.v !== 1 || typeof decoded?.s !== "string" || decoded.s.length > 100
    || decoded?.p !== purpose || String(decoded?.q || "") !== String(subscriptionId || "")
  ) return null;
  const signed = `${version}.${payload}`;
  for (const candidate of [secret, previousSecret].filter(Boolean)) {
    const expected = await hmac(signed, candidate, cryptoImpl);
    if (constantTimeEqual(expected, received)) return decoded;
  }
  return null;
}

export async function verificationToken({ subscriberId, subscriptionId, nonce }, secret, cryptoImpl = crypto) {
  const signed = await hmac(
    `funding-finder-verification-v2|${subscriberId}|${subscriptionId}|${nonce}`,
    secret,
    cryptoImpl,
  );
  return base64UrlEncode(signed);
}

export async function capabilityUrls(env, subscriberId, subscriptionId, cryptoImpl = crypto) {
  const origin = String(env.PUBLIC_WORKER_ORIGIN || "").replace(/\/$/, "");
  const secret = String(env.ALERT_CAPABILITY_SECRET || "");
  const manage = await createCapability({ subscriberId, purpose: "manage" }, secret, cryptoImpl);
  const unsubscribeThis = await createCapability({
    subscriberId, purpose: "unsubscribe_one", subscriptionId,
  }, secret, cryptoImpl);
  const unsubscribeAll = await createCapability({ subscriberId, purpose: "unsubscribe_all" }, secret, cryptoImpl);
  return {
    manage: `${origin}/manage?token=${encodeURIComponent(manage)}`,
    unsubscribeThis: `${origin}/unsubscribe?token=${encodeURIComponent(unsubscribeThis)}&subscription=${encodeURIComponent(subscriptionId)}`,
    unsubscribeAll: `${origin}/unsubscribe?token=${encodeURIComponent(unsubscribeAll)}&scope=all`,
  };
}

export async function verifySvixWebhook({ payload, headers, secret, now = new Date(), cryptoImpl = crypto }) {
  const id = String(headers.id || "");
  const timestamp = String(headers.timestamp || "");
  const signatures = String(headers.signature || "").split(/\s+/).flatMap(item => {
    const [version, encoded] = item.split(",", 2);
    return version === "v1" && encoded ? [encoded] : [];
  });
  const seconds = Number(timestamp);
  if (!id || !Number.isFinite(seconds) || Math.abs(now.getTime() / 1_000 - seconds) > 300 || !signatures.length) return false;
  const encodedSecret = String(secret || "").replace(/^whsec_/, "");
  let keyBytes;
  try { keyBytes = Uint8Array.from(atob(encodedSecret), character => character.charCodeAt(0)); }
  catch { return false; }
  const key = await cryptoImpl.subtle.importKey(
    "raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signed = new TextEncoder().encode(`${id}.${timestamp}.${payload}`);
  const expected = new Uint8Array(await cryptoImpl.subtle.sign("HMAC", key, signed));
  return signatures.some(signature => {
    try {
      const received = Uint8Array.from(atob(signature), character => character.charCodeAt(0));
      return constantTimeEqual(expected, received);
    } catch {
      return false;
    }
  });
}
