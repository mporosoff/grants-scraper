# Funding Finder — reconciliation status

Updated September 15, 2026. This is the single current handoff. Historical reports remain evidence, not competing active plans.

## What visitors use

The public application still uses the existing Search, all-member Team Match and prebuilt team workflow. The audited researcher registry and contextual/Luna recommender remain in development. No new scientific inference or experimental activation was performed during reconciliation.

**Published and verified:** maintenance PR251 merged as `dda8d168c35a61323abc740e2193dfc244a7f5f5`; publication PR252 merged as `1e88a107ff2ec078088c1a7531f43d5c7fbee42c`. Run34982791206 completed successfully, including exact live verification and the required fixed smoke, at September15 14:54:33 UTC. Live candidate is `f04234e0d00fe4520fa7e46a674c680e345958e0e3fd8e8f44c8b6e456b77d26`. Independent direct observations through 15:00 UTC confirm the new imports and expected bytes. The Search Worker was retained, not redeployed.

The blocked September 14 catalog update was not published. Its first review was never requested by the old publication coordinator; after that was corrected operationally, review identified duplicate NSF listings and a prose fragment incorrectly presented as an opportunity. Those source findings remain unresolved. Independent maintenance restores eight missing Funded Awards browser imports, avoids a redundant Team Match allocation, and establishes publication review readiness before serving mutations.

The researcher audit is preserved, but swapping it into production would invalidate all 107 legacy scope packages under the existing evidence contract. This is a real compatibility boundary, not a judgment that all 107 scientific suggestions are wrong. No guard was weakened and no inventory silently removed.

## Production and development identities

| Layer | Verified checkpoint and boundary |
| --- | --- |
| Starting public Pages | Candidate `62d5f51e2edc9f30227f7caa418db41003df5ea16a410cbbbbf62d2a6c09cfc6`; publication `fd37d5983405a04e650cb9d0a12aa34098ca2a76` (PR228); generation `48e4e15673d2b2e41fb15cab45a928972e0c9977`, artifact run34610105444. Direct GETs September 15 13:23:47–51 UTC matched nine manifest-covered files. |
| Starting protected main | `ef44f981803e2cde77a8d1a6659115e722c66e02`, the PR250 helper merge. |
| Maintenance PR251 | Reviewed head `96615efda18b177112a90f3365684ed162a79bc3`; clean terminal review5682053791 and CI34982040047; protected merge `dda8d168c35a61323abc740e2193dfc244a7f5f5`. |
| Starting canonical product development | `codex/on-demand-team-recommender`, local `842cee675ffe5795b77054104f6a606b719e3a71`; remote `517736dddd11591b47650c0341ca54152588c0c3`. Local documentation closeout supersedes the older supplied pre-dispatch SHA; nothing was reset. |
| Existing helper | `codex/contextual-luna-contract-repair`, `0422356ca3f901ff7ae98d96d22781963885714e`; PR250 already merged, retained. |
| Historical numerical work | `58a59143ef5446b05223f52982a547903f53e24d`; private review mappings and answers preserved. |
| Root checkout, unrelated work | `codex/freeze-nofo-e2e-fixture`, `dabaed933b71fd2572403371ae6c94090ed7cbe9`; unrelated work was not staged, reset or cleaned. |

Production's public registry generation is `59ccfbe8999eeb4c78441e16daca468c694fc5798b03587c72468390939dc96a`; legacy team generation `de586bbbaf1294389515d49e073e1f3b05de6d5110b341d363b859fc8af97478`. Public team file SHA256 `81623cb2dcbcff2042c30c735d5301e87d35139bccd1e90bb42fc87af5d116fe` (1,012,517 bytes). The audited generation is **not** that public registry.

## Release #223: first failure and independent source block

Run34868137301, run number223, generation base `31b69b0772c759d9d8f7651a02aef924c7bab7e5`, persisted candidate `f56721d3e6bd4db720604414994614aa471b4d250b241f6e05dcc10fb1b76673`. Publication job104060905346 created PR249 at `f01aa7c64c7e63c041c6558d28524e2341fa9df1`, then waited for a review it had not requested. The old helper requested verification only on rebase. Review timeout was the first failing boundary; candidate artifacts and prior generation were retained. No new scientific work was needed to diagnose it.

The search Worker changed temporarily to version `409640f2-1144-41b5-ba4b-596dfd0d4cce`, deployment `d180c609-e4b5-4f01-8d14-eb2b2500103a` at September 14 16:34:05 UTC. Its handshake passed; the failed publication rolled back to the captured version below. Pages was skipped. Current direct Pages hashes and search current/previous corpus health support restored compatibility; a workflow's rollback label alone was not used as proof.

On September 15 a single legitimate initial review was requested (comment5680972297); completed review at 13:38 UTC found:

- NSF24-503 duplicated as Grants.gov350802 and its NSF URL.
- NSF21-595 duplicated as Grants.gov334326 and its NSF URL.
- `vpr-email:vpr-7921302c954613de` contains an application-contact prose fragment with a generic ONR research link, not a coherent call.

A source-only family audit found 13 repeated NSF-number groups among 106 number groups. This is a diagnostic list, not 13 automatically established duplicate solicitations: program codes, parent/child ownership and true successors still require source interpretation. It was not resolved by simply deleting records or weakening duplicate guards. Retained artifact, review, and [PR249 disposition](https://github.com/mporosoff/grants-scraper/pull/249#issuecomment-5681516376) remain intact. PR249 is not approved for publication. No older pending candidate is substituted as fresher data.

The actual additional serving defect was eight public import URLs returning HTTP404. This affected Funded Awards module loading and is addressed independently by PR251. Catalog staleness and module-serving failure are reported separately.

Aggregate alert database receipts: 18 sent events, latest September 8 13:22:36 UTC; zero sent since the failed release began September 14 16:21:50 UTC; zero provider-event receipts in the inspected table. No recipient data was read, no notification was replayed, and no manual email was sent. This is bounded delivery evidence, not an assertion about every external mail system.

## Disposition of candidate improvements

| Change group / origin | Production presence and consumers | Benefit / dependency | Disposition |
| --- | --- | --- | --- |
| Eight Funded Awards imports; `1673a0d517f25e80f6ab4efb6389a4e485bd6d12` | Missing from public assembly and live URLs; browser adapter imports the public Worker helper modules and institution map | Fix transitive module closure; exact allowlist only | Isolated in PR251, with assembly/live verifier tests; no Worker secrets or experimental ingredients included |
| Allocation guard; `561fbd38fd1a94a11892eb165f8099f3d5365fa5` | Missing on main; existing Team Match evidence preparation | Avoid proximity scan whose only consumer cannot execute; same scores/evidence/explanations | Isolated in PR251; 244,590 profile/scope outputs and 214 complete-team outputs identical |
| Acronym preparation; `7ac8e33` historical family | Still development-only | Existing semantic dependency fingerprint would invalidate purchased corpus | Deferred; no corpus regeneration authorized |
| Canonical summary and institution normalization | Audited development registry and consumer changes; current production still has older compatible projections | Useful correction but must travel with coherent registry/evidence dependencies | Preserved in development; no partial display/scoring swap beside obsolete team assertions |
| Manual profile cache invalidation | Current production vocabulary cache already keys by full profile context; shared researcher module identical | Proposed experimental-cache fix has no matching production cache to repair | No manufactured production change |
| Currentness/stale-response/identity protections | Existing authoritative submission/currentness paths retained | Experimental seams are not interchangeable with public prebuilt path | No new fit or date policy imported |
| Publication readiness/history and UTF-8 review parsing | Missing initial-review request and premature Worker/smoke work reproduced | Preserve exact-head review, non-force branch history, final recheck, rollback and CI | PR251; completed findings and failed receipts retained |
| Test portability | Two old byte-freeze tests and two staged E2E setup assumptions | Preserve all historical bytes except the one exact parity-proven allocation hunk; use selected mocked provider and notice-aware geometry | PR251; no skip, timeout increase, removed feature assertion or presentation change |

The eight newly staged paths are `workers/award-api/src/{adapters/dod.js,institutions.js,ror.js,snapshot.js,http.js,contract.js,year-filter.js}` and `config/award_institutions.json`. They are public browser dependencies, not an allowance to export other service files.

## Researcher audit: exact compatibility boundary

Audited registry `60169651eaff43c75e0eccd12167371d8131b76ed67592eaed18d3689d188126` remains intact: 158 records, 155 auto-eligible, 14 department-visible, 141 institution-visible, three reference-only; 120 main-pool and 35 standby profiles. Four unresolved source gaps remain Lawton, Lomakina, Rygg and Slane. Historical audit counts are not newly performed reviews.

The [complete impact receipt](reconciliation/researcher-legacy-impact-20260915.json) enumerates every legacy scope and reference. Under the actual generation guard, all 107 scope packages block if that audited registry is substituted; 20 already had withholding reasons independently of this proposed swap. Thus 87 previously available packages would also be withheld. Across 789 old role/claim references, 712 have changed scientific/source evidence and77 are missing/retired. None were established as byte-identical or safely mechanically reanchorable. Across 270 primary-member assertions, exact old label/evidence/source triples do not survive. This does **not** establish scientific incompetence or disprove all old suggestions; it establishes that the old assertions cannot automatically inherit new evidence provenance.

Representative audited corrections already preserved in development:

- Abdolrahim: a broad “X-ray diffraction and crystallography” legacy label becomes a specific machine-learning connection to classification of large diffraction datasets.
- Blok: generic RF/microwave wording becomes microwave circuit QED with Josephson junctions; quantum sensing is explicitly tied to superconducting circuits.
- Singh: a broad quantum/topological-materials label becomes a connected description of topological, polar and superconducting materials in bulk, two-dimensional and heterostructure systems.

These are changed representations with source links in the canonical audit, not fresh role certifications. A coherent audited-data release needs an explicit owner choice about revalidation or withdrawal of affected legacy proposals. This reconciliation neither hides those controls nor creates a parallel registry subsystem. Currentness/source exclusions unrelated to the audit are kept separately in the impact table.

## Service state and activation boundary

Fresh authenticated serving metadata was inspected without provider calls. After publication, hosted-AI and intake deployment lists are exactly unchanged. The live release verifier re-established the same Search version and complete fingerprint at 14:54:27 UTC. Aggregate delivery receipts read again at closeout still show 18 historical sent events and zero since reconciliation; database writes were zero.

| Service | Observed deployed version | Configuration / boundary |
| --- | --- | --- |
| Search | `63af315b-cc2a-4742-ab2f-a5757e046686`; deployment `aa30021a-1d35-4782-b3a3-dffd927c498f` | Rollback at September 14 17:05:12 UTC; annotation `8ab2d205159ec3a997bd00888ea2220caf454abe`; current corpus `bd89d267b77e2f69b651e89c0017e0ec2c0ec206dd7d456435571b86fb8eaba4`, previous `d0e61393452e57f6b82e27e856af590167fa471feccb5aee72cbac5465f8d4ee`; health confirms current/previous supported |
| Hosted AI | `3ab7214f-5bd2-4d25-b313-d47786422389`; deployment `e0d00db6-72d6-4f51-9972-0f5e87f2ca73` | Protected annotation `22a9a5e29f45963c4036ba1abcb1753c6131df6e`; no route/model change |
| Researcher intake / restricted contextual service | `45f02b75-3505-4062-8886-5cb496a07c92`; deployment `4c1236f6-ccd1-4a84-960c-8bfafb701884` | Annotation `9871906030161a7e41558b5aa176084012077729`; Access-protected validation, public activation false; no new job or redeployment |

Hosted routes remain Gemma for search planning, institution translation and program-officer question planning; Luna for refinement, result chat, program-officer evidence answers and institutional narrative; notice chat Luna with its existing Gemma fallback. These are observed existing routes, not a new selection decision. Search retains voyage-4-lite1024 query embeddings and rerank-2.5, separate from offline experiment models.

The restricted trial control table has no override rows, so its existing cached/new-paid defaults apply **inside the restricted trial**. This is not public paid enablement and not a claim that every backend paid flag is disabled. Public contextual activation remains false. No Access, CORS, permissions, schedules, account plan, real profile or subscriber state changed.

## Validation and runtime measurements

Exact maintenance review/CI history:

- Original `646b1ac31eeae16deb3327cc502b2a4e58d08ae1`: Python passed; browser CI34977725521 identified two historical byte-freeze tests. Completed review found the same invariant.
- Consolidated repair `ba294b3fbc4f8860a56044c44d954de010ac581b`: CI34978857533 passed Python/browser; clean terminal review comment5681523557. Old frozen hashes remain; a helper checks exact new bytes and reverses only the one allowed allocation hunk before comparing to the old hash.
- Initial test-setup correction `11e83a851947a62ff76d6ba530efc01abd9565cd`: CI34980957945 passed, but review correctly found a self-referential geometry measurement and insufficient warning-presence assertion. Both findings were consolidated.
- Geometry remediation `96615efda18b177112a90f3365684ed162a79bc3`: all five affected staged tests passed; CI34982040047 passed; clean terminal review5682053791. The corrected test remains panel-relative, accounts only for notice height/margins, requires the warning according to the actual catalog date, and detects intentional displacement/hidden-warning mutations. All corrected threads were resolved only after the corresponding clean review.
- Initial automatic approval of the merge command was rejected because the older byte-freeze correction was not evidenced in that request. The exact patch, unchanged repaired files, clean review and old/current passing CI were supplied; the subsequent resolution/merge was approved. No protection was bypassed. One later read-only status check encountered approval-service capacity and succeeded on a bounded retry.

Matched production parity used155 eligible public profiles, 1,355 parent records and223 child records at `2026-09-15T13:23:47.898Z`: 210,025 parent +34,565 child decisions, zero full-output differences. All 107 legacy groups were also compared across parent/child catalog modes (214 complete outputs), zero differences. Single local Node observations: parent18,346.58→6,745.15ms; child1,061.33→741.96ms. These are whole-corpus diagnostic runs, not public-browser p95 or a new team inventory.

The staged public package is45,120,600 bytes and contains the real retained public data. Candidate `ae21e81cafcb609fde05d0a3b929f308ad9bde2a93d91810ee463d3b927ec64d` was locally derived from artifact34610105444 and the maintenance runtime; later changes were test/documentation-only. It is a test identity, not a claim of public publication.

Full configured Playwright1.62.1 run:117 executed,115 passed, two failed. Both failures were test setup: the mobile centering measurement included the correctly visible age warning, and the accessibility test mocked OpenAI while leaving hosted selected. The two files passed 11/11 after initial corrections, including the previously failing checks and axe scans; the additional review-mandated geometry correction then passed all five affected tests. The weaker intermediate assertion and its failed review are retained. No application bytes, timeout, warning or feature assertion was removed to pass. This is affected rerun evidence plus unchanged original observations, not128 independent tests. Windows server teardown was explicitly diagnosed and only the verified local test-server processes were closed. External DNS was blocked and provider responses were fixtures. Axe incomplete/manual findings remain limitations; physical-device validation was not performed.

Focused checks include publication lifecycle/accounting-boundary contracts, exact import closure, currentness and deployment contracts. Required CI is separate from mocked E2E; historical scientific tests are not qualification of new source data. Private logs, traces, before/after file hashes and failed review evidence remain under the reconciliation output directory.

## Money and preserved scientific evidence

Authoritative experiment owner remains run34967272858, artifact10394804222, authorization `on-demand-team-offline-v2-20260909`. Reconciliation rehashed 1,357 checkpoint files with zero mismatches; ledger and checkpoint were read only.

| Experiment accounting | Amount / count |
| --- | --- |
| Known charges | $7.346880 |
| Old unknown hold `fc618603458249348c6834d258264520` | $0.146074, exact cause still unknown |
| New unknown hold `d24a0654d72e486793519bead019b064` | $0.205254, compiled checker grammar rejected |
| Conservative usage, holds included once | $7.698208 /685 of690 attempts |
| Remaining | $2.301792 /5 attempts |
| Protected reserve | $1.267862 /2 attempts |
| Native count calls |187/190 |
| New scientific requests in reconciliation | **0** |

Ledger SHA256 `4cd9494d2934aa4df3ed52905b10001e695b67a3d302581c8fa062e5da270ec8`; checkpoint SHA256 `c4e38fe8c907878628f7e1360faa378098adb4a57e0b1d9c78c6c3c16e1fc78c`. Neither hold was released, no allowance reset, no copied spending owner or new quarantine exception created.

The saved Luna assessment is structurally valid **unverified** data for 351715,12 people×2 contributions: canonical SHA `eb65f24d6b2be4aff319fca8c63bf5e4f21858987a62789b367136c82cb271ad`; run34967025187, request`cc76321197cd497c8391654fd6e98298`,22.894593s,$0.007006. The new checker failed before 0/24 verdicts, provider request`req_011Cf5CdbtQ9HBdBSPfCuhnT`. No scientific acceptance or verified fast end-to-end route follows. Requirements-v2 and accepted Phase1/2 graphs remain historical evidence; DOE's corrected interpretation has not run.

Production smoke is a separate standing operation under the existing documented 50,000 daily embedding-token /25,000,000 daily reranking-token controls. Before dispatch the fixed query measured9 UTF-8 bytes and shared passage`parent:112354` measured1,763 bytes, SHA `7e016b00eae311440b125530590163442161114cde8b7dcb5312afa975df9abc`. One prepublication plus one postpublication smoke permits at most2 embeddings and4 reranks, no POST retries; invalid-corpus requests reject before provider work. Conservative complete-operation ceiling$0.007680 at September15 official Voyage prices. Actual returned usage across the two smoke executions: two embedding requests totaling 2 tokens, four rerank requests totaling 1,288 tokens (322 each). Published-price usage cost is **$0.00006444**, before account billing rounding; this is a usage-based computation, not an invoice. Both invalid-corpus requests were rejected locally by the Worker before provider work. No automatic paid retries occurred, and nothing debited the experiment ledger. No open-ended probes are authorized.

## Preservation and one development entry point

No worktree or branch was deleted. Named local refs `refs/checkpoints/reconciliation-20260915/{product,helper,analysis,main,pr225,pr249}` preserve exact starting identities. A verified repository bundle retains complete history (SHA256 `b427873292116e52beea1f1fe3ba52fd6242b6a1acda5c85d98553d3e27851f5`). A private ZIP retains 7,516 files /427,392,417 bytes, SHA256 `4cad01b3546662716ac1b9d08aaf23806582e5d6b83bf406e5bc5f4d0276ce7f`; every copied hash and ZIP CRC was checked. Originals remain. This is a verified local recovery copy, not an off-device permanent-backup claim or an extension of Actions'90-day retention.

Private location: `C:/Users/Marc Porosoff/projects/grants-scraper/outputs/production-reconciliation-20260915/`. Keep provider responses, source caches, hidden reasoning, reviewer keys and answers out of public commits. Initial scan covered 59 unpublished development commits /413 unique blobs with no high-confidence credential/path flags; scan scope and later additions are recorded before any push. A pattern scan is not proof that every apparently harmless text is public.

Untracked local HTML previews, debug logs and outputs were left in place. The helper's pre-existing EOL-only test modification was preserved. PR225's old exact-head review at517736… is preserved and does not qualify the current engine. PR225 was closed as superseded, without retargeting its old diff to main. The canonical development integration is `c93345276e67530cfbbd131b703e63601447b65e`; the containing commit of this status document is the later documentation-only handoff. A verified post-integration bundle (SHA256 `33fcae245dedb0497f61c773303093c479660d110e74163caa8dd67d5513688c`) also preserves that code checkpoint. PR229 and PR237 were closed as obsolete publication attempts after their exact heads were fetched into named refs and `older-publication-heads.bundle` was verified. Their source changes are not falsely represented as published; PR249 remains the one held source-update track.

## Completed publication and reconciled development

The [publication receipt](reconciliation/maintenance-publication-20260915.json) links exact protected/review/run identities. All seven candidate gates passed: package integrity, Python, browser contracts, frozen-query, scoring, no-drift and notice projection. The Actions bot requested review before any serving mutation, but the connector declined that unlinked account. The already connected maintainer account made one legitimate request (5682327551) after verifying no review had started. Clean terminal review5682408589 covered `9438d6d981d816e26429051d22b1f7ce25a7d595`. The existing coordinator then completed protected merge, Pages and live verification. Future bot-initiated releases still need this connected-maintainer review initiation; no new token, permission or false automated-review success is claimed.

The public candidate's serving files are byte-identical to the locally tested staged package. All 24 generation files remain from the retained source generation. Direct post-publication GETs covered 22 paths: all eight formerly missing imports now return200; entrypoints, matcher, prebuilt-team adapter/data and registry identities match the manifest. One metadata GET returned503; its failed response is retained, and a single bounded retry returned200 with the exact expected hash. The normal immutable verifier had independently passed all required bytes and Worker checks. No rollback was needed in this release. The preserved rollback reference is candidate62d5…/publicationfd37… plus Search version63af315b…; restoring it would restore its old missing-import limitation, not scientifically revalidate old proposals.

The [integration receipt](reconciliation/development-integration-20260915.json) records each conflict resolution and unchanged scientific file hash. Already-present imports and allocation logic were not duplicated. The development-specific renderer tests and audited generations were retained rather than overwritten by production hashes. A transient Windows text-decoding mistake was caught by the before/after byte check and corrected before commit; no mojibake was committed.

Development checks:86 Python tests passed; the first 56 Node contracts had 55 passes and one stale fixture failure. The fixture was updated to the existing `canAssessPerson` restriction from `015c8efcc836453356a6bee722fd2e0726e83fd4`; all 12 affected contracts then passed. No application permission changed. Three Phase1 graphs, including the base LPS graph, its retained extension and Veterans' negative result, replayed at their recorded reference clock. Three Phase2 graphs replayed with fresh action clocks, including the native child. All provider transports were forbidden and all six graph identities were preserved. The saved Luna assessment replay preserved 12 people/24 pairs and exact input/output hashes. These are deterministic engineering checks, not new scientific verdicts or live-browser qualification of the experimental path.

The integrated history scan covered 60 unpublished commits /430 unique blobs, with zero private-path or high-confidence credential flags. Additional structured-data inspection found 33 `thinking` keys, all public disabled-setting values, not hidden provider reasoning. The history contains public-input preparation/configuration and sanitized scientific receipts; raw provider caches and private review keys remain uncommitted. Final documentation additions were checked separately before push. The sanitized development checkpoint `5093208dd817ab677e71f641e5eb783ea07702bb` was pushed and independently matched to the remote branch. This completion annotation is documentation-only; the branch has no open production PR and its push triggers no production release or scientific dispatch. Resolve the exact documentation commit with `git log -1 --format=%H -- docs/PROJECT_STATUS.md`; the code checkpoint validated here is c93345276e67530cfbbd131b703e63601447b65e.

Existing source documents: [latest Luna report](team-recommender/reports/luna-contract-repair-and-scientific-check.md), [immutable Luna closeout](team-recommender/contextual-stage-b/luna-repair-closeout-v1.json), [experiment state](team-recommender/experiment-state.json), and [maintenance design](PRODUCTION_RECONCILIATION_MAINTENANCE.md). Their history and scientific statuses remain unchanged. This document is the current entry point.

Start the next session in:

```powershell
Set-Location -LiteralPath 'C:/Users/Marc Porosoff/projects/grants-scraper/.worktrees/on-demand-team-recommender'
git status --short
git rev-parse HEAD
git worktree list --porcelain
Get-Content -LiteralPath docs/PROJECT_STATUS.md
```

Read applicable AGENTS, the latest immutable Luna closeout and the authoritative ledger before any further execution. Do not infer local availability from the remote branch or reset to an older SHA.

**One next recommender task:** reduce structural duplication in the independent checker grammar while preserving complete questions, evidence ownership, local validation and diagnostic privacy; then consider a separately authorized check of the **saved** Luna assessment. The recovery-required accounting boundary still applies. This reconciliation does not authorize that inference, regeneration, DOE execution, another model/threshold campaign or public activation.
