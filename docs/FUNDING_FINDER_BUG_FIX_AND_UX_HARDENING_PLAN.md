# Funding Finder Bug Fix and UX Hardening Plan

**Document status:** Authoritative implementation map and execution ground truth
**Plan version:** 1.0
**Repository:** `mporosoff/grants-scraper`
**Audited baseline:** protected `main` at `e9ddcda995dd9f1fe5462bf8fde81a2d9922fc9b`
**Baseline release architecture:** v1.3.0
**Purpose:** Correct the twenty-five confirmed or strongly supported defects identified in the post-implementation backend, GUI, and user-experience audit without reopening completed architecture or adding unrelated product features.

The audited SHA identifies where the findings were established. It is not a command to reset the repository. Every phase must start from the then-current protected `main`, read the complete current implementation, and determine whether earlier work has already changed any affected path. Where this plan and the current implementation differ because a prior phase has merged, preserve the completed phase and apply the remaining requirements to the new state.

---

## 1. How to use this plan

Execute the work one phase at a time. A phase is complete only after its implementation, regression tests, protected pull request, merge, deployment validation where applicable, and execution record are complete.

### Standard prompt for any phase

> Read `FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` in full. Start from the current protected `main` and implement **Phase N only**. Treat the existing v1.3.0 architecture, current source contracts, and tests as authoritative where this plan is silent. Do not begin a later phase, add unrelated features, change Funding Finder ranking, rebuild vectors, or create parallel architecture. Add regression coverage that would fail before the fix, run the phase gate, complete the normal protected PR workflow, merge only after the gate passes, update the execution record in the plan, report the final `main` SHA and evidence, then stop.

Replace `N` with `1`, `2`, `3`, or `4`.

### Mandatory execution rules

1. **Read before editing.** Inspect the current versions of every affected file and the nearest existing tests before selecting an implementation.
2. **One phase per PR series.** Do not opportunistically implement later-phase items. A genuinely inseparable prerequisite may be included only when documented in the PR and kept to the smallest possible change.
3. **Reuse repository patterns.** Extend the existing browser modules, Workers, D1 store, adapters, fixtures, workflows, and test suites. Do not create a second alert system, award API, institution registry, or UI framework.
4. **Prove each correction.** Every bug ID requires a regression test that fails against the pre-fix behavior or an equivalent fixture-level demonstration when a live external source cannot be deterministically reproduced.
5. **Do not hide defects.** Do not solve a failing test by suppressing an error, discarding valid records, weakening source validation, lowering a health threshold without evidence, or changing truthful UI language into vague success language.
6. **Preserve graceful degradation.** One failed award or opportunity source must not prevent healthy sources from returning useful results. Degraded state must remain visible and specific.
7. **Preserve privacy boundaries.** Browser-local saved items, notes, pursuit state, profiles, CV text, ORCID publication text, uploaded documents, AI chat, and provider keys must not be sent to the Alerts Worker or award services.
8. **Preserve source authority.** NSF, NIH, DOE, ROR, Grants.gov, and other official-source records remain authoritative. Do not fabricate missing values, contacts, totals, explanations, aliases, or completeness claims.
9. **No ranking or vector work.** Do not change Funding Finder opportunity ranking, matching thresholds, vector generation, model-space fingerprints, or the frozen evaluation baselines unless a selected phase explicitly requires the smallest compatibility correction. None currently does.
10. **No direct production-only patch.** Source, tests, migrations, deployment configuration, and operational documentation must remain reproducible from the repository.
11. **Backward compatibility matters.** Existing saved browser data, alert subscriptions, email links, shared URLs, deep links, D1 rows, and source caches must continue to work or have an explicit tested migration path.
12. **Stop after the phase.** Report evidence and stop rather than continuing into the next phase.

---

## 2. Product contracts that must remain unchanged

The following are invariants across all four phases:

- Funding Finder opportunity search, Strong/Potential matching, current ranking behavior, filters, saved items, Team Match, Funded Awards, Institutional Intelligence, and email alerts remain separate but interoperable product surfaces.
- Funded Awards continues to use normalized public NSF, NIH, and DOE records. It must not use the opportunity vector corpus as an award search substitute.
- Current-opportunity to historical-award deep links remain exact or explicitly controlled. Uncertain mappings must continue to be described as searches rather than exact equivalence.
- NSF, NIH, and DOE adapters remain isolated. An unsupported criterion or source outage must be represented per source.
- Institutional Intelligence remains grounded in returned public award records. Optional AI may translate a question into visible filters; it may not invent an institutional answer.
- Alert matching remains deterministic and based on the existing Strong-match and change-event contracts. No LLM is required for alert generation.
- Alert subscription responses must not reveal whether an email address already exists, is verified, is suppressed, or has an active alert.
- Email verification, manage links, unsubscribe behavior, retry, suppression, idempotency, sender identity, and HTML/plain-text parity must be preserved or improved.
- External links remain protocol-validated, user-controlled HTML remains escaped, and no secrets enter browser bundles, URLs, logs, exports, or Git history.
- All public UI remains keyboard operable and usable at 320 px and 390 px widths.
- The normal Python, browser-contract, frozen search-quality, real-browser, and accessibility gates remain authoritative.

---

## 3. Audit finding registry

| ID | Phase | Severity | Finding | Primary paths |
|---|---:|---|---|---|
| `FF-BUG-001` | 1 | High | Missing award amounts can render as `$0`; missing award years can enter summaries as year `0`. | `assets/funded-awards.js`, `assets/institutional-intelligence.js` |
| `FF-BUG-002` | 3 | High | **Complete in PR #60.** Institution-filtered NSF, NIH, and DOE paging now fills the normalized post-validation sequence within bounded upstream scans, with fair trusted-identity query allocation and truthful `has_more`, exhaustion, safety-bound, and raw-record diagnostics. | `assets/funded-awards-core.js`, award adapters |
| `FF-BUG-003` | 2 | High | Recreating an inactive saved-search alert can reuse stale qualification and evaluation baseline state. | `workers/alerts/src/store.js`, `index.js`, `evaluator.js` |
| `FF-BUG-004` | 3 | High | **Complete in PR #56.** Institutional Intelligence now has independent NSF/NIH/DOE Load more controls, source-specific page sizes, accumulated deduplicated results, failure-safe retry state, shared-URL restoration, dropdown drill-downs, and mobile/accessibility coverage. | `assets/institutional-intelligence*.js`, Funded Awards e2e/contracts |
| `FF-BUG-005` | 4 | High | The external-source refresh layer is repeatedly degraded and the recurring source-specific cause remains unresolved. | refresh workflow, source adapters/tools, issue `#30` |
| `FF-BUG-006` | 2 | High | A multi-subscription weekly digest uses the first subscription for unsubscribe semantics and can confirm a broader unsubscribe than occurred. | alert evaluator, email templates, unsubscribe routes |
| `FF-BUG-007` | 2 | Medium-High | Alerts `/health` can return HTTP 200 when outbound delivery is disabled or the provider is unconfigured. | `workers/alerts/src/index.js`, deployment gate |
| `FF-BUG-008` | 2 | Medium-High | Verification email delivery is synchronous, not retryable, and leaves unrecoverable pending state after transient failures. | alert index, provider, store/migrations |
| `FF-BUG-009` | 2 | Medium-High | A suppressed subscriber can be re-verified into an apparently active state while remaining excluded from evaluation and delivery. | alert store, verification/manage routes |
| `FF-BUG-010` | 4 | Medium-High | Alert rate limiting is non-atomic; award/ROR abuse controls are not represented in application code or repository-managed infrastructure. | alert store, award Worker, deployment config |
| `FF-BUG-011` | 1 | Medium | Saved-item actions can appear successful even when local storage rejected the write. | `assets/saved.js`, `assets/app.js` |
| `FF-BUG-012` | 3 | Medium | **Complete in PR #60.** Short acronyms and multiple exact ROR alias/acronym matches require explicit accessible selection; unique canonical names and unambiguous aliases may resolve automatically, with the PR #56 URL, keyboard, location, Escape, and fallback behavior preserved. | `assets/institutional-intelligence-core.js`, UI controller |
| `FF-BUG-013` | 3 | Medium | **Complete in PR #60.** Selected ROR IDs are validated server-side and cached with bounded TTL; curated source identities remain authoritative, while bounded defensible ROR-derived names reach source queries and post-validation without trusting client alias arrays or uncontrolled short acronyms. | `ror.js`, `institutions.js`, award Worker/client |
| `FF-BUG-014` | 1 | Medium | Investigator drill-down can appear to select a PI while the retained opportunity lookup silently controls the request. | `assets/funded-awards.js` |
| `FF-BUG-015` | 1 | Medium | Combined multi-source pagination labels imply one contiguous result range even though offset is applied separately to each source. | `assets/funded-awards.js` |
| `FF-BUG-016` | 1 | Medium | Several GUI failure states collapse unsupported, invalid, rate-limited, and unavailable outcomes into the same message. | funded-award UI, Institutional Intelligence, alert dialog |
| `FF-BUG-017` | 2 | Medium | Weekly digest selection can be monopolized by one subscriber and can generate excessively large single messages. | alert store, evaluator, email templates |
| `FF-BUG-018` | 4 | Low-Medium | Operational D1 rows have no visible bounded retention/cleanup policy. | alert migrations, store, scheduler |
| `FF-BUG-019` | 4 | Medium security hardening | Long-lived manage capability tokens are stored in plaintext because future emails reuse them. | alert schema, crypto, store, email link generation |
| `FF-BUG-020` | 4 | Low | Evaluation runs record the scheduled start time as completion time, eliminating useful duration evidence. | alert scheduler, store/schema |
| `FF-BUG-021` | 3 | High | **Complete in PR #60.** Source-published investigator names and provenance remain intact while conservative normalized identities drive accessible loaded-award counts and bounded source-appropriate variant retrieval with post-validation and conflict separation. | `assets/institutional-intelligence*.js`, award Worker/adapters |
| `FF-BUG-022` | 3 | High | **Complete in PR #60.** Institutional questions now produce deterministic or bounded narrative answers from the exact loaded public-award evidence, validate every model citation, disclose scope and source limitations, and require explicit refresh after Load more. | `assets/institutional-intelligence*.js`, browser-local AI provider |
| `FF-BUG-023` | Post-3 | High | Active award-year criteria were sent upstream but not enforced on the normalized result sequence, and later paging/drill-down actions could read edited-but-unsent form values. This could admit out-of-range records, hide later valid records, or make metrics describe a different request. | award adapters, Funded Awards and Institutional Intelligence controllers |
| `FF-BUG-024` | Post-3 | High | Investigator options exposed incomplete loaded-page counts, sorted primarily by count, retained source spelling instead of a stable conservative label, and could lose the selected native-option state after investigator results rerendered. | `assets/institutional-intelligence*.js` |
| `FF-BUG-025` | Post-3 | High | Flat program aggregation treated a DOE parent office and its child program area as two programs, lost hierarchy in drill-down presentation, and exposed loaded-page counts in native options. | `assets/institutional-intelligence*.js` |

A finding may be marked complete only after its acceptance criteria below are satisfied. Passing unrelated tests is not sufficient.

---

# Phase 1 - Front-end correctness and interaction friction

## Phase 1 objective

Correct visible false data, misleading interaction state, persistence feedback, pagination language, and recoverable error messaging without changing award-source retrieval, alert backend state, institution resolution, or operational infrastructure.

## Phase 1 in scope

- `FF-BUG-001`
- `FF-BUG-011`
- `FF-BUG-014`
- `FF-BUG-015`
- `FF-BUG-016`

## Phase 1 out of scope

- Do not change adapter pagination or institution matching; that belongs to Phase 3.
- Do not change alert database lifecycle, delivery queues, unsubscribe semantics, or health; that belongs to Phase 2.
- Do not change source refresh integrations or rate-limit infrastructure; that belongs to Phase 4.
- Do not redesign Funded Awards or Institutional Intelligence.

## `FF-BUG-001` - Missing numeric values must remain missing

### Current defect

The current formatting paths call `Number(value)` before distinguishing an absent source value. JavaScript converts `null` and the empty string to zero. A source value meaning “not listed” can therefore display as `$0`. A similar conversion allows a missing award year to enter a result-page year range as `0`.

### Required behavior

- `null`, `undefined`, an empty string, and whitespace-only text display as **Not listed** or the existing context-specific equivalent.
- A source value explicitly equal to numeric zero remains distinguishable from a missing value. Do not treat all zeroes as missing solely to mask the bug.
- Money formatting accepts only a present finite numeric value.
- Award-year aggregation accepts only a valid integer year in the repository-supported award range.
- No summary may display year `0`, `NaN`, or an invalid range.
- Funded Awards and Institutional Intelligence must use consistent presence validation even if they retain separate display helpers.

### Likely implementation paths

- `assets/funded-awards.js`
- `assets/institutional-intelligence.js`
- Existing funded-award and Institutional Intelligence contract/e2e tests

### Required regression coverage

Test at least:

- `null`, `undefined`, `""`, and whitespace amount values;
- an explicit numeric `0` amount;
- a normal positive amount;
- `null`/empty year mixed with valid years;
- a page where all years are missing.

### Acceptance criteria

- Missing amounts never render as `$0`.
- Missing years never render as `0` or affect a valid year range.
- Explicit source zero, if supplied, is represented consistently and is not confused with absence.

## `FF-BUG-011` - Browser persistence failures must not look successful

### Current defect

The saved-item store catches storage errors, but mutating methods can return the modified in-memory array after `localStorage` rejected the write. The GUI then renders a saved, removed, or updated state that disappears on refresh.

### Required behavior

- Every saved-item mutation must expose whether persistence succeeded.
- On persistence failure, the UI must retain or restore the last actually persisted state rather than presenting an uncommitted state as successful.
- The user receives a concise actionable message that the browser did not allow the change to be stored.
- Failure handling applies to save/unsave, remove, pursuit status, and note updates, not only the star button.
- Existing valid local data must not be erased after a failed write.
- Existing storage format and key remain backward compatible unless a migration is unavoidable and tested.

### Likely implementation paths

- `assets/saved.js`
- `assets/app.js`
- `tests/browser/saved-contract.test.mjs`
- Relevant real-browser saved-state tests

### Required regression coverage

Use a deterministic storage double that throws on `setItem` and verify:

- the returned state describes failure;
- the visible saved state does not flip incorrectly;
- existing saved entries survive;
- a normal writable storage path remains unchanged.

### Acceptance criteria

A user can never be shown “saved,” “removed,” or “updated” when the corresponding durable browser write failed.

## `FF-BUG-014` - Investigator drill-down must control the actual request

### Current defect

A PI summary button changes the visible query and search mode, but an existing selected opportunity lookup can continue to take precedence in `buildRequest`. The interface can therefore appear to filter by investigator while submitting the old opportunity-derived criteria.

### Required behavior

A click on an investigator summary button means:

- the selected current-opportunity lookup is cleared;
- the selected-opportunity panel and program-watch state are updated consistently;
- the PI becomes the active standalone criterion;
- current institution, agency, and year filters remain when valid;
- the shared URL removes the stale `opportunity` parameter and records the PI search state;
- browser Back/Forward restores the correct state.

Do not silently combine the PI with the old opportunity mapping unless a future explicit product control requests that combination.

### Likely implementation paths

- `assets/funded-awards.js`
- `assets/funded-awards-core.js` only if a small request-state helper is justified
- Funded Awards contract and navigation/e2e tests

### Required regression coverage

Start from an opportunity deep link, produce a PI summary, click the PI, and assert that the outgoing award request contains the PI criterion rather than the selected opportunity mapping.

### Acceptance criteria

Visible search mode, URL state, selected-opportunity UI, and submitted request criteria always agree.

## `FF-BUG-015` - Multi-source pagination language must reflect source-scoped offsets

### Current defect

The award API applies the same offset separately to each source, while the GUI presents one combined range such as “Results 11-40.” That wording implies a single contiguous ranked list that does not exist.

### Required behavior

- Do not display a combined contiguous ordinal range for a multi-source page.
- Display a truthful combined count plus source-scoped paging context, or display a range within each source section.
- Preserve the explicit “source-native order; no cross-source reranking” contract.
- Single-source searches may continue to show a normal contiguous range when correct.
- The label must remain understandable on mobile and to screen readers.

### Likely implementation paths

- `assets/funded-awards.js`
- Possibly `assets/funded-awards-core.js` for a pure label helper
- Funded Awards contract/e2e tests

### Required regression coverage

Test a three-source payload with a nonzero offset and unequal result counts. The UI must not claim a fictitious combined range.

### Acceptance criteria

No pagination label implies cross-source ranking or a combined contiguous source order.

## `FF-BUG-016` - Recoverable failures must be classified accurately

### Current defect

Several browser paths reduce distinct backend outcomes to “temporarily unavailable.” This obscures whether the user should change a filter, wait after rate limiting, retry a transient outage, or correct an invalid request.

### Required behavior

Use existing bounded server error codes and per-source status to distinguish at least:

- `unsupported`: the selected source does not support that criterion or combination;
- `unavailable`/timeout: retry later; healthy sources may still be shown;
- `rate_limited`: wait before retrying;
- `invalid_request`: correct the submitted state;
- malformed/invalid service response: service error, not user error.

Specific requirements:

- Funded Awards source status must say **does not support this filter combination** for `unsupported`, not **temporarily unavailable**.
- The alert dialog must parse the bounded JSON error code and distinguish rate limiting from delivery/service outage while preserving no-email-enumeration behavior.
- Institutional Intelligence must retain its source-specific status distinctions.
- Do not expose stack traces, provider bodies, email existence, suppression state, or secrets.

### Likely implementation paths

- `assets/funded-awards.js`
- `assets/institutional-intelligence.js`
- `assets/alerts.js`
- Existing browser contract/e2e tests

### Required regression coverage

Fixture each supported error class and assert the user-facing recovery instruction. Include partial-success multi-source payloads.

### Acceptance criteria

The user can tell whether to change input, wait, or retry, without receiving sensitive backend detail.

## Phase 1 gate

Before the PR is eligible to merge:

1. Add or update targeted browser contract tests for all five bug IDs.
2. Run syntax checks for every modified browser JavaScript file.
3. Run `pnpm test:contracts`.
4. Run the relevant Playwright product and accessibility tests; run the full `pnpm test:e2e` before merge.
5. Verify 320 px and 390 px layouts for the changed Funded Awards, Saved, alert-dialog, and Institutional Intelligence states.
6. Run the repository's normal protected `Tests` workflow.
7. Do not rebuild vectors or run exploratory ranking evaluations.

## Phase 1 completion evidence

Record in the execution table:

- PR number and merge SHA;
- tests added/changed;
- contract and e2e counts/results;
- mobile and keyboard checks;
- screenshots or trace references for the corrected missing-value and persistence-failure states;
- any remaining limitation explicitly deferred to Phase 3.

---

# Phase 2 - Alert lifecycle, delivery, and user-control correctness

## Phase 2 objective

Make alert creation, reactivation, verification delivery, suppression, digests, health, and unsubscribe behavior internally consistent and recoverable while preserving deterministic matching, privacy, idempotency, and no-email-enumeration contracts.

## Phase 2 in scope

- `FF-BUG-003`
- `FF-BUG-006`
- `FF-BUG-007`
- `FF-BUG-008`
- `FF-BUG-009`
- `FF-BUG-017`

## Phase 2 out of scope

- Atomic abuse-rate storage and manage-token-at-rest redesign belong to Phase 4.
- Institution and award pagination belong to Phase 3.
- Do not introduce accounts, a public alert dashboard, or an LLM dependency.

## `FF-BUG-003` - Recreated alerts need a new baseline

### Current defect

An existing inactive subscription with the same subscriber, type, and definition receives a new verification token, but old qualification rows and evaluation timestamps can remain. Because `baseline_complete` may already be true, the newly supplied saved-search baseline is not written.

### Required lifecycle semantics

#### Exact subscription is already active

- Do not reset its baseline or queue duplicate historical events.
- Preserve a generic response that does not reveal account state.
- Avoid unnecessary duplicate verification delivery unless the existing product explicitly uses a safe management-email flow. Any such flow must remain non-enumerating.

#### Exact subscription exists but is inactive, unverified, paused after unsubscribe, or expired

Reactivation must atomically establish a fresh subscription cycle:

- set `active = 0` until verification;
- clear or replace the prior verification state;
- set a new verification token and expiration;
- set `baseline_at` to the new creation time;
- clear `last_evaluated_at` and any state that would cause historical changes to be reprocessed;
- replace saved-search qualification rows with the newly supplied current Strong-match baseline;
- prevent old queued/failed unsent events from being delivered after reactivation;
- mark baseline complete only after its rows are durably written;
- preserve subscriber-level identity and suppression policy.

The state transition must be atomic or fail closed. A partially cleared baseline must not become verifiable.

### Likely implementation paths

- `workers/alerts/src/store.js`
- `workers/alerts/src/index.js`
- `workers/alerts/src/evaluator.js`
- D1 migration only if required
- `tests/browser/alerts-phase3-contract.test.mjs` or a successor alert contract suite

### Required regression coverage

- inactive saved-search alert recreated with a different current baseline;
- stale prior qualification rows removed;
- old queued event cannot send after reactivation;
- active duplicate does not reset its baseline;
- failed baseline write leaves the alert inactive and incomplete.

### Acceptance criteria

A recreated alert starts from the current baseline supplied during recreation and cannot inherit stale qualifying or queued state.

## `FF-BUG-006` - Digest unsubscribe semantics must be truthful

### Current defect

Weekly events are grouped by subscriber, but the digest footer and `List-Unsubscribe` header use the first event's subscription ID. A digest representing several alerts can therefore unsubscribe only one alert while confirming a broader Funding Finder unsubscribe.

### Required behavior

Adopt explicit, tested semantics:

- Immediate single-subscription alerts retain **unsubscribe from this alert** behavior.
- A multi-subscription weekly digest uses a subscriber-level **unsubscribe from all Funding Finder email alerts** capability, with equally explicit HTML, plain text, header, confirmation, and manage-page wording.
- The digest always includes **Manage all alerts**.
- A single-subscription digest may use either the subscription-specific path or the all-alert path, but its wording must match its actual effect.
- One-click unsubscribe remains standards-compatible and does not require an account.
- No confirmation page may say “unsubscribed from Funding Finder” after deactivating only one alert.

This may require a subscriber-scoped unsubscribe route. Reuse the existing secure subscriber capability; do not expose an email address in the URL.

### Required regression coverage

- digest with events from two subscriptions;
- one-click digest unsubscribe deactivates the documented scope;
- immediate alert unsubscribe affects only its subscription;
- manage page accurately reflects resulting state;
- HTML and plain text contain the same semantics.

### Acceptance criteria

Every unsubscribe link, header, and confirmation precisely matches the subscriptions it deactivates.

## `FF-BUG-007` - Alert health must report delivery readiness

### Current defect

The health endpoint can return HTTP 200 when the API and D1 are enabled but outbound email is disabled or the Resend provider lacks a key.

### Required behavior

- Return an overall healthy status only when the service can accept and deliver the alert workflow promised by production configuration.
- Report component states separately, including database readiness, provider selection, provider configuration, outbound-delivery enablement, and scheduler readiness where determinable.
- A deliberately storage-only local/test configuration may expose a distinct degraded/test state, but production deploy validation must not treat it as delivery-ready.
- Deployment workflows must validate the intended production-ready field, not merely HTTP status.
- Do not return secrets or provider credentials.

### Required regression coverage

Test all combinations of enabled/disabled API, D1 ready/unready, provider configured/unconfigured, and outbound enabled/disabled.

### Acceptance criteria

Production health cannot be green while a new verification or notification email would necessarily fail.

## `FF-BUG-008` - Verification delivery must be accepted, persisted, and retryable

### Current defect

The subscription is written before a synchronous provider call. A transient provider/network/quota failure leaves pending state without an automatic retry record. Successful verification provider IDs are not persisted in the normal delivery evidence path.

### Required behavior

- Creating a valid subscription durably accepts a verification-delivery job before returning success.
- Verification delivery is idempotent and retryable for transient network errors, 429 responses, and retryable provider failures.
- Permanent provider rejection is represented as terminal bounded state and does not retry forever.
- Provider message ID, attempt count, next-attempt time, and terminal outcome are persisted.
- The subscription endpoint returns a generic accepted response without revealing whether an email/subscription already existed.
- A transient provider outage cannot leave an untracked pending subscription.
- Verification expiration semantics account for queued delivery. A message must not arrive with a token already expired due solely to queue delay; regenerate or extend safely at dispatch if required.
- Global daily email limits continue to apply per actual provider message, not per polling attempt.
- Bounce/complaint/suppression webhook correlation includes verification messages where supported.

Use the existing notification/store/provider architecture or a small generalized outbound-message extension. Do not build a second independent mail service.

### Required regression coverage

- accepted job followed by network failure and successful retry;
- provider 429 retry;
- permanent provider rejection;
- duplicate subscription request does not create duplicate provider messages beyond defined semantics;
- provider message ID persisted;
- no expired-token delivery caused by delayed dispatch.

### Acceptance criteria

Every accepted verification email is either delivered with evidence, retryable with bounded state, or terminally failed with evidence. No accepted job disappears between D1 and Resend.

## `FF-BUG-009` - Suppressed recipients need an explicit recovery policy

### Current defect

Verification can mark a subscription active while `activeSubscriptions()` continues to exclude the subscriber because `suppressed_at` remains set. The user can see “active” without any future delivery.

### Required behavior

- Do not automatically clear complaint, bounce, or provider suppression merely because the same address resubscribes.
- A suppressed subscriber cannot transition to an apparently deliverable active subscription.
- The public subscription response remains generic and non-enumerating.
- A valid manage capability may show that delivery is suppressed and the broad reason category, without exposing provider internals.
- Define and test the supported recovery path. At minimum, the user may use a different address; any administrative or explicit re-confirmation path must be deliberate and auditable.
- Verification route and manage page must agree with delivery eligibility.

### Required regression coverage

- suppressed subscriber attempts to create and verify an alert;
- subscription is not falsely shown as deliverable;
- active-subscription evaluation excludes it consistently;
- a nonsuppressed new address follows the normal path.

### Acceptance criteria

No state or page says an alert is active and deliverable while subscriber suppression prevents all delivery.

## `FF-BUG-017` - Weekly digest batching must be fair and bounded

### Current defect

The scheduler selects up to 500 event rows and then groups them by subscriber. One subscriber with many events can consume the candidate window, delay others, and produce one excessively long message.

### Required behavior

- Select eligible digest recipients fairly before one subscriber's event volume can monopolize the run.
- Send at most one digest per subscriber in a dispatch run.
- Introduce an explicit, documented maximum number of events per digest based on bounded email-size behavior. Keep overflow queued for a later digest or summarize that more events remain.
- Do not mark overflow events sent.
- Preserve global daily provider-message limits, idempotency, claim leases, retry, and suppression.
- Keep HTML and plain text readable on mobile.
- A failed digest releases or retries all claimed events consistently; it must not partially mark a batch sent.

### Required regression coverage

- first subscriber has more events than the per-digest limit and a second subscriber also has events;
- both can be selected fairly within provider-message limits;
- overflow remains queued;
- retry and idempotency remain correct;
- rendered email stays within the tested size bound.

### Acceptance criteria

A high-volume subscriber cannot starve other recipients or create an unbounded digest.

## Phase 2 gate

Before merge:

1. Add D1 migrations with forward and rollback/compatibility notes where schema changes are required.
2. Expand alert store, handler, evaluator, provider, webhook, and email-template contract tests for all six bug IDs.
3. Test migration against a copy of the pre-phase schema containing active, inactive, unverified, suppressed, queued, failed, sending, and sent rows.
4. Run `pnpm test:contracts` and the full alert-specific contract suite.
5. Run `pnpm test:e2e`, including verification/manage/unsubscribe pages and mobile email-render fixtures where the repository supports them.
6. Run a bounded provider integration using the mock provider; perform one explicitly controlled live Resend validation only if the repository's deployment process already supports it. Do not create unintended user alerts.
7. Run the alerts deployment workflow and verify production health against the final merged SHA.
8. Verify no private browser data or provider key enters an alert request, database fixture, log, or email.

## Phase 2 completion evidence

Record:

- migration numbers and compatibility strategy;
- exact lifecycle state matrix tested;
- retry/idempotency and provider-message evidence;
- digest size/fairness evidence;
- HTML/plain-text unsubscribe wording examples;
- deployed Alerts Worker version and health response summary;
- PR and final `main` SHA.

---

# Phase 3 - Institution resolution, source pagination, and result completeness

## Phase 3 objective

Make institution-scoped award retrieval, institution identity, investigator identity, and institutional questions complete and evidence-grounded within explicit bounded source paging, while preserving source-native order, source isolation, ROR authority, public-award provenance, and truthful result-scope language.

## Phase 3 in scope

Completed post-Phase-1 hardening that this phase must preserve:

- `FF-BUG-004` - completed by PR #56 at merge SHA `0fbf076551eed1529304af8602270780bebe817e`.

Phase 3 implementation findings completed by PR #60 at merged `main` SHA `1cc0a2a397338e6fce7cac38a6f9b2875fa7add9`:

- `FF-BUG-002`
- `FF-BUG-012`
- `FF-BUG-013`
- `FF-BUG-021`
- `FF-BUG-022`

## Phase 3 out of scope

- Do not add semantic/vector award search.
- Do not claim complete historical coverage when an upstream source caps or truncates results.
- Do not remove local institution validation merely to fill pages.
- Do not weaken exact current-opportunity mappings.
- Do not add collaborator recommendations, investigator ranking, fit scoring, inferred contacts, or facts from model pretraining.
- Do not create another credential store or server-side AI proxy.

## `FF-BUG-002` - Institution-filtered paging must expose later valid records

### Current defect after PR #56

PR #56 replaced combined navigation with independent NSF/NIH/DOE Load more controls and made those controls follow source-specific `has_more` state. The remaining defect is below that UI: NSF and DOE can return raw source pages that are reduced by deterministic local institution validation, while adapter offsets and exhaustion are still derived from the raw sequence. Valid records on later upstream pages can therefore remain absent from the normalized page or receive an incorrect `has_more = false` response.

### Required adapter/API behavior

- Source-native query narrowing remains in place.
- Local deterministic institution validation remains in place.
- For institution-filtered searches, each adapter must continue through bounded upstream pages until it can fill the requested normalized page, reaches true upstream exhaustion, or reaches a documented safety bound.
- Apply the public `offset` to the normalized, post-validation result sequence, not blindly to raw upstream rows.
- `has_more` must describe whether another normalized result page is available or reasonably known to be available.
- Do not report an upstream raw total as an exact normalized institution-match total. Use `null`, a distinct raw-total field, or explicit metadata when exact normalized total is unknown.
- `raw_record_count` and source-health evidence remain available for diagnosis.
- A local validation rejection must not silently count as a returned normalized record.

NIH already performs grouped upstream iteration and local filtering; inspect and preserve or correct it based on the same normalized-page contract rather than rewriting it without evidence.

### Required browser behavior

- Standalone Funded Awards and Institutional Intelligence must consume the same normalized, post-validation `offset` and `has_more` contract.
- Preserve PR #56's independent source-specific Load more controls, accumulated/deduplicated records, submitted-request state, shared-URL restoration, retained records after later-page failure, and explicit retry behavior.
- An empty normalized page must truthfully reflect source exhaustion or the documented safety bound and must not create an infinite Load more loop.

### Likely implementation paths

- `assets/funded-awards-core.js`
- `workers/award-api/src/adapters/nsf.js`
- `workers/award-api/src/adapters/doe.js`
- Inspect `nih.js`
- `workers/award-api/src/index.js`
- Award API and Funded Awards contract/e2e tests

### Required regression coverage

Use deterministic fixtures where:

- page 1 contains source-name false positives rejected locally;
- valid matches occur on page 2 or later;
- requested normalized page is filled when sufficient valid records exist;
- source exhaustion returns a short page with `has_more = false`;
- upstream raw total differs from normalized total.

### Acceptance criteria

A user can reach every valid result within the product's documented source bound even when local validation removes earlier raw rows.

## `FF-BUG-004` - Institutional Intelligence independent source paging

### Completion status

Completed by [PR #56](https://github.com/mporosoff/grants-scraper/pull/56), merged as `0fbf076551eed1529304af8602270780bebe817e`. Phase 3 must preserve this behavior while correcting the lower-level normalized paging and identity contracts.

### Pre-PR-#56 defect

Institutional Intelligence always requests offset zero. When DOE is among the selected sources, the common request limit is capped at DOE's ten-result limit, reducing NSF and NIH to ten as well. Aggregates therefore summarize a small first-page sample with no way to load additional source records.

### Completed behavior that must remain unchanged

- DOE's per-request cap must not reduce the NSF or NIH page size.
- Maintain independent source paging state because sources have different limits, totals, and `has_more` values.
- Provide independent bounded NSF, NIH, and DOE **Load more** controls with source-specific page sizes.
- Aggregates update over all records loaded in the current session and deduplicate by `source + award_id`.
- Scope text must state how many normalized records are loaded and which sources still have additional results.
- Source-specific errors do not discard records already loaded from healthy sources.
- Shared URL state restores the selected institution and filters. It need not encode an unbounded loaded-record cache, but navigation behavior must be deterministic and documented.
- Investigator and program drill-down operate on the actually loaded data and submit visible structured filters.
- No loop may retrieve an unlimited institution history automatically. Paging remains user-driven or subject to a documented strict bound.
- The exact submitted request, not unsent form edits, controls each later page; shared URLs and Back/Forward restore the submitted first-page state.
- A later-page failure retains already loaded records and offers a source-specific retry of the same request/offset.
- Investigator and program summaries remain accessible native dropdowns with explicit currently-loaded counts on desktop and at 320 px/390 px.

### Implementation options

Prefer the smallest architecture-compatible option. Acceptable approaches include:

- separate award API requests per source with source-appropriate limits and offsets; or
- a backward-compatible award API extension carrying per-source pagination.

Do not force unrelated Funded Awards callers into a new architecture without necessity.

### Required regression coverage

- all-agency initial search returns source-appropriate NSF, NIH, and DOE counts;
- DOE presence does not cap NSF/NIH at ten;
- loading more from one source preserves other source records and aggregates;
- source failure during a later page preserves previously loaded results;
- Back/Forward and shared URL state remain coherent;
- 320 px and 390 px controls remain usable.

### Acceptance criteria

Institutional Intelligence is no longer a fixed first-page sampler and never implies that a loaded subset is a complete institutional history.

### Completion evidence

- PR #56 added independent source paging, source-appropriate NSF/NIH/DOE limits, accumulation/deduplication, retry-safe partial failure, submitted-request and history restoration, dropdown drill-downs, and mobile/accessibility coverage.
- Its exact merged SHA passed 298/298 browser contracts, 773/773 Python validations, the 37-query and 50-case frozen gates, 22/22 no-drift artifacts, and 47/47 Playwright tests.
- Production Pages and Award Worker deployment run `32909055943` passed health, ROR, exact NSF/NIH/DOE smokes, and protected-main checks; Worker version `7faebbc9-08e4-4ad5-816a-cbed80d7c4b7`, rollback `a3735dbe-0eab-4035-92bd-f66b8e2f2f5c`.

## `FF-BUG-012` - Ambiguous institution acronyms require explicit selection

### Current defect after PR #56

PR #56 preserved the accessible ROR listbox, visible location, keyboard navigation, Escape behavior, shared URLs, and registry-unavailable fallback. Its selection helper can still treat the first exact acronym candidate as resolved. Short acronyms or multiple exact alias/acronym candidates may therefore resolve silently to the wrong institution.

### Required behavior

- A unique exact canonical-name match may auto-resolve.
- A unique exact alias match may auto-resolve when unambiguous.
- A short acronym or any query with multiple exact acronym/alias candidates requires the user to choose a visible ROR option.
- Do not use ranking score alone as permission to auto-select among multiple exact candidates.
- Keyboard selection, active-descendant state, Escape behavior, and screen-reader announcements remain correct.
- Typed complete source names remain available when ROR is unavailable, with the existing explicit fallback language.

### Required regression coverage

Use synthetic ROR candidates for ambiguous acronyms so tests do not depend on live registry ranking. Include unique canonical, unique alias, multiple acronym, keyboard selection, and registry-unavailable fallback cases.

### Acceptance criteria

No ambiguous institution acronym is silently converted into a canonical institution identity.

## `FF-BUG-013` - Preserve validated ROR identity through award retrieval

### Current defect after PR #56

PR #56 preserves the selected institution's canonical browser identity, visible location, shared URL, and submitted search state. The Worker still creates a generic identity from the submitted canonical name unless the institution is in the small curated source-identity configuration. Validated ROR aliases/acronyms and source-listed medical-center or legal grantee names can therefore be lost before source-specific querying and post-validation.

### Required behavior

- Treat the ROR ID as the canonical external identity when selected.
- Validate and resolve ROR information server-side or through a trusted cached registry response. Do not trust arbitrary client-supplied alias arrays.
- Preserve validated canonical name, aliases, acronyms, organization status/type/location as needed for deterministic matching.
- Use curated source identities and identifiers (UEI, NIH IPF, source-specific names) as authoritative overrides where available.
- For uncurated institutions, use safe ROR-derived names to improve source queries and post-filtering.
- Do not use very short acronyms as broad source queries without additional identity evidence.
- Cache ROR resolution with bounded TTL and source-version evidence.
- Keep source-specific normalization deterministic and explainable.
- Do not claim that ROR alone guarantees a complete NSF/NIH/DOE legal-grantee crosswalk.

### Likely implementation paths

- `workers/award-api/src/ror.js`
- `workers/award-api/src/institutions.js`
- `workers/award-api/src/index.js`
- `config/award_institutions.json`
- Institutional Intelligence client state only as needed

### Required regression coverage

- curated University of Rochester identity and medical-center alias;
- an uncurated synthetic ROR identity with aliases;
- ROR ID/name mismatch rejected;
- short acronym not used as uncontrolled source query;
- cache hit/miss behavior;
- source post-filter matches an approved alias while rejecting an unrelated similar name.

### Acceptance criteria

A selected ROR identity remains meaningful at the Worker and source-adapter layers rather than degrading to one display string.

## `FF-BUG-021` - Cross-source investigator identity must be conservative and complete

### Current defect

Institutional Intelligence groups and drills into investigators using source-published display strings. Case, punctuation, order, honorific, suffix, and middle-name variants can fragment one supported person into several dropdown entries. Selecting one entry can then send that single raw spelling to every agency, producing inconsistent or unrelated drill-down results.

### Required identity model

Separate every source-published investigator name from the normalized investigator identity used for grouping and retrieval. Preserve every original name and its source, award, and stable identifier/email provenance.

Normalize for deterministic comparison across:

- case and whitespace;
- punctuation around initials;
- `First Middle Last` and `Last, First Middle` order;
- common honorifics and suffixes;
- full middle names versus initials;
- apostrophes and hyphenated family names.

Group only with this evidence order:

1. Stable source person identifier.
2. Identical direct source-published email.
3. Exact normalized complete name at the same resolved institution.
4. Same first and family names where one record omits the middle name/initial, only when the institution matches and there is no conflicting identifier, email, or nonempty middle initial/name.

Never merge conflicting middle initials solely because first and family names match. Never use fuzzy similarity, research topics, an LLM, investigator ranking, or inferred identity evidence.

### Required dropdown and retrieval behavior

- A safe group appears once in the investigator dropdown and uses the most complete supported source name as its label.
- Original source variants and provenance are exposed accessibly.
- Counts explicitly describe currently loaded, deduplicated awards in the group.
- Selecting a group uses its normalized identity rather than blindly submitting one display string to every agency.
- Construct a bounded set of source-appropriate name variants for NSF, NIH, and DOE, union responses, deduplicate by `source + award_id`, and post-validate returned investigators against the selected identity.
- Preserve source isolation, normalized pagination, current institution/year/agency filters, submitted-request state, shared URLs, and Back/Forward behavior.
- A click must not replace a displayed one-project group with unrelated common-name records.

### Required regression coverage

The deterministic Marc fixture must prove that two NSF awards published under `Marc Porosoff` and one DOE award published under `Marc D Porosoff` form one safe group and return all three awards when selected.

Also cover:

- `Marc D. Porosoff`, `Porosoff, Marc D`, and `Dr. Marc D. Porosoff`;
- a full middle name versus its initial;
- conflicting middle initials;
- conflicting direct emails or stable identifiers;
- common first/family names at one and different institutions;
- apostrophes, hyphens, honorifics, and common suffixes;
- normalized paging during source-variant retrieval;
- shared URLs and Back/Forward restoration;
- accessible variant disclosure and truthful loaded-award counts.

### Acceptance criteria

Supported cross-source variants form one conservative investigator identity and complete bounded drill-down, while conflicting or weakly evidenced common names remain separate.

## `FF-BUG-022` - Institutional questions must answer from validated award evidence

### Current defect

“Ask about this institution” currently makes one browser-local provider call that translates the question into visible filters, then runs the structured award search. It does not provide a direct answer, supporting award citations, limitations, or an explicit evidence scope.

### Required evidence pipeline

1. The browser-local LLM translates the original question into visible structured filters plus a bounded answer intent.
2. The existing Award Worker retrieves authoritative NSF, NIH, and DOE records under the normal source and identity contracts.
3. Deterministic browser code answers counts, investigators, programs, years, and award lists whenever possible.
4. A second bounded browser-local LLM call may synthesize only returned titles and bounded abstract excerpts when narrative interpretation is useful.
5. The result displays the original question, transparent filters, direct answer, supporting award evidence, limitations, and the complete loaded award cards.

Every material model-generated claim must cite evidence IDs from the exact returned award set. Reject unknown IDs and fall back to the deterministic summary. Never render model HTML, unsupported factual claims, or facts from model pretraining.

### Evidence and result-scope contract

- Bound the evidence pack by record count, allowed public fields, per-record abstract length, and total serialized payload.
- Send only public award fields needed for the question.
- Disclose the number of normalized awards loaded, sources searched, unavailable/unsupported sources, additional pages, and whether the evidence set was bounded or truncated.
- Never imply complete institutional history while any source reports more pages or while the evidence pack is truncated.
- Loading more records retains the existing answer and does not automatically make another paid provider call.
- Provide an explicit **Update answer using loaded records** control when the loaded evidence changes.
- Structured search and deterministic summaries remain usable without a provider key.

### Browser-local provider and privacy contract

Reuse the existing Funding Finder browser-local provider, model, and credential store. Do not create another credential store, Worker-side AI proxy, or server-held provider key.

Update the disclosure so an explicit institutional AI question may send only:

- the original question;
- the selected public institution identity;
- the visible structured filters and bounded answer intent;
- a bounded set of returned public award identifiers, titles, program/year/investigator fields, and abstract excerpts needed for the answer.

It must never send profiles, CVs, ORCID publication text, uploaded documents, saved notes, pursuit state, alert data, unrelated chat, or provider keys.

### Required deterministic answer coverage

Use fixtures and mock-provider responses for:

- “Who has DOE BES awards?”;
- “Which programs funded catalysis?”;
- project counts and award years;
- narrative synthesis from returned titles/abstract excerpts;
- valid evidence citations and fabricated/unknown evidence IDs;
- partial source failures and additional pages remaining;
- explicit answer refresh after Load more and no automatic second provider call;
- malformed, rejected, or failed provider responses;
- no-key structured search and deterministic answers;
- privacy payload field/length boundaries;
- HTML escaping, keyboard operation, live-region announcements, and 320 px/390 px layouts.

### Acceptance criteria

An institutional question produces a transparent answer supported only by validated loaded public awards, degrades to deterministic evidence when AI fails or is absent, and never hides source or paging limitations.

## Phase 3 gate

Before merge:

1. Add adapter fixtures proving sparse post-validation pagination, normalized offsets, truthful `has_more`, source exhaustion, safety-bound behavior, and retained raw diagnostics across multiple upstream pages.
2. Expand `award-api-contract`, Funded Awards, and Institutional Intelligence contracts for ambiguous ROR selection, server-side identity resolution/cache, curated identifiers, trusted aliases, rejected mismatches, and registry fallback.
3. Add deterministic investigator fixtures for every `FF-BUG-021` name/identifier/email conflict case, including the three-award Marc example, source-variant paging, shared URLs, and Back/Forward behavior.
4. Add deterministic institutional-question and mock-provider fixtures for counts, investigators, programs, years, narrative synthesis, evidence validation/rejection, source limitations, explicit refresh, no automatic second call, no-key use, failures, escaping, and privacy payload bounds.
5. Run syntax checks for every modified browser and Worker JavaScript file, `pnpm test:contracts`, and the reconciled Phase 3 targeted suites during iteration.
6. Run bounded live NSF, NIH, DOE, ROR, University of Rochester, and Marc Porosoff checks against non-sensitive public queries. Record source URLs, retrieval time, normalized/raw counts, paging bounds, and upstream caps; live responses supplement but never replace deterministic fixtures.
7. Run `pnpm test:e2e`, including desktop, 390 px, and 320 px Institutional Intelligence, keyboard-only ROR selection, ambiguous selection, Load more/retry, investigator/program drill-down, evidence answers, answer refresh, shared URL, and Back/Forward state.
8. Run `python -m tools.run_refresh_validation` and `bash tools/verify_no_drift.sh`.
9. Run the existing frozen query and P9 scoring checks without rebuilding vectors.
10. Verify no profile, CV, ORCID publication text, uploaded document, saved note, pursuit state, alert data, unrelated chat, or provider key enters an award request or institutional-question provider payload.
11. Complete the normal protected PR and exact-final-commit review workflow. Deploy the Award API through its existing workflow; verify health, CORS, bounded NSF/NIH/DOE/ROR smokes, Pages equality, and rollback evidence against the exact merged SHA.

## Phase 3 completion evidence

Record:

- normalized pagination contract and safety bounds;
- source-specific page sizes and loaded-scope wording;
- fixture evidence for later-page valid records;
- ambiguous acronym behavior;
- ROR cache/identity behavior;
- investigator normalization/grouping evidence, conflict behavior, source-variant retrieval bounds, and the three-award Marc result;
- deterministic and narrative institutional answer contracts, evidence-ID enforcement, payload bounds, explicit refresh behavior, and privacy disclosure;
- deployed Award Worker version;
- PR and final `main` SHA;
- known upstream source caps stated explicitly.

---

# Phase 4 - Operational, security, and production hardening

## Phase 4 objective

Resolve the recurring external-source degradation and harden abuse control, capability-token storage, operational retention, and run evidence. Then validate the complete integrated production system against the final protected `main`.

## Phase 4 in scope

- `FF-BUG-005`
- `FF-BUG-010`
- `FF-BUG-018`
- `FF-BUG-019`
- `FF-BUG-020`
- Final cross-product validation and release evidence

## Phase 4 out of scope

- No new opportunity or award sources unless the exact recurring source defect requires a compatibility update to an already-supported source.
- No semantic/vector award search.
- No account system.
- No broad rewrite of Workers, D1, or the refresh pipeline.

## `FF-BUG-005` - Resolve recurring external-source degradation

### Current defect

Automated issue `#30` repeatedly reports degradation of the external-source refresh layer while the workflow retains last-known-good or fail-closed data. The audit output did not identify the exact source and failure mechanism, so the executor must inspect current workflow evidence rather than guess.

### Required investigation

- Inspect the latest issue comments and the associated refresh workflow run summaries/logs.
- Identify every recurring affected source, not merely the aggregate “external sources” layer.
- Classify each failure as request/network, source response change, parser/extractor drift, health-bound violation, document evidence/classifier failure, post-merge validation, or deployment/publication coordination.
- Determine the last healthy refresh and age of retained last-known-good data.
- Reproduce deterministically with a stored fixture where possible and use a bounded live request only to confirm current upstream behavior.

### Required fix behavior

- Correct the actual source adapter/parser/health logic at the smallest responsible layer.
- Preserve last-known-good and fail-closed publication contracts.
- Do not simply suppress the alert, broaden parsing until garbage passes, or lower a health threshold without evidence.
- Source summary evidence must name the degraded source, failure class, last successful refresh, retained-data age, and publication behavior.
- Automated recovery must close the issue only after a complete healthy run under the existing recovery rules.
- Add regression fixtures for the observed upstream shape or failure.

### Acceptance criteria

- The exact recurring failure is identified and fixed or, if upstream is genuinely unavailable, the source-specific limitation and bounded fallback are documented with truthful health state.
- At least one complete scheduled-equivalent refresh gate passes with the repaired source layer.
- Issue `#30` is not manually closed merely to make the repository look healthy.

## `FF-BUG-010` - Abuse limits must be atomic and deployable

### Alert endpoint requirements

- Replace the `SELECT` then `UPDATE` rate-limit sequence with an atomic D1 operation or transaction whose success is determined by the database change result.
- Concurrent requests at the limit must not all pass.
- Window rollover remains correct.
- Raw IP addresses are not persisted. Continue using bounded derived client keys.
- Cleanup of expired rate-limit rows is included under `FF-BUG-018`.

### Award and ROR endpoint requirements

The public award and institution-search endpoints need an explicit abuse-control contract represented either in repository code or repository-managed Cloudflare configuration:

- preserve anonymous no-account use;
- protect upstream NSF, NIH, DOE, and ROR services from unbounded caller amplification;
- allow normal browser paging and autocomplete bursts;
- retain cache effectiveness;
- return bounded `429` responses with retry guidance;
- do not persist raw IPs or expose source credentials;
- document whether enforcement uses a Worker binding, D1/KV, or Cloudflare rate-limiting/WAF rule and include deployment evidence.

Do not use per-isolate in-memory counters as the sole production control.

### Required regression coverage

- concurrent requests at `limit - 1`, `limit`, and `limit + 1`;
- window expiration;
- independent action/source buckets;
- normal autocomplete and pagination not blocked;
- 429 browser messaging from Phase 1 remains correct.

### Acceptance criteria

Rate limits are race-safe, operationally deployed, privacy-bounded, and visible in tests/documentation.

## `FF-BUG-018` - Add bounded D1 retention and cleanup

### Current defect

Rate-limit rows, provider events, notification history, and evaluation runs can accumulate indefinitely.

### Required behavior

- Define explicit retention classes for expired rate limits, evaluation runs, provider webhook evidence, sent/suppressed notification events, and terminal verification-delivery records.
- Never delete active subscriptions, subscriber management state, queued/sending/retryable events, or evidence still required for idempotency and webhook correlation.
- Retention periods must be documented and justified by operational/idempotency needs rather than selected only to make tests pass.
- Cleanup runs in bounded batches, uses indexed predicates, and cannot monopolize the scheduled alert run.
- Cleanup failure does not prevent evaluation/delivery, but is recorded in health/run evidence.
- Where privacy permits, consider anonymization rather than retaining unnecessary long-lived operational payloads.

### Required regression coverage

- eligible old rows removed;
- recent and active rows retained;
- bounded batch continuation;
- cleanup failure recorded without breaking delivery;
- foreign-key behavior remains correct.

### Acceptance criteria

D1 growth is bounded by a documented, tested retention policy without weakening retry, idempotency, suppression, or audit evidence.

## `FF-BUG-019` - Remove plaintext long-lived manage capabilities at rest

### Current constraint

The Worker currently reuses the manage capability in future emails, so simply hashing the stored token would prevent link generation. The fix must redesign capability generation rather than deleting required functionality.

### Required security design

Use a versioned server-secret-backed capability design, preferably a stateless HMAC-signed token scoped to a subscriber identity and purpose:

- no long-lived raw manage token stored in D1 for new or migrated subscribers;
- token includes or resolves a non-sensitive subscriber identifier plus version/purpose;
- Worker verifies the signature in constant-time using a secret stored only in Worker configuration;
- token remains unguessable and cannot be forged by changing the subscriber ID or purpose;
- manage and unsubscribe scopes are explicit;
- tokens are never logged;
- email links can be regenerated for future messages without plaintext database storage;
- key rotation and token versioning are documented;
- existing production links receive a tested compatibility window or migration path.

A repository-visible encryption key, reversible obfuscation, or hashing that still requires storing the raw token elsewhere is not acceptable.

### Migration requirements

- Add a versioned schema/config path that accepts legacy tokens only for the documented transition period.
- New emails after migration use the new capability format.
- Legacy-token use may lazily migrate the subscriber or redirect to a new capability, but must not reveal account state.
- Do not invalidate all existing manage links without an explicit operational decision and user-safe recovery path.

### Required regression coverage

- valid manage and unsubscribe capabilities;
- tampered subscriber ID, purpose, version, and signature rejected;
- expired/retired key version behavior if expiration is used;
- legacy link compatibility;
- new D1 rows contain no reusable raw capability;
- no token in logs or error payloads.

### Acceptance criteria

A D1 read-only disclosure no longer grants direct use of new manage capabilities, while legitimate future email links and legacy transition continue to work.

## `FF-BUG-020` - Record actual run completion and duration

### Current defect

The scheduled handler derives `completedAt` from the original scheduled time after work finishes, so start and completion can be identical.

### Required behavior

- Capture actual start and actual completion using an injectable clock suitable for deterministic tests.
- Record `duration_ms` or derive an accurate duration from distinct timestamps.
- Preserve the scheduled trigger time separately if operationally useful.
- Failed runs also record actual completion and duration.
- Duration data appears in bounded operational evidence without logging subscription content.

### Required regression coverage

Inject a clock that advances during evaluation/delivery and verify start, completion, duration, success, and failure paths.

### Acceptance criteria

Evaluation-run records provide accurate, testable duration evidence.

## Phase 4 integrated production validation

After all five Phase 4 bug IDs pass their targeted tests, validate the entire product rather than only the changed modules.

### Required complete gates

Run the current equivalents of:

- `python -m tools.run_refresh_validation`
- `bash tools/verify_no_drift.sh`
- syntax checks for modified JavaScript/Worker files
- `pnpm test:contracts`
- `node tools/query_baseline.mjs --check`
- `node tools/p9_scoring_probe.mjs --check`
- `pnpm test:e2e`

Do not rebuild production vectors or rerun unrelated exploratory model evaluations.

### Required real-browser workflows

Verify at desktop, 390 px, and 320 px where applicable:

- Funding Finder search, filters, Strong/Potential presentation, save/unsave, pursuit state, notes, and recoverable storage failure;
- Team Match;
- Funded Awards for NSF, NIH, and DOE, including partial source failure and independent pagination;
- current opportunity to historical-award deep links;
- Institutional Intelligence ROR selection, ambiguous acronym handling, source paging, filters, investigator/program drill-down, shared URL, Back/Forward, no-key operation, and optional shared AI-key configuration;
- opportunity, program, and saved-search alert setup;
- verification retry, verify, manage, pause/resume, cadence change, single-alert unsubscribe, digest all-alert unsubscribe, suppression, retry, idempotency, and bounded digest overflow;
- keyboard focus, dialogs, live regions, accessible names, and source/error status announcements.

### Required production security/privacy checks

- no Resend, HMAC, AI-provider, or other secret in browser assets, repository files, URLs, exports, workflow output, or client-visible errors;
- new manage capabilities are unforgeable and not stored raw;
- rate limits are deployed and race-safe;
- no email enumeration;
- no profile, CV, ORCID publication text, uploaded document, private note, pursuit state, or AI chat traffic to alert services;
- award-source isolation remains correct;
- ROR identity does not enable parameter injection or uncontrolled broad querying;
- HTML/plain-text email links are safe, encoded, and semantically consistent;
- source degradation remains visible rather than silently hidden.

### Required performance/operational evidence

Measure practical production behavior without inventing arbitrary service-level objectives:

- NSF, NIH, DOE, and ROR request time and cache hit/miss behavior;
- normalized multi-page institution retrieval bounds;
- Institutional Intelligence initial and subsequent page behavior;
- alert evaluation, cleanup, digest batching, and delivery durations;
- D1 query/batch counts where observable;
- refresh duration and source-health summary;
- Worker health, version, and rollback identifiers.

### Protected release workflow

- Use the normal protected pull request process; no direct push to `main`.
- Merge only after required checks pass on the exact final commit.
- Deploy affected Workers through their existing workflows.
- Verify GitHub Pages and Worker compatibility against the final merged SHA.
- Record rollback procedures and prior Worker versions before production deployment.
- Report final `main` SHA, deployed Worker versions, workflow runs, source health, test evidence, known limitations, and final release decision.

## Phase 4 completion evidence

Record:

- root cause and repair for each degraded external source;
- issue `#30` status and healthy-run evidence;
- rate-limit architecture and concurrency proof;
- retention policy and cleanup metrics;
- capability-token version/migration and secret-rotation procedure;
- actual evaluation durations;
- complete test counts and production smoke results;
- deployed Worker versions, final `main` SHA, rollback identifiers, and release decision.

---

## Post-Phase-3 Funded Awards / Institutional Intelligence correctness addendum

This bounded addendum preserves completed Phase 3 and corrects three defects found afterward. It does not reopen `FF-BUG-002`, `FF-BUG-004`, `FF-BUG-012`, `FF-BUG-013`, `FF-BUG-021`, or `FF-BUG-022`, and it does not begin Phase 4.

### `FF-BUG-023` - Year filters and summary-metric integrity

**Reproduced causes:** NSF and DOE used source date criteria but accepted normalized records without an inclusive local year check; their non-institution paths applied raw offsets before any such check. NIH grouped all returned support rows, so unrelated fiscal years and amounts could enter a filtered project summary, and a one-sided year criterion became a single exact fiscal year upstream. NIH request construction also used the UTC calendar year for an open-ended upper bound and previously clipped explicit future ends, which could omit the next federal fiscal year after the October 1 rollover. Institutional Intelligence investigator/program drill-downs and standalone Funded Awards Previous/Next plus investigator handoff could read the current form after a submitted search, allowing unsent edits to replace its years and other filters.

**Corrected contract and acceptance:** NSF and DOE must accept an active-year record only when its normalized award year is within the inclusive requested range. NIH must qualify a core project only through returned in-range annual-support rows, and its displayed year, annual support, and summed amount must use those rows only. NIH derives the open-ended upper bound from one immutable UTC `asOf` value captured by the Worker before source-cache lookup: through September 30 it uses the UTC calendar year, and beginning October 1 it uses the next federal fiscal year. The same value controls the NIH request body and, only for a start-only NIH range, a derived `nih_fiscal_year_ceiling` cache discriminator. The raw timestamp is not keyed, so entries remain reusable throughout one federal fiscal year; explicit/end-only/inactive NIH ranges and NSF/DOE remain unpartitioned, obsolete entries expire through the unchanged bounded TTL, and failed source responses remain uncached. Explicit NIH start/end ranges remain exact even when future-dated, and a start later than the current federal fiscal year remains a one-year future request. Missing years are rejected while an active filter is present and counted in bounded source diagnostics. Year post-validation occurs before normalized offset and `has_more`; the existing upstream caps remain NSF 12 x 25, NIH 12 x 100, and DOE 10 pages with DOE normalized offset capped at 100. One-sided filters remain supported. A submitted-state snapshot controls source-specific Load more, retry, Previous/Next, investigator/program drill-down, question search, shared URL restoration, and Back/Forward until the user submits a new search. Metrics are calculated from the exact deduplicated cards currently displayed and use the labels `Projects loaded`, `Investigator identities in loaded results`, `Distinct programs in loaded results`, and `Loaded award years`; the visible scope states the active requested year range and retains paging/safety-bound limitations.

**Deterministic regression authority:** `tests/browser/post-phase3-awards-correctness-contract.test.mjs` covers inclusive and one-sided filters, the September 30/October 1 federal-fiscal-year boundary, future ranges, single-clock request plumbing, minimum/maximum bounds, missing-year diagnostics, out-of-range NSF/NIH/DOE rejection, later valid rows, and NIH support-row amounts. Worker-level cache contracts cover pre-rollover miss/hit, post-rollover miss/hit, distinct federal-fiscal-year identities with the existing TTL, one-clock key/body coherence, stable explicit/end-only/inactive NIH and NSF/DOE keys, and uncached failures. `tests/e2e/institutional-intelligence.spec.mjs` covers submitted years through Load more, investigator/program selection, evidence-grounded questions, URLs/history, metrics, native selected state, mobile widths, and accessible status. Existing Phase 3 sparse-page, partial-source, retry, Marc, URL, mobile, and accessibility cases remain part of the gate.

### `FF-BUG-024` - Investigator grouping, dropdown, selection, and sorting

**Reproduced cause:** The loaded awards were already fed through the conservative Phase 3 identity grouping, including the deterministic three-award Marc fixture. The discrepancy was presentation and state coherence: dropdown labels included the current loaded-page count, groups were sorted by that count, the most complete published spelling could retain inconsistent initial punctuation, and rerendering replaced the selected native option without restoring it. Drill-down request construction also read unsent form values.

**Corrected contract and acceptance:** Existing stable-identifier, direct-email, same-institution complete-name, bounded missing-middle, and conflict-separation rules remain unchanged. Safe labels use the most complete supported source name in canonical given/middle/family order with normalized initial punctuation, while every original source spelling and provenance remains in the accessible selected-investigator explanation. Options contain only the identity label and sort by normalized family, given, middle, then stable display name. Selection runs the existing bounded source variants, preserves the submitted institution/agency/year/topic/program/officer filters, post-validates identity, deduplicates `source + award_id`, restores the selected native option after rerender, and reports the matching awards currently loaded across available sources outside the option. URLs retain only the bounded identity label and flag, never variant arrays or contact data.

**Deterministic regression authority:** the mixed-source contract covers family-name ordering, honorifics, suffixes, apostrophes, hyphens, canonical middle-initial punctuation, Marc grouping, loaded-card counts, and conflict separation. Playwright proves one count-free `Marc D. Porosoff` option, two NSF plus one DOE result after selection, selected-state persistence, active-year retention, source variants in explanatory text, Load more/history behavior, native mobile picker usability, and zero serious or critical accessibility findings in the affected scans.

### `FF-BUG-025` - Hierarchical program aggregation

**Reproduced cause:** DOE aggregation emitted one descriptor for `Office of Basic Energy Sciences` and a second for `Catalysis Science`, so one award contributed two flat program labels. Native options also appended loaded project counts, and award details did not consistently present both hierarchy levels when a child existed.

**Corrected contract and acceptance:** every award contributes at most one most-specific leaf descriptor, namespaced by source and parent/leaf identity. A descriptor records source, parent office or organization, leaf program, role, source-native codes, and bounded query identity. Parent-plus-child records count the child once; parent-only records use the most specific parent as the fallback leaf; different children under one parent remain distinct; and similar text across agencies never merges. DOE presentation retains `Office of Basic Energy Sciences › Catalysis Science`, and program options use a source-prefixed hierarchy label with no project count. Drill-down uses the leaf query while preserving the submitted filters, and award cards retain parent, child, and source-code provenance.

**Deterministic regression authority:** the mixed-source aggregation fixture covers parent-only and parent-plus-child records, duplicate children, multiple children under one parent, similar NSF/DOE labels, exact deduplicated metrics, and loaded years. Playwright verifies count-free hierarchy options, active-year drill-down, visible parent/child award details, partial-source metrics, 320 px and 390 px containment, keyboard operation, and accessibility.

### Addendum release boundary

The implementation changes classified Award Worker inputs by adding shared year post-validation and incrementing the NSF, NIH, and DOE adapter versions. The protected Award release workflow must therefore deploy and verify the Award Worker after merge, retaining the prior version as rollback protection. Alerts Worker inputs, D1 migrations, opportunity catalog/metadata, vectors, search packages, ranking, Team Match, and lazy catalog loading are unchanged. Remaining limitations are the documented bounded source scans, incomplete upstream history beyond a reached cap, and upstream source dates/annual-support rows that cannot be accepted when their year is missing under an active filter.

The three addendum findings remain unchecked until their exact candidate passes protected review and CI, merges, and the classified Award Worker deployment plus Pages/live bounded closeout succeeds. Final PR/SHA/version/run identifiers belong in the task closeout rather than a self-referential candidate commit.

---

## 4. Cross-phase regression matrix

The phase owner must add the narrowest regression at the responsible layer and retain all earlier tests.

| Product path | Phase 1 | Phase 2 | Phase 3 | Phase 4 final |
|---|---:|---:|---:|---:|
| Funded Awards rendering and labels | Required | Preserve | Required | Full workflow |
| Saved browser state | Required | Preserve | Preserve | Full workflow |
| Award API/adapters | Preserve | Preserve | Required | Live/source health |
| Institutional Intelligence | UI messages only | Preserve | Required | Full workflow |
| Alert browser dialog | Error mapping | Required integration | Preserve | Full workflow |
| Alert D1 lifecycle | Preserve | Required | Preserve | Security/retention |
| Email templates and unsubscribe | Preserve wording compatibility | Required | Preserve | Full workflow/live bounded check |
| Refresh/external sources | Preserve | Preserve | Preserve | Required |
| Security/privacy | Verify client changes | Required | Verify identity data | Complete audit |
| Accessibility/mobile | Required | Required for alert pages/email fixtures | Required | Complete gate |

---

## 5. Required execution record

Update this table in the same PR that completes each phase. Do not mark a phase complete before merge and post-merge verification.

| Phase | Status | PR | Final `main` SHA | Tests and workflow evidence | Deployment evidence | Notes / known limitations |
|---|---|---|---|---|---|---|
| Phase 1 - Front-end correctness | Complete - 2026-08-25 | [Implementation PR #54](https://github.com/mporosoff/grants-scraper/pull/54); [execution-record PR #55](https://github.com/mporosoff/grants-scraper/pull/55) | `058262102435f240bac3ed0079ae251ef002d283` (implementation and deployment) | Local: 6-file syntax check; 24/24 targeted contracts; 297/297 full browser contracts; 773/773 Python validations; 37-query baseline; 50-case P9 scoring; 22-artifact no-drift; 45/45 full Playwright, plus 23/23 final-audit and 9/9 post-review affected-spec reruns. Protected: [reviewed PR Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32887538551) and [post-merge Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32888287988) passed. | [Pages](https://github.com/mporosoff/grants-scraper/actions/runs/32888286698) published exact SHA; [Award deployment](https://github.com/mporosoff/grants-scraper/actions/runs/32888287950) version `a3735dbe-0eab-4035-92bd-f66b8e2f2f5c`, rollback `b6b6e9d4-e6bf-4a9b-9611-529ea2ccd7a9`; [Alerts deployment](https://github.com/mporosoff/grants-scraper/actions/runs/32888288009) version `ff84d774-40df-43a0-bf54-c866e4f9a844`, rollback `e9346921-bbd3-4988-97cf-8937bdb742f1`; [coordinated search-package publication](https://github.com/mporosoff/grants-scraper/actions/runs/32888287924) version `4e894667-e72b-4cb1-aaa3-a40f4372ac23`, rollback `bb7661b5-d9f1-4df2-8395-384400de39f9`. All health, bounded smoke, and Pages equality gates passed. | Released. Live 390 px checks returned 10 NSF awards and 11 Funding Finder results without overflow or console errors. Phase 3 remains responsible for adapter pagination and institution matching/completeness. No vectors were rebuilt and no ranking/search behavior changed. |
| Post-Phase-1 Funded Awards / Institutional Intelligence hardening | Complete - 2026-08-25 | [PR #56](https://github.com/mporosoff/grants-scraper/pull/56) | `0fbf076551eed1529304af8602270780bebe817e` | 298/298 browser contracts; 773/773 Python validations; 37-query baseline; 50-case P9 gate; 22/22 no-drift artifacts; 47/47 Playwright tests. [Post-merge Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32909055964) passed. | [Pages](https://github.com/mporosoff/grants-scraper/actions/runs/32909053793) published the exact SHA. [Award deployment](https://github.com/mporosoff/grants-scraper/actions/runs/32909055943) version `7faebbc9-08e4-4ad5-816a-cbed80d7c4b7`, rollback `a3735dbe-0eab-4035-92bd-f66b8e2f2f5c`; health, ROR identity, NSF/NIH/DOE smokes, and protected-main stability passed. | `FF-BUG-004` complete. Preserve independent source Load more, source page sizes, accumulated/deduplicated records, failure retention/retry, submitted/shared state, dropdown drill-downs, mobile behavior, and accessibility. Remaining Phase 3 identity and normalized paging findings stay open. |
| Phase 2 - Alert lifecycle | Complete - 2026-08-25 | [Implementation PR #57](https://github.com/mporosoff/grants-scraper/pull/57); [execution-record PR #59](https://github.com/mporosoff/grants-scraper/pull/59) | `f30ef367d093a94541d9764830b9f6a486ca4da7` (implementation, migration, and deployment) | Local: 24/24 alert matcher tests and 47/47 alert lifecycle/browser contracts. Protected candidate: [PR Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32926393214) passed 776/776 Python, 329/329 browser contracts, the 37-query baseline, the 50-case P9 scoring gate, and 54/54 Playwright product/accessibility tests. [Post-merge Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32927016123) passed on the exact implementation SHA. | [Alerts deployment](https://github.com/mporosoff/grants-scraper/actions/runs/32927016026) applied `0003_phase2_alert_lifecycle.sql`, passed 57/57 release contracts, deployed version `d9a02762-b7c9-4fa8-bef3-9edd9e2d8c0e`, passed delivery-ready health, bounded Worker smoke/CORS, Pages equality, and protected-main stability gates; rollback version `87fdeece-ba4b-4cc8-b2f0-cc541ec7556b`. | Released. No ranking/search behavior or vectors changed. Production happy-path email and destructive unsubscribe were not exercised because the bounded deployment process intentionally creates no user alerts; deterministic provider/lifecycle contracts cover those transitions. Live invalid-capability checks verified truthful verification/manage/unsubscribe responses without creating or changing a user alert; verification/manage probes wrote only their bounded operational rate-limit counters. |
| Phase 3 - Institution completeness | Complete - 2026-08-26 | [Implementation PR #60](https://github.com/mporosoff/grants-scraper/pull/60); [execution-record PR #61](https://github.com/mporosoff/grants-scraper/pull/61) | `1cc0a2a397338e6fce7cac38a6f9b2875fa7add9` (implementation and deployment) | Local: 18/18 Phase 3/Award adapter contracts, 337/337 full browser contracts, and 29/29 Institutional Intelligence Playwright tests passed during final review iteration. Protected exact candidate: [PR Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32953173498) passed 776/776 Python validations, 337/337 browser contracts, the 37-query baseline, the 50-case P9 scoring gate, 22/22 no-drift artifacts, and 64/64 Playwright product/accessibility tests. [Post-merge Tests](https://github.com/mporosoff/grants-scraper/actions/runs/32953992318) passed on the exact implementation SHA. | [Pages](https://github.com/mporosoff/grants-scraper/actions/runs/32953990450) published the exact SHA. [Award deployment](https://github.com/mporosoff/grants-scraper/actions/runs/32953992332) passed release contracts, health, bounded ROR and NSF/NIH/DOE public-source smokes, Pages equality, and protected-main stability; deployed Worker version `c3f8c613-1ead-4ce3-be5a-b6ec1b4c0b75`, rollback `7faebbc9-08e4-4ad5-816a-cbed80d7c4b7`. A separate bounded live CORS check returned allowed-origin HTTP 200 with the exact Pages origin, HTTP 204 for the POST/content-type preflight with the expected method/header policy, and HTTP 403 with no allow-origin header for a disallowed origin. | Released. Normalized scan caps are NSF 12 x 25, NIH 12 x 100, and DOE 10 upstream pages with normalized offset capped at 100; NSF/DOE fairly allocate the shared cap across at most three trusted identity queries. Live checks at 2026-08-26T09:38Z returned two NSF Marc Porosoff awards, zero current DOE Marc D Porosoff results, and one loaded NIH Rochester award with more pages. These bounded observations do not claim complete history; ROR is not a guaranteed legal-grantee crosswalk, and deterministic fixtures remain the regression authority. No ranking/search behavior, alert lifecycle, or vectors changed. |
| Phase 4 - Operational hardening | Not started |  |  |  | All Worker versions and final release |  |

### Phase 1 regression and verification evidence

- `FF-BUG-001`: `tests/browser/phase1-front-end-hardening-contract.test.mjs` and the Playwright case `missing award values remain missing while explicit zero stays visible`; screenshot attachment `ff-bug-001-missing-values-390px.png` covers the corrected missing-value state.
- `FF-BUG-011`: `tests/browser/saved-contract.test.mjs`, the Phase 1 contract, and the Playwright case `saved-item write rejection restores durable UI state across every mutation`; screenshot attachment `ff-bug-011-storage-rejection-390px.png` covers the persistence-failure state.
- `FF-BUG-014`: the Phase 1 contract and the Playwright case `investigator drill-down replaces an exact opportunity request and round-trips through history` verify request criteria, selected-opportunity UI, and Back/Forward URL state.
- `FF-BUG-015`: the Phase 1 contract and the Playwright case `multi-source pagination reports independent source offsets on mobile` verify three unequal source counts at a nonzero offset without a fictitious combined range.
- `FF-BUG-016`: the Phase 1 contract plus the Playwright cases `partial award results distinguish unsupported and rate-limited sources` and `alert dialog gives bounded recovery guidance for each server error class` verify bounded input/wait/retry/service guidance without backend detail.
- Mobile and accessibility: 320 px and 390 px Playwright coverage exercises each changed product state; the affected accessibility scans reported zero serious or critical violations, including `funding-saved-storage-error-mobile` and `awards-results-mobile`. Keyboard coverage verifies the alert-dialog focus path and restores focus after dismissal; persistence failure restores focus to the durable saved control.
- Protected review: the two automated review findings were fixed on the PR head and their threads resolved before merge. Regression coverage now also restores a durable snapshot changed outside the tab before a rejected write and treats an unrecognized `403 origin_not_allowed` as a service failure rather than invalid user input.
- Post-merge live verification: at 390 px, `funded_awards.html?deploy=058262102435f240bac3ed0079ae251ef002d283` returned 10 live NSF catalysis projects with a truthful single-source `Results 1–10` label and no horizontal overflow. `match_explorer.html?deploy=058262102435f240bac3ed0079ae251ef002d283` returned 11 catalysis results, exposed `#saved-status` as `role="status"` with `aria-live="polite"`, had no horizontal overflow, and logged no console errors.

### Phase 2 regression and verification evidence

- Migration and compatibility: additive migration `0003_phase2_alert_lifecycle.sql` extends the existing notification ledger with `message_kind`, terminal-state, provider quota/idempotency, digest-overflow, and exact rendered-payload fields plus `rate_limits.last_reservation_key`; existing event rows default to notification, no lifecycle state is rewritten, and the deployment rollback path terminalizes verification jobs that the prior Worker cannot understand. The migration regression starts from schema 0002 with active, inactive, unverified, expired, and suppressed subscriptions plus queued, failed, sending, and sent events, then proves every representative state is preserved with forward-compatible defaults.
- `FF-BUG-003`: duplicate active subscriptions retain their existing baseline; inactive, paused, unverified, and expired subscriptions receive a fresh baseline and verification cycle in one D1 batch. Tests prove stale qualifications, watermarks, and queued state cannot cross cycles, including evaluation-token, claim, reactivation, and in-flight provider races.
- `FF-BUG-006`: immediate messages say `Unsubscribe from this alert`; multi-alert digests say `Manage all alerts` and `Unsubscribe from all Funding Finder email alerts` in both HTML and plain text. Route regressions prove single-alert scope leaves sibling alerts active and all-alert scope deactivates both.
- `FF-BUG-007`: health is available only when schema 2, D1, the selected/configured Resend provider, outbound delivery, and the scheduler are all ready. Live health returned `service=available`, `delivery_ready=true`, `schema_version=2`, `email_provider=resend`, `email_provider_selected=true`, `email_provider_configured=true`, `email_template_version=phase2-lifecycle-20260825`, `outbound_email_enabled=true`, and `scheduler_ready=true`.
- `FF-BUG-008`: verification delivery is durably queued before acceptance and is claim-safe, quota-reserved, provider-message-correlated, idempotent, and retryable for transient or ambiguous outcomes while permanent outcomes terminate. Coverage includes concurrent claims, exact-key quota reuse, quota exhaustion, refresh races, completion during delivery, network-outcome reconciliation after completion, pending suppression evidence, atomic provider-ID commit rollback/retry, exact payload replay across deployment changes, and fresh-link rendering when token refresh changes the key.
- `FF-BUG-009`: suppressed recipients receive the same non-enumerating creation response but cannot become deliverable or apparently active; verification, evaluation, queued delivery, provider webhooks, and re-creation all preserve suppression. The live bounded check used only invalid capabilities and returned truthful verification `400`, manage `404`, and unsubscribe `404` pages without creating or changing a user alert.
- `FF-BUG-017`: weekly selection is subscriber-fair and provider-message-bounded; each digest is capped at 25 events, a second subscriber remains selectable, and overflow remains queued. Network reconciliation and ordinary HTTP retries reuse one quota reservation, exact event group, idempotency key, overflow notice, and byte-identical HTML/plain-text payload; mobile-render/size assertions remain bounded below 200 KB.
- Review and release: all PR #57 threads were resolved. The final automated exact-head review of `b221b1ba5d85756169067840063d71334a922a01` found no major issue, and the exact head passed the complete protected gate before merge. Deployment run `32927016026` is tied to merged `main` SHA `f30ef367d093a94541d9764830b9f6a486ca4da7`; its migration, Worker health, bounded smoke, Pages equality, and no-main-advance checks all passed without rollback.

### Phase 3 regression and verification evidence

- `FF-BUG-002`: NSF, NIH, and DOE fixtures place valid institution awards after locally rejected rows and prove normalized offsets, retained raw diagnostics, exhaustion, safety-bound disclosure, and truthful `has_more`. NSF scans at most 12 pages of 25 rows, NIH at most 12 pages of 100 rows, and DOE at most 10 pages with normalized offset capped at 100. NSF and DOE round-robin at most three server-trusted identity queries inside those existing total caps, preserving deterministic per-query source order, unioning and deduplicating by source award ID, and never weakening local institution validation.
- `FF-BUG-012` and `FF-BUG-013`: synthetic acronym fixtures prove MIT/UVA ambiguity requires explicit selection, while a unique canonical name or unambiguous Caltech alias may resolve. Keyboard/active-descendant state, screen-reader status, Escape, visible locations, shared URLs, and complete-name registry-outage fallback remain covered. Worker contracts reject uncontrolled short acronyms, client-supplied identity mismatch, and ROR ID/name mismatch; exact ROR records are server-resolved and cached for one hour, curated UEI/IPF/source names override ROR, and defensible ROR names are bounded to three NSF/DOE queries without claiming a legal-grantee crosswalk.
- `FF-BUG-021`: deterministic name fixtures cover case/spacing, initial punctuation, `First Middle Last` and `Last, First Middle`, honorifics/suffixes, full middle names versus initials, apostrophes/hyphens, common names, and conflicting middle initials, emails, and stable identifiers. Grouping uses stable identifier, exact direct email, exact complete normalized name at the same resolved institution, then the constrained missing-middle rule; fuzzy/topic/LLM evidence is never used. Each source receives at most four published/constructed variants, results are post-validated and deduplicated by `source + award_id`, partial failures retain matches and retry the exact submitted page, and unsent edits cannot contaminate a retry. The Marc fixture groups two `Marc Porosoff` NSF awards and one `Marc D Porosoff` DOE award once and returns all three; dropdown counts explicitly mean currently loaded awards, variants are disclosed accessibly, and pagination/shared URL/Back/Forward tests pass.
- `FF-BUG-022`: deterministic answers cover counts, investigators, programs, years, award lists, DOE BES, and catalysis. Optional narrative synthesis is limited to 24 public award records, 800 abstract characters per record, and 18,000 serialized characters; up to six material claims each require validated evidence IDs from the exact pack, and any fabricated ID, malformed response, provider failure, or missing key falls back to the deterministic answer. The UI shows the original question, visible filters, answer, cited evidence, full cards, loaded count, searched/unavailable sources, paging and truncation limits. Load more retains the answer and makes no paid call until the explicit update control is used. Privacy regressions exclude profiles, CVs, ORCID publication text, uploads, saved notes, pursuit state, alert data, unrelated chat, and provider keys; model HTML is never rendered.
- Review and release: PR #60 received one comprehensive and two exact-head automated reviews because consequential findings changed the candidate head. Eight consequential threads were corrected in batches and resolved: deterministic no-key/failed-translation answers, NSF safety-bound `has_more`, bounded trusted NSF/DOE aliases, retryable partial investigator variants, fair NSF/DOE page allocation, exact submitted-request retry state, and truthful NIH safety-bound disclosure. Exact implementation head `89b71407f72f99c7b894625218d3482e4da74adf` passed protected run `32953173498` before merge; merged SHA `1cc0a2a397338e6fce7cac38a6f9b2875fa7add9` passed post-merge run `32953992318`.
- Production release: deployment run `32953992332` deployed Award Worker version `c3f8c613-1ead-4ce3-be5a-b6ec1b4c0b75` from exact protected `main`, with rollback version `7faebbc9-08e4-4ad5-816a-cbed80d7c4b7`. Live `/health` returned HTTP 200 with service available, schema 1, credentials not required, ROR adapter 1.1.0, curated-or-server-validated-ROR resolution, adapter versions NSF/NIH 1.3.0 and DOE 1.2.0, and the documented paging bounds. Bounded smokes at 2026-08-26T09:38Z validated live ROR and institution-scoped sources: NSF returned awards `2533635` and `2345734` for the Rochester/Marc query; the current DOE Marc D query returned zero; NIH loaded `R01HL174537` with additional pages disclosed. A separate live CORS probe verified the exact Pages origin on an HTTP 200 response, the expected origin/method/header/max-age policy on an HTTP 204 preflight, and HTTP 403 with no allow-origin header for a disallowed origin. Pages run `32953990450` and the release workflow verified byte-identical `funded_awards.html` and `match_explorer.html` against the merged SHA. Rollback was not invoked.

### Finding-level completion checklist

- [x] `FF-BUG-001`
- [x] `FF-BUG-002`
- [x] `FF-BUG-003`
- [x] `FF-BUG-004`
- [ ] `FF-BUG-005`
- [x] `FF-BUG-006`
- [x] `FF-BUG-007`
- [x] `FF-BUG-008`
- [x] `FF-BUG-009`
- [ ] `FF-BUG-010`
- [x] `FF-BUG-011`
- [x] `FF-BUG-012`
- [x] `FF-BUG-013`
- [x] `FF-BUG-014`
- [x] `FF-BUG-015`
- [x] `FF-BUG-016`
- [x] `FF-BUG-017`
- [ ] `FF-BUG-018`
- [ ] `FF-BUG-019`
- [ ] `FF-BUG-020`
- [x] `FF-BUG-021`
- [x] `FF-BUG-022`
- [ ] `FF-BUG-023` - candidate implementation complete; protected merge/deployment closeout pending
- [ ] `FF-BUG-024` - candidate implementation complete; protected merge/deployment closeout pending
- [ ] `FF-BUG-025` - candidate implementation complete; protected merge/deployment closeout pending

For every checked item, the completing PR must cite its regression test and acceptance evidence.

---

## 6. Definition of complete

This bug-fix program is complete only when:

1. all twenty-five finding IDs are checked with evidence;
2. all four phases are merged through protected PRs;
3. the complete Python, contract, frozen search-quality, real-browser, and accessibility gates pass against the final protected `main`;
4. affected Workers and Pages assets are deployed and verified against that same final SHA;
5. the recurring external-source degradation is resolved or truthfully documented as an upstream limitation with correct bounded fallback;
6. existing browser data, alert subscriptions, legacy links, shared URLs, source mappings, and privacy boundaries remain compatible;
7. no untracked known defect from this plan is silently deferred;
8. the final execution record includes test counts, workflow references, deployed versions, rollback evidence, known limitations, and an explicit release decision.

At that point, stop. Any new feature, architecture change, or unrelated cleanup requires a separate roadmap.
