# Funding Finder award API

This Worker is the historical-award data boundary established in Phase 1 and
extended with an isolated Department of Defense adapter backed by USAspending. It exposes:

- `POST /awards/search` for bounded NSF, NIH RePORTER, DOE Office of
  Science PAMS, and DoD USAspending searches normalized to one award schema; and
- `GET /health` for the enabled sources, adapter versions, cache ceiling, and
  credential requirement only.

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
endpoints. Every request is restricted to Department of Defense assistance
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
operation, including server-validated ROR identity resolution and optional
detail enrichment, shares a 100-second budget below the browser's 120-second
deadline. The ROR identity cache and guard, source cache and guard, and detail
cache operations are each capped at two seconds within that shared budget; the
ROR request itself receives only the remaining budget. Cache failures remain
non-fatal. Reaching the upstream ceiling is reported as a safety-bound
diagnostic, but it does not advertise a client next page unless a normalized
lookahead record was actually collected.

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

## Cache and credentials

Successful per-source responses use the Cloudflare Cache API for one hour.
Failures are never cached, and a cache failure falls through to the official
source without coupling NSF, NIH, DOE, and DoD availability. All four public
sources are account-free; this Worker has no source API-key binding.

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
exact bounded smoke for each of NSF, NIH, DOE, and DoD, and then verifies that
GitHub Pages serves the same committed Funded Awards page. If a prior Worker exists, a failed
health, source, or Pages check automatically restores that version. The live
smoke set contains one exact, bounded query per source; pull-request CI uses
deterministic fixtures and does not call PAMS or USAspending.
