# Catalog deadline repair and publication closeout

Completed September 18, 2026. **The corrected September 17 catalog is published and independently verified live: 1,391 records.** The earlier September 11 public catalog has been replaced. This closes the resumed deadline/publication repair; it does not qualify or activate the experimental recommender.

## What failed and what changed

The canonical AFOSR YIP record already had a December 4 application deadline and a white-paper prerequisite. A separate VPR digest card exposed October 9 as an open application deadline. Exact official Grants.gov links, including the labelled legacy-record link on an exact Simpler opportunity page, now join proven duplicates. Canonical facts remain authoritative; alternate links, identity receipts and conflicting digest dates remain preserved. No title matching, sponsor guess, deadline-parser relaxation or successor collapse was introduced.

The September 16/17 daily failures were in publication review, after successful generation and validation. The Actions account could not initiate a working Codex review, and a 30-minute wait became a failed job. The workflow now preserves an explicit `awaiting_review` artifact after 90 seconds, skips every serving mutation, and can resume the exact compatible candidate on later ordinary runs. Findings, integrity failures and outages still fail. A waiting run is **not a publication success**.

The permission service timed out before one local review-initiation command executed. Its single permitted retry succeeded; no duplicate reviewer request ran. The publication dispatch was already submitted before the second user pause and completed remotely during that pause. The September 18 resumption inspected and verified that completion without dispatching another release.

## Exact identities and review history

| Boundary | Evidence |
| --- | --- |
| Starting production / product | `2e9b05456ac721820f1f73e1e780b2432c2967c2` / `f4b5f755dfd0079213a19e3c070d105e03481654` |
| Repair worktree / branch | `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/production-reconciliation`; `codex/catalog-deadline-review-repair` |
| Initial repair review | PR #260, head `077ff33959f9df73ab2dbea508b7429380a2ae1c`, review 5240948885, finding 4041045971 |
| Corrected exact head | `90a1eb7c9d866be74430cbcfc2573a99b2f0332e`; clean terminal comment 5720967520; CI 35271781424 |
| Protected repair merge | `c13d1b8547cb0e1d85814835affde253a893f61c` |
| Product reconciliation | `e2cd6090ffb872616adc3eee073208c03c741704`, on existing `codex/on-demand-team-recommender` worktree |
| Generation and validation | Run 35278318943; candidate `eea186246ffe73abb2f55294c99d03f08718e388d29ec2a0eaa42a010c1b0e62` |
| Publication review | PR #261, unchanged head `c93104df1854c8356ed5ab7fd1a39ab3a1723492`; clean terminal comment 5722128926 |
| Publication run / protected merge | Run 35284101222 / `957238e25f46d59c45cfef37716af8416a116ad1` |
| Live completion | September 17 at 22:56:06 UTC; zero differing assets, provider smoke and Worker provenance passed |
| Direct public-byte verification | September 18 at 19:38:36 UTC; catalog SHA256 `bf9db897dc2d23c0a7be119279b40014adfb1ec5e62ddc1696ac0738bf52eff5` matches reviewed candidate |

The first code review found that a prior number/stable-ID match could bypass a conflicting official link. It was reproduced, then repaired in one consolidated batch covering every preselected identity, direct/cached cross-links, absent canonical targets and contradictory links. Eighteen conflict combinations fail closed; consistent merges remain idempotent. The subsequent review was clean. All findings and initial commits remain preserved.

## Actual source result

| Canonical record | Published application deadline | Retained correction |
| --- | --- | --- |
|363829 / FA955026S0003|December 4, 2026|VPR YIP alias; `verify_prerequisite`; October 9 white-paper evidence remains in the cited notice, not a separate open-application card|
|363632 / N0001426SF004|October 30, 2026|Direct Grants.gov VPR alias|
|363378 / N0001426SF003|November 6, 2026|Official Simpler cross-link VPR alias|
|363745 / FA955026S0002|August 31, 2029|Official Simpler cross-link VPR alias|
|350802 / NSF24-503|October 14, 2026|Prior official NSF feed alias preserved|
|334326 / NSF21-595|October 14, 2026|Prior official NSF feed alias preserved|

The candidate has 21 source aliases, no standalone `nsf-funding:` card, and no applicant-prose fragment `vpr-email:vpr-7921302c954613de`. A zero-network replay of the preceding real 1,395-record candidate joined four proven duplicates into 1,391 records. Three cached Simpler mappings preserved their original retrieval metadata. The actual subsequent source build independently produced the corrected 1,391-record catalog, generated September 17 at 21:45:36 UTC.

The initial official YIP evidence was retrieved September 17 at 19:48:08 UTC from [Simpler Grants.gov](https://simpler.grants.gov/opportunity/c342c01d-4f34-440f-8bb2-4bdd4d763df0), whose labelled native link resolves to 363829. Original retrieval dates and representation hashes are retained in private receipts; a replay is not a new retrieval. Generic program links and the previously noted ambiguous VPR NSF-number groups are not silently promoted to proven identity.

The combined DARPA/IARPA adapter remains **partial_refresh**: four DARPA records refreshed, while IARPA returned HTTP 403. The existing degraded-source issue remains valid. This repair does not claim universal upstream health or that every official document retrieval succeeded.

## Publication, validation and production effects

- Initial local checks: 76 Python and 10 Node/browser lifecycle checks; after the review correction, 24 focused tests plus the real-candidate replay passed.
- Corrected-head required CI: 1,497 Python tests and 796 browser contracts passed. The generated candidate separately passed all seven required gates: package integrity, Python, browser, frozen query, scoring, no drift and notice projection.
- Publication reused the exact completed validation receipt. Source collection, vectors and full validation were not repeated by the publication resume. E2E/Playwright was **NOT RUN**, consistent with the current repository instruction.
- The first run demonstrated the real `awaiting_review` path: no protected catalog merge, Worker mutation, smoke or Pages deployment followed that checkpoint.
- After clean review, the normal publication workflow deployed the candidate-compatible Search Worker, merged exact catalog bytes, deployed Pages and verified the live assets and provider behavior.
- Search Worker changed from version `63af315b-cc2a-4742-ab2f-a5757e046686` to `e2173419-4a97-432e-bbce-eac03555d43a`. Its required/observed input fingerprint is `fa3511b8f2fe0ee6014207d731570404e10421375115623200b8c1cacedf67b0`; current and previous corpus compatibility passed. No rollback was necessary.
- Researcher-registry activation, contextual/Luna recommender activation, old team-service enablement, subscriber activity, account permissions and schedules were not changed. Existing catalog maintenance still handles source invalidation under its established rules.

## Money and preserved scientific boundary

No new experiment request, allowance, ledger write or checker dispatch occurred. The last authoritative experiment checkpoint remains run 34967272858 / artifact 10394804222: $7.346880 known charges plus $0.351328 uncertain holds, conservative total $7.698208; 685/690 attempts; $2.301792 and five attempts remain, including the protected $1.267862/two-attempt reserve. These retained accounting identities were not re-authorized or reset.

Separately, normal catalog maintenance run 35278318943 records 13 existing Cov4 classifier requests, 27,980 input tokens and 1,119 output tokens, charged $0.067150 within its existing $2 maintenance cap; no team-generation requests. The normal search-vector builder reports 1,598 new rows, zero reused rows, seven API requests and 316,970 tokens. Its existing compatibility contract did not permit row reuse; the model-space canaries passed with no detected drift. At the [September 17 official Voyage price](https://docs.voyageai.com/docs/pricing) of $0.02/million, that is $0.00633940 in usage cost.

The fixed pre/post publication smoke made two embedding and four rerank client requests, returning 2 embedding and 1,288 rerank tokens in total. At $0.02/$0.05 per million respectively, their combined usage-cost upper bound is $0.00006444; hosted cache reuse may lower actual metered requests. The complete normal-maintenance usage calculation is at most $0.07355384 before billing rounding, not an invoice or an experiment-budget debit. No additional smoke was rerun during September 18 verification. Today's scheduled maintenance is a separate standing run, not another manual generation requested here.

PR #256's compact checker remains reviewed but unmerged and scientifically unexecuted; the saved Luna assessment still has 0/24 independent checker verdicts. Its subsequent integration/dispatch and the audited registry's 107-legacy-package compatibility decision are separate from this completed catalog publication. No scientific readiness is inferred from the release repair.

## Daily run and remaining operational limitation

September 18 scheduled run 35356750364 completed successfully and retained its newer candidate `e9c5aa5f3f76821299f05a24c3b5b5bb4d44172c28eec5922b4b4a5efae6a07a` as **awaiting_review**, PR #262 at `7f6a38d22af8ecbbce649f3df53b84974bba332b`. Its checkpoint explicitly records `production_mutated:false`; Pages/live verification were skipped. It is not the live catalog and is not an error disguised as publication.

**Review initiation still needs a connected maintainer.** The Actions account has no working Codex connection; no credential was repurposed or permission broadened. The repaired workflow eliminates the recurring timeout failure and preserves pending work, but does not promise fully unattended daily publication. After a clean review of a pending candidate, use the existing exact `publish` resume. No schedule change or recurring Codex automation was introduced.

## Preservation and handoff

Superseded publication PRs #249, #253, #257, #258 and #259 were closed only after successful replacement and a verified complete Git-history backup. Their branches, findings and artifacts were not deleted. The bundle at `outputs/catalog-deadline-repair-20260917/published-repair-history.bundle` is 132,129,401 bytes, SHA256 `e6ab54a2aa57a72e11625e7d33033c94c92a6bb6e917d1a06b04c329f397a16b`. Private source pages, provider caches and detailed logs remain outside committed documents. The sanitized adjacent JSON indexes the exact receipts and hashes.

The root checkout and all unrelated worktrees/untracked files were preserved. The experimental product contains the reviewed code repair, not the generated production catalog or an activated registry. This report's containing commit supplies the documentation closeout identity after product reconciliation `e2cd6090ffb872616adc3eee073208c03c741704`.

**Disposition: deadline repair and catalog publication COMPLETE; recurring review-timeout failure corrected.** The live September 17 catalog is verified. Fully unattended review initiation and the separate scientific/registry work remain explicit limitations. Stop for user review; no new model campaign or experimental activation.
