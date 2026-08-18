# MEAS-3 — classifier repeatability: run design, and why it could not be run here

**Status: specified, not run. Cov4 is blocked on it.** Three blockers were isolated
this session, each with evidence rather than assumption (§17.11's discipline applied
to a credential rather than a socket). This document is the experiment a human with a
key can run in one sitting, and the decision table that turns its result into a Cov4
design.

> **Nothing was implemented.** No classifier code, no Cov4 gate, no new dependency.
> The plan's own rule — *measurement before mechanism*, §17.8 — is the reason.

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

### Blocker A — no classifier credential in this environment

Isolated to the layer, not inferred from a failure:

| Layer | State |
|---|---|
| SDK | **present** — `anthropic 0.122.0` imports cleanly |
| Endpoint | **present** — `ANTHROPIC_BASE_URL=https://api.anthropic.com` |
| Credential | **absent** — `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` both unset |
| Call | `TypeError: Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set` |

So the failure is **credential absence**, not transport, model or SDK — exactly what
§18.1 Cov4 already records: *"Key from GitHub Secrets; Claude Code strips it from tool
subprocesses, so local testing needs a human to make the calls."*

**An `OPENAI_API_KEY` is present in this environment and was deliberately not used.**
§11's result is specific to `claude-sonnet-5` with adaptive thinking, and the whole
configuration finding — **88% precision at thinking-default versus 54% disabled** —
is a property of that model. Substituting a different model family would answer a
different question while looking like an answer to this one.

### Blocker B — the frozen candidate population does not exist on disk

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

### Blocker C — `anthropic` is not an authorized dependency

§0.4 rule 7: *"Never add a dependency not named in this plan without stopping to ask.
Exactly one new runtime dependency is authorized: `pdfplumber`."* `anthropic` appears
in no requirements file. Both the MEAS-3 harness and Cov4's eventual production path
need it, so **that is a plan-level decision to take before either is written**, not an
implementation detail to slip in. Recorded as **DEC-15**.

---

## 3. The run design

### 3.1 Population

Two arms, because §11's population and Cov4's actual future population are not the
same set — and 8.5 already said so.

| Arm | Spans | Why |
|---|---|---|
| **A — comparability** | The **114** spans of §11's run: `349554` ×18, `360678` ×70, `361526` ×26 | The only way any variance figure is comparable to the 1-in-62 observation |
| **B — the population Cov4 will actually face** | The three shapes §18.1 Cov4 names and **none of which are in arm A**: `363594` (aggregating agency page, **BUG-9**), `330175` (grouped restarting counters, an **F1** shape), `362233` (bulleted set with an adjacent decoy, an **F4** shape) | Arm A is entirely outline-derived from bookmarked PDFs. A repeatability rule fitted only to it would be fitted to the easy case |

**Arm B is required, not optional.** F1 and F4 are the forms P7 would later admit, and
Cov4 exists to make them safe. Measuring stability only on arm A would license a gate
for a population it was never tested against.

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
* the §11 span-level prompt, imported unmodified;
* temperature and every other parameter at whatever §11 used, unchanged;
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
