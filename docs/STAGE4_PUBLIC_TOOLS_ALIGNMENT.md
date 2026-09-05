# Stage 4 public tool alignment

Protected-main starting point: `b9cb5b714b1ee9d5fccd83368dc8ecb8e4951177`.
The audit SHA was informational. Main was resolved again before creating the isolated
`codex/stage4-public-alignment` branch. The only merges after the plan audit were
Stages 1, 2 and 3 (PRs #137, #138 and #139); the open-PR inventory was empty.
The complete repository `AGENTS.md` was read before editing.

## Control and ownership map

| Existing surface | Stage 4 location | Existing owner retained |
| --- | --- | --- |
| Team members, Add researcher, directory combobox, saved researcher selection/removal | One `#team-editor-content` subtree in desktop `#team-sidebar`, moved into mobile `#team-editor-sheet` | Inline Team Match controller; `team-researchers.js` |
| Selected research summaries and shared/complementary theme toggles | Same editor; sticky desktop sidebar, mobile sheet | `renderSelectedResearcherCards`, `renderThemes`, original matching and theme state |
| Team selection summary | Compact mobile text and Edit team opener | Text derived from current selected names; no second selection owner |
| Team match count and text filter | Matching opportunities header beside the editor | Original `renderTeam`, `refresh`, filter and history values |
| Team card official source, secondary records, Funding Finder route, calendar and contact | Original result cards | Original card builders and delegated calendar action |
| Missing researcher handoff | Original control inside the team editor | Exact same bounded session snapshot, navigation token, token consumption, selected identities and return restoration |
| Team add/error/handoff feedback | `#team-status-home` when closed; same live node inside open sheet | Original `#external-status` and status setter |
| Award institution, agency, program, topic | Primary search fields | Original field IDs, source-native request construction and ROR selection |
| Award investigator, program officer, From/Through year | Advanced search disclosure inside the original form | Original constraints and submit handler; invalid/restored fields are revealed |
| Exact program-officer scope and year preset | Original visible source-scope section | Original locked query and immutable snapshot logic |
| Award heading, result scope/counts and Ask AI entry | Shared result-header styling | Original heading/count renderer; single new dialog opener |
| Project cards and page-size/page controls | Projects view | Original snapshot page data and pagination handlers |
| Investigator/program selectors and name-variant details | Investigators / Programs views | Original facet selectors and change handlers; successful facet navigation reveals Projects |
| Metrics and recipient-institution selector | Institution summary view | Original current aggregate and base-aggregate facet data |
| Source completeness/capabilities/limits and load-more controls | Outside the view panels | Original source-status and source-load/retry logic |
| Award AI question, provider/key controls, answer/evidence, privacy copy | Single `#awards-ai` native drawer | Original question, consent/privacy bounds, provider credentials, deterministic evidence and synthesis paths |
| Award request/source status during AI work | Original live status node moves into open drawer and returns to its original home on close | One status owner; no copied announcements |
| Evidence links in AI answer | Close drawer only after target record is available, reveal Projects and focus that record | Original evidence-to-page lookup and fetch/recovery |
| Public researcher update | Existing `faculty_interests.html`, titled Update researcher profile, shared header and Help | Entire governed form and application script unchanged |

## Bounded presentation changes

`site-shell.js` remains the owner of native modal lifecycle, Escape/backdrop dismissal,
focus restoration and transient action menus. `public-tools.js` adds presentation
adapters, one breakpoint listener for the single Team Match editor and one delegated
award-view switcher. It makes no requests and owns no storage, query, facet, ranking,
AI or URL state. Views use ordinary buttons with `aria-pressed`, not incomplete ARIA tabs.

Sticky offsets follow the measured public header and mobile summary height. Short
viewports fall back to ordinary document flow. Editor contents remain reachable by
scrolling; editable controls retain the 16 px mobile floor and zoom is unrestricted.
The existing directory combobox consumes its first Escape before native sheet cancellation.

Team Match's large inline stylesheet is now `assets/team-match.css`. The shared page
header, result header, action, disclosure, drawer-body and view styles are in
`assets/public-tools.css`. The new assets use content-derived versions and are included
by the maintained search release generator. The generation, corpus, vectors, allowlist
and faculty-match binding do not change.

No saved-team model or cross-page Workspace is introduced. Existing browser-only
researchers remain reachable from the team editor. Private administrator pages are
outside this patch. Funding Finder's search workflow and its Stage 1–3 surfaces are unchanged.

## Baseline and focused evidence

Before editing, 119 focused browser contracts passed. The reference inventory and
baseline log are retained in the local `outputs/stage4` directory. The checked-in
`stage4-public-baseline.json` records the protected starting SHA, every existing
control and validation rule, researcher form and four-source badge digests, product
owner/identity artifact digests, search release identity and controller function digests.

The Stage 4 contracts check single DOM ownership, exact moved-node identity and values,
mobile/desktop transitions while focused, modal close/reopen, status placement,
evidence navigation, native invalid-field disclosure, history focus restoration,
one delegated view owner and unchanged product/controller invariants. Existing contracts
continue to cover search ordering, CSV, saves, alerts, AI bounds, team currentness,
handoff tokens, researcher public/admin workflow and source-native award snapshots.

Implementation browser observations include a 320 px team sheet with keyboard directory
selection, 20 matches for Porosoff + Foster (first: NSF 26-518), and Escape restoring
the Edit team opener. A collapsed From year of 1980 is revealed and focused with the
native minimum-1989 validation message. The Funded Awards four-source badge is contained
at 320 px. No Playwright or E2E suite was run.

Exact-head protected CI, completed review, merge and deployment evidence are recorded
in the PR and local completion report after the candidate is validated.

## Completed review remediation

The completed review of `55470a862ac41ab0c31578b2404d549f40d9e9da` found that both
new drawer close buttons used an unsupported attribute. The read-only invariant audit
covered all public drawer open/close attributes, the shell's delegated click handler,
native cancellation/backdrop paths, initial focus, status return callbacks, evidence
navigation, history transitions and breakpoint cleanup. Both buttons and the team
initial-focus selector now use the existing `data-shell-drawer-close` contract.
The lifecycle tests activate the actual visible buttons through the shared event
handler and verify closure, exact opener focus, status return and queued close/reopen.
No new close listener or lifecycle owner was introduced.
