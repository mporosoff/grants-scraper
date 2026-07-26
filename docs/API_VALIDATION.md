# Grants.gov live API validation

**Date:** July 26, 2026

> **Current role:** The complete daily XML extract remains the catalog
> ingestion mechanism. Phase 1.5 now uses `fetchOpportunity` only as an
> incremental source-evidence layer for new or changed records; it is not the
> browser catalog's retrieval mechanism.

The ingestion prototype was exercised against the public `search2` and
`fetchOpportunity` endpoints without an API key.

## Records checked

| Opportunity ID | Type | Agency | Purpose |
|---|---|---|---|
| `347749` | posted synopsis | NSF | synopsis fields and external program link |
| `344592` | posted synopsis | Army | multiple attachment folders and amendments |
| `362681` | posted synopsis | Air Force | rolling opportunity and attachment selection |
| `355824` | forecast | HHS | forecast-only description, deadline, and award fields |

## Findings incorporated into the code

- Posted deadline notes use `responseDateDesc`, not only
  `responseDateNote`.
- Forecasts use `forecastDesc`, `estSynopsisPostingDate`,
  `estApplicationResponseDate`, `estApplicationResponseDateDesc`,
  `estAwardDate`, and `estProjectStartDate`.
- Agency names are more reliable under `agencyDetails` than the flat
  `agencyName` value for some records.
- ALN data may appear under `alns` or the older `cfdas` collection.
- Attachment download URLs using
  `https://grants.gov/grantsws/rest/opportunity/att/download/{id}` work and
  redirect to the current download host.
- Attachment ranking must penalize FAQs, appendices, samples, special notices,
  and topic lists so they are not mistaken for the primary announcement.
- Opportunities without an attached PDF may provide an agency announcement
  link through `fundingDescLinkUrl`.
- `Open until superseded` is a useful rolling-opportunity signal.
- The detail response can supply deadline notes, time/timezone, attachment
  history, agency announcement links, and award values that are absent or less
  precise in the daily XML extract.
- XML/detail disagreement must become a visible conflict flag rather than a
  silent overwrite.
- Explicit NOFO/FOA filenames can support a high-confidence direct action. A
  sole plausible full-announcement PDF is medium confidence; ambiguous
  attachment sets must fall back to the agency notice or Grants.gov record.
- The compact cache can be keyed by record status, version, update date, close
  date, and archive date so unchanged records require no API request.

## Remaining validation work

- Exercise a broader agency and opportunity sample.
- Expand curated API fixtures for complex amendment histories.
- Verify amended and revised NOFO selection across more complex attachment
  histories.
- Confirm daylight-saving and uncommon timezone labels across more agencies.
- Validate limited-submission and cost-share flags against source documents.
- Add document-level extraction only when every derived fact can retain an
  exact official source reference and confidence.
