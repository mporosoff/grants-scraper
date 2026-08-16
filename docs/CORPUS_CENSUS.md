# Corpus shape census

**20 notice documents, judged by reading, against the ten §6.3 families.**

§6.3's families were designed from expectation. B0 (`docs/PDF_API_NOTES.md`)
tested three documents and found zero family matches; this census widens that
to twenty chosen to span shapes rather than sampled at random, and separates
two questions the earlier work conflated:

1. **Does the document enumerate fundable subdivisions at all?** — judged by
   reading the document, not by running a regex over it.
2. **If so, does a family match?** — measured by running the real segmenter
   through production's own `extract_containers()`.

| Field | Value |
|---|---|
| Date | 2026-08-16 |
| Documents | 20 (18 PDF, 2 HTML), all from `data/document_evidence.json` |
| Segmenter | `scripts/subtopic_segmentation.py` at commit `248925d` |
| Families | ten, `scripts/subtopic_patterns.py`, unmodified |

## Headline

> **12 of 20 documents enumerate fundable subdivisions.**
> **A family identifies the right list in 1 of those 12.**
> **The segmenter produces subtopics for 0 of them.**

The denominator that matters is **12**, not 20. The eight that enumerate
nothing are correct zeroes and should never be counted against acceptance.

## ⚠ MURI is not in this corpus, and could not be

`MURI` appears **zero times** across all 958 evidence entries — no title, no
opportunity number, no description, no stored document text. This is not an
oversight in the sample; it is the deferral in §18.2 arriving:

> **SAM.gov adapter** (§7.5) — what is lost: *MURI specifically, and any
> SAM.gov-only notice.*

`dod_topic` is the family §6.3 lists as serving MURI. It therefore has **no
MURI document validating it**. It is, however, the one family this census
found working correctly — on an AFOSR DEPSCoR notice (`363526`), which uses
the identical `Topic N:` convention. So the family shape is validated; the
specific agency it was named for is not, and cannot be until SAM.gov ships.

## The table

`list?` = does the document enumerate fundable subdivisions, judged by reading.
`should` = the family that ought to claim it. `does` = what the segmenter did.

| # | id | Notice | Pages | list? | should match | does |
|---|---|---|---|---|---|---|
| 1 | `332894` | Army LQC BAA `W911NF21S0009` | 55 | **yes** — 6 Priority Research Thrusts | none — items are bare `1.)` | ✗ **false positive**: `roses_element`×3 on `A.1`/`E.1` section numbers |
| 2 | `343653` | DHAPP `W81XWH-22` | 219 | **yes** — 10 country FOAs | none — named, not numbered | ✗ no match |
| 3 | `345241` | Army DAC BAA `W911NF-23-S-0003` | 61 | no — topics live on an external website | — | ✓ correct zero |
| 4 | `352741` | NRL Long Range BAA | 114 | **yes** — per-Division research areas | none — named divisions | ✗ no match |
| 5 | `355867` | NIH `RFA-DA-25-024` (HTML) | — | no | — | ✓ correct zero |
| 6 | `356605` | ONR Long Range BAA | 74 | no — technology areas on ONR website | — | ✓ correct zero |
| 7 | `356623` | ARPA-E SCALEUP `DE-FOA-0003467` | 65 | **yes** — `CATEGORY 1:`–`CATEGORY 7:` | none — no `Category N` family | ✗ no match |
| 8 | `357305` | NIH `PAR-25-274` (HTML) | — | no | — | ✓ correct zero |
| 9 | `360261` | AFRL CHEERS `FA238424S2334` | 58 | no — **wrong attachment** (clauses list) | — | ✓ correct zero, wrong document |
| 10 | `360339` | CDC global health `jg-26-0054` | 70 | **yes** — Components 1–5 | none — no `Component N` family | ✗ no match |
| 11 | `360678` | **DOE Office of Science `DE-FOA-0003600`** | 224 | **yes** — full program taxonomy | none — hierarchical named + `(a)(b)(c)` | ✗ no match |
| 12 | `361526` | DOE Genesis Mission `DE-FOA-0003612` | 166 | **yes** — `1 - `, `2 - `, `3 – ` | none — bare `N - Title` | ✗ no match |
| 13 | `362005` | HUD PRO Housing | 107 | no — four goals, not fundable units | — | ✓ correct zero |
| 14 | `362329` | DHA PRMRP `HT942526PRMRPPCTA` | 57 | **yes** — portfolios × bulleted topic areas | `topic_area` by name only | ✗ bulleted, unnumbered |
| 15 | `362681` | AFOSR Open BAA `FA955026S0001` | 102 | **yes** — 39 named portfolios, 32 PM emails | none — named, not numbered | ✗ no match |
| 16 | `362711` | Army ARL NOFO `W911NF26S0085` | 30 | no — points to agency documents | — | ✓ correct zero |
| 17 | `362859` | DARPA MMoMA `HR001126S0013` | 22 | **yes** — Focus Area 1–4 | **`focus_area` — no such family** | ✗ missing family |
| 18 | `363065` | DOE NETL `DE-FOA-0003627` | 58 | **yes** — Topic Area 1a/1b/1c/2 | `topic_area` | ✗ **partial**: `1a`/`1b`/`1c` unmatched |
| 19 | `363489` | DARPA `HR001126S0016` | 18 | no — one technical area | — | ✓ correct zero |
| 20 | `363526` | AFOSR DEPSCoR-RC | 68 | **yes** — Topic 1–12 | `dod_topic` | ✓ **family correct**, ✗ rejected by acceptance |

**Yes-count: 12.** Correct family identified: **1/12** (`363526`). Subtopics
produced: **0/12**.

## Per-document notes where a list exists but no family matches

### The two that reached `best_family` and were rejected anyway

These are the most valuable rows in the table, because the failure is **not**
in the patterns.

**`363526` AFOSR DEPSCoR — `dod_topic` matched all 12 topics, twice.**

```
ACCEPTANCE FAILURES: ('ordinal_sequence', 'span_length')
ordinals    : [1,2,3,4,5,6,7,8,9,10,11,12, 1,2,3,4,5,6,7,8,9,10,11,12]
pages       : [4,4,4,4,4,4,4,4,4,4,4,4,    12,13,14,15,16,17,18,19,20,21,22,23]
span lengths: [143,122,135,120,133,126,127,144,121,125,231,15483, 3814,...,102719]
```

The first twelve are the **table of contents on page 4**; the second twelve are
the real headings on pages 12–23. Both sets enter the candidate list, so the
ordinal sequence runs 1→12 then drops back to 1, and the TOC spans are 120–230
characters — under the 200-character minimum. Two acceptance rules fire on what
is otherwise a textbook-perfect match.

**This is a segmenter defect, not a pattern gap**, and it has two parts:

- Layer D collects candidates from **every** container including TOC pages.
  §6.4 rule 6 rejects candidates *confined* to the TOC, but a set that mixes
  TOC and body passes rule 6 and then fails rules 2 and 3 instead.
- Layer B — which exists precisely for this document shape — computes its body
  cutoff as `max(page_start_offset(p) for p in toc_pages)`. That is the offset
  where the TOC page *begins*, so TOC candidates sit after it and survive the
  `offset > body_start` filter. It should be the offset where the last TOC page
  **ends**.

`detect_toc_pages` correctly identified page 4. The information needed to fix
this is already computed and simply not used. **Not fixed here** — this session
is C0–C3 and the fix belongs with package D's tuning, done against the whole
corpus. It is called out because it means package D's acceptance rate will read
**0%** until it is addressed, which will look like a pattern problem and is not.

**`363065` DOE NETL — `topic_area` matched only one of four topics.**

```
ordinals: [2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2]
```

The document's subdivisions are **Topic Area 1a, 1b, 1c and 2**. The family
pattern is `\bTopic\s+Area\s+(\d{1,2})\b`, and `\b` fails between `1` and `a`,
so `Topic Area 1a` does not match at all. Only `Topic Area 2` does, eleven
times, from prose mentions and the amendment log. This is a genuine **pattern**
gap: `sbir_subtopic` already models sub-lettered ordinals as `\d{1,2}[a-z]?`,
and `topic_area` does not. The inconsistency is not deliberate.

### Missing families, in frequency order

| Shape | Documents | Example |
|---|---|---|
| **Named subdivisions with a label** (no ordinal at all) | `362681`, `352741`, `360678`, `343653` | `Program Description:` × 39 with 32 program-manager emails (AFOSR) |
| **`Category N`** | `356623` | `CATEGORY 1:` … `CATEGORY 7:` |
| **`Component N`** | `360339` | `Component 1: Core Global Health Security Priorities` |
| **`Focus Area N`** | `362859` | `Focus Area 1: Integrated Materials Analysis` |
| **`N - Title`** (bare ordinal, dash) | `361526` | `2 - Scaling the Biotechnology Revolution` |
| **Bulleted topic areas under a named portfolio** | `362329` | `AUTOIMMUNE DISORDERS AND IMMUNOLOGY` → `• Celiac Disease` |

**The single largest gap is that every one of the ten families requires an
ordinal.** Four of the twelve enumerating documents — including the two richest,
AFOSR's 39 portfolios and DOE's Office of Science taxonomy — name their
subdivisions instead of numbering them. No amount of tuning to the existing
families reaches them; it needs a different recognizer keyed on a repeated
structural label (`Program Description:`, a program-manager email, a division
heading) rather than on a counter.

### False positives, which matter more than misses

`332894` matched `roses_element` three times on **`A.1 Funding Opportunity
Description`** and **`E.1 (Criteria)`** — ordinary DoD lettered-decimal section
numbering, not NASA ROSES elements. The pattern `^\s*([A-F])\.(\d{1,2})\s+(\S.*)$`
cannot distinguish them, and `A.`–`E.` section numbering is near-universal in
DoD BAAs.

Acceptance caught it. That is the design working — but it caught it via
`ordinal_sequence` and `span_length`, the same two rules that rejected the
*correct* match on `363526`. The rules are currently doing double duty as both
a precision filter and an accident, and only one of those is by design.

## What this changes

**§6.7 is wrong about the DOE Office of Science omnibus, and it is the most
consequential error in the plan for this user.** §6.7 states:

> the FOA does not enumerate research areas — it refers the reader to the
> program's own web pages … Segmentation cannot fix this, because the text
> genuinely is not there.

The text *is* there. `DE-FOA-0003600` carries **286 bookmarks** including a
complete program taxonomy:

```
III. Program Description
  A. Purpose
    1. Advanced Scientific Computing Research (ASCR)
      (a) Applied Mathematics
      (b) Computer Science
    2. Basic Energy Sciences (BES)
      (a) Materials Chemistry
      (b) Biomolecular Materials
      (c) Synthesis and Processing Science
      (d) Experimental Condensed Matter Physics
```

That is BES → sub-program granularity, in the notice, reachable by Layer A
today. §18.2 lists "the DOE BES omnibus gets no child records in v1" as "the
most painful single deferral in this table" and attributes it to needing a
web-scraping project (§6.7's `program_taxonomy` adapter). On this evidence a
large part of it needs a **pattern**, not a scraper. Recorded, not acted on —
but §6.7 and §18.2 should be revisited before package D commits to its scope.

**My own B0 conclusion was too strong.** `docs/PDF_API_NOTES.md` §4 reported
zero family matches on three notices and framed AFOSR and ONR as
outward-pointing umbrellas. That is right for ONR (`356605`, confirmed here:
technology areas live on a website) and **wrong for AFOSR** (`362681`), which
enumerates 39 portfolios with program managers in the document. B0 measured
family matching and described it as document shape. This census separates the
two, which is why it was worth doing before writing package C.

## Postscript: two things the C2 flag-on run added

The package C gate ran the real pipeline with `--enable-subtopics` against five
documents copied out of the cache. It surfaced two findings the census pass
could not.

**The best segmentation candidate in the corpus is unreachable by the fetch
path.** `363526` — the AFOSR DEPSCoR notice, the one document where a family
matches correctly — was staged for the run and never fetched.
`source_for_record()` returned `None` for it: its `primary_document_url` is
absent, its `funding_opportunity_url` is the generic `https://www.grants.gov/`,
and it needs no gap-fill because its close date and award range are already
populated. Its evidence entry exists and names a real attachment URL, so the
document *was* fetched at some earlier point and the record has since lost the
link. That entry is now effectively orphaned: it will never be rechecked and
can never be backfilled.

This is pre-existing behaviour, not something package C introduced, and fixing
it means changing `source_for_record`'s single-source contract — which §6.6
explicitly defers. But it bounds backfill coverage in a way §8.3 does not
mention: **a document is only reachable for segmentation if it still carries a
usable source on the parent record**, and an unknown number of the ~1,400
cached entries may be in the same state. Worth measuring before package D
reports an acceptance rate, because those documents will silently never appear
in the denominator at all.

**The end-to-end machinery is proven; the corpus is what yields nothing.** With
the flag on, five documents were fetched, segmented, and written to
`data/subtopic_records.json` with diagnostics populated:

```
documents_attempted: 5, documents_with_subtopics: 0, subtopic_record_count: 0
rejection_reasons: {"no_layer_accepted": 5}
```

Five `no_layer_accepted` results are exactly what this census predicts. The
same production call site, given a document that *does* enumerate, produces
three high-confidence records with titles, page spans, summaries, term maps and
both topic vocabularies — so the pipeline is not the thing that is broken. The
patterns and the TOC-duplication defect above are.

## Method

Documents were fetched from the attachment URLs already in
`data/document_evidence.json`, parsed through production's own
`extract_containers()`, and passed to `segment_document()` unmodified. The
`list?` column was judged by reading bookmark trees, section headings and the
neighbourhoods of enumeration cues — not by pattern matching, which is the
thing under test. Probe scripts are not committed, for the same reason as B0:
they are one-shot instruments against network-fetched documents, and the test
suite has no network path.
