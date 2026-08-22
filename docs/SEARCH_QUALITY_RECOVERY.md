# Funding Finder v1.2.0 search-quality recovery

Status: Phase 1 complete; Phase 2 not started

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
| `REEs` | 14 | NASA Earth/planetary, clinical rare-disease/cancer, YSEALI, and an unrelated Army child; all invalid direct REE matches |
| `REE separations` | 0 | Misses all adjudicated broad DOE/NSF program homes |
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
- holdout: 24 sealed queries stratified across direct positives, broad-program positives, method-only cases, hard negatives, phrase/acronym variants, and disciplines;
- holdout status: unopened;
- current REE truth population: 20 adjudicated result records, with no unlabelled result from the REE-family development queries.

The current catalog contains no publication-eligible parent or child that explicitly combines rare-earth target evidence with technical R&D scope. The supported anchors are broader program homes:

- DOE Office of Science annual solicitation (`360678`): Basic Energy Sciences and Separations;
- Genesis Mission (`361526`): Critical Minerals Supply plus Extraction and Processing Technologies;
- NSF Chemical Process Systems (`362061`): critical minerals and separations.

These are not honest direct matches. If displayed, they require a distinct `Broader program fit` policy and explanation.

## Confirmed root causes

1. `REEs` is not routed through the protected rare-earth concept. The tokenizer leaves the four-character plural as `rees`; the guarded branch recognizes `ree` and `lanthanide`, so the generic alias path expands `rees` without compound-evidence guards.
2. The rare-earth guard accepts token co-occurrence rather than an actual phrase/proximity. `rare` and `earth` can therefore satisfy the concept in a policy/workshop notice.
3. `requiredUnlessTopic: Separations and membranes` lets a method topic substitute for the missing rare-earth target. This admits targetless results for complex extraction queries.
4. Dotted and hyphenated forms are not normalized into the protected acronym/phrase representation.
5. The current source/index surface has broad DOE/NSF homes but no direct current rare-earth R&D call. A correct direct-result set may therefore be empty.
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
- require literal/phrase/proximity target evidence for direct admission;
- prevent separations/method topics from substituting for the target concept;
- saturate synonym contribution at the concept level;
- preserve browser/Python query parity;
- add a shared search/index/sidecar schema readiness contract;
- preserve causal field/hierarchy provenance needed by Phase 3 explanations;
- prototype a separately labeled broad-program fallback, without treating it as a direct result.

Phase 2 is not authorized to add embeddings, query-time AI, telemetry, artificial delay, a wholesale BM25F rewrite, broad synonym expansion, intuitive global weight tuning, or a source-ingestion rebuild intended to fabricate direct REE recall.

## User checkpoint

One product-policy decision remains before the Phase 2 result contract can be finalized:

> When no direct rare-earth target evidence exists, should DOE Office of Science, Genesis, and NSF Chemical Process Systems appear in a separate `Broader program fit` tier, or should the direct list remain empty and broader homes appear only as a suggestion?

The recommended default is a separate broader-program tier because it preserves useful DOE/Genesis discovery while staying explicit that the source does not name the target.

## Phase boundary

Completed in Phase 1:

- latest-live baseline and isolated branch;
- exact live asset reconciliation;
- 19 live query results;
- frozen development/holdout split;
- complete REE result adjudication;
- production-module diagnostic trace;
- eight field ablations;
- root-cause and Track B decision.

Verification at the Phase 1 boundary:

| Gate | Result | Exit code |
| --- | --- | ---: |
| Full browser product suite | 109 passed | 0 |
| Historical query baseline | 37 queries; zero top-10 churn | 0 |
| Page-entrypoint tests | 7 passed | 0 |
| Size-budget tests | 3 passed | 0 |
| Hermetic no-drift rebuild | 22 artifacts unchanged | 0 |
| Full Python suite on current refreshed catalog | 822 ran; 10 failures and 1 error in inherited P5/P7/MEAS-8 frozen-census checks | 1 |

The full Python failures reproduce catalog-fixture drift already present after the 2026-08-22 `main` catalog refresh: historical frames pin 1,475 records/745 cache entries while the current inputs contain 1,453 records/709 cache entries, and one retired ID (`362088`) is still referenced. No failing test imports or exercises the Phase 1 JavaScript tracing change. Those historical artifacts were not rewritten because they are outside this recovery scope and are intended to remain frozen evidence. The plan’s recommended `tests/test_search_query.py` parity file does not exist in the current repository; creating it belongs to Phase 2 when browser/Python query behavior changes.

Not started:

- Phase 2 retrieval/query correction;
- broad-program UI policy implementation;
- Phase 3 contextual explanation redesign;
- Phase 4 holdout execution and release-candidate freeze;
- merge, deployment, or live v1.2.0 shipment.

`main` remained untouched after branch creation. Phase 1 began with zero branch divergence. At the Phase 1 handoff, the branch contains only the committed Phase 1 package and tracks its remote counterpart.
