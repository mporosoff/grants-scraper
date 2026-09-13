# First exact-head review and bounded remediation

Candidate: `c2b09de1a7d64430cc869356a4a6a2335ac7f5f8`, PR #231. The automatic review completed on September 13, 2026 at 01:31 UTC. Required Python/browser CI run 34730510368 passed for that candidate only. No edits were made while its review was pending.

Both P1 findings are accepted and retained in the PR:

1. Discussion 3998245877: a before/after configuration comparison could preserve pre-existing drift. The affected provenance family was inspected before correction: runtime, plain variables, database/rate bindings, secret names, workers.dev and preview routing, zone routes, custom domains, cron triggers, serving traffic and module bytes. Capture and verification now compare the complete supported configuration to protected `wrangler.jsonc`, in addition to the before/after comparison and isolated-build module proof. Unexpected declarations or drift fail closed. Secret values are never retrieved or recorded. Route APIs follow the existing pinned Wrangler implementation.
2. Discussion 3998245879: compact independent-check requests omitted the disabled-thinking setting. Both check types now disable thinking before size checking, hashing and dispatch. The full evidence and fixed 512-token answer bound are retained. There is no paid retry or replay-key change.

Regression fixtures cover pre-existing and post-deployment binding/runtime/routing drift, mixed traffic, module changes, both check bodies and unchanged irreversible paid-request recovery. Live Cloudflare response compatibility and actual restricted deployment remain unexecuted until protected merge; fixtures do not establish serving provenance.

This same implementation checkpoint adds the restricted operator page at `/admin/contextual` and the private application's fixed localhost validation origin (`http://127.0.0.1:8876`) for the contextual API only. Every request still requires the existing administrator Access identity. There is no unauthenticated preflight exception, token export, Access-policy change or public activation. Operator startup/status are read-only; only the explicit action posts bounded canonical identifiers. Tests reject other origins and missing identity.

One exact-head verification review is required after this coherent remediation. Earlier CI is not evidence for the changed candidate. A repeated consequential issue is handled under the applicable owner-supplied convergence rule, without bypassing review or protections.
