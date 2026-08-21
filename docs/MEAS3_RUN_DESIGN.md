# MEAS-3 — classifier repeatability: run design, and the run

**Status: run 2026-08-24.** This document specified the experiment before it was
run; §§1–4 are as written beforehand, and the amendments below are marked with their
date so the pre-registration stays legible.

> **Correction, 2026-08-23 → 2026-08-24.** This document originally recorded three
> blockers, and **one of them was a misdiagnosis**. The credential was never absent
> from the machine: `ANTHROPIC_API_KEY` lives in the Windows **User** environment and
> Claude Code's tool subprocesses do not inherit it. Loading it explicitly in the same
> invocation authenticates against `claude-sonnet-5`. The claim that *a human must
> make the calls* is withdrawn. The other two blockers were real: **DEBT-9** is now
> closed by a frozen population, and **DEC-15** is resolved as direct HTTP with no new
> dependency.

---

## 1. Why MEAS-3 exists, now with a number

§11 caveat 2 measured **1 of 62 byte-identical spans flipping its verdict (1.6%)**
against the **0.9%** false-rejection signal Cov4's gate is meant to demonstrate. The
noise was larger than the signal, which is why the gate was called undemonstrable.

Computed this session from that same observation:

| Quantity | Value |
|---|---|
| Observed per-span flip rate | **1/62 = 1.61%** |
| **Wilson 95% CI** | **[0.29%, 8.59%]** |
| The signal it must resolve | 0.9% |

**The interval straddles the signal.** That is the quantitative form of "one
stochastic pass cannot claim zero false rejections", and it is why the original gate
wording cannot be satisfied by re-running the same single pass more carefully.

---

## 2. The three blockers, each isolated

### Blocker A — ~~no classifier credential~~ **misdiagnosed; cleared 2026-08-24**

The original isolation was correct about the *process* environment and wrong about
the *machine*:

| Layer | State |
|---|---|
| SDK | **present** — `anthropic 0.122.0` imports cleanly |
| Endpoint | **present** — `ANTHROPIC_BASE_URL=https://api.anthropic.com` |
| Credential | **absent** — `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` both unset |
| Call | `TypeError: Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set` |

**What was actually true.** The key is in the Windows **User** environment
(`[Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")`), and tool
subprocesses do not inherit it. Loading it in the same PowerShell invocation
authenticates and returns a completion from `claude-sonnet-5`. **The correct rule is
therefore operational, not human-in-the-loop:** every command that calls the API must
load the key itself, because shell state does not persist between tool invocations.

The original conclusion — *"the failure is credential absence… a human must make the
calls"* — is **withdrawn**, and §18.1 Cov4's matching sentence is struck.

**An `OPENAI_API_KEY` is present in this environment and was deliberately not used.**
§11's result is specific to `claude-sonnet-5` with adaptive thinking, and the whole
configuration finding — **88% precision at thinking-default versus 54% disabled** —
is a property of that model. Substituting a different model family would answer a
different question while looking like an answer to this one.

### Blocker B — ~~no frozen candidate population~~ **resolved 2026-08-24; DEBT-9 closed**

Was true as written. It is now fixed by building a *new* population rather than
reconstructing the old one — see §3.1, rewritten.

§11's span-level run used **114 spans** across `349554` (18), `360678` (70) and
`361526` (26), drawn from the **D4/D5 backfill generation**. That cache was
deliberately never committed, and **DEBT-1** records it as defective anyway (six
wrong-subject summaries, one missing span).

Verified this session: there is **no `data/subtopic_records.json`**, no committed
span-level artifact, and nothing under `evaluation/` holding spans. `git ls-files`
returns no candidate population.

**Regenerating it is not a substitute.** A fresh backfill (P4.4's run: 770 documents,
~53 minutes) produces a **different** population — Cov5 changed one document's span
count from 68 to 69, and §11's own numbers are keyed to the pre-Cov5 text. Comparing
new variance figures against §11's baseline would be comparing two different
experiments.

### Blocker C — `anthropic` unauthorized → **DEC-15 resolved 2026-08-24: no dependency added**

The decision was to call the Messages API directly over the already-pinned
`requests`, so §0.4 rule 7 stands unamended rather than excepted. Reasoning, and the
condition for revisiting it, are in the plan's DEC-15 entry.

§0.4 rule 7: *"Never add a dependency not named in this plan without stopping to ask.
Exactly one new runtime dependency is authorized: `pdfplumber`."* `anthropic` appears
in no requirements file. Both the MEAS-3 harness and Cov4's eventual production path
need it, so **that is a plan-level decision to take before either is written**, not an
implementation detail to slip in. Recorded as **DEC-15**.

---

## 3. The run design

### 3.1 Population — **redefined 2026-08-24**

**Arm A is no longer "§11's 114 spans".** That population cannot be rebuilt: its
artifact was never committed, and Cov5 changed extraction afterwards. Chasing it
would spend a full backfill to approximate a number that would still not match.

> **Arm A (current definition).** A **frozen post-Cov5 population of the candidate
> spans production actually produces today**, generated deterministically from
> committed evidence — the pinned URL *and* `sha256` in `data/document_evidence.json`
> — through the unmodified production path (`extract_containers` →
> `segment_document`). Frozen at `evaluation/meas3_population.json`; built by
> `tools/build_meas3_population.py`; reproducibility asserted by
> `tests/test_meas3_population.py` (**DEBT-9 closed**).

**Measured, and reported as produced rather than as targeted — the count was not
forced toward 114:**

| Arm | Record | Accepted spans | Method | Confidence |
|---|---|---|---|---|
| A | `360678` DOE Office of Science | **69** | `outline_structural` | medium |
| A | `361526` DOE Genesis Mission | **21** | `outline_structural` | medium |
| A | `363526` AFRL DEPSCoR | **8** | `toc` | high |
| A | `356623` ARPA-E SCALEUP | **7** | `numbered` | low |
| A | `362681` AFOSR Open BAA | **0** | — | `no_layer_accepted` |
| A | `363302` NETL | **0** | — | `no_layer_accepted` |
| **A total** | | **105 candidates** | | |
| B | `363594` aggregating agency page (BUG-9) | **0** | — | `no_layer_accepted` |
| B | `330175` F1 bare-numbered | **0** | — | `no_layer_accepted` |
| B | `362233` F4 named/bulleted | **0** | — | `no_layer_accepted` |
| **B total** | | **0 candidates** | | |

`349554` (AFRL PACER) is **deliberately excluded**: its topics live in a secondary
attachment reachable only through the Grants.gov detail API, which is not
deterministic from committed evidence.

**Two findings that arrived with the population, before any classifier ran.**

1. **The contaminants §11 measured against are gone.** `360678`'s
   *Multi-Institutional Teams* and *Open Science*, and `361526`'s five administrative
   spans, are **absent from today's output**. The producible population is
   essentially all true positives, so **Cov4's measurable risk today is false
   rejection, not missed contamination** — the inverse of the premise that motivated
   it.
2. **Arm B is empty in every branch.** No F1 candidates, no F4 candidates, and
   BUG-9's aggregating page now returns `no_layer_accepted` as well. **Cov4 cannot be
   exercised on the shapes P7 would later admit, because no mechanism produces
   candidates for them** — and building one is P7's job, which Cov4 gates. That
   circularity is recorded rather than worked around: *P7 is gated on Cov4 proving it
   can guard F1/F4, and Cov4 cannot be tested on F1/F4 until P7 produces candidates.*

**Arm B is retained as a declared, asserted-empty arm** rather than deleted, so the
gap stays visible and a later session that builds an F1 or F4 recogniser inherits the
requirement to re-run MEAS-3 against it.

### 3.2 Repeats, justified rather than picked

Computed this session, per span, from a per-call error rate `p`:

| `p` (per call) | R=1 | **R=3 majority** | R=5 majority |
|---|---|---|---|
| 1.6% (measured) | 1.60% | **0.076%** | 0.004% |
| 5% | 5.0% | 0.73% | 0.12% |
| 10% | 10.0% | 2.80% | 0.86% |
| 20% | 20.0% | 10.4% | 5.79% |

And for the **fail-closed** direction, where unanimity is required to *accept*:

| `p` | R=2 unanimous | R=3 unanimous |
|---|---|---|
| 1.6% | 0.026% | 0.0004% |
| 5% | 0.25% | 0.013% |
| 10% | 1.0% | 0.10% |

**R = 5 for the measurement.** Five repeats classify each span as stable (5/5 agree)
or unstable, bound the *pooled* flip rate at **3/570 = 0.53%** if zero flips are seen
(rule of three over 114×5 calls), and cost about 570 span calls — an order of
magnitude below what per-span certainty would need. **Bounding a single span's own
flip rate to ≤1% would take R≈30** (rule of three), which is why the design measures
population stability at R=5 rather than certifying each span individually.

**Do not** change the prompt between repeats. **Do not** majority-vote before
recording the raw per-run verdicts — the disagreement is the measurement.

### 3.3 Configuration, frozen

* model **`claude-sonnet-5`**;
* **`thinking` left at its default (adaptive)** — omitting this parameter is the
  measured difference between 88% and 54% span-level precision (§11);
* **a prompt committed before the run** (`tools/run_meas3.py`), asking §6.4b's
  question per span with the fail-closed direction stated. **§11's own prompt was
  never committed** — that is part of DEBT-9 — so this one is new, and it is a further
  reason the numbers are not comparable to §11's;
* temperature and every other parameter at the API default;
* inputs byte-frozen: the same title and the same excerpt text on every repeat.

### 3.4 Artifact

One JSONL row per *call*, never per span, so nothing is aggregated before it is
recorded:

```
{"span_id", "record_id", "arm", "run_index", "verdict", "reason",
 "input_sha256", "model", "thinking", "usage", "latency_ms"}
```

Plus a derived per-span summary with the four-way classification the package asked
for: **stable accept · stable reject · unstable · classifier error** (malformed or
missing verdict), and **every unstable span listed individually with its per-run
verdicts and reasons**, for qualitative inspection.

---

## 4. The decision table — what each outcome licenses

Written **before** the run, so the result cannot be reinterpreted to fit whatever
Cov4 design is convenient afterwards.

| MEAS-3 outcome | What it means | Cov4 design it licenses |
|---|---|---|
| **Zero flips across 570 calls** (pooled ≤0.53%) | The configuration is effectively deterministic at this population size | **One pass.** No ensemble. The simplest mechanism that satisfies the gate |
| **Flips confined to spans that are genuinely ambiguous** (corrupted excerpt, real borderline) and absent from obvious positives/negatives | The instability is in the data, not the classifier | **One pass plus an explicit `uncertain` state** for the flipping shapes, routed to the review queue rather than dropped |
| **Flips scattered across obvious positives or negatives** at ≤5% per call | The classifier itself wobbles, but bounded | **R=3, and unanimity required to accept.** Fail-closed asymmetry preserved: 0.0004% false-accept at the measured rate, and any disagreement becomes `uncertain` |
| **Per-call error >10%, or arm B markedly worse than arm A** | The gate cannot be made safe at proportionate cost, and F1/F4 are exactly where it fails | **Cov4 does not ship as an automatic gate.** Route everything to the review queue, and P7 stays closed |
| **Systematic arm A vs arm B gap** | The filter is fitted to outline-derived spans | Cov4 may gate arm-A-like spans only; **F1/F4 admission stays blocked** pending its own measurement |

**In every branch the fail-closed asymmetry is preserved**: no classifier verdict may
*create* structure, and an absent or unusable classifier publishes **nothing new**
rather than publishing unfiltered spans.

---

## 4a. The run — executed 2026-08-24

**Configuration as pre-registered:** `claude-sonnet-5`, `thinking` omitted (adaptive),
temperature at API default, the prompt committed in `tools/run_meas3.py` *before* the
run, **R = 5**, Arm A (Arm B has no candidates). **525 calls, 0 HTTP errors, 0
unparseable responses.** Raw rows: `evaluation/meas3_runs.jsonl` (one row per *call*).
Derived: `evaluation/meas3_summary.json`.

### 4a.1 Repeatability — the question MEAS-3 was asked

| Measure | Arm A | Arm B |
|---|---|---|
| Candidates | **105** | **0** (no mechanism produces any) |
| Calls | **525** | 0 |
| **stable accept** | **99** | — |
| **stable reject** | **5** | — |
| **unstable** | **1** | — |
| **classifier error** | **0** | — |
| Per-span instability | **1/105 = 0.95%** | — |
| Pooled per-call disagreement | **1/525 = 0.190%** | — |
| **Wilson 95% CI** | **[0.034%, 1.071%]** | — |
| Usage | 287,350 in / 25,826 out | — |

**The classifier is repeatable on this population.** Pooled disagreement is 0.19%,
below the 0.53% the design set as the "effectively deterministic" bar, and the single
unstable span is a *genuinely* ambiguous one rather than noise on an obvious case.

**The one unstable candidate, in full**, as the package requires:

| `360678:ixrs` — **(i) X-Ray Scattering** | verdicts: `reject, reject, accept, reject, reject` |
|---|---|
| run 1 | *"a description of a research program area/topic rather than a distinct fundable subdivision an applicant selects"* |
| run 2 | *"a program/research area description under BES, not a distinct fundable subdivision applicants select in this FOA"* |
| **run 3** | *"Names a specific research program area (X-Ray Scattering) under BES that applicants can propose research against."* |
| run 4 | *"a research area/topic description under a program, not a distinct fundable subdivision applicants formally apply"* |
| run 5 | *"a research topic/program description within BES, not a distinct fundable subdivision applicants select in this FOA"* |

The disagreement is **coherent, not random**: every run is arguing the same
distinction — *propose against* versus *formally select* — and lands differently once.

### 4a.2 The finding that matters more than the variance

**Five candidates were stably rejected, and four of them are genuine programmes.**

| Candidate | Human truth | Verdict |
|---|---|---|
| `360678` **(a) Microbiome Research** | A real BER programme in the FOA's own program list | **false reject** |
| `360678` **(b) Heavy Ion Nuclear Physics** | A real NP programme | **false reject** |
| `360678` **(d) Fundamental Symmetries** | A real NP programme | **false reject** |
| `361526` **10 - Securing U.S. Leadership in Data Centers** | One of the 21 Genesis Mission challenge areas the census verified as *"exactly the published list"* | **false reject** |
| `360678` **(n) Public-Private Partnerships** | **DEC-11's open question** — subject, or funding mechanism? Unresolved by a human | **not scoreable** |

Adding the unstable span, which rejects in 4 of 5 runs:

> **Measured false-negative (recall) rate: 4 of 104 scoreable candidates = 3.8%
> stable, rising to 5 of 104 = 4.8% if `(i) X-Ray Scattering` is counted at its
> majority verdict. Cov4's gate requires zero.** **Precision is unmeasured** — the
> population holds no contaminants to accept wrongly.

**No contaminants were available to catch.** The producible population contains none
(§3.1), so this run measures only the recall direction — the one that costs real
opportunities. **Precision and specificity were unmeasurable here**, which is exactly
why the Cov4 challenge set (§5a) was built.

### 4a.3 Repetition cannot fix this, and that is the structural point

The errors are **stable**, not noisy. An R=3 or R=5 consensus improves a *wobbling*
verdict; it does nothing for a verdict that is confidently wrong five times out of
five. **The variance mechanism the design was built to choose is not the mechanism
this population needs.**

### 4a.4 Adaptive thinking never engaged

`usage.output_tokens_details.thinking_tokens` was **0 on all 525 calls.** The
parameter was omitted, which is §11's "adaptive" configuration — but adaptive means
*the model decides*, and on this population it decided not to think, every time.

**That is a materially different condition from §11's**, where the 88%-versus-54%
difference was attributed to thinking rescuing spans with corrupted excerpts. Cov5
has since fixed those excerpts, so the trigger for thinking may simply be gone.
**"Thinking at default" does not guarantee thinking happens** — a distinction the
plan did not previously draw, and one any later session must not assume away.

### 4a.5 Comparison with §11, kept to what is legitimate

> §11 observed **1 flip among 62** reclassified historical spans, but **its exact
> population was not retained**. MEAS-3 uses a **new frozen post-Cov5 population** and
> therefore measures **current** repeatability rather than reproducing the historical
> rate. The prompt also differs, because §11's was never committed.

No matched subset is reported: the spans share titles with §11's population, but the
excerpts they carry are post-Cov5 and the prompt is different, so a "matched" subset
would imply a continuity that does not exist.

---

## 4b. Decision-table outcome, applied without reinterpretation

The table in §4 was fixed before the run. Reading it against the result:

| Branch | Matches? |
|---|---|
| Zero flips (pooled ≤0.53%) → **one pass, no ensemble** | **Yes on repeatability.** Pooled 0.19% [0.034%, 1.071%] |
| Flips confined to genuinely ambiguous spans → one pass + `uncertain` | **Yes.** The single flip is `(i) X-Ray Scattering`, coherently argued both ways |
| Flips scattered across obvious cases ≤5% → R=3 unanimity | No — there is no scatter to defend against |
| Per-call error >10% or arm B worse → Cov4 does not ship | Not on variance |

**So the variance question is settled: `R = 1` is licensed. No ensemble, no consensus
rule, no majority vote — the measured instability does not justify one.**

**But Cov4 is not thereby unblocked**, because the decision table governs *only* the
repeatability mechanism, and the binding failure is elsewhere:

> **MEAS-3 is complete. Cov4 remains blocked — on task definition and validation
> coverage, not on variance.** The gate's *"zero false rejections"* clause fails at
> **3.8%**, and **repetition cannot repair a stable error**.
>
> **Terminology, corrected 2026-08-25.** Those four rejected programmes are **false
> negatives — a recall failure**, not a precision failure. **Precision was and remains
> unmeasured on this population**, which holds no contaminants. An earlier revision
> called it "precision", inverting the direction of the error.

**Deliberately not done here:** the prompt was **not** tuned after seeing these
results. Doing so would convert a pre-registered measurement into a fitted one. The
next session should treat prompt/task definition as its own pre-registered
experiment against this same frozen population — and it now costs one command.

## 5a. The Cov4 prompt experiment — pre-registered 2026-08-25, run the same day

**MEAS-3 is untouched.** Its population, prompt, raw R=5 outputs, decision table and
105-candidate result are immutable. This is a *new* experiment that reuses the frozen
population as one of two arms.

### 5a.1 Diagnosis — the smallest common failure

All 25 rejection reasons behind MEAS-3's four stable false negatives repeat two moves:

> *"This is **descriptive background** on a research area…"*
> *"…not a distinct fundable subdivision applicants **select against**."*

The MEAS-3 prompt asks for *"something an applicant would actually apply against or
**select**"*. The model reads **select** as requiring a **formal application
category**, and reads a prose programme description as **background**. In a DOE
omnibus every genuine programme is precisely that — a named research area described in
prose that you propose work against.

**The model states the correct rule itself** in the single accepting run of the one
unstable span: *"Names a specific research program area (X-Ray Scattering) under BES
that **applicants can propose research against**."* So the decision rule is what
rejected them, not the model's capability.

`(n) Public-Private Partnerships` is **kept unresolved**: run 4 called it *"a general
funding mechanism"*, which is exactly DEC-11's open question, and DEC-11 says a human
settles it and **not from a model verdict**. It is excluded from every score below.

### 5a.2 The two populations

* **A** — the frozen MEAS-3 population, 105 candidates. Scored only where a committed
  label exists (19 copied into the challenge set); the other 86 are reported as a
  **descriptive accept-rate**, not as a score.
* **B** — `evaluation/cov4_challenge.json`, **36 real-document candidates: 23
  fundable, 12 contaminant, 1 unresolved**, every excerpt quoted from a
  digest-verified document, every label carrying its evidence, **all committed before
  any variant ran**.

### 5a.3 Results — 564 calls at R=1, 0 API errors, 0 unparseable

| Variant | A: recall | A: accept-rate (unlabelled) | B: TP | B: FN | B: TN | B: FP | B: recall | B: specificity |
|---|---|---|---|---|---|---|---|---|
| `V0_control` (MEAS-3 prompt) | **77.8%** (4 FN) | 96.5% | 16 | **7** | 11 | 1 | 69.6% | 91.7% |
| **`V1_propose_against`** | **100%** | 98.8% | **23** | **0** | 10 | 2 | **100%** | 83.3% |
| `V2_subject_vs_process` | **100%** | 100% | 22 | 1 | 11 | 1 | 95.7% | 91.7% |
| **`V3_subject_with_tiebreak`** | **100%** | **100%** | **23** | **0** | 10 | 2 | **100%** | 83.3% |

**The recall half is solved.** V1 and V3 keep **every** known genuine child on **both**
populations, including all four of MEAS-3's stable false negatives and the unstable
`(i) X-Ray Scattering`. The control loses 7 of 23 on the challenge set.

**By shape, on population B** (V1 and V3 identical except where noted):

| Shape | Truth | V0 | V1 | V2 | V3 |
|---|---|---|---|---|---|
| `f4_named_bulleted` (3) | fundable | **0/3** | 3/3 | 3/3 | 3/3 |
| `f1_bare_numbered` (2) | fundable | 2/2 | 2/2 | **1/2** | 2/2 |
| `f4_adjacent_decoy` (3) | contaminant | 3/3 | 3/3 | 3/3 | 3/3 |
| `f1_bare_numbered_decoy` (1) | contaminant | 1/1 | 1/1 | 1/1 | 1/1 |
| `navigation_toc` (1) | contaminant | 1/1 | 1/1 | 1/1 | 1/1 |
| `administrative_heading` (2) | contaminant | 2/2 | 2/2 | 2/2 | 2/2 |
| `policy_prose` · `eligibility_policy_prose` (2) | contaminant | 2/2 | 2/2 | 2/2 | 2/2 |
| `organizational_heading` (2) | contaminant | 2/2 | **1/2** | 2/2 | **1/2** |
| `aggregating_agency_page` (1) | contaminant | **0/1** | **0/1** | **0/1** | **0/1** |

**The F1/F4 answer is encouraging and is the point of the challenge set:** V1 and V3
separate genuine F4 focus areas from their adjacent review-criterion and
attachment-checklist decoys **3/3 and 3/3**, and genuine F1 research centres from the
document's own `3. Reserved` placeholder and its table-of-contents line **2/2 and
2/2**. The control got **0 of 3** F4 positives.

### 5a.4 The two contaminant classes that survive

1. **Cross-opportunity ownership — every variant fails, including the control.**
   `363594:x-other-foa-topic` is a topic whose own excerpt says it belongs to
   `DE-FOA-0003627` while the parent is `DE-FOA-0003215`. **4 of 4 variants accepted
   it**, two of them under prompts that state an explicit ownership rule. This is
   **BUG-9's exact fabrication surface**, and stating the rule in the prompt did not
   close it.
2. **Office/division granularity — a genuine trade-off, not an oversight.**
   `360678:x-org-bes` is *Basic Energy Sciences*, the office that **contains** the
   (a)–(x) programmes. **V2's explicit granularity rule rejects it correctly — and
   that same rule costs V2 a genuine F1 research centre**, which it also called an
   organizational unit. V1 and V3 keep every positive and accept the office.

**No variant achieves zero false negatives *and* zero fabrications.** V1/V3 trade 2 FP
for 0 FN; V2 trades 1 FN for 1 FP.

### 5a.5 Thinking behaviour — diagnostic only

Thinking tokens were **0 on 562 of 564 calls**; the two exceptions were V1 on
population B. Consistent with MEAS-3, and **not** treated as a defect: adaptive
thinking legitimately elects not to think, and §11's expectation of nonzero thinking
was formed on a population whose excerpts Cov5 has since repaired. No artificial
thinking budget was imposed to reproduce §11.

---

## 5b. Decision

> ### COV4 TASK DEFINITION STILL BLOCKED
>
> **What is now settled and should not be re-derived:** the recall failure is solved.
> `V1_propose_against` and `V3_subject_with_tiebreak` preserve **100%** of known
> genuine children on both populations — 4/4 of MEAS-3's stable false negatives
> recovered, the unstable span recovered, and F1/F4 genuine-versus-decoy separation
> at 5/5 positives and 4/4 decoys.
>
> **Why it is still blocked:** Cov4's gate carries a fabrication constraint as well as
> a zero-false-rejection constraint, and **no variant meets both**. Accepting another
> opportunity's topic (`363594`) is precisely the fabricated-publishable-record
> failure the gate exists to prevent, and it survived **all four** prompts including
> two that state an ownership rule explicitly.
>
> **This is not a case for relaxing the gate.** The zero-false-rejection requirement
> was *met*, so §"COV4 GATE REQUIRES PLAN DECISION" does not apply.

**What the next experiment should test, stated now so it is pre-registered rather than
fitted:** ownership is plausibly not a prompt problem at all. The classifier is handed
a title and an excerpt with no reliable statement of *which* opportunity the span was
extracted from, so "does this belong to the parent?" may be **unanswerable from the
input** rather than mis-instructed. The candidate fix is **structural** — supply the
parent's own identifiers and require the span's source document to match — and it
should be measured against this same frozen challenge set.

---

## 5c. The Cov4 ↔ P7 circularity, removed

**The problem.** P7's admission of F1/F4 forms is gated on Cov4 proving it can guard
them; Cov4's validation was gated on production emitting F1/F4 candidates; only a P7
recogniser emits those. Each waited for the other.

**The break, and it is already demonstrated above.** *Evaluation candidates are not
production candidates.* A candidate span hand-extracted from a document this project
has already read, with a human truth label and a page cite, validates Cov4 perfectly
well — no recogniser needs to exist for the classifier to be asked whether it can tell
a genuine focus area from the review criterion printed beside it.

**The ordering is therefore:**

1. **real F1/F4 documents establish candidate truth** — done: `330175` and `362233`,
   quoted, labelled, committed;
2. **manually frozen candidate spans validate Cov4** — done for these shapes: 5/5
   genuine kept, 4/4 decoys rejected under V1/V3;
3. **only then may P7 implement the recogniser** that would generate those spans
   automatically.

**Cov4's gate no longer requires production F1/F4 recognisers to exist.** P7 is not
started, and nothing here licenses starting it.

## 5d. The ownership experiment — pre-registered and run 2026-08-26

### 5d.1 The production ownership inventory

Traced through `source_for_record`, `subtopic_sources`, `segment_document` and
`build_records`. **Exactly four document kinds reach segmentation, and two carry
ownership by construction:**

| `source_kind` | Origin | Ownership evidence |
|---|---|---|
| `primary_notice` (565 records) | a Grants.gov attachment of this record | **bound by Grants.gov** |
| `secondary_attachment` | §6.6's multi-attachment path — also this record's attachment | **bound by Grants.gov** |
| `agency_notice` (393 records) | the record's own agency URL | **not guaranteed** |
| `subtopic_agency_notice` | Cov1's `subtopic_only_primary` | **not guaranteed — BUG-9's path** |

Available for **every** candidate at the Cov4 call site: parent record id, parent
opportunity number, parent title, source-document URL, name and `sha256`, the
`source_kind` above, and the excerpt. **The pipeline already holds deterministic
ownership evidence, so the classifier does not need to solve ownership at all.**

### 5d.2 The invariant

> A candidate may be **semantically fundable and still invalid for this parent** if
> the evidence establishes it belongs to another opportunity. **Ownership and
> fundability are two axes**; a candidate must pass both, and one verdict must not
> silently combine them when ownership is deterministically decidable.

### 5d.3 Results — O1 43 calls, O2/O3 deterministic

| Strategy | true-owned accepted | true-owned rejected | cross-opportunity rejected | cross-opportunity **accepted** | ambiguous |
|---|---|---|---|---|---|
| **O1** classifier context | 39 | **1** | **2/2** | 0 | 1 |
| **O2** deterministic guard | **40/40** | 0 | **2/2** | 0 | 1 |
| **O3** guard + classifier residue | **40/40** | 0 | **2/2** | 0 | 1 |

**My pre-registered expectation for O1 was falsified, and that is worth stating.** I
predicted O1 would fail the aggregating page because the earlier variants already
received `Parent number:` and accepted it anyway. **O1 rejected it, 5/5 on re-test** —
*"Excerpt explicitly attributes this topic area to DE-FOA-0003627, not the unnamed
parent opportunity."* Asking ownership as **its own question** was the difference, not
supplying more identity.

**O2 still wins on the criterion that matters for a gate: determinism.** It settles
**42 of 43** candidates with **zero API calls** and **without reading prose at all**
for the 40 attachment-sourced ones — which is what makes the over-aggression trap
safe. O1's one true-owned rejection shows a model verdict can err in the costly
direction; a guard cannot.

**The over-aggression trap held.** `own:360678-predecessor-citation` — a genuine HEP
programme quoted from page 96 of the parent's own notice, whose text cites predecessor
`DE-FOA-0003354` — passes as **owned** under O2 with `consulted_prose: False`. The
amendment-history case (`FundOpp_DE-FOA-0003627_Amd_000003.pdf`) passes the same way.
A rule of the form *"a foreign number anywhere means reject"* would have destroyed
both.

### 5d.4 Stability of the decisive verdicts (R=5)

| Candidate | Truth | O1 verdicts ×5 |
|---|---|---|
| `360678:x-org-bes` | owned, **not** fundable | `yes/no` ×5 — **stably rejects the office container** |
| `360678:x-org-office-of-science` | owned, not fundable | `yes/no` ×5 |
| `363594:x-other-foa-topic` | **not owned**, fundable | `no/yes` ×5 — both axes right |
| `360678:qcs` Catalysis Science | owned, fundable | `yes/yes` ×5 |
| `330175:f1-aeronautics-arc` | owned, fundable | `yes/yes` ×5 |

The office-container rejection is **not an n=1 fluke** — it was re-tested precisely
because a single call is not evidence, and it held 5/5.

### 5d.5 The specified configuration, scored

**Cov4 = O3 deterministic ownership guard + the O1 two-axis semantic prompt.**

| Axis | Result |
|---|---|
| Fundability | **TP=30 · FN=0 · TN=11 · FP=0** · unresolved 2 |
| Ownership | **40/40** owned accepted · **2/2** cross-opportunity rejected · deterministic for **42/43** |
| **Combined gate** | **28 published correctly · 0 FABRICATIONS · 0 GENUINE CHILDREN LOST** |

**A label precedence to disclose.** `363594:x-other-foa-topic` carries
`truth_label: contaminant` in the challenge set, written *before* the axes were
separated, and `owned: no / fundable: yes` in the ownership set, written *after*. The
two-axis label is used above because it is the more precise one and was still
committed **before** this run. On the one-axis label the same configuration scores
FP=1; the difference is bookkeeping about which axis the row fails, not about whether
it publishes — **it does not publish under either reading.**

### 5d.6 BUG-9 — fix defined, not implemented

The deterministic guard eliminates the aggregating-page fabrication **without
rejecting a single legitimate child**. BUG-9's fix is therefore specified as:

> **Ownership guard, evaluated before semantic classification.** A span whose source
> document is a Grants.gov attachment of the record (`primary_notice`,
> `secondary_attachment`) is owned, and its prose is never inspected. A span from an
> agency-hosted page (`agency_notice`, `subtopic_agency_notice`) is owned only if the
> parent's own solicitation number appears in the document identity or the span text;
> it is a **conflict** if some other measured solicitation number appears instead; and
> **unestablished** otherwise — which does not publish and routes to review.

**Not implemented in production this session**, per the package's own instruction to
end with a frozen decision Cov4's implementation can consume. `tools/cov4_ownership.py`
is that frozen specification.

---

## 5e. Decision

> ### COV4 FULLY SPECIFIED — IMPLEMENTATION NEXT
>
> Every clause of the stated criterion is met **on measured real-document evidence**:
>
> | Clause | Result |
> |---|---|
> | zero known genuine children rejected | ✅ **FN=0**, 0 lost at the combined gate |
> | known cross-opportunity fabrication rejected | ✅ **2/2**, by a deterministic guard |
> | measured contaminants rejected at the required gate | ✅ **TN=11, FP=0**, office containers stably rejected 5/5 |
> | ownership deterministic / reproducible | ✅ **42/43** decided by the guard with **zero API calls** |
>
> **What implementation consumes, all frozen:** the guard in
> `tools/cov4_ownership.py`; the two-axis prompt `O1_PROMPT`; **R=1**, licensed by
> MEAS-3; and the two evaluation artifacts as the regression set.
>
> **What implementation must still prove at its own gate**, and what this session did
> not touch: the production call site — `native` (NASA) and `referenced` (Army TDAC)
> records bypassing Cov4, only `inferred`/`inline` entering it, provenance never
> upgraded by classifier approval, classifier failure failing closed, and §0.5
> byte-identical with the flag off.

## 5. What this session did not do, and why

* **Cov4 was not implemented.** Its repeatability rule is the thing MEAS-3 exists to
  choose, and implementing a gate whose rule is unmeasured is precisely the
  "force an implementation" the package forbids — and §17.8's rule against a
  mechanism without measured evidence behind it.
* **No harness was committed**, because it would import `anthropic` (Blocker C) and
  could not be run against a population that does not exist (Blocker B). The design
  above is the harness's specification; writing it is a one-sitting task **once the
  key, the population and DEC-15 are in place**.
* **The P6 forward obligation stands unchanged and untested at a call site that does
  not exist yet**: when Cov4 lands, `native` (NASA ROSES) and `referenced` (Army TDAC)
  records must be proven to bypass the classifier *at the production call site*, not
  merely in a helper. Today they bypass it trivially, because there is no classifier
  to enter — which is not the same as proven, and must not be recorded as if it were.

---

## 6. Unblocking checklist

1. **DEC-15** — authorize `anthropic` as a dependency (§0.4 rule 7).
2. **A key** in an environment that can run the calls; §18.1 Cov4 already notes this
   is a human task because Claude Code strips it from tool subprocesses.
3. **A committed candidate population** — regenerate the backfill, fix **DEBT-1**'s
   six wrong-subject summaries first, and commit the arm A + arm B spans as a frozen
   evaluation artifact so every future run is comparable.
4. Run arms A and B at R=5, publish the JSONL and the per-span summary.
5. Read the decision table above and pick the Cov4 mechanism it licenses.
