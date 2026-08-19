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

> **Measured false-rejection rate: 4 of 104 scoreable candidates = 3.8% stable, rising
> to 5 of 104 = 4.8% if `(i) X-Ray Scattering` is counted at its majority verdict.**
> **Cov4's gate requires zero.**

**No contaminants were available to catch.** The producible population contains none
(§3.1), so this run measures only the false-rejection direction — which is the
direction that costs real opportunities.

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

> **MEAS-3 is complete. Cov4 remains blocked — on precision, not on variance.**
> The gate's *"zero false rejections"* clause fails at **3.8%** with the committed
> prompt, and **repetition cannot repair a stable error**. What changed is which
> problem Cov4 has: it is now a task-definition problem, and it is cheap to attack
> because the population is frozen and the harness exists.

**Deliberately not done here:** the prompt was **not** tuned after seeing these
results. Doing so would convert a pre-registered measurement into a fitted one. The
next session should treat prompt/task definition as its own pre-registered
experiment against this same frozen population — and it now costs one command.

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
