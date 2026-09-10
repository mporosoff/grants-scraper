# Funding Finder — richer embeddings, on-demand teams
## Stage 2 continuation D3 and the remaining release path

Version 1.0 — September 10, 2026
Repository: `mporosoff/grants-scraper`
Experiment: `codex/on-demand-team-recommender`
Worktree: `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender`

**Decision:** Test richer reusable representations before adding a reranker. Prepare vectors when call/profile information changes. Calculate researcher rankings, groups, alternatives and replacements when a user requests them. Do not build a new production inventory of pre-generated teams or paid researcher–call assessments.

**Execution boundary:** This document is one continuation of the existing four-stage project. Stage 1 is not repeated. Its execution instruction authorizes Stage 2 D3 only; deliver the full report and STOP before Stage 3. Stage 3 validation and Stage 4 publication remain separately approved stages. This document does not itself imply that any work has been executed.

## 1. Preserve what works and identify the actual hypothesis

The supplied D2 report records a functioning experimental on-demand calculation, frozen researcher records, and no new recommender deployment. It reports 155 eligible researchers, 402 person-passages, 35 prepared development scopes, 61 aspects, and only 18/150 prepared rollout scopes. Selected D2 remains the evidence-only R0 representation. The tested R1 used a limited context blend, capped positive uplift, and retained the old evidence admission. That is not a standalone test of the whole-profile representation proposed here. [R1, lines 47–92, 191–211, 245–255]

The new hypothesis is specific: **independently embedded short interests may lose the scientific context needed to distinguish an applicable contribution from a superficial resemblance.** Test the representation and embedding model, not another collection of exceptions for individual researchers or calls.

Do not assume a richer representation will win. Preserve D2 and the whole-call baseline. A combined-profile model is a legitimate winner if contextual chunks do not provide enough extra value. An inconclusive result is not permission for an automatic new provider/model campaign.

### Nonnegotiable product boundaries

- Keep the current presentation, wording, controls, child selector, all accessible matches, complete proposed groups, explanations/source links, alternatives, add/remove actions, saved/manual paths, and separate all-member Team Match behavior.
- Keep two-to-four-person automatic groups and up to eight useful alternatives through the existing renderer. These are maxima, not targets to pad.
- Make no paid model, embedding, or reranking request on prepared-scope build/edit/retry/cache-miss/error paths. Add no browser model inference in this revision.
- Do not precompute a serving inventory of new teams, all researcher–call matches, or pairwise model approvals. A bounded in-memory cache of results already requested by a user is allowed, not authoritative.
- Do not scrape faculty pages, retrieve publications or ORCID, rewrite summaries, add skills, change claims/eligibility, or recertify profiles. All researcher facts remain the same.
- No department-distance, racial/demographic, reputation, popularity, or novelty reward. Scientific relevance admits people; relevant complementarity ranks groups.
- Keep the interface's evidence status separate from recommendation score. Contextual similarity does not establish possession of equipment, clinical access, availability, or a required capability.
- Keep broad parents as scope choosers. Do not combine unrelated siblings or alternatives into a fictitious project.

## 2. Architecture: prepare individual entities, not combinations

### When information is added or changed

Prepare a canonical public researcher document from that person's already-stored information and a scientific query package for each coherent call/child. Create their required embeddings once through the existing trusted preparation workflow. Publish the reusable ingredients through the existing verified asset path when the appropriate release stage is approved.

### When the user clicks Build a team

Load the current compatible ingredient package through the existing loader; select the exact call/child; compare its vectors with eligible researcher vectors; compute candidate rankings; select complementary groups and alternatives; populate the existing interface. Removing or adding someone recalculates using the same numbers and preserved user exclusions.

No provider is contacted. No pre-generated team file must exist for that call. Never calculate every enabled call's teams during startup or ingredient loading.

### Evaluation is not pre-generation for production

Offline experiments necessarily calculate and may save example groups to measure quality. Those outputs are test evidence, not a serving dependency and not the contents of a new production team catalog. The runtime must work after evaluation-output directories are removed.

Previously published, still-valid legacy teams may remain on their existing route during migration. Do not regenerate them or represent old evidence as newly validated.

## 3. Define the exact text before making vectors

### 3.1 Combined researcher document

Use one deterministic document per person containing:

1. Their existing research summary, when present.
2. Their distinct active research-interest/evidence statements, in a stable order.
3. Associated existing claim labels/types, where they provide useful context, with their identity retained.

Use plain, stable field labels and original text; no generated narrative. Deduplicate repeated interests so repetition does not add importance. Do not repeat the full summary before every claim. Names, departments, URLs, citation counts and administrative metadata are not relevance text. Retain identity/source metadata outside the text for attribution.

**One combined-profile embedding means actually encoding the combined text.** Averaging old short-phrase vectors is not the same experiment.

Preserve missing summaries and sparse records honestly. Exact researcher-object/claim hashes must remain unchanged, although derived input hashes and vectors can change.

### 3.2 Contextualized interests

For a contextual representation, use the same canonical document content divided into a summary/context chunk and individual interest/evidence chunks. Context belongs to one researcher only. Never place different researchers in one contextual document group, even when batching several people in one API request.

Use explicit deterministic chunks rather than automatic chunking for these short profiles. Retain the full document identity, chunk order, source fields and chunk-to-claim mapping. Do not duplicate the summary across all chunks.

Do not confuse contextual influence with evidence: a chunk can become similar because of another interest in the same profile. Explanations must cite the actual supporting retained statements, not assert that the highest-scoring chunk alone proves the proposed contribution.

### 3.3 Scientific call queries

Retain the actual source-backed aspects, central scientific purpose, coherent approach/child identity and relevant limitations. Separate scientific text from application boilerplate, contact details, deadlines and submission mechanics. Keep those fields for eligibility, not as accidental expertise features.

For the first controlled comparison, use the identical existing D2 scientific query strings across the new arms; change only the specified model/profile representation. Preserve the exact D2 baseline.

One additional, predeclared input-format comparison is allowed on the leading representation: an aspect alone versus the same aspect with bounded source-derived central purpose and applicable context/exclusions. Do not give only one comparison arm unexplained additional scientific evidence. Report this as a query-format effect, not a model-only improvement.

A source-grounded aspect must not be a synthetic detailed experiment. A single aspect is allowed. Do not split synonyms to force complementary roles or increase their total weight.

Freeze source scope definitions for the initial representation experiment. Perform only necessary bounded integrity/context corrections, version and report them, and rerun comparable arms on the same corrected evidence. Do not expand the entire source catalog while diagnosing representations.

## 4. A finite representation comparison

| Arm | Embedding model | Researcher representation | Purpose |
|---|---|---|---|
| E0 | Retained `voyage-4-lite` | Exact selected D2 evidence phrases | Reproduce the incumbent, including its known limits |
| E1 | `voyage-4-large` | The same independent evidence phrases | Test stronger standard embeddings with matched text |
| E2 | `voyage-4-large` | One combined existing-profile document per researcher | Test the user's proposed global representation |
| E3 | `voyage-context-4` | Interest chunks contextualized within that researcher's existing document | Test richer context while preserving identifiable interests |

Generate both query and document representations with the appropriate model for each new arm. Do not compare a new-model query to an old-model document merely to save a negligible embedding charge. Keep E0 intact as a historical/comparison space. Vendor compatibility among standard Voyage 4 models does not make exact input identities or score calibration interchangeable. Do not assume compatibility between standard and contextual model spaces. [S1–S2]

Start at 1,024 dimensions and float output for controlled comparison. More dimensions, quantization variants, additional vendors, and model fine-tuning are not separate experiments in D3. Check output shape, finite values, norms, input roles and identity with bounded smoke/contract checks, then use the full eligible directory.

### API detail that corrects the earlier conceptual sketch

Voyage's contextual API groups **document** chunks. For `query` input, the documented nested form contains one query per inner list. Thus E3 should use one query string per call aspect; include bounded call context in that string only in the declared query-format comparison. Do not send a multi-aspect query list as though the API automatically contextualizes it as a document. Use the current guide/model contract and a bounded preflight; do not change input roles simply to make an unsupported request shape pass. [S2–S3]

The standard model documentation lists `voyage-4-large` as its high-quality standard option and lite as cost/latency optimized. The contextual model is designed to encode a chunk with its document's context. Those are vendor capabilities, not proof of improved scientific matching in this application. [S1–S2, S4]

### One optional local/global combination, not a new model sweep

E3 may also be tested with a global profile-consistency feature from the same contextual model, using a single-document encoding of the combined profile. Compare contextual local relevance alone with one modest predeclared global blend, using reused vectors where possible.

Do not impose a new universal hard whole-profile-similarity veto. A researcher with a relevant specialist technique may have a broader research program in a different application. Global context should disambiguate, not suppress legitimate transfer automatically.

Do not retain D2's capped R1 uplift or old evidence-only gates unchanged as prerequisites for new-arm admission. That would prevent the representation experiment from testing improved admission. Preserve scientific constraints and development-only calibration instead.

## 5. Scoring: retain coverage, separate individual quality

For aspect query Q_i and combined profile P_j, E2 supplies:

s_global(i,j) = cosine(E_query(Q_i), E_document(P_j)).

For researcher j's contextualized interest chunks C_jk, E3 supplies:

s_local(i,j) = max_k cosine(E_query(Q_i), E_context_document(C_jk | P_j)).

A simple local/global combination may be tested using calibrated, comparable scores. The global component is optional. Neither score is automatically a probability of usefulness or expertise.

Keep the group objective:

F(T) = sum_i w_i * max_{j in T} r_ij.

Use group-level scientific anchoring, member relevance and scoped nonredundancy; prefer the smallest adequate group. Do not restore a universal positive removal-marginal condition or an arbitrary universal raw-coverage cutoff. Those earlier defects remain regression cases.

Each automatically included member must independently be reasonable. Within a near-best coverage envelope, weakest-member and average-member relevance must matter; the strongest person cannot carry an irrelevant partner into seven alternatives. Preserve the broader individual list and user's manual selection/removal control.

### Calibrate fairly across representations

Freeze a small, common calibration procedure before comparing results. Numerical constants such as .40 or .50 are not portable measures of relevance across models, global documents and contextual chunks.

Use grouped development folds for transforms, admission operating points and any fitted coefficients. Compare relevance/yield tradeoffs with their denominators, not one hand-picked threshold per method. Never rescale every call's best candidate to a positive match; a directory can genuinely lack a good contributor.

Maximum-over-chunks scores can favor verbose profiles. Keep within-person deduplication and test short/long-profile bias, unrelated added text, misleading shared words, rare specialist interests and multiple distinct interests. Test whether unrelated context changes a chunk's meaning or falsely attributes another claim's capability.

Use D2's call-person labels only for their actual call-person event. The limited aspect labels are not hundreds of independent capability labels. A compact regularized or Bayesian scorer is optional local analysis using the same valid labels; do not create another paid labeling campaign or require five useful sources as an arbitrary eligibility rule for analysis.

MMR stays off during representation selection. Once reasonable groups exist, one membership-overlap diversification comparison may be considered on development outputs only if budget and evidence remain. It is not a requirement to finish this stage. No disciplinary-distance bonus and no online posterior sampling.

## 6. Development evaluation that answers the right question

Use all 35 already-prepared development scopes and all 155 eligible researchers for the representation experiment, while continuing to account for all 90 development scientific reservations and 30 controls. This is not a new five-call pilot. Do not pretend the unprepared reservations were numerically evaluated.

Compare exact incumbent E0, the new representations, and simple whole-call top-k at matched team size. Preserve no-group/abstention cases in the yield comparison; do not invent groups solely to obtain a matched comparison.

Reuse existing model judgments whenever the person/call evidence and task are genuinely identical. New ranking scores or a new algorithm name do not require paying again for the same relevance question. Pay only for unjudged newly surfaced people/groups and a predeclared representative sample of alternatives. Preserve unresolved failed items; a meaningful new question is not a license to relabel old failed requests for automatic replay.

Keep the source/profile evidence and judge rubric consistent across arms. Do not give the judge an arm's richer generated rationale or numerical score. Explain selections from original text, never from a vector value or generated claim of capability.

Report separately:
- Individual ranking quality, list lengths, empty lists and false-positive examples.
- Useful primary groups, every primary member's relevance, and group yield.
- Alternative quality by rank, unique groups and repeated member occurrences.
- Scientific transfer versus unrelated topical overlap.
- Explanation faithfulness versus recommendation usefulness.
- All prepared versus action-admitted outcomes and all reservation dispositions.
- Paired common-source effects and source-group uncertainty.

Retain the previously agreed 80% relevance, 5% unrelated-member, usefulness and yield targets with their stated limitations. Do not lower them after results. Do not declare the independently feasible-scope target measured when feasibility is still unknown. Development comparisons remain development evidence, not Stage 3 confirmation.

Select the simplest representation that earns an advantage without destroying useful coverage. Do not require E3 to win. A ranking gain from E2 is an acceptable simpler result. If none improves the central relevance problem, finish the report with that conclusion; no automatic cross-encoder, new provider or next tuning cycle follows.

Marc's existing 20-item development packet remains the only requested development packet; do not request replacements or new items. Record any returned judgments with their original context. Keep the final 20-item allowance and holdout sealed. Do not claim the machine judge is an independent human expert.

## 7. Updates, space identity and runtime robustness

### Changes invalidate the right objects

- With independent phrases, an edit can invalidate only affected phrase rows plus any dependent combined document.
- With combined profiles, a material change invalidates that person's global vector.
- With contextual chunks, a material change can affect **all chunks of that person**, because every chunk used the shared document context. Re-embed the person as a unit; do not reuse a chunk solely because its own text is unchanged.
- A call-purpose change invalidates any aspect queries containing that purpose. A changed child must not alter another child's scientific text.
- Display-name-only changes update metadata, not text vectors when names are excluded.

Contextual vector keys must bind the model/version, endpoint/input role, dimensions, complete ordered document, chunk identity/order and preprocessing. Identical phrases in two different profiles are not interchangeable contextual cache entries. Request batching across independent documents must not change their meaning or identity.

Use one coherent published package. Never mix query/document spaces, new profile metadata with incompatible old vectors, or stale membership scores with a new registry. Material input/model changes invalidate derived matrices and option caches. Recalculate on demand; do not schedule a rebuild of all teams.

A user-created manual researcher or edited free text is not silently a prepared vector. Preserve the existing manual workflow without sending private text to providers. New registered public information becomes numerically available after normal ingredient preparation/publication.

### Serving and interface

Publish only the winning representation's ingredients, not all experimental vector spaces. Exclude test-team outputs, judge verdicts and training/private caches from public packages. Explanations use existing evidence fields and truthful suggested-applicability language. Do not change fixed presentation wording or force stronger evidence badges to display candidates.

Measure real bytes, memory and cold/warm calculation with the existing loader. The reported D2 package/runtime is a baseline, not proof a new contextual package fits. Preserve existing performance targets and staged E2E authority. A preparation failure or unsupported model must not trigger a paid user-click fallback.

## 8. Cost and trusted execution

The supplied D2 checkpoint records $2.279110 spent, $3.720890 remaining through the Stage 2 ceiling, and $7.720890 overall. Restore the execution-time authoritative ledger before spending. These amounts are reported checkpoints, not an invitation to reset usage. [R1, lines 213–232]

Keep authorization `on-demand-team-offline-v2-20260909`: $10 total, cumulative <=$6 through Stage 2, at least $4 reserved for later stages. Count embeddings, queries, contextualization, judging, probes, failures and uncertain reservations. Account free credits are not assumed.

Official prices checked September 10, 2026 list `voyage-4-large` and `voyage-context-4` at $0.12 per million tokens and lite at $0.02. For scale, one million billed tokens at $0.12/M costs $0.12; the real estimate must use measured complete inputs and repeated context, not that illustration. [S5]

Before dispatch, inventory exact distinct inputs, conservative tokens, bounded requests and new-judgment needs across D3 and the remaining stages. Reuse purchased work where identities match. Do not start with a repeated whole-judge campaign. If the plan cannot fit, complete safe zero-paid comparisons and report the precise missing evidence without requesting a larger budget.

Use the existing main-only trusted executor and durable ledger. Giving this plan to Codex authorizes only the narrowly reviewed helper changes needed to allow `voyage-4-large`, `voyage-context-4`, deterministic frozen-profile input construction, and their documented request shapes, while retaining exact source/profile ownership, bounded data and budget controls. This is not arbitrary model/endpoint access.

Permitted helper work includes focused tests, required CI, independent exact-head review, protected merge and bounded manual execution. Do not check out/run untrusted experiment code with provider credentials, change permissions, add a schedule, merge the recommender, enable the old Sonnet service, or deploy a cohort during D3. Reuse accounting; do not build another budget framework.

Do not migrate historical spend into a fresh allowance. Preserve exact failed/uncertain requests and irreversible dispatch semantics. Use the existing bounded review/convergence policy; do not bypass required review or security controls.

## 9. The original four stages remain the project structure

### Stage 1 — Already completed; do not repeat

Preserve the interface inventory, existing experiment branch, grouped development/holdout manifests, old reports, source-selected rollout policy and ledger history.

### Stage 2 — D3 representation experiment and final development choice

Perform the bounded comparison above. Start with zero-paid input manifests and API contract tests, then a small source-stratified wiring batch, followed by the complete prepared development set. The first small batch is not the end of the stage.

Deliver `docs/team-recommender/reports/stage-2-embedding-revision-d3-report.md`, exact candidate/ingredient identities, a winner or a precise no-winner conclusion, and an updated experiment state. STOP FOR USER REVIEW. Do not open the holdout or run Stage 3 automatically.

### Stage 3 — Independent confirmation and unchanged-interface validation

Only after explicit approval of the Stage 2 report: prepare the winning representation for the sealed holdout without tuning on its outputs. Evaluate the agreed grouped 90+30 holdout and report preparation/eligibility gaps honestly. Run the complete configured browser/E2E/accessibility suite, including cold loads, edits, stale/corrupt snapshots, source expiration, profile changes and zero paid network requests.

Prepare the source-selected 50/150 rollout ingredient inventory and both routing configurations. Retain the agreed target of 150 current eligible scopes across at least 80 parent opportunities, including at least 50 eligible child scopes and six research families where the genuine inventory permits. This is input preparation, not 150 precomputed sets of teams. The present 18/150 readiness gap remains visible. Only predefined source-based reserves may address source closures; do not replace difficult calls based on recommendation outcomes or fabricate children to reach the count.

An incompatible source inventory may require an explicit user-reviewed adjustment at this boundary rather than an open-ended source-expansion project. Do not claim all 150 are ready from a 35-scope test.

Measure the retained targets: p95 cached group/edit work under 200 ms, p95 calculation after inputs arrive under 1 second, and p95 cold click-to-interactive within 5 seconds on the declared 20 Mbit/s / 150 ms-latency reference. Report actual transferred bytes against the 8 MiB ingredient ceiling and additional browser heap against 48 MiB; distinguish throttled tests from physical devices. Do not move targets after seeing failures.

Deliver the complete Stage 3 report with pass/fail/inconclusive/not-run status, real prepared counts, performance, limits and exact release identities. STOP before production.

### Stage 4 — Activate prepared inputs and verify on-demand use

Only after approval: protected release to the source-selected 50-scope cohort, verify its exact serving state and existing interface, then expand the already-tested configuration to 150. Separate release identities and affected checks still apply. Preserve valid legacy coverage outside the new route and the normal rollback reference.

No source collection, paid team generation, unrelated Worker deployment, subscriber test email or profile mutation is implied by activation. Demonstrate that groups appear through local computation after a click, that edits recalculate without provider calls, and that invalid input packages fail safely.

Deliver actual live prepared/source/parent/child counts, recommendation outcomes and limits, network evidence, costs, rollback identity and a final status report. STOP before wider expansion.

## 10. Required D3 status report

The full report must distinguish inspected, implemented, executed, judged, reviewed and deployed. Include:

1. Actual branch/head/worktree, precise helper PR/run identities, unchanged production.
2. Exact embedding input examples for a call, combined researcher profile and contextual chunks. Identify which fields were excluded and why.
3. Researcher-object/claim hash proof of no enrichment; compatible source/registry identities.
4. E0/E1/E2/E3 availability, observed results and missing work; separate model-strength, document-granularity and query-format effects.
5. Admission/calibration rules, grouped development procedure and labels' actual target; no false probability claim.
6. Real quality/yield/alternative/explanation measurements, denominators, missing judgments, uncertainty and concrete failure examples.
7. Final representation/scorer/optimizer choice or a supported no-winner conclusion; optional hybrid/Bayesian/MMR status.
8. Whole-document contextual invalidation and cross-person isolation tests; exact cache/space behavior.
9. Interface preservation, no production team-inventory dependency, zero paid interactions, real package/resource measurements and unrun Stage 3 tests.
10. Cumulative ledger and remaining funds/human allowance; source-selected 150-scope readiness, not generated-team counts.
11. READY / READY SUBJECT TO EXISTING MARC AUDIT / REVISE / DEFER, with the smallest justified next stage and a literal STOP.

Do not close the stage just because a helper merged or one good group appeared. Do not claim a win by discarding abstentions, choosing a new holdout, upgrading vague profile statements to capabilities, or returning fewer suggestions without reporting yield.

## 11. Plain-English summary

We will compare three ways of describing a researcher to the computer: their individual interests, all their existing interests together, and individual interests that retain the context of the whole profile. We will also check whether a stronger embedding model helps.

The researcher records will not be rewritten. The experiment changes how existing information becomes reusable numbers. A combined profile may be best; contextual interests may preserve niche expertise better. We will measure rather than presume which wins.

Those numbers are prepared only when their underlying information changes. Clicking Build a team then performs cheap local calculations. Teams and alternatives are not stored in advance as a production inventory. Changing one researcher may change future recommendations across many calls without requiring a job to regenerate all those teams.

We will preserve scientific relevance, usable alternatives, truthful explanations, the current interface and the $10 total ceiling. First finish the development comparison, then independently validate the winning approach, then activate the prepared inputs at meaningful scale. Each remaining stage ends in a full report and a stop.

## 12. Instruction to give Codex

Paste or attach THIS ONE DOCUMENT to the existing experiment conversation, with:

> Execute the Stage 2 D3 continuation in this document only. Read the existing local reports, actual latest checkpoint and applicable AGENTS first; preserve all prior work. The document's scoped helper/model/input-format authority applies within the unchanged $10 total and $6 cumulative Stage 2 ceilings. Test richer reusable embeddings, not a reranker or pre-generated teams. Preserve researcher records and the interface. Complete the bounded development comparison, deliver the full D3 report, and STOP before Stage 3.

This document controls the D3-specific differences from the earlier plan; unrelated safety, repository and reporting policies remain. No second plan folder, restarted branch, new allowance or separate prompt package is necessary.

## Sources and evidence basis

[R1] User-supplied **Stage 2 D2 ranking revision — completed automated work; REVISE**, September 10, 2026; repository report path `docs/team-recommender/reports/stage-2-ranking-revision-d2-report.md`. D2 runtime/input checkpoint reported as `ed303ab367ccb2f0bec3f0e62acf3ed45e9809a6`. Treat it as historical evidence; resolve actual execution-time state, never reset to it.

[S1] Voyage, **Text Embeddings**, checked September 10, 2026: `https://docs.voyageai.com/docs/embeddings`.

[S2] Voyage, **Contextualized Chunk Embeddings**, checked September 10, 2026: `https://docs.voyageai.com/docs/contextualized-chunk-embeddings`.

[S3] Voyage, **Contextualized chunk embedding models — API reference**, checked September 10, 2026: `https://docs.voyageai.com/reference/contextualized-embeddings-api`. Parts of the reference still name the older model; use the current guide for model choices and verify actual supported request shapes before metered work.

[S4] Voyage, **voyage-context-4**, June 29, 2026: `https://blog.voyageai.com/2026/06/29/voyage-context-4/`. Vendor benchmark results are not Funding Finder validation.

[S5] Voyage, **Pricing**, checked September 10, 2026: `https://docs.voyageai.com/docs/pricing`. Recheck at execution; no account-specific free-credit assumption.
