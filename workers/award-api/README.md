# Funding Finder award API

This Worker is the Phase 1 historical-award data boundary. It exposes:

- `POST /awards/search` for bounded NSF and NIH RePORTER searches normalized to
  one award schema; and
- `GET /health` for the enabled sources, adapter versions, cache ceiling, and
  credential requirement only.

The Worker follows the existing Funding Finder service pattern: strict request
bounds, dependency-injected source calls, deterministic fixtures, explicit
provenance, local-development and production-origin CORS, and a small public
health response. It does not import or modify the Funding Finder ranking code.

## Request contract

```json
{
  "sources": ["NSF", "NIH"],
  "criteria": {
    "topic": "warm dense matter",
    "institution_id": "university-of-rochester",
    "year_start": 2020,
    "year_end": 2026
  },
  "limit": 25,
  "offset": 0
}
```

Criteria may use `award_id` (NSF), `core_project_number` (NIH),
`opportunity_number` (NIH), `program`, `topic`, `institution_id` or
`institution`, `pi`, `program_officer`, and a bounded year range. NSF program
codes are six-digit program element codes. NIH program identifiers are activity
codes such as `R01`.

The response returns a flat normalized `results` list and a per-source status.
One source failure never discards successful results from the other source.
NIH annual applications are grouped by `core_project_num`; their original
application IDs, project numbers, fiscal years, amounts, and official links are
retained in `annual_support`.

## Contact policy

Email is copied only from an explicit source response field. Missing email stays
`null`, while `official_contact_url` points to the official NSF Award Search or
NIH RePORTER record. No name-to-email inference or page reveal automation is
performed.

## Cache and credentials

Successful per-source responses use the Cloudflare Cache API for one hour.
Failures are never cached, and a cache failure falls through to the official
source without coupling NSF and NIH availability. Both APIs are public; this
Worker has no API-key or secret binding.

The Phase 1 Worker is committed but is not linked from the public product. The
Funded Awards page and its deployment integration belong to Phase 2.
