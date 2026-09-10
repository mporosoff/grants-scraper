> Current C2 execution: trusted executor merged; real vectors and development outputs now exist. See evaluation-C2-execution.md and receipts/c2-development-judge-plan.json. Prior zero-run/unavailable-route and optional-comparison omissions below are historical, superseded by C2. Stage 3 remains unauthorized.

# Fixed offline judge protocol — E1/B1 v2, not executed

Authority: PLAN v2.0 + explicit user amendments E1, B1 and C1. Stage 2 is approved; model/human judgments completed: **0/0**. Marc Porosoff is the sole confirmed human reviewer. One $10 ceiling covers all stages, cumulative $6 through Stage 2 with at least $4 for later stages. C1 authorizes the narrow task-specific trusted prerequisite. Proposed PR #215 remains unmerged at a review-convergence checkpoint; operational execution is still unavailable. Prior protocol/prompt/schema and the rejected $69 budget are preserved in history. B1 batching replaces the former one-request-per-item cost plan, without changing the semantic rubric, grouped cases or acceptance targets.

## Judge, evidence, and execution

Freeze one primary judge: Anthropic `claude-sonnet-5`, fixed Messages API model ID, default supported sampling/thinking settings, strict compact JSON output, maximum 512 output tokens per bounded packet. Do not set unsupported temperature controls or call model outputs deterministic. Exact request/cache identities produce reproducible retained judgments; they do not guarantee identical new samples. Pin returned model, prompt/schema hashes, transport revision and inputs for every item; model drift or an incompatible returned identity stops that evaluation cohort.

Anthropic is already configured in `config/offline_ai.json`; recent main-only run `34402343578` completed operationally. This does not assert scientific quality. The protected-main boundary `.github/workflows/offline-ai-evaluation.yml` and `tools/offline_ai.py:Client.json` already support exact-cache keys, durable reservations, explicit model response validation and finite attempts. However, existing workflow phases and checkpoint identities belong to the previous experiment. **There is no ready authorized standalone judge dispatch for this task.** The C1-authorized narrow preparation/evaluation prerequisite must accept allowlisted public input packets and a new ledger; it must not run recommender branch code with secrets, invoke the old qualification phases, or mutate production service/release state. Stage 2 feature work stays isolated; this prerequisite remains unmerged after the recorded review-convergence stop.

The judge runs in a fresh evaluation process/context per uncached item, with no implementation conversation, tools, browsing, prior judge answers, expected winners or optimizer scores. Source strings are untrusted quoted data, not instructions. The evaluator receives blinded item packets exported from the frozen evaluation inputs; it cannot edit the recommender or pick a winning arm. Separate storage for model judgments, human responses and deterministic test receipts.

Preparation currently proposes zero LLM aspect extraction. Thus no aspect-generating LLM family needs to be separated from the judge. If separately approved future preparation uses Sonnet, disclose the same-family limitation before final freeze; do not add a new provider automatically. This judge also shares a family with historical Sonnet work and may share systematic errors. Human audit and objective checks constrain claims but do not prove full independence.

## Packet and rubric

Packet fields: blinded item ID, source scope/approach reference, original bounded call spans with locators/hashes, explicit source conditions/exclusions, original relevant public profile passages with claim IDs/revisions/URLs, task type, and a comparable-format candidate or pair. Semantic packets exclude generated explanation prose. Retain counterevidence and qualifiers; never crop away inconvenient clauses. If original evidence cannot fit the predeclared 12,000-token per-packet bound and the aggregate phase bound, record an unevaluated/insufficient-input item; do not invent an answer or pay for unbounded context. Use the model's current tokenization or conservative byte ceiling, including prompt/schema/framing, before reservation.

Individual label definitions:

| Label | Meaning |
|---|---|
| strong | Specific, source-backed connection worth a scientific discussion |
| plausible | Reasonable contribution or method transfer; application/extent remains uncertain |
| unrelated | No meaningful connection or generic overlap only; does not mean the person is incompetent |
| insufficient-information | Available evidence is too thin/ambiguous to assess |

Group items ask whether the complete group is worth discussion and whether contributions complement each other under one coherent source approach. Compare at matched size; allow A/B/tie/unresolved. Do not require disciplinary distance, prior collaboration or certified facilities. Feasibility is reviewed from source plus relevant directory evidence without seeing algorithm outcomes first. Source-feasibility/negative controls remain distinguished from algorithm refusal to output.

**Explanation faithfulness is a separate item/request**, after source-only semantic judging, with original evidence plus the exact explanation. It asks only whether the text overstates or invents expertise, source requirements, facilities or certainty, with `faithful / unsupported / insufficient-information`. No semantic score is shown. A plausible match with an unsupported explanation is recorded as both plausible and unsupported; one never cancels the other. Citation identity/span errors are deterministic failures even if the judge approves.

Use `judge-prompt.md` and `judge-output-schema.json`; each item has its own compact verdict and evidence reference; a bounded shared note records limitations. Same-scope model packets may share original evidence once and include at most ten distinct individual items or primary/two alternatives plus one matched-size pair. No per-person hidden adjudication inside a single human group item. Model requests cannot assert identities, exact quotations or constraints without deterministic checks. `tools/team_recommender_evaluation.py` implements development-only eligibility, deduplication/occurrences, balanced ordering and pre-dispatch packet bounds; it executes no judge.

## Finite item inventory and cost

The exact unique judgment count remains unknown until real outputs exist. These are bounded slots, never executed labels. Current B1 plan:

| Packet type | Stage 2 development | Stage 3 final |
|---|---:|---:|
| Source-only coherent-scope/conditions checks | 90 | 0 (use frozen preparation receipts; unclear feasibility remains unknown) |
| Top-five person occurrences from each of A/B, <=10 per same-scope packet | 90 | 90 |
| Primary and up to two alternatives, plus matched-size A/B comparison | 90 | 90 |
| Source/edge controls | 30 | 30 |
| Separate source-selected explanation audit | 30 | 30 |
| Predeclared balanced order swaps | 10 | 10 |
| Maximum one transport/format retry per affected packet, global cap | 10 | 10 |
| **Maximum judge requests** | **350** | **260** |

All 90 scientific reservations and 30 control slots per split remain in denominators. Optional C/D and MMR semantic campaigns are omitted. Up to 1,800 individual, 540 complete-group, 180 matched-size comparison, 90 source-only, 60 control and 60 explanation slots across phases are not independent scientific cases. Exact deduplication retains every algorithm occurrence; absent teams/options yield missing outputs, not fabricated items. Source feasibility is not inferred from recommendation refusal. The explanation sample is 30 source-hash-selected cases per split, rather than the former 90; report its actual denominator. This is a declared B1 sampling change, not a full explanation-quality census.

Every request including correction has <=12,000 conservative input tokens (UTF-8 serialized body bytes plus the existing 1,024-token framing margin when an exact tokenizer is unavailable) and <=512 output tokens. Variable packet sizes share an aggregate input envelope averaging at most 4,096 tokens per maximum planned request. Stage 2 input/output reservations are bounded to 1,433,600/179,200; Stage 3 to 1,064,960/133,120. Total judge bounds remain 2,498,560 input and 312,320 output tokens, 610 requests. At conservative $2.50/M input and $10/M output, the aggregate reservation is $5.376 development + $3.9936 final. A maximum-size individual request reserves $0.03512; $0.01536 is the planned average ceiling, not the per-request maximum. Actual base prices are $2/$10. No cache/free discount is assumed. The ledger counts every attempt against the aggregate token and request limits even after a cheaper actual receipt.

Preparation has <=80 embedding attempts, <=3,840 unique missing rows, <=10 million billed input tokens and $0.20. Stage 2 modeled reservation <=$5.576; whole experiment <=$9.5696, with $0.4304 unallocated inside $10. Stage 4 plans zero metered calls. Larger substantive-evidence packets consume more of the same aggregate allocation; they do not raise the budget or silently reduce reported case denominators. Later-stage approval is still required.

Batch shared original source evidence once, preserving relevant profile passages and counterevidence. Use compact response aliases with an exact retained mapping to item hashes. The output cap must accommodate every separate verdict. If meaningful evidence or output cannot fit, defer the packet with its missing denominator; do not crop inconvenient material or retry until favorable. Actual fit across real prepared outputs is unmeasured because no compatible ingredient vectors/route exist. The plan is an enforceable cost ceiling, not a claim that all semantic work already fits or will pass. No paid token-count probe is authorized outside the same ledger.

Prices rechecked September 9, 2026: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) $2/$10 per million for Sonnet 5, [Voyage pricing](https://docs.voyageai.com/docs/pricing) $0.02/M for voyage-4-lite. All failures, retries and uncertain requests remain charged/reserved in the same `budget-ledger.json`. No old qualification credit or repeated allowance grant. The original $69 proposal and 3,025-request plan remain historical only.

## Bias, disagreement and systematic errors

Deterministic item hash assigns pair orientation, alternated within family/phase strata to balance left/right counts (difference <=1 where possible). Human order is independent of model order. Ten comparison slots per phase are fixed by source/item hash for swapped repetition, not by disagreement. Exact substantive evidence is unchanged; only A/B order swaps. Map labels back to the same candidates. Non-tie conflicting mapped outcomes become unresolved and remain in denominators; never choose the favorable verdict.

The 20 development human checks assess rubric intelligibility and gross judge errors. Report raw four-label confusion tables, reasonable/unrelated disagreements, unable-to-assess, exact agreement on assessable items **and** requested-item denominators, source-family/control slices and exact binomial intervals. Report systematic failure patterns: broad source purpose, invented apparatus/clinical access, generic overlap, real transfer rejected, verbosity, source alternatives, and explanation overstatement. No population human-precision estimate from 20 selected cases. Cohen kappa may be descriptive only with sparse category counts disclosed; no threshold hides disagreement.

Proposed caution flags before final freeze: >20% reasonable-versus-unrelated disagreement among assessable development human items; >10% orientation conflict across the 20 planned order-swap items; or any repeated unsupported-expertise/source-invention pattern. Small-sample uncertainty is shown. These flags trigger a disclosed reliability limitation and user-reviewed revise/defer decision, not new providers/manual rounds or an autonomous retry loop. Objective identity/privacy/source violations block release regardless of model agreement. Do not change the judge protocol using final audit outcomes.

Final 20 human items are separately preselected in `manifests/human-audit.json` using only source IDs/kinds, before recommendation scores or judge results. Model scores never select easier cases. Fifty reserved rollout scopes also belong to holdout: Stage 2 may prepare those inputs but must not calculate or inspect their recommendation outputs, even for a rollout demonstration. The final human set is unexposed until Stage 3 and the finalist/protocol freeze. Human skips/unavailable outputs are retained and never automatically replaced. Development prompt concerns may be reported at the Stage 2 boundary; any material protocol revision preserves old judgments/version and cannot reclassify earlier outputs as fresh evidence.

## Training and final validation

Machine development labels may train C/D on grouped development folds. They are explicitly noisy machine labels. Sampling weights/representative subset must be saved after actual aspects exist. Score calibration can only be claimed relative to that sampled judge event; agreement with the training judge is not calibrated human preference. Compare learned models with B and A using paired grouped uncertainty, discrimination and reliability bins/counts, not Brier loss alone. Prefer the simpler baseline if value is inconclusive.

Freeze primary, at most the already-counted simpler fallback, rubric/prompt/schema/model/transport, source/group identities, transforms, thresholds, selection rule and analysis code before opening holdout recommendation results. Report semantic targets as model-estimated and capped human observations separately; insufficient-information, missing/no-group results, all-case/independently feasible denominators and clustered intervals remain visible. A machine label is never written into runtime `directEvidence` or a public proof badge. Final human or holdout evidence cannot be used for tuning and still called independent.
