# Stage 2 D2 ranking revision — completed automated work; REVISE

September 10, 2026. This is the new D2 closeout, preserving the Stage 1, Stage 2 engineering, completion, final and D1 diagnostic reports. D2's bounded automated sequence is complete. It recovered useful groups, but **does not justify a quality-qualified finalist or advancement to Stage 3**. Missing human answers are not the reason for that recommendation. No holdout recommendations, researcher enrichment, Stage 3 or recommender deployment occurred.

The strongest remaining demonstrated problem is person-level scientific discrimination: relevant and unrelated people still overlap in the numerical features, and a favorable group judgment can coexist with an unrelated member. The new absolute member rule reduces some weak alternatives but does not meet the 5% unrelated-member target. Existing profile context and the compact learned scorer did not earn adoption. These results do not authorize another tuning or labeling cycle.

## 1. Checkpoints, trusted execution and production

Repository: `mporosoff/grants-scraper`. Worktree: `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender`; branch: `codex/on-demand-team-recommender`.

| Identity | Exact checkpoint |
|---|---|
| Preserved D1 code/data | `f148325cc456e8d26d8d71c0541a2b3aad470a5c` |
| Actual resumed D1 report/state head | `ec9c717cf1943ac68be4b1a4ba453bbb29dbd931` |
| D2 diagnosis/protocol/context packet frozen | `15f1f5397902c3862a88745ab6a601949d4bb8f9` |
| D2 runtime, ingredients, outputs and judge packet frozen before new grades | `ed303ab367ccb2f0bec3f0e62acf3ed45e9809a6` |
| Trusted helper PR | [#221](https://github.com/mporosoff/grants-scraper/pull/221) |
| Helper initial head | `cd8b195c02a8a7ec07be7e28ee297cbd25bfa55e` |
| Helper corrected, reviewed head | `c93ecdf4cdfb84388a32fe51de76778cdc37e4ec` |
| Protected merge / execution code | `c9491b8ffb225a49d8fadb9d2f735ab96cd1e0f8` |
| Context / judging runs | `34508950140` / `34510982749` |

The closeout commit containing this report and state is resolved with `git log -1 --format=%H -- docs/team-recommender/reports/stage-2-ranking-revision-d2-report.md`; this avoids a self-referential commit hash. The candidate manifest binds exact runtime and data bytes to the pre-judgment code commit above. No runtime tuning occurred after the new grades.

The existing unique helper worktree was continued, and its two commits were cherry-picked into the experiment without resetting it. The unrelated root checkout (`codex/freeze-nofo-e2e-fixture`, `dabaed933b71fd2572403371ae6c94090ed7cbe9`) and the separate main checkout were preserved. No duplicate worktree or recommender merge was created. Original reports, failed reviews, failed paid requests, splits and budget checkpoints remain history.

PR #221 adds only the deterministic frozen-registry context representation and bounded D2 execution/item protection. Initial review `5170175615` found that a previously paid judge item or embedding row could be rebundled into a different request. Findings `3981676214` and `3981676219` were consolidated into one lifecycle/item-identity repair. Exactly one verification review followed. Terminal clean comment `5622793234` covers corrected head `c93ecdf4...`; required Python/browser CI `34508020881` passed at that head. Corrected threads were resolved afterward and protected merge completed at 17:32:38 UTC. This was one focused repair, not an unbounded convergence loop. See [the helper receipt](../receipts/d2-trusted-helper.json).

The durable invariant now covers logical item intersection across rebatching as well as exact request identity. It preserves the historical map of 162 D1 requests / 332 submitted item occurrences, including paid failures. Exact complete request caches remain reusable. A reconciled request without its expected result, an invalid paid response, or an uncertain dispatch cannot become a new automatic attempt. The helper checks the entire packet before dispatch and rechecks inside the shared ledger lock. Crash/restore/rebatch/concurrent fixtures cover the persistence boundaries and produced **zero duplicate fixture dispatches**. All 336 actual lifetime requests still have attempt 1 and unique request keys; earlier ledger rows were unchanged by the two D2 runs.

Push/PR/merge triggers were audited. The helper changed the validation dependency group only; workflow permissions, schedules and release dependencies were not broadened. Main push planner `34508859600` succeeded with generation, assembly, validation, Pages, publication and live verification skipped. No recommender runtime, activation manifest, production catalog, subscriber mail, real profile or old Sonnet service was changed on protected main. The local experimental runtime remains unactivated.

## 2. Diagnosis before revision

The exact D1 implementation reproduced its saved options and top-five lists on all 35 prepared scopes at `2026-09-10T12:00:00Z`. Reproduction SHA: `abda07d0a64a85955c885953dc315268f353eec73c1d630d19139b8eb00faf86`. The clock is fixed for the comparison; actual interaction tests refresh one authoritative decision clock between actions.

| Hypothesis | Finding and limit |
|---|---|
| Cross-scope .45 cutoff rejects plausible pools | **Confirmed mechanically.** Seventeen scopes fail only this floor after pool/anchor checks; 15 contain already model-judged reasonable admitted people. Olfactory imaging's upper bound is .4207904. This establishes an uncalibrated exclusion, not that every excluded pool deserves a team. |
| Strong member carries weak partners through maximum coverage | **Confirmed as a numerical mechanism; semantic causation only partly attributable.** D1 member quality mattered only at coverage ties to six decimals. Eight of 20 unrelated option-member occurrences had zero removal marginal; 12 had positive marginal. Restoring a universal positive marginal would neither distinguish usefulness nor preserve legitimate overlap. |
| Scorer and judge receive different existing context | **Confirmed.** D1 scores short evidence vectors; its judge packet already contains associated claim labels/types and full unchanged research summaries. This is not an identity error or evidence-enrichment requirement. Whether context repairs quality is an empirical question addressed below. |

Aspect cosine, core cosine and lexical overlap were traced separately in [the before-edit diagnosis](../receipts/d2-before-edit-diagnosis.json). D1 member-score medians were .5415 for strong, .4238 for plausible and .4529 for unrelated judgments. Their overlap directly limits a universal raw-score interpretation. No finding supports interpreting coverage as the probability of a complete team.

## 3. R0/R1 and selection ablations

[The predeclared D2 protocol](../EVALUATION_PROTOCOL_D2.md) fixes one R1 representation. Each exact retained passage gets sorted/deduplicated existing `{claim_type,label}` context plus its unchanged evidence; each nonempty existing summary is encoded once per person. UTF-8 canonical JSON preserves field values. There are no names, departments, inferred descriptors or generated factual additions. Missing summaries remain missing.

R1 uses `.7 evidence cosine + .2 associated-context cosine + .1 summary cosine`, renormalizing .7/.2 when the summary is absent. Uplift is capped at original evidence cosine + .05; reductions are allowed. Original evidence admission and the scientific anchor remain required. A context vector cannot manufacture a confirmed role. R0 uses the original evidence vectors.

With **unchanged D1 selection**, R1 returned the same five group scopes and 40 options; the accessible candidate pool was identical. Its top-five lists had 99 graded of 107 occurrences: 74 reasonable, 20 unrelated, five insufficient, eight missing. R0/D1 had 106 graded: 75 reasonable, 26 unrelated, five insufficient, one missing. Observed-source macro relevance was 73.125% versus 70.2083%. The observed-only paired difference was +2.9167 percentage points (source-cluster interval +0.4 to +6.0417). Uneven missing labels, including seven unpurchased R1-only items and one historical paid failure, prevent interpreting this as a complete-label or independent benefit. No additional campaign was bought to resolve that diagnostic uncertainty.

Selection was then tested first on fixed D1 matrices, followed by the combined R1 matrices. The table preserves the pre-new-judgment counts; later judgments do not overwrite these selection observations. “Reasonable/unrelated/missing” refers to option-member occurrences, not independent people.

| Representation / automatic scorer | Alternative rho | Groups | Options | Reasonable | Unrelated | Missing |
|---|---:|---:|---:|---:|---:|---:|
| R0 fixed | .90 | 8 | 40 | 61 | 16 | 3 |
| R0 fixed | .95 | 8 | 32 | 51 | 10 | 3 |
| R0 regularized | .90 | 7 | 27 | 40 | 11 | 3 |
| R0 regularized | .95 | 7 | 26 | 38 | 11 | 3 |
| R1 fixed | .90 | 8 | 25 | 38 | 10 | 2 |
| R1 fixed | .95 | 8 | 23 | 34 | 10 | 2 |
| R1 regularized | .90 | 8 | 32 | 46 | 10 | 8 |
| R1 regularized | .95 | 8 | 29 | 40 | 10 | 8 |

The .95 R0 setting loses 16.39% of already-judged reasonable occurrences, exceeding the predeclared 10% tradeoff; .90 was retained. Combined R1 fixed scoring had four known unrelated primary members versus R0's three, the same group yield and fewer reasonable alternative-member occurrences. For olfactory imaging it substituted individually unrelated Jong-Hoon Nam for plausible James Zavislan. R1 therefore **was evaluated and not selected**, without claiming it is universally inferior. Its new vectors are retained as reusable experimental assets, not loaded by the chosen runtime.

The frozen D2 candidate is R0 fixed quality. Every automatic member must satisfy `q=.7*maximum scientific aspect cosine + .3*maximum scientific whole-call cosine >= .50`. The old .45 group floor is removed. Within a .95 near-best coverage envelope, minimum member quality, then mean quality, then coverage, then stable identities determine order. Alternatives retain at least .90 of the best minimum member quality for their size. The original evidence admission remains broader for candidate/manual access. Uniformly poor pools fail the absolute member gate; the best person in a poor pool is not normalized into a strong match.

The objective remains `F(T)=sum_i w_i max_j r_ij`, with aspect/core/lexical utility weights .5/.3/.2, original topic/core floors .4/.3, evidenced-method/context floors .5/.5 and a .4 scientific anchor. Scoped passage nonredundancy uses Jaccard .9. The existing bounded optimizer chooses the smallest adequate size from 2–4 and returns at most eight without padding. Zero removal marginal remains legal and reported. **MMR is off throughout D2**, including callers passing a nonzero setting.

## 4. Frozen researcher fields and real ingredient inventory

No researcher page, publication or ORCID retrieval occurred. No names, claims/revisions, evidence, labels, summaries, URLs, eligibility or registry generation were edited or recertified. Deterministic context encoding is numerical preparation, not new evidence.

| Frozen identity | Before = after SHA-256 |
|---|---|
| Complete researcher objects | `08054e3393fa4e3606876ccc0cbebd31d1c7c34c7822d261cb6f4b882b4badc3` |
| Complete claims | `e91568362019ecbb68026ddc86d1136259424529ee93f27368296a46b64abe89` |
| Prepared directory bytes | `3803171442db49e888bed3a4b8c42385e4015aa4c569b92cd9c79615fd54e53a` |
| Public directory JavaScript | `93b95b1f5e0656fa527c313f3ae40ccfc244e73b92f20e5e870cbe570f82da69` |
| Registry generation | `59ccfbe8999eeb4c78441e16daca468c694fc5798b03587c72468390939dc96a` |

All **90 scientific reservations** were accounted for: **35 prepared, 55 unprepared** for the recorded source/coherence/context gaps. The 35 records map to 35 distinct parents and include three child scopes; they retain 61 scientific aspects. At the comparison clock 26 are action-admitted and nine action-blocked. All 155 eligible researchers are scored; the retained public directory also has 158 manual-path records and 427 active claims / 402 distinct person-passages. There are 154 nonempty summaries, totaling 21,205 characters, maximum 437. No profile was enlarged to exploit length.

All 30 derived controls remain accounted for: 12 source-backed deterministic perturbations exercised and rejected; 18 have unprepared origins. There were **zero semantic control judgments in D2**. Their objective rejection is not model-validated relevance evidence.

D2 reused the existing 35 source-validation records with original dates and limitations. Historical composition remains 33 provenance translations, one C2 official retrieval and one D1 NASA preparation. **D2 added zero sources, zero provenance translations and zero source re-fetches.** “No new v2 receipt” is not interpreted as “no usable evidence.” The 55 unprepared scopes were not converted into no-group outcomes.

All 493 compatible D1 rows were reused byte-for-byte (398 distinct evidence-document rows and 95 query rows). R1 added **542 unique context rows** in five bounded requests. Its 1,035-row space retains exact Voyage 4 lite / 1,024 dimensions / query-document roles / exact UTF-8 preprocessing / L2 / f32 identities. General-search vectors were untouched. Storage conversion did not stand in for semantic compatibility.

The actual selected generation is `d4d2d28f66d769fc70938e8cf11df2694c285eff681bcc6b1ad43cb36a591958`, manifest `35420e07e0f867261f3757e3c7f98d309848c326e774e84677d4f912912e6847`. Selected bundle and vectors are the original D1 bytes, respectively `6587df3faca43c5a2710ca671c532a893971d3569732a9e1ac4a9c3e0396a9a7` and `cbc5788875e257e3a64030826623a1ec743e37b4667dfd1f0afe2863fb6c9d90`. Frozen real output SHA is `c220ba58bc6922d6e353594b02dd4a3cf6783047e3d330d69ee30a41e22cd410`. Public ingredients contain bounded public data; unrestricted source context and raw provider caches remain outside release assets.

## 5. Actual call-person fitting and optional components

The target event is a machine judge finding a person strong/plausible for at least one scientific contribution to the call. It is not aspect-level training truth or probability of competence, facilities, willingness, success or human approval. D1 supplies 227 unique call-person items: 106 plausible, 24 strong, 80 unrelated, 14 insufficient and three missing. **210 binary labels across 33 source groups** support this bounded analysis; the old five-useful-primary-sources condition was not used.

Five declared features are maximum aspect cosine, core cosine at that maximizing passage, lexical overlap there, maximum whole-call cosine and mean best-two aspect cosine. The same features/event are used under R0/R1. Five grouped outer folds and three grouped inner folds keep source/successor families together. Scaling, regularization and operating-point selection occur only in training partitions. The small fixed range is C={.1,1}, learned thresholds={.65,.80}, fixed thresholds={.45,.50}. If no training rule meets the unchanged 5% unrelated target with adequate counts, the predeclared TP−4FP fallback selects an operating point; that is not a relaxed product target.

| Representation / family | Outer Brier | Outer log loss | AUC | Selected reasonable / all selected | Unrelated selected | Selected groups |
|---|---:|---:|---:|---:|---:|---:|
| R0 fixed | .242903 | .678335 | .711058 | 40/49 | 9/49 (18.37%) | 9 |
| R0 regularized | .215015 | .624527 | .668365 | 24/32 | 8/32 (25.00%) | 8 |
| R1 fixed | .244865 | .682248 | .725000 | 39/53 | 14/53 (26.42%) | 9 |
| R1 regularized | .211212 | .613115 | .684519 | 31/39 | 8/39 (20.51%) | 8 |

The learned family improves Brier loss but fails the predeclared combined requirement of improved positive yield with no worse unrelated rate. Neither representation selects it. The R0 fixed full-development threshold is .50. Final refit predictions and selection-matrix diagnostics are development tuning observations, not outer-fold performance. Calibration bins, fold assignments and all setting outcomes are retained in `d2-fit-R0.json` and `d2-fit-R1.json`.

Labels are sampled by prior algorithms, correlated within source groups and noisy. No representative population calibration or human preference calibration follows from these losses. **Bayesian fitting was not run**: D2 explicitly makes it optional, and no unresolved numerical ambiguity required another fit. It is not reported as losing a comparison. MMR was prohibited in D2 and was not semantically compared here; historical component observations remain separate. No learned model asset or MMR lambda is adopted.

## 6. Nine D1 judgment disagreements

All 332 submitted item mappings reproduce. The nine inspected useful-group/unrelated-member cases retain exact people, claim revisions, source identity, target framing and per-person source/profile passages after removing local evidence aliases. There is no demonstrated packet, mapping or aggregation defect and no need to change the D1F rubric.

| D1 scope and option rank | Disposition |
|---|---|
| 357002, ranks 2 and 6 | Unresolved semantic disagreement on comparable evidence |
| 361207, ranks 2, 6, 7 and 8 | Unresolved semantic disagreement on comparable evidence |
| 363622, rank 2 | Group judgment plausibly driven by the individually strong member; inference only |
| 363622, ranks 4 and 8 | Unresolved semantic disagreement on comparable evidence |

Thus: zero different-evidence explanations established, zero mapping defects, one plausible strong-member mechanism and eight unresolved semantic disagreements. A group question and an individual question differ, but no undocumented target contribution was invented to reconcile them. Original grades remain intact. D2 still has seven useful-group/unrelated-member disagreements, including the Resource Center primary group. Favorable group grades never override the unrelated individual grades. Private model reasoning was not available and is not inferred as fact.

## 7. Real A / D1 / D2 outcomes

All numbers below are **actual offline model judgments** or explicitly deterministic output counts, not human judgments. Strong + plausible is “reasonable.” Insufficient information stays in the observed denominator and is not counted reasonable or unrelated. Missing verdicts are excluded from observed rates and separately counted. Full slices and per-scope counts are in [the immutable development results](../receipts/d2-development-results-34510982749.json).

| Top-five arm, all 35 prepared scopes | Returned / 175 possible | Graded | Reasonable | Unrelated | Insufficient | Missing | Macro reasonable / observed scopes |
|---|---:|---:|---:|---:|---:|---:|---|
| Whole-call A | 169 | 168 | 92 | 63 | 13 | 1 | 54.56% / 34 |
| Exact D1 B | 107 | 106 | 75 | 26 | 5 | 1 | 70.21% / 24 |
| D2 B | 107 | 106 | 75 | 26 | 5 | 1 | 70.21% / 24 |

A has one empty and one short nonempty list; D1/D2 have 11 empty and four short lists. D2 changes group membership, not individual ranking. On common sources, A→D2 reasonable precision differs by +6.25 percentage points, 95% source-cluster interval **−1.739 to +15.217**, 24 scopes / 23 source groups, 5,000 draws, seed 20260910. This equals the preserved D1 contrast, not a new D2 ranking gain. On the action-admitted slice D2 returns 67 entries, 66 graded: 51 reasonable, 11 unrelated, four insufficient, one missing. Its 77.27% observed reasonable rate remains below 80%. Pooled all-prepared D2 reasonable bounds including the one missing verdict are 75/107–76/107; empty slots are not quietly counted as successes.

| Group/member outcome | D1 | D2 | Whole-call A at D2 matched sizes |
|---|---|---|---|
| Numerical groups / 35 prepared | 5 | 8 | 8 matched comparison groups |
| Prepared no-group | 30 | 27 | No group invented for B abstentions |
| Useful primary groups / graded | 4/5 | 7/8 | 7/8 |
| Primary member reasonable / graded | 8/10 | 13/16 | 15/16 |
| Primary member unrelated / graded | 2/10 | 3/16 | 1/16 |
| All options: reasonable / graded / returned | 33/40/40 | 24/28/40 | Not claimed for unsampled A alternatives |
| All option members: reasonable / graded / occurrences | 56/77/80 | 63/79/80 | — |
| All option members: unrelated / graded | 20/77 (25.97%) | 16/79 (20.25%) | — |
| Distinct source/person option items: unrelated / graded | 13/42 | 6/36 | — |

D1's option groups also have five unrelated and two insufficient judgments. D2's have three unrelated, one insufficient and **12 unjudged**. D1 member occurrences have one insufficient and three missing; D2 has zero insufficient and one missing. Distinct D2 source/person items total 37: 30 reasonable, six unrelated, one missing. Repeated option appearances do not become independent scientific evidence. For all 40 D2 options, the reasonable-group fraction is bounded by 24/40–36/40 if every missing judgment is assigned adverse/favorable; the observed 24/28 is not validation of all alternatives. D2 unrelated-member bounds across all 80 occurrences are 16/80–17/80.

All D2 groups contain two members. The action-admitted subset has seven groups / 26 scopes, all seven judged useful; 19 prepared scopes have no group. Its primary members have **one unrelated / 14 graded (7.14%)**, already exceeding 5%. Its 33 options have 23 group grades (22 reasonable, one unrelated, ten missing). Its option-member occurrences have eight unrelated / 65 graded (12.31%), 57 reasonable and one missing. The nine blocked scopes retain one offline Wave Computing group judged unrelated and eight no-groups. The currentness policy prevents presenting that blocked group, but its scientific failure remains in all-prepared results.

Useful-group yield is 7/35 prepared or 7/90 reserved; action-admitted yield is 7/26. These are observed yields, **not the 85% independently feasible-scope metric**: feasibility remains unknown and is not defined by returning a group. The 55 unprepared reservations and 18 unprepared control origins remain in the inventory.

| D2 option rank | Group grades: reasonable / unrelated / insufficient / missing | Member grades: reasonable / unrelated / missing |
|---:|---|---|
| 1 | 7 / 1 / 0 / 0 | 13 / 3 / 0 |
| 2 | 7 / 1 / 0 / 0 | 13 / 3 / 0 |
| 3 | 3 / 0 / 0 / 4 | 12 / 2 / 0 |
| 4 | 2 / 0 / 1 / 2 | 7 / 2 / 1 |
| 5 | 1 / 0 / 0 / 3 | 5 / 3 / 0 |
| 6 | 2 / 0 / 0 / 1 | 5 / 1 / 0 |
| 7 | 0 / 1 / 0 / 2 | 5 / 1 / 0 |
| 8 | 2 / 0 / 0 / 0 | 3 / 1 / 0 |

The alternative sample was declared before judging: ranks 2 and 8 when present, plus a stable source/option-hash interior rank, alongside new primaries. It did not select only appealing outputs. Seven final options on 363622 and the lower-ranked olfactory/cancer alternatives show that the numerical rule does not guarantee usefulness.

Of eight matched-size A/D2 primary comparisons, three teams are identical and need no paid preference judgment. Five distinct comparisons yield two whole-call wins (361207 and 363622), two ties (359696 and Army 345241 child), and one order-conflict/unresolved result (Modern Optics child). Four predeclared swaps gave three consistent outcomes and one conflict. The conflicting judge chose displayed A in both orientations; it was not rerun or converted into a win. **There is no resolved distinct D2 preference win.** Matched-size group usefulness alone does not establish complementary benefit over A.

Six actual explanations were audited: **five faithful, one unsupported**. Four grades are new and two exact cached. The unsupported case is Resource Center 361207: the template links Diane Dalecki's “physical acoustics of biological systems” to human inner/middle-ear tissue resources. The passage exists, but the scientific connection was judged unsupported. This is a faithfulness/use-of-evidence failure, distinct from the group-usefulness disagreement and from a fabricated quotation. No paid narration or post-grade wording change was made.

## 8. Real examples and retained failure traces

- **Useful overlap:** Hearing scope 362218 selects Anne E. Luebke (“peripheral auditory neurobiology,” plausible) and Choongheon Lee (“targeted cochlear and vestibular drug delivery,” strong); the group is strong. Their q values are .609425 and .636010. Luebke's removal marginal is zero, Lee's .029093. Keeping both is an exploratory overlap decision, not proof of two independently covered sponsor requirements.
- **Recovered optics/imaging:** Olfactory imaging 359696 pairs Benjamin L. Miller (“sensing in microphysiological systems”) with James M. Zavislan (“optical coherence modeling for microscopy”); both and the group are plausible for discussing the source's in-vivo high-resolution imaging aim. Modern Optics `344592:ab-0009` pairs Brian Kruschwitz and Lewis Rothberg; both and the group are plausible despite coverage .419739 below the old floor. These outcomes support removing the universal cutoff, not claiming direct olfactory expertise.
- **Applicable transfer:** Rothberg's retained “organic light-emitting diode physics” supports a plausible conversation about Modern Optics' optical effects/light control. Douglas H. Kelley's “inner-ear fluid mixing” provides an evidenced method connection to hearing research. Departmental difference contributes no score or bonus.
- **Rejected automatic placement with preserved access:** Zhiyao Duan is graded unrelated on hearing scope 362218 and has q=.479056, below .50; the broad admitted/manual list remains intact. David W. McCamant and Ibrahim Mohammad are similarly rejected automatically on Wave Computing at q=.464138 and .498542. These successes do not erase the two unrelated people that the rule still selects there.
- **Unrelated primary failure:** Wave Computing 363622 selects Benjamin Storer and David G. Foster; both and the primary group are unrelated. This scope is action-blocked at the fixed clock. Resource Center 361207 is actionable and still includes individually unrelated Diane Dalecki beside plausible Jong-Hoon Nam, despite a plausible group grade.
- **Weak alternatives:** Olfactory option 8 contains individually unrelated Nam with plausible Rebecca Irwin and still receives a plausible group grade. Cancer imaging option 2 contains strong Edward Brown III with unrelated Foster and is graded plausible. A strong partner and a superficially plausible group description do not validate every member.
- **Honest no-group:** PINPOINT 363489 is prepared and has 16 admitted researchers, but no automatic group meets the frozen member/anchor/coverage rule. Individual/manual paths remain reachable. This is an algorithmic abstention, not proof that no reasonable collaborators exist and not an unprepared-input error.

All examples use retained public registry descriptions/interest passages. They are not newly verified faculty-page quotations or certificates of expertise. Explanations preserve exact passage anchors, and real person/aspect roles remain unconfirmed.

## 9. Focused validation, resource costs and limits

On changed D2 code, **57 focused Node/DOM checks and 76 focused Python checks passed**. The Node set includes five real-input DOM cases and 32 independent small-pool exact-optimization cases, not 32 additional browser tests. Relevant contracts cover fixed-matrix parity on all 5,425 call-person rows, candidate accessibility, 2/3/4 sizes, eight/fewer options, scoped duplicates, generic/repeated evidence, missing context, original-evidence context admission, unconfirmed status, parent/child identity, currentness between actions, stale responses, retired/mixed/corrupt snapshots, full slots, add/remove/exclusion, cache bounds and error paths.

The initial focused run exposed three fixture/reference issues: synthetic “distinct” passages collapsed under tokenization, strict equality on .9999999999999999, and a previously no-group olfactory example now legitimately returning a group. These were corrected; the real no-group test now uses PINPOINT. A real-pair reference assertion made vacuous by removing the old group parameter was replaced by the actual member-quality rule with a nonempty assertion. These failures and corrections are retained; old Stage 1 passes are not substituted for D2 validation.

The freeze tests retain nine presentation functions and 36 frozen files, plus exact fixed strings, styles, HTML constraints, old services and AGENTS policy. D2 changes only `assets/team-recommender.js` and the permitted nonvisual viability seam in `assets/team-ingredients.js`; presentation and public search/Team Match behavior are unchanged from D1.

Prepared cold/warm build, option switch, remove, add, full slots, retry, cold cache miss, stale response and failure paths made **zero model/embedding/reranking requests** in focused instrumented contracts. Ordinary directory/search startup had zero ingredient matrix calculations or team optimizations and did not load team ingredients before the existing interaction. Missing preparation has no provider fallback. These are runtime and fixture receipts, not a claim of observing deployed customer traffic.

| Actual selected package / Node measurement | Observation |
|---|---:|
| Content-addressed package bytes | 2,959,226 |
| Sum gzip / Brotli transfer bytes | 2,034,139 / 1,953,320 |
| First-interaction gzip including two lazy runtime files, excluding already-loaded directory/index | 2,047,707 |
| Hydration, single observation | 235.05 ms |
| 35 full-directory matrices: median / p95 / max | 14.81 / 43.28 / 48.36 ms |
| 35 numerical group calculations: median / p95 / max | .066 / 9.06 / 12.17 ms |
| 26 cold build/view/options: median / p95 / max | 15.63 / 27.15 / 44.33 ms |
| 26 cached build/view/options: median / p95 / max | .301 / .734 / .804 ms |
| 26 cached edits/replacements: median / p95 / max | .686 / 8.78 / 75.77 ms |
| RSS before / after hydration / after actions | 79,753,216 / 80,769,024 / 110,460,928 bytes |
| Heap used before / after hydration / after actions | 11,094,688 / 13,413,448 / 15,771,416 bytes |

Primary timing receipt is `d2-real-measurements-uncontended.json`; the earlier observation is also preserved. These are Windows Node v24.19.0 observations with real vectors/text, not a phone, physical-browser peak-memory measurement or network latency benchmark. Inputs were already resident for selected hydration. Matrix/option/row cache bounds remain 8/32/1,600. Results are stable under repeated exact inputs; currentness refreshes between actions.

Unused R1 costs are measured separately. Its bundle is 999,106 bytes and vectors 4,239,360 bytes; together gzip is 4,112,110 bytes, versus the selected evidence-only representation's smaller assets. The complete experimental R1 archive including directory and research/source context is 7,708,682 raw / 4,468,208 gzip bytes; that archive is **not a first-click package**. Node prototype decode took 122.39 ms; 35 matrices had median/p95/max 76.73/96.72/116.25 ms and group calculation .794/49.07/147.33 ms. Its original isolated outputs reproduced exactly. This measures extra representation work, not adapter hydration or a validated R1 browser integration. No synthetic gzip ratios or loader cap is used as evidence that all 150 scopes fit.

**Unrun:** full E2E, Playwright, accessibility, physical-browser/device measurements and all held-out quality gates. These remain Stage 3 work requiring separate approval. Stage 2 focused DOM passes do not stand in for them.

## 10. One durable budget and exact reuse

Authorization remains `on-demand-team-offline-v2-20260909`, **$10 total**, Stage 2 cumulative ceiling **$6**. D1's actual ledger was restored, never reset. The finite pre-dispatch D2 plan capped context at five requests and judging at 120 requests / 1,100,000 conservative input units / 61,440 output tokens, within $3.3844. The materialized plan was smaller: five context requests with $0.001852 conservative reservation, and 21 judge requests with $0.575959 conservative reservation. These were ceilings, not quotas.

| Accounting | Actual requests | Actual tokens | Actual USD |
|---|---:|---|---:|
| Prior experiment through D1 | 310 | Preserved in original ledger/history | 2.138302 |
| D2 context embeddings, 542 new rows | 5 | 15,730 input | .000318 |
| D2 judging, 29 valid items | 21 | 63,470 input + 1,355 output | .140490 |
| **D2 new spend** | **26** | As above | **.140808** |
| **Cumulative experiment** | **336 / 690 lifetime cap** | Full ledger retained | **2.279110** |
| Outstanding reservations | — | — | **0** |
| Remaining Stage 2 ceiling | — | No further work commissioned | **3.720890** |
| **Remaining total for the experiment** | — | Includes the preserved later-stage minimum | **7.720890** |

Prices were verified September 10, 2026: [Voyage 4 lite](https://docs.voyageai.com/docs/pricing) $0.02/M input; [Sonnet 5](https://platform.claude.com/docs/en/about-claude/pricing) $2/M input and $10/M output, conservatively reserving $2.50/M input. Per-request conservative rounding and actual usage reconciliation are retained. Prepaid credit did not make requests free. Historical other-task spending supplies **$0 credit**, and the old Sonnet qualification balance was not used.

The new judge packet contains one call-person item, 16 groups, four explanations and eight oriented comparison items (including four swaps). All 29 returned valid results; no new paid failure or retry occurred. Of 165 intended evaluation items, 135 already had compatible exact grades, one was historically paid-failed and not rerun, and 29 were newly purchased. Across the full reporting map there are 321 unique items / 772 occurrences: **269 unique cached grades reused over 712 occurrences**, 29 new unique grades and 23 ungraded items. The latter include deliberately unsampled alternatives and the old paid failure. These counts refer to distinct questions; they do not combine incompatible C2/D1 judgments or count a repeated option as an independent label.

Latest authoritative cloud owner: **run 34510982749**. Ledger SHA: `590e761abeefde54343e83f09341cca931b8149e0ab01d268c7acfd8c109413e`; paired checkpoint SHA: `7119bbaa839c7feeae0e1af92032fc8ed2ec48aaa7c81612a90c4c70c7d44b71`. All 315 rows from the preceding context checkpoint remain identical. `budget-ledger.json` is a read-only mirror, not an independent local spending authority. Private exact result caches and checkpoint files remain outside public release assets. Reused extraction, source evidence, 493 vectors and cached judgments are purchased work retained, not refunds or renewed authorization.

## 11. Human review, holdout and rollout

Marc Porosoff remains the sole confirmed reviewer. The original [20-item development packet](../human-review/development-packet-c2.md) is unchanged: **20 requested, zero returned, zero new or replacement requests**. The other 20 items remain reserved for the final audit. Unable-to-assess/skipped items count against the original cap; no additional labels are assumed. D1 had already changed source context relevant to packet items 1 and 5, and possible earlier verdict exposure was disclosed. D2's changed teams do not become human-validated by that historical packet. Its absence of returned answers does not make the completed automated D2 sequence incomplete.

Development reservations, source/successor grouping, the sealed holdout and source-based 50/150 rollout selection remain byte-identical. No recommendation output influenced a source replacement in D2; none was made. Key hashes are:

- Development: `833cbb454369285b381e3083426553d9b836b90ad16d3b62b65f60d2e19cb9c6`.
- Holdout: `6c08baadefcf2bab3da03684a7cc402228a0592ddf53a011816a0542229ccdd0`.
- Source-only grouping overlay: `f92fc5995a0a1ac01fce18e8366236dd06f45cd01dcec9b0953dbc7bd4558359`.
- Rollout: `71b6feef1d4bb8e5c617b23ffc4eafd2b14a104ce1d92e2eccdb625cdbcf35a5`.

The original source-only correction of NSF 22-600 and 14 historical holdout replacements remains preserved. Development has 90 reservations in 87 groups; holdout has 90 scientific reservations in 90 groups and 30 control reservations. Holdout recommendation outputs have not been generated or inspected. Preparation for the source-selected rollout remains **8/50 and 18/150 scopes**. D2 did not expand preparation merely to increase that count; no 150-scope readiness or runtime-size claim is made.

## 12. Frozen candidate and recommendation

[The D2 candidate manifest](../stage2-ranking-d2-candidate.json) freezes coverage-v2.4 / ingredients-v2.4, R0, fixed q≥.50, rho=.90, all utility/anchor/size/cache/tie parameters, exact sources/registry/vectors, adapter, D1F judge and protocol identities. Runtime SHA-256 values are `584ded558dd284e058ca4f496f01498dc1990b603252b25d6ae6f51e419d7a10` and `c9354aa5419f7dc2335d658bf4cfa79f006f546ccd1b6a4623eb7fa4225af4ef`. There is no learned asset, MMR, newly confirmed role or production fallback. Whole-call A remains a benchmark, not an activation fallback.

This is a **frozen development candidate for reproducibility, not a justified quality winner**. Targets remain visible: ≥80% macro reasonable top-five relevance, ≤5% unrelated automatic members, ≥80% useful primary groups, ≥85% yield on independently feasible scopes, and useful complementarity over matched-size A without increased harm. D2 improves observed group yield and some alternative-member counts, but misses the relevance and unrelated-member targets, has an unsupported explanation, unresolved individual/group and order judgments, unjudged alternatives and unknown independent feasibility. A simpler scorer was selected under the declared development rule; that does not mean it passed product acceptance.

**Recommendation: REVISE.** Advancement is not ready and is not merely waiting for Marc's existing audit. The evidence points to a remaining mismatch between semantic scientific contribution and the available similarity features, rather than a need to pad teams, diversify departments, enrich every profile, lower targets or buy more labels automatically. The bounded context channel did not remedy that mismatch; single-judge disagreements and biased development labels limit causal certainty.

[The conditional Stage 3 protocol](../stage3-analysis-protocol-d2.md) records the exact candidate and unchanged sealed analysis, with a maximum proposed $3.90 for Stage 3 and $0.10 Stage 4 contingency from the existing balance. It is not a request for increased money or permission to proceed. No Stage 3 gate is claimed passed. Further work requires user direction; no additional scientific revision is commissioned by this report.

**STOP FOR USER REVIEW. Do not open holdout recommendations, begin Stage 3 or deploy.**
