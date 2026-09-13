# Phase 1 contextual assessment — completed audit

September 13, 2026. **PHASE 1 CLOSED — implementation and the two planned audit requests completed; observed LPS evidence supports consideration of the next phase.** Release quality is not established, and no next phase or deployment is authorized.

The accepted model results are **one strong and two plausible individual matches; a plausible primary group; and three faithful explanations**. All seven original questions now have retained, validated answers. There are no missing verdicts and no new human judgments. These are separate kinds of evidence, not a seven-out-of-seven accuracy score.

The [previous incomplete Phase 1 report](phase-1-contextual-assessment-closeout.md) and [original Option 1 report](contextual-stage-b-option1-integration-repair-report.md) are preserved byte-for-byte. This report completes their missing audit; it does not rewrite their failures or infer the answers discarded by those attempts.

## 1. Exact work, review and execution identities

|Boundary|Actual identity|
|---|---|
|Repository / product branch|mporosoff/grants-scraper; `codex/on-demand-team-recommender`|
|Product worktree|`C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender`|
|Starting report checkpoint|`ea11efdc975c41f31a874090c62cb52b54060e6d`|
|Preserved tested application|`1a1bdfc2d4b5a68afa3cc3603177903d8d7de05a`|
|Protected main before repair|`6e054ac57308a72d3e4efb99bbe66571418ea4e8`|
|Helper branch / existing worktree|`codex/contextual-phase1-reference-repair`; existing `contextual-team-demand-service` worktree; prior helper branch retained|
|[PR240](https://github.com/mporosoff/grants-scraper/pull/240) reviewed head|`0fd6ca232dd8c582fc90764caafc1747707cc704`|
|Independent exact-head review|Completed clean at 18:45:16Z; [summary 5655289536](https://github.com/mporosoff/grants-scraper/pull/240#issuecomment-5655289536), configured no-findings reaction `503597275`; unchanged head, no submitted/inline findings or unresolved review threads. One automatic review; no duplicate.|
|Required CI|[34775421829](https://github.com/mporosoff/grants-scraper/actions/runs/34775421829), Python and browser green on that head|
|Protected helper merge|`3ebe0466c202903b44c099d2b0803e2436f04e37`, 18:46:15Z; exact-head guarded squash, no bypass|
|Exact product reconciliation|`1528d18ca1e22f65196823aa8b93387cf686fb20`; only the six reviewed helper/config/test/doc files cherry-picked|
|Pre-dispatch product lock commit|`197c038aa9039017535980753fa9e00a65903c3f`|
|[Actual audit run](https://github.com/mporosoff/grants-scraper/actions/runs/34775743077)|`34775743077`, attempt 1, successful, executing protected-main merge above|

The local documentation commit containing this completion report follows `197c038…`; resolve it with the report's git history. It is distinct from the reviewed helper and tested application identities. The experimental branch was not pushed or merged. Private previews, outputs, failed reviews, prior branches, ledgers and all earlier reports remain intact. AGENTS was not changed.

Frozen scientific inputs:

- LPS scope `332894`, original base graph `a9ce47f194e303b6d4173bf4a8d28685e597df2e31144f45d1d9ce44acbbeb64`.
- Primary members, in original order: Blok `urh-000091`, Huang `urh-000099`, Singh `urh-000126`.
- Registry `60169651eaff43c75e0eccd12167371d8131b76ed67592eaed18d3689d188126`.
- Approved input file `d72ba3a24200133a6fdfed0b33d3d72b3c22462499a7932e5b01b5de14ba23f9`.
- Experimental release `d91e57fa512745c4d8154e2b7ebadc4508dbdae082a1937297edd759a5179055`.
- Source identity `b898f42c6b93f3450da1169b595281fc578bb2c9c48173448d07d67d06a5b2f3`, [official call](https://www.grants.gov/search-results-detail/332894), [notice PDF](https://grants.gov/grantsws/rest/opportunity/att/download/350603).

## 2. What failed and what was corrected

The first failed check (`b12fa7fbde6e45069d14358b6c73ee79`, run 34770252997, $0.016528) returned a complete reason longer than the old 60-character bound. PR239 corrected capacity, but its group check (`53020ccfc01749f3b7971c2ca442102f`, run 34774192296, $0.020762) then failed per-question citation validation. The failed raw answer and offending citation were not retained. Their precise grades, citation spelling and whether the citation was unknown or owned by another person remain unknown; they were not recovered or reconstructed.

The complete contract audit identified the mechanical mismatch: the provider was allowed to emit any citation string, while the subsequent local validator required a specific scope/person/owned-claim identifier. V3 now sends a `verdicts` object keyed by each exact question, with that question's permitted citation identifiers enumerated directly in the provider schema. A question cannot cite another person's evidence. The group may cite any of its three members. The accepted object is deterministically normalized into the existing canonical array cache without changing any answer or reason. Invalid citations now produce existing bounded schema-path diagnostics; there is no new raw-response or hidden-thinking retention.

Both requests retain Sonnet 5, thinking disabled, 2,048 output tokens and the 32,768-byte complete-response acceptance bound. Complete multi-sentence/Unicode reasons survive unchanged. No clipping, guessed reference, relaxed ownership, partial completion or favorable rejudging was introduced. Exact question keys, enums/types, completion and evidence ownership remain strict.

**The original scientific messages compare byte-for-byte equal.** Full retained call science and governing conditions, all three stored summaries and all nine active claims remain supplied. Only mechanical schema/format wording changed; the scientific rubric file was not edited. Group/person grading did not receive desired answers, old verdicts or numerical scores. The separate explanation batch retained the exact original contributions, quotations, limitations and unconfirmed-coverage wording.

The [resumed owner authority](../contextual-stage-b/PHASE1-REFERENCE-REPAIR-AUTHORITY.md) explicitly requested diagnosis/rerun and completion. Its finite [v2 lock](../contextual-stage-b/phase1-check-execution-lock-v2.json) binds all 660 preceding ledger rows and the exact completed reference failure, including logical key, body, usage and charge. It allows one further group replacement and the first explanation request. V1 and both failed charges remain history. Old check purposes cannot claim new requests; these two new purposes can each claim once. Lost, failed or uncertain paid requests do not automatically reopen. Both complete successful caches remain reusable.

The new rerun adds one group attempt to the earlier Phase 1 plan: three Phase 1 attempts in total, including the already failed one. It adds **no dollar allowance**: all three fit the original $0.25 Phase 1 ceiling. The minimum remaining lifetime-slot reserve accordingly became 28 rather than 29, explicitly recorded before dispatch. No old unused allowance or purchased-asset credit was added.

## 3. All seven accepted answers, verbatim

These are **model-sourced** checks from the named trusted run, not human assessments or ordinary in-task analysis. References below are the exact returned identifiers, linked to their retained public source attribution. They are not claims of newly fetched faculty pages or independent confirmation of every sentence. Each request included the complete corresponding stored evidence.

### Individual relevance and primary-group usefulness

**`group` — Blok–Huang–Singh primary group: plausible**

Evidence reference: [`urh-000091`](https://www.sas.rochester.edu/pas/people/faculty/blok_machiel/index.html).

> Person-1 (superconducting circuit QED, qubit encoding, quantum sensing) is a strong fit for LQC qubit development thrusts; person-2 contributes non-von-Neumann/Ising-machine architectures and classical-overhead reduction relevant to associated quantum information technology; person-3 contributes first-principles modeling of topological and superconducting materials relevant to qubit material design. Each has a plausible-or-better individual link to the call, and the trio could plausibly be discussed together as covering qubit devices, materials, and supporting classical architecture, though no direct evidence shows they have worked together or that architecture/materials work was aimed specifically at qubits.

**`person-1` — Machiel Blok: strong**

Evidence reference: [`urh-000091-c001`](https://www.sas.rochester.edu/pas/people/faculty/blok_machiel/index.html).

> Direct, specific match: superconducting circuit QED with Josephson junctions and encoding quantum information in nonlinear oscillators is precisely the qubit development/quantum computing focus the LQC BAA solicits, with additional quantum-sensing relevance (a named secondary interest).

**`person-2` — Michael Huang: plausible**

Evidence reference: [`urh-000099-c001`](https://www.hajim.rochester.edu/ece/people/faculty/huang_michael/index.html).

> Non-von-Neumann optical/mixed-signal computing (including Ising machines) and reducing classical-component overhead are reasonable topics adjacent to the BAA's interest in 'reducing the overhead of classical components in quantum information technology,' though the person's work is not shown to be about qubits or QIS specifically, making this plausible rather than strong.

**`person-3` — Sobhit Singh: plausible**

Evidence reference: [`urh-000126-c002`](https://www.hajim.rochester.edu/me/people/faculty/singh_sobhit/index.html).

> Study of topological phases, superconductivity and polar/ferroelectric materials via first-principles methods is a reasonable contribution to material selection questions named in the BAA (e.g., 'material selection' as a limiting factor for qubit performance), but no direct link to qubit devices or QIST research is demonstrated, so this is plausible rather than strong.

### Explanation faithfulness

**`explanation-1` — Blok explanation: faithful**

Evidence reference: [`urh-000091-c001`](https://www.sas.rochester.edu/pas/people/faculty/blok_machiel/index.html).

> The claim directly states use of lithographically defined superconducting circuits to manipulate microwave quantum states, and the assertion faithfully paraphrases this as addressing qubit device design and control, which is consistent with the LQC's stated interest in device design/control limits. The qualification that this is not a capability certificate is preserved.

**`explanation-2` — Huang explanation: faithful**

Evidence reference: [`urh-000099-c003`](https://www.hajim.rochester.edu/ece/people/faculty/huang_michael/index.html).

> The claim supports 'develops practical architecture solutions informed by device and circuit behavior' verbatim as cited, and the assertion accurately frames this as a classical-computing optimization method with an explicit limitation noting no evidenced application to quantum systems specifically, which matches the retained evidence and avoids overclaiming.

**`explanation-3` — Singh explanation: faithful**

Evidence reference: [`urh-000126-c001`](https://www.hajim.rochester.edu/me/people/faculty/singh_sobhit/index.html).

> The claim supports the description of DFT and theoretical analysis for structure-property prediction, and the assertion appropriately labels this as a transferable method while explicitly noting the lack of direct application to qubit gate fidelity, consistent with the retained evidence and without asserting demonstrated capability in that specific domain.

Accepted denominators: **3/3 individuals** (1 strong, 2 plausible, 0 unrelated, 0 insufficient-information), **1/1 primary group** (plausible), and **3/3 explanations** (faithful). No question is missing. This is not a precision estimate, a calibration claim or seven independent observations. A group-usefulness judgment does not override any member grade.

The practical interpretation is limited: Blok has a direct qubit-related connection; Huang's classical architecture and Singh's materials modeling are plausible transfers with explicitly unproven qubit-specific applications. The judge accepted those limitations as faithful explanations. This supports discussing this particular exploratory group, not certifying qualifications, equipment, willingness, prior collaboration or proposal success.

## 4. Actual requests, tokens and one ledger

Same authorization: `on-demand-team-offline-v2-20260909`. Existing prices were rechecked September 13 at [Anthropic's official table](https://platform.claude.com/docs/en/about-claude/pricing): Sonnet 5 $2/M input, $10/M output. No new model/provider, embedding, source extraction, paid probe or provider prompt-cache creation.

|Check|Wire bytes / conservative input bound|Output ceiling|Reserved USD|Actual input / output / thinking|Actual USD|
|---|---:|---:|---:|---:|---:|
|Group + three individuals|21,224 /22,248|2,048|0.064976|7,784 /699 /0|0.022558|
|Three explanations|22,239 /23,263|2,048|0.067006|7,893 /446 /0|0.020246|
|Total|||0.131982|15,677 /1,145 /0|**0.042804**|

Both returned HTTP 200, `end_turn`, valid complete answers. Elapsed provider times: 10.007078 seconds and 6.140190 seconds respectively. These are offline-check timings, not application inference or browser performance measurements.

- `cb-p1-reference-group`: request `21259d12a5554cb3a9aed1aab8fad080`, logical key `2891d4a8ee79131c21ccda4d2c3094f5a71ee02f7d024eaf28dddf165996f621`, body `868474ab21bb7c87388a695197cc94d0b835cb23fec0b28315a4dedf9b00455d`. Explicit `repair_of=53020ccfc01749f3b7971c2ca442102f`; that completed failure remains charged.
- `cb-p1-reference-explanation`: request `0895738a761d44fab93ddcf0658725d3`, logical key `653e930b7b874cbf143429853f54203c8695a9a81efe2617e5db0f24b5c0b469`, body `2c00e41aa7679c6b17737691a3b49c64b563569ff691e3ba7b39c37b1c882203`. First explanation execution; no repair ancestor and no prior explanation grade.

|Accounting boundary|USD|Attempts|
|---|---:|---:|
|Starting experiment, including all prior failures|5.779176|660|
|This continuation, both valid|0.042804|2|
|Cumulative experiment|**5.821980**|**662/690**|
|Outstanding reservation|**0**|0|
|Remaining experiment balance|**4.178020**|**28**|
|Entire Phase 1, including prior reference failure|**0.063566 /0.25 ceiling**|**3**|

The earlier $0.016528 Option 1 failure remains in starting lifetime spend, separately from Phase 1's $0.020762 failure. Historical purchased work is reused work, never a refund. The dollar ceiling was not renewed across retries or sessions. The unspent balance supplies no automatic authority for another check or next phase.

Authoritative cloud owner: **34775743077**, state artifact **10323207152**, reservation **10323406505**, results **10323187316**. Ledger SHA256 `03b81d8af0369617f1f87b0cf573c22d34dd1f30d6795869648fe7e1bf201b74`; checkpoint SHA256 `7ff91ac743a74d28de323ec59dd14956059b74b3b2e22601dfd83f7df4a62981`. All **1,304 file hashes** verified. All 660 original request rows and every previous cache/receipt byte are unchanged; there are no duplicate IDs or logical keys. Each new valid answer has its exact durable cache and receipt, independently revalidated read-only three times (zero provider calls). Local artifacts remain read-only mirrors. Full [accounting](../contextual-stage-b/phase1-reference-accounting-v1.json) and [accepted answers](../contextual-stage-b/phase1-reference-verdicts-v1.json) are retained.

## 5. Actual checks and unchanged application

- **78 focused Python checks passed** on helper and again after exact product reconciliation. These overlap; they are not 156 independent tests or scientific samples. The new reference suite contains 16 cases, including all question-specific citation enums, both converted provider schemas, exact input/prompt identity, full reason/cache round trips, missing/wrong question/reference/completion rejection, legacy-purpose closure and ledger lifecycle tests.
- Required exact-head CI: **1,407 Python tests and 784 Node/browser contracts passed**, including frozen-query and no-drift checks. Post-merge required CI also passed. No duplicate full-suite invocation was commissioned locally.
- Crash fixtures cover eight request persistence boundaries, with three restorations each and **zero duplicate fixture-provider dispatches**; exact success reuses cache, lost/failed/unknown requests stay terminal/recovery-required. Negative fixture grades still complete the explanation batch. Earlier valid answers survive a later technical failure.
- Initial local reference-suite failures were fixture harness errors: its replacement plan mock was not activated, its added synthetic history row lacked provider/stage fields, and a refusal assertion expected the wrong exception family. These were corrected before the PR. The failed logs remain private; no provider dispatch was involved.
- Fresh read-only Node checks reproduced **all four original graph IDs, primary members and option lists exactly**, using the original comparison clock `2026-09-13T17:00:59.587Z`. Candidate reachability, whole-pool invalidation, expiry and full-slot remove/re-add remained passing, with zero network/provider route.
- HTML, assets, registry, generated data and Worker files have **zero diff** from tested application `1a1bdfc…`. The earlier **117/117 Playwright** result, including 25 accessibility scans and its stated manual/incomplete limitations, is reused only for those unchanged bytes. Artifact SHA256 `f1c8c5fe2b5cc90784369476d75451bc9c43c26f3d59255fbd847b12aeacf7a0`. No E2E rerun or new physical-device/performance claim.

The original application's demonstrated positive LPS path, second option, Veterans negative, adjacent-only Boyd extension, joined job/status reuse, cached visitor and manual/edit/Team Match paths remain **reused** evidence from the Option 1 report. No scope workflow, graph generation, extension assessment or paid click was replayed. Previous latency and memory observations retain their original environment/limitations.

## 6. Production effects, scientific limits and closeout

Only the offline helper/configuration/tests/instructions merged to protected main. Automatic [immutable-release run 34775652211](https://github.com/mporosoff/grants-scraper/actions/runs/34775652211) succeeded with generation, assembly, publication, Pages and live-publication verification **skipped**. No new Worker deployment occurred: the last intake deployment remains run 34769173566 /PR238. No permissions, secrets, Access rules, origins, schedules, subscribers, real profiles, catalog publication, activation or old service states changed. No live rollback was required or performed.

The judge is the same model family as generation, this LPS source was already exposed, and this is one retained three-person primary group. The check is a separate offline execution, not independent human or multi-source validation. No new human packet or judgment occurred. The second team option, Cardenas/Boyd adjacent decisions, Veterans' full-directory feasibility, other original scopes and universal quality targets remain unassessed by these seven questions. Faithful explanation wording is separate from proving the proposed application will succeed.

No scientific selection rule, threshold, profile, source meaning, contribution or explanation changed after grading. Historical Stage 3 failures remain failures; they are not relabeled by this limited positive audit.

Deferred release work remains: a wholly uncached revised interpretation path; broader independent usefulness evidence; production-shaped access and spending controls; actual rollout routing/package and resource limits; and coherent release/rollback proof. These are later owner decisions, not work silently launched here. Deployment itself cannot resolve scientific generalization or unmeasured performance.

**PHASE 1 CLOSED — implementation and the two planned audit requests completed; observed LPS evidence supports consideration of the next phase.** The seven-answer audit is complete. The group is plausible for a scientific conversation with two explicit transfer limitations. This is not release qualification or deployment approval.

**STOP FOR USER REVIEW.**
