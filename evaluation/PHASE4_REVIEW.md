# Funding Finder search v2 Phase 4 review

## Decision

```text
Release candidate blocked with exact failing gate
```

Phase 5 is not authorized. Search v2 remains disabled in production. Phase 4
did not merge to `main` and did not deploy.

The holdout was executed exactly once against candidate code
`627e7c82480e97ed1cc6a5adbc4e830469347acb`. Its immutable raw result SHA-256
is `8d4a1d37e0940fde1eefdd3dca7f3fa2a39a40194ce6b083b40eafd4897fb919`.
All 24 queries were then adjudicated as exact `(query_id, result_id)` pairs
under the corrected authoritative-scope relevance rubric. No search weights,
aliases, thresholds, admission rules, or explanations were changed after the
holdout was opened.

## Exact failing gates

1. **REE direct-anchor recall.** Five of six positive REE variants missed all
   three authoritative programs: rare-earth recycling, lanthanide ion
   exchange, REE hydrometallurgy, yttrium separation, and scandium recovery.
   Rare-earth solvent extraction retrieved DOE BES, Genesis, and NSF CPS at
   ranks 1–3.
2. **DOE/Genesis scope recall.** The same five variants demonstrate that the
   bounded authoritative-scope path is tied too narrowly to the protected
   query forms instead of the scientific relationships required by the
   corrected rubric.
3. **Direct-positive precision and recall.** Material failures include rural
   maternal health missing Rural MOMS, drought-tolerant crop genetics missing
   AFRI, long-duration storage ranking SCALEUP seventh behind weak matches, and
   microgravity radiation biology admitting nine records with no microgravity
   scope.
4. **Candidate explosion.** `health data workforce workshop` admitted 213
   candidates. Its top ten did not contain a primary result.
5. **Confirmed irrelevant primary admissions.** Forty-three top-ten
   query/result pairs were adjudicated irrelevant, including partial-intent,
   cross-topic, citation-collision, and administrative `program element`
   matches.
6. **Rich evidence buried by weaker evidence.** Rural MOMS was absent for
   `maternal mortality rural communities`; the Genesis foundation-model child
   ranked 30th for `secure foundation models`.
7. **Misleading result explanations.** The Phase 3 explanation generator is
   still causal and field-backed, but it faithfully labels incorrectly
   admitted holdout results as primary. This is an upstream retrieval failure,
   not a reason to redesign the explanation contract.

The NASA rare-earth false-positive gate passed: `rare Earth observation
elements` returned no results. The intended REE success case also passed for
`rare earth solvent extraction`, and `AI journalism exchange` contracted from
seven candidates to one adjudicated primary result.

## Holdout metrics

- Query-average primary precision at 10: **0.373**
- Positive-query average required-primary recall at 10: **0.633**
- Positive-query average required-primary recall at 50: **0.650**
- Direct-positive average primary precision at 10: **0.348**
- Direct-positive average nDCG at 10: **0.586**
- Maximum candidate count: **213**
- Candidate latency: **26.96 ms p50 / 133.32 ms p95**
- Production latency on the same one-time run: **16.29 ms p50 / 159.67 ms p95**

For empty negative queries, the machine-readable artifact treats precision and
recall as 1.00 only when no primary result is required. Per-query failures are
not hidden in the aggregate.

| Query ID | Query | Old→new candidates | P@10 | Required recall @10 / @50 | Required-primary ranks |
| --- | --- | ---: | ---: | ---: | --- |
| `hold_ree_01` | `rare earth recycling` | 0→0 | 0.00 | 0.00 / 0.00 | BES miss; Genesis miss; CPS miss |
| `hold_ree_02` | `rare earth solvent extraction` | 1→3 | 1.00 | 1.00 / 1.00 | BES 1; Genesis 2; CPS 3 |
| `hold_ree_03` | `lanthanide ion exchange` | 1→0 | 0.00 | 0.00 / 0.00 | BES miss; Genesis miss; CPS miss |
| `hold_ree_04` | `REE hydrometallurgy` | 0→0 | 0.00 | 0.00 / 0.00 | BES miss; Genesis miss; CPS miss |
| `hold_ree_05` | `yttrium separation` | 0→0 | 0.00 | 0.00 / 0.00 | BES miss; Genesis miss; CPS miss |
| `hold_ree_06` | `scandium recovery` | 0→0 | 0.00 | 0.00 / 0.00 | BES miss; Genesis miss; CPS miss |
| `hold_ree_07` | `rare Earth observation elements` | 0→0 | 1.00 | 1.00 / 1.00 | no primary required |
| `hold_ree_08` | `rare disease molecular elements` | 5→5 | 0.40 | 1.00 / 1.00 | GREGoRi Technology 1; Innovation 2 |
| `hold_chem_01` | `electrocatalytic ammonia synthesis` | 1→1 | 1.00 | 1.00 / 1.00 | ARL 1 |
| `hold_chem_02` | `innovation catalyst student success` | 3→3 | 0.67 | 1.00 / 1.00 | S-STEM 1; LSAMP 3 |
| `hold_energy_01` | `long duration energy storage` | 10→10 | 0.10 | 1.00 / 1.00 | SCALEUP 7 |
| `hold_energy_02` | `mineral supply chain diplomacy` | 5→5 | 0.40 | 1.00 / 1.00 | Tunisia 1; YSEALI 2 |
| `hold_bio_01` | `single cell cancer immunology` | 2→2 | 0.50 | 1.00 / 1.00 | Mathers 1 |
| `hold_bio_02` | `BioData Catalyst training` | 0→0 | 1.00 | 1.00 / 1.00 | no primary required |
| `hold_health_01` | `maternal mortality rural communities` | 1→1 | 0.00 | 0.00 / 0.00 | Rural MOMS miss |
| `hold_health_02` | `health data workforce workshop` | 213→213 | 0.00 | 1.00 / 1.00 | no primary required |
| `hold_ag_01` | `drought tolerant crop genetics` | 0→0 | 0.00 | 0.00 / 0.00 | AFRI miss |
| `hold_space_01` | `microgravity radiation biology` | 9→9 | 0.00 | 1.00 / 1.00 | no current catalog anchor; precision gate |
| `hold_space_02` | `Earth system chemical elements` | 16→16 | 0.10 | 1.00 / 1.00 | Geospace 10 |
| `hold_defense_01` | `high temperature hypersonic composites` | 1→1 | 1.00 | 1.00 / 1.00 | ARL 1 |
| `hold_ai_01` | `secure foundation models` | 59→59 | 0.20 | 0.67 / 1.00 | PESOSE 1; DCL 3; Genesis 30 |
| `hold_ai_02` | `AI journalism exchange` | 7→1 | 1.00 | 1.00 / 1.00 | Jakarta 1 |
| `hold_env_01` | `membrane PFAS treatment` | 6→6 | 0.33 | 1.00 / 1.00 | water purification 1; CPS 2 |
| `hold_env_02` | `coastal ecosystem climate adaptation` | 4→4 | 0.25 | 1.00 / 1.00 | Alaska CESU 2 |

## Old/new material movements

- `rare earth solvent extraction`: added BES, Genesis, and CPS; removed the
  policy workshop.
- `lanthanide ion exchange`: removed the policy workshop but failed to recover
  the three authoritative scientific programs.
- `AI journalism exchange`: removed six partial or unrelated results and kept
  the Jakarta media grant as the sole primary result.

All other top-ten sets were unchanged. Zero churn is not counted as success
where the inherited result set is adjudicated wrong.

## Independent gates

| Gate | Result |
| --- | --- |
| Frozen split and pre-open SHA/config checkpoint | Passed |
| Single holdout execution; separate raw/adjudicated artifacts | Passed |
| Post-outcome tuning | None |
| 49-query development frame | Passed |
| 48-query MEAS-5 / 11 disciplines | Passed; zero top-ten movement |
| Historical 37-query baseline | Passed; zero top-ten churn |
| Phase 3 explanation frame | Passed; 42 pairs, 97.62% useful, zero unsupported |
| Browser contracts | Passed; 137 tests |
| Live-product Python suite | Passed; 756 tests |
| Focused Python search/parity/schema/size | Passed; 11 tests |
| Parent/child scorer | Passed; 50 cases, byte-identical and cardinality-invariant |
| Size budgets | Passed; 3 tests |
| Hermetic no-drift | Passed; 22 artifacts unchanged |
| Local desktop/mobile | Passed; flagged three-card REE view, no errors, no 390 px overflow; unflagged behavior preserved |
| Permanent CI canaries | Added and passed; 4 grouped cases |

The inherited closed P5/P7/MEAS-8 frozen-census failures remain documented and
were not repaired or redrawn. The live-product test runner deliberately
excludes those closed historical frames and passed all 756 in-scope tests.

## Artifact map

- Pre-open checkpoint: `evaluation/search_v2_phase4_preopen.json`
- Evaluator wiring incident: `evaluation/search_v2_phase4_execution_incident.json`
- Immutable raw execution: `evaluation/search_v2_holdout_results_raw.json`
- Query-specific truth: `evaluation/search_v2_holdout_truth.json`
- Adjudicated result and per-query metrics: `evaluation/search_v2_holdout_results.json`
- Independent gate runs: `evaluation/search_v2_phase4_test_runs.json`
- Blocked release decision: `evaluation/search_v2_release_candidate.json`

The evaluator incident occurred before any query was scored or outcome was
observed; the production harness was then instantiated correctly and the
holdout was executed once. The raw artifact's execution count is one, and the
runner refuses to execute again while that artifact exists.

## Required next step

Reopen the owning retrieval phase as a new iteration. Preserve this failed
holdout as permanent evidence, define a new frozen development/holdout
discipline before tuning, and address the general defects rather than adding
holdout-string special cases. Phase 5 remains closed.
