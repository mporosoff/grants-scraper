# Stage 2 continuation checkpoint — INCOMPLETE / DEFER

Recorded September 9, 2026 EDT / September 10 UTC. Authority: PLAN v2.0, E1, B1, and user continuation C1. This is the requested completion-report path, **not a claim that Stage 2 completed**. Four stages remain. No Stage 3 or holdout recommendation evaluation began.

## 1. Outcome and first failing boundary

The first blocking boundary is the required independent exact-head review of the narrowly authorized trusted executor, PR [#215](https://github.com/mporosoff/grants-scraper/pull/215). Its current head is `8972595625f0d3b9fb4ea44794c65bc03ac3fe7b`. Required Python and browser CI passed. Verification nevertheless found a consequential accounting/recovery defect after one remediation round. The executor was **not merged or dispatched**. There were no actual provider calls, no new vectors, no model judgments, and no completed real A/B outcomes.

The supplied conversation AGENTS instructions say: “If a completed exact-head re-review finds another consequential issue in the same subsystem after one remediation round, do not begin another autonomous fix/review loop. Stop and report the convergence failure…” That condition occurred. The actual repository AGENTS file has a broader rule permitting new bounded rounds for newly confirmed defects. This is a policy conflict: this checkpoint follows the explicit, stricter user-supplied instruction rather than using the repository file to loosen it. AGENTS and protections were not edited. This was **not** an automatic approval rejection, missing dollar authorization, or credential-value access failure.

The independently reproduced remaining defect is precise: response validation can fail after usage is known; if persistence is interrupted after reconciliation to `failed` but before the `terminal` marker, the restored request can be dispatched a second time. A zero-vector response followed by an injected write failure reproduces two fixture dispatches. No real network/provider traffic was involved. The first repair protected cacheless `valid` rows but did not cover this adjacent `failed` path. That incomplete invariant repair is acknowledged, not described as a passed gate.

## 2. Actual identities and preserved prior work

| Item | Identity / disposition |
|---|---|
| Repository | `https://github.com/mporosoff/grants-scraper` |
| Experiment branch | `codex/on-demand-team-recommender` |
| Experiment worktree | `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender` |
| Resumed Stage 2 code checkpoint | `7ae6f1dce6e655a905ebd7d9d0c915cace1ab48b`, tree `755b644056ff8a230b6a125af0962102c1791ae6` |
| Stage 1 checkpoint | `b6f71ae0396bd2670043291bc676ee8af0d222b2`, tree `094156f98f12645ffc4c77015f2b92737c67819d` |
| Execution-time protected main and latest read | `6adca6a795d4ab52e216e2ff7032d0e393db76b1`; protected; unchanged |
| Separate authorized prerequisite worktree | `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/team-recommender-trusted-executor` |
| Prerequisite branch / head | `codex/team-recommender-trusted-executor` / `8972595625f0d3b9fb4ea44794c65bc03ac3fe7b` |
| Starting checkout, untouched | `codex/freeze-nofo-e2e-fixture`, `dabaed933b71fd2572403371ae6c94090ed7cbe9` |
| Existing live package identity inspected | `5927df0f5835c5a06df60d6bedea9667c9aec76994174452e01fa15a2e1642f0`; no new package published |

The experiment began clean, with its actual unpushed Stage 2 files accessible. Exactly one existing worktree owns its branch. No reset, duplicate experiment checkout, main movement, or overwrite of unrelated work occurred. The additional worktree owns only the expressly authorized prerequisite branch. Its working tree is clean at the reported review head. The experiment closeout adds sanitized documents/receipts only; the final response supplies the resulting documentation commit SHA.

The complete actual PLAN, HANDOFF, E1, B1, both prior reports, state, candidate/receipt manifests and applicable AGENTS were read. The original reports remain byte-identical:

- Stage 1 report SHA256: `cee7bf5159d6978bc80439d9289a743517766ab5a9e01f30f07ffa0ca75d4713`.
- Stage 2 engineering report SHA256: `82ddbe9b698044291aa8e442dd62aa34c0b9d6c4445330b7b6aa8e2ca808b351`.
- Original Stage 2 candidate SHA256: `bebc5184763ef5185f6741c4ac7ae677eeb307a81fb21fb3bc137f7621d370be`.
- Original Stage 2 receipt index SHA256: `13ad3b60b1fba8d9db0b4b19d5458171e4fb1a19564026e500c3a22bfed95e61`.

Exact engineering state/candidate/index copies are also preserved in `history/stage2-engineering-*`. The rejected $69 proposal and prior approvals remain historical. C1 was added to the existing PLAN/HANDOFF/state; it does not redefine Stage 2 as an infrastructure phase.

## 3. Trusted prerequisite implementation and review history

Existing protected-main offline execution was inspected first. Its phases, old logical budget and checkpoint namespace belong to the previous qualification experiment, so it could not perform the new task unchanged.

The new prerequisite contains only a manual workflow, executor, experiment-budget helper, focused tests, fixed configuration/public claim allowlists, original empty-ledger bytes, fixed E1/B1 judge prompt/schema and operations documentation. It accepts one content-hashed public JSON packet from a full commit identity as data. It never checks out the experiment with credentials, accepts executable imports/attachments, accepts arbitrary endpoints/models, or loads a recommender runtime. Voyage and Anthropic credentials are scoped to separate intended provider steps. Only credential **names** were inspected; both configured names exist.

The route enforces the single authorization identity, stage/total envelopes, fixed models, scope/profile allowlists, source-span hashes, original public claim revisions/text, bounded packets/results, pre-dispatch request reservations, durable checkpoint restoration, cache identity and one workflow concurrency group. A cloud reservation artifact precedes provider execution, with paired accounting/cache/receipt checkpoints after success or failure. These controls remain unmerged engineering work with the unresolved recovery defect above.

| Review / test event | Actual result |
|---|---|
| Initial prerequisite head `4e6739bdcba6bec8712df886d3566a18951a6763` | 20 focused tests passed; required CI run `34424331894`, Python and browser passed |
| Automatically triggered review | Terminal `Failed` at `2026-09-10T01:10:29.103346Z`, no findings; one retry on unchanged head |
| Completed retry | Review `5161690581`, same full head; finding `3974627455`: cacheless valid request could repeat |
| One bounded repair | Added valid-row recovery stop and interrupted-cache-write regression; 21 focused tests passed |
| Corrected head `8972595625f0d3b9fb4ea44794c65bc03ac3fe7b` | Required CI run `34425407003`, Python and browser passed |
| One exact-head verification | Completed `2026-09-10T01:29:45Z`; finding `3974656336`: cacheless failed reconciliation could repeat |
| Local reproduction of verification finding | Confirmed with two injected fixture dispatches, zero real provider calls; no second repair applied |
| Merge / trusted manual preparation or judging run | None / none |

The initial budget-helper concurrency check also exposed a Windows file-lock release race; a local thread guard was added around the existing process lock before the first PR head. The shared production `offline_spend.py` was not changed. Failed review and test paths are retained in the receipts/history, not erased by later passing tests.

Push/PR/main trigger audit preceded prerequisite pushes. PR pushes run required Python/browser checks. The new workflow is manual-main-only and has no schedule. Existing deployment path filters do not match these files. Dependency comparison added only validation-group dependencies, with no runtime/source/team-generation change. The inspected immutable release plan would choose `noop` while its existing team-generation readiness remains false. **No main merge occurred**, so no new main-push production workflow was caused. The old Sonnet service, historical qualification results/balance, publication, subscriber activity and real profiles were untouched. No experiment branch push was necessary for this checkpoint.

## 4. Readiness findings and real source inventory

### Currentness

The prior implementation already uses the authoritative retrieval/submission policy, with one decision clock per action and refresh between actions. It was not changed in this continuation. A new real-input observation at `2026-09-10T01:34:58.943Z` evaluated all 90 development reservations and their parents without calculating recommendations:

- All 90 cached source records and their parents were current under the ordinary retrieval rule.
- Scope submission states: 69 open, 6 rolling, 7 not listed, 1 invitation required, 7 verify prerequisite.
- **81/90** met both parent and child action-admission policy; **9/90** did not. The additional case is `361526:f-18`, whose child is not-listed but whose parent requires prerequisite verification.

These are policy observations on the actual cached snapshot, not new sponsor verification, source coherence labels, feasible-team labels, or an integrated real prepared-panel test. Existing policy was preserved. No competing date parser was added. Expiration/edit/cache/stale-response behavior still needs real prepared-input integration after the paid prerequisite is resolved; the historical Stage 2 fixture results are not substituted for that run.

### Source provenance and readiness

The new content-addressed inventory is `receipts/c1-real-source-inventory-f4d8898adcff802f.json`, SHA256 `f4d8898adcff802f83479129d316b3fbc5cb8d271f5390a206430567ad8d6299`. It contains identities, original dates, available source/document hashes and representation limits for **90 actual development reservations: 87 parents and 3 children**. The public catalog generation is `2026-09-09T13:58:17.257546Z`. This is a source inventory, **not a ready numerical ingredient package**.

Readiness categories are kept separate:

| Category | Actual evidence / remaining work |
|---|---|
| A: older authoritative representation | Native Grants.gov synopses, retained official NSF page excerpts and deterministic document/child extraction records exist. Their original retrieval/check dates and document hashes can support translation. No missing v2 wrapper alone justifies wholesale re-fetching. **0 v2 receipts were translated here.** |
| B: genuine context, ownership, coherence or currentness gap | Broad-program and single-investigator reservations need honest source dispositions; native child fields need bounded assertions and parent restrictions; the NSF feed excerpt is truncated. The source grouping conflict below is real. **The full coherence/conditions audit is unfinished.** |
| C: missing numerical representation | Compatible exact query/document vectors are still missing. **0 vectors reused, 0 new vectors generated.** General funding-search vectors were not modified. |

Examples of retained evidence, without recommending any team:

- `359696` has an original 1,970-character Grants.gov synopsis about high-resolution human olfactory imaging, with original enrichment time `2026-08-01T11:35:33.536291Z`.
- `344592:ab-0009` (“Modern Optics”) has a deterministic source excerpt tied to page 43 and document SHA256 `c9ab5dd5a95c0f40f68fa4af8b4600c4534e26a15f09a16662e53fb795ba8b24`; its old extraction date is preserved.
- `361526:f-18` comes from native workbook challenge/focus cells. Its assembled “Challenge Area…Focus Area…” summary is **not** a verbatim document quotation. The source cells and their ownership must be represented truthfully.
- `362178` explicitly excludes animal studies and drug-only trials, in addition to its invitation condition. Short positive topic phrases must not erase those restrictions.
- `363612` and `360205` list multiple programs/priority areas. Their existing “specific_parent” reservations do not establish one coherent approach.

The official [NSF DMS/NIGMS page](https://www.nsf.gov/funding/opportunities/dmsnigms-joint-dmsnigms-initiative-support-research-interface) and [NASA HWOICA page](https://nspires.nasaprs.com/external/solicitations/summary.do?solNum=NNH25ZDA001N-HWOICA) were read to check identities/context. These web reads did not produce adopted raw-source extraction receipts. No old retrieval was relabeled as a new verification; no full-notice verification was claimed from a synopsis.

### Grouping correction before recommendation exposure

The development NSF feed entry ending in `nsf22-600` and held-out parent `340828` are the same solicitation `22-600`, despite differing URL forms/title suffixes. `manifests/source-group-amendment-c1.json` records that source-only link, preserves all original manifests/hashes, and withholds the duplicate held-out reservation from independent validation without drawing a replacement. The original 90/90 scope and 30/30 control denominators remain visible. At most **89** held-out source reservations can currently be independent after this known collision; the rest of the successor audit is not asserted complete. Other title-similarity candidates are recorded as unresolved metadata comparisons, not automatically declared duplicates.

No recommendation result, final human label or model verdict was used for this correction. Holdout recommendation results remain unopened and uncomputed.

### Real-input seam defect found

The existing ingredient ID pattern rejects the actual development ID `nsf-funding:https://www.nsf.gov/funding/opportunities/dmsnigms-joint-dmsnigms-initiative-support-research-interface/nsf22-600`. This is recorded in `c1-input-seam-findings.json`; it was not silently renamed, dropped or repaired during this stop. A future bounded nonvisual fix must preserve the canonical source identity and existing transport/path protections.

## 5. Reuse, real input counts and rollout progress

The eligible public registry is `59ccfbe8999eeb4c78441e16daca468c694fc5798b03587c72468390939dc96a`: **155 eligible people**, **427 active claims**, **398 globally distinct exact evidence strings**, totaling **14,194 UTF-8 bytes**, maximum **63 bytes/string**. The earlier 402 count was normalized within-person passage accounting; 398 is a different, global exact-input deduplication count. Claim IDs/revisions/people and all occurrences must remain associated even when an embedding input is shared.

These short public profile evidence phrases are available original registry inputs; they are not newly retrieved long-form external profile quotations or person-to-role certification. Thin evidence and public interest statements must remain uncertain in judging and explanations.

| Reuse inventory | Actual result |
|---|---|
| Cached public source records | 90 development identities inventoried; native provenance inspected |
| Public researcher evidence | 155 people / 427 active claims / 398 unique exact document texts available |
| Compatible numerical rows adopted | 0 |
| New numerical rows purchased | 0 |
| Existing historical offline cache metadata | 481 exact keys inspected in prior reuse inventory; 0 compatible E1 development labels adopted |
| Latest inspected other-task usage | 543 requests / $11.971342; reusable historical work, **not experiment credit** |
| Prepared development inputs / full A/B outputs | 0/90 / 0/90 |
| Derived controls executed on real prepared inputs | 0/30 |
| Prepared rollout scopes | 0/150; original source-selected 100 parent / 50 child reservation retained |
| Rollout recommendation calculations touching holdout | 0 |

No source/profile text was fabricated, no general search corpus was rebuilt, and no pre-generated production team inventory was created. The full eligible directory has not yet been numerically scored with real compatible vectors in this experiment. The source inventory and a merged executor would both be insufficient to close Stage 2.

## 6. Development evaluation, optional components and human review

**No real development numerical comparison ran.** The initial source-stratified wiring check and subsequent 90 scientific + 30 control comparison remain pending. There are no A/B performance values, successful real team examples, measured no-group counts, or independently feasible denominator yet. Missing preparation is not a valid no-group outcome.

The current `coverage-v2.1` remains an engineering candidate: topic/core `.4/.3`, method/context `.5/.5`, anchor `.5`, group `.55`, final marginal `.03`, near-best envelope `.95`, weights `.5/.3/.2`, 2–4 members, maximum 8 useful options, 300,000 coverage-evaluation ceiling, MMR default 0. No development parameter sweep or opportunity-specific exception was introduced. Its parameters have not earned finalist status from real data.

MMR versus no-MMR: **not evaluated semantically on real outputs**. Regularized and Bayesian scoring: **not evaluated**, with no suitable new development labels. Neither failure nor superiority is claimed. No learned probability of human approval is claimed.

Judge: the existing E1/B1 fixed `claude-sonnet-5` prompt/schema and rubric were copied unchanged into the proposed trusted route. Original bounded source/profile evidence, hidden algorithm identities/scores, balanced order, separate explanation faithfulness and exact caching remain required. Labels remain strong / plausible / unrelated / insufficient-information; pair ties and unresolved cases remain allowed. There were **0 separate model-judge requests and 0 model labels**. Ordinary in-task code/source analysis, automated code review, deterministic fixture outputs and semantic model judgments are distinct evidence categories.

Marc Porosoff remains the sole confirmed human reviewer. **0 human items requested, 0 returned**. All **40** slots remain: at most 20 development and 20 final audit. No real development packet was requested because no real recommendation outputs exist; no hypothetical or synthetic packet was charged to Marc. The existing evidence-first packet format and preselection are preserved, with inability-to-assess and no automatic replacements. Judge agreement/systematic error estimates are unmeasured.

Original acceptance targets stay visible and unrun: top-five reasonable precision >=80%; unrelated automatic-member occurrences <=5%; useful primary group >=80%; yield >=85% on independently feasible scopes; matched-size complementarity improvement without unrelated-rate harm. Model estimates, actual human observations, insufficient information, all-case denominators and grouped uncertainty must be reported separately when evidence exists.

## 7. Validation, presentation and realistic resources

- The prerequisite's 21 focused executor/accounting checks passed before verification; required exact-head Python/browser CI passed. The new negative reproduction demonstrates a defect those tests missed. The prerequisite is **not validated for merge**.
- A fresh preservation check compared **87** tracked assets/entry pages/AGENTS files with Stage 2 code checkpoint `7ae6f1d…`: **0 changed**. Presentation and runtime were unchanged by this continuation. The earlier presentation-function freeze remains historical supporting context, not a new full browser test.
- The real currentness observation covers 90 actual sources/parents with a network trap and zero recommendation calculation. It is not a full renderer/add-remove/cold-cache integration test.
- No full E2E, Playwright or accessibility suite ran. No duplicate full CI suite was manually launched for an unchanged head.
- Actual distinct profile-text encoding is measured above. **Real vector-package size/compression, numerical latency, cold/warm build/edit/retry/error/cache-miss behavior, browser heap and physical-device latency remain unmeasured.** No synthetic gzip ratio or loader cap is used as evidence that the 150-scope inventory fits.
- Zero **actual experiment provider traffic** is established by the unchanged empty ledger and absence of manual executor runs. This does **not** constitute the required real prepared-scope interaction proof, which remains pending with its missing package.

Supporting receipts: `c1-preservation-check.json`, `c1-real-currentness.json`, `c1-prerequisite-review.json`, `c1-second-review-reproduction.json`, `c1-input-seam-findings.json`, the content-addressed source inventory and `c1-budget-reconciliation.json`.

## 8. Single $10 ledger and finite remaining execution plan

Authorization: **`on-demand-team-offline-v2-20260909`**. Existing ledger bytes are unchanged, SHA256 `0835f7b7017d6655d3de13395c3d5ee8a94342a3ba1ac9115e652bfab4c73f9a`. No cloud spending copy was initialized and execution ownership was not transferred. The seed in the proposed trusted route is the exact existing ledger, not a second allowance.

| Budget item | Actual USD |
|---|---:|
| Prior spend attributable to Stages 1–2 | 0.00 |
| This continuation's provider spend | 0.00 |
| Outstanding reservations / provider calls / tokens | 0 / 0 / 0 |
| Total remaining within the one authorization | 10.00 |
| Maximum remaining spend through Stage 2 | 6.00 |
| Minimum protected for Stages 3–4 | 4.00 |
| Historical other-task spend (separate; no credit) | 11.971342 |

The existing finite B1 plan remains a ceiling, not a quota. Prices were checked against official [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) and [Voyage pricing](https://docs.voyageai.com/docs/pricing) on September 9 EDT: Sonnet 5 $2/M input and $10/M output; Voyage 4 lite $0.02/M input. Judge reservations conservatively use $2.50/M input. No new provider or paid extraction is proposed.

| Remaining work envelope | Conservative ceiling |
|---|---|
| Reuse public sources/profile evidence and compatible purchased assets | Zero provider spend for local validation/reuse; actual compatible vector cache hits currently 0 |
| Missing embeddings only, including canaries/retries | <=80 attempts, <=3,840 unique rows, <=10M reserved input tokens, <=$0.20 |
| Stage 2 fixed-judge development | <=350 requests including <=10 retries; <=1,433,600 input / 179,200 output tokens; <=$5.376 |
| Stage 3, only after separate approval | <=260 requests including <=10 retries; <=1,064,960 input / 133,120 output tokens; <=$3.9936 |
| Stage 4 | Planned zero provider calls |
| Entire modeled envelope / unallocated inside $10 | $9.5696 / $0.4304 |

Per packet: at most 12,000 conservative input tokens (serialized UTF-8 byte bound plus framing), 512 output tokens, with aggregate envelope enforcement. Actual full packets have not been assembled/measured, so this is not a claim that every substantive evidence item fits. Decisive evidence must not be cropped. No unknown request may be refunded/reset or repeated automatically. No increased budget is requested.

## 9. Required next action and proposed later scope

**Recommendation: DEFER advancement. Stage 2 remains incomplete. STOP FOR USER REVIEW.**

The smallest first prerequisite is a new explicitly resumed bounded correction round for PR #215's already reproduced failed-reconciliation/cache-loss path, preserving head `8972595…`, both review findings and all existing tests. Cover the complete cacheless prior-state family, obtain the required exact-head verification and CI, then perform the protected merge and manual dispatch only if clean. The earlier $10 and narrow-executor authority are recorded and are not being requested again; the checkpoint concerns the supplied review-convergence rule.

After that boundary, continue **Stage 2**, not a new scientific phase: translate adequate native provenance, address genuine source gaps and the URL-shaped ID seam, finish grouping dispositions before scoring, build real compatible development ingredients through the one authoritative ledger, perform the source-stratified sanity check and full 90+30 comparison, assess real MMR and same-label local scoring variants where justified, provide the one compact real development human packet, and run focused real-input integration/resource/zero-paid-interaction checks. Preserve unsuccessful outputs and every missing denominator. Freeze one actual development finalist and at most one simpler fallback only when real evidence supports that designation.

No scientifically selected finalist or fallback can honestly be frozen at this checkpoint. The unchanged engineering candidate and fixed judge protocol identities are recorded in `stage2-continuation-candidate.json` for resumption.

Proposed Stage 3 remains conditional on completing Stage 2 and a separate user approval: freeze exact source/registry/vector/scorer/threshold/adapter/judge identities and decision rule; respect the shared-source holdout quarantine; evaluate the preserved 90+30 reservation with all missing/unknown denominators; use no more than the $3.9936 judge envelope within the at-least-$4 later reserve; request at most the 20 separately preselected final human items; run the specifically authorized browser/E2E/accessibility/resource validation then. No tuning against final human or holdout outcomes, deployment, cohort publication, subscriber action or old qualification-service enablement is included in this checkpoint.
