# Stage 2 contextual drawers: scope and evidence

Protected main was resolved from GitHub to `42ec9a74c9c58269e89e5ed2acad4e2c536af989` before creating `codex/stage2-contextual-drawers`. The intervening history after the plan audit `5dc303589e73e44cde1ecd09c79e3616cd1982c1` is Stage 1 PR #137, including its completed Popover fallback remediation. There were no other newer merges or open PRs at branch creation or the pre-PR refresh. The work starts directly from that protected main. Full AGENTS.md was read; no nested instructions apply.

## Bounded implementation

| Existing behavior | Stage 2 presentation and ownership |
| --- | --- |
| Results Ask AI, bounded result IDs | Existing `result-assistant` is a wide native dialog outside `.workspace`; shared shell context `results` |
| Card More / Ask AI | Same delegated action and single-opportunity state; context `opportunity`; closing resolves the same card's More after its existing result rerender |
| Uploaded notice extraction, matching, PDF context and connected card actions | Existing functions and markup in the same dialog; context `notice`; original upload opener is retained across asynchronous extraction |
| Provider choice, in-tab key, optional saved key and removal | One existing `provider-setup` DOM subtree moves between search and chat slots. Its field values, storage listeners and prior disclosure state survive closing, switching and failed opens |
| Suggestions, responses, copy, retry, result links and privacy text | Existing conversation and handlers retained; request construction and model/provider routing unchanged |
| Opportunity-team proposals | Existing scope/proposal/removal/replacement API rendered into one `team-builder-content` slot in the wide Team Builder dialog |
| Broad parent / child or declared branch selection | Existing chooser and exact eligibility rules retained; stale asynchronous scope/load completions cannot populate a closed or replaced context |
| Continue in Team Match and missing-researcher route | Existing URL construction and selected researcher identities retained |
| Workspace and menus | Same Stage 1 controller. Added drawer cleanup callbacks, named contexts and opener resolution; no second overlay owner, history state or global key listener |
| More affordance | Card ellipsis replaced by the existing shared navigation/results chevron `▾` |

Team Model v2 has not landed as a separate replacement API. This is a presentation adapter over the current reviewed model. The scientific team generation, schema, scoring and dataset are unchanged. The team-panel presentation script now receives its own content-derived version in both the page and normal refresh generator; the scientific generation remains independently bound.

Late AI completions and errors are discarded when the conversation, context mode or ordinary-search signature has changed. They cannot append an old answer to a new opportunity or clear a newer conversation's working state. Current-context success, failure and retry still follow the existing request and display paths.

## Preservation evidence

Before edits, the complete relevant JS/CSS/test reference inventory was recorded in `outputs/stage2/prechange-references.txt`. The baseline focused suite passed 36 tests and the frozen retrieval baseline passed all 37 queries with zero top-10 churn.

`tests/fixtures/stage2-preserved-behavior.json` records the exact protected-base code, request-construction and generated-artifact hashes. Protected code and sampled team rendering/handoff functions are checked by focused contracts. Generated-artifact hashes are audit evidence only, so catalog and researcher publication can continue normally. Existing dynamic generation/coherence contracts remain authoritative for refreshed data.

The Stage 1 executable fixture continues to verify identical CSV bytes, URL output, saved-search and opportunity-alert definitions, source targets and team availability. Team Match's bounded same-tab return snapshot, exact navigation token consumption/removal, canonical directory identities, faculty-match content binding, researcher public/private workflows, and Funded Awards source-native behavior are unchanged.

## Validation before PR

- 112 focused browser contracts passed across shell/dialog lifecycle, Stage 1 action routes, Stage 2 AI/team state, provider/notice/chat, AI refinement, public navigation, team currentness, researcher intake/registry and award behavior.
- After adding asynchronous upload-opener preservation, 15 affected AI/notice contracts passed, including the new notice-context focus regression. All 14 focused Python page-entrypoint/model tests passed on the updated candidate.
- Native browser inspection used desktop 1280 × 900 and mobile 320/390 × 850, without Playwright or an E2E runner. Results and single-opportunity AI contexts, canonical provider switching and disabled Send without a key, Escape to exact results/card opener, Team Builder proposal/removal/replacement, broad-call scope chooser and exact Team Match URLs were exercised. The 320 px Remove button was adjusted to avoid breaking its word.
- Native Funded Awards inspection retained the accessible four-source group and two-row `NSF · NIH` / `DOE · DoD` badge at 320 px. Funding Finder's header remained contained at 320 px.
- PDF extraction-to-drawer context/focus and stale PDF response behavior were verified with runtime fixtures; a PDF was not uploaded through native browser automation. No private data, alert submission or paid AI request was used for validation.
- Versioned public references and `data/search-v2-release.json` were refreshed coherently. Search corpus, vector, allowlist, registry and team artifacts are unchanged.
- Manual E2E selectors were updated for the moved team dialog only; no E2E/Playwright suite was run or enabled, and no workflow was modified. Complete protected Python/browser checks run through the PR on its exact candidate.

Stage 3 search-workflow redesign, new team algorithms, saved teams, recent searches, researcher form changes and private administrator changes are outside this patch.

## Completed first review and consolidated remediation

PR #138 candidate `f93e168a8d55b3b2dc2fa3ae8d9f498057831ef8` received a terminal submitted Codex review (review `5118935505`, completed 2026-09-05 00:21:14 UTC) with one finding: the existing provider-privacy contract searched for the literal opening tag without the newly canonical ID. Protected run `33932470884` passed Python and 616 of 617 browser contracts, with exactly that assertion failing.

After collecting the complete conversation, submitted review, inline findings and reactions, a read-only audit covered all provider-setup, removed duplicate-provider, old chat-overlay and team-close references across app, CSS and tests. Only the one literal tag assertion needed remediation. The bounded batch switches that assertion to the canonical `details.provider-setup#provider-setup` DOM selector, checks uniqueness and retains every privacy, provider and asset-binding assertion. Product code is unchanged. The corrected commit requires its own protected checks and exactly one exact-head re-review before merge.
