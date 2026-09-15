# Targeted checker repair and catalog publication checkpoint

Recorded September 15, 2026. Current entry point: [PROJECT_STATUS.md](../PROJECT_STATUS.md). This report preserves the outcome of the supplied targeted patch and the separate catalog repair. It is not scientific acceptance or a completed catalog publication.

## Outcome

- **Checker implementation complete offline:** the supplied compact-schema patch is applied in the existing development worktree. Its focused protected-main PR256 has clean exact-head review and passing required CI, but is not merged. Provider acceptance is **NOT RUN** and the saved Luna assessment still has **0/24 independent verdicts**.
- **Two development packaging defects repaired:** the HTML asset version and generated search-release manifest now match their actual dependencies. Seven reported recovery/compatibility failures did not reproduce in this environment; their guards were preserved.
- **Initial catalog source repairs merged:** PR255 fixes official NSF sponsor identity and VPR prose segmentation. A real September 15 candidate contains both formerly duplicated NSF entries as aliases and excludes the false contact fragment.
- **Catalog publication remains blocked:** exact-head review of that candidate found a further consequential YIP duplicate/deadline defect. The release stopped before any Worker change, provider smoke or Pages publication. Direct GETs at **16:30:18 UTC** still show **September 11 data, 1,422 opportunities**.
- **Review convergence checkpoint:** the user-supplied repository rule stops another autonomous repair round after a consequential same-subsystem re-review finding. No new source repair/re-review loop was started. Independent checker work and preservation are complete.

## Identities and preserved work

| Item | Exact identity / disposition |
| --- | --- |
| Repository and product worktree | `mporosoff/grants-scraper`; `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender`; branch `codex/on-demand-team-recommender` |
| Resumed product | `55b0c4a273945d7b2cf959b77027976418828057`; not reset |
| Compact checker and development packaging commit | `a5a9de67ce7cee3f2f7942976108505328e797d4` |
| Reconciled product code | `346385e9d6c499634a9e9852c893e90d60f7258a`; exact source-repair cherry-pick, no conflicts |
| Containing handoff commit | Later documentation-only commit; resolve with `git log -1 --format=%H -- docs/reconciliation/targeted-checker-catalog-20260915.md` |
| Production source PR255 | Head `2ca7fa1d814efdfd991e076cfa93c209bd862dce`; clean terminal review5683543503; required CI34992128029; protected merge **`2e9b05456ac721820f1f73e1e780b2432c2967c2`**, September15 16:04:56 UTC |
| Checker PR256 | Head **`3dd60868fdd3b368e804f31fdc40b7baea709b4a`**; required CI34992742591; completed review5683636190 at16:08:58 and no-findings reaction16:09:01; no unresolved review threads; **open/unmerged** |
| Source publication PR257 | Head **`94f750752a536ccdc3e2707271846c1085943f4d`**; completed review **5212796068**, September15 16:24:53 UTC, one P1 finding; **open/unmerged** |
| Protected main at closeout | `2e9b05456ac721820f1f73e1e780b2432c2967c2` |
| Current public candidate | `f04234e0d00fe4520fa7e46a674c680e345958e0e3fd8e8f44c8b6e456b77d26`; prior publication `1e88a107ff2ec078088c1a7531f43d5c7fbee42c` |

The existing production-reconciliation and contextual-team-demand-service worktrees were reused for the two focused branches. The older helper head `0422356ca3f901ff7ae98d96d22781963885714e`, all experiment commits, reports, cached scientific outputs, split identities and accounting were retained. No main reset, force push, worktree deletion or generated-production-data overwrite was used. Root checkout and unrelated files remain untouched. Local HTML previews, debug logs, private output directories and the helper's pre-existing EOL-only change in `tests/test_team_recommender_executor.py` remain unstaged.

PR256 is held because the current release planner compares source dependencies to the last published candidate. A read-only invocation after PR255 identified the three source files as changed and selected `generate` for another main push. Merging the unrelated checker now would repeat source/vector generation while publication is blocked. Its review and CI are preserved; recheck exact head, required checks and release dependencies before eventual protected merge. No schedule or planner policy was changed to bypass that dependency.

## Compact checker and actual tests

Supplied patch SHA256: `e3a104d99b1f0b2bbb84830249e0dc2abebe16ffe5cfe2635d82afa9240cb442`.

`compact_check_body` shares repeated native schema definitions. Expanding them reproduces the original projected schema for 1, 6 and 12 people with both contributions. Complete questions, per-person claim ownership, contribution source identities, prompt, model, output allowance and strict local parser are unchanged. The builder is opt-in and has no dispatch or new spending authority.

| Measured item | Original | Compact |
| --- | ---: | ---: |
| Native schema UTF-8 bytes | 27,593 | 15,427 |
| Complete request bytes | 71,013 | 58,847 |
| Required person/contribution pairs | 24 | 24 |

Compact body SHA256: `eb7d49209b5ce1c6052a45a854924924147756c7ecab218360e3b4ba6dd35e3e`.
Derived contract: `d0e44d872d57767039991c4242285ffb5a5fefc6f9a3b3d93fce9ac2dbe5f149`.
Implementation file: `37d5ecd879a331d0af300a37e878c42b8b521a922dcc3ba2bde9c260d28a245a`.

These are wire-size and equivalence results, not proof of acceptance by the provider's compiled-grammar implementation. The historical paid lock correctly rejects the new packet. Neither unknown hold was released; no request was rekeyed, authorized or sent.

| Check performed in this task | Actual result and boundary |
| --- | --- |
| Development checker tests | **19 passed**, including saved-response canonical replay and network-forbidden new contracts |
| Production-isolated checker tests | **18 passed**; three new portable schema/lock/ownership tests. The fourth new replay test remains in development with its existing experimental receipt |
| Reported inherited recovery/scope failures | **24 selected tests passed unchanged**; all seven reported recovery/compatibility failures also passed in the complete Python run |
| Complete development Python run | **1,531 tests**, one failure: stale HTML version. This is retained as a failed run, not renamed a full pass |
| Complete development Node/browser run | **919 tests: 918 passed, one failed**, stale release manifest; no skips in this environment |
| Affected tests after packaging correction | **8 Python and 6 browser package contracts passed** |
| Frozen retrieval and scoring | **37 queries, zero top-10 churn; 50 scoring cases byte-identical** |
| Hermetic no-drift | **23 artifacts unchanged** using the existing build stages and frozen inputs through a native Windows/Python invocation |
| Source-focused regressions | **95 passed**, also rerun after product reconciliation |
| PR255 required exact-head CI | **1,486 Python /796 browser tests**, plus frozen-query, scoring and no-drift gates passed |
| PR256 required exact-head CI | **1,489 Python /796 browser tests**, plus frozen-query, scoring and no-drift gates passed |
| Real catalog candidate validation | All seven required gates passed; independent publication review subsequently failed |
| E2E / Playwright | **NOT RUN** in this task; earlier manual evidence is not new validation of this candidate |

The supplied document's seven other inherited failures did not reproduce under the local installed runtime. That difference does not justify changing recovery semantics or claiming the external observation was fabricated. No evidence guard was weakened. The existing registry-generation helper updated the one script version in `match_explorer.html`; the standard release-package builder updated its two dependent hashes. Markup, styling, fixed wording, science, registry generation, corpus and vector bytes in development were unchanged by this correction.

Initial Git Bash no-drift wrapper attempts failed on Windows command/PATH setup before establishing a valid run. The successful native invocation retained the same hermetic stages, fixed clocks and zero-fetch limits; no full-suite duplicate was run to inflate evidence. Full-branch merge readiness is not claimed from isolated PR CI or affected reruns.

Automatic approval rejected copying the detailed experimental closeout into the main helper as a test dependency. No copy or commit happened. The safer isolation retained that replay only in development and kept main's patch to the builder and portable tests. The denied approach was not bypassed and no raw provider cache was published.

## Catalog: what was fixed, and why freshness is still blocked

The official NSF feed omitted its agency, so the existing sponsor-scoped merger correctly treated it as an uncertain source default and failed to join its entries to Grants.gov. PR255 supplies authority only on that adapter's official HTTPS NSF funding links, retains complete NSF/PD identifiers, and leaves generic aggregators, successor editions and program descriptions distinct. VPR applicant-directed prose can no longer start a new call; its text stays with the preceding announcement. The publication filter also rejects the old cached false fragment.

The official NSF feed was read once at `2026-09-15T15:52:37.692120Z`: 11,697 bytes, 12 entries, SHA256 `ad9f19176c2d9c3fd6b9c0b7fd3910cbfb8ee5599e5d8baceae0f139733fbcdc`. Source-only repeated-number comparisons were retained, without treating every shared number as a duplicate or assigning sponsor authority from a title alone.

The normal main-merge release **34992708733** generated candidate **`489945e6dfe720414afd575e960ed8c0be0f26e8d6eb694d87e296a7ed0b32ae`**, source timestamp `2026-09-15T16:06:23.686570Z`, **1,398 records**. Candidate artifact10407100757; 10,831,017 compressed artifact bytes. It has 17 total source aliases, no standalone `nsf-funding:` record, and no `vpr-email:vpr-7921302c954613de`. Specifically:

- Grants.gov350802 retains NSF24-503 and the official RET URL as an alias.
- Grants.gov334326 retains NSF21-595 and the official TCUP URL as an alias.

Validation artifact10407066645 / publication-failure artifact10406164090 retain exact receipts. Validation fingerprint `34fc350e054d57235be390d198da616dedcbcc7e6a8a50039d0d0a8d093e6e48` passed package integrity, Python, browser contracts, frozen-query, scoring, no-drift and notice projection. Generation and validation succeeded; publication did not.

The Actions-bot review request was declined by its unconnected account. After confirming no review was active, one connected-maintainer request5683838805 started the legitimate exact-head review. No duplicate review or alternate credential was used.

### Confirmed remaining P1 finding

[Review5212796068 on PR257](https://github.com/mporosoff/grants-scraper/pull/257#pullrequestreview-5212796068) identifies the same Air Force FY2027 YIP solicitation represented by:

| Candidate record | Identity / deadline presentation |
| --- | --- |
| `363829` | Sponsor AFOSR; number `FA955026S0003`; December4 application close; required white-paper prerequisite and `verify_prerequisite` action state. Retained official PDF page37 identifies October9 as the required white-paper deadline |
| `vpr-email:vpr-a3ddeff815d159a4` | Same title; Simpler.Grants.gov UUID `c342c01d-4f34-440f-8bb2-4bdd4d763df0`; missing sponsor/solicitation authority; October9 incorrectly exposed as an open application with no prerequisite |

This is a supported-path identity and submission-stage defect, with duplicate cards and misleading `new`/`closing_soon` events. Read-only inspection of the exact candidate corroborated it. A future bounded repair should establish the authoritative Simpler.Grants.gov-to-Grants.gov identity, preserve the digest as an alias, and keep canonical stage ownership. It must not solve uncertain aggregator matches through a general title-based merge. The full relevant link/identity/deadline family should be audited before that remediation, including the already noted ambiguous VPR NSF records (`24-569`, `NSF26-511`, `NSF26-512`, `26-514`, `26-522`). Their existence is a limitation, not proof that all are identical or all need collapsing.

This is the consequential same-subsystem finding after the current consolidated source remediation. The user-supplied [root-checkout repository instructions](<C:/Users/Marc Porosoff/projects/grants-scraper/AGENTS.md>) require: “If a completed exact-head re-review finds another consequential issue in the same subsystem after one remediation round, do not begin another autonomous fix/review loop. Stop and report the convergence failure”. That stricter supplied rule governs this checkpoint despite the more permissive historical development-branch policy. No AGENTS file was changed. Another source fix/re-review requires the owner's explicit resumption of this named repair.

Run34992708733 stopped in **Establish exact-head review readiness before changing serving state**, publish job104464518801. Worker inspection/deployment/smoke, protected data merge, Pages and live-verification stages were skipped. No rollback was required because serving was never mutated. Direct post-failure GETs exactly match the pre-run public catalog metadata and candidate hashes. The current catalog remains September11, not September15.

PR249 and PR253 remain historical held candidates; they were not closed or merged as though a corrected replacement had published. PR257 is the current reviewed failed candidate. No candidate, vector build or source receipt was deleted. DARPA/IARPA's refresh was separately degraded (`partial_refresh`, four published records); the task does not claim every upstream source is healthy.

## Money and scientific boundary

Authoritative experiment owner remains **run34967272858**, artifact10394804222, `on-demand-team-offline-v2-20260909`. Fresh read-only inspection and closeout rehash match:

- Ledger: `4cd9494d2934aa4df3ed52905b10001e695b67a3d302581c8fa062e5da270ec8`.
- Checkpoint: `c4e38fe8c907878628f7e1360faa378098adb4a57e0b1d9c78c6c3c16e1fc78c`.
- Known charges **$7.346880**; holds **$0.146074 +$0.205254**; conservative total **$7.698208**, holds counted once.
- **685/690 attempts** used; **$2.301792 and5 attempts remain**, including protected **$1.267862/two attempts**. Native counts187/190.
- New experiment provider requests **0**, new experiment spending **$0**; no new spending owner, allowance, quarantine exception or hold release.

The normal catalog refresh has separate maintenance evidence. Its generation-spend ledger records **zero classifier/team requests**. The established search-vector builder required a homogeneous rebuild: **1,605 rows, seven API requests, 316,721 tokens, 0 reused rows**, 3,287,040 float16 vector bytes; previous-space canary identity was unstable, so it did not mix representations. The canary is included in those seven requests, not an eighth. Voyage-4-lite at the [official September15 price](https://docs.voyageai.com/docs/pricing) of $0.02/million tokens implies **$0.00633442** usage cost before billing rounding. This is a usage calculation, not an invoice, a free-credit claim, or an experiment-budget debit. No publication provider smoke ran because review failed first. No additional generation or paid probe was manually dispatched after the failure.

New catalog corpus `a795cafdcb9d4763f47e02e94a0a41afbeadb9b99919afeecc402cbc73fc1f4b`; vectors `40cdee53ea69a5c04af8435ef0356cb7c6da8fee5186b891ed7cdde004ede39a`; space `8c080778811e5c47d012f0d5db1f0d9c8cac63ae604eb9a12e7892202095f06d`. These belong to the held catalog candidate, not a served package or recommender representation campaign. Existing normal maintenance limits and schedules were unchanged.

Saved Luna assessment remains `complete_unverified_assessment`, scope351715, 12 people/24 pairs, canonical SHA256 `eb65f24d6b2be4aff319fca8c63bf5e4f21858987a62789b367136c82cb271ad`. Its existing 22.894593-second/$0.007006 result was not regenerated. Provider acceptance of the compact checker, all24 verdicts and any serving approval remain missing. Audited registry activation remains the separate 107-legacy-package compatibility decision; nothing was silently published or withheld to improve counts.

## Preservation and next action

Private receipts, completed logs, source-family audit, candidate, generation accounting and failed publication evidence are retained under `C:/Users/Marc Porosoff/projects/grants-scraper/outputs/targeted-checker-catalog-20260915/`. Development test/replay logs remain under the product worktree's `outputs/`. Raw caches, reviewer keys, source documents and detailed provider artifacts are uncommitted. Existing verified reconciliation backups remain available; remote Actions retention is not represented as permanent storage.

**Disposition: checker repaired and reviewed offline; initial source fixes merged; catalog publication blocked at a review-convergence checkpoint.** Recommended next action is one explicitly resumed, bounded YIP source-identity/submission-stage repair followed by exact-head review and corrected publication. Reuse the preserved expensive outputs wherever dependency compatibility permits; do not rerun unaffected scientific work. Merge the already-reviewed checker only when doing so will not duplicate the held catalog generation. A new scientific checker request still needs its own explicit execution authorization and authoritative recovery disposition. No deployment of the experimental recommender or Stage4 is authorized by this report.
