# Compact checker continuation — September 21, 2026

**PR256 is merged; catalog recovery is complete. The authorized checker workflow failed before reservation or provider execution. All 24 independent verdicts remain missing.** This is a preparation defect in the merged helper, not a scientific rejection or a provider grammar result. No automatic repair/retry was performed, following the continuation's explicit stop rule.

## Checkpoints and review

- Product resumed at `b3bb7bf65cf47a170d21c9e6026a233d34273833` in the existing `codex/on-demand-team-recommender` worktree. Pre-dispatch receipt commit: `4437242fede245044ccbc82fbb782509ce58b63e`. This report's containing commit is the subsequent documentation closeout; resolve it through this path's Git history.
- Existing helper branch `codex/compact-checker-contract` retained its implementation and unrelated local files. Current catalog main was integrated without conflict; exact reviewed helper head: `e8e37b003efe87ca158cca5da0f00170116739ee`.
- [PR256](https://github.com/mporosoff/grants-scraper/pull/256) automatic review completed at14:06:35 UTC; configured no-findings reaction at14:06:39. Conversation, submitted reviews, inline comments and threads were inspected; zero consequential findings/unresolved threads. No duplicate review was requested.
- Required [CI35609287887](https://github.com/mporosoff/grants-scraper/actions/runs/35609287887) passed at that exact head. Normal protected merge, with the head condition and no bypass, produced **`e5b6947837f5ae4666f27b9897e2d5dc948e2738`** at14:07:53 UTC. Main uses ruleset21286570 with required Python/browser checks; its classic protection endpoint returning404 did not mean the ruleset was absent.
- No recommender/runtime, audited registry or historical experiment branch was merged into main. Product already contained the same checker engineering; main's catalog/legacy projections were not bulk-merged into product. Existing private previews, outputs, debug files and the helper's prior EOL-only test change remain unstaged.

## Actual execution and precise failure

The frozen [pre-dispatch receipt](compact-check-predispatch-20260921.json) records the complete58,847-byte packet, all12 people/24 questions, saved Luna assessment, unchanged Sonnet5 rubric/model/12,000-output-token ceiling, $0.263282 conservative reservation, zero token-count calls and protected reserves. Official prices were rechecked September21; no scientific input was changed.

Exactly one workflow dispatch was made: [run35610297158](https://github.com/mporosoff/grants-scraper/actions/runs/35610297158), attempt1, trusted main `e5b6947837f5ae4666f27b9897e2d5dc948e2738`. Preparation restored the authoritative state and reconstructed the exact packet, then failed at14:10:14 UTC in `install_authority` with **`compact_terminal_evidence_hash`**. The reservation upload, provider-executing step, state upload and result upload were all skipped. The run has zero artifacts. No provider credentials were supplied to the failing preparation step.

The old receipt is intact. Its diagnostic has two legitimate, different identities:

| Identity | SHA256 |
| --- | --- |
| Original diagnostic file bytes, including its serialization/newline | `9f5cc1a7b775fb4e442545308ca037b2b2481ce6e2b1e6a3be3d38f65457c62b` |
| Canonical JSON content identity | `30cd6ebf824c14c3267e0aea79071c056bb9f67ae5b5c24bd37c572dceea191c` |
| Constant currently compared against raw bytes | `30cd6ebf824c14c3267e0aea79071c056bb9f67ae5b5c24bd37c572dceea191c` |

The merged guard mixes these representations. The separate receipt's raw-byte hash correctly matches `6c237d6db06aeaf48df9896505c74e6836a7fea9d00116f6c3ed2727af993723`; only the diagnostic comparison fails. A zero-network reproduction using copied real ledger/receipt/diagnostic bytes reaches the same error before any API call or ledger change. All1,357 original checkpoint file hashes still match. This is not evidence of corruption or lost accounting.

The14 focused contracts and required suites passed, but the new fixture replaces both constants with hashes of its synthetic files. That substitution concealed the representation error. The earlier real-data preflight checked packet reconstruction and checkpoint integrity, not the complete authority-installation path using its unmodified constants. Those green checks therefore did not establish readiness of this boundary. The implementation and preflight missed this defect.

The smallest next repair is to make the diagnostic's identity type explicit and compare like with like, retaining exact provenance and canonical linkage to the old receipt. It needs an unmodified-constant regression against the retained diagnostic identity and tamper rejection, plus the normal exact-head review/CI. It must not rewrite old evidence, release either unknown hold, change the scientific packet or weaken uncertainty checks. No such repair or second dispatch is included in this closeout: the [authority](../team-recommender/contextual-stage-b/COMPACT-CHECK-CONTINUATION-AUTHORITY.md) says to preserve a failed run and stop without automatic repair/retry. A subsequent explicit continuation is needed before another attempt.

## Scientific result and accounting

| Quantity | Actual outcome |
| --- | --- |
| Workflow dispatches | 1; terminal preparation failure |
| New provider attempts / tokens / native token counts | 0 /0 /0 |
| New spending or new outstanding reservation | $0 /$0 |
| Accepted independent contribution verdicts | 0/24; all24 missing |
| Derived independent person outcomes | 0/12 |
| Provider grammar acceptance | NOT RUN |
| Luna assessment | Exact saved result retained; no regeneration |

The prior Luna result still describes10 supported and2 credible-transfer people, with14 direct,9 method-transfer and1 adjacent contribution decisions. These are the previously saved, unverified model judgments, not new checker findings. No inclusion/exclusion agreement, explanation faithfulness, population accuracy or cold end-to-end latency can be inferred from this failed preparation.

Authoritative owner remains **run34967272858 / artifact10394804222**. Artifact digest `93a8a61d561b9291352a2783b1f0fb8bb6cf409206f9b88b3d637c688847a840`; ledger `4cd9494d2934aa4df3ed52905b10001e695b67a3d302581c8fa062e5da270ec8`; checkpoint `c4e38fe8c907878628f7e1360faa378098adb4a57e0b1d9c78c6c3c16e1fc78c`.

- Known charges: **$7.346880**. Historical unknown holds: **$0.146074 +$0.205254**. Conservative total: **$7.698208**.
- Lifetime attempts: **685/690**; remaining **$2.301792 and5 attempts**, including protected **$1.267862/two attempts**. Native counts remain187/190.
- Both historical request rows are unchanged; no new quarantine authority was installed or persisted. The failed workflow is not a new spending owner. No local mirror was used to spend.
- The new one-request/$0.50 cap was not consumed, but the explicit failure-stop rule bars automatic retry. An unused balance is not fresh authorization.

## Catalog and production boundary

Grants.gov's extract endpoint is available again. Ordinary automation had already completed [release35515844236](https://github.com/mporosoff/grants-scraper/actions/runs/35515844236) and published PR265 as `765cdb7da73598fb30b4a098bd8d568e10ac67c6` on September20. Public candidate **`5315ab4d3e4f293df625097775f3c042b718759312c057ea8b5ac66aadaaa700`** contains **1,368 records**, catalog generated14:15:20 UTC and pipeline package14:21:53 UTC September20. Its retained publication/live receipts passed. The three public catalog/registry/search metadata files were fetched again September21 at14:13:56 UTC and match that candidate exactly. This bounded check does not claim a new whole-package serving audit.

The premerge planner selected validation only and found no compatible pending publication. Rejected PR262 was not selected or published. [Postmerge release35610076546](https://github.com/mporosoff/grants-scraper/actions/runs/35610076546) completed successfully: all seven validation gates passed; generation, assembly, publication, Pages and live-provider smoke were skipped. Postmerge ordinary CI35610075995 also passed. No manual catalog refresh, subscriber replay, service deployment or new maintenance provider work was initiated by this continuation. IARPA degradation/issue30 remains separate.

## Checks and handoff

Actual focused continuation checks:14 passed. Required candidate CI:1,520 Python and796 Node/browser contracts;23 no-drift artifacts,37 frozen queries with zero top-ten churn,50 scoring cases byte-identical. The failure reproduction above is additional zero-provider evidence of a defect, not a passing readiness check. E2E/Playwright: NOT RUN, not authorized. Full browser cold-flow performance and new scientific quality remain unmeasured here.

The one current handoff is [PROJECT_STATUS.md](../PROJECT_STATUS.md), with matching [experiment state](../team-recommender/experiment-state.json) and [sanitized execution receipt](compact-check-execution-20260921.json). Earlier reports and receipts are preserved. Public Search/Team Match remain live; contextual serving remains restricted; historical E2/D3 remain superseded experiments. Audited-registry activation and the107 affected legacy-package revalidation/withdrawal decision are still separate and unexecuted. No new teams, vectors, profiles, interpretations, human packets, holdout analysis, release nomination or Stage4 occurred.

**Disposition: merged engineering prerequisite, catalog recovered, scientific continuation blocked at a reproduced pre-provider hash-representation defect. Stop for user review.**
