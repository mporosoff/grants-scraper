#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const KEY_ID_PATTERN = /^[0-9a-f]{16}$/;

function checkedKeyId(value, label) {
  const keyId = String(value || "").trim().toLowerCase();
  if (!KEY_ID_PATTERN.test(keyId)) throw new Error(`${label} must be a 16-character hexadecimal fingerprint.`);
  return keyId;
}

export function validateAlertCapabilityRotation(health, currentValue, previousValue) {
  if (!health || typeof health !== "object" || Array.isArray(health)) {
    throw new Error("The deployed Alerts health response must be a JSON object.");
  }
  const currentKeyId = checkedKeyId(currentValue, "Current key ID");
  const previousKeyId = checkedKeyId(previousValue, "Previous key ID");

  if (Object.hasOwn(health, "capability_key_id")) {
    const deployedKeyId = checkedKeyId(health.capability_key_id, "Deployed key ID");
    if (deployedKeyId !== currentKeyId && deployedKeyId !== previousKeyId) {
      throw new Error("ALERT_CAPABILITY_PREVIOUS_SECRET must match the currently deployed signing key before rotation.");
    }
    return Object.freeze({ mode: "verified-continuity", deployedKeyId });
  }

  const legacyBootstrap = health.service === "available"
    && health.delivery_ready === true
    && health.api_enabled === true
    && health.schema_version === 2
    && health.database_ready === true
    && health.email_provider === "resend"
    && health.email_provider_selected === true
    && health.email_provider_configured === true
    && health.email_template_version === "phase2-lifecycle-20260825"
    && health.outbound_email_enabled === true
    && health.scheduler_ready === true;
  if (!legacyBootstrap) {
    throw new Error("The deployed Alerts signing-key fingerprint is unavailable; refusing secret mutation outside the verified Phase 2 bootstrap contract.");
  }
  return Object.freeze({ mode: "verified-phase2-bootstrap", deployedKeyId: "" });
}

function run() {
  const [currentKeyId, previousKeyId] = process.argv.slice(2);
  const raw = readFileSync(0, "utf8");
  let health;
  try { health = JSON.parse(raw); }
  catch { throw new Error("The deployed Alerts health response was not valid JSON."); }
  const result = validateAlertCapabilityRotation(health, currentKeyId, previousKeyId);
  process.stdout.write(`${result.mode}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { run(); }
  catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
