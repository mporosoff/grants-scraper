# Automatic publication — paused at the owner's request

Paused September 18, 2026. Wait for an explicit owner signal before resuming implementation, review requests, merging, pushing, generation or publication. This checkpoint does not disable or change existing repository schedules.

## Exact working checkpoint

- Repository: `mporosoff/grants-scraper`.
- Worktree: `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/production-reconciliation`.
- Branch: `codex/automatic-catalog-publication`.
- Local and pushed repair head: `7dda8bb1c4a22e0465e2087270a38d00ff774891`.
- Base main: `957238e25f46d59c45cfef37716af8416a116ad1`.
- PR: https://github.com/mporosoff/grants-scraper/pull/263 (open, not merged, no auto-merge requested).
- The unrelated untracked `debug.log` remains untouched. This pause note is intentionally uncommitted. No baseline correction has yet been made.
- Preserve the existing product worktree and its `codex/on-demand-team-recommender` head `fe3e3852ea98632a3788359daa6a27a6aa3c3813`; no product reconciliation or experimental activation was performed in this task.

## Completed work

1. Restored repository Codex automatic review configuration to **Review all PRs / Every push**, verified after reload. Personal preferences, credit use, permissions, protections, secrets, schedules and Security Review were unchanged.
2. Confirmed automatic review of the unchanged bot-authored catalog PR #262 after one draft-to-ready transition. No duplicate manual review request was sent. Its completed review found two real DOE source errors, so that candidate remains unpublished.
3. Committed and pushed the bounded PR #263 repair: conditional guidance no longer invents a required LOI; cost-share field answers take precedence over the label word “required”; corresponding parser dependencies advance. The release reader recognizes exact-head source-linked blocking findings, and the publisher allows the established 30-minute review window instead of 90 seconds. See `automatic-publication-20260918.md` for the invariant and source evidence.
4. Focused checks passed: 124 release/parser tests and 12 browser contracts, followed by 67 targeted checks covering the final guards and 47 source/cache checks. These counts overlap and must not be summed as independent evidence. No E2E/Playwright was run.
5. PR #263 automatic review **completed clean** at the unchanged head above. Summary comment `5735619005` records completion at `2026-09-18T20:16:19.713790Z`; the trusted bot added its no-findings `+1` reaction at `2026-09-18T20:16:22Z`. Complete conversation, submitted reviews, inline threads and reaction surfaces were checked. The exact-head review reader, supplied the observed request boundary `2026-09-18T20:12:00Z`, returned `(True, [])`.

## Current blocker and unfinished correction

Required CI run **35390137306**:

- Browser job **105746317626**: SUCCESS.
- Python job **105746317335**: FAILURE solely at **Verify flag-off output has not drifted** after the Python tests passed.
- The frozen-output gate reports two changed fingerprints:
  - `document_evidence.json`: `cf4f1de9c07862e5d12ccbcefda49750976ad93c2cec6ff7d7f2a91b771b32ee` → `52f09a719caea8f00fec5085a264d8e832da75e653105475c306d4eda956bc87`.
  - `opportunities.js`: `9d2f464c693db0ba12b024f4dc3fff755938b9e7906f9cefc9111bbcfd401671` → `15c37aabd824dae98d3b6b667c24a20895c6498fe3df19d93d5f4dd07a9e7807`.
- The parser/dependency changes intentionally affect output, but the actual frozen-artifact differences still need inspection before accepting a new baseline. Do not merely paste CI hashes or weaken the gate. `tools/hermetic_build.sh`, `tools/freeze_inputs.sh`, `tools/fingerprint.py` and `tools/verify_no_drift.sh` were read; no regeneration or baseline edit has been done.
- Git Bash exists at `C:/Program Files/Git/bin/bash.exe` but is not on PATH. Any hermetic build must use an explicitly checked, isolated output path; do not delete unrelated data. All generation for this baseline check is offline and zero-provider.

## Resume sequence after the owner signals

1. Recheck actual branch, worktree, local changes, PR head/review/CI, protected main and any scheduled release activity; preserve any later work. Read applicable AGENTS instructions. Do not duplicate worktrees or reset branches.
2. Inspect the frozen-build differences; if they are solely the intended repair, refresh only the justified fixture/baseline outputs through the existing tooling and document the changes. Run affected checks.
3. Commit/push the correction once. The configured automatic review should start; do not request a duplicate. Wait without editing while review is pending. Require clean exact-head review and required exact-head CI before protected merge. Earlier clean review does not cover changed bytes.
4. After merge, observe the existing main-triggered immutable release workflow; do not initiate duplicate generation. Parser dependencies require affected generation, while compatible expensive caches remain reusable. Do not publish PR #262's known-failed candidate.
5. Verify the new bot-created catalog PR receives review and completes ordinary protected publication, Worker/Pages coordination and live hash checks. Preserve failed candidates and reports. Close superseded PR #262 only after the corrected replacement is safely established, without deleting its evidence.
6. Record actual merge/run/review/candidate/live identities and maintenance usage in a closeout, reconcile the necessary repair/documentation to the existing experimental worktree without activating it, and report the actual outcome. Automatic publication is not yet proven end-to-end for this repair.

## Preserved evidence and production boundary

- PR #262 head: `7f6a38d22af8ecbbce649f3df53b84974bba332b`.
- Failed candidate: `e9c5aa5f3f76821299f05a24c3b5b5bb4d44172c28eec5922b4b4a5efae6a07a`; generation run **35356750364**; completed findings comment **5735498210**.
- Private retained artifacts: `C:/Users/Marc Porosoff/projects/grants-scraper/outputs/automatic-publication-20260918/` (candidate, validation, review evidence, official source verification, logs and PR body). Keep these private outputs uncommitted.
- Last live verification before this repair: September 17 catalog, **1,391 records**, from PR #261 / publication run **35284101222**, candidate `eea186246ffe73abb2f55294c99d03f08718e388d29ec2a0eaa42a010c1b0e62`. No new catalog was published during this repair.
- No experiment provider spending, scientific calls, new credentials, workflow/schedule edits, subscriber action, researcher changes or recommender activation occurred. Existing experiment accounting remains untouched.

**PAUSED — await the owner's explicit resume signal.**

Historical checkpoint retained. On September 19, 2026, the owner explicitly resumed this work and authorized continuation through merge/publication and release-bug repair. The pause above no longer applies. See `automatic-publication-20260918.md` and the subsequent closeout for resumed evidence.
