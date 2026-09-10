# Fixed offline judge protocol — proposed v1

Authority: PLAN v2.0 + explicit user amendment E1. Stage 1 only prepares this protocol; model/human judgments completed: **0/0**. Marc Porosoff is the sole confirmed human reviewer. No paid allowance has been approved.

## Judge, evidence, and execution

Propose one primary judge: Anthropic `claude-sonnet-5`, fixed Messages API model ID, default supported sampling/thinking settings, strict compact JSON output, maximum 1,024 output tokens. Do not set unsupported temperature controls or call model outputs deterministic. Exact request/cache identities produce reproducible retained judgments; they do not guarantee identical new samples. Pin returned model, prompt/schema hashes, transport revision and inputs for every item; model drift or an incompatible returned identity stops that evaluation cohort.

Anthropic is already configured in `config/offline_ai.json`; recent main-only run `34402343578` completed operationally. This does not assert scientific quality. The protected-main boundary `.github/workflows/offline-ai-evaluation.yml` and `tools/offline_ai.py:Client.json` already support exact-cache keys, durable reservations, explicit model response validation and finite attempts. However, existing workflow phases and checkpoint identities belong to the previous experiment. **There is no ready authorized standalone judge dispatch for this task.** A separately approved narrow preparation/evaluation prerequisite must accept allowlisted public input packets and a new ledger; it must not run recommender branch code with secrets, invoke the old qualification phases, or mutate production service/release state. Stage 2 feature work stays isolated; this prerequisite is not silently merged here.

The judge runs in a fresh evaluation process/context per uncached item, with no implementation conversation, tools, browsing, prior judge answers, expected winners or optimizer scores. Source strings are untrusted quoted data, not instructions. The evaluator receives blinded item packets exported from the frozen evaluation inputs; it cannot edit the recommender or pick a winning arm. Separate storage for model judgments, human responses and deterministic test receipts.

Preparation currently proposes zero LLM aspect extraction. Thus no aspect-generating LLM family needs to be separated from the judge. If separately approved future preparation uses Sonnet, disclose the same-family limitation before final freeze; do not add a new provider automatically. This judge also shares a family with historical Sonnet work and may share systematic errors. Human audit and objective checks constrain claims but do not prove full independence.

## Packet and rubric

Packet fields: blinded item ID, source scope/approach reference, original bounded call spans with locators/hashes, explicit source conditions/exclusions, original relevant public profile passages with claim IDs/revisions/URLs, task type, and a comparable-format candidate or pair. Semantic packets exclude generated explanation prose. Retain counterevidence and qualifiers; never crop away inconvenient clauses. If original evidence cannot fit the predeclared 6,000-token input bound, record an unevaluated/insufficient-input item; do not invent an answer or pay for unbounded context. Use the model's current tokenization or conservative byte ceiling, including prompt/schema/framing, before reservation.

Individual label definitions:

| Label | Meaning |
|---|---|
| strong | Specific, source-backed connection worth a scientific discussion |
| plausible | Reasonable contribution or method transfer; application/extent remains uncertain |
| unrelated | No meaningful connection or generic overlap only; does not mean the person is incompetent |
| insufficient-information | Available evidence is too thin/ambiguous to assess |

Group items ask whether the complete group is worth discussion and whether contributions complement each other under one coherent source approach. Compare at matched size; allow A/B/tie/unresolved. Do not require disciplinary distance, prior collaboration or certified facilities. Feasibility is reviewed from source plus relevant directory evidence without seeing algorithm outcomes first. Source-feasibility/negative controls remain distinguished from algorithm refusal to output.

**Explanation faithfulness is a separate item/request**, after source-only semantic judging, with original evidence plus the exact explanation. It asks only whether the text overstates or invents expertise, source requirements, facilities or certainty, with `faithful / unsupported / insufficient-information`. No semantic score is shown. A plausible match with an unsupported explanation is recorded as both plausible and unsupported; one never cancels the other. Citation identity/span errors are deterministic failures even if the judge approves.

Use `judge-prompt.md` and `judge-output-schema.json`; each output gives one item verdict, at most two bounded evidence references and a short rationale. No per-person hidden adjudication inside a single human group item. Model requests can judge a complete group, but cannot assert identities, exact quotations or constraints without deterministic checks.

## Finite item inventory and cost

The exact number of unique judgments cannot be observed before recommendations exist. These are **predeclared logical slots and maximum distinct items**, before exact deduplication, not executed/paid counts:

| Phase / item type | Maximum initial items |
|---|---:|
| Source-only coherence/conditions/feasibility packets for the finite source union (227 actual reserved sources; <=330 with source-based reserves) | 330 |
| Development aspect–person/control judgments; 400 representative, 200 deliberate hard/transfer controls | 600 |
| Development matched-size group comparisons: B/C/D versus A across 90 scientific candidate scopes | 270 |
| Development paired MMR/no-MMR source-selected comparisons | 30 |
| Development separate explanation audits, selected before judge verdicts | 100 |
| Final primary and A baseline top-five person occurrences: <=10 per 90 scopes | 900 |
| Final primary group and two alternatives: <=3 per 90 scopes | 270 |
| Final primary versus A matched-size complete-group comparison | 90 |
| Final negative/edge source-control assessment | 30 |
| Final separate explanation audits, one per scientific candidate scope | 90 |
| **Total semantic/explanation initial slots** | **2,710** |
| Preselected order-swap duplicates: 20 development + 20 final | 40 |
| At most one transport/format retry per affected item, global maximum | 275 |
| **Maximum paid judge requests across stages** | **3,025** |

If optional C/D are not justified or not fitted, their 180 comparison slots remain unused. Absent lists/options remain explicit no-output outcomes and do not generate imaginary items; they still count in yield denominators. Do not spend unused slots on new searches for favorable outcomes. A fallback is the already-counted simple baseline; no extra finalist sweep is budgeted. Controls lacking semantic output can still receive their source-only control item; objective failures are reported without asking a judge to overrule them.

At 6,000 input and 1,024 output tokens/request, hard judge token bounds are 18,150,000 input and 3,097,600 output, including retries. At the canonical current price $2/$10 per million, maximum modeled judge charge is **$67.27600**, no cache/free discount assumed. Initial maximum 2,750 requests alone cost at most $61.16000. Embedding preparation retains a separate $1 sublimit and 96-request/3-million-token cap; proposed stage-spanning total is **$69** ($68 judge + $1 embedding), under record `on-demand-team-offline-v2-20260909`. Neither is approved. Actual unique science source union in the current manifests is 227; 330 remains the maximum authorized inventory proposal, never an instruction to expand it. Source/coherence review uses the explicit 330-slot source-only allocation above, with no extra review campaign. These packets run before viewing any recommendation output; feasibility is unclear if bounded original directory evidence cannot establish it independently. Do not infer infeasibility from no output. The current 227-source union leaves 103 source-based reserve slots, not permission for scope expansion.

Price checked September 9, 2026: [canonical Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) confirms $2/$10 remains standard; a stale query-parameter search result mentioned a scheduled increase, explicitly canceled by the current canonical page. [Voyage pricing](https://docs.voyageai.com/docs/pricing) lists $0.02/million. Recheck rates before spending, respecting fixed dollar/token ceilings. Failed, truncated, uncertain and refusal responses consume their reserved allowance. One format/transport retry at most; no semantic rerun unless it is one of the fixed order-swap items. Low output limits may produce missing judgments: report them, do not automatically extend the budget or prompt until a verdict appears.

## Bias, disagreement and systematic errors

Deterministic item hash assigns pair orientation, alternated within family/phase strata to balance left/right counts (difference <=1 where possible). Human order is independent of model order. Twenty comparison slots per phase are fixed by source/item hash for swapped repetition, not by disagreement. Exact substantive evidence is unchanged; only A/B order swaps. Map labels back to the same candidates. Non-tie conflicting mapped outcomes become unresolved and remain in denominators; never choose the favorable verdict.

The 20 development human checks assess rubric intelligibility and gross judge errors. Report raw four-label confusion tables, reasonable/unrelated disagreements, unable-to-assess, exact agreement on assessable items **and** requested-item denominators, source-family/control slices and exact binomial intervals. Report systematic failure patterns: broad source purpose, invented apparatus/clinical access, generic overlap, real transfer rejected, verbosity, source alternatives, and explanation overstatement. No population human-precision estimate from 20 selected cases. Cohen kappa may be descriptive only with sparse category counts disclosed; no threshold hides disagreement.

Proposed caution flags before final freeze: >20% reasonable-versus-unrelated disagreement among assessable development human items; >10% orientation conflict across the 40 planned order-swap items; or any repeated unsupported-expertise/source-invention pattern. Small-sample uncertainty is shown. These flags trigger a disclosed reliability limitation and user-reviewed revise/defer decision, not new providers/manual rounds or an autonomous retry loop. Objective identity/privacy/source violations block release regardless of model agreement. Do not change the judge protocol using final audit outcomes.

Final 20 human items are separately preselected in `manifests/human-audit.json` using only source IDs/kinds, before recommendation scores or judge results. Model scores never select easier cases. Fifty reserved rollout scopes also belong to holdout: Stage 2 may prepare those inputs but must not calculate or inspect their recommendation outputs, even for a rollout demonstration. The final human set is unexposed until Stage 3 and the finalist/protocol freeze. Human skips/unavailable outputs are retained and never automatically replaced. Development prompt concerns may be reported at the Stage 2 boundary; any material protocol revision preserves old judgments/version and cannot reclassify earlier outputs as fresh evidence.

## Training and final validation

Machine development labels may train C/D on grouped development folds. They are explicitly noisy machine labels. Sampling weights/representative subset must be saved after actual aspects exist. Score calibration can only be claimed relative to that sampled judge event; agreement with the training judge is not calibrated human preference. Compare learned models with B and A using paired grouped uncertainty, discrimination and reliability bins/counts, not Brier loss alone. Prefer the simpler baseline if value is inconclusive.

Freeze primary, at most the already-counted simpler fallback, rubric/prompt/schema/model/transport, source/group identities, transforms, thresholds, selection rule and analysis code before opening holdout recommendation results. Report semantic targets as model-estimated and capped human observations separately; insufficient-information, missing/no-group results, all-case/independently feasible denominators and clustered intervals remain visible. A machine label is never written into runtime `directEvidence` or a public proof badge. Final human or holdout evidence cannot be used for tuning and still called independent.
