# Funding Finder Post-Phase-4 Final Product Hardening Plan

**Document status:** Final execution record for the completed post-Phase-4 hardening program<br>
**Plan version:** 3.0<br>
**Repository:** `mporosoff/grants-scraper`  
**Reconciled:** 2026-08-29<br>
**Completed program baseline:** protected `main` at `888ca4264f0c437f970b867b9e3c28b4d393643b`  
**Unit 0 synchronization baseline:** protected `main` at `1cbbb345a3b85051256dc934f9fe28dbe137d9d9`  
**Final application baseline:** protected `main` at `fee9912a47d0b5841d04973a23086e6566546200`<br>
**Purpose:** Preserve the completed twenty-five-finding program and record the verified Unit 0, A-C integration, production deployment, and Unit D documentation closeout evidence.

The SHAs above record the completed-program and Unit 0 synchronization baselines. They are not instructions to reset the repository. Every implementation unit must start from the then-current protected `main` and preserve any later merged work.

---

## 1. Relationship to the existing plans

### Completed authoritative plan

`docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` remains the authoritative record for the completed four-phase, twenty-five-finding program. All twenty-five findings are complete. Do not reopen or renumber them.

### Historical untracked roadmap

`docs/FUNDING_FINDER_FUNDED_AWARDS_AND_ALERTS_PLAN.md` is an untracked historical product roadmap. It describes major features as future work even though those features are now deployed. It is not an execution authority for Units A-D. Preserve it unless the user separately authorizes archival or deletion.

### This plan

This document governed the now-complete post-Phase-4 work:

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
| Unit A | Complete and live | Closed-unmerged preservation PR #82 at `443748b0381fedbae5ba478fb04b11dcf057827e`; integrated application PR #83 at candidate `55df7df2c20e92d3eff243b66ad10c0416292d28`; protected `main` `fee9912a47d0b5841d04973a23086e6566546200` | None |
| Unit B | Complete and live | Historical frozen delta `cfbbcd309d8340313e7f10b70851603ddbbb95a6`; integrated application PR #83; Award Worker `d375880e-4ec4-4436-b435-2cb41e302124` | None |
| Unit C | Complete and live within the A-C application release | Train commit `ba2938983d5689bdbbb757a0ba277cb40b4ccd9f`; integrated application PR #83; Pages deployment verified; Alerts Worker and D1 intentionally unchanged | No authorized inbox-receipt evidence; that boundary is recorded, not an unfinished defect |
| Unit D | Complete through this documentation-only closeout | This final execution record and the concise addendum in the completed hardening plan | None |

At Unit 0 reconciliation, no pull request existed for Unit A or Unit B. PR #82 subsequently preserved an integrated Unit A candidate and exact-head evidence, but was closed without merge under the authorized integration-train amendment. Its branch and commits remain preservation evidence. Unit B remained a clean local branch without an upstream branch until its exact delta was incorporated into PR #83.

The frozen Unit A and Unit B branches/worktrees remain historical preservation evidence and were not rewritten during the integrated release or Unit D. They are no longer unintegrated implementation authority because PR #83 is live, but they must not be represented as merged commits or substituted for the recorded application candidate.

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
| `PFH-001` | A | High | User-connected OpenAI/Anthropic calls can return malformed or structurally ambiguous results to AI refinement/chat consumers. | Complete and live through PR #83 |
| `PFH-002` | A | Medium | Funding Finder primary search and AI refinement controls are visually fragmented and the AI action/key readiness relationship is unclear. | Complete and live through PR #83 |
| `PFH-003` | A | Medium | Strong/Potential counts and explanatory privacy copy occupy the wrong visual hierarchy. | Complete and live through PR #83 |
| `PFH-004` | A | Medium | AI failure must preserve the ordinary query, filters, results, key state, and a bounded retry path. | Complete and live through PR #83 |
| `PFH-005` | B | High | Funded Awards cannot truthfully promise complete full-query totals while browser state contains only incrementally loaded source pages. | Complete and live through PR #83 |
| `PFH-006` | B | High | Additional retrieval must be independently bounded to no more than 25 newly normalized awards per requested agency per action, without making 25 a total-result cap. | Complete and live through PR #83 |
| `PFH-007` | B | High | Investigator, program, year, agency, and deterministic-question aggregates must describe the complete normalized snapshot when completeness is proven and must disclose partial state otherwise. | Complete and live through PR #83 |
| `PFH-008` | B | Medium-High | Investigator and program selections must be reversible and must not become unintended permanently stacked request filters. | Complete and live through PR #83 |
| `PFH-009` | B | Medium-High | Award cards require server-backed numbered pagination, direct page access, and selectable page sizes of 10, 25, and 50. | Complete and live through PR #83 |
| `PFH-010` | B | Medium-High | Source failure/retry must retain successful source results and create a coherent successor snapshot without inventing completeness. | Complete and live through PR #83 |
| `PFH-011` | C | High | Verification-email behavior across multiple addresses/subscriptions has not been conclusively separated into application acceptance, provider acceptance, and inbox delivery. | Complete: application/provider acceptance evidence confirmed; provider-webhook and authorized inbox-receipt evidence absent and not claimed |
| `PFH-012` | C | Medium | The mobile alert dialog permits background-page scrolling and requires focus/scroll/repeated-open hardening. | Complete and live through PR #83 |
| `PFH-013` | D | Medium | The post-Phase-4 implementation and production evidence is not yet recorded in one repository-tracked execution record. | Complete through this Unit D documentation closeout |
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

## 5A. Authorized A-C integration-train amendment

This amendment was authorized after PR #82 preserved Unit A at `443748b0381fedbae5ba478fb04b11dcf057827e`. It supersedes only the separate unit-by-unit PR, review, complete-gate, merge, deployment, and production-verification sequence in Sections 7-10 and any directly conflicting per-unit sequencing in Section 5. It does not weaken any acceptance criterion, privacy/security requirement, exact-head green-check requirement, no-drift requirement, source-authority requirement, or production-verification requirement.

### Preserved Unit A checkpoint

- Preserve closed-unmerged PR #82, its branch, candidate, terminal clean exact-head review, and completed CI evidence; do not delete or rewrite them and do not rerun its unchanged failed workflow.
- The two failed scenarios used real opportunity `361187` / `PAR-26-114`, whose `close_date` is `2026-08-28`. Establish a deterministic test-scoped browser time of `2026-08-28T12:00:00Z` before navigation and application scripts for those scenarios. Preserve the real catalog record, deadline, current/expired filtering, normal timers, and exact mapping.
- Audit other E2E visibility assertions for expiring real records and correct only genuinely date-bound fixtures. Do not increase timeouts, add application test hooks, or call the expiry behavior a catalog-loading defect.
- Use only focused syntax, contract, and diff validation at this checkpoint. Unit A remains integrated into the A-C candidate, pending combined final validation and production deployment; it is not complete or live.

### One application train

1. Continue from exact Unit A candidate `443748b0381fedbae5ba478fb04b11dcf057827e` in one isolated integration worktree/branch.
2. Preserve separate logical commits for the amendment/date-fixture correction, Unit A, Unit B, and Unit C.
3. Apply only Unit B delta `cfbbcd309d8340313e7f10b70851603ddbbb95a6`; do not replay historical Unit A parent `c6fd6bab2f86f3c6ef3959bd55e26e7b952e553d`. Reconcile it against integrated Unit A and current protected-main behavior while preserving all snapshot, completeness, source-state, pagination, facet, ordering, retry, privacy, and Worker-limit contracts.
4. Perform Unit C's privacy-safe read-only delivery audit before backend changes. Correct only demonstrated residual delivery defects and implement the complete alert-dialog scroll, focus, Escape, repeated-open, verification-pending, and narrow-mobile contract while preserving the completed PR #73/#78 scheduler and delivery invariants.
5. Until A-C implementation is coherent, run only focused deterministic contracts, syntax checks, package/Worker validation, migration checks, and architecture measurements. Do not run complete Playwright/E2E, repository-wide Python, frozen-query, frozen-P9, or no-drift gates; do not request review, open/update an application PR, or deploy.

### Combined final application gate

After Units A-C are fully implemented, rebase the complete train once onto the then-current protected `main`, resolving drift without dropping or duplicating any unit behavior. Run the complete combined validation exactly once on the resulting candidate: Python, all browser contracts, complete Playwright/E2E and accessibility, frozen queries, frozen P9, no-drift, Worker/package validation, migration/deployment classification, and Unit B architecture/resource checks. Diagnose and correct a demonstrated failure before running a changed candidate; never rerun an unchanged failed candidate.

Open one application PR for integrated Units A-C. Request one exact-head Codex review only after the candidate is complete and protected checks are running or green. Continuous convergence is explicitly authorized for that PR: each review remains atomic to one SHA, all findings must be collected before edits, accepted consequential findings must be corrected coherently by invariant, and exact-head validation/review repeats only after the head changes. Merge only the unchanged exact reviewed head when every required check is green and no consequential thread remains unresolved.

After merge, track post-merge Tests and Pages; deploy only components classified by the merged diff; apply only required forward-compatible migrations; retain and record Worker rollback versions; verify every Unit A-C production contract; and prove no catalog, vector, ranking, or opportunity-search drift. Provider acceptance is not inbox receipt, and inbox delivery must not be claimed without authorized inbox evidence.

Unit D remains a separate post-deployment documentation-only closeout. Only after the integrated application deployment and production verification succeed may it reconcile this plan and add the concise required pointer to the completed historical plan through one documentation-only protected PR.

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

Close the post-Phase-4 program after Units A-C are merged, deployed, and verified. PR #83 and all applicable post-merge production gates satisfied that prerequisite on 2026-08-29.

### Required updates

- [x] Mark `PFH-001` through `PFH-013` complete only with evidence.
- [x] Record every Unit 0/A/B/C PR, candidate SHA, protected-main SHA, review artifact, exact-head CI, post-merge CI, Pages/Worker deployment, deployed version, and rollback version.
- [x] Record Unit A provider behavior and remaining user-key boundary.
- [x] Record Unit B complete versus partial semantics, batch ceilings, pagination, ordering, snapshots, and production limits.
- [x] Record Unit C provider-correlated versus inbox-delivery evidence and mobile dialog behavior.
- [x] Append a concise post-Phase-4 addendum or pointer to `docs/FUNDING_FINDER_BUG_FIX_AND_UX_HARDENING_PLAN.md` without rewriting its completed Phase 4 evidence.
- [x] Record genuine remaining source limitations, including JHU challenge behavior and snapshot/cache locality.
- [x] Record the Workflows/Queues architecture follow-up as future work, not as completed implementation.

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
| 0 | Complete | [PR #81](https://github.com/mporosoff/grants-scraper/pull/81) | `68af61ea71a9ba10144a7532916fa392f0c4738e` | `464d0dd48cd69eefee2bd349afd4f7a4b5ec0fe6` | [Terminal clean exact-head review](https://github.com/mporosoff/grants-scraper/pull/81#issuecomment-5458431203); [exact-head Tests `33216853205`](https://github.com/mporosoff/grants-scraper/actions/runs/33216853205); [post-merge Tests `33217703714`](https://github.com/mporosoff/grants-scraper/actions/runs/33217703714) | Documentation only; [Pages `33217702854`](https://github.com/mporosoff/grants-scraper/actions/runs/33217702854) passed; no Worker, D1, catalog, vector, ranking, search-package, or refresh deployment |
| A | Complete and live | [Preservation PR #82](https://github.com/mporosoff/grants-scraper/pull/82); integrated [PR #83](https://github.com/mporosoff/grants-scraper/pull/83) | Preserved `443748b0381fedbae5ba478fb04b11dcf057827e`; integrated `55df7df2c20e92d3eff243b66ad10c0416292d28` | `fee9912a47d0b5841d04973a23086e6566546200` | [PR #82 clean review](https://github.com/mporosoff/grants-scraper/pull/82#issuecomment-5459031304); PR #83 review/convergence and protected evidence recorded below; [exact-candidate Tests `33246300974`](https://github.com/mporosoff/grants-scraper/actions/runs/33246300974); [post-merge Tests `33246934811`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934811) | [Pages `33246934213`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934213); [search-package release `33246934851`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934851), version `60124838-52e5-4db7-8853-cdd5d08702f0`, rollback `e71f9ef0-77ba-49cc-9375-9a289ca3f941` |
| B | Complete and live | [PR #83](https://github.com/mporosoff/grants-scraper/pull/83) | Frozen delta `cfbbcd309d8340313e7f10b70851603ddbbb95a6`; train commits `716aa3979c02916bf6571f7fe0376242d9a1054e`, `502305afb14d69dc100ebcfcb7269866e52871f3`, `3c7a84915faa375e3ca47256fae82655bb30a046`; integrated `55df7df2c20e92d3eff243b66ad10c0416292d28` | `fee9912a47d0b5841d04973a23086e6566546200` | [Terminal review artifact](https://github.com/mporosoff/grants-scraper/pull/83#issuecomment-5459644970), convergence record, exact-candidate and post-merge Tests as above | [Award release `33246934839`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934839), version `d375880e-4ec4-4436-b435-2cb41e302124`, rollback `61f565cf-0c1b-419d-903c-6534e4ca72ec`; Pages passed |
| C | Complete and live | [PR #83](https://github.com/mporosoff/grants-scraper/pull/83) | Train commit `ba2938983d5689bdbbb757a0ba277cb40b4ccd9f`; integrated `55df7df2c20e92d3eff243b66ad10c0416292d28` | `fee9912a47d0b5841d04973a23086e6566546200` | Privacy-safe audit, terminal review/convergence, exact-candidate and post-merge Tests as above | Pages passed; [Alerts classifier `33246934814`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934814) retained version `7b95c810-f46f-47a8-9a8d-6100aa75bb34`; no Alerts Worker or D1 mutation |
| D | Complete through this closeout | This documentation-only closeout PR | Documentation-only commit based on application main `fee9912a47d0b5841d04973a23086e6566546200` | Recorded by the protected Unit D merge | Protected exact-head CI and terminal review are required on this closeout PR | Documentation only; Pages may run under repository policy; no application deployment is authorized |

### Pre-deployment integration evidence — 2026-08-28

- Unit A's two date-bound real-catalog fixtures are fixed at `2026-08-28T12:00:00Z`; both focused cases and the 32 applicable browser contracts passed.
- Unit B's final focused Worker gate passed 62 Award, ROR, snapshot, source-state, pagination, facet, ordering, retry, privacy, release, and deployment-classification contracts. Pinned Wrangler `4.125.0` accepted the package at 404.39 KiB uncompressed and 101.22 KiB gzip.
- The final production target is Workers Paid, with `limits.cpu_ms` explicitly set to 250. In the repeated 1,650-award synthetic measurement, snapshot construction measured 5.623 ms minimum, 9.691 ms p50, 13.097 ms p95, and 17.612 ms maximum; create-response serialization measured 0.486 ms p50 and page-50 construction plus serialization measured 1.741 ms p50. Actual post-deployment Cloudflare CPU distributions and invocation outcomes remain authoritative.
- The same Unit B measurement produced a 1,126,787-byte stored snapshot, a 38,313-byte create response, and a 347,299-byte page-50 response. Observed process-heap growth from fixture construction through the snapshot-build peak was 4,718,672 bytes against Cloudflare's 128 MiB isolate limit.
- A maximum all-source cache-miss create with uncurated ROR resolution is structurally bounded to 10 Cache API operations, 40 upstream/abuse-guard subrequests, and 50 combined subrequests, below the Workers Paid 10,000-subrequest limit. Server-built membership, complete-versus-partial truthfulness, internal facet membership, source isolation, and immutable snapshot ownership remain unchanged; the public create/page projections avoid returning redundant internal membership arrays.
- Unit C's read-only production audit confirmed application/provider acceptance evidence but no provider-webhook or authorized inbox-receipt evidence; inbox delivery is therefore not claimed. The integrated dialog implementation passed its focused repeated-open, focus, scroll-lock, 320 px mobile/virtual-keyboard/orientation, deterministic multiple-address/subscription, and accessibility checks without changing the Alerts Worker or D1 schema.

### PR #83 review and protected validation — 2026-08-29

- The integrated application candidate was `55df7df2c20e92d3eff243b66ad10c0416292d28`. The [terminal Codex review artifact](https://github.com/mporosoff/grants-scraper/pull/83#issuecomment-5459644970) reviewed predecessor `7b77a12df49b361105c04416789ca1d8dd758ed7` and reported two final P2 evidence-ownership findings. Commit `55df7df2c20e92d3eff243b66ad10c0416292d28` corrected both together, added focused deterministic regressions, and received no further Codex review under the user's explicit no-rereview instruction. Every corrected review thread contains final-SHA evidence and all review threads were resolved before merge.
- The final exact candidate passed [protected run `33246300974`](https://github.com/mporosoff/grants-scraper/actions/runs/33246300974): 788 Python tests, 431 browser contracts, 87 Playwright/accessibility scenarios, 37 frozen queries with zero top-10 churn, 50 frozen-P9 cases with invariant cardinality and byte-identical output, and 23 unchanged no-drift artifacts.
- Protected-main merge `fee9912a47d0b5841d04973a23086e6566546200` passed [post-merge run `33246934811`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934811) with the same 788/431/87 counts, frozen-query/P9 results, and 23-artifact no-drift result.

### Unit A production record

- All six user-connected OpenAI and Anthropic operations use the shared operation-specific strict-schema path. Native provider structured-output controls, local schema validation, bounded malformed-output retry, storage-disabled OpenAI requests, evidence-ID validation, bounded timeouts, and deterministic fallback are live.
- Provider keys remain browser-local and user-managed; they are not committed, placed in URLs, sent through the repository's Workers, or included in telemetry. User-connected provider availability, model access, quota, and cost remain provider/user-account boundaries. Ordinary catalog search, filters, results, and stored provider configuration remain usable after an AI failure.
- [Search-package release `33246934851`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934851) deployed compatibility Worker `60124838-52e5-4db7-8853-cdd5d08702f0` with rollback `e71f9ef0-77ba-49cc-9375-9a289ca3f941`; the protected package gate and real-provider smoke passed before publication and again after Pages propagation. This was an application-asset compatibility release, not a corpus, vector, model-fingerprint, ranking-threshold, or catalog-content change.

### Unit B production record

- The server remains authoritative for immutable snapshot membership, exact-versus-partial status, stable recency/source/award-ID ordering, aggregates, facets, retry successors, and numbered pages. Exact totals are exposed only after every requested source is exhausted; bounded or failed sources retain successful results and disclose `at_least` rather than inventing completeness. Page sizes remain 10, 25, and 50, and each explicit source hydration action remains capped at 25 newly normalized awards for that agency without treating 25 as a total-result ceiling.
- [Award release `33246934839`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934839) deployed version `d375880e-4ec4-4436-b435-2cb41e302124` with rollback `61f565cf-0c1b-419d-903c-6534e4ca72ec`. Pinned Wrangler `4.125.0` reported 404.51 KiB uncompressed, 101.26 KiB gzip, and 8 ms startup. Deployed version metadata ties the release to protected main `fee9912a47d0b5841d04973a23086e6566546200`, the Standard/Workers Paid usage model, and `limits.cpu_ms = 250`.
- The release smoke and a separate bounded production verification returned one complete 629-award snapshot: NSF 79, NIH 517, DOE 33. Health, direct second-page access, investigator facet, expected expiry, per-source batching, Pages equality, and exact/complete source-state checks passed. The observed maximum public response was 472,943 bytes.
- Cloudflare real-time observability on deployed version `d375880e-4ec4-4436-b435-2cb41e302124` recorded a warmed nine-invocation stateless sample with CPU times `0, 1, 10, 12, 12, 13, 17, 19, 72` ms (minimum 0, median 12, nearest-rank p95 and maximum 72). All nine outcomes were `ok`; eight returned HTTP 200 and the ninth returned the expected expired-snapshot HTTP 410. A preceding uncached snapshot create recorded 688 ms CPU and outcome `ok`. Across both bounded samples there was no `exceededCpu`, `exceededMemory`, exception, or other resource-limit outcome. Cloudflare documents that occasional invocations and higher quantiles can exceed a configured CPU limit without an error because the runtime permits [built-in limit flexibility and rollover CPU](https://developers.cloudflare.com/workers/observability/metrics-and-analytics/#cpu-time-per-execution); repeated overruns remain subject to the configured limit.
- Snapshot data remains in the Cloudflare Cache API for 3,600 seconds and is datacenter-local. A shared URL can therefore encounter an expired or cross-datacenter cache miss; the committed submitted criteria rebuild the snapshot coherently before restoring the requested page/facet. That locality is a documented architecture property, not authority for browser-side totals or membership.

### Unit C production record

- The privacy-safe read-only audit confirmed application acceptance and provider acceptance/correlation evidence. It found no provider-webhook delivery event and no authorized inbox-receipt evidence. The closeout therefore does not claim inbox delivery and records no address, token, provider identifier, secret, or message body.
- The live alert dialog locks document/background scrolling while keeping dialog content scrollable, contains and restores focus, handles Escape and repeated opens, preserves verification-pending and recoverable failure state, and remains horizontally contained across the covered 320 px, 390 px, virtual-keyboard, and orientation scenarios. Deterministic multiple-address/subscription and accessibility regressions passed in the exact-candidate and post-merge suites.
- [Alerts workflow `33246934814`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934814) classified `deploymentInputs: []`, skipped secrets, migrations, Worker deployment, and Worker smoke, verified the committed Pages surfaces, and retained Alerts Worker `7b95c810-f46f-47a8-9a8d-6100aa75bb34`. No Alerts Worker or D1 schema change was part of Unit C.

### Deployment classification, remaining limitations, and closeout

- [Pages `33246934213`](https://github.com/mporosoff/grants-scraper/actions/runs/33246934213) succeeded. Production equality checks confirmed the merged Funding Finder, Funded Awards, structured-provider, snapshot, and alert-dialog assets. No refresh workflow ran; no opportunity catalog, vector payload, passage corpus, model fingerprint, Strong/Potential membership, ranking threshold, or source mapping changed.
- JHU remains explicitly disabled/fail-closed because its official unattended routes still require an interactive Cloudflare challenge. ROR remains identity evidence rather than a guaranteed legal-grantee crosswalk. External agency/provider availability can still yield truthfully labeled partial results or deterministic fallback.
- Cloudflare Workflows/Queues evaluation remains a separate future architecture decision. It was not implemented in Units A-D and does not reopen this closeout.
- The historical untracked roadmap and the frozen Unit A/Unit B worktrees were preserved unchanged. Unit D changes only this execution record and the concise pointer in the completed twenty-five-finding plan.

All post-Phase-4 findings `PFH-001` through `PFH-013` are complete with evidence. `PFH-014` remains intentionally separate future architecture work. The post-Phase-4 final product hardening program is closed when this documentation-only Unit D candidate passes its protected exact-head gate, receives its terminal review, and merges without an unrelated deployment.
