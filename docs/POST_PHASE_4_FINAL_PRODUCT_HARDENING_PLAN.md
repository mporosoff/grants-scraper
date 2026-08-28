# Funding Finder Post-Phase-4 Final Product Hardening Plan

**Document status:** Authoritative execution plan for the remaining post-Phase-4 work  
**Plan version:** 2.0  
**Repository:** `mporosoff/grants-scraper`  
**Reconciled:** 2026-08-28  
**Completed program baseline:** protected `main` at `888ca4264f0c437f970b867b9e3c28b4d393643b`  
**Unit 0 synchronization baseline:** protected `main` at `1cbbb345a3b85051256dc934f9fe28dbe137d9d9`  
**Purpose:** Integrate the already-built Unit A and Unit B candidates, complete the residual alert-delivery/mobile work, and close the post-Phase-4 record without reopening the completed twenty-five-finding hardening program.

The SHAs above record the completed-program and Unit 0 synchronization baselines. They are not instructions to reset the repository. Every implementation unit must start from the then-current protected `main` and preserve any later merged work.

---

## 1. Relationship to the existing plans

### Completed authoritative plan

`docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` remains the authoritative record for the completed four-phase, twenty-five-finding program. All twenty-five findings are complete. Do not reopen or renumber them.

### Historical untracked roadmap

`docs/FUNDING_FINDER_FUNDED_AWARDS_AND_ALERTS_PLAN.md` is an untracked historical product roadmap. It describes major features as future work even though those features are now deployed. It is not an execution authority for Units A-D. Preserve it unless the user separately authorizes archival or deletion.

### This plan

This document governs only the remaining post-Phase-4 work:

1. Unit 0 — commit and merge this reconciliation.
2. Unit A — integrate the frozen AI-provider and Funding Finder layout candidate.
3. Unit B — integrate the frozen complete-result Funded Awards candidate.
4. Unit C — perform the residual alert-delivery audit and mobile alert-dialog correction.
5. Unit D — reconcile final documentation after Units A-C are live.

Cloudflare Workflows/Queues evaluation is a separate future architecture item. It does not block Units A-D, but no additional scheduler feature may be added before that evaluation.

---

## 2. Reconciled status

| Workstream | Status | Evidence or candidate | Remaining work |
|---|---|---|---|
| Four-phase bug-fix and UX-hardening program | Complete and live | PR #79; protected `main` `888ca4264f0c437f970b867b9e3c28b4d393643b` | None |
| Alerts scheduler recovery and Phase 4 operational closeout | Complete and live | Alerts Worker `7b95c810-f46f-47a8-9a8d-6100aa75bb34`; rollback `34c69ecb-7c70-4892-a28f-748ece759df0` | Future Workflows/Queues evaluation only |
| Unit A | Implemented and locally validated; not integrated | `codex/post-phase4-unit-a` at `c6fd6bab2f86f3c6ef3959bd55e26e7b952e553d` | Rebase, exact-head validation, PR, merge, deployment classification, production verification |
| Unit B | Implemented and locally validated on Unit A; not integrated | `codex/post-phase4-unit-b` at `cfbbcd309d8340313e7f10b70851603ddbbb95a6` | Integrate after Unit A; exact-head validation, PR, merge, Award Worker/Pages deployment, production verification |
| Unit C | Not started as a bounded residual unit | Current protected `main` contains the completed PR #73/#78 alert backend baseline | Evidence-based residual delivery audit and mobile dialog work |
| Unit D | Not started | This plan and the completed hardening plan | Final post-Phase-4 execution record |

No pull request exists for Unit A or Unit B as of this reconciliation. Unit A is pushed to `origin`; Unit B is a clean local branch without an upstream branch.

Until a separately authorized Unit B task creates remote preservation, the Unit B local branch and worktree are preservation-critical. Do not delete, rename, reset, rebase, garbage-collect, or otherwise rewrite them. If the exact commit is not locally available when Unit B is authorized, stop rather than reconstructing or substituting it.

---

## 3. Completed baseline that all units must preserve

The following behavior is already complete and is not new Unit A-D scope:

- all twenty-five findings in the authoritative bug-fix plan;
- truthful missing amount/year rendering and saved-state persistence feedback;
- corrected Funded Awards drill-down/request state and source-specific failure language;
- independent normalized NSF, NIH, and DOE retrieval and ROR identity validation;
- source-balanced Institutional Intelligence evidence and structured investigator/program/year presentation;
- institution questions submitting with Enter;
- catalog loading feedback in the primary Find funding action;
- removal of the optional institutional-identity note;
- clarified submitted-year and loaded-award-year presentation;
- generic additional-award loading and ten-card browser presentation;
- alert verification queues, retries, idempotency, suppression, signing-key rotation, cleanup, rate limits, health, and scheduler recovery;
- Award/ROR abuse controls;
- truthful JHU disablement while official unattended routes remain Cloudflare-challenged;
- current frozen-query, frozen-P9, catalog/vector, accessibility, and no-drift baselines.

Unit B may replace the existing incremental award-card browsing with its complete-result snapshot architecture, but it must preserve every applicable truthfulness, identity, provenance, failure-isolation, and accessibility contract above.

---

## 4. Remaining finding registry

| ID | Unit | Severity | Finding or improvement | Current status |
|---|---|---|---|---|
| `PFH-001` | A | High | User-connected OpenAI/Anthropic calls can return malformed or structurally ambiguous results to AI refinement/chat consumers. | Implemented in frozen Unit A; not live |
| `PFH-002` | A | Medium | Funding Finder primary search and AI refinement controls are visually fragmented and the AI action/key readiness relationship is unclear. | Implemented in frozen Unit A; not live |
| `PFH-003` | A | Medium | Strong/Potential counts and explanatory privacy copy occupy the wrong visual hierarchy. | Implemented in frozen Unit A; not live |
| `PFH-004` | A | Medium | AI failure must preserve the ordinary query, filters, results, key state, and a bounded retry path. | Implemented in frozen Unit A; not live |
| `PFH-005` | B | High | Funded Awards cannot truthfully promise complete full-query totals while browser state contains only incrementally loaded source pages. | Implemented in frozen Unit B; not live |
| `PFH-006` | B | High | Additional retrieval must be independently bounded to no more than 25 newly normalized awards per requested agency per action, without making 25 a total-result cap. | Implemented in frozen Unit B; not live |
| `PFH-007` | B | High | Investigator, program, year, agency, and deterministic-question aggregates must describe the complete normalized snapshot when completeness is proven and must disclose partial state otherwise. | Implemented in frozen Unit B; not live |
| `PFH-008` | B | Medium-High | Investigator and program selections must be reversible and must not become unintended permanently stacked request filters. | Implemented in frozen Unit B; not live |
| `PFH-009` | B | Medium-High | Award cards require server-backed numbered pagination, direct page access, and selectable page sizes of 10, 25, and 50. | Implemented in frozen Unit B; not live |
| `PFH-010` | B | Medium-High | Source failure/retry must retain successful source results and create a coherent successor snapshot without inventing completeness. | Implemented in frozen Unit B; not live |
| `PFH-011` | C | High | Verification-email behavior across multiple addresses/subscriptions has not been conclusively separated into application acceptance, provider acceptance, and inbox delivery. | Residual audit not started |
| `PFH-012` | C | Medium | The mobile alert dialog permits background-page scrolling and requires focus/scroll/repeated-open hardening. | Not started |
| `PFH-013` | D | Medium | The post-Phase-4 implementation and production evidence is not yet recorded in one repository-tracked execution record. | This plan begins the correction; final closeout pending |
| `PFH-014` | Future | Architectural | Additional alert scheduler features require a Cloudflare Workflows/Queues versus Cron/D1 architecture decision. | Recorded; intentionally outside Units A-D |

---

## 5. Global execution rules

1. Read the repository-root `AGENTS.md`, this plan, and `docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` completely before editing.
2. Start every unit from the then-current protected `main`. Never reset protected `main` to a historical candidate SHA.
3. Use one branch/worktree and one protected pull request per unit. Do not combine Units A, B, C, and D.
4. Before freezing a candidate, audit the complete invariant family once and add regressions for all discovered boundary cases in that family. Do not push one speculative fix at a time.
5. Follow the exact-head CI and review-convergence rules in `AGENTS.md`. Never merge a red, stale, or incompletely reviewed candidate.
6. A previously green frozen candidate is evidence, not current validation. Rerun every applicable gate after rebasing onto current protected `main`.
7. Preserve catalog contents, vectors, semantic passages, model fingerprints, Strong/Potential membership and ranking, frozen baselines, profile/CV/ORCID semantics, and source mappings unless an exact selected-unit contract requires a compatibility update.
8. Do not expose, print, copy, log, commit, or request a user API key, alert secret, email address, token, provider identifier, or message body.
9. Preserve no-email-enumeration, provider idempotency, signing-key rotation, suppression, privacy, ROR validation, source isolation, cache isolation, and official-source provenance.
10. Use forward-compatible migrations only. Record rollback behavior before deployment.
11. Let normal repository deployment-input classification decide which Pages/Worker workflows run. Do not force unrelated deployments.
12. Update this plan's execution record only with verified evidence. Passing tests alone does not prove production behavior.
13. Do not modify or commit the unrelated untracked historical roadmap during Units 0-A-C.
14. Stop a unit only for a genuinely unsafe action, missing authority/credential, an unresolved consequential review result under repository policy, or an external failure that cannot be safely isolated.

---

## 6. Unit 0 — Plan reconciliation

### Objective

Add this document to the repository so Units A-D have one version-controlled execution authority.

### Scope

- Add `docs/POST_PHASE_4_FINAL_PRODUCT_HARDENING_PLAN.md` with this exact reconciled content.
- Verify all referenced SHAs, branches, PRs, Worker versions, migration state, and protected-main baseline read-only before committing.
- Preserve `docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` unchanged.
- Preserve the untracked `docs/FUNDING_FINDER_FUNDED_AWARDS_AND_ALERTS_PLAN.md` unchanged and uncommitted.

### Gate

- documentation-only diff;
- Markdown and repository documentation checks;
- protected exact-head CI required by repository policy;
- terminal exact-head review;
- protected merge;
- no Worker, D1, catalog, vector, ranking, search-package, or refresh deployment.

### Decision

`UNIT 0 COMPLETE — POST-PHASE-4 EXECUTION PLAN IS VERSION-CONTROLLED`

---

## 7. Unit A — User-connected AI structured responses and Funding Finder layout

### Frozen evidence

- Branch: `codex/post-phase4-unit-a`
- Candidate: `c6fd6bab2f86f3c6ef3959bd55e26e7b952e553d`
- Historical base: `ff8d1a271a628df0a185d0efeb4f7a89fa56bc06`
- Historical validation: 389 browser contracts; 59 targeted Playwright/mobile/accessibility scenarios; 7 Python entrypoint tests; 9 provider-contract tests.

The frozen SHA is not merge-ready because protected `main` advanced through PRs #77-#79.

### Integration method

1. Start a fresh Unit A integration branch from protected `main` after Unit 0 merges.
2. Apply the frozen Unit A change as one preserved logical change, using rebase or cherry-pick as appropriate.
3. Audit the resulting diff against the original Unit A commit and current `main`.
4. Resolve the known overlap in `match_explorer.html` and `data/search-v2-release.json` deliberately:
   - retain current catalog metadata/version identity from protected `main`;
   - retain the PR #78 optional candidate-index/search-retrieval compatibility path and hashes;
   - retain Unit A's intended layout and application/provider changes;
   - regenerate the release manifest using repository tooling rather than hand-selecting stale hashes.
5. Do not reintroduce historical catalog or search-package artifacts from the Unit A base.

### Required behavior

- All six user-connected AI operations use one shared structured-result path with operation-specific strict schemas.
- OpenAI uses its supported native strict structured-output contract with storage disabled.
- Anthropic uses its supported native structured-output contract.
- Local validation rejects missing fields, unexpected fields, invalid bounds, unsupported tool blocks, multiple ambiguous terminal messages, and fabricated evidence identifiers.
- Only malformed/incomplete/schema-invalid structured output receives one bounded retry.
- Authentication, model access, quota, refusal, network, and timeout failures do not retry blindly and do not expose provider bodies or secrets.
- Ordinary catalog search remains fully usable after any AI failure.
- The user's query, filters, results, and locally stored provider configuration remain intact after failure.
- The primary Find funding control is adjacent to the main query input and Enter submits it.
- The separate section is titled `Expand and refine your search with AI`.
- Its AI action remains visible outside the collapsible provider setup, disabled until both a usable result context and a current entered/saved key exist.
- Strong/Potential counts appear with the main results count.
- Redundant long-form privacy/traffic text is removed from that visual block while essential key, cost, help, and privacy disclosure remains available in provider setup.
- Desktop, 540 px, 390 px, and 320 px layouts remain keyboard-operable and horizontally contained.

### Required validation

- all Unit A provider and layout contracts;
- every existing AI consumer contract;
- complete browser-contract suite;
- complete Python suite;
- complete Playwright/accessibility suite;
- provider-failure, malformed-output, retry, citation, privacy, keyboard, and mobile regressions;
- frozen-query and frozen-P9 gates;
- catalog/vector/model-fingerprint/no-drift checks;
- release-manifest and deployment-input classification.

### Merge and production gate

- one Unit A PR;
- exact-head protected CI and terminal review;
- merge only the exact reviewed candidate;
- verify Pages and any automatically classified compatibility release;
- verify primary search, Enter submission, key-disabled/key-ready AI state, ordinary-search preservation after provider failure, and narrow viewport behavior without inspecting a real user key;
- record final PR, candidate, protected-main SHA, deployment evidence, and rollback/classification evidence.

### Decision

`UNIT A COMPLETE — STRUCTURED USER-CONNECTED AI AND SEARCH LAYOUT ARE LIVE`

---

## 8. Unit B — Funded Awards complete-result architecture

### Frozen evidence

- Branch: `codex/post-phase4-unit-b`
- Candidate: `cfbbcd309d8340313e7f10b70851603ddbbb95a6`
- Parent/Unit A dependency: `c6fd6bab2f86f3c6ef3959bd55e26e7b952e553d`
- Historical validation: 397 browser contracts and 70 Playwright/accessibility tests.
- Historical boundaries: 0, 1, 9, 10, 11, 25, 26, 50, and 51 results.
- Historical synthetic architecture measurement: 1,650 normalized awards across NSF, NIH, and DOE.

The Unit B commit must not be integrated until Unit A is merged and production-verified.

### Integration method

1. Before applying the candidate, publish exact commit `cfbbcd309d8340313e7f10b70851603ddbbb95a6` to a remote preservation ref and verify that the remote ref resolves to that full SHA. This preservation step does not open the Unit B pull request or integrate Unit B.
2. Start from protected `main` after Unit A merges.
3. Apply only the Unit B commit/change. Do not replay or duplicate the historical Unit A parent commit.
4. Compare the resulting diff with the frozen Unit B candidate and current Award Worker/Pages implementation.
5. Repeat the architecture measurement and verify current Cloudflare Worker limits and deployment configuration rather than relying only on historical local wall time.

### Architecture contract

- A server-built immutable snapshot owns one submitted query and one explicit ordering version.
- Snapshot identity includes institution/ROR identity, source selection, year/fiscal-year interpretation, submitted criteria, as-of boundary, ordering version, and every criterion that changes membership.
- Exact totals are exposed only when every requested source is fully exhausted and the normalized/deduplicated snapshot is complete.
- Otherwise the result is explicitly `partial`, `safety_bounded`, `rate_limited`, `unsupported`, or `unavailable` per applicable source.
- Snapshot expiration or a cache-colo miss produces a recoverable refresh state rather than invented continuity.
- The browser does not use an unbounded loop to fetch an entire result set.

### Retrieval and ordering contract

- Each requested agency advances independently.
- One hydration action adds no more than 25 newly normalized awards per agency.
- Twenty-five is a per-action/per-agency ceiling, never a total-result cap.
- Source controls state how many awards were added and what remains known or unknown.
- Stable ordering is most recent award/action date, then project start, then award year, missing dates last, then source and award ID tie-breakers.
- Source-specific validation, post-validation paging, deduplication, provenance, rate limits, ROR identity safety, and cache isolation remain intact.

### Aggregate and facet contract

- Complete snapshot totals, investigator identities, programs, represented years, agency totals, and deterministic answers are derived from the full normalized snapshot rather than the visible card page.
- Partial snapshots never present an exact total or comprehensive answer.
- Investigator and program facets filter the same immutable snapshot.
- `All investigators`, `All programs`, and one-action reset remove the active facet without retaining unintended filter stacking.
- A new submitted query creates/replaces the snapshot and resets incompatible facet/page state.

### Pagination contract

- Default page size is 10.
- User-selectable page sizes are 10, 25, and 50.
- Pagination provides accessible Previous, Next, numbered pages, and compact ellipses.
- Direct navigation to a page not resident in browser memory is server-backed.
- URL, reload, Back/Forward, page, page size, active facet, focus, and scroll restoration are deterministic.

### Failure and retry contract

- A failed source does not discard successful source results.
- Source retry creates a coherent successor snapshot and retains successful sources.
- Ambiguous full-result facets reset when the successor cannot prove the same complete membership.
- Optional AI remains limited to strict question translation and evidence-bounded narrative synthesis. It does not decide source completeness or fabricate aggregates.

### Required validation

- all Unit B snapshot contracts and browser scenarios;
- boundary counts 0, 1, 9, 10, 11, 25, 26, 50, and 51;
- per-agency batch ceilings and independent source advancement;
- ordering, missing-date ties, deduplication, and consecutive snapshots;
- complete/partial/unavailable/rate-limited/unsupported/safety-bounded states;
- full-snapshot aggregates and reversible facets;
- direct pages, page sizes, history, focus, scroll, keyboard, and mobile containment;
- failed-source successor snapshots;
- current ROR, Award Worker, cache, source-adapter, privacy, and provider contracts;
- complete Python, browser, Playwright/accessibility, frozen-query, frozen-P9, no-drift, Worker-validation, and deployment-classification gates;
- production CPU/subrequest/response-size telemetry after deployment.

### Merge and production gate

- one Unit B PR after Unit A is live;
- exact-head protected CI and terminal review;
- deploy only classified Award Worker/Pages components;
- record new Award Worker version and rollback version;
- verify representative NSF, NIH, DOE, ROR, exact-ID, institution, broad-year, facet, pagination, partial-source, and snapshot-expiry behavior in production;
- verify no ranking, vector, catalog, or opportunity-search drift.

### Decision

`UNIT B COMPLETE — FUNDED AWARDS COMPLETE-RESULT SNAPSHOTS ARE LIVE`

---

## 9. Unit C — Residual alert delivery and mobile dialog

### Objective

Determine what, if anything, remains defective after PRs #73 and #78, correct only demonstrated residual behavior, and finish the mobile alert-dialog interaction.

### Read-only delivery audit first

Using privacy-safe aggregate/provider-correlated evidence:

- distinguish subscription request acceptance, verification-event reservation, provider request, provider acceptance, provider webhook state, and confirmed inbox receipt;
- determine whether multiple email addresses can create and verify independent subscriptions;
- determine whether multiple subscriptions for one address remain independently manageable;
- verify that immediate dispatch cannot select an unrelated older verification event instead of the newly created/reserved event;
- verify retry behavior across current, previous, and bounded legacy signing paths;
- verify provider idempotency and ambiguous-outcome reconciliation;
- verify suppression, unsubscribe, manage links, and no-email-enumeration behavior;
- do not claim inbox delivery from provider acceptance alone.

Do not display or record addresses, tokens, provider IDs, secrets, or message bodies. Do not send to an invented or unauthorized address. If live inbox confirmation is not authorized, report that boundary truthfully and rely on deterministic provider-correlated evidence.

### Delivery correction rule

- If current production already satisfies the delivery invariants, do not redesign the backend. Add only missing deterministic regression or operational evidence.
- If a residual defect is demonstrated, fix the smallest complete invariant family and preserve the final Phase 4 scheduler/state-machine baseline.
- Do not add more scheduler functionality in Unit C.

### Alert-dialog behavior

- Opening the alert dialog locks background-page scrolling on desktop and mobile.
- The dialog itself remains scrollable when its content exceeds the viewport.
- Focus moves into the dialog, remains contained, and returns to the invoking control on close.
- Escape, explicit close, successful submission, failure, and repeated opening restore focus and scroll state correctly.
- The submitted email remains visible or is replaced by an unmistakable sent/verification-pending state; the UI must not look as though nothing happened.
- Mobile layouts remain contained at 320 px and 390 px, including virtual-keyboard and orientation changes where testable.

### Required validation

- alert lifecycle, privacy, delivery, provider, signing-key, migration, scheduler, retention, rate-limit, health, release, and no-email-enumeration contracts;
- deterministic multiple-address and multiple-subscription cases;
- retry/idempotency/ambiguous-provider cases;
- dialog scroll lock, internal scroll, focus trap, focus return, Escape, repeated-open, submission success/failure, 320 px and 390 px tests;
- complete applicable Python, browser, Playwright/accessibility, frozen/no-drift, and deployment-classification gates.

### Merge and production gate

- one Unit C PR;
- exact-head protected CI and terminal review;
- deploy only classified Alerts/Pages components;
- if the Alerts Worker changes, record deployed and rollback versions and verify health remains HTTP 200 with delivery and scheduler readiness truthful;
- verify aggregate provider/event state without exposing subscriber data;
- do not require or claim unauthorized inbox confirmation.

### Decision

`UNIT C COMPLETE — RESIDUAL ALERT DELIVERY IS EVIDENCED AND THE MOBILE DIALOG IS HARDENED`

---

## 10. Unit D — Final documentation reconciliation

### Objective

Close the post-Phase-4 program after Units A-C are merged, deployed, and verified.

### Required updates

- Mark `PFH-001` through `PFH-013` complete only with evidence.
- Record every Unit 0/A/B/C PR, candidate SHA, protected-main SHA, exact-head review, exact-head CI, post-merge CI, Pages/Worker deployment, deployed version, and rollback version.
- Record Unit A provider behavior and remaining user-key boundary.
- Record Unit B complete versus partial semantics, batch ceilings, pagination, ordering, snapshots, and production limits.
- Record Unit C provider-correlated versus inbox-delivery evidence and mobile dialog behavior.
- Append a concise post-Phase-4 addendum or pointer to `docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` without rewriting its completed Phase 4 evidence.
- Record genuine remaining source limitations, including JHU challenge behavior and snapshot/cache locality if still applicable.
- Record the Workflows/Queues architecture follow-up as future work, not as completed implementation.

### Gate

- documentation-only final diff;
- factual diff/provenance audit against merged PRs and production evidence;
- protected exact-head CI and terminal review;
- protected merge;
- no unrelated deployment.

### Decision

`POST-PHASE-4 FINAL PRODUCT HARDENING COMPLETE`

---

## 11. Future architecture item — Cloudflare Workflows and Queues

Before adding any new scheduler behavior, complete a separate architecture decision comparing:

1. the current Cron + D1 orchestration;
2. Cloudflare Workflows with D1 business state; and
3. a Workflow + Queue hybrid with D1/provider idempotency.

The decision must verify the actual account plan, CPU, wall-time, subrequest, step-result, state-retention, cost, migration, rollback, and observability constraints. Queues are at-least-once, so deterministic D1 and provider idempotency remains mandatory. This work is not authorized as part of Units A-D.

---

## 12. Execution record

| Unit | Status | PR | Candidate | Final `main` | Review/CI | Deployment |
|---|---|---|---|---|---|---|
| 0 | Not started | — | — | — | — | Documentation only |
| A | Frozen candidate; not integrated | — | `c6fd6bab2f86f3c6ef3959bd55e26e7b952e553d` | — | Historical local validation only | Not deployed |
| B | Frozen candidate on Unit A; not integrated | — | `cfbbcd309d8340313e7f10b70851603ddbbb95a6` | — | Historical local validation only | Not deployed |
| C | Not started | — | — | — | — | — |
| D | Not started | — | — | — | — | Documentation only |

Final completion requires Units 0 and A-D to be merged and every applicable production gate to be truthfully closed.
