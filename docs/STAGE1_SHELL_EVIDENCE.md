# Stage 1 shell: scope and evidence

Base resolved from GitHub: `5dc303589e73e44cde1ecd09c79e3616cd1982c1` (protected main, 2026-09-04). No intervening commits since the plan audit. Open PR inventory was empty immediately before branch creation. Branch: `codex/stage1-site-shell`. Full root AGENTS.md read; no nested instructions found. Required branch checks: `python`, `browser`, strict up-to-date main, resolved review threads. No E2E or Playwright execution.

## Before editing: action inventory

| Existing action / state owner | Stage 1 location and routing |
| --- | --- |
| Saved list/count, clear, pursuit status/note, remove (`renderSaved`, saved.js) | Workspace / Saved opportunities; canonical IDs retained; separate non-stateful header badge mirrors count |
| Save (`data-save`, saved.js) | Card header; global `saved-status` gives immediate confirmation |
| Current-search alert (`alert-new-matches`, `openSavedSearchAlert`) | Workspace / Email alerts; Results More opens and focuses this canonical control |
| Counts (`result-tier-counts`) | First in results header |
| Team filter (`filter-team-ready`) | Team options only; visibility from pre-filter `workflowDisplay`, active toggle always reachable |
| Sort (`sort`) | Results header, same listener and values |
| Export (`export-csv`, `exportCsv`) | Canonical button in Results More |
| Results chat (`open-results-chat`) | Compact Ask AI; existing panel unchanged |
| Official source (`officialActions`, `data-source-open`) | Existing primary anchor stays visible; secondary anchors in Sources |
| Opportunity AI (`data-chat-record`) | More / Analyze, existing results delegate |
| Historical awards (`data-funded-awards`) | More / Analyze, unchanged target and tab semantics |
| Opportunity alert (`data-watch-opportunity`) | More / Track, unchanged definition and submission path |
| Program alert (`data-watch-program`, label) | More / Track, unchanged controlled program identity |
| Calendar (`data-calendar`) | More / Track, unchanged disabled state and export |
| Program contact (`programContactAction`) | More / Contact; same mailto/tel, label and subject |
| Team (`data-opportunity-team`, scope, broad) | Visible second card action only under existing exact availability predicate; inline panel unchanged |
| Evidence, full details, matched-topic disclosure, optional evaluation controls | Remain with existing card evidence; no workflow redesign |
| Researcher updates (`faculty_interests.html`) | One More disclosure in the canonical public nav; no desktop/mobile duplicates |

No existing copy-opportunity-link action exists; none is added. The complete pre-change JS/CSS/test reference inventory is recorded locally in `outputs/stage1/prechange-references.txt`, including non-executed E2E references. Historical evidence documents are not live control owners.

## Representative pre-change outputs

- Deployed search `carbon capture`: URL `match_explorer.html?q=carbon+capture`; 0 Strong / 12 Potential. First records: `362061` (CPS), `351715` (ECLIPSE), `363616` (CBET), `363065`, NYSERDA PON 5989, `363684`, `nsf-cbet:PD-26-370Y`, `362063`, NYSERDA RFP 6224, NYSERDA PON 6220, `344592`, `356538`. Hosted results are observational; frozen local retrieval is the deterministic comparison.
- Frozen retrieval baseline: 37 queries, zero top-10 churn.
- Saved/alerts/researcher handoff/opportunity-team baseline: 55 focused contracts passed. Synthetic saved identity `x1` persists unchanged through toggle, pursuit update and remove; original storage tests include rejecting-storage recovery.
- Executed app functions on a fixed public fixture recorded exact CSV bytes (46 fields), URL with query/public agency filter, saved-search definition/baseline and opportunity triggers in `outputs/stage1/baseline.json`. These are local deterministic fixtures, not production alert submissions.
- CPS primary source: `https://www.nsf.gov/funding/pgm_summ.jsp?pims_id=506547`; secondary Grants.gov `https://www.grants.gov/search-results-detail/362061`; awards `./funded_awards.html?opportunity=362061`; contact subject `Question about PD-26-367Y`.
- Army `344592`: primary attachment `/grantsws/rest/opportunity/att/download/345967`, Grants.gov record, agency `https://arl.devcom.army.mil/opportunities/arl-baa/`, telephone route `tel:9195494281`. Exact eligible-child team tests passed; broad unsupported scopes remain unavailable.
- Team Match handoff: existing tested bounded same-tab snapshot and exact token consumption/removal preserved; no handoff code changes planned.
- Browser screenshots: Funding Finder header contained at 320 px (brand icon, catalog indicator, Help, hamburger); old saved summary crowded/overflowed its card. Funded Awards 320 px badge retained two rows `NSF · NIH` / `DOE · DoD`, accessible four-source group, with Help and hamburger contained. Desktop Funded Awards header also inspected.

## Shell ownership

One shared controller owns transient disclosure/action-list positioning and native Workspace lifecycle. Card descriptors are kept only for the rendered page and materialize into one shared menu on demand. Ordinary Tab order is used; no incomplete ARIA menu roles. Existing native alert and Help dialogs may open as child dialogs over Workspace: this deliberate exception preserves their existing state and restores focus to the canonical in-Workspace opener when dismissed. The browser makes the lower dialog inert while the child is open. AI and team contents are not moved.


## Implementation validation before PR

- Focused baseline comparison is now a checked-in executable contract with `tests/fixtures/stage1-shell-baseline.json`. CSV bytes, canonical alert definitions, URL output and the protected sampled function hashes compare identically.
- 63 focused contracts passed covering shell, source transport, catalog startup/release, researcher intake/registry and Team Match researcher contracts. A subsequent 21 UI/lifecycle contracts and all 7 Python page-entrypoint tests passed after the final layout updates. The full protected Python/browser gates run once on the PR candidate via CI.
- Native browser checks (no Playwright): desktop 1280 x 900 and 320 x 800 Funding Finder header; mobile full-screen Workspace; desktop right drawer; canonical current-search alert route; nested native alert dismissal; zero/one saved badge and visible save status; menu Escape and nested mobile More; card opportunity alert and card AI launch; AI close returns to the same card's More after its result rerender. No alert form, AI request, or researcher update was submitted.
- Menu action cleanup uses the next task, not a microtask, because browsers can checkpoint microtasks between native capture and bubble listeners. This was caught in browser inspection and covered by a focused event-ordering regression contract.
- Shared header navigation now participates in normal flex layout to reserve space for the catalog, Workspace and Help at desktop widths.
- Dedicated manual E2E files have selector/routing updates for the moved controls only. They were not run or enabled. No workflow changed.
- Search/AI/team panels, algorithms, query/history writers, CSV serializer, alert API/payload builders, storage module, researcher intake/admin logic, generated researcher/team data and Funded Awards query/transport code are unchanged. Public HTML bindings and the search release manifest are coherently refreshed for changed shell assets.

## First protected round and consolidated remediation

PR #137 candidate `8275e677bba3b70d9dcb23fa6a4b773f83e4507b`: automated Codex review completed clean (2026-09-04 20:32:43 UTC, completed summary and configured bot thumbs-up; unchanged head throughout). Protected run `33916459536` passed Python and found three stale browser contracts. Read-only audit of the complete related reference family found: former combined saved/alert markup, a saved-status assertion requiring adjacent attributes, and a hard-coded Funded Awards app.css version. One batch updates only these assertions to the new canonical structure and exact content hash; no product code changes. The new candidate requires its own protected checks and one exact-head re-review before merge.

## First review-finding remediation

Candidate `ad85851af19656f5a5f7967a945d0064f42c7726` passed both protected checks in run `33916941604`. Its requested review completed on 2026-09-04 at 20:40:13 UTC with one P2 finding: the legacy-browser fallback attempted the unsupported `:popover-open` selector while closing menus. The completed conversation, submitted review and inline findings were collected before editing. A bounded read-only audit covered all Popover API/selector uses and all shared close paths (Escape, outside interaction, focus departure, terminal action, toggle, drawer opening, scroll, rerender and disconnected opener). Only one unguarded selector existed.

One coherent product-code remediation feature-detects native Popover support before evaluating the selector. The DOM fixture now models absent methods and a throwing unsupported selector; the focused regression exercises the full dismissal family and exact focus/cleanup behavior. All 10 shell contracts passed. Asset bindings and the release manifest are refreshed coherently. This is the first remediation of a consequential review finding; the preceding remediation changed stale CI assertions only. A changed commit must receive its own protected checks and one exact-head re-review.
