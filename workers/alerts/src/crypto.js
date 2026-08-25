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
