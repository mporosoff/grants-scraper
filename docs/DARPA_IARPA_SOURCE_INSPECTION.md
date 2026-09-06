# DARPA / IARPA research solicitation source

Verified September 5, 2026. The pre-change catalog contained five DARPA
Grants.gov records and no individual Disruption/QBI or IARPA records.

## Live inventory and admission

The public [DARPA opportunity table](https://www.darpa.mil/work-with-us/opportunities)
loads [this JSON inventory](https://www.darpa.mil/json/opportunity.json).
Its 143 rows include joins repeating the same solicitation, events, RFIs,
small-business topics, office-wide BAAs, and umbrella program announcements.
The RSS feed is truncated and often links to the generic listing, so it is not
used for inventory discovery.

One enabled `darpa-iarpa` adapter discovers individual DARPA PA topics, requires
Disruption/QBI research submission language, and confirms the exact child
number, official solicitation link and current date on its linked program page.
It does not infer an application date from an event or an umbrella PA.
Child-shaped PA numbers for other programs are excluded before detail fetching;
only established Disruption/QBI scope makes submission evidence required.
Explicit closed status markers, including standalone HTML labels, exclude the
corresponding child while leaving its open siblings available.
For both sponsors, explicit closure and verified date-window exclusions precede
positive admission requirements such as submission language and action links.

| Individual call | Solicitation | Program-page submission deadline |
|---|---|---|
| [SHINE](https://www.darpa.mil/research/programs/shine) | DARPA-PA-25-07-06 | October 9, 2026 |
| [Resilient](https://www.darpa.mil/research/programs/resilient) | DARPA-PA-25-07-04 | October 19, 2026 |
| [QBIT Stage A](https://www.darpa.mil/research/programs/quantum-benchmarking-initiative) | DARPA-PA-26-02-02 | November 30, 2026 |
| [QBI independent verification and validation](https://www.darpa.mil/research/programs/quantum-benchmarking-initiative) | DARPA-PA-26-02-01 | December 30, 2026 |

The table still lists September 30 for QBIT Stage A; the exact topic's program
block lists November 30. The adapter uses the program-block date, records both
values in source diagnostics, and attaches the program URL to the structured
deadline. The card links directly to the official SAM.gov solicitation.

The [IARPA open R&D table](https://www.iarpa.gov/engage-with-us/open-r-d-opportunities)
explicitly reported no open opportunities. This is a healthy zero, not a fetch
failure. The adapter follows only program links in that table; it requires an
open research solicitation status, a matching solicitation-number link and a
current recognized proposal date. An administrative closing date never replaces
a missing, blank, renamed or expired proposal deadline. RFI, draft, event, cancelled and closed statuses are
excluded. IARPA's old `/engage-with-us/open-baas` route returns 404 and its
commented-out RSS links are not active discovery routes.

The positive IARPA regression case is synthetic. Its markup follows the
status/date blocks inspected on the closed
[Video LINCS page](https://www.iarpa.gov/research-programs/video-lincs).
It proves parsing against that structure without presenting an invented call
as live funding. A future unsupported row or changed table/status structure
fails closed and is visible through the existing source-health reporting.

## Identity and lifecycle

DARPA and IARPA records use normalized sponsor plus normalized solicitation
number in catalog identity and cross-source merge. Agency acronyms, full names
and office-specific agency labels resolve to the same sponsor. Whitespace,
case and punctuation do not split a number, including in DARPA's discovery
inventory and exact program blocks. In-scope rows with an unrecognized number
format are reported as source degradation rather than a healthy zero; a
recognized umbrella-only inventory can correctly contain no individual calls.
Distinct sponsors or distinct
solicitations survive even if their numbers or titles match. Grants.gov wins
when both sources identify the same call. Other adapters keep their established
deduplication rules.

Both inventories belong to one adapter and one atomic refresh. It has no
stale fallback: if either inventory or a required detail fetch fails, the
adapter clears its cached rows and publishes zero with degraded diagnostics.
Verified empty inventories remain healthy. Removed calls disappear on the
next successful source refresh.

Required confirmation failures are distinct from exclusions. An otherwise
actionable child with a missing or unsupported program/solicitation route,
missing exact action link, unrecognized status, missing/unparseable submission
date, inverted date window or conflicting confirmation degrades the source.
All exact solicitation links must identify one valid SAM notice, allowing
equivalent public and workspace URL forms. DARPA also requires that notice to
match its inventory and exactly one program block to match the child number.
Conflicting date fields or status blocks cannot be resolved by page order.
IARPA requires an explicit open research status; "not open" variants are
excluded. Explicit non-call/closed statuses and
verified expired or future submission windows are normal exclusions. Missing
proof cannot silently turn a populated research inventory into a healthy zero.

## Site wiring and verification

Registration uses the existing refresh workflow, with the identity module
added to its path triggers. No synthetic records or partial generated release
are committed. The normal refresh merges this adapter before rebuilding
faculty matching, change events, feeds, proposed teams, all production document
vectors, the Worker compatibility package and the coordinated Pages release.

The canonical records carry source type, sponsor, stable ID, solicitation
number, technical description, topics, official action and structured deadline.
They use the existing agency/topic filters, lexical and semantic search,
comparison, saved results, CSV/calendar exports and opportunity alerts.
Funding instrument, award amount and eligibility stay unknown when not
established by the official source; no unsupported award-provider mapping or
team result is invented.

The live local merge added four records, with no overlaps or invalid rows, and
passed catalog validation. The local preview and source-health evidence are in
`outputs/darpa-iarpa-preview/`; this is not evidence of production publication.
Offline contracts cover both sponsors, repeat collection, Grants.gov precedence,
same-title distinct calls, same-number distinct sponsors, dates, exclusions,
failure policy, facets, search, feeds, change events, official actions, exports
and opportunity watch payloads. The required Python and browser suites and
frozen query/P9 checks passed. No E2E or Playwright suites were run.
