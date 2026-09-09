# Annotation work packet — Stage 1

Status: no newly commissioned reviewers, no completed human judgments, no permission to contact anyone. The user was asked about existing labels/reviewer availability during Stage 1. Until an answer identifies actual people and commitment, all roles below are **unassigned**. Repository claim review is evidence-admission history, not a label for a new scientific recommendation. Historical Sonnet/developer judgments are exposed diagnostics, not independent human labels.

## Rubric

Question: based on this exact public passage and source-owned scientific contribution, would a knowledgeable evaluator reasonably discuss that contribution with this researcher? Do not certify facilities, eligibility, willingness, clinical access or proposal readiness.

| Label | Definition | Metric treatment |
|---|---|---|
| Strong useful match | Clear specific relevance to the contribution with a current supporting passage | Reasonable |
| Plausible contribution/transfer | A defensible method or scientific relation with stated application limits | Reasonable, separately report transfer |
| Clearly unrelated | No meaningful relation, generic overlap only, or explicit source constraint rules it out | Unrelated |
| Insufficient information | Passage/source too thin or ambiguous to judge | Explicit unresolved count; not a success and not silently removed |

Separately record source coherence, independently feasible group (`yes/no/unclear`), actual passage identity/currentness, direct versus expressed-interest evidence, and explicit constraint violations. Feasibility review sees source and eligible directory **before** seeing an algorithm's proposed group. It need not certify qualifications or predict grant outcomes.

## Sampling and workload

Target 600 development aspect/person judgments: 400 probability-sampled rows stratified by source family and passage-count band, 200 deliberate difficult/transfer/generic/negation cases. The representative component must record frame size, selection seed, inclusion probability and stratum weight after real aspects exist. Do not fabricate those numbers now or use enriched rows as deployment probability calibration. Holdout uses its own representative sample if calibrated probabilities are claimed.

Two knowledgeable reviewers are needed for 150 double-rated rows (25% of 600); remaining rows need one rating. Blind arm names, scores, ranking position and other reviewers' answers where practical. Preserve independent initial ratings, disagreement counts and rationales. Resolve disagreement in discussion with a named adjudicator; retain unresolved insufficient-information labels. The adjudicator may be one of the actual reviewers, disclosed, not another LLM impersonating one.

Estimated **not executed** development workload: 750 ratings × 2–3 minutes = 25–37.5 reviewer-hours, plus 4–8 hours disagreement handling. Source/coherence/approach preparation for up to 330 unique scientific scopes at 5–10 minutes adds up to 27.5–55 hours; source feasibility pre-review for 180 corpus scopes at 5–10 minutes is 15–30 hours (combine with preparation where the same real reviewer performs both, recording overlap). Stage 3 top-five people plus primary/two alternatives on 90 held-out candidate scopes means up to 450 person occurrences and 270 group assessments before deduplication, further-option audits or post-edit checks. At 2–3 minutes/person and 4–6 minutes/group that is 33–49.5 hours, plus disagreements and feasibility review. These are planning estimates, not booked availability or paid annotation approval.

## Fillable offline table

`annotation-template.csv` is an empty schema, not a fabricated completed row. Keep completed reviewer names/contact details/private notes in an access-controlled location; commit only consenting anonymized reviewer IDs, methodology, counts, and safe evidence references. Public ingredient assets must not contain evaluation labels or private reviewer data.

Required columns: judgment ID, split, group ID, scope ID, approach/aspect IDs, researcher and claim IDs/revisions, source locator/hash, profile passage hash, sampling stratum/probability/weight, reviewer pseudonym, rating, exact evidence status, rationale, independent timestamp, blinded arm token, disagreement/adjudication status. The empty template cannot be fitted or scored.

## Availability consequence

Missing labels allow untrained fixed-score numerical development and synthetic contracts after Stage 2 approval. Logistic/Bayesian fitting, calibration claims, quality target passes and independent final scientific acceptance remain **not run** until real evidence exists. No successful team yield or false-positive rate is claimed from the Stage 1 fixtures. Obtain actual reviewers and finish source-group audit before claiming the 240-case evaluation is ready.
