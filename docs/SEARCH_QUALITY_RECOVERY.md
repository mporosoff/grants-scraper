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
