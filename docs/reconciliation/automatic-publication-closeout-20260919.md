# Automatic publication repair — merged; upstream outage blocks publication

September 19, 2026. **The reviewed repair is merged. A new catalog has not been published.** The first automatic release after the merge stopped at Grants.gov source acquisition during its announced maintenance outage. The existing verified September 17 catalog remains live. No manual owner review of the catalog is required by this repair.

## What is fixed

- Repository Codex review now covers all PR authors, including the Actions bot, and runs on new pushes. Both settings were verified after reload. Automatic bot-PR review was observed on PR #262, and automatic initial/update review was observed on PR #263. No duplicate reviewer request was sent.
- Publication allows the existing 30-minute review window inside the unchanged 45-minute job. A slow review still retains an honest `awaiting_review` checkpoint; findings and service failures still block. Review comments containing exact-head source links can establish blocking findings, never unanchored clean approval.
- DOE conditional “If required” wording no longer creates a mandatory LOI prerequisite. A cost-share field's negative answer is no longer overridden by the word “required” in its label. Parser versions invalidate the old interpretations through the existing cache path. Independent unconditional requirements remain supported.
- The frozen-output baseline now matches the intended parser identities. Separate offline builds of protected main and the repair showed only ten parser identity/dependency field changes, with no changed funding facts in the frozen sample. The two expected output hashes were regenerated, original frozen inputs retained, and all 23 artifact fingerprints passed.

The first attempt to run the existing Git Bash helper lacked its Unix utilities on PATH, and the sandbox subsequently denied its output-directory creation. A narrowly approved execution against the checked isolated output directory completed. The existing freeze script also imported unrelated live-cache metadata; those imports were discarded before commit, preserving the original fixture inputs. These local attempts made no provider calls and did not alter production data.

## Exact implementation and validation identities

| Boundary | Evidence |
| --- | --- |
| Resumed worktree | `C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/production-reconciliation` |
| Repair branch | `codex/automatic-catalog-publication` |
| Resumed head | `7dda8bb1c4a22e0465e2087270a38d00ff774891` |
| Corrected exact PR head | `54f7356066b6847fcf3483ba9d877516c36fc061` |
| PR | [#263](https://github.com/mporosoff/grants-scraper/pull/263) |
| Terminal review | Summary comment 5735619005 completed September 19 at 15:58:28.667157 UTC; trusted no-findings reaction at 15:58:31 UTC; head unchanged |
| Required exact-head CI | [35453243454](https://github.com/mporosoff/grants-scraper/actions/runs/35453243454), Python and browser SUCCESS |
| Protected merge | `e6692238f3bbc1603f7b1549d96360f4c42cd6ed`, September 19 at 16:00:17 UTC |
| Automatic post-merge tests | Run 35453554271, SUCCESS |
| Automatic release | [35453554431](https://github.com/mporosoff/grants-scraper/actions/runs/35453554431), generation failed before candidate creation |
| Existing product branch reconciliation | `20e1708a1e0a681bf80235329b378782d3585399` on `codex/on-demand-team-recommender`; no bulk merge or duplicate checkout |

The first PR revision had a clean review and passing Python tests/browser CI, but failed the no-drift gate. Its full evidence remains preserved. The baseline correction received its own automatic exact-head review and CI; earlier evidence was not used to merge changed bytes. Complete conversation, submitted reviews, inline threads and reactions were checked before protected merge. No unresolved consequential findings remained on PR #263.

Required CI ran **1,503 Python tests and 796 browser contracts**, all passing; frozen query checks reported 37 queries with zero top-ten churn, the configured scoring gate passed, and all 23 no-drift artifacts matched. The resumed local baseline work also passed 24 focused hermeticity tests. After exact cherry-pick into the product worktree, six repair regressions passed. These overlap with earlier focused tests and are not independent scientific evidence. E2E/Playwright was **NOT RUN** under the current repository policy.

## First failing publication boundary

The official `https://www.grants.gov/xml-extract` endpoint redirects to Grants.gov's maintenance blog with HTTP 200 and no extract link. The [official announcement](https://grants-gov.blogspot.com/2026/09/maintenance-alert-for-september-19-21.html) says production and training are offline September 19 at 00:01 Eastern through September 21 at 06:00 Eastern. A direct HTTP observation and separate page read confirmed the redirect and notice.

Both the paused-period scheduled run **35447171113** and the new merged-code release **35453554431** stopped with `No enhanced Grants.gov XML extract link was found`. The latter's plan passed; generation failed; candidate, validation, publication, Pages and release live-verification stages were skipped. No new candidate exists to resume at publication. No Worker or Pages serving mutation occurred. Repeated generation during this known outage would not establish new evidence.

The original rejected PR #262 remains open with its branch, candidate and completed findings preserved. Candidate `e9c5aa5f3f76821299f05a24c3b5b5bb4d44172c28eec5922b4b4a5efae6a07a`, generated by run 35356750364, is **not approved**. Its source dependency identities no longer match the repaired parser. Do not relabel it, bypass validation, or publish it merely to clear staleness.

## Actual live state and costs

A read-only public-byte check at **2026-09-19T16:01:56.867201+00:00** confirmed:

- Catalog generated September 17 at 21:45:36.229174 UTC, **1,391 records**, 14,605,726 bytes.
- Catalog SHA256 `bf9db897dc2d23c0a7be119279b40014adfb1ec5e62ddc1696ac0738bf52eff5`, matching its public immutable manifest.
- Live candidate `eea186246ffe73abb2f55294c99d03f08718e388d29ec2a0eaa42a010c1b0e62` from the previously verified PR #261 publication.
- The search release descriptor was retrieved and retained, but no paid search/provider smoke was repeated and no new Worker-equivalence claim is inferred from that GET.

The durable generation ledgers for runs **35447171113** and **35453554431** each contain zero requests and zero events. Both stopped before provider stages. **New provider usage for this repair/resumption: zero requests, $0.** The separate experiment ledger, its unknown holds, request cap and protected reserve remain unchanged. Codex PR reviews are not represented as metered scientific-API requests.

No schedules, GitHub protections, AGENTS policy, credentials, permissions, real researcher records, subscriber activity, or experimental activation changed. The previous YIP/source-identity repair remains intact. Previously recorded IARPA HTTP 403 degradation is not declared resolved by this work.

## Recovery and outstanding completion evidence

1. After the upstream extract returns, the existing daily workflow can generate with protected merge `e6692238f3bbc1603f7b1549d96360f4c42cd6ed` or a later compatible protected head. No owner catalog-reading approval or new model campaign is needed. The unchanged schedule is 10:17 UTC; actual scheduled start time may be delayed by GitHub.
2. If resuming manually, inspect the latest scheduled run first to avoid duplicate generation. Reuse any complete compatible candidate and receipt. If the failed run still has no candidate, the existing automatic dependency plan selects required generation, preserving reusable caches and durable accounting.
3. Let the new immutable candidate receive automatic review and required gates. Only then complete protected publication, Search Worker/Pages coordination, and live hash verification. Preserve any genuine source findings; never treat automatic initiation as scientific/source approval.
4. Once a corrected replacement is live, record its candidate/review/run/merge/live identities and close superseded PR #262 without deleting its evidence. A complete unattended generate-to-live cycle under the repaired configuration remains **UNMEASURED**, because the external source is unavailable.

**Disposition: repair merged and validated; publication blocked at the official Grants.gov extract availability boundary.** Automatic review configuration is restored, but end-to-end automatic publication is not claimed complete. The task remains unfinished at this genuine external boundary, without a new approval requirement.
