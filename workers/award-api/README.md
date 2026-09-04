# Funding Finder award API

This Worker is the historical-award data boundary established in Phase 1 and
extended with an isolated Department of Defense adapter backed by USAspending. It exposes:

- `POST /awards/search` for bounded NSF, NIH RePORTER, and DOE Office of
  Science PAMS searches normalized to one award schema;
- `POST /awards/snapshots` plus `/page`, `/batch`, and `/retry` for immutable,
  server-authoritative result snapshots;
- `POST /awards/snapshots/evidence` for bounded deterministic retrieval over
  an unexpired Program Officer snapshot. Evidence requests declare
  `"plan_format": "provider-concepts-v1"` and carry a provider-generated,
  browser-validated plan of at most 16 concepts, eight ranking phrases, and
  eight exclusions. The Worker never interprets the raw question. Matching
  tokenizes up to 20,000 retained abstract characters per award; and
- `GET /health` for the enabled sources, adapter versions, cache ceiling, and
  credential requirement only.

In production, the page imports the same DoD adapter and snapshot primitives
from this package but makes the USAspending network requests from the browser.
USAspending returns `Access-Control-Allow-Origin: *` for these public endpoints,
while its edge rejects Cloudflare Worker egress. `source_transports.DOD` therefore
reports `browser_direct_cors`, and a direct DoD request to the production Worker
fails fast with `client_direct_required` instead of waiting on an unreachable
upstream. The page merges the normalized DoD result into the same result and
snapshot contracts used for the other sources; this is a transport boundary,
not a second DoD schema or search implementation.

The Worker follows the existing Funding Finder service pattern: strict request
bounds, dependency-injected source calls, deterministic fixtures, explicit
provenance, local-development and production-origin CORS, and a small public
health response. It does not import or modify the Funding Finder ranking code.

## Request contract

```json
{
  "sources": ["NSF", "NIH", "DOE", "DOD"],
  "criteria": {
    "topic": "warm dense matter",
    "institution_id": "university-of-rochester",
    "year_start": 2020,
    "year_end": 2026
  },
  "limit": 10,
  "offset": 0
}
```

Criteria may use `award_id` (NSF, DOE, or DoD), `core_project_number` (NIH),
`opportunity_number` (NIH FOA or exact DOE Office of Science FOA), `program`, `topic`, `institution_id` or
`institution`, `pi`, `program_officer`, and a bounded year range. NSF program
codes are six-character program element codes. A reviewed NSF parent mapping
may use `program_codes` with at most 24 exact program element codes. NIH program
identifiers are activity codes such as `R01`. DOE program searches use the
PAMS public Program Area field. Requests containing DOE are limited to ten
results and a documented bounded browse window. DoD program searches accept
only numeric Assistance Listing codes such as `12.800`; DoD PI,
program-officer, core-project, program-code, and opportunity-number filters
are reported as unsupported without discarding successful results from other
selected sources.

The DoD adapter calls USAspending's prime-award search and award-detail
endpoints through the production browser transport. Every request is restricted to Department of Defense assistance
award types `04` (Project Grant) and `05` (Cooperative Agreement). Contracts,
IDVs, direct payments, loans, subawards, and separate SBIR or DTIC feeds are
outside this catalog. Detail enrichment is bounded to the returned page,
concurrent in groups of three, and cached on successful responses. If a detail
record fails, the base search result remains available with honest null fields,
the source health is marked degraded, and both award interfaces report the
failed-detail count. All valid Assistance Listings from award detail are
retained; an exact queried listing is ordered first and supplies the displayed
program name without discarding the award's other listings. If stale or
unavailable detail omits it, the exact queried code is still retained first
without inventing a title. Every retained listing contributes its own
code-keyed Institutional Intelligence program facet, and a shared facet prefers
an available official title over a code-only fallback label.
Search-row award ID, recipient identity, signed year, and overlapping base
fields remain authoritative so optional cached detail cannot invalidate a
selected page. When a ROR identity has no curated UEI, DoD fairly traverses up
to three validated recipient names within the shared 12-page source bound,
deduplicates the union, and applies exact institution validation before paging.
Later USAspending result pages use stable Award ID ordering and are traversed
sequentially with the paired continuation values returned by the preceding
page; direct page jumps are not used. DoD offsets are applied after exact
institution and normalized year validation. Up to 12 upstream pages may be
inspected to fill the bounded first normalized snapshot page, while detail
enrichment remains capped at 25 records with concurrency three. Each
USAspending search request has a 20-second deadline, and the complete DoD
operation, including ROR identity resolution and optional
detail enrichment, shares a 100-second budget below the browser's 120-second
deadline. Browser source and detail cache operations are capped at two seconds,
successful entries are retained for one hour, and cache failures remain
non-fatal. Four-source snapshots reuse the shared snapshot primitives and are
kept in bounded one-hour browser session storage; NSF, NIH, and DOE snapshots
remain in the Worker cache. Reaching the upstream
ceiling is reported as a safety-bound diagnostic, but it does not advertise a
client next page unless a normalized lookahead record was actually collected.

The response returns a flat normalized `results` list and a per-source status.
One source failure never discards successful results from the other sources.
NIH annual applications are grouped by `core_project_num`; their original
application IDs, project numbers, fiscal years, amounts, and official links are
retained in `annual_support`. The public `offset` advances through those
normalized core projects. RePORTER annual-record offsets are scanned internally
until the requested project page and one-project lookahead are available.

## Contact policy

Email is copied only from an explicit source response field. Missing email stays
`null`, while `official_contact_url` points to the official NSF Award Search,
NIH RePORTER, or PAMS public record. The inspected PAMS records did not expose
email fields, so DOE contact emails remain null. USAspending does not expose
award-level investigator or program-contact fields for the DoD records in this
catalog. No name-to-email inference or page reveal automation is performed.

Person-like program contacts also receive a deterministic same-source identity
made from the source, exact source-published display name, and a comparison key.
The key normalizes display-only Unicode, case, whitespace, punctuation, and
comma ordering while preserving substantive tokens, middle initials, and
suffixes. It never uses email, crosses sources, or infers aliases. Dedicated
Program Officer snapshots send the exact source name upstream and then reject
every returned award whose normalized `program_contacts` do not contain that
same key before totals, facets, pages, or evidence are computed.

Program Officer snapshot criteria use `mode: "program_officer"`, one source,
the exact `program_officer` name, `program_contact_key`, and a `year_preset` of
`recent5`, `all`, or `custom`. The recent preset derives five inclusive source
award years from the snapshot's single UTC clock. Public metadata discloses the
exact or lower-bound total, source/coverage state, abstract coverage, expiry,
and post-validation counts.

The evidence endpoint accepts only a snapshot ID, a strict bounded topical plan,
and a limit no greater than 24. Every provider concept must occur in the same
record; an exclusion disqualifies a record; phrases affect deterministic ordering
but cannot admit a record. It scores the complete stored snapshot without
changing membership, returns at most 800 abstract characters per record and
18,000 serialized evidence characters, and never stores the plan. Title
matches outweigh abstract matches; program/office fields are supporting
signals, and investigator/institution fields are weak signals. The endpoint
uses the existing origin, body-size, expiration, and Durable Object abuse-control
contracts. Its tokenizer is deliberately conservative: alphanumeric formulas
such as `CO2`, `H2`, and `As2O3` and the short allowlist `AI`, `ML`, and `pH` are
accepted; ambiguous alphabetic two-letter tokens such as `Am`, `As`, `At`, `Be`,
`He`, and `In` are rejected, so the provider must return full names. No
capitalization, punctuation, bracket, neighbor, or notation inference is used.
It creates no corpus or database.

## Cache and credentials

Successful NSF, NIH, and DOE responses and immutable Worker snapshots use the Cloudflare Cache API for one
hour. Successful DoD source and detail responses use the browser Cache API for
one hour. Failures are never cached, and a cache failure falls through to the
official source without coupling source availability. All four public sources
are account-free; neither transport has a source API-key binding.

The DOE adapter uses the account-free PAMS public WebForms search documented in
`docs/DOE_PAMS_PUBLIC_AWARD_RECONNAISSANCE.md`. It obtains fresh view-state per
search, forces all-status/all-country coverage, retains source-native order,
and fetches at most ten direct public abstracts with concurrency two. A PAMS
markup or availability failure is contained to DOE.

Phase 2 links this boundary from the Funded Awards product. Current NIH
opportunities use exact FOA numbers. Eligible NSF opportunities use an exact
program element code or a committed, reviewed parent-program code set; the
browser does not silently substitute a fuzzy title match. DOE Office of Science
opportunities use exact `DE-FOA-<number>` solicitation searches only. DoD
award cards compare the detail record's funding-opportunity number with the
current catalog and show the original opportunity only when exactly one
catalog record matches. Zero or multiple matches fail closed.

## Deployment

The protected-main `Deploy Funded Awards service` workflow validates the award
contracts, deploys this Worker, waits for its public health contract, runs one
exact bounded Worker smoke for each of NSF, NIH, and DOE plus one exact DoD
browser-transport smoke against the official CORS responses, and then verifies that
GitHub Pages serves the same committed Funded Awards page. If a prior Worker exists, a failed
health, source, or Pages check automatically restores that version. The live
smoke set contains one exact, bounded query per source; pull-request CI uses
deterministic fixtures and does not call PAMS or USAspending.
