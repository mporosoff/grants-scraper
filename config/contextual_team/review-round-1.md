# First exact-head review and bounded remediation

Candidate: `c2b09de1a7d64430cc869356a4a6a2335ac7f5f8`, PR #231. The automatic review completed on September 13, 2026 at 01:31 UTC. Required Python/browser CI run 34730510368 passed for that candidate only. No edits were made while its review was pending.

Both P1 findings are accepted and retained in the PR:

1. Discussion 3998245877: a before/after configuration comparison could preserve pre-existing drift. The affected provenance family was inspected before correction: runtime, plain variables, database/rate bindings, secret names, workers.dev and preview routing, zone routes, custom domains, cron triggers, serving traffic and module bytes. Capture and verification now compare the complete supported configuration to protected `wrangler.jsonc`, in addition to the before/after comparison and isolated-build module proof. Unexpected declarations or drift fail closed. Secret values are never retrieved or recorded. Route APIs follow the existing pinned Wrangler implementation.
2. Discussion 3998245879: compact independent-check requests omitted the disabled-thinking setting. Both check types now disable thinking before size checking, hashing and dispatch. The full evidence and fixed 512-token answer bound are retained. There is no paid retry or replay-key change.

Regression fixtures cover pre-existing and post-deployment binding/runtime/routing drift, mixed traffic, module changes, both check bodies and unchanged irreversible paid-request recovery. Live Cloudflare response compatibility and actual restricted deployment remain unexecuted until protected merge; fixtures do not establish serving provenance.

This same implementation checkpoint adds the restricted operator page at `/admin/contextual` and the private application's fixed localhost validation origin (`http://127.0.0.1:8876`) for the contextual API only. Every request still requires the existing administrator Access identity. There is no unauthenticated preflight exception, token export, Access-policy change or public activation. Operator startup/status are read-only; only the explicit action posts bounded canonical identifiers. Tests reject other origins and missing identity.

One exact-head verification review is required after this coherent remediation. Earlier CI is not evidence for the changed candidate. A repeated consequential issue is handled under the applicable owner-supplied convergence rule, without bypassing review or protections.

## Owner-authorized recovery-state resumption

The verification of `61d2829b4553adbc7f944ee8b50b411b352ad0c9` completed in review 5189029706 on September 13 at 02:06 UTC. P1 discussion 3998349238 identified that a timeout or HTTP error without usage retained the irreversible ledger reservation but was reported as an ordinary terminal failure, releasing the Worker slot. The experiment stopped and preserved that finding, its reproduction and passing CI run 34731851200. No provider dispatch or restricted deployment had occurred.

The owner subsequently instructed: “Ok go ahead and execute the four indicated tasks and then we will check in again.” This starts one bounded repair/re-review round for the named recovery invariant, followed by the already-authorized restricted deployment, eight-scope assessment/extension/check and browser corrections if review clears. It does not authorize public activation or a new allowance.

The completed read-only invariant audit covered ledger claims/reconciliation, successful/invalid/missing caches, receipt/checkpoint failures, workflow artifact-before-callback ordering, and Worker ownership/immutable completion/currentness. The correction derives recovery from durable unknown usage or a typed missing/corrupt paid-result condition, rather than searching exception messages. Unknown usage blocks new contextual paid requests. Recovery callbacks retain the sole active slot and their immutable receipt; expiry and repeated callbacks cannot hide or release the unresolved state. Known reconciled failures and pre-dispatch budget deferrals remain distinct and cannot reopen their logical job.

Fresh focused evidence: 42 Python executor/accounting checks and 36 Node Worker/deployment/console/intake contracts pass. New actual-main fixtures cover timeout, HTTP 503, missing usage, malformed response, receipt-write failure, and reconciled success with lost cache. Three independent restorations per uncertain case make zero duplicate fixture-provider requests, including attempts to start another scope. Existing eight-boundary crash injection and complete exact-cache reuse still pass. Actual SQLite contracts cover repeated recovery callbacks, another visitor/scope/run, immutable conflicts and expiration. All provider traffic in these checks is local fixture traffic; no scientific outcomes or real usage are claimed.

Required exact-head CI and one independent verification review remain pending until submitted for this correction. Their results must be collected before any protected merge.
