# Public workflow and update robustness audit

This bounded audit resumes PR #140 after the completed review of
`f064e04e42613b21f90b892980d8faefdc48f935`. Protected main remained
`b9cb5b714b1ee9d5fccd83368dc8ecb8e4951177`; there were no other open PRs.
The user requested a workflow/search review and hardening before E2E. No E2E or
Playwright suite was executed. The existing protected Python/browser gate and
exact-head review still govern merge.

## Workflow and search conclusions

| User transition | Existing owner and audited invariant | Failure/update protection |
| --- | --- | --- |
| Enter topic, browse, refine, clear, restore a URL | `app.js` owns applied query, profile, filters, sort, page and history; shell controls reveal those exact inputs | Catalog-dependent state commits only after required objects exist; pending URL/filter selections survive lazy loading |
| Receive Strong then Potential matches | Local retrieval determines Strong; hybrid retrieval uses eligible parent IDs before each bounded stage and removes Strong duplicates | Query, filter and catalog signatures plus sequence checks reject late responses; identical requests share work; failures retain Strong results and truthful retry status |
| Sort, page, filter team options, export | Existing display pipeline owns tier ordering and current team eligibility; CSV uses the same canonical result identities | Sorting does not change hybrid membership/signatures; page bounds are clamped; shared menus do not own search state |
| Save, alert, ask AI, build a team | Existing saved, alert, AI and exact-scope team owners receive the original delegated actions | One canonical search-alert control; save feedback survives a closed Workspace; refinement is invalidated on changed criteria; token/currentness/privacy contracts remain intact |
| Edit a team across screen widths | One editor node moves between the sidebar and native sheet | Preserve a genuinely open sheet; preserve an explicitly closed sheet; keep input nodes, values, handlers, status and focus |
| Search awards, switch summary, ask a question, follow evidence, go Back | Snapshot controller owns committed criteria, source requests, bounded history, evidence and focus IDs; public adapter reveals the appropriate panel | Failed replacement requests retain committed results; late work cannot replace a restored snapshot; closing AI makes underlying page controls reachable |
| Update a researcher and return to Team Match | Existing public intake and Team Match handoff owners | Exact token consumption, selected directory identities, local-only profiles, consent and governed registry/admin flows remain byte-identical |

The audit found no reason to change search admission, ranking, profile semantics,
source-native award queries, request/privacy payloads or storage. The existing
search-product, hybrid-production, catalog-startup and Stage 3 contracts exercise
these protections. Stage 4's immutable-file and function baselines additionally
prove this patch leaves the business owners and generated identities unchanged.
This is a code/contract and native-browser audit, not a claim of exhaustive live
provider testing or a human usability study.

## Corrections and safeguards

- Team breakpoint focus now carries explicit presentation intent: sidebar focus
  inherited from an open sheet can resume it; sidebar focus inherited from its
  closed opener returns to Edit team with the sheet still closed. The audit covered
  Done, editor inputs, opener, sidebar, results, both directions, repeated cycles,
  queued native closes, status relocation and scroll lock. Contracts exercise both
  open and dismissed cycles. Native 320 → 1280 → 320 inspection confirmed a closed
  sheet returns focus to Edit team and remains closed.
- Dormant award/accessibility checks use shared visible-control helpers to open
  and close Ask AI, select a summary view and reveal advanced criteria. Hydration,
  replacement search and facet flows close AI before operating the page and reopen
  it to inspect answers. Cleared-answer checks inspect the answer's own hidden
  state, so a closed parent dialog cannot produce a false pass. The Funding Finder
  award handoff opens the actual card More menu. Syntax and helper contracts run
  without importing Playwright or executing its suites. This is targeted fixture
  maintenance, not a claim that the entire dormant E2E suite has passed.
- `tools/sync_public_shell_assets.mjs` checks or updates the eight shared
  presentation assets across all four public pages. Both `assets/` and `./assets/`
  routes are supported. It reads the complete family before writing, preserves
  unrelated content/identities, fails on missing integration, and is idempotent.
  The normal browser contract suite rejects stale served-byte versions. No private
  pages or generated catalog, researcher, team or search identity rules are changed.

## Routine shell updates

After editing shared public presentation files, run:

```text
node tools/sync_public_shell_assets.mjs --write
node tools/build_search_release_package.mjs --write
```

The first command updates the browser cache keys; the existing release generator
then records those exact HTML/source bytes. For read-only verification, use
`node tools/sync_public_shell_assets.mjs --check`. Do not hand-edit generated
identity fields or introduce another cache/version owner.

The resumed batch passed 66 focused search, startup, shell, lifecycle and maintenance
contracts. Exact-head full CI and review evidence are recorded in PR #140; deployment
evidence is collected only after protected merge. Earlier walkthrough evidence and
device-testing limitations remain in `STAGE5_SHELL_HARDENING.md`.
