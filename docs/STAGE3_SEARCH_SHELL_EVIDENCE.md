# Stage 3: results-first Funding Finder

## Protected base and bounded scope

GitHub protected main resolved to `d0d7a8a2401a0489b63ad8b0d909b434898b4697`, the Stage 2 merge, before creating `codex/stage3-results-first`. No merges followed Stage 2 and there were no open PRs at branch creation or the pre-PR refresh. The intervening history since the plan's informational audit is the completed Stage 1 and Stage 2 work documented in this directory. Full AGENTS.md was read; no nested instructions apply.

The user's request advances the supplied plan to Stage 3 only. The implementation changes Funding Finder's presentation before/after search and moves its existing configuration controls into Refine Search. Stage 4 public-page redesign, new search algorithms, recent searches, saved teams and new state/storage models are excluded. The existing More chevrons remain; ellipses are not reintroduced.

## Control and state ownership

| Existing control or behavior | Stage 3 location and routing |
| --- | --- |
| Query, notice upload/drop, Find funding | Same `search-form`, `query`, `nofo-file` and canonical submit button. Initial question becomes a compact Funding search heading after search. |
| Research profile, keywords, applicant context, career stage | Same controls, IDs, attributes, handlers and form ownership inside the native `refine-search` dialog. Add research context opens the existing profile disclosure. |
| ORCID, CV, optional local profile saving and consent | Original controls and private browser state retained. No upload, import, storage or consent pipeline changes. |
| Facets, status, dates, amount, flags and audience | Existing `filter-panel` and controls in Refine. Add filters opens its disclosure. Existing change handlers still update results; rerender leaves the drawer and focus intact. |
| Optional AI refinement and Restore original results | Original controls inside Refine after search. Same eligibility, provider, requests, assessments and restoration logic. Successful refinement closes Refine only when that drawer is still open. |
| AI provider and optional personal key | Same Stage 2 `provider-setup` subtree and `search-provider-slot`, now within Refine. Chat still temporarily owns that single subtree and returns it on close. |
| Refine footer Find funding | Delegates to `search-form.requestSubmit(find-funding)`. No duplicate submit handler, input copy or payload construction. Native Enter from a profile field submits the original form. |
| Search/AI status | Existing single live nodes. Search status follows the shared drawer lifecycle; AI refinement status moves into Refine while open and returns to a global slot when closed/switched. |
| Clear search | Secondary compact-header button invokes unchanged `clearEverything`, then focuses the query. Existing URL replacement/reset semantics remain. |
| Counts, team filter, sort, Ask AI, Results More | Existing result header immediately below the compact search area. Empty displays suppress Sort and unavailable chat; Results More remains available for eligible typed search alerts. |
| Empty/loading/degraded result states | One contextual next action through the existing delegate: Refine, uploaded-notice chat, or the canonical team filter. Loading and hosted degradation have distinct headings; source, stale-catalog and Potential status surfaces remain outside the drawer. |
| Workspace, card actions, AI drawer, Team Builder, public routes | Existing Stage 1/2 owners and handlers retained. Other public pages change only app stylesheet content versions. |

Refine lives inside the original form without a nested form. This preserves Enter submission and keeps every profile/filter/provider input singular. Dialog state is never written to URL/history. The Stage 1/2 native shell supplies Escape, backdrop close, modal keyboard containment, synchronous cleanup and exact opener restoration. A disappeared initial/empty opener resolves to the compact Refine button. Validation opens and focuses the relevant profile field; an empty search closes Refine before focusing the query outside it.

No sticky search layer was added. The dialog scrolls as one surface, with its footer reachable at 320 px. Scoped single-column profile/provider/import controls and wrapped mobile actions preserve the 16 px editable-control floor and pinch zoom. The visually hidden ORCID label retains its 1 px sizing instead of receiving the full-width input rule.

## Baseline and focused evidence

Before edits, `outputs/stage3/prechange-references.txt` recorded current JS/CSS/test references across the search workflow, profile/filter/provider controls, AI refinement, statuses and empty actions. The protected-base focused suite passed 47 contracts; all 37 frozen queries had zero top-10 churn.

`tests/fixtures/stage3-preserved-behavior.json` was captured from the protected base before edits. It records all original profile/filter/provider control attributes and select options plus hashes of search execution/ranking, URL serialization, profile construction/import, reset/filter counting, CSV, search alerts and provider request routing. The new contracts compare these to the candidate. Stage 1 executable CSV/URL/saved/source/alert fixtures and Stage 2 AI/team/registry/cache identity guards remain active. Scientific generated artifacts, corpus, vector and worker allowlist are unchanged; only frontend source/version bindings in the search release manifest change.

Focused validation before PR:

- 68 browser contracts passed across the new search shell, shared shell, contextual drawers, result action routes, profile/search behavior and additive AI. All 13 Stage 3 contracts subsequently passed with the added filter-rerender regression.
- Seven Python page-entrypoint tests passed, and all 37 frozen query checks again reported zero top-10 churn.
- Native browser checks at desktop 1280 × 900 and mobile 320/390 × 900 exercised initial and restored-query states, section opening, Escape and exact focus return, retained draft keywords, Enter submission from Refine, and scrolling to the drawer footer. No E2E runner or Playwright API was used.
- The representative `?q=inner+ear` search retained 4 Strong and 12 Potential results and its original first official NIH target. Before Stage 3 the numbered setup occupied the first desktop screen; after Stage 3 the first card begins approximately 450 px from the top and is visible in that screen. The Funding Finder header, query/upload/submit row and Refine sheet remained contained at both narrow widths.
- Native checks found and corrected the compact trigger's empty-section opening path and an expanded ORCID layout overflow at 320 px. Runtime contracts cover both regressions.
- No private files, live alert submission or paid AI operation was used. Existing runtime fixtures verify CV/notice extraction, request/privacy payloads, and async AI/team lifecycle behavior.

Complete protected Python/browser gates and the configured comprehensive review run through the PR on the exact committed candidate. This document records pre-PR evidence, not a claim that pending review or deployment has completed. No workflow or automatic-refresh policy is changed; E2E remains manual-only and was not run or polled.

## Completed review and consolidated remediation

PR #139 candidate `32bdcd9f1e038cd870f447b8bb8039df62b5e9a6` received a terminal Codex review (`5119125245`, 2026-09-05 01:10:33 UTC) with one finding: native form validation could block submission while an invalid Refine control was in the closed drawer. Protected run `33935125796` passed Python and 629 of 630 browser contracts; the single browser failure was a case-sensitive assertion for the now sentence-initial word “Hosted.”

After collecting the full conversation, submitted review, inline thread and reactions, the read-only audit covered all search-form constraints, nested disclosures, native/canonical/Enter submission paths, profile validation focus, status custody and hosted-query privacy copy/contracts. The bounded remediation adds one capturing invalid-event owner to the existing form. Native validation continues to block an invalid submission; the handler opens Refine and all ancestor disclosures, focuses the first invalid control, announces the browser's validation message through the existing live status, and leaves values unchanged. Additional invalid controls in the same validation pass cannot steal focus. The privacy-copy assertion accepts sentence-initial capitalization while retaining the same typed-topic and private-context restrictions. No search eligibility, native constraints or payload logic is bypassed.

All 50 targeted remediation contracts passed. Native verification reproduced the reported flow with `award-min=500` and both the drawer and nested Deadline and award disclosure closed: Find funding reopened the drawer, expanded the disclosure, focused the field and announced its native validation message. Changing the amount to `1000` and pressing Enter submitted successfully through the original form and retained the expected query/filter URL.

The corrected candidate requires its own protected gates and exactly one exact-head re-review. No edits were made while the first review was pending.
