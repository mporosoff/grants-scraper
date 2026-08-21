# Coverage survey — where subdivision lists actually live

> **⚠ NASA reachability corrected 2026-08-17 — read `docs/ROSES_SOURCE_INSPECTION.md`.**
> Every statement in this document that describes `nspires.nasaprs.com` or
> `solicitation.nasaprs.com` as unreachable, resetting the connection, or
> refusing this client is **a fact about our HTTP client, not about NASA**.
> CPython's default TLS cipher list omits `AES256-GCM-SHA384`, which is the only
> suite those hosts offer; adding it — security level untouched, certificate and
> hostname verification intact — connects at `TLSv1.2`. **All 12 NASA records
> previously recorded as unreachable were re-fetched successfully on 2026-08-17,
> with zero failures.** The counts and classifications below are otherwise
> unchanged; only the attributed cause is wrong.


**Every number in `docs/CORPUS_CENSUS.md` before its D4 section came from 20
hand-picked documents.** This survey replaces that denominator with the whole
catalog for what can be counted, and with a 40-record stratified sample —
deliberately disjoint from the 20 — for what has to be read.

| Field | Value |
|---|---|
| Date | 2026-08-16 |
| Catalog | 1,475 records, `data/opportunities.js` (schema 3) |
| Attachment metadata | **1,635 attachments across all 1,475 records**, from live `fetchOpportunity`. Metadata only — no attachment bytes fetched in stage 1 |
| Read sample | **40 records, 131 attachments and agency pages opened, 0 fetch failures.** None of the 20 census records |
| Segmenter | `scripts/subtopic_segmentation.py` at commit `9151a03`, unmodified |
| Written | `docs/COVERAGE_SURVEY.md` only. No production code, no new families, no cache committed |

## Headline

> **The catalog is 44.7% zero-attachment and 46.4% unreachable, and those are
> the two biggest coverage facts — bigger than any pattern.**
>
> **In a stratified 40-record sample, 10 records (25%) carry an enumerated set
> of fundable subdivisions; 7 clear the §6.4 three-item floor.** The census's
> 12-of-20 was a property of the sample, not of the corpus.
>
> **No single mechanism unlocks more than an estimated ~48 records.** The
> ranked table is at the end; the largest row is not a pattern, it is
> `source_for_record()`.

---

## Stage 1 — attachment metadata census

### What the caches can and cannot answer

The committed caches store **`attachment_count` and the one selected primary
document's name** — nothing else. `document_urls` holds agency web links from
`synopsisDocumentURLs`, not Grants.gov attachments. Filenames, extensions,
sizes and folders of every *other* attachment are stored nowhere, and
`scripts/subtopic_sources.py` records why: storing them would change
`compact_detail` and therefore `data/opportunity_enrichment.json` on the next
nightly with the flag off, which is exactly what §0.5 forbids.

So a cache-only census can report counts and the primary's name and stops
there. `fetchOpportunity` is the only source for the rest, and it returns
metadata; **no attachment bytes were downloaded in this stage.**

The sweep also validates the cache: across all 1,475 records the live
attachment count and the cached `attachment_count` agreed **1,475 times out of
1,475, with zero mismatches and zero API errors.** The count field is reliable;
it is simply not enough.

### Distribution of attachment counts

| Attachments | Records | Share |
|---|---|---|
| **0** | **660** | **44.7%** |
| 1 | 583 | 39.5% |
| 2 | 91 | 6.2% |
| 3 | 29 | 2.0% |
| 4 | 32 | 2.2% |
| 5 | 35 | 2.4% |
| 6–10 | 31 | 2.1% |
| 11–39 | 14 | 0.9% |

**232 records (15.7%) carry more than one attachment**, not the 60% the census
measured — the census's 20 were chosen for shape and are far heavier than the
corpus. The tail is real though: one Army record carries 39 attachments, a DOE
record 26, a VA record 19, an AFRL BAA 17.

### File types

| Extension | Attachments | Share |
|---|---|---|
| `.pdf` | 971 | 59.4% |
| `.html` | 366 | 22.4% |
| `.docx` | 177 | 10.8% |
| `.xlsx` | 84 | 5.1% |
| `.zip` | 17 | 1.0% |
| `.jpg` | 9 | 0.6% |
| `.pptx` | 6 | 0.4% |
| `.doc` / `.rtf` | 5 | 0.3% |

**483 records carry at least one non-PDF attachment.** 88 carry a Word file,
64 a spreadsheet, 15 a zip.

**All 366 `.html` attachments belong to NIH**, and they split hard by size:
**255 are stubs under 1 KB** (the census's `355867` was one — 429 bytes) and
**111 are complete announcements averaging ~145 KB**, spread across 108
records. `select_primary_document` requires a PDF, so **not one of those 108
full-text HTML announcements is selectable today.**

### Functional categories

Clustered from filename + description + folder name, first match wins. This is
a *name-based* clustering, and stage 2 exists partly to measure how badly
name-based inference misleads — it does, see `349554`.

| Category | Attachments | Share | Example |
|---|---|---|---|
| notice | 898 | 54.9% | `OFOP0003000 - Bosnia SPO Analytics NOFO.pdf` |
| other | 196 | 12.0% | `FY26 Annual Program Statement 04022026.pdf` |
| amendment | 170 | 10.4% | `hhs-2026-acf-acyf-ts-0013 - Revised Full Announcement.pdf` |
| appendix | 151 | 9.2% | `Attachment 1 - Applicant Organization Information Survey.docx` |
| template | 122 | 7.5% | `Environmental_Checklist_Fillable.pdf` |
| budget form | 41 | 2.5% | `SF424A-V1.0.pdf` |
| faq / webinar | 21 | 1.3% | `Questions and Answers- DFOP0019393.pdf` |
| certification | 21 | 1.3% | `Mandatory_SF424B-V1.1.pdf` |
| **topic list** | **15** | **0.9%** | `BIGST_BAA_T06_MUSE_2v1.pdf` |

Two cautions the counts themselves supply. **The categories overlap heavily** —
123 attachments match both `amendment` and `notice`, 69 both `appendix` and
`template` — so first-match-wins is a convenience, not a taxonomy. And **the
`topic list` row is 0.9%, which is the single most misleading number in this
section**: stage 2 found enumerated lists inside files named
`FA2391-23-S-2403.pdf`, `H08 HQ003423NFOEASD01 STEM NFO 20260323.pdf` and
`FY2026_CTP_NOFO_06.25.2026_508c.pdf`. Names do not carry this signal.

Grants.gov's own folders are a better structural hint than the names:
**Full Announcement 1,209 · Other Supporting Documents 306 · Revised Full
Announcement 120.**

Of the 1,635 attachments, **373 are the selected primary** and **1,262 have
never been opened by the production path**. By category those 1,262 break down
as notice 584, other 182, appendix 151, amendment 129, template 119, budget
form 41, faq 21, certification 21, topic list 14.

### Records with zero fetchable attachments — 660, and why

| Reason | Records |
|---|---|
| Agency posts its announcement on its own site; an agency URL is present | **347** |
| Agency posts elsewhere and **no URL of any kind** is on the record | **313** |

By agency: NIH 210, NSF 149, HRSA 42, CDC-ERA 42, NYSERDA 39, VPR digest 24,
BJA 14, IHS 12. By source: 596 are Grants.gov records that simply carry no
attachment, 39 are NYSERDA and 24 are the VPR digest — two non-Grants.gov
sources for which an attachment cannot exist by construction.

**313 records — 21.2% of the catalog — have no fetchable source at all.** No
mechanism in this document reaches them; they need a different acquisition
path, which is the §7.5/§18.2 adapter work.

---

## Stage 2 — 40 records, every attachment opened

### How the sample was drawn

Stratified on **attachment profile** × **agency family**, seeded and
reproducible, with the 20 census records excluded by construction, a cap of two
records per agency string (DHA alone offers dozens of near-identical award
notices, and four of them measure one thing four times), and reserved seats for
DOE, NASA and DOT, which a purely proportional draw dropped.

| Stratum | Catalog | Sampled |
|---|---|---|
| A — exactly one attachment, PDF | 215 | 10 |
| B — 2–4 attachments, all PDF | 90 | 9 |
| C — 5+ attachments, all PDF | 27 | 6 |
| D — any non-PDF attachment (of which NIH HTML: 363) | 483 | 7 (2 NIH) |
| E — zero attachments, agency URL present | 347 | 8 |
| F — zero attachments, no URL at all | 313 | 0 — nothing to open |

Agency spread: DoD 5, State/USAID 6, Interior 5, HHS-other 5, NIH 2, NSF 2,
USDA 3, DOT 2, DOE 1, NASA 1, DHS 1, other 7.

**Every attachment on every sampled record was downloaded and structurally
read** — bookmark trees, enumeration cues and their neighbourhoods, worksheet
cell values, Word paragraph runs, HTML headings — with no name-based skipping.
131 files and pages, 0 fetch failures. Judgments below were made by **reading
the neighbourhood**, not by trusting the cue counts.

### The ten records that enumerate

| id | Agency | Where the list is | Type | Form | ~n | Reachable today | Segmenter today |
|---|---|---|---|---|---|---|---|
| `360205` | USDA NIFA | primary PDF, bookmarked | pdf | numbered `1a.`…`7g.` | **37** | yes | **accepts, 37 spans, medium** |
| `349554` | AFRL PACER | **secondary** `FA2391-23-S-2403.pdf` | pdf | numbered `Topic N – Title` | **18** | wrong file selected | accepts on the right file — **`low`, never publishes** |
| `345938` | WHS NDEP STEM | primary PDF, zero bookmarks | pdf | bare `1)`…`8)` | 8 | yes | `no_layer_accepted` |
| `vpr-…78b24028` | Sloan Foundation | **agency HTML page** | html | named fields | 7 | **no** | n/a |
| `363607` | State GHSD | **6 separate PDF attachments** (Addenda G–L) | pdf | one subdivision per file | 6 | **no** | `no_layer_accepted` per file |
| `362233` | DHA CDMRP Lupus | primary PDF, §3.2.1 | pdf | **bulleted, no ordinal** | 5 | yes | `no_layer_accepted` |
| `363000` | FEMA CTP | primary PDF + Appendix C | pdf | bulleted project types | 3 | yes | `no_layer_accepted` |
| `358100` | DOE NRC licensing | primary PDF | pdf | `Topic Area 1` / `2` | **2** | yes | below the 3-item floor |
| `332127` | EDA Seattle | primary PDF, bookmarked | pdf | named `a)` / `b)` programs | **2** | yes | below the 3-item floor |
| `334079` | EDA RNTA | primary PDF, bookmarked | pdf | named R&E / NTA | **2** | yes | below the 3-item floor |

> **10 of 40 records (25%) enumerate. 7 clear §6.4 rule 1's three-item floor.
> One of the ten segments and publishes today.**

Extrapolated per stratum — hit rate within a stratum times that stratum's
catalog population — this is **~128 records catalog-wide carrying an
enumerated set, ~115 of them at three items or more.** The per-stratum sample
sizes are 6–10, so treat these as an order of magnitude, not a count: the
95% interval on a 2-of-10 stratum rate runs roughly 6%–51%.

| Stratum | Hits | Rate | Catalog estimate |
|---|---|---|---|
| A (215) | 2/10 | 20% | ~43 |
| B (90) | 2/9 | 22% | ~20 |
| C (27) | 5/6 | 83% | ~22 |
| D-NIH (363) | 0/2 | 0% | ~0 |
| D-other (120) | 0/5 | 0% | ~0 |
| E (347) | 1/8 | 13% | ~43 |

**The C stratum is where lists live** — 5 of 6 records with five or more
attachments carry one — and it is only 27 records. **The D stratum, 483 records
and the largest with attachments, produced zero**, and 363 of those are NIH
records whose attachment is an HTML stub.

### The five findings that change how the table should be read

**1. The selected primary is sometimes furniture.** `349554` (AFRL PACER, 17
attachments) has `Atch 10 BAA Attachment - Security Program Questionnaire.pdf`
as its `primary_document_url` — a single page, 1,853 characters. The real BAA
is `FA2391-23-S-2403.pdf`, and it carries `Topic 1 – Aero-Structures` through
`Topic 18 – Development and Demonstration of Advanced Military Air…`.
Handed that file, production's own segmenter returns **18 correct spans** —
at `numbered`, which is Layer D, which is `low`, which never publishes.
Corpus-wide this misselection is rare: **4 records of 1,475** have a
furniture-named primary, including the census's `360261`.

**2. Subdivisions are sometimes one-per-attachment.** State's `363607`
Advancing Global Health APS carries six Addenda — Cameroon, Côte d'Ivoire,
Mozambique, NTDs, Nutrition, Surveys and Surveillance — each a separate PDF,
each a fundable subdivision, and the APS itself only says *"through specific
Addenda, the Department will signal priorities."* Nothing in §6.2's four layers
models a subdivision that **is** a whole document. The record is also
unreachable, so nothing is fetched for it at all.

**3. A bulleted list is the DHA shape, and it sits next to a decoy.**
`362233` reads *"the proposed research must address at least one of the
following FY26 LRP IA Focus Areas"* and lists five bullets. The very next
subsection, `3.2.2. Key Elements for the IA`, is also five bullets —
*Innovation, Impact, Research Strategy, Focus Areas, Research Team* — and is
not a subdivision list at all. Any bulleted-list recognizer meets both, two
inches apart, with no ordinal to tell them apart. Note also that the sibling
record `362848` (DHA Duchenne) has **one** focus area in prose: the same
program office, the same template, different shape.

**4. Word is where four sampled announcements live, and none of them
enumerates.** `363537`, `363538` (USGS CESU), `363247` (Embassy Tirana) and
`363541` (Embassy Yerevan) all publish `Full Announcement.docx` or an
equivalent, and all four have `primary_document_url: null` because
`select_primary_document` requires a PDF. Parsing Word makes those documents
readable — and buys **zero** subdivision lists, because each is a
single-project cooperative agreement. That is worth knowing before building it.

**5. Two agency-page hosts return nothing at all.** NYSERDA's portal
(`portal.nyserda.ny.gov`) and State's `mygrants.servicenowservices.com` both
return a ~17 KB JavaScript shell — literally `{{::c.i18n.search_categories}}`.
**87 catalog records point their agency URL at those two hosts** (48 mygrants,
39 NYSERDA). BJA's page is a landing page with the solicitation one hop away as
a linked PDF. NSF's `pub_summ.jsp` pages, by contrast, carry the **entire**
solicitation in HTML — and 153 records point at `www.nsf.gov`, 294 at
`grants.nih.gov`.

Also recorded: `363388` (ETA UIPL 13-26) is an 18.7 MB, 49-page image-only PDF
yielding **48 characters** of text — the `no_extractable_text` case, seen in
the wild. `360003` (ROSES A.10 INNOVATE) has exactly one attachment, a zip; the
zip holds `INNOVATE25_PSD.pdf`, which is a *Program Specific Data form*, not
the element text. NASA's element text really is only on NSPIRES, which resets
the connection.

---

## Stage 3 — reachability

### The census's 246-of-1,016 was the wrong denominator

That figure counted entries **already in the evidence cache**. The question is
what fraction of the *catalog* is never attempted, and the answer is larger.

Running production's own `source_for_record()` over all 1,475 catalog records:

| Outcome | Records | Share of catalog |
|---|---|---|
| `primary_notice` — a selected PDF attachment | 373 | 25.3% |
| `agency_notice` — an agency URL, gap-fill needed | 417 | 28.3% |
| **`None` — never attempted** | **685** | **46.4%** |

The two figures reconcile exactly: after the D5 backfill the evidence cache
held 1,016 entries, of which 213 belong to records that have left the catalog;
**672 catalog records have no evidence entry at all, and every one of the 672
is in the unreachable set** (685 − 672 = 13 orphans, records that still carry
an entry from when they were reachable — the `363526` pattern, now measured at
13, kind `primary_notice` for 12 of them).

### Why the 685 are unreachable

| Cause | Records | of which carry attachments |
|---|---|---|
| No document URL of any kind on the record | 464 | 151 |
| Agency URL present, but `needs_gap_fill` is false so the source is declined | 221 | 85 |

**236 of the 685 carry live Grants.gov attachments right now.** The rule
declining them is `select_primary_document`, which is deliberately
conservative: it accepts only a PDF whose name or description carries explicit
NOFO/FOA/RFA/BAA language, or a lone PDF in a Full Announcement folder, and
skips anything matching the supplemental pattern. That is a defensible rule for
*citation* — a wrong one-click link is worse than none — and it is the wrong
rule for *segmentation*, which does not have to publish the link it read.

### What a different selection rule would reach

| Rule | Unlocks (of the 685) | Share of catalog |
|---|---|---|
| Any PDF in a Full / Revised Announcement folder | 46 | 3.1% |
| Any PDF attachment at all | 57 | 3.9% |
| Any non-stub (≥2 KB) HTML attachment | **108** | 7.3% |
| Any attachment at all | **236** | 16.0% |
| Drop the `needs_gap_fill` test on agency URLs | **221** | 15.0% |
| **Union of all of the above** | **372** | **25.2%** |

The remaining **313 have no source of any kind** and stay unreachable under
every rule above.

The 108 HTML row is the single largest clean win and it is entirely NIH: the
full-text announcement is sitting in the Grants.gov attachment system as an
`.html` file and is rejected because it is not a PDF. Stage 2 tempers what that
buys — the two NIH records sampled and the one FDA record on the same NIH
template all enumerate nothing.

### Fetch failures, re-derived

25 entries carry `last_error`, unchanged in character from the census:
`nspires.nasaprs.com` 10, `solicitation.nasaprs.com` 6, `www.transit.dot.gov`
4, `www.rd.usda.gov` 2, `bja.ojp.gov` 1, `nsf.gov` 2. **Two hosts account for
16 of 25**, and neither is a segmentation problem.

---

## The ranked coverage table

One row per mechanism. **"Sampled"** is records out of the 40 whose subdivision
list the mechanism would put in reach; **"Catalog est."** applies that
stratum's rate to that stratum's catalog population. A record can need more
than one mechanism, so the column does not sum — and `vpr-…78b24028` (Sloan) is
counted in both row 1 and row 2, so those two rows overlap almost entirely.

| # | Mechanism | Sampled | Catalog est. | Cost | What it actually buys, and what it risks |
|---|---|---|---|---|---|
| 1 | **Fix the fetch-path gap** (`source_for_record`) | **2/40** | **~48** | **Medium** | Gates **685 records — 46.4% of the catalog — from ever being tried**, of which 372 have a reachable source. The pattern already exists: `subtopic_sources.py` is a parallel subtopic-only path that leaves `source_for_record`'s single-source contract, `document_evidence.json` and §0.5 untouched. Risk: none to flag-off parity if it stays parallel; every widening also widens the false-positive surface, as §6.6 already measured |
| 2 | **HTML / external agency pages** | 1/40 | ~43 | **Medium–large** | 108 records have a full NIH announcement sitting in an unselectable `.html` attachment; 347 more have only an agency URL. `extract_html_sections` already exists. But the tail is per-host and unbounded: NSF pages carry the whole solicitation, NYSERDA and State return a JavaScript shell, BJA needs one more hop to a PDF. The one sampled win — Sloan's seven fellowship fields — came from a foundation page, not a federal one |
| 3 | **Named / structural lists with no ordinal** (bulleted, labelled) | 2/40 | ~32 | **Large** | The `label_run` gap §6.3a deferred, plus the bulleted variant. Highest false-positive risk in the table: `362233`'s five real Focus Areas sit one subsection above five decoy bullets (*Innovation, Impact, Research Strategy…*), and no ordinal separates them. §18.3's asymmetry applies at full force |
| 4 | **Lower §6.4 rule 1's floor from 3 items to 2** | 3/40 | ~14 | **Trivial (one constant)** | The cheapest row and the most dangerous. It would admit DOE's real `Topic Area 1`/`2` and EDA's two programs — and every two-item administrative pair in 1,475 notices. Recorded because it is the third-largest sampled unlock, **not** recommended |
| 5 | **New ordinal families** (bare `N)` ) | 1/40 | ~10 | **Small (regex)** | `345938`'s eight NDEP STEM program areas are written `1) … 8)`. This is precisely the generic numbered family §6.3 and §18.3 name as the most damaging change available — the one that manufactures a subtopic titled *Federal Agency Name*. Same verdict as `332894` in the census |
| 6 | **Multi-attachment fetch + rank by result quality** | 1/40 | ~5 | **Small — already built** | `scripts/subtopic_sources.py` exists and works. What is missing is (a) primary *selection* quality — only 4 records of 1,475 have a furniture-named primary, but one of them is `349554`, which hides 18 correct topics — and (b) the `low`-confidence cap on secondary-won results, which correctly blocked one fabrication and now also blocks PACER's 18 correct spans. That cap is a one-record-of-evidence decision on both sides |
| 7 | **Word (`.docx`) parsing** | **0/40 lists** | **0 lists** | **Small** (`zipfile` + tag strip, no new dependency) | 177 `.docx` files across 88 records; 32 records carry Word and no selectable PDF. Makes 4 sampled announcements readable at all — and **none of the four enumerates**. Buys evidence coverage, not subtopics |
| 8 | **Spreadsheet parsing** | **0/40 lists** | **0 lists in sample** | **Medium** | 84 `.xlsx` across 64 records. Every spreadsheet in this sample was a budget template. The one known win is outside this sample and is large: the Genesis Mission's **98 focus areas** in a `Focus Areas` worksheet (`docs/CORPUS_CENSUS.md`). `openpyxl` is already a dependency, so the cost is dispatch plus a cell-list segmentation path — there are no prose spans to summarize, which §6.5 assumes throughout |

### How to read the ranking

**The top of this table is plumbing, not patterns.** Rows 1 and 2 are about
which bytes arrive; rows 3–5 are about what to do with bytes already arriving.
That ordering is the opposite of where package D's effort went, and it is
consistent with what package D found: more regexes bought almost nothing.

**Rows 1 and 2 overlap and rows 7 and 8 are honest zeroes.** The union of
rows 1 and 2 is ~48 records, not ~91. Rows 7 and 8 are in the table because
they were asked for and because measuring them to zero is a result — the
sample says Word and spreadsheets carry forms, not topic lists, with one known
and important exception.

**Nothing here is worth building before the precision question is settled.**
The D5 re-run reached zero fabricated publishable records by *demoting* things
— Layer C to `low`, secondary attachments to `low`, plus the process-vocabulary
check. Rows 1, 2 and 3 all widen the input again. On the backfill's own
evidence, widening the input widened the false-positive surface faster than it
widened recall, and the §12 per-subtopic budget conflict is still open and
still blocks committing a cache at all.

### The measurement that would change this table

Every catalog estimate here rests on 6–10 records per stratum. The two cheapest
ways to tighten it, in order:

1. **Sample 40 more records inside strata C and E only** (27 and 347 records).
   C has the highest hit rate in the corpus and the smallest population; E is
   the largest reachable-but-unfetched population and rests on a single hit.
2. **Read 20 of the 108 non-stub NIH HTML announcements.** That one number —
   how many NIH full announcements enumerate anything — moves row 2 by a factor
   of five in either direction, and it is a stratum of 108 nearly identical
   documents, so 20 is enough.

---

## Method, and what this survey did not do

Attachment metadata came from `scripts.pull_grants.fetch_detail` and
`collect_attachments` — production's own functions — once per catalog record at
a 0.25 s delay, writing JSONL to the session scratchpad. Documents in stage 2
were fetched with production's `download_document`, parsed with `pypdf`,
`openpyxl`, and `zipfile` plus a tag strip for OOXML and HTML, and the
enumerating ones were passed through production's `extract_containers` and
`segment_document` unmodified. Reachability used production's
`source_for_record` against the committed catalog, and the post-backfill
evidence counts came from the D5 re-run artifact in the previous session's
scratchpad, which remains uncommitted.

Probe scripts are not committed, for the same reason as B0 and the census: they
are one-shot instruments against network-fetched documents, and the test suite
has no network path.

**Not done, and a reader might assume otherwise:** no mechanism was
implemented, no family was added, no threshold was changed, no backfill was
run, and no cache was committed. The 40-record judgments are one reader's
reading of each document, not a second-rater-agreed label set. The stratum
rates have 6–10 records behind them. And stratum F — 313 records with no
fetchable source at all — was measured but not sampled, because there is
nothing to open.
