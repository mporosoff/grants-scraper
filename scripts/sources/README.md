# `scripts/sources` — modular multi-source ingestion layer

Add funding sources beyond Grants.gov (NYSERDA, foundations, internal portals, RSS
feeds, …) through the canonical merge step that refreshes external records in the
generated catalog.

## Why it's safe to drop in

- **Shared enrichment.** Collection and canonical merge run after the Grants.gov
  structured API step and before common official HTML/PDF extraction. Every
  canonical source can receive evidence and eligible child topics. The common
  writer rebuilds enriched text, indexes and facets before faculty/team projections.
- **Safe enablement.** New adapters default to `enabled = False` until they are
  implemented and verified. Production adapters are enabled one at a time.
- **Grants.gov always wins.** External records never override a Grants.gov
  record, and duplicates are dropped.
- **One broken source can't break the build.** Adapter errors are isolated and
  reported. Most sources can republish a filtered last-healthy snapshot;
  sources that cannot prove their rows are current can opt out and publish
  zero. Expired cached records are always removed.
- **Degradation is visible.** The scheduled job publishes each source's safe
  lifecycle result and opens or updates an owner-facing GitHub issue when an
  enabled source fails, becomes unhealthy, or fails post-merge validation.
- **Fail closed.** Records need an official URL and plausible dates, source
  counts must remain within health bounds, and the full merged catalog is
  validated before either generated file is written.
- **Same schema, same index.** External records are expanded to the exact record
  shape `build_catalog.py` produces and are indexed/faceted by Grants.gov's own
  functions, so the browser can't tell the difference.

## Files

| File | Purpose |
|---|---|
| `base.py` | `CanonicalOpportunity` model + `SourceAdapter` base class. Expands the few fields you have into a full catalog record. |
| `registry.py` | Adapter registration + `collect()` with per-adapter error isolation. |
| `merge.py` | Applies atomic per-source refresh/fallback, merges/dedups, rebuilds index/facets/counts, validates, and writes the catalog plus snapshot cache. `integrate()` is the entry point. |
| `discoverability.py` | Evidence registry for opaque umbrella calls. Matches scoped identifiers/signals, records official source URLs, and makes injected terms reversible. |
| `validate.py` | Currentness, official-link, date-plausibility, and source health gates. |
| `http.py` | Polite HTTP client (UA, timeouts, size cap, pacing) for network adapters. |
| `intake.py` | Bounded developer preview/acceptance and maintained-input adapter; uses native parsers or cited explicit facts. |
| `adapters/` | Bundled adapters. `_template.py` to copy; `rss.py`; `sample.py` (offline demo); verified `nyserda.py`; and the disabled `ur_infoready.py` shell. |
| `fixtures/` | Demo data for the sample adapter and tests. |
| `__main__.py` | CLI: `list`, `dry-run`, `intake`, `merge`. |

## Try it now (no changes to your catalog)

```powershell
python -m scripts.sources list                                   # see adapters + on/off
python -m scripts.sources dry-run --adapter sample --include-disabled   # preview demo output
python -m scripts.sources merge --adapter sample --include-disabled     # preview merge (no write)
```

`merge` without `--write` only previews. Add `--write` to actually update
`data/opportunities.js`.

## Add a new source (3 steps)

1. Copy `adapters/_template.py` to `adapters/<yoursource>.py`; fill in `slug`,
   `display_name`, `source_type`, and the `fetch` + `parse` methods. You only
   set the fields you have — topics, LOI/limited/early-career signals, and
   deadlines are derived for you.
2. Add `from . import <yoursource>` to `adapters/__init__.py`.
3. Verify, then flip `enabled = True`:
   ```powershell
   python -m scripts.sources dry-run --adapter <slug> --include-disabled
   ```

## Daily refresh integration

The workflow runs this step after Grants.gov structured-detail reconciliation
and before shared document-evidence extraction:

```yaml
      - name: Merge additional (non-Grants.gov) sources
        run: >-
          python -m scripts.sources merge
          --catalog data/opportunities.js
          --cache data/source_records.json
          --write
          --fail-on-degraded
```

That's it. Locally, the equivalent one-liner is:

```powershell
python -m scripts.sources merge --catalog data/opportunities.js --cache data/source_records.json --write
```

Because the merge step reuses `build_catalog`'s index/facet/writer functions and
preserves every top-level catalog field, the existing "Run regression tests
against generated asset" step still validates the result.

The coordinated order is collection/normalization, Grants.gov structured details,
canonical merge (including each adapter's structured reconciliation), shared
document extraction and eligible topics, faculty matching, team invalidation and
assessment, feeds/change events/link health/documentation, vectors and release
packaging. `merge` alone creates an intermediate searchable catalog; run the
shared extraction before building downstream projections. No consumer-specific
opportunity IDs or direct edits to generated assets are needed.

## Developer-only intake

Preview a current notice selected from a supported native official listing:

```powershell
python -m scripts.sources intake --adapter arpa-e --url "OFFICIAL_NOTICE_URL"
python -m scripts.sources intake --adapter arpa-e --url "OFFICIAL_NOTICE_URL" --accept
```

Supported URL parsers are `arpa-e`, `eere-exchange`, and `nsf-funding`. The URL must
exactly identify one record in that parser's official listing. The parser retains
its native ID and structured dates, including submission time/timezone. Acceptance
records the selector in `config/source_intake.json`; normal coordinated refresh
consumes it through the maintained adapter and the existing native adapter. The
developer merge summary reports its canonical IDs (including a Grants.gov winner),
unavailability or absence from the current listing. A selector cannot resurrect a
withdrawn notice or enable a disabled adapter.

For unsupported markup, supply a small source-cited JSON manifest:

```powershell
python -m scripts.sources intake --manifest path/to/notice.json
python -m scripts.sources intake --manifest path/to/notice.json --accept
python -m scripts.sources merge --write
```

The default is dry run: it validates and prints normalized records without writes.
`--accept` atomically updates maintained canonical inputs, never catalog or team
assets. Review that input diff as code. `--inputs PATH` selects an isolated input
file for developer tests; pass the same path to `merge`. Production refresh uses
the default maintained file. Synthetic fixtures belong only under `tests/` and
temporary directories, never in accepted production inputs.

A manifest has exactly `schema_version: 1` and `entries` (1–20 records, at most
256 KiB). Every entry has exactly these keys:

| Key | Contract |
| --- | --- |
| `kind` | `record` |
| `source_name`, `source_type` | Supplemental official publisher; type is Federal, State, Foundation, International, Internal or Other. Grants.gov cannot be impersonated. |
| `verified_on`, `review_after` | ISO dates, no future verification, review within 30 days. Expired verification withholds a record without asserting withdrawal. |
| `opportunity` | Existing `CanonicalOpportunity` schema, without `extra` or `contacts`. Explicitly include `external_id`, `title`, `opportunity_number`, `url`, `agency`, `description`, `status`, `close_date`, `posted_date`, `award_floor`, `award_ceiling`, `total_program_funding`, `eligibility_text`. Use JSON `null` for unknown facts. |
| `citations` | Map each supplied factual field to exactly `{ "url": ..., "quote": ... }`; quote is 15–600 characters, present in the official notice. Stable external ID and document URL/name are identity metadata. |

Status is explicitly `posted` or `forecasted`; dates are ISO or null; numeric
amounts are finite, nonnegative and ordered. Optional `additional_deadlines` name
`kind`, `date`, `time`, `timezone` explicitly, with null unknown time/zone. Quotes
must come from `url` or an explicitly supplied `primary_document_url`; acceptance
fetches those public documents and verifies the quotes. It does not infer missing
facts or assert that a quoted passage supports a developer's interpretation.
The developer remains responsible for source-to-field accuracy. See
`tests/fixtures/phase2_pipeline.py` for an executable synthetic schema example.

Maintained record IDs bind the official host and external ID. Existing canonical
merge rules preserve Grants.gov precedence and distinct numbered calls. A failed
source retains only the fallback its adapter permits; expired records are always
filtered. Supported HTML/PDF retrieval validates every redirect and public network
address, rejects credentials, loopback/private targets and licensed source hosts,
and bounds time and size. Anonymous retrieval does not inherit environment
credentials or bypass access controls. Exchange page extraction is restricted to
the exact notice fragment. Unsupported structure fails clearly.

Shared evidence uses content hashes for material amendments. HTTP validators and
freshness timestamps do not create amendments. Failed retrieval retains the last
successful check internally, withholds stale public quotes and child topics, and
invalidates dependent team scopes. Structured dates, amounts and eligibility retain
authority; document conflicts stay disclosed. Inferred topics still require the
existing publication gate, and broad parents do not automatically receive teams.

Phase 2 contracts: `python -m unittest tests.test_pipeline_phase2 -q` and
`node --test tests/browser/pipeline-phase2-contract.test.mjs`. The latter uses a
JavaScript VM, not a browser. Both run actual pipeline commands in temporary
directories; no live subscribers, provider calls or researcher mutations occur.

### Opaque umbrella calls

Some master FOAs and BAAs omit their program scope from the catalog synopsis.
`discoverability.py` restores that scope before indexing, but does not grant a
search-time exception to every broad call. Each registry rule must use a stable
announcement number or tightly scoped agency/title signals and should cite the
official program pages that support every added topic family. Acronym signals
use whole-token matching. Registry-owned additions are recorded separately so
a corrected or retired rule can remove its prior search terms and topic tags.

## Bundled adapters status

| Adapter | Status | Note |
|---|---|---|
| `sample` | Works (offline) | Demo/tests only; stays disabled. |
| `pnd-rfp` (Philanthropy News Digest / Candid) | Ready to configure | Confirm the live RSS URL and add a topic/eligibility filter (it's nonprofit-skewed) before enabling. |
| `nsf-funding` | Enabled | Official NSF upcoming-due-dates feed; tolerant of the feed's malformed bare ampersands and protected by source health bounds. |
| `darpa-iarpa` | Enabled | One adapter for individual DARPA Disruption/QBI topics and IARPA open research solicitations. Requires exact official solicitation links, open status and current submission dates; excludes umbrella PAs, drafts, RFIs and events. Deduplicates by normalized sponsor and solicitation number. A verified IARPA empty table is healthy; either source failing clears this adapter's snapshot. |
| `nih-guide` | Disabled intentionally | NIH stopped publishing NOFOs in the Guide in FY2026; its feed now carries policy/informational notices while Grants.gov is the official NIH NOFO source. |
| `nyserda` | Enabled | Verified live JSON API; publishes the next open application round and retains later application/concept-paper dates as structured deadlines. |
| `arpa-e` | Enabled | Server-rendered ARPA-E eXCHANGE NOFO list; excludes RFIs/teaming/intent notices and retains later open submission dates. |
| `eere-exchange` | Enabled | Server-rendered DOE EERE Exchange NOFO list using the same verified parser and source-health gates. |
| `nasa-nspires` | Disabled shell | The public entry point is session/POST-gated; no stable list route is confirmed. |
| `ur-infoready` | Disabled shell | The earlier undocumented endpoint currently returns HTTP 500. No embedded credential or unstable request ships; the fixture parser remains for a future permissioned route. |
| `vpr-email` | Enabled | Reads the private forwarding mailbox over read-only IMAP. VPR and Cindy messages are classified and counted separately; both streams are required, and a format regression preserves the last good snapshot. |
| `jhu-fellowships` | Disabled - upstream unavailable | The parser and complete-set validation remain available for bounded diagnostics, but automated publication is disabled. JHU's category pages, WordPress API, direct media URLs, and JHU-published short links require an interactive Cloudflare challenge from unattended refresh clients. Because all three workbooks are mandatory and no stale snapshot can be proven current, production publishes zero JHU records and does not represent this source as healthy. Re-enable only after an official unattended retrieval path is live-verified. |

## Notes

- **Data quality:** foundation/state pages rarely expose structured award floors
  or eligibility codes, so those records populate fewer facets and rely on prose.
  The model keeps award floor/ceiling separate from total program funding and
  flags missing dates as `status_verification_required`, matching the project's
  rules.
- **Provenance:** every external record carries its own `source` and
  `source_type`, and a per-source count is written to
  `diagnostics.additional_sources` in the catalog.
- **Legal hygiene:** only add public, non-licensed sources; respect `robots.txt`
  and rate limits (the HTTP client paces requests). Do not scrape SPIN/InfoEd,
  Pivot, Duke, GrantForward, or other licensed databases.

### JHU RDT workbook outage compatibility

JHU's graduate, postdoctoral, and early-career category pages currently expose
an under-construction notice instead of workbook links. The adapter may use the
official 7/1/26 JHU workbook URLs (or JHU's public short links to those files)
for at most 62 days from their published date. These files are reported as a
bounded source snapshot, never as a fresh live refresh. A newer workbook found
on a category page takes precedence. Once the snapshot exceeds the bound, the
source fails closed and the source-health summary reports
`pinned_workbook_expired`; it does not republish rolling rows indefinitely.

As of the 2026-08-27 scheduled-equivalent recovery audit, those pages and every
official workbook route also returned `cf-mitigated=challenge` to unattended
clients. The bounded compatibility path therefore cannot retrieve a complete
set. The adapter is disabled, its parser remains regression-tested, and the
catalog publishes zero JHU records. This is a documented upstream limitation,
not a successful refresh or a retained-data fallback.
