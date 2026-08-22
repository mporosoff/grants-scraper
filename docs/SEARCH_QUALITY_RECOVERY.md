# Funding Finder v1.2.0 search-quality recovery

Status: Phase 2 complete; Phase 3 not started

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

## Phase boundary

Completed through Phase 2:

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

Verification at the Phase 1 boundary:

| Gate | Result | Exit code |
| --- | --- | ---: |
| Full browser product suite | 118 passed | 0 |
| Historical query baseline | 37 queries; zero top-10 churn | 0 |
| Selected Python Phase 2/page/size suites | 37 passed | 0 |
| Size-budget tests | 3 passed | 0 |
| Hermetic no-drift rebuild | 22 artifacts unchanged | 0 |
| Full Python suite on current refreshed catalog | 825 ran; 10 failures and 1 error in inherited P5/P7/MEAS-8 frozen-census checks | 1 |

The full Python failures reproduce catalog-fixture drift already present after the 2026-08-22 `main` catalog refresh: historical frames pin 1,475 records/745 cache entries while the current inputs contain 1,453 records/709 cache entries, and one retired ID (`362088`) is still referenced. No failing test imports or exercises the Phase 2 search path. Those historical artifacts were not rewritten because they are outside this recovery scope and are intended to remain frozen evidence. Phase 2 added `tests/test_search_query.py` for the new browser/Python parity contract.

Not started:

- Phase 3 contextual explanation redesign;
- Phase 4 holdout execution and release-candidate freeze;
- merge, deployment, or live v1.2.0 shipment.

`main` remained untouched after branch creation. The Phase 2 candidate remains committed only to `search-quality-v2`, with production activation intentionally deferred.
