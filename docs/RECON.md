# Reconnaissance — §0.1 of `docs/TOPIC_LAYER_PLAN.md`

**Session 1 (recon only).** Date: 2026-08-16. Branch: `topic-layer` (commit `b40d400`).
No existing file was modified. No script was run in write mode. Nothing was installed.

Everything below was read from the working tree in this session. Where the plan and the
repository disagree, the repository is reported and the disagreement is listed in
[Plan discrepancies](#plan-discrepancies).

Per the plan's naming rule (§ "Naming collision"), the new concept is called **`subtopic`**
throughout this document. The repository's existing `topic_areas` / `feeds/topic/` /
"Topic" facet meaning of "topic" is *subject area* and is untouched.

---

## Answers

### Q1. Which script writes each file in `data/`? Which are added by the workflow's `git add`, and which are build-local?

| Path | Written by | In `git add`? | Notes |
|---|---|---|---|
| `data/opportunities.js` | **Five** scripts, in sequence: `build_catalog.write_catalog` ([build_catalog.py:960‑987](../scripts/build_catalog.py#L960), called at [:1107](../scripts/build_catalog.py#L1107)); then rewritten in place by `enrich_catalog` ([:1088](../scripts/enrich_catalog.py#L1088)), `extract_document_evidence` ([:1914](../scripts/extract_document_evidence.py#L1914)), `sources.merge.integrate` ([merge.py:390‑394](../scripts/sources/merge.py#L390)), and `check_links` ([:315](../scripts/check_links.py#L315)) | ✅ yes | Every rewrite goes through the same `build_catalog.write_catalog`, which rebuilds nothing — it only serializes the dict it is handed. Only `sources.merge.rebuild_catalog` recomputes facets/index. |
| `data/opportunity_enrichment.json` | `enrich_catalog.write_cache` ([:141‑165](../scripts/enrich_catalog.py#L141)), default at [:60](../scripts/enrich_catalog.py#L60) | ✅ yes | |
| `data/document_evidence.json` | `extract_document_evidence.write_cache` ([:244‑265](../scripts/extract_document_evidence.py#L244)), default at [:46](../scripts/extract_document_evidence.py#L46) | ✅ yes | 11.8 MB, the largest cache. |
| `data/source_records.json` | `sources.merge.save_source_cache` ([merge.py:88‑99](../scripts/sources/merge.py#L88)), default at [:49](../scripts/sources/merge.py#L49) | ✅ yes | Last-known-good per adapter. |
| `data/faculty_matches.js` | `faculty_match.match_to_catalog` ([:813‑817](../scripts/faculty_match.py#L813)), default `--out` at [:829](../scripts/faculty_match.py#L829) | ✅ yes | Emits `globalThis.FACULTY_MATCHES=…`. |
| `data/link_health.json` | `check_links.main` ([:310‑313](../scripts/check_links.py#L310)), default at [:283](../scripts/check_links.py#L283) | ✅ yes | |

Files written **outside** `data/` that are nonetheless committed by the same step:
`feeds/changes.json` and `feeds/changes.xml` (`build_changes.write_change_feed`,
[:252‑258](../scripts/build_changes.py#L252)); `feeds/all.xml`, `feeds/topic/<slug>.xml`,
`feeds/source-type/<slug>.xml`, `feeds/index.json`, `feeds/index.html`
(`build_feeds.build_feeds`, [:185‑249](../scripts/build_feeds.py#L185)); and
`README.md`, `PROJECT.md`, `match_explorer.html`, `team_match.html`
(`update_catalog_docs.main`, [:347‑352](../scripts/update_catalog_docs.py#L347)).

The `git add` list is a single explicit line — [refresh-opportunities.yml:125](../.github/workflows/refresh-opportunities.yml#L125):

```
git add README.md PROJECT.md match_explorer.html team_match.html \
  data/opportunities.js data/opportunity_enrichment.json data/document_evidence.json \
  data/source_records.json data/faculty_matches.js data/link_health.json feeds
```

**Build-local / not committed by the workflow:**

- `$RUNNER_TEMP/opportunities.previous.js` — the pre-build catalog copy used for change
  detection ([workflow:48‑50](../.github/workflows/refresh-opportunities.yml#L48)). Pure build-local.
- `faculty_profiles.json` — at the **repo root**, not in `data/`. Written only by
  `python -m scripts.faculty_match profiles` ([:834‑835](../scripts/faculty_match.py#L834)),
  which the workflow never runs; the workflow only runs the `match` subcommand and
  *reads* this file ([workflow:94‑99](../.github/workflows/refresh-opportunities.yml#L94)).
  It is tracked in git but refreshed by hand.

**Critical for the subtopic work — `.gitignore` is a deny-by-default allowlist**
([.gitignore:12‑20](../.gitignore#L12)):

```
/data/*
!/data/opportunities.js
!/data/opportunity_enrichment.json
!/data/document_evidence.json
!/data/source_records.json
!/data/link_health.json
!/data/faculty_matches.js
```

A new `data/subtopic_records.json` is **ignored** unless a `!` line is added. Adding it to
the workflow's `git add` alone is not enough: `git add` on an ignored path exits non-zero,
and the commit step runs under `shell: bash` (GitHub's `-eo pipefail`), so the step — and
with it the entire publish — would abort. Both the `.gitignore` allowlist and the `git add`
line must change together.

---

### Q2. Exact step order in `.github/workflows/`, and which steps may fail?

`.github/workflows/refresh-opportunities.yml`, job `refresh`, [lines 39‑217](../.github/workflows/refresh-opportunities.yml#L39). One job, no matrix, `timeout-minutes: 45` ([:37](../.github/workflows/refresh-opportunities.yml#L37)).

| # | Line | Step | May fail? |
|---|---|---|---|
| 1 | 40 | `actions/checkout@v6` | no |
| 2 | 41 | `actions/setup-python@v6` (3.13, pip cache) | no |
| 3 | 45 | `actions/setup-node@v6` (22) | no |
| 4 | 48 | Copy `data/opportunities.js` → `$RUNNER_TEMP/opportunities.previous.js` | no |
| 5 | 51 | `pip install -r requirements.txt` | no |
| 6 | 52 | `python -m unittest discover -s tests -v` (**pre**-refresh) | no |
| 7 | 54 | `node --test tests/browser/*.test.mjs` | no |
| 8 | 56 | `scripts.build_catalog --output data/opportunities.js --min-records 1000 --max-record-count 5000` | no |
| 9 | 62 | `scripts.enrich_catalog --max-updates 250 --request-delay 0.25` | no |
| 10 | 69 | `scripts.extract_document_evidence --max-documents 45 --request-delay 0.2 --recheck-days 14` | **`continue-on-error: true`** ([:70](../.github/workflows/refresh-opportunities.yml#L70)) |
| 11 | 78 | `scripts.sources merge --write --fail-on-degraded` — `id: additional-sources` | **`continue-on-error: true`** ([:80](../.github/workflows/refresh-opportunities.yml#L80)) |
| 12 | 94 | `scripts.faculty_match match` | no |
| 13 | 100 | `scripts.build_changes --previous … --current … --out feeds` | no |
| 14 | 106 | `scripts.check_links --max-checks 150 --workers 8 --fail-threshold 0.35` | no |
| 15 | 114 | `scripts.build_feeds --catalog … --out feeds` | no |
| 16 | 116 | `scripts.update_catalog_docs` | no |
| 17 | 118 | `python -m unittest discover -s tests -v` (**post**-refresh) | no |
| 18 | 120 | Commit + rebase-retry push (5 attempts) | no |
| 19 | 146 | Owner issue: degraded source — `if: always() && steps.additional-sources.outcome == 'failure'` | — |
| 20 | 183 | Owner issue: job failed — `if: failure()` | — |

Only steps 10 and 11 carry `continue-on-error`. Everything else is fail-fast, and a failure
anywhere in steps 1‑17 stops the run **before** step 18, so nothing is published.

Triggers: `push` to `main` filtered to 14 specific paths ([:4‑21](../.github/workflows/refresh-opportunities.yml#L4)),
`schedule: cron "17 10 * * *"` ([:23](../.github/workflows/refresh-opportunities.yml#L23)), and
`workflow_dispatch`. `permissions: contents: write, issues: write` ([:26‑28](../.github/workflows/refresh-opportunities.yml#L26)).
`concurrency: grants-gov-opportunity-refresh`, `cancel-in-progress: false` ([:30‑32](../.github/workflows/refresh-opportunities.yml#L30)).

Note the path filter: adding `scripts/extract_subtopics.py` to the repo will **not** by
itself trigger a push-run; it must also be added to the `paths:` list if push-triggering is
wanted.

---

### Q3. Which nonzero exit paths trigger the owner-issue automation, and what distinguishes "a source degraded" from "the build is broken"?

**Two distinct issue titles, two distinct conditions.**

*"External funding source refresh degraded"* ([workflow:146‑182](../.github/workflows/refresh-opportunities.yml#L146))
fires on `always() && steps.additional-sources.outcome == 'failure'` — i.e. **only** when
step 11 (`scripts.sources merge`) exits non-zero. That is exactly one code path:
`cmd_merge` raises `SystemExit(2)` when `--fail-on-degraded` is set and
`summary_is_degraded()` is true ([sources/__main__.py:90‑98](../scripts/sources/__main__.py#L90)).
`summary_is_degraded` ([:30‑39](../scripts/sources/__main__.py#L30)) is true when post-merge
`validate_catalog` failed, or `--write` was requested but nothing was written, or any
enabled adapter's status is not `refreshed` / `recent_snapshot`.

Because the step is `continue-on-error`, this is a *warning* channel: the good data still
publishes. **This alert is firing today** — `jhu-fellowships` is at
`status: "failed_no_fallback"`, `healthy: false` in the committed catalog
(`data/opportunities.js` → `diagnostics.additional_sources.lifecycle`).

*"Automated Grants.gov refresh failed"* ([workflow:183‑217](../.github/workflows/refresh-opportunities.yml#L183))
fires on `failure()` — any non-`continue-on-error` step failing. The reachable sources are:

- either `unittest` run (steps 6, 17) — a red test blocks the publish;
- `node --test` (step 7);
- `build_catalog.validate_catalog` `RuntimeError` on record count below `--min-records`,
  above `--max-record-count`, duplicate identities, or >1% records missing title/agency
  ([build_catalog.py:1025‑1044](../scripts/build_catalog.py#L1025));
- any uncaught `requests` / parse exception in `build_catalog`, `enrich_catalog`,
  `faculty_match`, `build_changes`, `build_feeds`;
- `check_links.main` returning `2` when ≥20 links were checked and the broken fraction
  exceeds `--fail-threshold 0.35` ([check_links.py:325‑327](../scripts/check_links.py#L325));
- `update_catalog_docs.main` returning `1` — but only under `--check`, which the workflow
  does not pass ([update_catalog_docs.py:341‑345](../scripts/update_catalog_docs.py#L341)), so unreachable here;
- the commit step's explicit `exit 1` after five failed rebase/push attempts ([workflow:141‑144](../.github/workflows/refresh-opportunities.yml#L141)).

**The distinction, stated plainly:** "a source degraded" is *scoped to step 11's exit code
and nothing else*. It is not a general health signal. In particular there is a **third,
silent** category worth knowing before adding a step: `extract_document_evidence` has its
own health gate (`validate_refresh_health` raises when >80% of ≥5 attempted document
fetches fail, [:1667‑1680](../scripts/extract_document_evidence.py#L1667)), but it is
`continue-on-error` **and** has no `id:`, so its failure opens no issue at all. Note also
that this gate runs *after* both caches are written ([:1913‑1916](../scripts/extract_document_evidence.py#L1913)),
so a failed health check still persists that run's output.

A new subtopic step modelled on this one would inherit the same silence — which is what
plan §9.3 wants during Phase 2, but it means "the step is failing every night" is not
observable without reading run logs.

---

### Q4. Precise top-level shape of `data/opportunities.js`, and is there a schema version field?

The file is `/* comment */\n` + `globalThis.GRANT_CATALOG=` + minified JSON + `;\n`
([build_catalog.py:960‑987](../scripts/build_catalog.py#L960); global name at [:33](../scripts/build_catalog.py#L33)).
Serialization is `separators=(",",":")`, `ensure_ascii=False`, `default=str`, with `</`
escaped to `<\/`; written via a temp file and atomic `replace`. **Not** sorted, **not**
indented. Current size 24.8 MB, 1,475 records.

Top-level keys, as parsed from the committed file:

| Key | Type | Origin |
|---|---|---|
| `schema_version` | int — **`3`** | [build_catalog.py:34](../scripts/build_catalog.py#L34), emitted at [:938](../scripts/build_catalog.py#L938) |
| `source` | object (`name`, `url`, `extract_page`, `extract_file`, plus `api_enrichment`, `agency_funding_page_enrichment`, `document_evidence` added downstream) | [:939‑944](../scripts/build_catalog.py#L939) + enrich/evidence |
| `generated_at` | ISO-8601 Z string | [:945](../scripts/build_catalog.py#L945) |
| `record_count` | int | [:946](../scripts/build_catalog.py#L946) |
| `status_counts` | `{archived, forecasted, posted}` | [:947‑949](../scripts/build_catalog.py#L947) |
| `diagnostics` | `{deduplicated_count, quality, detail_enrichment, document_evidence, additional_sources}` | [:950‑953](../scripts/build_catalog.py#L950) + downstream |
| `facets` | 9 facets: `status, source_type, source, agency, discipline, topic, eligibility, funding_instrument, funding_category` | [:864‑892](../scripts/build_catalog.py#L864) |
| `opportunities` | array of 1,475 record objects | [:955](../scripts/build_catalog.py#L955) |
| `search_index` | `{algorithm:"bm25", document_count, average_document_length, document_lengths[], postings{}}` | [:851‑861](../scripts/build_catalog.py#L851) |
| `detail_enrichment_generated_at` | ISO string | `enrich_catalog` |
| `document_evidence_generated_at` | ISO string | `extract_document_evidence` |
| `link_health_generated_at` | ISO string | `check_links` |

**Yes, there is a schema version field, and the browser hard-asserts it.**
`app.js` `validateCatalog` ([assets/app.js:227‑245](../assets/app.js#L227)) throws unless
**all** of the following hold:

- `schema_version === 3` (exact equality, not `>=`);
- `opportunities.length === record_count`;
- `record_count >= 1000`;
- `search_index.document_count === record_count` and `search_index.postings` present.

This is the hardest constraint on plan §7.1. Subtopic child records appended to
`opportunities` **must** be counted in `record_count` and indexed into the same
`search_index`, or the application refuses to start. `postings` are `[docId, tf, docId, tf, …]`
positional into `opportunities`, and `document_lengths` is a positional array
([build_catalog.py:840‑841](../scripts/build_catalog.py#L840); consumed at
[search-retrieval.js:52‑56](../assets/search-retrieval.js#L52)), so any insertion position
other than "append" renumbers every document id.

**No record carries a `record_type` field today**, and none carries `parent_id`. Across all
1,475 records the key set is 82 distinct names; `record_type` is not among them. The
plan's `record_type === 'topic'` guards are therefore new-field guards, which is fine —
`undefined !== 'subtopic'` is a safe default — but nothing existing sets or reads it.
Record identity in the browser is `opportunity_id || opportunity_number`
([app.js:223‑225](../assets/app.js#L223)), so a subtopic record needs one of those two.

---

### Q5. Which functions in `extract_document_evidence.py` are imported by other modules?

**None. Zero production modules import from it.** Verified by grepping every `import` /
`from` line under `scripts/` and every reference to the module name repo-wide.

The dependency arrow points the other way — it imports *from* others
([extract_document_evidence.py:34‑41](../scripts/extract_document_evidence.py#L34)):
`from scripts.build_catalog import (…, write_catalog)`, `from scripts.enrich_catalog import read_catalog`,
`from scripts import program_areas`.

The only importers anywhere are two test modules:

- `tests/test_document_evidence.py:7‑18` — `build_document_entry`, `empty_cache`,
  `enrich_document_evidence`, `extract_containers`, `extract_document_facts`,
  `merge_document_entry`, `source_for_record`, `source_signature`, `validate_refresh_health`
- `tests/test_program_areas.py:10‑14` — `extract_program_areas`, `merge_document_entry`

`tests/test_pages_entrypoint.py:558` asserts the workflow contains the literal string
`python -m scripts.extract_document_evidence`.

**Consequence for plan §6.1/§8.3.** The backward-compatible alias block the plan prescribes
protects against a risk that does not exist: no downstream importer can break. The eleven
test-visible names above are the real contract, and per plan §8.1 ("no existing test is
modified") they must keep working. Note the plan names five symbols to move
(`FetchedDocument`, `Unchanged`, `fetch_document`, `_sha256_bytes`, `_extract_page_texts`) —
**none of these exist**; see discrepancies.

---

### Q6. Total workflow runtime today, and what is the job timeout?

**Job timeout: `timeout-minutes: 45`** ([refresh-opportunities.yml:37](../.github/workflows/refresh-opportunities.yml#L37)).
There is no per-step timeout anywhere.

**Total runtime is not recorded in the repository.** It exists only in the GitHub Actions
run history, which this session cannot reach. The best in-repo proxy is the interval from
`catalog.generated_at` (stamped by `build_catalog.main` before the extract download,
[build_catalog.py:1089](../scripts/build_catalog.py#L1089)) to the bot commit timestamp,
which covers steps 8‑18 inclusive:

| Commit | `generated_at` | Commit time | Δ |
|---|---|---|---|
| `7b5ed68` | 20:28:20Z | 20:29:56Z | 96 s |
| `2b42faf` | 19:23:17Z | 19:25:06Z | 109 s |
| `6d4a1cc` | 10:39:01Z | 10:41:11Z | 130 s |
| `d208663` | 11:56:40Z | 11:58:41Z | 121 s |
| `4d5a2ed` | 02:39:12Z | 02:41:08Z | 116 s |

So the **data half of the pipeline is ~2 minutes**, and the unmeasured remainder is
checkout, Python/Node setup, `pip install`, and two full test runs. That is comfortably
inside 45 minutes, but it also means the plan's "runtime delta under 20%" gate (§9.4) is
about 20 s of headroom on the measurable portion — a 400-page PDF parse could blow through
it on a single document. See Blocked, item B1.

---

### Q7. Does the Pages deploy job depend on the build job succeeding?

**There is no Pages deploy job.** `.github/workflows/` contains exactly two files
(`refresh-opportunities.yml`, `tests.yml`) and neither references
`actions/deploy-pages`, `actions/upload-pages-artifact`, `environment: github-pages`, or
`pages: write`. The site is served by **branch-based (classic) GitHub Pages** from the
default branch: `docs/HOSTING.md:196‑197` — "Commit a changed catalog, public feeds, and
compact caches to the default branch for GitHub Pages" — and `:208` — "confirm the
generated commit triggers GitHub Pages."

The functional answer to the plan's underlying concern is therefore **yes, but by a
different mechanism**: publication is a side effect of the `git push` inside step 18, and
every non-`continue-on-error` step precedes it. A new failing step inserted anywhere before
step 18 blocks publication of otherwise-good data. A new step inserted *after* step 18 does
not. This makes the plan's `continue-on-error: true` requirement for the Phase 2 subtopic
step correct and load-bearing, for the reason the plan gives even though the mechanism it
assumes is not the one in place.

---

### Q8. What exactly does `currentness.py` gate, and who calls it — build time, feed time, browser, or all three?

`scripts/currentness.py` is 129 lines and exports four functions:
`parse_date` ([:30](../scripts/currentness.py#L30)), `non_funding_reason` ([:42](../scripts/currentness.py#L42)),
`record_is_current` ([:64](../scripts/currentness.py#L64)), `filter_current` ([:109](../scripts/currentness.py#L109)).

`record_is_current(record, as_of)` returns `(bool, reason)` and gates, in order:
terminal `status` values (`closed/archived/cancelled/canceled/withdrawn/expired`) → `False`;
`status` not in `{posted, forecasted}` → `False, "invalid_status"`; a `non_funding_reason`
(title matching notice-of-intent / RFI, or an "Other"-only instrument whose description says
applications are not accepted) → `False`; then `close_date < as_of` → `"expired"`;
else `archive_date < as_of` → `"archived"`; else `True` with reason `"rolling"` or
`"undated_verify_status"`.

**Callers — build time (partial), feed time, and browser. Not all three uniformly:**

| Caller | Function | Line |
|---|---|---|
| `scripts/build_feeds.py` | `filter_current` | [:28](../scripts/build_feeds.py#L28) |
| `scripts/build_changes.py` | `parse_date`, `record_is_current` | [:24](../scripts/build_changes.py#L24) |
| `scripts/update_catalog_docs.py` | `filter_current` | [:15](../scripts/update_catalog_docs.py#L15) |
| `scripts/faculty_match.py` | `record_is_current` | [:39](../scripts/faculty_match.py#L39), applied at [:684‑688](../scripts/faculty_match.py#L684) |
| `scripts/alert_match.py` | `record_is_current` | [:24](../scripts/alert_match.py#L24) |
| external private digest repo | via `scripts.alert_match` | [docs/weekly-alerts/send_digest.py:50‑51](weekly-alerts/send_digest.py#L50) |
| browser — search app | `recordIsCurrent` (re-implemented) | [assets/app.js:299‑346](../assets/app.js#L299), applied at [:976](../assets/app.js#L976) |
| browser — team matcher | `recordIsCurrent` (re-implemented) | [assets/team-matcher.js:53‑64](../assets/team-matcher.js#L53), applied at [:140](../assets/team-matcher.js#L140) |
| browser — team researchers | `recordIsCurrent` (re-implemented) | [assets/team-researchers.js:184](../assets/team-researchers.js#L184), applied at [:416](../assets/team-researchers.js#L416) |

**`scripts/build_catalog.py` does not import `currentness.py` at all.** It has its own,
different `is_current(values, status, as_of)` ([build_catalog.py:469‑534](../scripts/build_catalog.py#L469))
that operates on raw Grants.gov XML tag values during extract parsing, before records are
normalized. So "the published catalog is gated at build time by `currentness.py`" is not
accurate: `opportunities.js` retains records `currentness` would exclude (the file carries
6 `archived` records today), and the gate is applied by *consumers* — feeds, docs stats,
faculty match, alerts, and three independent browser re-implementations against **today's**
date rather than the build date.

This is the resilience property `docs/HOSTING.md:262‑267` describes and the plan §16.2
correctly identifies. Extending it for subtopics means touching one Python module and
**three** JavaScript copies, not one.

---

### Q9. Team matching across `faculty_match.py`, `team-matcher.js`, `team-researchers.js` — which scores, which renders, and does any share the BM25 index with `search-retrieval.js`?

All three score. None purely renders. Rendering lives in `team_match.html` itself
(60 KB, inline `<script>` from [:260](../team_match.html#L260)), which loads all three
plus `search-query.js`, `search-retrieval.js`, and `orcid.js`
([team_match.html:251‑258](../team_match.html#L251)) and wires them at [:264‑271](../team_match.html#L264).

**`scripts/faculty_match.py` — build time, own scoring, no BM25.** `match_to_catalog`
([:673‑818](../scripts/faculty_match.py#L673)) filters the catalog through
`record_is_current`, then for each of 14 hard-coded faculty
([:46‑52](../scripts/faculty_match.py#L46)) requires at least one *hand-curated* key phrase
(`FACULTY_KEYTERMS`, [:162](../scripts/faculty_match.py#L162)) to hit the opportunity's
tokens via `_phrase_hit`. Score is `4.0 × len(hit_terms) + min(1.5, 0.25 × len(shared_topics))`
plus a bounded 0‑3 recency term ([:751‑755](../scripts/faculty_match.py#L751)). It never
reads `catalog.search_index`. Its OpenAlex inputs (`x_concepts`, `topics`) are explicitly
**overridden** by the curated lists — see the comment at [:157‑161](../scripts/faculty_match.py#L157).
Output: `data/faculty_matches.js`.

**`assets/team-matcher.js` — browser, own scoring, no BM25.** `create()`
([:99](../assets/team-matcher.js#L99)) rebuilds its own `wordFrequency` / `topicFrequency`
maps from `catalogData.opportunities` ([:134‑186](../assets/team-matcher.js#L134)) and uses a
hand-tuned bucketed `idf()` ([:189‑196](../assets/team-matcher.js#L189)) and `topicWeight()`
([:198‑205](../assets/team-matcher.js#L198)). It borrows `searchApi.tokenize` and
`searchApi.createAcronymResolver` when available ([:109‑132](../assets/team-matcher.js#L109))
but **not** `search_index.postings`. Exports `globalThis.FUNDING_TEAM_MATCHER`.

**`assets/team-researchers.js` — browser, and this one *does* share the BM25 index.**
`buildMatches` calls `retrievalEngine.score(keyword, { context })` and indexes the returned
`result.scores` by `documentId` ([:325‑341](../assets/team-researchers.js#L325)), i.e. the
same `FUNDING_RETRIEVAL` engine created over `catalog.search_index` in
[search-retrieval.js:45‑56](../assets/search-retrieval.js#L45). A non-BM25 fallback path
exists for when the hybrid scorer fails to load ([:366](../assets/team-researchers.js#L366)).
Exports `globalThis.FUNDING_TEAM_RESEARCHERS`.

**Answer to the plan's question:** partially, and the split matters. The ad-hoc-researcher
path (`team-researchers.js`) shares the BM25 index and would pick up subtopic records for
free once they are in `opportunities` + `search_index`. The roster/theme path
(`team-matcher.js`) and the build-time path (`faculty_match.py`) each run independent
similarity and would each need explicit work — including the per-parent cap, since neither
has any notion of a parent/child relationship.

---

### Q10. `assets/profile.js` and `tests/fixtures/browser_cv.txt` — what does the current CV path do with the text, and how does it combine with OpenAlex data?

**CV upload exists and is fully wired into live search.** The path:

1. **Extraction, entirely client-side.** `extractCv(file)`
   ([assets/profile.js:369](../assets/profile.js#L369)) reads the dropped file in the
   browser. PDFs go through vendored **pdf.js** (`assets/vendor/pdf.mjs`,
   `pdf.worker.mjs`), loaded dynamically at [:282‑284](../assets/profile.js#L282) and used
   at [:322‑324](../assets/profile.js#L322); `.docx` goes through vendored
   `assets/vendor/mammoth.browser.min.js`. Nothing is uploaded anywhere.
2. **Normalization and storage.** `normalizeCvText` ([:247‑264](../assets/profile.js#L247))
   caps at `MAX_CV_TEXT_CHARS = 120_000` ([:9](../assets/profile.js#L9)) and sets
   `cv_truncated`. The result is stored as `cv_text` in the browser-local profile object
   (`schema_version: 1`, [:127](../assets/profile.js#L127)) alongside `cv_name`, `cv_type`,
   `cv_word_count`, `cv_page_count`, `cv_updated_at`, `include_cv_in_ai`
   ([:139‑146](../assets/profile.js#L139), sanitized at [:176‑186](../assets/profile.js#L176)).
   Persisted to `localStorage` only if the user opts in.
3. **Scoring.** `assets/profile-ranking.js` `buildTermQuery` ([:20‑101](../assets/profile-ranking.js#L20))
   tokenizes four sources with different weights and turns them into a **weighted term
   query against the catalog's own BM25 postings** — it looks each expanded term up in
   `catalog.search_index.postings` ([:59](../assets/profile-ranking.js#L59)), computes an
   IDF from `catalog.record_count` ([:67‑72](../assets/profile-ranking.js#L67)), and emits
   the top 28 terms as a query string. The weights:

   | Source | Weight | Line |
   |---|---|---|
   | `expertise_keywords` | 5.0 | [:81](../assets/profile-ranking.js#L81) |
   | `research_description` | 2.2 | [:80](../assets/profile-ranking.js#L80) |
   | **`orcid_text`** | 0.72 | [:84](../assets/profile-ranking.js#L84) |
   | **`cv_text`** | 0.42 | [:83](../assets/profile-ranking.js#L83) |
   | career-stage boost | 5.0 | [:85‑89](../assets/profile-ranking.js#L85) |

4. **Admission vs. reranking.** The `admissionOnly` flag ([:27](../assets/profile-ranking.js#L27),
   applied at [:82](../assets/profile-ranking.js#L82)) excludes **both** `cv_text` and
   `orcid_text` from the pass that decides *whether* a record is admitted; they contribute
   only to ranking. This is the recent commit `bce35ce` "Separate profile admission from CV
   reranking."
5. **AI path, separately gated.** `include_cv_in_ai` controls whether a CV excerpt is put
   into AI chat context ([:460‑463](../assets/profile.js#L460)); default true, user-toggleable.

**How it combines with OpenAlex: it does not — the browser path uses Crossref, not OpenAlex.**
`assets/orcid.js` queries `https://api.crossref.org/works?filter=orcid:…`
([:4](../assets/orcid.js#L4), [:148‑176](../assets/orcid.js#L148)) for up to 50 works,
keeps only items where an author's `ORCID` matches, and builds `publicationText` from
**title | subjects | container-title** per work ([:130‑134](../assets/orcid.js#L130)) —
no abstracts. That string is stored as `orcid_text` (cap 40,000 chars,
[profile.js:10](../assets/profile.js#L10)) and enters the same term query at weight 0.72.
`team_match.html:370` re-labels it `publication_text` for the two team modules.

OpenAlex appears **only** at build time, in `scripts/faculty_match.py`
([:41](../scripts/faculty_match.py#L41), `build_profiles` at [:108‑139](../scripts/faculty_match.py#L108)),
where it supplies `x_concepts`, `topics`, and 12 recent titles — and where the concepts and
topics are then largely overridden by hand-curated `FACULTY_KEYTERMS`. So the two systems
are entirely disjoint: browser = Crossref + CV + free text, in BM25 space; build =
OpenAlex + curation, in its own phrase-match space.

---

### Q11. Which of the three workflow files are active, which is the nightly build, and do any share state?

Only **two** files are in `.github/workflows/`, and both are active:

1. **`refresh-opportunities.yml` — this is the nightly build.** `schedule: cron "17 10 * * *"`
   ([:22‑23](../.github/workflows/refresh-opportunities.yml#L22)), plus filtered `push` to
   `main` and `workflow_dispatch`. Writes and pushes the catalog.
2. **`tests.yml` — CI.** Triggers on every `push` and `pull_request` with no branch or path
   filter ([:3‑5](../.github/workflows/tests.yml#L3)), `permissions: contents: read`. Two
   independent jobs: `python` (`pip install -r requirements.txt`; `unittest discover -s tests`)
   and `browser` (`node --check` on six named asset files, then `node --test tests/browser/*.test.mjs`).

3. **`docs/weekly-alerts/weekly-digest.yml` is not a workflow of this repository.** It sits
   under `docs/`, where GitHub never looks. Its own header says so
   ([:1‑10](weekly-alerts/weekly-digest.yml#L1)): "This workflow belongs in a PRIVATE
   repository (so subscriber emails stay private). Copy it to
   `.github/workflows/weekly-digest.yml` in that repo." It is a template, committed here for
   reference.

**Shared state:**

- `refresh-opportunities.yml` and `tests.yml` share the **test suite** and `requirements.txt`
  but no artifacts, no cache keys beyond `setup-python`'s pip cache, and no concurrency group.
  Because `refresh` pushes to `main` and `tests.yml` triggers on every push, **each nightly
  commit fires a full `tests.yml` run**, and `tests.yml` re-tests against the freshly
  generated catalog.
- The digest template shares state **one-way and out of band**: it `git clone`s this public
  repo ([:39‑40](weekly-alerts/weekly-digest.yml#L39)) and imports `scripts/alert_match.py`
  from the clone ([send_digest.py:50‑51](weekly-alerts/send_digest.py#L50)). `alert_match.py`
  is never executed by any workflow in this repository — it is a library maintained here and
  consumed there. Its own watermark (`state.json`) lives in the private repo.
- `refresh-opportunities.yml` carries the only `concurrency:` group
  ([:30‑32](../.github/workflows/refresh-opportunities.yml#L30)); `tests.yml` has none.

---

## Plan discrepancies

Ordered roughly by how much rework each implies. Every item was checked against the tree in
this session.

### D1. The PDF library is `pypdf`, not `pymupdf` — and Layers A, B and C of §6.2 are not implementable as written

`requirements.txt` is three lines: `requests>=2.31.0`, `pypdf>=5.0.0,<7`, `openpyxl>=3.1.0`.
`extract_document_evidence.py:31` is `from pypdf import PdfReader`; extraction is
`page.extract_text()` per page ([:419‑450](../scripts/extract_document_evidence.py#L419)).

The plan's segmentation design is PyMuPDF-specific throughout:

- §6.1 `FetchedDocument.outline: list[tuple[int, str, int]]` and §6.2 Layer A
  (`doc.outline`) — pypdf exposes bookmarks as `reader.outline`, a *nested* list of
  `Destination` objects, not `(level, title, page)` triples, and page resolution requires
  `get_destination_page_number`. Reachable, but not the shape the plan assumes.
- §6.1 `page_spans: list[list[dict]]` with `size` and `flags`, and §6.2 Layer C's
  `s['size'] >= 1.15 * median or s['flags'] & (1 << 4)` — **pypdf does not expose per-span
  font size or a bold flag** from `extract_text()`. Layer C as specified requires either
  adding PyMuPDF (a new dependency, which §0.4 rule 7 forbids without asking) or a
  visitor-callback rewrite against pypdf's `extract_text(visitor_text=…)`.
- §6.1's "pin `pymupdf` exactly" and §12's "phantom `topic_amended` flood after a library
  upgrade" mitigation are moot; the relevant pin is `pypdf`, currently a **range**
  (`>=5.0.0,<7`), which is the actual determinism exposure.
- §9.3's "Dev dependencies: `reportlab` … goes in `requirements-dev.txt`" — **there is no
  `requirements-dev.txt`**, and `tests.yml` installs only `requirements.txt`. Note that
  `tests/test_document_evidence.py:5` already generates PDF fixtures with
  `from pypdf import PdfWriter`, so the existing pattern is pypdf-based fixture generation
  with no extra dependency.

Also relevant: extraction is capped at `MAX_PDF_PAGES = 250` and `MAX_PAGE_CHARS = 30_000`
per page ([:49‑50](../scripts/extract_document_evidence.py#L49)), so a 400-page BAA is
already truncated at page 250 today.

### D2. Umbrella-solicitation handling already exists, in two places, and §3's "there is no registry" is false

The plan's §3 states the design deliberately avoids "a hand-curated umbrella registry." One
already exists and is in production.

`scripts/sources/discoverability.py` — 445 lines, docstring at [:1‑23](../scripts/sources/discoverability.py#L1)
opening with the *exact* DOE Office of Science example the plan uses in §6.7. It defines
`PROGRAM_RULES` ([:38‑285](../scripts/sources/discoverability.py#L38)), **11 hand-maintained
rules** keyed on opportunity number or scoped title/description triggers, each carrying
`topics`, `terms`, and `evidence_urls`. It is versioned
(`DISCOVERABILITY_REGISTRY_VERSION = "2026-08-15"`) and calls itself "an evidence registry"
at [:17](../scripts/sources/discoverability.py#L17). `augment_records`
([:345‑444](../scripts/sources/discoverability.py#L345)) runs inside `merge.integrate`
([merge.py:371](../scripts/sources/merge.py#L371)), appends topic tags to `topic_areas` and
terms to `document_search_text`, and — importantly — **reverses its own prior contribution
first** ([:360‑374](../scripts/sources/discoverability.py#L360)) so rules can be corrected or
retired. 11 records in the committed catalog carry `discoverability_augmented: true`.

`scripts/program_areas.py` — 105 lines, a controlled vocabulary of 24 program areas
(`_ENTRIES`, [:34‑87](../scripts/program_areas.py#L34)) whose docstring
([:1‑27](../scripts/program_areas.py#L1)) describes it as the *generalization* of the
registry: `extract_program_areas` ([extract_document_evidence.py:916](../scripts/extract_document_evidence.py#L916))
scans actual notice text for these patterns and attaches only what genuinely appears, with a
page/section citation. 359 records currently carry `document_program_areas`.

**Implications for the plan:**

- §6.7 presents the DOE Office of Science "annual omnibus that points outward" as "the
  single largest remaining gap." It is the single most-worked case in the repository. The
  `doe-office-of-science-umbrella` rule already attaches BES / catalysis / separations /
  quantum topics and terms to `DE-FOA-0003600`, with `science.osti.gov/bes/Research` and
  `.../csgb/Research-Areas/Catalysis-Science` as cited evidence URLs
  ([:193‑217](../scripts/sources/discoverability.py#L193)). The gap that remains is
  *granularity* (no child record, no named program manager, no per-program deadline), not
  discoverability.
- §6.5's "`program_area_tags`: matched against the existing `scripts/program_areas.py`
  controlled vocabulary" is directionally right, but the vocabulary is a
  `(label, topics, pattern)` triple where `topics` must match the catalog Topic facet
  *exactly* ([:20‑24](../scripts/program_areas.py#L20)). The plan's §5.1 example value
  `["catalysis", "co2_utilization"]` matches neither form — the real values are
  `"catalysis"` (label) and `"Catalysis and reaction engineering"` (topic tag).
  `co2_utilization` does not exist in either vocabulary.
- The plan should reuse or extend these rather than introduce `scripts/sources/program_taxonomy.py`
  as an unrelated third mechanism. Note also the plan gives this file two different paths:
  §6.7 says `scripts/sources/program_taxonomy.py`, §8.2 and the §15 checklist say
  `scripts/sources/adapters/program_taxonomy.py`.

### D3. §10's justification for moving SAM.gov into Phase 1 is factually wrong

The plan asserts: "the canonical umbrellas (MURI, ONR LRBAA, AFOSR, ARO, DARPA) are
contract-vehicle BAAs that never appear on Grants.gov. Today they are absent from the
catalog entirely."

They are in the catalog today, via Grants.gov. 31 records mention BAA/MURI/DARPA/AFOSR in
title or agency, including:

| Number | Agency | Title (truncated) |
|---|---|---|
| `N0001425SB001` | Office of Naval Research | FY25 Long Range Broad Agency Announcement (BAA) |
| `W911NF-23-S-0001` | Dept of the Army — Materiel Command | DEVCOM ARMY RESEARCH LABORATORY BAA FOR FOUNDATIONAL… |
| `HR001126S0003 / S0010 / S0013 / S0016 / S0011` | DARPA (BTO, I2O, DSO) | office-wide and thrust BAAs |
| `NOFOAFRLAFOSR20260001 / …0003 / …0004` | Air Force Office of Scientific Research | DURIP, DEPSCoR |
| `N00173-24-S-BA01` | Naval Research Laboratory | NRL Long Range BAA |
| `W912HZ26S0001` | Engineer Research and Development Center | ERDC BAA |

The genuine gap is narrower than stated: no *MURI* record specifically, and no SAM.gov-only
notices. That may still justify the adapter, but not on the stated grounds, and the
"development corpus does not exist without SAM.gov" argument does not hold — a corpus of
DoD umbrella BAAs is already reachable through the existing document-evidence path.

Relatedly, §7.4's proposed `expected_solicitations.json` pattern
`^N00014-\d{2}-S-B\d{3}$` for ONR LRBAA does **not** match the number as it actually
appears in this catalog, `N0001425SB001` (no hyphens).

### D4. CV-based matching already exists, so §7.9's premise needs restating

§7.9 is written as though the profile representation problem is unaddressed and OpenAlex
concepts are the live representation. In the browser — which is where the personal profile
lives — none of that is true:

- CV upload, client-side pdf.js/mammoth extraction, 120 K-char storage, and BM25 scoring
  against `search_index.postings` are all shipped (Q10 above).
- The ORCID path uses **Crossref**, not OpenAlex (`assets/orcid.js:4`). So §7.9's
  "ORCID is never called directly. Resolution goes ORCID → `openalex.org/authors/orcid:…`"
  describes a change of provider, not a change of role, and would replace a working
  Crossref integration.
- §7.9's "the OpenAlex terms were irrelevant because the wrong OpenAlex output was used"
  applies only to build-time `faculty_match.py`, where the OpenAlex concepts have *already*
  been diagnosed as bad and overridden by hand-curated key terms — the code comment at
  [faculty_match.py:157‑161](../scripts/faculty_match.py#L157) says they "mis-resolved
  several people and attached over-broad tags."
- §7.9's table says the personal profile takes "ORCID (optional) + resume/CV + free-text
  interests." That is exactly what ships. The *new* content in §7.9 is: rehydrated abstracts
  as a terms source, recency weighting, and the negative-term list. Everything else is a
  description of the status quo.
- §7.9's `faculty_profiles_v2.json` would sit at the repo root next to `faculty_profiles.json`,
  not in `data/` — and neither is in the workflow's `git add` list, so committing it is a
  manual act.

### D5. §8.4's hermetic gate cannot be built as specified — `build_catalog.py` does not read those inputs

`tools/freeze_inputs.sh` proposes copying `data/source_records.json`,
`data/opportunity_enrichment.json` and `data/document_evidence.json` into
`tests/fixtures/frozen/` and then running
`build_catalog.py --input-dir tests/fixtures/frozen --output-dir … --build-date …`.

`build_catalog.py` reads **none of those three files**. Its only input is the Grants.gov
XML extract ZIP — downloaded from `grants.gov/xml-extract` or supplied via `--archive`
([:1092‑1101](../scripts/build_catalog.py#L1092)). The three caches are consumed by
`enrich_catalog`, `extract_document_evidence` and `sources.merge`, each of which rewrites
`opportunities.js` *after* `build_catalog` has produced it. A hermetic gate has to freeze
the XML archive and drive the whole five-script chain, not `build_catalog` alone.

Current CLI ([:1047‑1084](../scripts/build_catalog.py#L1047)): `--archive`, `--output`,
`--as-of`, `--min-records`, `--max-record-count`. So:

- `--build-date` already exists in substance as **`--as-of`** ([:1062‑1066](../scripts/build_catalog.py#L1062)).
  Per §8.1 ("no existing CLI flag changes meaning") the right move is to use `--as-of`, not
  add a synonym.
- `--input-dir` has no meaning for this script; the analogue is the existing `--archive`.
- `--output-dir` has no meaning; the analogue is the existing `--output`.

Plan Phase 1 step 1 as written would therefore add three flags, two of which duplicate
existing ones and one of which has nothing to point at. Note also that `write_catalog` is
**not** deterministic across runs even at a fixed date: `generated_at` is `utc_now()` at
[:1089](../scripts/build_catalog.py#L1089), and `enrich_catalog` / `extract_document_evidence` /
`check_links` each stamp their own `*_generated_at`. Byte-identical output requires those to
be injectable too.

### D6. `evaluate_phase2.py` does not evaluate the catalog, so Phase 1 step 3 cannot run

Plan step 3: "Run `evaluate_phase2.py` against the current catalog; commit
`evaluation/baseline_pre_topics.json`."

`evaluate_phase2.py` takes one or more **exported human relevance-label files** as
positional arguments ([:283‑288](../scripts/evaluate_phase2.py#L283)) and requires
`schema_version == 1` with a `feedback` list ([:26‑31](../scripts/evaluate_phase2.py#L26)).
Labels come from the browser review flow (`assets/review.js`). It never opens
`opportunities.js`. Its docstring says it "never needs an API key, research description, or
CV."

Compounding this: the label inputs are deliberately private. `.gitignore:24‑25` excludes
`/evaluation/inbox/` and `/evaluation/reports/`. The only committed sample is
`tests/fixtures/phase2_evaluation_export.json` (2.2 KB). A meaningful frozen baseline needs
a labelled corpus that is not in the repository.

§10 step 26 ("report topic-level recall separately from record-level") has the same
dependency: recall is computed over labels, so subtopic recall requires the review UI to
emit subtopic-level labels first.

### D7. `extract_document_evidence.py` contains none of the five symbols §8.3 says to move

§8.3 gives a literal alias block re-exporting `FetchedDocument`, `Unchanged`,
`fetch_document`, `_sha256_bytes`, `_extract_page_texts`. **None of these names exists.**
The nearest real equivalents:

| Plan name | Actual | Line |
|---|---|---|
| `fetch_document` | `download_document(url, headers=None, *, timeout=30, maximum_bytes=…, session=requests)` | [:1258‑1327](../scripts/extract_document_evidence.py#L1258) |
| `FetchedDocument` | no dataclass; `build_document_entry` returns a `(dict, bool)` tuple | [:1330‑1416](../scripts/extract_document_evidence.py#L1330) |
| `Unchanged` | no type; unchanged-ness is a `previous_hash == digest` early return | [:1336‑1351](../scripts/extract_document_evidence.py#L1336) |
| `_sha256_bytes` | inline `hashlib.sha256(content).hexdigest()` | [:1333](../scripts/extract_document_evidence.py#L1333) |
| `_extract_page_texts` | `extract_pdf_pages` / `extract_html_sections` / `extract_containers` | [:419](../scripts/extract_document_evidence.py#L419), [:453](../scripts/extract_document_evidence.py#L453), [:501](../scripts/extract_document_evidence.py#L501) |

The change-detection ladder the plan describes does exist, but split across three places:
conditional-request 304 handling in `download_document` ([:1288‑1297](../scripts/extract_document_evidence.py#L1288)),
SHA-256 comparison in `build_document_entry` ([:1336‑1351](../scripts/extract_document_evidence.py#L1336)),
and a `--recheck-days` / signature staleness check in `due_for_check` ([:1419‑1436](../scripts/extract_document_evidence.py#L1419)).

**One structural consequence the plan should absorb.** §4 asserts "Segmentation adds **no**
fetches. It reuses bytes already in hand." Today the extracted page text (`containers`) is
strictly local to `build_document_entry` — it is created at [:1381](../scripts/extract_document_evidence.py#L1381),
consumed by fact/program-area extraction, and discarded. It is never cached and never
returned. Worse, when the document hash is unchanged the function returns at
[:1338‑1351](../scripts/extract_document_evidence.py#L1338) **without extracting containers
at all**. So a separate `extract_subtopics.py` process running after
`extract_document_evidence` would have nothing in hand and would refetch every document. The
zero-added-fetches property requires either segmenting inside the same pass or persisting
something new — and persisting page text collides with the §4 privacy constraint.

### D8. Smaller factual corrections

| § | Plan says | Repository |
|---|---|---|
| §0.1 | "at least three workflow files … `docs/weekly-alerts/weekly-digest.yml`" | Two active; the third is a template for a different, private repo ([:1‑10](weekly-alerts/weekly-digest.yml#L1)) |
| §0.1 / §10 / §15 | "eleven questions" (§0.1) vs "all eight questions" (Phase 1 step 0) vs "nine answers written down" (§15) vs "nine answers with file/line citations" (§17.3) | There are eleven. Three different counts appear in the document |
| §5.2 | `from build_catalog import tokenize, stem, STOPWORDS` | `tokenize` exists ([:804](../scripts/build_catalog.py#L804)); `stem` does **not** — stemming is folded into `normalize_token` ([:791‑801](../scripts/build_catalog.py#L791)); the constant is `STOP_WORDS`, not `STOPWORDS` ([:309](../scripts/build_catalog.py#L309)). Also `tokenize` already drops stopwords and tokens of length ≤1, so the plan's extra filtering is redundant |
| §8.2 | `LICENSE` — "Replace MIT with the all-rights-reserved notice"; Phase 1 step 5 "LICENSE (MIT is leftover)" | **There is no `LICENSE` file.** The repo root has `copyright`, already reading "All rights reserved… Personal, non-commercial use is permitted." Seven commits between `d76c2a3` and `8b7ef92` did this work. Phase 1 step 5 is already done |
| §8.2 | `scripts/faculty_match.py` produces `data/faculty_matches.js` | Correct — [:829](../scripts/faculty_match.py#L829) |
| §8.2 | `scripts/build_changes.py` — "Append four new event types to the existing emitter" | File is real ([:287 lines](../scripts/build_changes.py)); `SCHEMA_VERSION = 1`, `RETENTION_DAYS = 90` ([:26‑27](../scripts/build_changes.py#L26)) |
| §8.2 | `assets/site-help.js`, `match_explorer.html`, `team_match.html`, `assets/search-retrieval.js`, `assets/app.js`, `assets/team-matcher.js`, `assets/team-researchers.js` | All exist at the stated paths |
| §8.2 | `scripts/sources/adapters/_template.py` | Exists, 53 lines |
| §8.2 | `scripts/sources/adapters/nspires.py` — "activate shell: fill in the existing stub's contract" | Accurate. `enabled = False`, `fetch()` raises, `parse()` returns `[]` ([:25‑44](../scripts/sources/adapters/nspires.py#L25)). Its docstring already flags the ROSES omnibus problem the plan describes |
| §9.2 | Step order: "build catalog (XML) / run source adapters / enrich catalog / extract document evidence / build catalog merge / … / check links / … / deploy Pages" | Actual order is build → **enrich** → **document evidence** → **sources merge** → faculty match → build changes → **check links** → build feeds → update docs → tests → commit. Source adapters run *fourth*, not second; there is no second "build catalog / merge" step (the merge is inside step 11); check-links runs *before* build-feeds; there is no deploy-Pages step |
| §9.2 | `check expected solicitations` inserted after "build catalog / merge" | The insertion point that actually exists is after step 11 (`sources merge`) and before step 13 (`build_changes`) |
| §11 | Cost estimate assumes a Haiku-tier model | Fine as an estimate. If this is ever built, note the current model line-up is the Claude 5 family (`claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`) plus `claude-haiku-4-5-20251001` |
| §16.3 | Heartbeat file `.github/last_build` | Does not exist. `.github/` contains only `workflows/`. The risk the plan identifies is real and unmitigated |
| §17.5 | "A proper `git clone`, on a branch" | Satisfied — branch `topic-layer` exists locally and on `origin`, tree clean at `b40d400`. One friction point: the checkout is owned by `BUILTIN\Administrators`, so `git` refuses it as "dubious ownership" unless invoked with `-c safe.directory=…`. Every git command in this session needed that prefix |

### D9. Constraints the plan does not mention and should

1. **`.gitignore` deny-by-default on `data/`** (Q1). The plan's §9.3 warns about the
   `git add` list but not about the ignore allowlist, and the ignore list is the one that
   fails the build loudly.
2. **`app.js` `validateCatalog` invariants** (Q4). `schema_version === 3` exact,
   `opportunities.length === record_count`, `search_index.document_count === record_count`.
   These make "child records in `opportunities`" a strictly all-or-nothing change.
3. **Positional document ids.** `search_index.postings` and `document_lengths` index into
   `opportunities` by position ([build_catalog.py:818‑841](../scripts/build_catalog.py#L818)).
   Subtopic records must be appended, and the index rebuilt in the same pass.
4. **Three browser copies of the currentness gate** (Q8), not one.
5. **`build_catalog.build_search_index` has a fixed field/weight table**
   ([:820‑834](../scripts/build_catalog.py#L820)). `subtopic_terms` would need a new entry
   there, and the comment at [:831‑833](../scripts/build_catalog.py#L831) records the
   existing policy: "Phase 3 adds only compact, cited notice facts here. Raw notice text is
   never placed in the browser catalog or search index."
6. **The workflow's `paths:` push filter** ([:7‑21](../.github/workflows/refresh-opportunities.yml#L7))
   lists scripts individually; new scripts do not trigger push-runs unless added.
7. **`opportunities.js` is already 24.8 MB.** The plan's Phase 1 step 4 size-budget test at
   1.5× would set the ceiling near 37 MB. Worth deciding whether that is a budget or a
   ceiling — GitHub's recommended file-size warning threshold is 50 MB.

---

## Blocked

**B1. Q6 — total workflow wall-clock runtime.** Not recoverable from the repository. The
`generated_at` → commit-time proxy (96–130 s) covers only steps 8–18; checkout, toolchain
setup, `pip install`, and two full test runs are unmeasured. Getting the real number needs
the Actions run history — either the run-summary page or
`gh run list --workflow refresh-opportunities.yml --json databaseId,createdAt,updatedAt,conclusion`.
This blocks nothing in Phase 1, but it does block calibrating §9.4's "runtime delta under
20%" gate, so it should be captured before the first workflow edit.

**B2. Partial — the current state of the `jhu-fellowships` degradation.** The committed
catalog shows `status: "failed_no_fallback"`, which means the "External funding source
refresh degraded" issue is being opened or commented on every run. Whether that issue is
currently open, and whether the owner considers it expected, is not determinable from the
tree. It matters because §9.4 checklist item 4 is "confirm no GitHub issue was opened or
updated" — which will fail for reasons unrelated to the subtopic work unless this is
resolved or explicitly excepted first.

Nothing else in §0.1 was blocked. All eleven questions are answered from code above.

---

## §0.4 session report

### 1. Files read this session

Read in full: `docs/TOPIC_LAYER_PLAN.md` (1,121 lines, both pages);
`.github/workflows/refresh-opportunities.yml`; `.github/workflows/tests.yml`;
`docs/weekly-alerts/weekly-digest.yml`; `scripts/currentness.py`; `scripts/program_areas.py`;
`scripts/sources/discoverability.py`; `scripts/sources/__main__.py`;
`scripts/sources/adapters/nspires.py`; `assets/orcid.js`; `assets/profile-ranking.js`;
`requirements.txt`; `.gitignore`; `copyright`.

Read in part (named ranges): `scripts/build_catalog.py` (1–70, 308–320, 791–1120);
`scripts/extract_document_evidence.py` (419–535, 1192–1460, 1667–1700, 1902–1928);
`scripts/faculty_match.py` (1–60, 108–170, 575–820);
`scripts/enrich_catalog.py` (140–170, 1060–1100); `scripts/check_links.py` (296–332);
`scripts/update_catalog_docs.py` (330–361); `scripts/build_changes.py` (240–287);
`scripts/evaluate_phase2.py` (1–40, 276–303); `scripts/sources/merge.py` (46–130, 325–395);
`assets/app.js` (222–245, 3900–4010); `assets/profile.js` (100–200);
`assets/search-retrieval.js` (45–75); `assets/team-matcher.js` (1–220);
`tests/test_document_evidence.py` (1–40); `tests/test_program_areas.py` (1–30);
`docs/HOSTING.md` (grep + 190–215); `tests/fixtures/browser_cv.txt`.

Structural reads (grep/wc/symbol listings, not line-by-line): all of `scripts/**`,
`assets/*.js`, `tests/**`, `team_match.html`, `match_explorer.html`, `index.html`,
`evaluation/SEARCH_RELEVANCE_AUDIT_2026-08-15.md`, `feeds/`.

Parsed read-only with a throwaway `python -c` (no file opened for writing):
`data/opportunities.js`, `data/source_records.json`.

### 2. The exact diff I intended, stated before making it

One new file, `docs/RECON.md`. No edit, of any size, to any pre-existing file. That is what
happened: the diff is `1 file changed, N insertions(+), 0 deletions(-)`, all in
`docs/RECON.md`.

### 3. Commands run, with their real output

All commands were read-only: `ls`, `find`, `wc -l`, `grep`, `sed -n`, `head`, `tail`,
`git log`, `git branch`, `git status`, `git show --stat`, and two `python -c` one-liners
that parse JSON and print. No script in this repository was executed. Nothing was installed.
`git status --short` was empty at the start of the session.

Two outputs are load-bearing enough to reproduce:

```
$ git -c safe.directory=... log --oneline -5
b40d400 Update topic layer plan to v6.2 (naming rule, corrected paths)
981789d Add topic layer implementation plan
7b5ed68 chore: refresh Grants.gov catalog
7f8345a Improve recall for audited umbrella funding calls
bce35ce Separate profile admission from CV reranking
```

```
$ cat requirements.txt
requests>=2.31.0
pypdf>=5.0.0,<7
openpyxl>=3.1.0
```

The second is the single most consequential finding for Phase 2 (D1).

I did **not** run the test suite. Nothing in this document claims a test passed, a build
succeeded, or a gate cleared.

### 4. Which §15 checklist item is now complete

**Phase 1, item 0 — "§0 reconnaissance complete."** All eleven §0.1 questions are answered
from code, with file and line citations, in this file. Q6 is answered as far as the
repository permits and its residual is recorded under Blocked (B1).

No other checklist item was touched. The Phase 1 gate remains uncrossed.

### 5. What I did *not* do that a reader might assume I did

- **I did not correct `docs/TOPIC_LAYER_PLAN.md`.** Nine substantive discrepancies (D1–D9)
  are documented here only. Per §17.3 that is session 2's deliverable, and §0.4 rule 5
  forbids doing two steps in one sitting. The plan on disk is still wrong about `pymupdf`,
  the registry, SAM.gov coverage, the CV path, `--input-dir`, `evaluate_phase2.py`, the
  five function names, and the workflow step order.
- **I did not verify anything by execution.** No test run, no script run, no `pip install`,
  no `workflow_dispatch`. Every claim above is from reading source, with two exceptions that
  are read-only parses of committed data files.
- **I did not read `assets/app.js` in full** (4,361 lines). I read the catalog-validation
  and CV-upload regions and grepped for the rest. If subtopic rendering touches a region I
  did not read, that region is unassessed.
- **I did not read `PROJECT.md` (49 KB) or `README.md` (17 KB) in full**, only greps. Both
  are workflow-regenerated, so they are output rather than source, but they may contain
  design history that contradicts something here.
- **I did not evaluate whether the subtopic layer is a good idea**, whether the four-layer
  segmentation would work on real notices, or whether the acceptance rules in §6.4 are
  well-calibrated. Those are design questions; §0.1 is a factual survey.
- **I did not check that the plan's other claims about *external* systems hold** — the
  SAM.gov API shape in §7.5, the OpenAlex `abstract_inverted_index` behaviour in §7.9, the
  GitHub 60-day schedule-disabling rule in §16.3. §0.4 rule 10 requires fetching a real
  response before writing code against any of them; none was fetched, because this session
  made no network calls at all.
- **I did not confirm the ONR/ARL/DARPA records found in the catalog are *umbrella* records
  with enumerable subtopics.** I confirmed they are present. Whether their attached PDFs
  contain segmentable topic lists is a Phase 2 question and would require fetching them.
- **I did not resolve B2** (whether the `jhu-fellowships` degradation issue is currently
  open on GitHub). That needs the repository's issue list.
