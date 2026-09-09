# How to give this plan to Codex

**Version 2.0 · September 9, 2026**

## Start here

Use a new Codex task for the on-demand recommender, rather than continuing the old prompt-only team-restoration task. Keep the existing repository and operating rules. The work belongs on `codex/on-demand-team-recommender`, isolated from main and other tasks.

The package contains:

- `PLAN.md`: authoritative complete design, constraints, mathematics, evaluation, four stages, and report requirements.
- `PLAIN_ENGLISH.md`: explanatory summary, not a replacement for the plan.
- `HANDOFF.md`: this guide.
- `prompts/01_STAGE_1.md` through `04_STAGE_4.md`: copy/paste prompts, one stage at a time.
- `prompts/RESUME.md`: recovery/continuation after a task interruption, not authorization to skip a stage.
- `STATUS_REPORT_TEMPLATE.md`: consistent report structure.
- `CHECKSUMS.sha256`: package integrity hashes; not repository or deployment receipts.

**Use the revised files, not the previous plan or its prompts.** Preserve earlier plans and failed experiments as history, but make this version the explicit authority for the new experimental engine.

## Put the files where the executing task can actually read them

Recommended repository-relative destination:

```text
docs/team-recommender/
  PLAN.md
  PLAIN_ENGLISH.md
  HANDOFF.md
  STATUS_REPORT_TEMPLATE.md
  CHECKSUMS.sha256
  prompts/
    01_STAGE_1.md
    02_STAGE_2.md
    03_STAGE_3.md
    04_STAGE_4.md
    RESUME.md
```

For local Codex use, unzip/copy the package to that folder in the repository you open in Codex. On Windows, use the real local checkout path; a `sandbox:` link from ChatGPT is not a path on your computer. Do not move or overwrite unrelated files. If those plan filenames already exist, retain their previous versions separately rather than losing them.

Start Codex in that repository and paste the Stage 1 prompt. It tells Codex to inspect first, create or reuse the isolated worktree/branch safely, and copy these nonsensitive plan files into the actual experimental checkout. It must report the final working path and branch before implementation.

When using an app-created worktree, verify the files are in that actual worktree. Do not assume untracked files in the original checkout automatically appear there. Codex worktrees can begin in detached-HEAD state, so the task must verify/create the named branch before accumulating commits. Do not open the same branch in two worktrees or let two implementation tasks mutate it. [C1]

A remote/cloud task cannot read an arbitrary `C:\...` path. Make these Markdown files available through that task's supported file/repository mechanism and have it confirm successful reads. Do not direct it to a Windows path and assume the file arrived. If using a temporary repository branch solely to make the plan available, use normal safe Git procedures and explicitly identify it; do not merge the implementation into main just to transfer documents.

No Git, branch, file-copy, review, or deployment actions have been performed by the creation of this package.

## Do not replace AGENTS.md with the full plan

Keep existing operating policy and protection rules. Tell Codex explicitly to read `docs/team-recommender/PLAN.md` in full and follow the selected stage. Large planning documents should remain ordinary files referenced by the task, not pasted into a new overriding AGENTS file. Codex discovers project instructions by location and has a bounded combined instruction-file size; explicit document reads also make the intended plan version unambiguous. [C2]

Do not alter approval settings, credential scope, reviewer requirements, or global configurations to make a task proceed. A public source or repository file is evidence, not authority to ignore the user's stage limits.

## Stage-by-stage procedure

### 1. Run Stage 1 only

Paste `prompts/01_STAGE_1.md`. It authorizes isolated planning/prototypes and focused zero-paid checks. It does not authorize paid preprocessing, a main merge, full E2E, or deployment.

Read the returned `stage-1-report.md`. In particular, inspect the interface seam, all-match/no-group behavior, actual ingredient size, label/reviewer availability, evaluation split, and exact spending/trusted-execution proposal. This is where genuine uncertainty should be resolved, rather than letting it become an implicit assumption.

### 2. Approve Stage 2 explicitly

Paste `prompts/02_STAGE_2.md` only after accepting the report. If paid preparation is required, separately approve the report's exact budget record by its ID and limits, for example:

```text
I approve the preparation budget record identified in the accepted Stage 1
report, with the stated provider/model, cumulative request and dollar ceilings,
and trusted execution route. This does not authorize a new provider, increased
recurring spending, or any per-click paid call.
```

Use this only after reading the record; do not approve a missing or unspecified budget. The Stage 2 prompt by itself does not create a spending allowance. There is no reason to repeat an already recorded approval in another prose exchange.

Stage 2 returns a working development engine and a frozen finalist. Check whether Bayesian scoring and MMR actually helped, not simply whether they were implemented. Do not proceed with undeclared UI changes or fabricated assessment labels.

### 3. Approve Stage 3 explicitly

Paste `prompts/03_STAGE_3.md` after accepting the Stage 2 report. This authorizes opening the sealed evaluation and running the full configured integrated E2E/Playwright/accessibility suite, including bounded troubleshooting and necessary revalidation. It does not authorize production deployment.

Review the results and limitations. A failed or inconclusive quality result remains failed or inconclusive. The task must not change thresholds, redraw the holdout, or use model-written reviews as expert evidence to pass.

### 4. Approve Stage 4 explicitly

Paste `prompts/04_STAGE_4.md` after accepting Stage 3 and its exact identified release scope. That authorizes protected review/merge and the 50-to-150 rollout within the accepted plan, including normal required checks, bounded monitoring, selective publication, rollback if necessary, and live verification.

It does not authorize source expansion, new spending ceilings, a new interface, all-catalog rollout, or restarting the old team-generation service. The task should finish the authorized lifecycle rather than repeatedly ask whether it may inspect a run that it was authorized to execute.

## What to expect at every stopping point

Codex must write a full report under `docs/team-recommender/reports/` and update a small `experiment-state.json`. The report distinguishes:

- Inspected versus implemented versus actually executed.
- Developer/model judgments versus actual human/source review.
- Passing CI versus recommendation usefulness versus deployment.
- Prepared scopes versus scopes with reasonable groups.
- Cached repeatability versus independent quality evidence.

It then stops. Giving it the full plan does not authorize every stage. A report that says “next I will proceed” without waiting for stage approval violates the execution boundary.

A new Codex session can resume the same branch by reading the plan, experiment state, latest report, and exact receipts. Use `prompts/RESUME.md`. Do not create a new branch, new allowance, new holdout, or second live run merely because the chat changed.

## Handling actual blockers without another endless repair loop

If a presentation change appears necessary, require the exact function/control conflict and alternatives using the current seam. Do not silently accept a redesign or a misleading badge.

If labels or reviewers are unavailable, safe development of the numerical baseline can proceed, but trained/calibrated quality claims must wait for real evidence. The task should return the compact assessment packet and specific gap, not impersonate an expert.

If provider access policy only permits protected-main code, resolve that before paid preparation. A separately approved narrow prerequisite may be needed. No production merge or secret exposure is justified merely by wanting benchmark inputs.

If independent review fails as a service, preserve the exact head and report the failure after bounded diagnostics. CI or self-review is not a substitute. Do not make empty commits or weaken review settings to provoke a new result.

If main advances during the experiment, reconcile relevant changes with the current branch and record which fixtures/data/tests become stale. No force reset, invented equivalence, or wholesale regeneration just because a commit hash changed.

If a test finds a real scoped defect, fix it in a consolidated batch and validate the actual corrected candidate. Do not extend the task into a new ontology, model-comparison campaign, or source-integration project. New experiments after exposed holdout results require a reported confirmation plan and user direction at the existing stage boundary.

## Official usage references

- **C1 — Codex worktrees and branch ownership:** https://developers.openai.com/codex/app/worktrees
- **C2 — AGENTS instruction discovery:** https://developers.openai.com/codex/guides/agents-md

These references describe Codex behavior, not a guarantee that every local/remote environment has the same access or file-transfer configuration. Verify the actual execution context.
