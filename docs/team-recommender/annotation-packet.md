# Human review packet — E1, proposed v1

Marc Porosoff is the sole confirmed human reviewer. No second reviewer is assumed. Human judgments requested/completed so far: **0/0**. This document prepares the format only; no recommendations yet exist for review. The superseded pre-amendment draft is retained in history and is not active guidance.

## Exact cap and allocation

Hard experiment-wide cap: **40 compact requested items**, at most 20 development and 20 separate final-audit items. Each phase has 12 individual matches and 8 complete-team comparisons. Development individuals: 6 source-representative, 2 borderline, 2 method-transfer, 2 unrelated-control slots. Development groups: 4 representative, 2 borderline, 1 method-transfer, 1 unrelated-control slot. Final audit uses 12 source-selected individual positions and 8 complete-team comparisons selected before judge results, with family/child representation where available. Do not show only disagreements or favorable outputs.

One individual item asks one relevance label. One group item asks one overall worth-discussion/complementarity preference (A / B / tie / unable-to-assess); it does not request separate ratings of every member. Provide up to four members per group with short source-linked passages. An optional short reason does not create extra required subjudgments. If the packet would require dozens of judgments, split scope only within the unchanged 40-item cap or record unable-to-assess.

`manifests/human-audit.json` preselects source IDs, task type and masked item IDs without recommendations or judge scores. Development hard-case slots materialize only the named perturbation/transfer/borderline category; no searching repeated outputs for the most favorable example. Final individual position is chosen deterministically from 1–5; if the list lacks that position, record no-output/unable-to-assess. Do not replace the source or ask for a different item automatically. Actual source-representative does not mean statistically representative of human preferences; report that limit.

## Evidence-first packet order

1. Blinded item ID and task type; original bounded call evidence, coherent child/approach and explicit constraints, with exact source URLs/locators.
2. Relevant original public profile passages and exact researcher/claim IDs/revisions. No generated rationale in a relevance-comparison packet; explanation fidelity has separate model items.
3. A single question and labels: strong / plausible / unrelated / insufficient-information (individual), or A / B / tie / unable-to-assess (group pair). Algorithm names, numerical scores, expected winners and prior decisions hidden; balanced order independent of the judge's order.
4. Marc records assessment or unable-to-assess. Timestamp and request-counter update are durable. Only then may the judge's cached verdict be revealed for disagreement analysis.

Strong = clear contribution worth discussing; plausible = defensible relevance/transfer with limitations; unrelated = no meaningful connection on supplied evidence, not incompetence; insufficient-information = cannot assess. No expertise/facility/eligibility/willingness certification.

Every requested item counts against the cap, including skips, no-output and unable-to-assess. No replacements or extra rounds. Track development and final requested/completed/skipped separately. Additional human review needs explicit approval. Human evidence belongs in separately attributed records, never silently combined with model labels as expert truth.

## Work estimate and analysis

Per phase: 12 individual items × 2–3 minutes plus 8 group comparisons × 4–6 minutes = about 56–84 minutes. Entire experiment: about 112–168 minutes if all 40 are requested. This is an estimate, not work already done. No hundreds of human labels, source audits, double ratings or adjudicator time are required outside this cap. Model/source checks handle the wider corpus within the finite offline budget.

Compare Marc with the hidden-first model verdict using raw category confusion tables, reasonable/unrelated disagreements, unable-to-assess counts, assessable and all-requested denominators, and intervals appropriate to the small sample. Explain systematic errors. Marc's audit is limited product evidence, not multi-expert cross-field validation or calibrated preference ground truth. Do not tune against the final 20 items or rejudge conflicts until they agree.

## Storage template

`annotation-template.csv` remains header-only. `label_provenance` distinguishes human/model; `judge_protocol_id`, model identity and request/cache hashes apply to machine rows, while Marc's pseudonym and human request index apply to human rows. Retain source/claim evidence and sample inclusion fields. Keep private notes/access-sensitive reviewer material out of the public ingredient bundle. All real judgment rows are currently absent.
