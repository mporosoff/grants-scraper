# Stage 5 shell hardening and release evidence

The resumed candidate is PR #140, based on protected main
`b9cb5b714b1ee9d5fccd83368dc8ecb8e4951177`. Main was resolved again, the full
`AGENTS.md` was read, and the complete open-PR inventory contained only this PR.
The Stage 4 checkpoint at `280baedca278994f9faaee97e02cdc2f116b0614` was preserved.
The user's instruction to complete Phase 5 and merge resumes one bounded remediation
round and closes out the existing Stage 4 work in the same PR.

## Read-only invariant audit and changes

Before remediation, the audit covered every team editor focus origin (editor field,
sheet Done, desktop sidebar, mobile opener, results), both breakpoint directions,
native queued close/reopen, status relocation, all four award view buttons and their
panel controls, invalid/restored advanced fields, AI evidence routing, and the
existing history focus/scroll capture and restoration owner.

- Repeated team breakpoint changes carry open-sheet sidebar focus back into the mobile editor.
  A focused mobile Edit team button transfers to the visible sidebar on desktop.
  Resizing while working in results does not open a modal. Exact editor nodes,
  values, selection, listener ownership and matching remain unchanged.
  The resumed workflow audit also preserves an explicitly dismissed sheet across
  a desktop round trip; see `PUBLIC_WORKFLOW_ROBUSTNESS.md` for that correction
  and the shared asset maintenance command.
- Award history restoration derives the visible view from either its switcher
  button or the panel containing the focus target. The existing history controller
  still owns URLs, snapshots, focus IDs, scroll and write throttling.
- Menu positioning constrains both minimum and maximum widths to the visual
  viewport. This prevents a CSS layout-viewport minimum from defeating collision
  handling during pinch zoom. Tests include panned 160 px visual viewports.
- Native screenshots revealed Funding Finder header overlap at 430 and 541 px.
  A page-specific `funding-header` class reserves room for its extra catalog and
  Workspace controls. Compact branding also covers the direct-navigation boundary;
  the 541–700 px range uses compact catalog and Workspace labels. Full accessible
  names, catalog count/freshness, Help and navigation remain available. The award
  source badge markup and its own styles are unchanged.

The regressions were reproduced before correction. No search, alert, AI, team,
researcher, award, storage or URL owner was edited in this resumed batch. Existing
More buttons retain the chevron and no ellipsis. No bottom action bar was added:
the walkthrough found the existing result actions and tool returns reachable, and
did not establish a benefit sufficient to add another persistent surface.

## Native browser walkthrough, 2026-09-05 UTC

These are agent-operated accessibility-tree and screenshot checks, not a human
usability study. Timings include tool and inspection overhead; they are not load-time
benchmarks. No Playwright APIs or E2E suites were used. Pixel scroll distance was
not measured: native accessibility activation scrolls controls into view. There
were no manual scroll commands in the timed sequences, so zero explicit scrolls
must not be interpreted as zero movement or as a human discoverability result.

| Task | Observed result | Time to first useful action |
| --- | --- | --- |
| Search and open source | `catalysis`: 9 Strong, 12 Potential; first CPS result opened the official NSF Chemical Process Systems page | 18.9 s through source activation |
| Save and find again | Immediate save announcement outside Workspace; badge announced one saved opportunity; exact CPS item in Workspace | 1.0 s |
| Current-search alert | Results More → Workspace Email alerts → sole canonical alert control → existing verification form; Escape twice restored Results More | 12.7 s to canonical control |
| Export results | Keyboard More → Export CSV; original CSV owner and frozen fields/records checked by contracts | 0.05 s from focused More |
| Ask AI | Results drawer focused the question; hosted public-context answer cited ARL BAA, Nov 20 2027, and linked its connected result and official source | 0.34 s to drawer, answer time not measured |
| Team from broad parent | Army `W911NF-23-S-0001` required a specific reviewed topic; keyboard selection produced the existing team and exact `344592:ab-0079` Team Match link. Catalysis also opened the exact eligible Genesis child team | 5.9 s to Genesis builder; Army sequence not separately timed |
| Team selection and update round trip | Porosoff + Foster yielded 20 calls; removal and replacement with Muller worked. Update-profile handoff preserved Porosoff + Muller, added a temporary browser-only profile, and removed the handoff token from the return URL | 25.0 s to first selection including breakpoint exercise; 28.3 s for local profile/return |
| Historical awards | NSF + catalysis + 2026 returned 144 exact awards, first NSF 2621831; Back/Forward restored Programs active and focused | 18.8 s to returned snapshot |
| Researcher correction | Keyboard directory selection prefilled Marc D. Porosoff's published profile; consent, payload preview and governed form retained | 0.30 s to selected profile |

The local profile exercise initially supplied one research interest; the existing
validation correctly requested three to eight and focused that field. Three distinct
interests completed the local-only return. This was one input-validation correction,
not a misclick. No unintended product action or filter/action confusion was observed
in the agent walkthrough. No control went undiscovered using accessibility names;
human discoverability and task success rates remain unmeasured. Context returned
after Workspace, AI, Team Builder and award history transitions. Browser tools could
not operate one native local-profile deletion confirmation; this is a tool limitation,
not evidence of a product failure. No alert email, researcher review submission,
registry publication or administrator operation was sent to production.

## Responsive and accessibility coverage

Funding Finder and Funded Awards were inspected at 320, 360, 390, 430, 768 and
desktop widths. Funding Finder's overlap was then corrected and rechecked at
430, 541, 701 and the 1221 px direct-navigation boundary. Deployed 320/390/desktop
verification and the complete served-byte inventory are recorded during closeout.
The four-source badge retains its accessible group, all four labels and the narrow
row-break separator. Team Match's full-screen sheet was checked at 320 px with
Done → desktop sidebar → mobile Done focus, exact input focus during resizing,
keyboard combobox selection, Escape, and visible status outside the closed sheet.
At 390 px, researcher More remained active and opening it retained the hamburger
navigation. Menus stayed within the visible viewport and use ordinary action-list
semantics and native Tab/Enter/Escape operation.

Contracts cover unique IDs and named dialogs, exact close controls, one canonical
saved/search-alert owner, active toggle semantics, forced-color rules, reduced
motion, the 16 px editable-control floor and unrestricted viewport zoom. Existing
sticky offsets use measured header/summary heights and short-height fallbacks.
Actual OS forced-color mode, touch-device pinch gestures and a screen-reader speech
session were not available through these browser controls; source/lifecycle contracts
cover their preserved hooks without claiming those device tests were performed.

## Reliability, performance and protected gates

The two shared controllers are constrained to less than 6 KB combined gzip and make
no network, storage or history writes. Reinitialization cannot register another set
of global listeners. Injected native-modal failure releases scroll lock, status and
focus ownership so an independent tool can still open. Team graph data remains
loaded on demand; no additional initial AI or team rendering was introduced.
Existing contract fixtures exercise saved-storage failure, alert verification and
delivery, provider failure/privacy, late team data/currentness, researcher public and
admin validation, award source failure/transport and immutable snapshot recovery.

Local validation logs are in `outputs/stage5`: 51 focused shell/lifecycle contracts,
194 domain/reliability contracts, then 24 header/public-tool contracts after the
header correction, plus seven Python page checks. Asset versions and the maintained
search release manifest were regenerated from content. Corpus, vectors, faculty-match
binding, team generation, registry identities and worker allowlist remain unchanged.

The protected Python/browser suites run once for the pushed candidate. Merge requires
a clean terminal review of that exact head, green protected checks and resolved
accepted findings. Exact commit, CI, review, merge, deployment and live served-byte
evidence are recorded in the PR and `outputs/stage5` closeout report, after they exist.
