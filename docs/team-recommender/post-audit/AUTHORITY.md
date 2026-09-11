# Post-audit implementation and revalidation plan

## Decision and basis

Continue the existing shared-matching correction. Do not restart the profile audit, reopen embedding/model selection, or deploy the failed Stage 3 candidate.

This plan is based on the attached **Shared matching and complete researcher-registry repair** completion report and **Researcher source audit** overview. The reported implementation checkpoint is `5dd8ad38f2954ea2610be075e2afc5f113fce5f4` on `codex/on-demand-team-recommender`, in the existing on-demand-team-recommender worktree. The containing closeout commit may be later. Resolve and preserve the actual local head and subsequent work; do not reset to a previously pushed checkpoint.

The attachments establish reported full-roster corrections and shared-function integration. They do not include the full person audit, implementation map, package receipts, or new runtime source. Review those existing local artifacts to resolve the specific implementation questions below; do not repeat the underlying 158-person research exercise.

The next task is one corrective implementation and revalidation task, with one frozen candidate and one final release-readiness report. Stage 4 deployment remains separately authorized.

## What is already complete

- All 158 canonical researchers have audit dispositions: 154 corrected and four with explicit remaining gaps. All 144 legacy interest-template summaries were replaced.
- SharedTeamEngine reportedly calls the existing `FUNDING_TEAM_MATCHER.create(...).scoreProfile`, with canonical catalog/child projections and unchanged fit rules. The reported real-input comparison has 15,965 identical decisions across 103 current scopes and 155 automatically eligible people.
- Canonical summaries and active evidence now survive the relevant directory and Team Match projections. This is not a request to build another profile store.
- The new shared candidate uses no embeddings. The shared packet builder calculates no teams, and instrumented interactions make no provider calls.
- Existing failed scientific evaluations remain historical failures, not results for the corrected registry and matcher.

## Unchanged product requirements

Use the existing scientific fit function, query interpretation, source evidence and selected-child projection. Do not copy formulas into a competing matcher. Preserve Search and Team Match behavior and their distinct purposes. In particular, the separate existing hosted search/Team Match enhancement must not become a paid Build-a-team fallback.

Generate teams only when a user requests or edits a specific scope. Cached text preparation, immutable lookup structures and recently requested results are permitted; scheduled inventories of complete teams or all-scope score matrices are not serving dependencies.

Preserve presentation, controls, child selection, all admitted researcher access, source-linked explanations, saved/manual behavior, two-to-four-person groups and up to eight useful alternatives without padding. Keep identity, privacy, currentness and stale-evidence protections.

Do not manufacture sponsor requirements or infer capabilities from generic labels. Equal profile standards do not imply equal claim counts. Preserve the four unresolved records and their supported information; do not invent missing expertise or silently change administrative eligibility. The three reference-only researchers remain outside automatic selection even though they now have active evidence.

## 1. Finish the shared candidate: composition, performance and dependency safety

### 1A. Resolve the composition-rule ambiguity before a new quality run

Read the actual implementation behind the report's phrase “positive final member contributions.” Establish whether it means independent evidence of relevance, a distinct useful contribution, or a strictly positive removal marginal under weighted maximum coverage.

If it requires `F(T) > F(T without j)` for every member, inspect how that behaves when independently relevant people have overlapping evidence. Replacing aspect dimensions with tokens does not remove the mathematical possibility that one person dominates every covered dimension and gives a useful second person zero removal marginal.

Do not assume this defect has returned; verify the code and traces. Do not blindly remove every redundancy check. Retain shared person-level fit, a scientific anchor, smallest-adequate group selection and evidence-based redundancy control. Treat marginal coverage as a complementarity preference rather than the sole possible justification for membership. Do not rescue irrelevant people or fill empty slots.

Enumerate actual group outcomes for every bound, current scope, not only the six integration examples. Record the first selection boundary: no admitted person, only one admitted person, absent scientific anchor, redundancy/contribution restriction, valid no-group, or group produced. Do not equate “two admitted people” with a guaranteed useful team.

Inspect representative successes and no-group cases alongside the existing known failure cases. This is implementation diagnosis and regression evidence, not a fresh independent benchmark. No new thresholds, model variants, disciplinary bonuses or call-specific exceptions.

### 1B. Remove repeated work without changing shared fit semantics

The reported warm actions of 1.67–1.95 seconds and initial fits of 0.63–3.94 seconds need attention. Profile the actual execution, separating snapshot reconstruction/validation, catalog preparation, profile normalization, per-scope fit, composition and rendering.

- Validate and compile a coherent immutable ingredient snapshot on adoption, not by repeatedly serializing and hashing its complete contents during every click.
- Reuse the existing prepared shared matcher and canonical profile projections for that snapshot. Preserve the full catalog context used by its vocabulary/frequency logic; do not construct a single-record matcher that changes scoring semantics.
- Compute fits for the requested scope and cache that immutable result by relevant source, registry, matcher and configuration identities. Add/remove normally changes the allowed set and composition, not the underlying source-person fit.
- Refresh currentness cheaply at each action using one decision clock, and immediately reject stale/mixed identities or late responses. Caching is not permission to reuse expired eligibility or stale scientific evidence.
- Invalidate candidate-pool-dependent results when any relevant candidate record changes, not merely when a previously selected member changes.
- Keep caches bounded and teams lazy. Do not precompute every possible team or import offline evaluation teams into the runtime.

Measure again with real data. Retain the agreed post-input and cached-interaction targets; do not declare a slow warm path acceptable by relabeling it cold. Introduce a worker only if profiling shows remaining unavoidable work blocks the main thread; worker complexity is not the first remedy. Do not introduce new embeddings or hosted services for this correction.

### 1C. Audit the release dependency boundary

The regenerated experimental dependencies withhold all 107 affected legacy scopes. The shared package maps 105 of those identities; two remain unmapped. Nothing has yet changed in production.

Trace the release effects of publishing the corrected registry, current adapter, routing index and legacy compatibility projections. Do not merge/publish the registry alone without understanding that it can invalidate legacy team evidence. Do not attach new profiles to old vectors, old claim explanations or the wrong runtime schema.

Preserve source-supported mappings for `332894:superconducting-qubits` and `eere-exchange:DE-TA1-0003589` only if their canonical identities and ownership can actually be established. Do not match them approximately by title or resurrect old evidence to recover a count.

## 2. Verify one frozen corrected implementation

### 2A. Engineering verification

Freeze the integrated candidate after the work above. Reuse the completed audit and focused checks; rerun affected contracts after changes. Run the full configured browser/E2E/accessibility suite once the actual final candidate and routing assets are assembled, with focused correction/rechecks when justified. The old Stage 3 browser evidence does not validate this changed implementation.

Check real parent and child scopes, broad-parent chooser behavior, full/fewer/no-group options, full slots, remove/add/exclusions, saved state, handoff, successive deadline decisions, corrupt/mixed snapshots, delayed responses, profile retirement and profile changes affecting previously unselected candidates.

Measure cold and warm behavior in a real browser, including repeated samples rather than a single cold timing. Report retained and peak memory separately when measurable. Do not interpret the reported 334 MB Node process delta as a browser heap measurement.

Prove that shared scientific-fit decisions remain consistent between consumers using the same snapshot, selected scope and clock. This is consistency evidence, not proof of semantic accuracy. Search regression checks should establish no algorithm drift while permitting intended profile-based output changes.

Prove zero paid calls on prepared Build/edit/options/retry/error/cache-miss paths and zero team loading/calculation during ordinary Search startup. Keep the separate hosted search path distinguishable.

### 2B. One bounded scientific check, not another tuning campaign

Use the corrected profiles and exact complete source evidence for all newly evaluated outputs. Historical machine grades based on materially different researcher text are not transferable labels. Reuse only genuinely identical evidence/question judgments.

First use all available current bound scopes for zero-provider numerical inventories and trace inspection. Then plan one source-stratified semantic check of approximately 24 previously unexposed parent groups, including at least six selected child scopes where a genuinely independent supported inventory exists, and difficult/no-good-match cases. Select and freeze source groups before viewing their quality labels. If independence cannot be established, state that limit instead of relabeling old cases as holdout.

Judge available top suggestions, every member of each evaluated primary group, and the group itself. For alternatives and explanations, predeclare deterministic sampling from outputs that actually exist, before viewing their quality labels. Do not repeat the old approach that locked most audit slots to nonexistent outputs. Preserve source-population abstention denominators separately from returned-output audit denominators.

Use the same existing judge and an evidence-first rubric. A fit decision is not a judge verdict; a faithful quote is not necessarily a faithful claim of applicability. Keep individual relevance, group usefulness and explanation faithfulness separate. Missing or insufficient-information results remain explicit. Do not replace poor cases or rerun unchanged complete-evidence failures for favorable answers.

The former Stage 3 set is now regression/diagnostic history. The profile and algorithm corrections invalidate any claim that it is untouched independent confirmation. Do not discard its failures or claim a new pass by substituting updated profiles into old grades.

Retain the original product targets and report uncertainty and coverage. A small finite check cannot precisely certify a 5% long-run error rate across disciplines. Do not quietly reduce thresholds or require an invented independent-feasibility denominator. If feasibility is unknown, report it as unknown and separately report yield across eligible scopes.

No fresh human packet is automatically authorized: 40 earlier slots have been accounted for. Record any returned answers and their applicability. Do not count unavailable items or unreturned answers as completed review.

## 3. Reconcile actual coverage and prepare the Stage 4 decision

Produce one inventory joining the 107 legacy availability identities, 105 shared-package bindings and the original 50/150 rollout reservations. Report distinct parents/children and these separate states:

- Canonical scope available;
- Corrected ingredients bound and valid;
- Action-current;
- Broad/unselected/otherwise unsupported;
- No shared-fit candidate or no useful group;
- Missing identity/source projection;
- Intentionally withheld because supporting evidence changed.

Do not count a package entry as an available useful team, and do not count a legitimate no-group outcome as a broken loader. The 105 shared bindings are not a completed 150-scope rollout.

Reuse existing canonical source and child preparation. Fix actual adapter omissions rather than reopen independent quote-to-aspect interpretation. Where old rollout reservations are objectively unsuitable, report source-based substitutions for explicit approval without using favorable recommendation outcomes to choose them. Do not silently substitute a smaller 30/81 or 105-scope release for the agreed inventory.

Prepare a reviewed, coherent registry/runtime/adapter/routing release. PRs may be organized for reviewability, but publication must not expose a mixed intermediate state. Use existing dependency and release tooling, not a new deployment framework. Check transitions from the old active package, including schema rejection and stale legacy recovery routes.

Rollback must restore a coherent previously published data-and-runtime release, not combine old matching code with the new registry. Do not label historically retained legacy proposals scientifically revalidated. Warn explicitly about valid coverage that changes or is lost rather than preserving unsupported proposals to retain a count.

Stage 4 activation remains a separate owner decision. If authorized after revalidation, activate the actual qualified 50-scope cohort, verify live operation and zero paid team interactions, then expand to the qualified 150-scope inventory. No precomputed team inventory is introduced at either step.

## Budget and authority for the proposed follow-up

The attached report records zero correction spending and a historical balance of $6.047013 / 95 lifetime request slots after $3.952987 charged. Reconcile the actual existing authoritative ledger before any metered action; do not reset or extend it.

Engineering, cache profiling, profile/source tracing and numerical inventories need no provider requests. A proposed finite ceiling for the single semantic check is $2 and 60 new provider attempts, including failures and retries allowed by the existing lifecycle. At the reported balance this preserves at least $4.047013 and 35 slots for release-related needs. Actual complete packets must be sized and budgeted before dispatch; this is not a guarantee that every desired question fits.

This is a proposed work plan, not a new allowance or deployment authorization. An execution handoff should explicitly authorize the selected paid ceiling and final E2E work, and narrowly scoped trusted-executor changes if required. Preserve existing protections, independent exact-head review and the one cloud-owned accounting route. No provider tournament, automatic retry of terminal paid failures, or new grant of the old balance.

## Completion report and stop

Write one corrective revalidation report in the existing report directory. Include exact resumed/final identities; the resolved contribution-rule semantics; actual all-scope group counts and first-failure boundaries; before/after performance with profiler findings; intact profile audit and unresolved cases; fit parity; scientific observations and missing denominators; final browser evidence; zero-paid interaction proof; complete legacy/105/150 migration accounting; rollback; and remaining money/request capacity.

End with a concrete recommendation:

1. Ready to request Stage 4 approval for an explicitly stated inventory;
2. A named implementation or integrity defect still blocks release; or
3. Implementation is sound but observed usefulness/coverage requires an explicit owner tradeoff.

Do not automatically launch another model-selection or threshold-tuning cycle. Do not publish before the owner has reviewed the corrected candidate, its actual coverage and the final report.
