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

## D2: the complete bookmark tree of `DE-FOA-0003600`

§6.7 left one question open — the census read 26 of 286 bookmarks, so whether
`Catalysis Science` is reachable *in the notice* was unverified, and that answer
decides how much of §18.2's `program_taxonomy` deferral survives. Package D
item D2 read all 286.

**286 destinations, maximum depth 3.** Nodes per level: **9 / 46 / 167 / 64**.

Level 0 is exactly the federal NOFO skeleton, which confirms §6.3a's
depth-0 exclusion empirically:

```
I. Basic Information            VI.   Application Review Information
II. Eligibility                 VII.  Award Notices
III. Program Description        VIII. Post-Award Requirements and Administration
IV. Application Contents        IX.   Other Information
V. Submission Requirements
```

**`(q) Catalysis Science` is present: level 2, page 46, parent `2. Basic Energy
Sciences (BES)`.** It is the only bookmark in the document matching `/catalys/i`.
BES carries **24 sub-programs** at that level:

```
(a) Materials Chemistry              (m) Gas Phase Chemical Physics
(c) Synthesis and Processing Science (o) Condensed Phase and Interfacial Molecular Science
(d) Experimental Condensed Matter    (q) Catalysis Science
(l) Atomic, Molecular, Optical       (r) Separation Science
                                     (u) Photochemistry and Radiation Chemistry
                                     (v) Photosynthetic Systems
```

So the answer to §6.7's open question is **yes** — the BES → program granularity
this project's user actually needs is in the PDF, at a citable page.

### What the tree also proves about §6.3a's selection rule

Grouping every sibling set of ≥3 by its **level-0 ancestor** separates the
document cleanly, and not the way §6.3a assumed:

| Level-0 ancestor | Sibling sets | Nodes |
|---|---|---|
| `III. Program Description` | 10 | **93** — the real taxonomy (BES 24, FES 14, NP 11, HEP 9, IRP 5, BER 4, ASCR 4, …) |
| All other sections | 23 | **159** — administrative (40 under *Administrative and National Policy Requirements*, 16 under *How-To Guides*, 14 form fields under *Research and Related Other Project Information*, 11 under *Component Pieces of the Application*) |

Three findings, each of which forced a change to §6.3a:

1. **The immediate-parent lexicon is too weak.** `C. Administrative and National
   Policy Requirements` matches no lexicon term, and neither do most of its 40
   children (*Availability of Funds*, *Buy America Preference*, *Conference
   Spending*). The **level-0 ancestor** catches all 23 administrative sets
   cleanly — structural, template-derived, and exactly the "primary exclusion is
   structural, not lexical" §6.3a asked for and then failed to deliver.
2. **"Deepest qualifying depth" selects the wrong level.** Under `III.`, level 3
   holds 3 nodes (`Multi-Institutional Teams`) and would beat level 2's 77.
   Selection must be **the admissible depth carrying the most nodes**.
3. **The 60-node cap forces the wrong granularity.** Level 2 under `III.` is 77
   nodes; level 1 is 16. At 60 the document yields 16 *program-office* children
   and `Catalysis Science` disappears into the BES span — losing precisely the
   record that motivated the whole §6.7 analysis.

## Package D results, measured against this census

Every figure below is a rate against the **12 enumerating documents**, never a
raw count, and the false-positive count on the **8 non-enumerating** documents
is reported separately because it matters more: a false positive publishes a
fabricated subtopic to a principal investigator, a miss publishes nothing.

| Stage | Acceptance | Wrong list | False positives |
|---|---|---|---|
| Baseline (start of package D) | **0/12 = 0%** | 0 | 0/8 |
| + D0a Layer B body cutoff | 0/12 = 0% | 0 | 0/8 |
| + D0c final-span cap | **1/12 = 8%** | 0 | 0/8 |
| + D0b Layer C/D TOC exclusion | 1/12 = 8% | 0 | 0/8 |
| + D1 `structural_siblings` | **3/12 = 25%** | 0 | 0/8 |
| + D3 census-named families | **5/12 = 42%** | 0 | 0/8 |

**Of the 5 accepted, only 3 would publish.** `356623` and `362859` resolve at
Layer D, which is low confidence, and low confidence never publishes (§6.2
Layer D, §13). The figure the package D gate cares about — "zero
low-confidence records in the published set" — is therefore **3/12 = 25%**.

| Document | Result | Method | Confidence | Publishes |
|---|---|---|---|---|
| `363526` AFOSR DEPSCoR | 8 topics | `toc` | high | yes |
| `360678` DOE Office of Science | **70 subtopics inc. `(q) Catalysis Science` p46** | `outline_structural` | medium | yes |
| `361526` DOE Genesis Mission | 26 challenge areas | `outline_structural` | medium | yes |
| `356623` ARPA-E SCALEUP | 7 technical categories | `numbered` | low | **no** |
| `362859` DARPA MMoMA | 4 focus areas | `numbered` | low | **no** |

### The seven remaining misses, and why none is a tuning problem

| Document | Why it misses | Fixable by tuning? |
|---|---|---|
| `362681` AFOSR | 39 named portfolios, **zero bookmarks** | No — needs `label_run` (§6.3a), deferred with its risks stated |
| `343653` DHAPP | 11 bookmarks, **all at level 0** | No — §6.3a excludes depth 0 by construction |
| `352741` NRL LRBAA | 3 junk bookmarks; divisions are named in body prose | No — same shape as AFOSR |
| `332894` Army LQC | 6 thrusts written as bare `1.)` | Only by a generic numbered family — §6.3/§18.3 forbid it |
| `362329` DHA PRMRP | topic areas are **bulleted**, no ordinal, no outline | No mechanism covers this |
| `360339` CDC | `Component 1-5` matches, but the located occurrences are a **front-matter summary list**, spans 88-239 chars against a 200 minimum | Needs occurrence selection, not pattern work |
| `363065` DOE NETL | `Topic Area 1a/1b/1c/2` now matches, but 36 hits are prose mentions and amendment-log entries; ordinals read `1,2,1,1,1,…` | Needs heading-vs-mention discrimination |

Two of these — `360339` and `363065` — are the same underlying problem in
different clothes: **the pattern matches in several places and nothing chooses
which occurrence is the heading.** That is the next real mechanism, and it is
not a regex.

### Correct-acceptance, judged by reading every span

"Did it segment?" and "did it segment the right thing?" are different questions,
and ARPA-E SCALEUP proved it: before the D3 lexicon fix it segmented the 13
subsections of `H. Funding Restrictions` — *Allowable Costs*, *Foreign Travel*,
*Lobbying* — and a binary metric scored that as a success. Every accepted
document below was therefore re-scored by reading its spans.

| Document | Spans | Spans that are fundable subdivisions | Recall of the real list | Publishes |
|---|---|---|---|---|
| `363526` AFOSR DEPSCoR | 8 | **8** | 8 of 12 topics = 67% | yes (high) |
| `362859` DARPA MMoMA | 4 | **4** | 4 of 4 = 100% | no (low) |
| `356623` ARPA-E SCALEUP | 7 | **7** | 7 of 7 = 100% | no (low) |
| `360678` DOE Office of Science | 70 | **68** | 68 of 71 programmes = 96% | yes (medium) |
| `361526` DOE Genesis Mission | 26 | **21** | 21 of 21 challenge areas = 100% | yes (medium) |

> **Correct-acceptance rate: 5/12 = 42%.** Every accepted document found the
> right list. **Publishable correct-acceptance: 3/12 = 25%**, because `356623`
> and `362859` resolve at Layer D and low confidence never publishes.

**Span-level precision is 108/115 = 94%, and all seven bad spans are in the
publishable set.** They are not near-misses; they are administrative sections
that happen to be outline siblings of real topics:

| Document | Contaminating spans |
|---|---|
| `360678` | `Multi-Institutional Teams` (p118), `Open Science` (p120) |
| `361526` | `Annual Meetings` (p60), `Annual Progress Reports` (p60), `Teaming Arrangements` (p60), `Joint Consideration` (p62), `Open Science` (p62) |

Neither the §6.3a set-level veto nor the lexicon caught them: 5 of 26 is 19%,
under the 25% threshold, and `Annual Progress Reports` does not match the term
`reporting`. **Seven cards titled *Annual Progress Reports* and *Open Science*
would reach a principal investigator with a page anchor**, which is §18.3's harm
at small scale. This is a precision defect in `structural_siblings`, recorded
and not fixed.

### `DE-FOA-0003612` — Genesis Mission, in census format

The highest-value document in the corpus: a **live, open** opportunity, not an
archival test case.

| Field | Value |
|---|---|
| Opportunity number | `DE-FOA-0003612` |
| Title | The Genesis Mission: Transforming Science and Energy with AI |
| Agency / status | Office of Science · **posted** |
| Closes | **2026-12-17** (archive 2027-03-17) |
| Evidence id | `361526` |
| Notice | `DE-FOA-0003612.000003.pdf`, 166 pages, 1,321,107 bytes |
| URL | live, `apply07.grants.gov/…/att/download/350588` |
| Outline | 240 bookmarks |

**Published ground truth: 21 challenge areas, drawn from 26 national
challenges, reported elsewhere as 99 focus areas.**

| Against | Spans | Result |
|---|---|---|
| **21 challenge areas** | 21 | **21/21 = 100% recall, exact** — spans 1–21 are the numbered challenge areas, `1 - Reenvisioning Advanced Manufacturing` through `21 - Artificial Intelligence in Fluid Flow for Energy Components` |
| **99 focus areas** | 0 | **0/99 = 0%.** The focus areas sit one level below the challenge areas and are not bookmarked, so `structural_siblings` cannot see them. The segmenter operates at challenge-area granularity |
| Precision | 26 emitted | **21/26 = 81%** — spans 22–26 are the five administrative siblings listed above |

So on the single most valuable document the layer recovers the *entire*
published challenge-area list exactly, at the wrong granularity for focus areas,
with five spurious cards. The 99-focus-area level would need either a deeper
bookmark tree than the notice has, or the occurrence-selection mechanism the
misses below also need.

### The seven misses, one line each

| Document | Cause | Category |
|---|---|---|
| `362681` AFOSR Open BAA | 39 named portfolios with **zero bookmarks**; `structural_siblings` needs an outline tree | **missing family shape** — `label_run`, deferred in §6.3a |
| `352741` NRL LRBAA | Divisions named in body prose; only 3 junk bookmarks | **missing family shape** — same `label_run` gap |
| `362329` DHA PRMRP | Topic areas are **bulleted** under named portfolios, no ordinal and no outline depth | **missing family shape** |
| `332894` Army LQC | Six Priority Research Thrusts written as bare `1.)` | **missing family shape**, and the only family that would catch it is the generic numbered one §6.3/§18.3 forbid |
| `343653` DHAPP | Ten country FOAs are real fundable subdivisions but sit at **outline depth 0**, which §6.3a excludes by construction | **acceptance rule rejecting something legitimate** |
| `360339` CDC | `Component 1-5` matches, but the located occurrences are a front-matter summary list — spans 88–239 chars against a 200 floor | **known defect** — occurrence selection |
| `363065` DOE NETL | `Topic Area 1a/1b/1c/2` now matches, but 36 hits are prose mentions and amendment-log entries; ordinals read `1,2,1,1,1,…` | **known defect** — occurrence selection |

**Four of seven are one missing mechanism** (`label_run` for named subdivisions,
plus the bulleted variant). **Two are one known defect** — the pattern matches in
several places and nothing decides which occurrence is the heading, the same
class of bug as the table-of-contents duplication fixed in D0a/D0b. **One is an
acceptance rule refusing a legitimate list.** Only `332894` would need the
forbidden loosening.

That distribution is the answer to whether more tuning is worth it: **more
regexes buy almost nothing.** Two mechanisms — label runs and occurrence
selection — would address six of the seven.

### Two reachability findings

- **`363526` is orphaned.** The one high-confidence acceptance in the corpus
  cannot be reached by the production fetch path: its parent record has no
  `primary_document_url` and needs no gap-fill, so `source_for_record()` returns
  `None`. It segments when handed the bytes and **would never be handed them by
  the nightly**.
- **`360339` has left the catalog** since the census was taken, so one of the
  twelve enumerating documents is no longer a live record at all.

### The stop

**42% acceptance is below the 50% threshold set for this package, so tuning
stopped here rather than continuing.** Every remaining miss needs either a new
mechanism (`label_run`, occurrence selection) or a generic numbered-section
family, and §6.3 and §18.3 both name that last one as the most damaging change
available to this design — the one that manufactures subtopics titled *Federal
Agency Name*. Loosening to reach an arbitrary number would trade the metric
that matters (0 false positives) for the metric that does not.

**The strongest evidence that the discipline is working is the zero.** Across
five layers of change and four new families, no non-enumerating document ever
produced a subtopic, and the one wrong-list acceptance that did appear — ARPA-E
SCALEUP returning `Allowable Costs`, `Foreign Travel` and `Lobbying` from
`H. Funding Restrictions` — was caught only because the harness checks *which*
list was found rather than *whether* one was. A binary metric scored that
fabrication as a success.

## Attachment inventory — the assumption the census inherited

§6.6 requires segmenting every attachment on a record. `source_for_record()`
returns exactly one, and this census was built on whatever that one was. **No
secondary attachment had ever been opened.** All 62 were enumerated from the
live `fetchOpportunity` responses.

> **62 attachments across the 20 records. 12 of 20 carry more than one.
> Only 8 are genuinely single-attachment.**

The one-source assumption is therefore wrong for **60% of the corpus**, and the
census's per-document judgments were made against a fraction of each record.

| Record | Attachments | Segmented | Notable secondaries |
|---|---|---|---|
| `332894` Army LQC | 5 | `LQC BAA W911NF-21-S-0009-3.pdf` | 3 older BAA versions + a Special Notice |
| `343653` DHAPP | 2 | main PDF | `FY27 SOW_New Award_YR1.xlsx` |
| `345241` Army DAC | 1 | main PDF | — |
| `352741` NRL LRBAA | 3 | `FY24 BAA Announcement FINAL.pdf` | **`Amendment 0004.pdf` — see below** |
| `355867` NIH | 1 | 429-byte HTML stub | — |
| `356605` ONR LRBAA | **9** | base BAA | Amendments 0001–0007, none carrying topics |
| `356623` ARPA-E | 1 | main NOFO | — |
| `357305` NIH | **0** | — | not in the Grants.gov attachment system at all |
| `360261` AFRL CHEERS | 2 | **the clauses list** | `Open Period Solicitation 1_BAA Amend 01.pdf` |
| `360339` CDC | 2 | main PDF | M&E indicator list |
| `360678` DOE Office of Science | 1 | main NOFO | — |
| `361526` **Genesis Mission** | **5** | `DE-FOA-0003612.000003.pdf` | **3 `.xlsx` templates — see below** |
| `362005` HUD | 1 | main PDF | — |
| `362329` DHA PRMRP | 1 | main PDF | — |
| `362681` AFOSR | 4 | main BAA | Appendices 1–2 (security/privacy), AFRL addendum |
| `362711` Army ARL | 1 | main PDF | — |
| `362859` DARPA MMoMA | 4 | main BAA | proposal templates (`.docx`, `.pptx`) |
| `363065` DOE NETL | 5 | `Amd_000003` | **`NOFO_Part_2.pdf` — checked, see below** |
| `363489` DARPA | **10** | main BAA | 9 proposal/cost templates |
| `363526` AFOSR DEPSCoR | 4 | main NOFO | Amendment 1, Appendices 1–2 |

Three secondaries were fetched and segmented. Two changed nothing; one changed a
verdict.

**`363065` — `DE-FOA-0003627_NOFO_Part_2.pdf` (1.85 MB, 49 pages): not a topic
document.** It says so itself: *"Part 2 includes fixed DOE requirements that
generally do not change from NOFO to NOFO."* Zero mentions of `Topic Area N`,
zero bookmarks, `no_layer_accepted`. This record's topic areas really are in
Part 1, drowned in prose mentions — its classification stands.

**`352741` — `N00173-24-S-BA01 Amendment 0004.pdf` (1.18 MB, 49 pages): this is
where the topic list lives.** The amendment's own purpose line reads *"revise
Appendix 1 in it's entirety"*, and Appendix 1 is `RESEARCH DESCRIPTION -
SUMMARY TOPICS`. It contains **32 numbered NRL research topics with 25 distinct
per-topic contact mailboxes**, organized under four directorates:

```
A.  SYSTEMS DIRECTORATE - CODE 5000
    53-24-01  - HIGH FREQUENCY RADAR
    53-24-01C - HIGH FREQUENCY RADAR (CLASSIFIED)
    53-24-02  - LOW-COST WIDEBAND ANTENNA ARRAY TECHNOLOGIES
    55-24-01  - INFORMATION AND DECISION SCIENCES
    ...
    82-24-01  - SPACECRAFT & SPACE SYSTEMS TECHNOLOGY
```

The primary notice the census judged contains none of this. **`352741` is not a
pattern failure at all — it is a fetch-scope failure**, and it segments nothing
today because the file holding its topics is never downloaded.

## `DE-FOA-0003612` — where the 99 focus areas actually are

All five attachments, from the live API:

| # | File | Size | Type |
|---|---|---|---|
| 1 | `DE-FOA-0003612.000003.pdf` | 1,321,107 B | PDF — **the one segmented**, folder *Full Announcement* |
| 2 | `Sample OT and Project Agreements … REV2.pdf` | 1,346,203 B | PDF — legal templates |
| 3 | **`Genesis Mission Phase I Application Template v2.xlsx`** | 28,058 B | **spreadsheet** |
| 4 | **`Genesis Mission Phase II Application Template.xlsx`** | 35,219 B | **spreadsheet** |
| 5 | `Genesis Mission Phase II LOI Template v2.xlsx` | 26,515 B | spreadsheet |

**The 21 challenge areas are in attachment 1**, as bookmarks under
`III. Program Description → A. Purpose`, and segmentation recovers all 21
exactly.

**The focus areas are in attachments 3 and 4, in a worksheet named
`Focus Areas`** — the dropdown source list the applicant selects from on the
`Phase I Summary` sheet (`Focus Area | Select from dropdown menu`).

> **The count is 98, not 99.** The sheet is `A1:A99`: one header cell reading
> `Topics`, then **98 focus areas**. The widely reported "99" is the row count.

They are coded `<challenge>-<letter>`, and every one of the 21 challenges is
represented:

```
1-A  Reenvisioning Advanced Manufacturing and Industrial Productivity | Agentic AI-Driven Chemical Manufacturing
1-B  Reenvisioning Advanced Manufacturing and Industrial Productivity | AI-Driven Materials Processing
…
21-C Artificial Intelligence in Fluid Flow for Energy Components and Technologies | Data-Driven Operational Intelligence
```

Focus areas per challenge range from **2** (challenges 10, 13) to **10**
(challenge 9), totalling 98 across 21.

**No mechanism in the plan or on the deferred list reaches them.** Three
independent barriers, and all three would have to fall:

1. `source_for_record()` returns one attachment; §6.6 defers multi-attachment
   fetch explicitly.
2. `extract_containers()` dispatches on `pdf`, `html` and `text` only — a
   spreadsheet produces no containers, so there is nothing to segment even if it
   were fetched. (`openpyxl` is already a runtime dependency for other scripts,
   so this is a dispatch gap, not a dependency one.)
3. The content is a **dropdown source list**, not prose — there are no spans to
   summarize, only cell values to read.

This matters because the notice permits **one application per focus area**, so
the focus area, not the challenge area, is the unit a PI applies against. The
layer currently exposes the 21 and cannot see the 98.

## Classifying every miss

Six categories, one line each.

| Miss | Cause | Category |
|---|---|---|
| `332894` Army LQC | Six thrusts bookmarked as `1.) Spin qubits, fast.` — a bare ordinal no family covers, and at outline depth 0 besides | **(b)** no family shape |
| `362329` DHA PRMRP | Topic areas are bullets under a named portfolio heading, with no ordinal anywhere | **(b)** no family shape |
| `362681` AFOSR | Portfolios coded `A.1.a.`, `A.1.b.`, `A.1.c.` followed by `Program Description:` — no family matches that form, and the document has zero bookmarks | **(b)** no family shape |
| `343653` DHAPP | Ten country FOAs are correctly bookmarked but sit at **outline depth 0**, which §6.3a excludes by construction | **(c)** acceptance rule rejected a legitimate list |
| `360339` CDC | `Component 1-5` matched cleanly; the located occurrences are a front-matter summary list, spans 88–239 chars against a 200 floor | **(d)** known defect — occurrence selection |
| `363065` DOE NETL | `Topic Area 1a/1b/1c/2` matched 36 times, but the hits are prose mentions and amendment-log entries; ordinals read `1,2,1,1,1,…` | **(d)** known defect — occurrence selection |
| `352741` NRL | 32 topics with 25 contact mailboxes live in `Amendment 0004.pdf`, which is never fetched | **(f)** list in a different attachment |

> **(a) 0 · (b) 3 · (c) 1 · (d) 2 · (e) 0 · (f) 1**

**No census judgment was wrong.** Every one of the twelve documents the census
called enumerating does enumerate — the reading was sound, and category (a) is
empty. That is worth stating because it means the 42% is a mechanism gap, not a
measurement artifact.

Separately, **`363526` is an (e) case that is not a miss**: it segments
correctly at high confidence and is unreachable by the nightly.

### The shapes, quoted

**`332894` — bare `N.)` ordinals, at depth 0:**
```
A.1.1 LPS Qubit Collaboratory Priority Research Thrusts (FY 2021)
1.) Spin qubits, fast.
2.) More epitaxy, better qubits?
3.) Voltage controllable superconducting qubits
4.) Going hot and not looking back
5.) Beyond Moore, Before Shor
6.) Accelerated Learning of Quantum Information Concepts
```

**`362681` — `A.1.a.` codes plus a repeated label, no bookmarks:**
```
A.1.a. Energetic Solid-State Physics and Mechanochemistry
Program Description: The objective of this portfolio is to understand critical…
A.1.b. Energy, Combustion and Non-Equilibrium Thermodynamics
Program Description: Majority of Air and Space Forces' system functions rely on…
A.1.c. Aerodynamic Sciences
Program Description: The Aerodynamic Sciences portfolio supports basic research…
```
An earlier version of this census described these as "39 named portfolios" with
no ordinal. **That was wrong** — they carry a hierarchical `A.1.a.` code, which
is a far more tractable shape than "named", and `label_run` may not even be the
right mechanism for them.

**`362329` — bulleted, under a named portfolio:**
```
AUTOIMMUNE DISORDERS AND IMMUNOLOGY
All applications under this portfolio must be aligned to Autoimmune Disorders and
Immunology by addressing one topic area and one strategic goal listed below.
TOPIC AREAS
• Celiac Disease
• Eczema
• Food Allergies
• Inflammatory Bowel Disease
```

**`343653` — legitimate list, rejected by the depth-0 rule:**
```
L0 p 26  Angola_FOA_COP26_FY27_Final
L0 p 45  Burundi_FOA_COP26_FY27_Final
L0 p 63  Ethiopia_FOA_COP26_FY27_Final
…
L0 p197  Uganda_FOA_COP26_FY27_Final
```

## The denominator, re-derived against the live catalog

The frozen 20 has drifted, in both directions.

| | Census | Still in catalog | Reachable by the nightly |
|---|---|---|---|
| Enumerating | 12 | **11** (`360339` gone) | **10** (`363526` orphaned) |
| Non-enumerating | 8 | **6** (`362005`, `362711` gone) | 6 |

> **The correct denominator is 10, not 12**, and the false-positive denominator
> is **6, not 8**.

Restating the package D result against it:

| Metric | Against 12 | **Against 10 reachable** |
|---|---|---|
| Correct-acceptance | 5/12 = 42% | **4/10 = 40%** (`363526` is unreachable) |
| Publishable **and** reachable | 3/12 = 25% | **2/10 = 20%** — only `360678` and `361526` |
| False positives | 0/8 | **0/6** |

Three of twenty census records left the catalog within a day of the census being
taken. Any future acceptance rate should be re-derived at the time it is quoted
rather than compared against a figure from a previous session.

## §11 — the deferred AI layer, assessed against these causes

§11 constrains the model tightly: it *"would only label and summarize spans
deterministic segmentation already located"*, and *"does not do: discover
topics."*

Applying that constraint to the seven misses:

| Category | Misses | Spans located for a model to label | Reachable by §11? |
|---|---|---|---|
| **(b)** no family shape | 3 | **zero** — nothing matched | No |
| **(c)** rule rejected | 1 | zero emitted | No |
| **(d)** known defect | 2 | candidates located, then rejected | No — adjudicating a rejected set *is* discovery |
| **(f)** wrong attachment | 1 | zero — file never fetched | No |

> **An LLM labeler under §11's constraint reaches 0 of 7 misses.**

The result is not close, and the reason is structural rather than a matter of
model quality: **in six of the seven, segmentation located no spans at all**, so
there is nothing for a labeler to label. In the remaining two, candidates were
located and then rejected by acceptance — and having a model overturn that
rejection is precisely the "discover topics" role §11 forbids, because the model
would be deciding *whether a list exists*, not describing one that does.

**This closes §11 rather than deferring it further.** It was recorded as polish —
"cleaner human-readable summaries, normalized dates, consistent phrasing" — and
that assessment is confirmed: it is polish, the misses are mechanism, and polish
does not fix mechanism. Two narrower uses survive and are worth noting when §11
is revisited:

- **Filtering the seven contaminating spans.** A model shown `Open Science` and
  `Annual Progress Reports` alongside `Catalysis Science` would plausibly reject
  the first two. That is *classification of located spans*, squarely inside
  §11's constraint, and it addresses the precision defect rather than the recall
  gap.
- **Reading the Genesis `Focus Areas` sheet.** Nothing about that requires a
  model — it needs a spreadsheet reader.

## Method

Documents were fetched from the attachment URLs already in
`data/document_evidence.json`, parsed through production's own
`extract_containers()`, and passed to `segment_document()` unmodified. The
`list?` column was judged by reading bookmark trees, section headings and the
neighbourhoods of enumeration cues — not by pattern matching, which is the
thing under test. Probe scripts are not committed, for the same reason as B0:
they are one-shot instruments against network-fetched documents, and the test
suite has no network path.
