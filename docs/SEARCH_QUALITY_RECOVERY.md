# Funding Finder v1.2.0 search-quality recovery

Status: Phase 4 complete; release candidate blocked by the adjudicated holdout; Phase 5 not authorized

Branch: `search-quality-v2`

Starting/live `main`: `ef7a0642f6ce66828f01ee280bd5993f66029b2f`

Branch created: 2026-08-22 14:11:14 -04:00

Live application observed: Funding Finder v1.1.0, updated 2026-08-21

## Phase 1 outcome

The reported REE failure is real, reproducible, and not caused by stale deployment assets.

The live site and refreshed local `main` produced the same public-search results:

| Query | Results | Outcome |
| --- | ---: | --- |
| `REE` | 1 | YSEALI supply-chain policy workshop; irrelevant technical-R&D fit |
| `REEs` | 14 | NASA Earth/planetary, clinical rare-disease/cancer, YSEALI, and an unrelated Army child; all invalid primary results |
| `REE separations` | 0 | Misses all three authoritative-scope primary results |
| `solvent extraction of REEs` | 8 | Targetless NASA/clinical/policy/Army results admitted |
| `ionic liquids for REE extraction` | 5 | Method-only programs admitted without rare-earth target evidence |
| `R.E.E.` | 0 | Dotted acronym is not normalized |
| `rare-earth elements` | 0 | Hyphenated phrase becomes an extra unmatched concept group |

The complete 19-query live result list, asset hashes, and readiness observations are in `evaluation/search_v2_live_state.json`. The 49-query development trace is in `evaluation/search_v2_baseline.json`.

## Deployed-state reconciliation

All observed live assets were byte-identical to the refreshed repository baseline:

| Asset | SHA-256 match |
| --- | --- |
| `match_explorer.html` | yes |
| `assets/search-query.js` | yes |
| `assets/search-retrieval.js` | yes |
| `assets/match-explain.js` | yes |
| `data/opportunities.js` | yes |
| `data/subtopics.js` | yes |

Observed initialization completed with the parent catalog and publication-eligible child sidecar ready in 2,103 ms on the first measured reload and 1,598 ms on the subsequent reload. Search event binding occurs only after the sidecar and child engine initialize, so the reported result cannot be a persistent parent-only state. Initialization failure is visible as `Catalog unavailable`.

No service worker is registered by this repository. Cache-busting strings exist, but query, retrieval, explanation, parent-catalog, and sidecar assets do not share an explicit schema/version handshake. That is a bounded readiness hardening item for Phase 2, not the cause of the reported failure.

## Frozen evaluation frame

The development/holdout split was frozen before any Phase 2 tuning:

- development: 19 REE/control queries plus 30 adversarial queries across chemistry/materials, energy, biomedical, public health, agriculture, space, defense, AI/computing, and environmental science;
- holdout: 24 sealed queries stratified across primary positives, broader-program positives, method-only cases, hard negatives, phrase/acronym variants, and disciplines;
- holdout status: unopened;
- current REE truth population: 20 adjudicated result records, with no unlabelled result from the REE-family development queries.

The current catalog contains no publication-eligible parent or child that explicitly combines rare-earth target wording with technical R&D scope. Explicit wording is only one valid relevance path. The following are primary results through bounded authoritative scope entailment:

- DOE Office of Science annual solicitation (`360678`): Basic Energy Sciences and Separations;
- Genesis Mission (`361526`): Critical Minerals Supply plus Extraction and Processing Technologies;
- NSF Chemical Process Systems (`362061`): critical minerals and separations.

Their published scientific scopes encompass rare-earth separation: rare-earth elements are a controlled subset of critical minerals, and rare-earth separation lies within extraction, processing, recovery, separation science, and the cited Chemical Process Systems scope. Currentness and applicant eligibility remain separate display gates.

`Broader program fit` is reserved for genuinely adjacent programs whose fit is plausible but not established by published scope. NSF Transport Phenomena (`362063`) and the ONR long-range BAA (`356605`) currently carry that non-primary label.

## Pre-Phase-2 relevance correction

On 2026-08-22, before any Phase 2 tuning, the relevance definition was corrected. The earlier Phase 1 interpretation incorrectly treated literal rare-earth or lanthanide target wording as necessary for a primary result. The corrected primary-admission contract has two paths:

1. **Explicit evidence:** the opportunity or a publication-eligible child explicitly establishes the target and method or scientific intent.
2. **Authoritative scope entailment:** controlled concept relationships plus authoritative opportunity or child scope establish that the complete query concept is contained within the funded scientific domain.

Scope entailment is deliberately bounded. Generic agency, discipline, broad topic, category, or method labels are insufficient; each entailment must expose the controlled relationship and the authoritative scope evidence that completes the path. This correction changes the development truth rubric and labels only. It does not change query frames, retrieval scoring, admission behavior, ranking, or production assets.

The sealed holdout remains unopened and unchanged. When it is first adjudicated in Phase 4, it must use the corrected rubric rather than the superseded literal-target interpretation. The machine-readable audit record is `evaluation/search_v2_relevance_correction.json`.

The frozen Phase 1 baseline retains its original retrieval outputs, score traces, truth hash, and embedded adjudication snapshots as historical evidence. The correction record binds that superseded truth hash to schema version 2. From this checkpoint forward, evaluation must join results to `evaluation/search_v2_truth.json`; it must not use the baseline's embedded pre-correction labels as current judgment.

## Confirmed root causes

1. `REEs` is not routed through the protected rare-earth concept. The tokenizer leaves the four-character plural as `rees`; the guarded branch recognizes `ree` and `lanthanide`, so the generic alias path expands `rees` without compound-evidence guards.
2. The rare-earth guard accepts token co-occurrence rather than an actual phrase/proximity. `rare` and `earth` can therefore satisfy the concept in a policy/workshop notice.
3. `requiredUnlessTopic: Separations and membranes` lets a method topic substitute for the missing rare-earth target. This admits targetless results for complex extraction queries.
4. Dotted and hyphenated forms are not normalized into the protected acronym/phrase representation.
5. Retrieval has no controlled authoritative-scope entailment path. It therefore misses DOE BES Separation Science, Genesis Critical Minerals extraction/processing/recovery, and NSF Chemical Process Systems even though their published scopes establish primary relevance for `REE separations`.
6. Parent and child indexes collapse field identity. Retrieval evidence exposes matched terms and aggregate score contribution, so `Why this matched` cannot reliably distinguish title, description, child, program area, metadata, or source evidence.

The evidence rules out stale assets, a live/local catalog mismatch, sidecar timing, personalization, eligibility, freshness, filters, sorting, and title bonuses as the primary cause of the reported REE behavior.

## Field-ablation result

Phase 1 ran eight measurement-only variants over the frozen 49-query development frame. The production scorer itself was instrumented with optional diagnostic settings; its defaults are unchanged.

| Variant | Total admissions | Known-negative admissions | Zero-result queries | Median latency |
| --- | ---: | ---: | ---: | ---: |
| Production | 674 | 32 | 15 | 5.44 ms |
| Exact-title bonus off | 673 | 32 | 15 | 4.84 ms |
| Parent title 7 → 3 | 674 | 32 | 15 | 4.87 ms |
| Parent/child titles separated | 660 | 32 | 15 | 4.97 ms |
| Metadata cannot admit | 440 | 32 | 15 | 9.24 ms |
| Description/child summary strengthened | 660 | 32 | 15 | 4.69 ms |
| Citation source strengthened | 674 | 32 | 15 | 4.91 ms |
| Titles removed | 654 | 32 | 15 | 4.59 ms |

Title and metadata choices materially change cross-domain candidate breadth and child behavior, but none changes the REE negative count. Disabling the stacked exact-title bonus does not repair the motivating failure. A global title/description retune is therefore not authorized from this evidence.

The causal trace now records query groups, expansions, evidence guards, exact/prefix/fuzzy resolutions, admission/rejection reason, normalized parent/child scores, field-weighted term attribution, stacked phrase bonuses, and the rendered explanation for adjudicated/top results. Child source text that cannot be reconstructed from the compact sidecar is explicitly labeled `collapsed_child_source_excerpt`; it is not falsely assigned to a field.

## Scope decision

Recommended retrieval track: **Track B — bounded query/admission correction**.

Phase 2 is authorized to:

- normalize `REE`, `REEs`, dotted forms, hyphenated rare-earth phrases, and lanthanide variants into one protected target concept;
- admit primary results through either explicit evidence or bounded authoritative scope entailment;
- encode controlled target relationships such as `rare-earth elements ⊂ critical minerals` and require authoritative extraction, processing, recovery, separation-science, or equivalent child/program scope to complete the entailment path;
- require literal/phrase/proximity evidence for the explicit-evidence path;
- prevent generic separations/method topics, agency, discipline, or broad category labels from substituting for a missing target or controlled scope relationship;
- saturate synonym contribution at the concept level;
- preserve browser/Python query parity;
- add a shared search/index/sidecar schema readiness contract;
- preserve causal field/hierarchy provenance needed by Phase 3 explanations;
- reserve a separately labeled broader-program tier for adjacent programs whose authoritative scope does not establish primary entailment.

Phase 2 is not authorized to add embeddings, query-time AI, telemetry, artificial delay, a wholesale BM25F rewrite, broad synonym expansion, intuitive global weight tuning, or unbounded inference from generic metadata.

## User checkpoint resolved

The result contract now requires DOE BES Separation Science (`360678`), Genesis Critical Minerals extraction/processing/recovery (`361526`), and NSF Chemical Process Systems (`362061`) as primary relevant results for `REE separations`, subject to currentness and applicant eligibility. The success state is not an empty primary list plus three suggestions.

NASA Earth/planetary programs, rare-disease or rare-cancer programs, the YSEALI policy workshop, and unrelated child-text collisions remain excluded noise.

## Phase 2 outcome

Phase 2 implemented the authorized Track B design without changing global field weights, title bonuses, or the relevance definition. Production remains disabled. The candidate path is available only through the local/test `ff-search-v2` flag until the Phase 4 release gate.

The implementation adds:

- one protected target concept for `REE`, `REEs`, `R.E.E.`, rare-earth phrase variants, and lanthanides;
- explicit, field-backed evidence admission for technical rare-earth research, with policy/workshop and lexical-collision guards;
- identifier-bound authoritative scope entailments for DOE BES Separation Science (`360678`), Genesis Critical Minerals extraction and processing (`361526`), and NSF Chemical Process Systems (`362061`);
- complete target-plus-method coverage for protected REE searches, so a generic method or topic cannot replace the rare-earth target;
- concept-level synonym saturation;
- browser/Python query-plan and scope-entailment parity;
- a shared query/retrieval/catalog/index/evidence compatibility contract that rejects mixed asset schemas;
- causal admission provenance that separates `admittedBy`, `rankedBy`, authoritative scope, and field contribution evidence for Phase 3.

The controlled scope map lives in `config/search_v2.json`. It requires exact mapped opportunity identifiers, a supported complete scientific query, controlled concept relationships, and an authoritative parent, program-area, or publication-eligible child scope. Generic critical-minerals text, agency, discipline, topic, and category metadata do not create an entailment.

### Old/new development comparison

| Query | Phase 1 result count | Phase 2 result count | Phase 2 outcome |
| --- | ---: | ---: | --- |
| `REE` / `REEs` / `R.E.E.` / `rare-earth elements` | 0–14, depending on spelling | 0 for every alias | Identical protected target-only behavior; no current explicit technical result |
| `REE separations` | 0 | 3 | NSF CPS, DOE BES Separation Science, Genesis Mission; all admitted as primary by authoritative scope entailment |
| `rare earth separations` | 0 | 3 | Same three primary results |
| `lanthanide separation` | 0 | 3 | Same three primary results |
| `rare earth element recovery` | 0 | 3 | Same three primary results |
| `solvent extraction of REEs` | 8 noisy results | 3 | Same three primary results; NASA, clinical, policy, and unrelated child collisions removed |
| `ionic liquids for REE extraction` | 5 method-only results | 3 | Same three primary results; targetless method programs removed |

Across the 49-query development frame, 14 top-ten lists changed and all 14 were REE-family queries governed by the corrected rubric; the other 35 were unchanged. Every REE-family admission is adjudicated, no known irrelevant result is admitted, and `REE separations` contains exactly the three required primary results. The separate 48-query MEAS-5 frame spans 11 disciplines and had zero top-ten movement between production and the candidate on identical catalog and sidecar bytes. The historical 37-query production baseline also remains at zero top-ten churn.

Warm candidate scoring measured a 5.70 ms median, 11.84 ms p95, and 14.58 ms maximum over three passes of the development frame. Evidence-collecting evaluation measured an 11.30 ms median and 90.64 ms p95. The coordinated browser asset delta is 23,547 uncompressed bytes, including the new 5,701-byte generated configuration wrapper; parent and child catalog bytes are unchanged.

Local browser verification on 2026-08-22 loaded the flagged path without console warnings or errors and rendered exactly three results for `REE separations`: Chemical Process Systems, the DOE Office of Science annual solicitation containing BES Separation Science, and the Genesis Mission. The same page without the flag rendered `No opportunities matched`, confirming that the production path remains isolated.

The machine-readable evidence is in `evaluation/search_v2_results.json`, `evaluation/search_v2_movement_review.json`, `evaluation/search_v2_field_calibration.json`, and `evaluation/search_v2_field_ablation_final.json`. Phase 1 evidence did not authorize a BM25F rewrite or global weight search, so the calibration and final-ablation records explicitly mark those tasks not required rather than manufacturing a tuning exercise.

No sealed holdout query has been executed or adjudicated. The evaluator refuses a `--holdout` invocation, and the eventual Phase 4 judgment contract is the corrected schema-version-2 relevance rubric.

## Phase 3 outcome

Phase 3 replaced the flagged candidate’s keyword-echo explanations with a versioned causal contract. The production v1 explanation path remains unchanged; contextual explanation v2 activates only with the local/test search-v2 flag.

The new contract consumes Phase 2’s `admittedBy`, `rankedBy`, authoritative-scope, field-contribution, and parent/child provenance. Each displayed reason has a reason code and selected evidence record. Removing the causal admission field removes the explanation. The UI shows at most three reasons and remains collapsed by default.

Authoritative scope entailment is presented as **Primary program-scope match**, not as broader-program fit. A separate **Broader program fit** class exists only for an explicitly supplied adjacent-program fallback; it is never inferred from an umbrella title, agency, discipline, topic, or generic program label.

Representative explanation cards from the frozen frame:

| Case | Collapsed label | Expanded explanation |
| --- | --- | --- |
| NSF CPS for `REE separations` | Primary program-scope match | Authoritative scope: Chemical Process Systems — Critical Minerals and Separations; controlled rare-earth/critical-minerals and chemical-separation relationships; `REE` interpretation disclosed |
| DOE BES for `REE separations` | Primary program-scope match | Authoritative scope: Basic Energy Sciences — Separation Science; rare-earth separation identified as a specialization of separation science |
| Genesis for `REE separations` | Primary program-scope match | Authoritative scope: Securing America’s Critical Minerals Supply — Extraction and Processing Technologies; controlled target and operation relationships disclosed |
| Genesis for `catalyst design` | Subprogram match | Names the publication-eligible Electrochemical Energy Conversion Catalyst Discovery and Scale up focus area and its matching summary |
| Army BAA for `catalyst design` | Subprogram match | Names the publication-eligible Electrochemistry subprogram and its causal summary evidence |
| `DE-FOA-0003600` | Exact identifier match | Names the exact opportunity number rather than echoing the query |
| NSF CPS for `catalysis` | Contextual evidence match | Quotes the bounded opportunity-description sentence containing catalysis in its scientific scope |
| Explicit rare-earth title fixture | Contextual evidence match | Discloses the `REE` interpretation and identifies target and method evidence in the opportunity title |
| `R.E.E. recovery` with lanthanide evidence | Expanded scientific match | Discloses the acronym expansion and identifies lanthanide evidence in the opportunity description |
| Profile-assisted catalysis fixture | Exact title match | Gives the public title evidence, then says only that the research profile increased ranking; private profile text is never repeated |
| Explicit adjacent Transport Phenomena fixture | Broader program fit | Clearly says the published scope is adjacent and does not explicitly name the target |
| `CFD` → `CFDA` collision | No displayed explanation | Rejected before explanation because a short technical acronym cannot prefix-expand into a longer unrelated indexed token |

The explanation truth frame was committed before implementation at `7a18983` and contains 42 query/result pairs. After stabilization, 41 are `correct_and_useful` and one individually reviewed case is `correct_but_too_shallow`, for 97.62% useful coverage. The remaining shallow case is deliberately fail-closed: a fixture admitted only through generic metadata renders no confident explanation. The former `CFD`/`CFDA` collision is now rejected by retrieval and therefore has no explanation.

All Phase 3 explanation gates pass:

- 0 unsupported or misleading explanations;
- 0 reasons citing evidence that did not affect admission or ranking;
- 0 review-only child leakage;
- 0 private profile/CV/ORCID excerpts;
- 0 authoritative-scope results mislabeled as broader fit;
- 0 tautological query echoes;
- every causal child-driven explanation names the publication-eligible child;
- generic title reranking is explained through the substantive admission field instead;
- maximum three reasons per card, collapsed by default;
- at a 390 px browser viewport, all three REE card summaries fit with no horizontal overflow.

The browser asset delta for Phase 3 is 15,553 uncompressed bytes: 13,801 bytes in the explanation contract, 1,417 bytes in app wiring, 319 bytes in compact badge styling, and 16 bytes in coordinated cache-version strings. Existing size-budget tests pass.

The frozen frame and results are `evaluation/match_explain_v2_frame.json` and `evaluation/match_explain_v2_results.json`. No sealed search holdout query was executed or adjudicated, production remains disabled, and no live deployment occurred.

## Phase 2.1 / Phase 3.1 stabilization outcome

The development-only stabilization pass generalized the partial-intent correction without changing the Phase 2 relevance definition or scoring architecture. It preserves the protected REE concept, all three authoritative-scope entailments, global field weights, title bonuses, the Phase 3 explanation contract, and the production-off flag. It adds no BM25F, embeddings, query-time AI, telemetry, or broad ontology.

For concise technical queries with two to four substantive concept groups, primary admission now requires complete substantive coverage when at least one group has a bounded scientific evidence rule. A synonym or deterministic expansion may satisfy its own group, but one query concept cannot substitute for another. Longer natural-language searches retain the prior forgiving coverage behavior. The bounded evidence vocabulary adds only concepts supported by existing deterministic program language or observed development failures: critical minerals, technical separation operations, quantum sensing, maritime context, navigation/PNT, critical-minerals workforce context, and artificial-intelligence evidence. Scientific `catalysis` remains non-strict so the stable two-term chemistry behavior and MEAS-5 frame are not broadened or damaged.

Short uppercase technical acronyms now require an exact indexed token or an existing high-confidence deterministic resolution. They cannot recover through prefix or fuzzy matching into a longer token. This removes `CFD` → `CFDA` generically. The existing `AI` resolution also rejects `AI/AN` population wording unless genuine artificial-intelligence evidence is present.

Development relevance truth is now keyed by exact query ID and result ID in `evaluation/search_v2_development_truth.json`: 77 judgments across 16 existing development queries. This prevents a result's judgment for one scientific domain from leaking into another query. During the bounded review, `adv_ai_03:344592` was corrected to primary after its single publication-eligible ARL child was verified to fund electronic sensing of biological threats. That is recorded as a query-specific truth correction, not a scoring change. The sealed holdout was neither inspected nor modified and must eventually be judged with the corrected relevance rubric.

The six required cross-domain development checks are fully judged and contain no unjudged or non-primary top-ten result:

| Query | Stabilized primary results | Precision at 10 | Required recall |
| --- | --- | ---: | ---: |
| `critical mineral separations` | NSF CPS, Genesis, NSF EWRE | 1.00 | 1.00, up from 0.67 |
| `AI catalyst design` | NSF CPS, DOE ECLIPSE | 1.00 | 0.67, unchanged |
| `critical mineral workforce` | DOL critical-sectors workforce, U.S.-Egypt workforce collaboration, UNITE | 1.00 | 1.00 |
| `autonomous maritime sensing` | ONR Long Range BAA | 1.00 | 1.00 |
| `quantum navigation` | DEVCOM ARL and TDAC BAAs | 1.00 | 1.00 |
| `quantum sensing biology` | NSF CPS and the ARL Electronic Sensing child | 1.00 | 1.00 |

Across the 49-query development frame, 11 top-ten lists moved relative to the Phase 2 candidate and all 11 have explicit query-specific reviews in `evaluation/search_v2_stabilization_movement_judgments.json`. The material improvements include moving Genesis into `critical mineral separations` while removing the policy workshop and other partial-intent records; restricting `AI catalyst design`, `autonomous maritime sensing`, `trustworthy AI health`, `quantum sensing biology`, and `critical mineral workforce` to results establishing the complete intent; and removing unsupported partial matches for `CO2 membrane separation`, `geothermal lithium extraction`, and `AI cancer diagnosis`. One REE query and `space biology` only reordered already-relevant membership. The final 48-query MEAS-5 frame spans 11 disciplines and has zero top-ten movement.

Phase 3 was not redesigned. The same causal, field-backed, fail-closed contract was rerun across all 42 pairs. Only the `CFD` case changed, because it is no longer admitted; all legitimate explanation evidence remains causal and the final frame has 41 useful cases, one reviewed shallow metadata fixture, and zero unsupported explanations.

Local browser verification loaded the flagged candidate without warnings or errors. `REE separations` rendered exactly NSF CPS, DOE BES Separation Science, and Genesis, each labeled `Primary program-scope match`. With the flag absent, the same search rendered no matches, confirming production isolation. Under the default Grants.gov source filter, `critical mineral separations` rendered CPS and Genesis and excluded the policy workshop; the development evaluator additionally retains the relevant NSF EWRE result when all configured sources are evaluated.

The machine-readable stabilization evidence is `evaluation/search_v2_results.json`, `evaluation/search_v2_development_truth.json`, `evaluation/search_v2_phase2_top10.json`, `evaluation/search_v2_movement_review.json`, and `evaluation/search_v2_stabilization_movement_judgments.json`.

## Phase boundary

Completed through Phase 2.1 / Phase 3.1:

- latest-live baseline and isolated branch;
- exact live asset reconciliation;
- 19 live query results;
- frozen development/holdout split;
- complete REE result adjudication, followed by the recorded pre-Phase-2 relevance-definition correction;
- production-module diagnostic trace;
- eight field ablations;
- root-cause and Track B decision.
- protected query normalization and substantive explicit-evidence verification;
- bounded authoritative program-scope entailment for the three required primary programs;
- concept saturation, strict protected-query coverage, and causal field/scope provenance;
- browser/Python parity and mixed-schema fail-closed readiness checks;
- old/new development movement review and cross-domain regression evaluation;
- local flagged/unflagged browser integration verification.
- frozen 42-pair explanation truth frame committed before explanation tuning;
- deterministic explanation contract separating admission, ranking, and displayed evidence;
- primary authoritative-scope, direct child, contextual field, expanded acronym, exact identifier, profile-ranking, broader-fit, and fail-closed weak-evidence treatments;
- compact collapsed explanation UI with desktop and 390 px mobile browser verification;
- explanation privacy, publication-boundary, causality, density, and usefulness gates.
- query-specific development truth keyed by query and result;
- complete substantive coverage for bounded two-to-four-concept technical queries while preserving longer-query coverage behavior;
- exact-only short-acronym recovery and bounded `AI/AN` disambiguation;
- six fully adjudicated cross-domain development checks and review of all 11 development top-ten movements;
- final 49-query, MEAS-5, historical-baseline, explanation, browser, Python, size, and no-drift gates.

Verification at the Phase 2.1 / Phase 3.1 boundary:

| Gate | Result | Exit code |
| --- | --- | ---: |
| 49-query development frame | All hard gates passed; warm p95 45.12 ms; holdout sealed | 0 |
| Query-specific cross-domain sample | 6 queries; no unjudged or non-primary top-ten results; recall not worse | 0 |
| 48-query MEAS-5 frame | 11 disciplines; zero top-ten movement | 0 |
| Full browser product suite | 131 passed | 0 |
| Historical query baseline | 37 queries; zero top-10 churn | 0 |
| Selected Python search/parity/page/size suites | 15 passed | 0 |
| Phase 3 explanation truth | 42 pairs; 97.62% correct and useful; 0 unsupported | 0 |
| Size-budget tests | 3 passed | 0 |
| Hermetic no-drift rebuild | 22 artifacts unchanged | 0 |
| Full Python suite on current refreshed catalog | 827 ran; 10 failures and 1 error in inherited P5/P7/MEAS-8 frozen-census checks | 1 |

The full Python failures reproduce catalog-fixture drift already present after the 2026-08-22 `main` catalog refresh: historical frames pin 1,475 records/745 cache entries while the current inputs contain 1,453 records/709 cache entries, and one retired ID (`362088`) is still referenced. No failing test imports or exercises the Phase 2 retrieval or Phase 3 explanation path. Those historical artifacts were not rewritten because they are outside this recovery scope and are intended to remain frozen evidence. Phase 2 added `tests/test_search_query.py` for the new browser/Python parity contract.

## Phase 4 outcome

The pre-registered 24-query holdout was opened and executed exactly once
against frozen candidate code `627e7c82480e97ed1cc6a5adbc4e830469347acb`, then
adjudicated as query/result pairs under the corrected authoritative-scope
rubric. No post-outcome retrieval or explanation tuning occurred.

The release candidate is blocked. Five of six positive REE variants missed all
three authoritative DOE BES, Genesis, and NSF CPS programs; direct-positive
holdout queries exposed missing rural maternal-health and agricultural anchors,
partial-intent admissions, a 213-candidate health/workforce/workshop explosion,
and rich evidence buried below weaker matches. The NASA rare-earth false-positive
gate passed, and the exact `rare earth solvent extraction` success case returned
the three required primary programs.

All independent infrastructure and regression gates passed: the 49-query
development frame, 48-query MEAS-5 frame, 37-query historical baseline,
42-pair explanation frame, 137 browser tests, 756 live-product Python tests,
11 focused Python tests, 50-case parent/child invariant, size gates, 22-artifact
no-drift rebuild, and desktop/390 px mobile verification. Four grouped permanent
CI canaries were added. These passes do not override the failed holdout.

The complete review is `evaluation/PHASE4_REVIEW.md`; the machine-readable
decision is `evaluation/search_v2_release_candidate.json`. Search v2 remains
disabled, `main` remains untouched, and Phase 5 is not authorized. Any further
tuning must be a new iteration with this failed holdout preserved as evidence
and a newly frozen development/holdout protocol.

## Phase 2R / Iteration 2 outcome

Iteration 2 began from `38181e63bc9b19b4fea10494852dd4068ffe2d09` on `search-quality-v2`. Before retrieval tuning, the failed Phase 4 package was reclassified as permanent development challenge evidence and its five governing artifacts were hashed in `evaluation/search_v2_iteration2_challenge.json`. A new 28-query, cross-discipline acceptance population was then pre-registered in `evaluation/search_v2_iteration2_holdout_frame.json`; its frame hash is `3e94159b9eff8ef424b51ddc46c4cdb3a28243a39aa21374cd3411fb5d4b3cc3`. It has never been executed or adjudicated, has no results artifact, and remains behind a runner lock pending explicit Phase 4B authorization.

The failed challenge clustered into a small number of shared causes: literal query normalization and grouping gaps; query-form-specific rather than concept-family scope rules; lack of generic complete-intent verification; citation and administrative-text collisions; conflation of discovery with primary admission; and rich child or authoritative evidence being ranked in the same pool as weak lexical matches. The detailed 24-query causal table and the dominant clustering of all 43 irrelevant top-ten admissions are in `evaluation/search_v2_iteration2_root_causes.json`. Catalog review confirmed that Rural MOMS, AFRI, SCALEUP, and the Genesis foundation-model children already contain usable authoritative evidence; those failures belonged to retrieval, not ingestion.

The generalized candidate keeps the Phase 2 REE architecture, field weights, title bonuses, Phase 3 explanation contract, and production-off boundary. It adds:

- complete substantive-intent verification for concise technical searches with two to five groups, while keeping the measured forgiving behavior for longer prose queries;
- bounded, directional, non-transitive concept families with canonical IDs, rationale, observed need, and tests;
- program scope expressed as verified concept-family coverage at publication-eligible child, controlled program-area, or authoritative parent level;
- a separate discovery → verification → primary/broader/reject pipeline with diagnostic counts for every stage;
- evidence tiers that order exact or complete rich authoritative evidence before incomplete lexical score, then retain the existing lexical and child-rollup signals within each tier;
- citation-source text as discovery/ranking context only, never as the sole basis for primary admission;
- explicit broader-program fit outside the primary list.

No BM25F, embeddings, query-time AI, telemetry, paid API, or browser model was added. The static configuration is bounded to observed concept families and has no transitive inference.

Two development labels were corrected after source inspection, both as query/result truth changes rather than scoring changes: ECLIPSE is broader rather than primary for `AI catalyst design` because its published scope does not establish AI/ML, and the ONR BAA is broader rather than primary for `autonomous maritime sensing` because the complete phrase is present only in collapsed citation/index text. Truth remains keyed by exact query and result.

### Former Phase 4 challenge results

| Metric | Failed candidate | Iteration 2 |
| --- | ---: | ---: |
| Primary Precision@10 | 0.373 | 1.000 |
| Required-primary Recall@10 | 0.633 | 1.000 |
| Required-primary Recall@50 | 0.650 | 1.000 |
| Direct-positive nDCG@10 | 0.586 | 0.915 |
| Maximum visible primary count | 213 | 4 |
| Confirmed irrelevant top-ten primaries | 43 | 0 |

All six REE method/material queries recover DOE BES, Genesis, and NSF CPS where the adjudicated scope requires them; NASA/planetary and rare-disease noise remains excluded. Rural MOMS and AFRI are recovered, SCALEUP moves from rank 7 to rank 1, and Genesis moves from rank 30 to rank 3 for `secure foundation models`. Both zero-primary hard negatives now display zero primary results. Across the 24 challenge queries, the candidate displays 39 primary results and one broader fit after considering 11,675 internal candidates and rejecting 11,635 partial-intent candidates. Admissions comprise five direct and 34 authoritative-scope paths. Challenge latency measured 32.58 ms p50 and 183.92 ms p95.

Metrics are reported separately by REE/material hierarchy, health, agriculture, energy, AI/computing, defense, space, environment, and hard negatives in `evaluation/search_v2_iteration2_results.json`; no failing domain is hidden in the aggregate.

### Deterministic and semantic comparison

The authorized offline semantic spike used a local, static PPMI distributional candidate generator over eligible parent and publication-eligible child text. It made no external calls, excluded citation-source text, capped candidates at 50, and could not declare a result primary. Across 34 development/challenge queries and 77 required anchors, deterministic retrieval reached 1.000 required-anchor recall at 50 while the semantic alternative reached 0.481. The decision is **SEMANTIC SPIKE NOT NEEDED FOR PRODUCTION**; no semantic asset or dependency was shipped. Full evidence is in `evaluation/search_v2_iteration2_semantic_spike.json`.

### Iteration 2 development and Phase 3R gates

The 49-query development frame passes all hard gates. Twenty-five top-ten lists moved and every movement has an explicit accepted review. The six query-specific cross-domain checks have no unjudged or non-primary top-ten admissions, with `autonomous maritime sensing` now correctly returning zero primary results under the corrected source-backed truth. The 48-query MEAS-5 frame has 38 reviewed top-ten movements across 11 disciplines; nonzero churn is accepted only where the prior result was demonstrably incomplete or irrelevant. The historical 37-query baseline retains zero top-ten churn, and the 50-case parent/child cardinality invariant remains byte-identical.

Phase 3 was verified, not redesigned. The 42-pair frame retains 41 correct-and-useful explanations, one individually reviewed shallow fail-closed case, and zero misleading, unsupported, overstated, privacy-violating, or non-causal explanations. Semantic similarity is never shown as a match reason.

Final verification passed: 138 browser tests; 43 focused Python search/parity/schema/size tests; 756 live-product Python tests; all size gates; and the 22-artifact hermetic no-drift rebuild. The live-product runner continues to exclude the inherited closed `test_meas8`, `test_p5_closeout`, `test_p7_frame`, and `test_p7_residual` frozen-census modules. Their previously documented catalog-fixture failures were neither rewritten nor repaired in this pass.

The coordinated browser assets grew by 75,445 uncompressed bytes from the failed-candidate starting SHA: 229 bytes in app evidence ordering, 27,038 in query interpretation, 12,770 in retrieval verification/diagnostics, and 35,408 in the generated configuration wrapper; the explanation asset is unchanged. Size gates pass. Warm development scoring measured 11.33 ms p50, 31.39 ms p95, and 35.94 ms maximum; evidence-collecting evaluation measured 23.95 ms p50 and 65.99 ms p95.

Machine-readable outcome and movement review are in `evaluation/search_v2_iteration2_gate_report.json` and `evaluation/search_v2_iteration2_movement_review.json`.

**ITERATION 2 DEVELOPMENT GATES PASSED**

**READY TO FREEZE CANDIDATE FOR PHASE 3R / PHASE 4B**

Phase 4B has not been authorized or executed. Search v2 remains off, `main` remains untouched, nothing was deployed, no release version/date was created, and Phase 5 remains unauthorized.

## Phase 4B outcome

Phase 4B supersedes the preceding Iteration-2 pre-open status. The pre-registered 28-query frame was verified at SHA-256 `3e94159b9eff8ef424b51ddc46c4cdb3a28243a39aa21374cd3411fb5d4b3cc3`, opened once against frozen candidate `daa3355bc68b9fda45037a0a8d2be8c38fad7638`, and immediately frozen. The immutable raw-results SHA-256 is `fef755fb0bfdd2f485bf712478dc3b82623038882f9e961746d79ac599ff8af5`. The runner now refuses a second execution. Adjudication is keyed by exact query and result, retains every pre-registered anchor, and made no retrieval, scoring, concept, scope, explanation, or UI change.

The release candidate is blocked. Across 28 queries and 27 required anchors, query-average primary Precision@10 was 0.411, positive-query required-primary Recall@10 and Recall@50 were both 0.300, micro anchor recall was 0.296, and nDCG@10 was 0.393. Nineteen required anchors were completely missed. Recall failed in materials, agriculture, energy, AI/computing, defense, space, and environmental science. The only domain with complete positive-query recall was public health, where one adjacent rural residency-workforce program was incorrectly labeled primary.

The candidate considered 19,839 internal candidates, rejected 19,826, displayed 12 primary results, displayed no broader fits, and had a maximum of three visible primaries versus 1,142 internal candidates for one query. Three displayed primaries were irrelevant and one was a broader fit. The failures include unseen material-operation normalization and scope gaps; missing authoritative parent/child recall for AFRI, SCALEUP, Genesis, ARL, Geospace, DWPR, and CESU; AIM/ordinary-`aim` and partial-intent admissions; a stale currentness admission; and a broader-fit classification failure. These are class-level Iteration-3 evidence, not authorization to patch or rerun this spent holdout.

Phase-4B explanations contained no unsupported evidence or privacy/review-only leakage, but four of 12 were misleading because retrieval incorrectly labeled broader or irrelevant results as primary. The independent 42-pair Phase-3 frame itself remained green with 41 useful cases, one reviewed shallow fail-closed case, and zero unsupported or misleading explanations.

All regression and infrastructure gates remained green: the 49-query development frame; former Phase-4 challenge; 48-query/11-discipline MEAS-5 frame; 37-query historical baseline with zero top-ten churn; 50-case parent/child invariant; browser/Python configuration parity; 139 browser tests; 43 focused Python tests; 756 live-product Python tests; size gates; and the 22-artifact no-drift rebuild. Warm development latency was 11.23 ms p50 and 31.46 ms p95. Phase-4B candidate latency was 35.71 ms p50 and 172.53 ms p95. Phase 4B added zero browser-asset bytes.

The authoritative decision is `evaluation/search_v2_release_candidate_v2.json`; raw execution, receipt, truth, adjudicated results, and actual test exit codes are recorded in the adjacent Phase-4B evaluation artifacts. Search v2 remains disabled, `main` remains untouched, nothing was deployed, and no release version/date was created.

**PHASE 4B BLOCKED — PHASE 5 NOT AUTHORIZED**

The Phase-4B holdout is permanently spent and must not be rerun as acceptance. If work continues, these outputs become Iteration-3 challenge evidence and a new sealed holdout must be frozen before any tuning.

## Local search architecture reset

The local architecture reset began from `29d94701e13134dcfefb991a5c69a6589c57c273` on `search-quality-v2`. It tested the smallest conventional information-retrieval replacement for the manually configured scientific relationship system. Phase 4C was not opened: its frame remains at SHA-256 `7fde6b7ccbdab59331c26899f37bdbb8f9ee7e30f8f3632f257e28d27124865e`, its manifest remains at `d45fcc91a52d01673cf1fa5bc91f25ed26c0c8f92f970e902559ecbda9164c6c`, and no Phase-4C result or truth artifact exists.

Before implementation, the 19 Phase-4B missed anchors were audited against the text already present in six authoritative fields. Only one anchor had complete query support in a single passage, one had complete support split across fields, and one had partial support that still depended on a scientific relationship. Sixteen of 19 did not contain enough query-side vocabulary for conventional fielded ranking to establish the complete intent. The detailed query/anchor evidence and post-implementation fate are preserved in `evaluation/search_v2_local_field_feasibility.json`.

The reset replaces collapsed-text scoring and configured scientific entailment with a browser-local fielded passage scorer:

- parent title, publication-eligible child title, child summary, parent description, authoritative program area, and bounded authoritative document scope remain separate scoring fields;
- BM25-style term saturation and per-field length normalization are combined with field weights, exact phrase bonuses, bounded proximity bonuses, and a cubic query-coordination factor;
- concise two-to-five-concept searches require complete coordination for primary admission; near-complete coherent evidence may be labeled broader, while partial candidates are rejected;
- short uppercase acronyms and identifiers require exact indexed evidence or a high-confidence existing acronym expansion, and fuzzy recovery is limited to edit distance one for terms of at least seven characters when exact evidence is absent;
- a parent inherits only the strongest single matching parent or child passage, with no child-count bonus and no cross-child evidence stitching;
- candidate discovery, final primary/broader/reject classification, and ranking evidence are recorded separately;
- `Why this matched` extracts the highest-contributing verified field or passage and never presents a score, fuzzy relationship, or configured entailment as agency language.

All active scientific relationship maps are now empty. Relative to the starting candidate, active configuration was reduced from 25 concept families, three controlled relationships, 11 source-scope relationships, 21 authoritative-scope entailments, one configured broader fit, and 43 query contract cases to zero of each. The retained acronym table is bounded normalization, not a scientific scope map.

This architecture produces a real precision improvement but does not generalize well enough to open Phase 4C. Across both spent acceptance populations (52 queries, 65 required anchors), primary Precision@10 is 0.974, required-primary Recall@10 and Recall@50 are both 0.185, and nDCG@10 is 0.375. Fourteen primaries are visible after 11,857 internal candidates; 92 results are separated as broader fit and 11,751 partial-intent candidates are rejected. Two visible results are irrelevant or unjudged under existing spent-set truth, and the maximum visible-primary count is three.

| Spent population | Precision@10 | Recall@10 / Recall@50 | nDCG@10 | Visible primaries | Non-primary or unjudged primaries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Phase 4, 24 queries / 38 anchors | 0.944 | 0.105 / 0.105 | 0.236 | 6 | 2 |
| Phase 4B, 28 queries / 27 anchors | 1.000 | 0.296 / 0.296 | 0.494 | 8 | 0 |

Because every scientific family and program-specific scope map is globally withheld, the same results are also the leave-family/program-out test. Recall@50 is zero for materials (31 anchors), agriculture (three), chemistry (three), defense (two), and biology (one); it is 0.333 for space, 0.400 for energy and environment, 0.500 for AI/computing, and 0.750 for health. Hard negatives produce zero primaries. Three of the 19 Phase-4B missed anchors become visible, while 16 remain rejected.

The result is not a ranking-weight failure. Candidate discovery remains broad, and the scorer ranks rich explicit child passages effectively when the query vocabulary is present. The blocking limitation is source representation: ordinary lexical IR cannot infer material hierarchies, method paraphrases, properties, or program objectives that are absent from the authoritative indexed passages, while relaxing complete-intent coordination would recreate the proven false-positive problem. No query exception, program signature, semantic dependency, paid API, hosted service, query-time model, or new infrastructure was added.

The browser suite passes 145 tests; focused Python search and size suites pass 32 tests; the scoring/no-drift Python group passes 22 tests; the historical 37-query production baseline has zero top-ten churn; the hermetic rebuild preserves all 22 governed artifacts; and the 42-pair explanation frame retains 41 correct-and-useful cases, one reviewed shallow case, and zero unsupported, privacy-leaking, or review-only explanations. The 49-query search-v2 development gate correctly fails this candidate, and 44 of 48 MEAS-5 queries move, so the reset is not a release candidate. The full 827-test Python discovery still has the same 10 failures and one error confined to inherited frozen-census P5/P7/MEAS-8 modules.

Measured over the 52 spent queries, scoring latency is 38.08 ms p50 and 109.08 ms p95. The three coordinated browser assets shrink by 27,286 bytes overall: retrieval grows by 24,852 bytes, the generated configuration wrapper shrinks by 53,047 bytes after removing the mappings, and explanations grow by 909 bytes.

The machine-readable measurements are `evaluation/search_v2_local_architecture_results.json`, `evaluation/search_v2_local_architecture_leaveout.json`, and `evaluation/search_v2_local_architecture_gate_report.json`. The architecture is retained as bounded experimental evidence on `search-quality-v2`, but it is not authorized for Phase 4C or production.

**LOCAL ARCHITECTURE STILL INSUFFICIENT — INDEXED AUTHORITATIVE TEXT LACKS COMPLETE QUERY VOCABULARY FOR 16 OF 19 AUDITED MISSED ANCHORS**

## Local MiniLM reranker feasibility

A development-only cross-encoder experiment tested whether semantic reranking can repair the remaining vocabulary-gap failures without changing the local BM25F baseline, primary admission, production explanations, or browser assets. The experiment used `cross-encoder/ms-marco-MiniLM-L6-v2` at immutable revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, Apache-2.0 licensed, with the 23,200,716-byte dynamically quantized UINT8 AVX2 ONNX graph and 712,726 bytes of tokenizer files. Transformers.js 4.2.0 and ONNX Runtime Node 1.24.3 were installed only in a temporary directory; model weights remain outside the repository.

The unchanged BM25F discovery stream supplied the top 20, 30, or 50 authoritative parent/child passages. MiniLM scored query/passage pairs, and each parent inherited only its strongest passage score. Semantic score was never treated as relevance evidence and could not admit a primary result.

At depth 50, required-anchor candidate Recall@10 increased from 0.477 to 0.538, while Recall@50 remained exactly 0.600. Across all 65 required anchors, five moved into the top 10 and one moved out; the known-correct `AI journalism exchange` result regressed from candidate rank 1 to rank 12. Among the 16 vocabulary-gap anchors, nine entered the depth-50 candidate window, six were already BM25F top-10 candidates, and MiniLM promoted only two additional anchors into the top 10. Seven vocabulary-gap anchors remained outside the candidate window and one remained below rank 10. MiniLM therefore mostly reordered candidates already found lexically and did not solve candidate-window recall.

The historical truth set does not fully adjudicate the new semantic top 10: 440 of 501 query/result pairs are unjudged. On judged pairs, Precision@10 moved from 0.492 to 0.574, while the conservative query-average lower bound moved only from 0.073 to 0.081 and 17 known irrelevant results remained in the combined top tens. Across 12 zero-primary hard negatives, semantic top tens contain nine known irrelevant and 109 unjudged pairs. User-visible hard negatives remain unchanged only because semantic score is prohibited from manufacturing primary evidence.

Native CPU performance at depth 50 measured 0.828 seconds p50 and 1.050 seconds p95 including BM25F. Cached initialization took 0.682 seconds and added about 94 MB RSS; the full evaluation process reached about 839 MB RSS. On the same 20-passage query, native CPU reranking measured 0.271 seconds p50, while direct single-thread ONNX Runtime Web/WASM measured 3.323 seconds. WebGPU was unavailable in the Node harness and was not benchmarked. No production asset bytes were added.

Detailed evidence is in `evaluation/search_v2_local_minilm_results.json`, `evaluation/search_v2_local_minilm_runtime_benchmark.json`, `evaluation/search_v2_local_minilm_model_receipt.json`, and `evaluation/search_v2_local_minilm_decision.json`. Phase 4C remains sealed and unexecuted.

**LOCAL MINILM RERANKING DOES NOT JUSTIFY ITS COST/WEIGHT — DISCARD THIS PATH**

## Voyage reranker API feasibility

A final development-only experiment tested `rerank-2.5` through Voyage's ordinary real-time API without changing the frozen BM25F baseline or production search behavior. The harness used the same 52 spent queries and 65 required anchors as the MiniLM experiment, retrieved up to 200 BM25F parent/child passages per query, sent only bounded public indexed text, used one fixed generic complete-intent instruction, and retained only the strongest reranked passage per parent. Semantic score never created primary admission evidence. No private researcher data, model weights, browser dependency, backend, Worker, secret, scientific mapping, or generated program metadata was added.

Voyage improved ordering among reachable candidates: required-anchor Recall@10 rose from 0.477 for BM25F and 0.538 for MiniLM to 0.615. Recall@50 rose from 0.600 to 0.662, and judged-pair Precision@10 rose from 0.492 to 0.714. Eleven required anchors entered the top ten and two left it. Voyage promoted three of the 16 audited vocabulary-gap anchors into the top ten beyond BM25F, including CPS for dysprosium recovery, Genesis for critical-metal leaching, and SCALEUP for grid-scale storage scale-up. This was genuine semantic-paraphrase recovery within the candidate pool.

The end-to-end quality bar nevertheless failed. Only 43 of 65 required anchors were present in the frozen depth-200 candidate pool, establishing a maximum possible Recall@50 of 0.662 versus the pre-registered approximate 0.85 screen. Seven of the 16 vocabulary-gap anchors were absent from the candidate pool. Voyage therefore reached the pool ceiling but could not solve discovery. It also newly promoted one known irrelevant acronym collision to rank 2 on a hard negative. Historical truth remains sparse over semantic top tens, with 445 Voyage pairs unjudged; no new large adjudication was used to rescue the result.

The run completed 52 successful scoring requests after two recorded pre-scoring HTTP 429 attempts during rate-limit propagation, reranked 6,653 passages, and reported 2,055,171 tokens. At Voyage's published paid price the nominal cost is $0.102759. This usage is about 1.03% of the published 200-million-token free allocation, although the rerank response does not expose the account's remaining free balance. API latency measured 0.385 seconds p50 and 0.513 seconds p95; BM25F plus API measured 0.435 seconds p50 and 0.640 seconds p95. Browser asset size changed by zero bytes.

Detailed results are in `evaluation/search_v2_voyage_reranker_results.json`, the request/usage receipt is `evaluation/search_v2_voyage_api_receipt.json`, the candidate ceiling is `evaluation/search_v2_voyage_candidate_ceiling.json`, and the decision is `evaluation/search_v2_voyage_reranker_decision.json`. Phase 4C remains sealed and unexecuted.

**VOYAGE RERANKING DOES NOT CLEAR THE QUALITY BAR — DISCARD API RERANKING**

## Hybrid Voyage retrieval and reranking feasibility

The follow-up development-only experiment tested the missing stage: semantic
candidate retrieval. It embedded 1,659 stable public parent/child passages once
in memory with `voyage-4-lite` (`input_type=document`, 1,024 float dimensions),
embedded each of the 52 spent queries with `input_type=query`, fused the top 200
semantic and unchanged BM25F passages with reciprocal-rank fusion, and sent at
most 300 union passages to `rerank-2.5`. No vectors, model assets, credentials,
private researcher material, or query/result text were persisted beyond the
existing bounded evaluation evidence. Semantic scores did not create admission
evidence and cannot be used in explanations.

Candidate discovery cleared its feasibility gate. BM25F required-anchor recall
at depths 10/50/100/200 was 0.477/0.600/0.646/0.662; semantic retrieval reached
0.600/0.769/0.908/0.985; and the union reached
0.646/0.815/0.908/0.985. Semantic retrieval recovered 21 of the 22 anchors absent
from BM25F's candidate pool. The sole remaining discovery miss was DOE BES for
`REE hydrometallurgy`.

Reranking converted the new candidate recall into materially stronger final
ordering. Across 65 required anchors, Recall@10 rose from 0.477 to 0.877 and
Recall@50 from 0.600 to 0.985. Query-average nDCG@10 rose from 0.566 to 0.771,
and Precision@10 over previously judged pairs rose from 0.492 to 0.781. The
19-anchor Phase-4B audit reached 0.895 Recall@10 and 1.000 Recall@50; the 16
vocabulary-gap anchors reached 0.875 and 1.000. With all scientific mappings
still globally absent, leave-family Recall@50 was 1.000 in nine evaluated
positive families and 0.968 in materials. This is evidence of untuned semantic
generalization rather than another relationship map.

The result still has important boundaries. Eight anchors remain below rank 10;
the previously correct NSF child for `secure foundation models` moved from rank
1 to 28, and `AI journalism exchange` moved from 1 to 14. One known acronym
collision was newly promoted to rank 1 for `AIM materials intelligence`.
Nevertheless, the experiment did not show a systematic known-irrelevant
increase: known irrelevant top-ten placements fell from 17 to six overall and
from eight to four across the 12 hard-negative queries. Any production design
must therefore retain exact acronym/identifier checks and deterministic
complete-intent admission as hard gates after semantic ordering. The historical
truth is sparse over the newly discovered candidates (447 hybrid top-ten pairs
remain unjudged), so this is architecture-feasibility evidence, not acceptance.

The run made seven corpus-embedding requests, 52 query-embedding requests, and
52 successful rerank requests (54 attempts after two transient 429 retries),
reranking 13,731 passages. It used 395,436 embedding tokens and 3,349,932
reranking tokens. At published paid pricing, the nominal cost was $0.175406;
both model-family totals are within the published free-token quantity, although
the API does not expose the account's remaining balance. The one-time corpus
build took 10.48 seconds. Per-query component latency was 0.625 seconds p50 and
0.778 seconds p95. Production browser assets changed by zero bytes.

Detailed evidence is in
`evaluation/search_v2_hybrid_voyage_results.json`, the sanitized API receipt is
`evaluation/search_v2_hybrid_voyage_api_receipt.json`, and the interpretation is
`evaluation/search_v2_hybrid_voyage_decision.json`. Production search code and
behavior remain unchanged, search v2 remains off, `main` is untouched, and
Phase 4C remains sealed and unexecuted.

**HYBRID VOYAGE RETRIEVAL + RERANKING CLEARS THE QUALITY BAR — PRODUCTION ARCHITECTURE SHOULD BE CONSIDERED**

## Production-shaped hybrid Voyage implementation

The feasibility architecture is now implemented behind the disabled search-v2
flag without deploying a proxy or changing production behavior. The browser
renders the existing local BM25F results immediately, then lazily loads a
versioned 1,659-passage `voyage-4-lite` float16 index, performs local cosine
retrieval, fuses the top 200 lexical and semantic passages with reciprocal-rank
fusion, and sends at most 300 allowlisted public passages to `rerank-2.5` through
a separately deployable Cloudflare Worker. The strongest parent or eligible
child passage represents each result. Any vector, network, provider, schema, or
timeout failure leaves the already-rendered BM25F results in place.

The static index uses stable passage IDs and a corpus/vector hash handshake.
Its 3,397,632-byte vector payload and 431,976-byte manifest are excluded from
the initial page and downloaded only for an eligible search. An incremental
no-change build reused all 1,659 passages, made zero provider requests, and
left both assets byte-identical. The browser gained 31,992 uncompressed initial
bytes. The Worker accepts only the production GitHub Pages origin and local
development origins, validates exact query and candidate schemas, requires
committed public passage ID/text-hash pairs, returns no documents, retains the
Voyage key as a server secret, and contains no query logging. It has been
contract-tested locally but not deployed.

The production-shaped run used both spent holdouts only: 52 queries and 65
required anchors. Required-anchor Recall@10 was 0.846 and Recall@50 was 0.954;
query-average nDCG@10 was 0.734, and Precision@10 over the 70 previously judged
top-ten pairs was 0.786. All 19 audited Phase-4B anchors and all 16 audited
vocabulary-gap anchors reached the top 50. Warm end-to-end latency was 651 ms
p50 and 854 ms p95. The final run made 52 query-embedding and 49 reranking
requests, reranked 12,832 public passages, and has a nominal published-price
estimate of $0.156, or about $2.99 per 1,000 searches at the measured mix.

The development gate remains blocked. A bounded manual review covered 139
exact query/result pairs: every surfaced top-ten result for zero-anchor queries
and the top result for every positive query that returned one. All 100 reviewed
zero-anchor results were non-primary, and positive-query top-one complete-intent
precision was 0.795. A global cutoff cannot separate them: hard-negative scores
reach 0.641 while required anchors fall to 0.340; a 0.45 cutoff still leaves 49
hard-negative results and reduces required Recall@50 to 0.585. The audit also
found an ingestion-owned representation error: the Burma governance record
`363604` exposes `hydrometallurgy` as an authoritative program area despite no
support in its title or description, making it rank first for `REE
hydrometallurgy` and contaminating its extractive explanation.

The complete browser suite passes 166 tests, the focused hybrid/proxy suite
passes eight, focused Python suites pass 43 unittest cases plus 37 pytest cases
and 24 subtests, the live-product Python run passes 756 tests, the 50-case
parent/child invariant is byte-identical and cardinality-invariant, and the
hermetic rebuild preserves all 22 governed artifacts. Search v2 remains off,
the Worker is not deployed, `main` is unchanged, and the Phase-4C holdout
remains sealed and unexecuted. Phase 4C is not authorized until the source
representation defect and the generalized partial-intent precision failure are
resolved without query-specific tuning.

**HYBRID PRODUCTION IMPLEMENTATION BLOCKED — SPENT HARD NEGATIVES STILL RECEIVE HIGH-RANKED PARTIAL-INTENT RESULTS**

## Final intent/abstention gate experiment

The extraction defect behind the Burma governance collision was repaired at its
source. The controlled `ion exchange` phrase had matched the suffix of
`information exchange`, incorrectly deriving `hydrometallurgy`. Word-bounded
recognizers plus cached-quote revalidation removed five stale evidence hits and
changed four public passages, including record `363604`, without remerging
unrelated deadline/currentness fields. Four affected passages were re-embedded;
the final 1,659-passage corpus and 3,397,632-byte vector asset were then
revalidated with zero additional API requests.

A final development-only abstention experiment added a strict `/judge` contract
to the undeployed Worker and tested exactly
`@cf/meta/llama-3.1-8b-instruct-fast` through Wrangler's local remote binding.
One fixed prompt classified each reranked top ten as primary, broader, or
reject. The Worker accepts only exact committed public passages and matching
parent/type/title/field metadata; private or arbitrary text is rejected. The
browser uses the model only as a classification gate, never as a ranker or an
explanation generator. Invalid output preserves the neutral hybrid-ranked list
without fabricated labels.

The gate failed decisively on the 52 spent queries and 65 required anchors.
Hybrid candidate Recall@50 remained 0.954, but user-visible primary Recall@10
and Recall@50 fell to 0.215. Query-average nDCG@10 fell from 0.734 to 0.205.
Precision over 56 previously adjudicated visible-primary outputs was 0.304 (91
additional primary outputs remain unjudged, so this is not presented as a fully
adjudicated population estimate). Only four of 12 zero-anchor queries returned
zero primary results. Exact-pair confusion included 20 primary-to-reject, 10
primary-to-broader, one broader-to-primary, and one irrelevant-to-primary
classification. Several hard negatives still received three to eight primary
labels.

Reliability was also insufficient: 10 of 49 Workers AI calls failed strict
structured-output validation, producing 13 query-level neutral fallbacks when
zero-candidate cases are included. No classifications were fabricated. Judge
latency was 1.050 seconds p50 and 1.720 seconds p95; warm end-to-end latency was
1.794 seconds p50 and 2.336 seconds p95. The run used 663.53 Workers AI Neurons
(6.64% of the documented daily free allocation) plus a nominal $0.155657 of
Voyage usage at published paid pricing. Extractive explanations remained clean
for all 236 visible primary/broader results checked, with zero generated-language
or private-text exposure.

Detailed evidence is in `evaluation/search_v2_intent_gate_results.json`,
`evaluation/search_v2_intent_gate_usage.json`,
`evaluation/search_v2_intent_gate_source_fix.json`, and
`evaluation/search_v2_intent_gate_gate_report.json`. The Worker was not
deployed, search v2 remains off, `main` is unchanged, and Phase 4C remains
sealed and unauthorized.

**INTENT GATE DOES NOT SOLVE HARD-NEGATIVE PRECISION WITHOUT UNACCEPTABLE RECALL LOSS**
