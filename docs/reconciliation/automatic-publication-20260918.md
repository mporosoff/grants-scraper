# Restore automatic catalog publication

The owner authorized restoration of unattended publication on September 18, 2026. No human catalog-reading or daily review task is introduced.

## Root cause and restored configuration

The repository's Codex setting followed personal preferences. That worked for connected human authors but did not automatically review the `github-actions[bot]` catalog PRs. The workflow's manual bot mention could not establish a connected account. On September 18 the existing public repository's Code Review preference was set to **Review all PRs**, with **Every push** as its trigger, and both values were verified after reload. Personal settings, credit use, exhaustive review, Security Review, GitHub protections, secrets, schedules and access permissions were unchanged.

For the already-open PR #262, one draft-to-ready transition retriggered the unchanged candidate under the new setting. No new `@codex review` comment was posted. Codex acknowledged the automatic trigger at 19:55:06 UTC and completed at 20:01:10 UTC. Summary comment 5735430744 records `Draft marked ready` for head `7f6a38d22af8ecbbce649f3df53b84974bba332b`. This proves automatic initiation for a bot-authored release; it is not a clean review.

The existing publisher gets its established 30-minute bounded review window, within the unchanged 45-minute publication job. A slow review still preserves `awaiting_review` without serving changes; findings and service failures still block publication. The prior 90-second wait was too short for this observed six-minute review.

## Findings preserved and corrected

Completed comment 5735498210 identified two source defects in candidate `e9c5aa5f3f76821299f05a24c3b5b5bb4d44172c28eec5922b4b4a5efae6a07a` (generation run 35356750364):

- DE-FOA-0003617 / 363757: generic **If required** LOI guidance was promoted into a mandatory prerequisite.
- Its **Minimum cost share required: No cost share for this project** field was interpreted from the label's word "required", producing a false positive and contradictory evidence.

The full original 33-page notice was retrieved once for bounded verification. Its SHA256 is unchanged: `ca315dae30c47eaa8bb4f2ac6cc5ae6458c2fd93794b799072363a6fdf4e4447`, 1,248,159 bytes. Pages 6, 10 and 27 were inspected; page 10 states no cost sharing and page 27 preserves the conditional wording. The new retrieval is separately dated 2026-09-18T20:09:08.299937+00:00. The regression fixture retains the original morning retrieval, citations and limitations, not the new retrieval date.

The bounded obligation repair keeps conditional guidance from inventing a call-specific preliminary stage, including the synopsis fallback. Independently supported native dates and unconditional requirements remain eligible. Cost-share field answers take precedence over the question label; unsupported answers remain unknown, and "no less than 20%" is not mistaken for no cost share. The deadline and cost-share parser versions advance to invalidate earlier interpretations through the existing structure/cache recovery path. No generated assets are hand-edited.

The latest reviewer posted its findings with exact full-commit source links instead of `Reviewed commit:`. The review reader now recognizes that format **only as blocking findings** from the trusted bot. Such links never establish clean approval. Other repositories, mixed/stale heads, human comments, running acknowledgements and abbreviated status summaries cannot authorize publication.

## Validation and publication status

Before correction, the new zero-provider fixtures reproduced the source errors, missing review-format recognition and insufficient wait. After correction, 67 focused obligation/review checks passed, including the original retained DOE excerpts, receipt-preserving cache reprojection, open application access, negation/conditional controls and stale/untrusted review evidence.

Required exact-head CI, independent review, corrected generation and live verification remain required. Their completed identities will be recorded in a subsequent closeout. PR #262's failed candidate and review remain historical evidence; they are not approved or silently relabelled. Existing provider-generation caches and immutable outputs must be reused where their dependencies match. No experiment allowance, service activation, profile update, subscriber action or E2E run is authorized by this repair.

Official setup reference: [Codex GitHub review documentation](https://learn.chatgpt.com/docs/third-party/github).

## September 19 resumption and baseline correction

The owner resumed work with authorization to continue through merge/publication and release repairs. PR #263 remained at `7dda8bb1c4a22e0465e2087270a38d00ff774891`, protected main at `957238e25f46d59c45cfef37716af8416a116ad1`, and the paused worktree had no intervening code changes. Its first automatic review completed clean at 20:16 UTC September 18. Required browser CI passed; Python tests passed but the frozen-output gate failed because the expected fingerprints had not been advanced with the parser versions.

Separate offline builds of the protected-main source and repair source reproduced the old and new CI fingerprints. A recursive comparison of normalized artifacts found only ten parser identity fields changed: `submission-fields-20` to `submission-fields-21` and `cost-obligation-1` to `cost-obligation-2`, including pending reparse dependency identities. No fixture funding fact changed. The existing freeze script was run, but its unrelated imports of live `subtopic_only` and `official_identities` metadata were discarded; the original frozen inputs are byte-preserved. The existing fingerprint tool produced the two justified baseline updates. The offline no-drift gate then passed for all 23 artifacts. No gate was weakened.

Scheduled run `35447171113` failed before source generation on September 19: the official Grants.gov XML extract page redirected to its maintenance notice rather than returning extract links. A direct official HTTP check and independent page read confirmed the announced September 19–21 outage, with service expected Monday September 21 at 06:00 Eastern. This is an upstream availability boundary, not proof that the parser repair failed. Preserve prior valid live data and do not fabricate a fresh extract date or approve PR #262's rejected candidate to bypass it. [Official maintenance notice](https://grants-gov.blogspot.com/2026/09/maintenance-alert-for-september-19-21.html).

The changed baseline still requires a new exact-head automatic review and required CI before merge. Publication and live verification have not yet occurred.
