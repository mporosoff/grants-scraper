# `scripts/sources` — modular multi-source ingestion layer

Add funding sources beyond Grants.gov (NYSERDA, foundations, UR InfoReady, RSS
feeds, …) through a final pipeline step that refreshes external records in the
generated catalog.

## Why it's safe to drop in

- **Nothing existing changes.** It runs *after* `build_catalog.py`,
  `enrich_catalog.py`, and `extract_document_evidence.py`, so those Grants.gov
  steps never see external records.
- **Safe enablement.** New adapters default to `enabled = False` until they are
  implemented and verified. Production adapters are enabled one at a time.
- **Grants.gov always wins.** External records never override a Grants.gov
  record, and duplicates are dropped.
- **One broken source can't break the build.** Adapter errors are isolated and
  reported; a committed per-source snapshot republishes the last healthy
  records. Expired cached records are still removed.
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
| `validate.py` | Currentness, official-link, date-plausibility, and source health gates. |
| `http.py` | Polite HTTP client (UA, timeouts, size cap, pacing) for network adapters. |
| `adapters/` | Bundled adapters. `_template.py` to copy; `rss.py` (works today); `sample.py` (offline demo); `nyserda.py` / `ur_infoready.py` (scaffolds). |
| `fixtures/` | Demo data for the sample adapter and tests. |
| `__main__.py` | CLI: `list`, `dry-run`, `merge`. |

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

The workflow runs this step after document-evidence extraction and before the
post-refresh regression suite:

```yaml
      - name: Merge additional (non-Grants.gov) sources
        run: >-
          python -m scripts.sources merge
          --catalog data/opportunities.js
          --cache data/source_records.json
          --write
```

That's it. Locally, the equivalent one-liner is:

```powershell
python -m scripts.sources merge --catalog data/opportunities.js --cache data/source_records.json --write
```

Because the merge step reuses `build_catalog`'s index/facet/writer functions and
preserves every top-level catalog field, the existing "Run regression tests
against generated asset" step still validates the result.

## Bundled adapters status

| Adapter | Status | Note |
|---|---|---|
| `sample` | Works (offline) | Demo/tests only; stays disabled. |
| `pnd-rfp` (Philanthropy News Digest / Candid) | Ready to configure | Confirm the live RSS URL and add a topic/eligibility filter (it's nonprofit-skewed) before enabling. |
| `nsf-funding` | Enabled | Official NSF upcoming-due-dates feed; tolerant of the feed's malformed bare ampersands and protected by source health bounds. |
| `nih-guide` | Disabled intentionally | NIH stopped publishing NOFOs in the Guide in FY2026; its feed now carries policy/informational notices while Grants.gov is the official NIH NOFO source. |
| `nyserda` | Scaffold | Implement `parse()` against the live funding page; low volume, low maintenance. |
| `ur-infoready` | Scaffold | Implement `parse()` against `rochester.infoready4.com`; covers internal + limited submissions. |

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
