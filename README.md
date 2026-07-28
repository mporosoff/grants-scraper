# Funding Finder

A public funding-opportunity search engine with optional AI refinement.

Open the application:

https://mporosoff.github.io/grants-scraper/

## What it does

Anyone can search the comprehensive catalog without an account or API key. The browser provides:

- full-text search across current Grants.gov opportunities;
- one-click browsing of the complete current catalog without search terms;
- filters for status, discipline, topic, agency, eligibility, instrument,
  deadline, award size, cited-FOA availability, and special requirements;
- relevance and field-based sorting;
- one-click official FOA, agency-notice, or Grants.gov record actions;
- expandable page/section-cited FOA evidence, pagination, and CSV export; and
- visible catalog source, size, generated time, and freshness;
- public RSS/Atom feeds for the full catalog and individual topics/source
  types; and
- automatic dark-mode and Windows high-contrast support.

The page initially shows no opportunities. One guided workflow combines a
topic, optional profile/CV context, and optional filters under a single “Find
funding” action. Users can explicitly save a reusable researcher profile on
that device; saving it does not launch a competing search. Profile relevance
uses the local BM25 index and makes zero AI calls.

Ordinary and profile-ranked search make zero AI calls. A user may enter an
OpenAI or Anthropic key to:

1. expand the search with useful synonyms;
2. rerank at most 32 retrieved candidates into a shortlist of at most 12; and
3. ask grounded follow-up questions that can further narrow the shortlist.

“Ask about these results” appears with the returned result set and can answer
questions over the top 20 ordinary search results without requiring a prior AI
rerank. It uses the same responsive result workflow on desktop and mobile.

When the scheduled Phase 3 pipeline has analyzed an official notice, the
result card shows document version/change status and compact cited facts for
submission stages, funding, duration, page limits, cost share,
eligibility/review excerpts, and application components. Each fact opens the
exact PDF page or HTML section. “Ask AI about this FOA” focuses chat on a
single result; AI may cite only evidence identifiers that the browser supplied.

The original CV file is never retained. A bounded CV excerpt is sent only when
the user enables that option and explicitly runs AI refinement or chat. An API
key is tab-only unless the user explicitly saves it on that device. Saved keys
are isolated from profiles and reviewer data, have a visible saved/loaded
status and removal control, and never enter GitHub, URLs, exports, or an
application database. The shortlist and chat remain page-memory only.

Match-quality controls include `not relevant`, `partial`, `useful`, `strong`,
and `needs verification` labels with reason codes. After three graded ratings,
an optional local preference model can prioritize future Relevance sorting.
The explicit evaluation export includes current search text, filters, ranks,
and ratings while omitting API keys, saved profile text, CV text, and chat.
`scripts/evaluate_phase2.py` measures retrieval recall separately from AI
reranking precision. Reviewers can switch from the 12-result shortlist to the
pre-reranking candidate set when labeling. The 3–5 researcher pilot is
deliberately deferred until the Phase 3 deployment batch and review handoff are
verified.

Ratings appear directly on result cards. Invited testers can open the collapsed
“Help improve Funding Finder” area to
mark cited evidence accurate, incorrect, or unverifiable, check
the field they inspected, and add a short non-confidential note. This progress
autosaves only on that device. “Send review” uses the native file share sheet
where available; otherwise it downloads a privacy-safe JSON file and opens an
addressed email to the project owner. Returned files can be aggregated into
private Markdown, JSON, and CSV reports.

## Data model

The daily workflow processes the official [Grants.gov XML database extract](https://www.grants.gov/xml-extract), then merges enabled, independently validated
public-source adapters. NSF upcoming due dates, NYSERDA, ARPA-E eXCHANGE, and
DOE EERE Exchange are enabled. NASA NSPIRES and UR InfoReady remain disabled
shells until stable public or permissioned routes exist. It publishes open
posted and current forecasted records plus a compact BM25 search index to
`data/opportunities.js`. Past deadlines are rejected for every source, and
stale undated forecasts are excluded.

An incremental second step enriches only new or changed records through the
official Grants.gov `fetchOpportunity` detail API. It reconciles structured
deadline and award evidence, preserves supplied deadline time/timezone, and
selects a direct announcement only when the attachment evidence is defensible.
When Grants.gov drops spacing from an NSF synopsis, the same step replaces
only that damaged prose with the synopsis from the linked official NSF funding
page and rebuilds the search index. Successful NSF text is cached for 14 days;
an unparseable agency page leaves the Grants.gov text unchanged.
Its compact cache is `data/opportunity_enrichment.json`.

A bounded third step retrieves selected official PDF or HTML notices. It uses
document hashes and HTTP validators to detect changes and avoid unnecessary
downloads, extracts readable text ephemerally, and publishes only short cited
facts and a human-review queue. Raw notices and full extracted text are never
committed. Machine-extracted dates and amounts do not replace structured
Grants.gov fields used by filters or sorting. Its compact cache is
`data/document_evidence.json`.

External-source records use atomic per-source replacement and the committed
`data/source_records.json` last-known-good cache. A degraded enabled source
cannot erase healthy published records: the safe merge completes, exits
nonzero for monitoring, and the scheduled workflow opens or updates an
owner-facing GitHub issue. NYSERDA publishes the next open application round
and retains later application and concept-paper dates as structured deadlines.
DOE Exchange adapters publish only actual NOFOs, not RFIs, teaming notices, or
notices of intent, and retain later submission rounds as structured deadlines.
The source cache also preserves a first-seen date so undated external records
can participate reliably in feeds and consent-based alerts.

After the final validated merge, `scripts/build_feeds.py` regenerates static
Atom feeds under `feeds/`. They require no account, backend, or personal data.
For a small manually managed pilot, `docs/weekly-alerts/` contains a
private-repository email-digest bundle. The public site does not collect email
addresses; the bundle requires explicit consent and keeps subscriptions,
watermarks, and SMTP secrets outside this public repository.

<!-- catalog-stats:start -->
This replaces the former 48-record Chemical and Sustainability Engineering feed. The
July 28, 2026 build contains 1,493 current funding opportunities (1,247 posted and 246
forecasted) from Grants.gov (1,456), NYSERDA (37), with no deadline before the catalog
date. It provides a direct official announcement for 447 records, an official source-
page route for another 637, and the official Grants.gov record for the remaining 409.
Across all route types, 789 records also contain an official source URL.
<!-- catalog-stats:end -->

Funding values are intentionally not conflated: award floor/ceiling drive
per-award display and filtering, while total program funding is a separate
fact. Missing evidence remains “not listed” until an official source can
support it.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Redirects GitHub Pages to the application |
| `match_explorer.html` | Public search and AI-refinement interface |
| `assets/app.js` | Search, cited source evidence, review/export, profile ranking, AI matching, and chat |
| `assets/profile.js` | Local profile/feedback storage and CV extraction |
| `assets/review.js` | Local Phase 3 deployment-review storage and privacy-safe handoff |
| `assets/credentials.js` | Explicit device-local provider-key save/load/clear boundary |
| `assets/ai-provider.js` | OpenAI and Anthropic request adapters |
| `assets/app.css` | Responsive application styles |
| `assets/vendor/` | Vendored PDF.js and Mammoth parsers and license notices |
| `data/opportunities.js` | Generated catalog and search index |
| `data/opportunity_enrichment.json` | Incremental official-detail cache |
| `data/document_evidence.json` | Incremental document hash/version, cited-fact, and review-queue cache |
| `data/source_records.json` | Last-known-good snapshots for enabled external sources |
| `scripts/build_catalog.py` | Official XML ingestion and catalog builder |
| `scripts/enrich_catalog.py` | Official detail reconciliation and FOA selection |
| `scripts/extract_document_evidence.py` | Official PDF/HTML retrieval, versioning, deterministic fact extraction, and citations |
| `scripts/program_areas.py` | Evidence-backed controlled vocabulary for discoverability in official notices |
| `scripts/sources/` | Validated multi-source adapters, lifecycle, health gates, and merge |
| `scripts/build_feeds.py` | Static all/topic/source-type Atom feed generator |
| `scripts/alert_match.py` | Server-side saved-search matcher shared by the optional digest bundle |
| `feeds/` | Generated public Atom feeds and feed directory |
| `docs/weekly-alerts/` | Private-repository pilot bundle for consent-based weekly email digests |
| `scripts/evaluate_phase2.py` | Phase 2 retrieval/reranking evaluator |
| `scripts/summarize_phase3_reviews.py` | Private Phase 3 deployment-review aggregator |
| `evaluation/README.md` | Pilot export, privacy, and aggregation workflow |
| `evaluation/PHASE3_REVIEW.md` | Deployment-review storage, return, and reporting procedure |
| `PROJECT.md` | Product decisions, architecture, and roadmap |
| `tests/` | Pipeline and public-page regression checks |
| `docs/HOSTING.md` | Deployment and privacy boundary |

## Development

Install the small Python dependency set and run the regression suite:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Build from an existing official extract:

```powershell
python -m scripts.build_catalog --archive GrantsDBExtractYYYYMMDDv2.zip
```

Or discover and download the latest official extract:

```powershell
python -m scripts.build_catalog
```

Then enrich new or changed records:

```powershell
python -m scripts.enrich_catalog --catalog data/opportunities.js --cache data/opportunity_enrichment.json --max-updates 250
```

Then process a bounded set of new, changed, or due official notices:

```powershell
python -m scripts.extract_document_evidence --catalog data/opportunities.js --cache data/document_evidence.json --max-documents 45
```

To summarize review files returned to the project owner:

```powershell
python -m scripts.summarize_phase3_reviews evaluation/inbox --output-dir evaluation/reports
```

The scheduled workflow runs the Grants.gov, enrichment, document-evidence, and
external-source steps daily; validates source-specific and whole-catalog
health; regenerates the public feeds; retests the generated assets; alerts the
owner about degradation; and commits the normalized browser catalog, feeds,
and compact caches. Raw XML archives, raw notices, full extracted notice text,
subscriber data, SMTP credentials, and returned review files are not committed.

See `PROJECT.md` for the completed Phase 1/1.5 scope, deferred Phase 2 pilot,
and Phase 3 implementation,
and `docs/HOSTING.md` for the deployment boundary.
