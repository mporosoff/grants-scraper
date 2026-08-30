# Funding Finder award API

This Worker is the historical-award data boundary established in Phase 1 and
extended through the isolated DOE adapter in Phase 4. It exposes:

- `POST /awards/search` for bounded NSF, NIH RePORTER, and DOE Office of
  Science PAMS searches normalized to one award schema;
- `POST /awards/snapshots` plus `/page`, `/batch`, and `/retry` for immutable,
  server-authoritative result snapshots;
- `POST /awards/snapshots/evidence` for bounded deterministic retrieval over
  an unexpired Program Officer snapshot. Evidence requests declare
  `"phrase_format": "normalized-concepts-v1"`; phrases are browser-normalized
  substantive concepts and are not reinterpreted as raw questions; and
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

The evidence endpoint accepts only a snapshot ID, one to eight bounded phrases,
and a limit no greater than 24. It scores the complete stored snapshot without
changing membership, returns at most 800 abstract characters per record and
18,000 serialized evidence characters, and never stores the phrases. Title
matches outweigh abstract matches; program/office fields are supporting
signals, and investigator/institution fields are weak signals. The endpoint
uses the existing origin, body-size, expiration, and Durable Object abuse-control
contracts. It creates no corpus or database.

## Cache and credentials

Successful per-source responses and immutable snapshots use the Cloudflare
Cache API for one hour.
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
