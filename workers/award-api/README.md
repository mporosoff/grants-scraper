# Funding Finder award API

This Worker is the historical-award data boundary established in Phase 1 and
extended through the isolated DOE adapter in Phase 4. It exposes:

- `POST /awards/search` for bounded NSF, NIH RePORTER, and DOE Office of
  Science PAMS searches normalized to one award schema; and
- `GET /health` for the enabled sources, adapter versions, cache ceiling, and
  credential requirement only.

The Worker follows the existing Funding Finder service pattern: strict request
bounds, dependency-injected source calls, deterministic fixtures, explicit
provenance, local-development and production-origin CORS, and a small public
health response. It does not import or modify the Funding Finder ranking code.

## Request contract

```json
{
  "sources": ["NSF", "NIH", "DOE"],
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

Criteria may use `award_id` (NSF or DOE), `core_project_number` (NIH),
`opportunity_number` (NIH FOA or exact DOE Office of Science FOA), `program`, `topic`, `institution_id` or
`institution`, `pi`, `program_officer`, and a bounded year range. NSF program
codes are six-character program element codes. A reviewed NSF parent mapping
may use `program_codes` with at most 24 exact program element codes. NIH program
identifiers are activity codes such as `R01`. DOE program searches use the
PAMS public Program Area field. Requests containing DOE are limited to ten
results and a documented bounded browse window.

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
email fields, so DOE contact emails remain null. No name-to-email inference or
page reveal automation is performed.

## Cache and credentials

Successful per-source responses use the Cloudflare Cache API for one hour.
Failures are never cached, and a cache failure falls through to the official
source without coupling NSF, NIH, and DOE availability. All three public
sources are account-free; this Worker has no API-key or secret binding.

The DOE adapter uses the account-free PAMS public WebForms search documented in
`docs/DOE_PAMS_PUBLIC_AWARD_RECONNAISSANCE.md`. It obtains fresh view-state per
search, forces all-status/all-country coverage, retains source-native order,
and fetches at most ten direct public abstracts with concurrency two. A PAMS
markup or availability failure is contained to DOE.

Phase 2 links this boundary from the Funded Awards product. Current NIH
opportunities use exact FOA numbers. Eligible NSF opportunities use an exact
program element code or a committed, reviewed parent-program code set; the
browser does not silently substitute a fuzzy title match. DOE Office of Science
opportunities use exact `DE-FOA-<number>` solicitation searches only.

## Deployment

The protected-main `Deploy Funded Awards service` workflow validates the award
contracts, deploys this Worker, waits for its public health contract, runs one
exact bounded smoke for each of NSF, NIH, and DOE, and then verifies that GitHub Pages serves
the same committed Funded Awards page. If a prior Worker exists, a failed
health, source, or Pages check automatically restores that version. The live
smoke set contains one exact, bounded query per source; pull-request CI uses
deterministic fixtures and does not call PAMS.
