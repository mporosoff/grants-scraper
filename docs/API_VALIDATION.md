# Grants.gov live API validation

**Date:** July 25, 2026

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

## Remaining validation work

- Exercise a broader agency and opportunity sample.
- Save curated, anonymized API fixtures for repeatable regression testing.
- Verify amended and revised NOFO selection across more complex attachment
  histories.
- Parse API date strings into timezone-aware database values.
- Validate limited-submission and cost-share flags against source documents.
